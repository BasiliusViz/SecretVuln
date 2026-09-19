import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db
from app.models import Finding
from app.models.finding import FindingStatus, Severity
from app.models.finding_event import FindingEvent
from app.schemas.finding import FindingRead
from app.schemas.finding_event import FindingEventRead

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


@router.patch("/findings/{finding_id}", response_model=FindingRead)
async def update_finding_status(
    finding_id: uuid.UUID,
    new_status: FindingStatus = Query(..., alias="status"),
    _: object = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> Finding:
    finding = await db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    finding.status = new_status
    await db.commit()
    await db.refresh(finding)
    return finding
