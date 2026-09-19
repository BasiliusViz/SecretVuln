"""Настройки, наследуемые вниз по дереву активов."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity


async def resolve_default_branch(db: AsyncSession, entity_id: uuid.UUID) -> str | None:
    """Ближайшая заданная default_branch от узла вверх к корню."""
    current: uuid.UUID | None = entity_id
    while current is not None:
        entity = await db.get(Entity, current)
        if entity is None:
            return None
        if entity.default_branch:
            return entity.default_branch
        current = entity.parent_id
    return None


def branch_allowed(branch: str | None, default_branch: str | None) -> bool:
    """Ветка не указана или основная не задана — принимаем (как до этапа 1)."""
    return branch is None or default_branch is None or branch == default_branch


def branch_rejection_message(branch: str, default_branch: str) -> str:
    return (
        f"Ветка «{branch}» не основная для актива (основная — «{default_branch}»). "
        "Проверки веток появятся позже"
    )
