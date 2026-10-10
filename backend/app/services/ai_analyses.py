"""Выводы ИИ по находкам. Статус находки здесь не меняется никогда."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiAnalysis, AiAnalysisKind, AiReviewStatus, Finding, User
from app.schemas.ai_analysis import AiAnalysisCreate


class AnalysisError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


async def refresh_ai_verdict(db: AsyncSession, finding_id: uuid.UUID) -> None:
    """`findings.ai_verdict` — вердикт последнего неотклонённого вывода «triage»."""
    latest = (
        select(AiAnalysis.verdict)
        .where(
            AiAnalysis.finding_id == finding_id,
            AiAnalysis.kind == AiAnalysisKind.triage,
            AiAnalysis.review_status != AiReviewStatus.rejected,
        )
        .order_by(AiAnalysis.created_at.desc(), AiAnalysis.id.desc())
        .limit(1)
    )
    # через ORM, а не UPDATE: объект находки в сессии остаётся загруженным.
    finding = await _lock_finding(db, finding_id)
    finding.ai_verdict = await db.scalar(latest)
    await db.flush()


async def _lock_finding(db: AsyncSession, finding_id: uuid.UUID) -> Finding:
    """Блокировка находки: параллельные выводы пересчитывают вердикт по очереди.

    FOR NO KEY UPDATE, а не FOR UPDATE: вставка в `ai_analyses` берёт по внешнему ключу
    KEY SHARE на находку, и FOR UPDATE с ним взаимно блокировался бы у двух агентов.
    """
    return await db.get(Finding, finding_id, with_for_update={"key_share": True})


async def list_analyses(db: AsyncSession, finding_id: uuid.UUID) -> list[AiAnalysis]:
    rows = await db.scalars(
        select(AiAnalysis)
        .where(AiAnalysis.finding_id == finding_id)
        .order_by(AiAnalysis.created_at.desc(), AiAnalysis.id.desc())
    )
    return list(rows)


async def create_analysis(
    db: AsyncSession, finding: Finding, data: AiAnalysisCreate, author: User
) -> AiAnalysis:
    # блокируем до вставки: вторая транзакция ждёт здесь, а не после своего INSERT
    await _lock_finding(db, finding.id)
    analysis = AiAnalysis(
        finding_id=finding.id,
        created_by=author.id,
        review_status=AiReviewStatus.pending,
        **data.model_dump(),
    )
    db.add(analysis)
    await db.flush()
    await refresh_ai_verdict(db, finding.id)
    return analysis


async def review_analysis(
    db: AsyncSession, analysis: AiAnalysis, reviewer: User, accept: bool, comment: str | None
) -> AiAnalysis:
    if analysis.review_status != AiReviewStatus.pending:
        raise AnalysisError(409, "Вывод уже рассмотрен")
    if analysis.created_by == reviewer.id:
        raise AnalysisError(403, "Нельзя рассматривать собственный вывод")
    analysis.review_status = AiReviewStatus.accepted if accept else AiReviewStatus.rejected
    analysis.reviewed_by = reviewer.id
    analysis.reviewed_at = datetime.now(timezone.utc)
    analysis.review_comment = (comment or "").strip() or None
    await db.flush()
    await refresh_ai_verdict(db, analysis.finding_id)
    return analysis


async def analysis_of_finding(
    db: AsyncSession, analysis_id: uuid.UUID | None, finding_id: uuid.UUID
) -> AiAnalysis | None:
    """Ссылка `ai_analysis_id` при смене статуса: принятый вывод этой же находки."""
    if analysis_id is None:
        return None
    analysis = await db.get(AiAnalysis, analysis_id)
    if analysis is None or analysis.finding_id != finding_id:
        raise AnalysisError(400, "Вывод ИИ не найден у этой уязвимости")
    if analysis.review_status != AiReviewStatus.accepted:
        raise AnalysisError(400, "Сослаться можно только на принятый вывод ИИ")
    return analysis
