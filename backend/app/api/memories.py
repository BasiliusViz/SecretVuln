"""Правила команды: подсказки решений по находкам (`triage_memories`).

Читает правило тот, у кого `finding:read` на его область; действующее (`approved`)
правило видно ещё и тем, у кого `finding:read` на проект под ней — оно действует на
их находки. Предложенные и выключенные сверху не видны: в них обоснование из решения
по чужой находке. Меняет — `memory:manage` на область; чужое правило — 404.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, not_found, require_permission
from app.db.session import get_db
from app.models import Entity, MemorySource, MemoryStatus, TriageMemory
from app.schemas.memory import CONDITIONS, MemoryCreate, MemoryRead, MemoryUpdate, check_rule
from app.services import audit
from app.services.access import ancestors
from app.services.memories import open_hint_counts, recompute

router = APIRouter(prefix="/api/v1/memories", tags=["memories"])

READ = "finding:read"
MANAGE = "memory:manage"


def _read(principal: Principal, memory: TriageMemory, entity: Entity, open_findings: int = 0):
    return MemoryRead.model_validate(memory).model_copy(update={
        "entity_path": entity.path_cache,
        "entity_name": entity.name,
        "open_findings": open_findings,
        "can_manage": principal.access.allows(MANAGE, entity),
    })


async def _one(db: AsyncSession, principal: Principal, memory: TriageMemory, entity: Entity):
    counts = await open_hint_counts(db, [memory.id], principal.access)
    return _read(principal, memory, entity, counts.get(memory.id, 0))


async def _visible(
    db: AsyncSession, principal: Principal, memory_id: uuid.UUID
) -> tuple[TriageMemory, Entity]:
    memory = await db.get(TriageMemory, memory_id)
    entity = await db.get(Entity, memory.entity_id) if memory else None
    access = principal.access
    if memory is None or not (
        access.allows(READ, entity)
        or access.allows(MANAGE, entity)
        or (memory.status == MemoryStatus.approved and access.allows_from_above(READ, entity))
    ):
        raise not_found("Правило")
    return memory, entity


async def _area(db: AsyncSession, principal: Principal, entity_id: uuid.UUID) -> Entity:
    """Проект-область правила; нужен `memory:manage` на него."""
    entity = await db.get(Entity, entity_id)
    if entity is None or not principal.access.can_see(entity):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    if not principal.access.allows(MANAGE, entity):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Недостаточно прав: {MANAGE}")
    return entity


@router.get("", response_model=list[MemoryRead])
async def list_memories(
    memory_status: MemoryStatus | None = Query(None, alias="status"),
    entity_id: uuid.UUID | None = None,
    include_descendants: bool = False,
    manageable: bool = False,
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[MemoryRead]:
    """`entity_id` — правила, действующие в проекте: его собственные и предков
    (`include_descendants` — ещё и правила его поддерева). `manageable` — только те,
    что вызывающий может менять (счётчик предложенных)."""
    access = principal.access
    q = (
        select(TriageMemory, Entity)
        .join(Entity, Entity.id == TriageMemory.entity_id)
        .where(or_(
            access.filter(READ, Entity.path_cache),
            access.filter(MANAGE, Entity.path_cache),
            # сверху видны только действующие правила
            and_(
                TriageMemory.status == MemoryStatus.approved,
                access.filter_from_above(READ, Entity.path_cache),
            ),
        ))
    )
    if manageable:
        q = q.where(access.filter(MANAGE, Entity.path_cache))
    if memory_status:
        q = q.where(TriageMemory.status == memory_status)
    if entity_id:
        entity = await db.get(Entity, entity_id)
        if entity is None or not access.can_see(entity):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
        path = entity.path_cache
        scope = [Entity.path_cache.in_([*ancestors(path), path])]
        if include_descendants:
            scope.append(func.starts_with(Entity.path_cache, path + "/"))
        q = q.where(or_(*scope))
    q = q.order_by(TriageMemory.created_at.desc(), TriageMemory.id).offset(offset).limit(limit)
    rows = (await db.execute(q)).all()
    counts = await open_hint_counts(db, [m.id for m, _ in rows], access)
    return [_read(principal, m, e, counts.get(m.id, 0)) for m, e in rows]


@router.get("/{memory_id}", response_model=MemoryRead)
async def get_memory(
    memory_id: uuid.UUID,
    principal: Principal = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> MemoryRead:
    memory, entity = await _visible(db, principal, memory_id)
    return await _one(db, principal, memory, entity)


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
async def create_memory(
    data: MemoryCreate,
    request: Request,
    principal: Principal = Depends(require_permission("memory", "manage")),
    db: AsyncSession = Depends(get_db),
) -> MemoryRead:
    entity = await _area(db, principal, data.entity_id)
    memory = TriageMemory(
        id=uuid.uuid4(),
        **data.model_dump(),
        status=MemoryStatus.approved,
        source=MemorySource.manual,
        created_by=principal.user.id,
        approved_by=principal.user.id,
        approved_at=datetime.now(timezone.utc),
    )
    db.add(memory)
    hinted = await recompute(db, memory, actor_id=principal.user.id)
    audit.record_audit(
        db, principal.user, audit.MEMORY_CREATE,
        target=("memory", memory.id, _label(memory)),
        entity=entity,
        changes={**audit.snapshot(memory, audit.FIELDS["memory"]), "hints_changed": hinted},
        ip=audit.client_ip(request),
    )
    await db.commit()
    await db.refresh(memory)
    return await _one(db, principal, memory, entity)


@router.patch("/{memory_id}", response_model=MemoryRead)
async def update_memory(
    memory_id: uuid.UUID,
    data: MemoryUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("memory", "manage")),
    db: AsyncSession = Depends(get_db),
) -> MemoryRead:
    """Правка, утверждение (`status=approved`) и выключение (`status=disabled`).
    Смена статуса, условия или области действующего правила пересчитывает подсказки."""
    memory, entity = await _visible(db, principal, memory_id)
    if not principal.access.allows(MANAGE, entity):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Недостаточно прав: {MANAGE}")

    before = audit.snapshot(memory, audit.FIELDS["memory"])
    old_path = entity.path_cache
    fields = data.model_fields_set
    if "entity_id" in fields and data.entity_id and data.entity_id != memory.entity_id:
        entity = await _area(db, principal, data.entity_id)
        memory.entity_id = entity.id
    for f in (*CONDITIONS, "reason", "reason_tag"):
        if f in fields:
            setattr(memory, f, getattr(data, f))
    if "decision" in fields and data.decision is not None:
        memory.decision = data.decision
    was_approved = memory.status == MemoryStatus.approved
    if data.status is not None:
        memory.status = MemoryStatus(data.status)
    # выключенное правило ничего не подсказывает — его обоснование можно не проверять
    # (иначе предложение с неполным текстом нельзя было бы отклонить)
    conditions = {f: getattr(memory, f) for f in CONDITIONS}
    try:
        if memory.status != MemoryStatus.disabled:
            check_rule(
                conditions=conditions,
                decision=memory.decision, reason_tag=memory.reason_tag, reason=memory.reason,
            )
        elif not any(conditions.values()):
            # условие нужно всегда: без него строку не примет ограничение в БД
            raise ValueError("Задайте хотя бы одно условие: сканер, правило, CWE или маску пути")
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    now_approved = memory.status == MemoryStatus.approved
    if now_approved and not was_approved:
        memory.approved_by = principal.user.id
        memory.approved_at = datetime.now(timezone.utc)

    after = audit.snapshot(memory, audit.FIELDS["memory"])
    changes = audit.diff(before, after, audit.FIELDS["memory"])
    if "entity_id" in changes:
        changes["entity_path"] = [old_path, entity.path_cache]
    matching_changed = any(f in changes for f in ("entity_id", *CONDITIONS))
    if was_approved != now_approved or (now_approved and matching_changed):
        changes["hints_changed"] = await recompute(db, memory, actor_id=principal.user.id)

    if changes:
        if "status" in changes:
            action = audit.MEMORY_APPROVE if now_approved else audit.MEMORY_DISABLE
        else:
            action = audit.MEMORY_UPDATE
        audit.record_audit(
            db, principal.user, action,
            target=("memory", memory.id, _label(memory)),
            entity=entity,
            changes=changes,
            ip=audit.client_ip(request),
        )
    await db.commit()
    await db.refresh(memory)
    return await _one(db, principal, memory, entity)


def _label(memory: TriageMemory) -> str:
    return audit.memory_label(memory)
