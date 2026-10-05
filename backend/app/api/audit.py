"""Журнал аудита: чтение с фильтрами и видимостью по поддеревьям."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, ensure, not_found, require_permission
from app.db.session import get_db
from app.models import AuditLog, Entity
from app.schemas.audit import AuditLogPage, AuditLogRead
from app.services.entity_paths import subtree_ids

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

PERM = "audit:read"


@router.get("", response_model=AuditLogPage)
async def list_audit(
    entity_id: uuid.UUID | None = None,
    subtree: bool = True,
    actor: str | None = Query(default=None, max_length=255),
    action: str | None = Query(default=None, max_length=100),
    target_type: str | None = Query(default=None, max_length=50),
    target_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_permission("audit", "read")),
    db: AsyncSession = Depends(get_db),
) -> AuditLogPage:
    access = principal.access
    # проектные события — по праву на проект, глобальные — только глобальным аудиторам
    visible = access.entity_scope(PERM, AuditLog.entity_id)
    if access.is_global(PERM):
        visible = or_(visible, AuditLog.entity_id.is_(None))
    conds = [visible]

    if entity_id is not None:
        entity = await db.get(Entity, entity_id)
        if entity is None:
            raise not_found("Проект")
        ensure(principal, PERM, entity, what="Проект")
        conds.append(
            AuditLog.entity_id.in_(subtree_ids(entity))
            if subtree
            else AuditLog.entity_id == entity.id
        )
    if actor:
        conds.append(AuditLog.actor_label.ilike(f"%{_escape_like(actor)}%", escape="\\"))
    if action:
        # «binding.» — все действия группы, иначе точное совпадение
        conds.append(
            func.starts_with(AuditLog.action, action)
            if action.endswith(".")
            else AuditLog.action == action
        )
    if target_type:
        conds.append(AuditLog.target_type == target_type)
    if target_id is not None:
        conds.append(AuditLog.target_id == target_id)
    if date_from is not None:
        conds.append(AuditLog.created_at >= date_from)
    if date_to is not None:
        conds.append(AuditLog.created_at <= date_to)

    where = and_(*conds)
    total = await db.scalar(select(func.count()).select_from(AuditLog).where(where))
    rows = await db.scalars(
        select(AuditLog)
        .where(where)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return AuditLogPage(
        items=[AuditLogRead.model_validate(r) for r in rows], total=total or 0
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
