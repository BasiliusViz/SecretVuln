"""Выводы ИИ: читать — `finding:read`, писать — `finding:analyze`, рассматривать — `finding:triage`.

Принятие вывода статус находки не меняет: человек меняет его обычным путём,
передав `ai_analysis_id` — ссылка остаётся в событии истории.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, ensure, get_current_principal, not_found, require_permission
from app.api.findings import finding_checked
from app.core.config import get_settings
from app.db.session import get_db
from app.models import AiAnalysis, Entity, Finding
from app.schemas.ai_analysis import AiAnalysisCreate, AiAnalysisRead, AiAnalysisReview
from app.services.ai_analyses import (
    AnalysisError,
    create_analysis,
    list_analyses,
    review_analysis,
)
from app.services import audit

router = APIRouter(prefix="/api/v1", tags=["ai-analyses"])


async def _reload(db: AsyncSession, analysis_id: uuid.UUID) -> AiAnalysis:
    return await db.scalar(
        select(AiAnalysis)
        .where(AiAnalysis.id == analysis_id)
        .execution_options(populate_existing=True)
    )


@router.get("/findings/{finding_id}/analyses", response_model=list[AiAnalysisRead])
async def get_analyses(
    finding_id: uuid.UUID,
    principal: Principal = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[AiAnalysis]:
    finding = await finding_checked(db, principal, finding_id, "finding:read")
    return await list_analyses(db, finding.id)


@router.post("/findings/{finding_id}/analyses", response_model=AiAnalysisRead, status_code=201)
async def submit_analysis(
    finding_id: uuid.UUID,
    data: AiAnalysisCreate,
    principal: Principal = Depends(require_permission("finding", "analyze")),
    db: AsyncSession = Depends(get_db),
) -> AiAnalysis:
    finding = await finding_checked(db, principal, finding_id, "finding:analyze")
    analysis = await create_analysis(db, finding, data, principal.user)
    await db.commit()
    return await _reload(db, analysis.id)


@router.post("/analyses/{analysis_id}/review", response_model=AiAnalysisRead)
async def review(
    analysis_id: uuid.UUID,
    data: AiAnalysisReview,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> AiAnalysis:
    analysis = await db.get(AiAnalysis, analysis_id)
    if analysis is None:
        raise not_found("Вывод ИИ")
    finding = await db.get(Finding, analysis.finding_id)
    entity = await db.get(Entity, finding.entity_id)
    ensure(principal, "finding:triage", entity, what="Вывод ИИ")
    try:
        await review_analysis(db, analysis, principal.user, data.decision == "accept", data.comment)
    except AnalysisError as e:
        raise HTTPException(e.status_code, e.detail)
    await db.commit()
    return await _reload(db, analysis.id)


@router.post("/findings/{finding_id}/ai-triage", status_code=202)
async def request_ai_triage(
    finding_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_permission("finding", "analyze")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Разбор встроенным ИИ — в очередь, всегда (повторный разбор тоже)."""
    finding = await finding_checked(db, principal, finding_id, "finding:analyze")
    if not get_settings().ai_enabled:
        raise HTTPException(503, "Встроенный ИИ не настроен")
    entity = await db.get(Entity, finding.entity_id)
    audit.record_audit(
        db, principal.user, audit.AI_TRIAGE_REQUEST,
        target=("finding", finding.id, f"SV-{finding.number}"),
        entity=entity, ip=audit.client_ip(request),
    )
    await db.commit()
    from app.worker import enqueue_ai_triage

    await enqueue_ai_triage(str(finding.id))
    return {"queued": True}


@router.get("/ai/status")
async def ai_status(principal: Principal = Depends(get_current_principal)) -> dict:
    settings = get_settings()
    enabled = settings.ai_enabled
    return {"enabled": enabled, "model": (settings.ai_model or None) if enabled else None}
