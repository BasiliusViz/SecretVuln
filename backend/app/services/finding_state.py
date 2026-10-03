"""Единая точка смены статуса находки и расчёта срока SLA.

Событие в историю пишет вызывающий (record_event) — здесь только поля находки.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity, Finding, SlaPolicy
from app.models.finding import CLOSED_STATUSES, OPEN_STATUSES, FindingStatus, Severity
from app.services.entity_tree import effective_sla


async def policy_for_entity(db: AsyncSession, entity_id: uuid.UUID) -> SlaPolicy | None:
    entity = await db.get(Entity, entity_id)
    if entity is None:
        return None
    eff = (await effective_sla(db, [entity]))[entity.id]
    return await db.get(SlaPolicy, eff.policy_id) if eff.policy_id else None


def due_from(policy: SlaPolicy | None, severity: Severity, start: datetime) -> datetime | None:
    days = policy.days_for(Severity(severity).value) if policy else None
    return start + timedelta(days=days) if days is not None else None


async def compute_due(
    db: AsyncSession,
    finding: Finding,
    *,
    start: datetime | None = None,
    policy: SlaPolicy | None = None,
) -> None:
    """Задать начало отсчёта (если передано) и срок по эффективной политике проекта.

    policy можно передать заранее (импорт создаёт много находок в одном проекте).
    """
    if start is not None:
        finding.sla_start_at = start
    if policy is None:
        policy = await policy_for_entity(db, finding.entity_id)
    begin = finding.sla_start_at or finding.first_seen or datetime.now(timezone.utc)
    finding.due_at = due_from(policy, finding.severity, begin)


async def set_status(
    db: AsyncSession,
    finding: Finding,
    new_status: FindingStatus,
    *,
    now: datetime | None = None,
    policy: SlaPolicy | None = None,
) -> FindingStatus:
    """Сменить статус с учётом SLA. Возвращает прежний статус."""
    now = now or datetime.now(timezone.utc)
    previous = finding.status
    finding.status = new_status
    was_closed = previous in CLOSED_STATUSES
    if new_status in CLOSED_STATUSES:
        if not was_closed or finding.resolved_at is None:
            finding.resolved_at = now
    elif was_closed:
        # переоткрытие — новый отсчёт срока
        finding.resolved_at = None
        await compute_due(db, finding, start=now, policy=policy)
    return previous


def _days_case(policy: SlaPolicy):
    return case(
        *((Finding.severity == sev, policy.days_for(sev.value)) for sev in Severity),
        else_=None,
    )


async def recompute_due(db: AsyncSession, *, entity_ids: list[uuid.UUID] | None = None) -> None:
    """Пересчитать due_at открытых находок по эффективной политике. Закрытые не трогаем."""
    q = select(Entity)
    if entity_ids is not None:
        if not entity_ids:
            return
        q = q.where(Entity.id.in_(entity_ids))
    entities = list(await db.scalars(q))
    await db.flush()
    by_policy: dict[uuid.UUID | None, list[uuid.UUID]] = defaultdict(list)
    for entity_id, eff in (await effective_sla(db, entities)).items():
        by_policy[eff.policy_id].append(entity_id)

    for policy_id, ids in by_policy.items():
        policy = await db.get(SlaPolicy, policy_id) if policy_id else None
        if policy is None:
            due = None
        else:
            start = func.coalesce(Finding.sla_start_at, Finding.first_seen)
            due = start + func.make_interval(0, 0, 0, _days_case(policy))
        await db.execute(
            update(Finding)
            .where(Finding.entity_id.in_(ids), Finding.status.in_(OPEN_STATUSES))
            .values(due_at=due)
            .execution_options(synchronize_session=False)
        )


async def recompute_for_policy(db: AsyncSession, policy_id: uuid.UUID) -> None:
    """Пересчитать сроки во всех проектах, где политика эффективна (своя, унаследованная, default)."""
    entities = list(await db.scalars(select(Entity)))
    eff = await effective_sla(db, entities)
    await recompute_due(db, entity_ids=[eid for eid, e in eff.items() if e.policy_id == policy_id])
