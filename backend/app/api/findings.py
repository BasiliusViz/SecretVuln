import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, has_permission, require_permission
from app.db.session import get_db
from app.models import Finding
from app.models.finding import FindingStatus, Severity
from app.models.finding_event import ActorType, FindingEvent, FindingEventType
from app.schemas.finding import FindingRead, FindingStatusUpdate
from app.schemas.finding_event import FindingEventRead
from app.services.events import record_event

router = APIRouter(prefix="/api/v1", tags=["findings"])


@router.get("/findings", response_model=list[FindingRead])
async def list_findings(
    entity_id: uuid.UUID | None = None,
    severity: Severity | None = None,
    finding_status: FindingStatus | None = Query(None, alias="status"),
    scanner: str | None = None,
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    _: object = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[Finding]:
    q = select(Finding)
    if entity_id:
        q = q.where(Finding.entity_id == entity_id)
    if severity:
        q = q.where(Finding.severity == severity)
    if finding_status:
        q = q.where(Finding.status == finding_status)
    if scanner:
        q = q.where(Finding.scanner == scanner)
    q = q.order_by(Finding.last_seen.desc()).offset(offset).limit(limit)
    result = await db.scalars(q)
    return list(result)


@router.get("/findings/stats")
async def findings_stats(
    entity_id: uuid.UUID | None = None,
    _: object = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    q = select(Finding.severity, func.count()).group_by(Finding.severity)
    if entity_id:
        q = q.where(Finding.entity_id == entity_id)
    rows = (await db.execute(q)).all()
    by_severity = {sev.value: cnt for sev, cnt in rows}

    q2 = select(Finding.status, func.count()).group_by(Finding.status)
    if entity_id:
        q2 = q2.where(Finding.entity_id == entity_id)
    rows2 = (await db.execute(q2)).all()
    by_status = {st.value: cnt for st, cnt in rows2}

    total = sum(by_severity.values())
    return {"total": total, "by_severity": by_severity, "by_status": by_status}


@router.get("/findings/by-number/{number}", response_model=FindingRead)
async def get_finding_by_number(
    number: int,
    _: object = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> Finding:
    finding = await db.scalar(select(Finding).where(Finding.number == number))
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    return finding


@router.get("/findings/{finding_id}", response_model=FindingRead)
async def get_finding(
    finding_id: uuid.UUID,
    _: object = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> Finding:
    finding = await db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    return finding


@router.get("/findings/{finding_id}/events", response_model=list[FindingEventRead])
async def list_finding_events(
    finding_id: uuid.UUID,
    _: object = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[FindingEvent]:
    if await db.get(Finding, finding_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    result = await db.scalars(
        select(FindingEvent)
        .where(FindingEvent.finding_id == finding_id)
        .order_by(FindingEvent.created_at, FindingEvent.id)
    )
    return list(result)


# Ставятся вручную. Ложное/риск — через запросы (decisions), «Исправлена» — только повторным сканом.
MANUAL_STATUSES = {
    FindingStatus.new,
    FindingStatus.triaged,
    FindingStatus.confirmed,
    FindingStatus.in_progress,
}
DECISION_STATUSES = {FindingStatus.false_positive, FindingStatus.risk_accepted}


@router.patch("/findings/{finding_id}", response_model=FindingRead)
async def update_finding_status(
    finding_id: uuid.UUID,
    data: FindingStatusUpdate,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> Finding:
    finding = await db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")

    if data.status in DECISION_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "«Ложное срабатывание» и «Риск принят» оформляются запросом: "
            f"POST /api/v1/findings/{finding_id}/decisions",
        )
    if data.status not in MANUAL_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "«Исправлена» ставится автоматически, когда повторный скан не находит уязвимость",
        )
    if finding.status in DECISION_STATUSES and not has_permission(principal, "finding", "approve"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Снять решение может только AppSec (право finding:approve)"
        )

    if finding.status != data.status:
        previous = finding.status
        finding.status = data.status
        record_event(
            db, finding.id, FindingEventType.status_changed,
            actor_type=ActorType.user, actor_id=principal.user.id,
            from_status=previous, to_status=data.status,
            reason=(data.reason or "").strip() or None,
        )
        await db.commit()
        await db.refresh(finding)
    return finding
