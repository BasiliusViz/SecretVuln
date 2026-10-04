"""Политики SLA: сроки исправления по критичности."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db
from app.models import Entity, SlaPolicy
from app.schemas.sla_policy import SlaPolicyCreate, SlaPolicyRead, SlaPolicyUpdate
from app.services.finding_state import recompute_for_policy

router = APIRouter(prefix="/api/v1/sla-policies", tags=["sla"])

DAY_FIELDS = ("days_critical", "days_high", "days_medium", "days_low", "days_info")


async def _usage(db: AsyncSession) -> dict[uuid.UUID, int]:
    rows = await db.execute(
        select(Entity.sla_policy_id, func.count())
        .where(Entity.sla_policy_id.is_not(None))
        .group_by(Entity.sla_policy_id)
    )
    return dict(rows.all())


async def _to_read(db: AsyncSession, policy: SlaPolicy) -> SlaPolicyRead:
    await db.refresh(policy)
    usage = await _usage(db)
    return SlaPolicyRead.model_validate(policy).model_copy(
        update={"entities_count": usage.get(policy.id, 0)}
    )


async def _get_or_404(db: AsyncSession, policy_id: uuid.UUID) -> SlaPolicy:
    policy = await db.get(SlaPolicy, policy_id)
    if policy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Политика SLA не найдена")
    return policy


async def _make_default(db: AsyncSession, policy: SlaPolicy) -> None:
    """Снять флаг со старой политики и поставить новой — в одной транзакции."""
    await db.execute(
        update(SlaPolicy).where(SlaPolicy.is_default.is_(True), SlaPolicy.id != policy.id)
        .values(is_default=False)
        .execution_options(synchronize_session=False)
    )
    await db.flush()
    policy.is_default = True
    await db.flush()


async def _commit(db: AsyncSession) -> None:
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Политика с таким названием уже есть")


@router.get("", response_model=list[SlaPolicyRead])
async def list_policies(
    _: object = Depends(require_permission("sla", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[SlaPolicyRead]:
    usage = await _usage(db)
    policies = await db.scalars(select(SlaPolicy).order_by(SlaPolicy.is_default.desc(), SlaPolicy.name))
    return [
        SlaPolicyRead.model_validate(p).model_copy(update={"entities_count": usage.get(p.id, 0)})
        for p in policies
    ]


@router.post("", response_model=SlaPolicyRead, status_code=status.HTTP_201_CREATED)
async def create_policy(
    data: SlaPolicyCreate,
    _: object = Depends(require_permission("sla", "manage")),
    db: AsyncSession = Depends(get_db),
) -> SlaPolicyRead:
    policy = SlaPolicy(**data.model_dump(exclude={"is_default"}), is_default=False)
    db.add(policy)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Политика с таким названием уже есть")
    if data.is_default:
        await _make_default(db, policy)
        await recompute_for_policy(db, policy.id)
    await _commit(db)
    return await _to_read(db, policy)


@router.patch("/{policy_id}", response_model=SlaPolicyRead)
async def update_policy(
    policy_id: uuid.UUID,
    data: SlaPolicyUpdate,
    _: object = Depends(require_permission("sla", "manage")),
    db: AsyncSession = Depends(get_db),
) -> SlaPolicyRead:
    policy = await _get_or_404(db, policy_id)
    fields = data.model_dump(exclude_unset=True)
    if fields.get("is_default") is False and policy.is_default:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Политика по умолчанию должна быть всегда — назначьте по умолчанию другую",
        )
    if "name" in fields and fields["name"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Название не может быть пустым")

    days_changed = any(
        key in DAY_FIELDS and getattr(policy, key) != value for key, value in fields.items()
    )
    for key, value in fields.items():
        if key != "is_default":
            setattr(policy, key, value)
    # дубль имени ловим здесь: дальше autoflush в _make_default/recompute дал бы 500
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Политика с таким названием уже есть")
    became_default = fields.get("is_default") is True and not policy.is_default
    if became_default:
        await _make_default(db, policy)
    if days_changed or became_default:
        await recompute_for_policy(db, policy.id)
    await _commit(db)
    return await _to_read(db, policy)


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: uuid.UUID,
    _: object = Depends(require_permission("sla", "manage")),
    db: AsyncSession = Depends(get_db),
) -> None:
    policy = await _get_or_404(db, policy_id)
    if policy.is_default:
        raise HTTPException(status.HTTP_409_CONFLICT, "Нельзя удалить политику по умолчанию")
    used = (await _usage(db)).get(policy.id, 0)
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Политика назначена проектам ({used}) — сначала смените её у них"
        )
    await db.delete(policy)
    await db.commit()
