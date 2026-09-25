import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, has_permission, require_permission
from app.db.session import get_db
from app.models import Entity, Finding, User, UserGroup
from app.models.finding import FindingStatus, Severity
from app.models.finding_event import ActorType, FindingEvent, FindingEventType
from app.schemas.finding import FindingAssign, FindingRead, FindingStatusUpdate
from app.schemas.finding_event import FindingEventRead
from app.services.entity_paths import subtree_ids
from app.services.events import record_event
from app.services.ownership import build_resolver

router = APIRouter(prefix="/api/v1", tags=["findings"])


async def _entity_filter(db: AsyncSession, entity_id: uuid.UUID, include_descendants: bool):
    """Условие на Finding.entity_id: сам проект или всё его поддерево."""
    if not include_descendants:
        return Finding.entity_id == entity_id
    entity = await db.get(Entity, entity_id)
    if entity is None:
        return Finding.entity_id == entity_id  # пустой результат
    return Finding.entity_id.in_(subtree_ids(entity))


async def load_finding(db: AsyncSession, finding_id: uuid.UUID) -> Finding:
    """Перечитать находку вместе с командой/исполнителем (selectin) — для ответа после изменений."""
    return await db.scalar(
        select(Finding).where(Finding.id == finding_id).execution_options(populate_existing=True)
    )


@router.get("/findings", response_model=list[FindingRead])
async def list_findings(
    entity_id: uuid.UUID | None = None,
    include_descendants: bool = False,
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
        q = q.where(await _entity_filter(db, entity_id, include_descendants))
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
    include_descendants: bool = False,
    _: object = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    scope = await _entity_filter(db, entity_id, include_descendants) if entity_id else None
    q = select(Finding.severity, func.count()).group_by(Finding.severity)
    q2 = select(Finding.status, func.count()).group_by(Finding.status)
    if scope is not None:
        q = q.where(scope)
        q2 = q2.where(scope)
    by_severity = {sev.value: cnt for sev, cnt in (await db.execute(q)).all()}
    by_status = {st.value: cnt for st, cnt in (await db.execute(q2)).all()}
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
    return await load_finding(db, finding.id)


@router.post("/findings/{finding_id}/assign", response_model=FindingRead)
async def assign_finding(
    finding_id: uuid.UUID,
    data: FindingAssign,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> Finding:
    finding = await db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")

    if data.by_rules:
        new_group = (await build_resolver(db, finding.entity_id)).resolve(finding.file_path)
        finding.assigned_manually = False
        finding.assignee_user_id = None
    else:
        if data.group_id is not None and await db.get(UserGroup, data.group_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Команда не найдена")
        if data.user_id is not None and await db.get(User, data.user_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Пользователь не найден")
        new_group = data.group_id
        finding.assigned_manually = True
        finding.assignee_user_id = data.user_id

    record_event(
        db, finding.id, FindingEventType.assigned,
        actor_type=ActorType.user, actor_id=principal.user.id,
        payload={
            "from_group_id": str(finding.assignee_group_id) if finding.assignee_group_id else None,
            "to_group_id": str(new_group) if new_group else None,
            "user_id": str(data.user_id) if data.user_id and not data.by_rules else None,
            "by_rules": data.by_rules,
        },
    )
    finding.assignee_group_id = new_group
    await db.commit()
    return await load_finding(db, finding.id)
