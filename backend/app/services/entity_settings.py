"""Наследуемые настройки проекта и их источник (файл / вручную / унаследовано)."""

from __future__ import annotations

import enum
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity

# Ключи закрепления: правка в админке закрепляет ключ, файл его больше не трогает
PIN_KEYS: tuple[str, ...] = ("default_branch", "owner_group_id", "repo", "ownership_rules")
# Наследуемое поле → ключ закрепления (поля репозитория закрепляются вместе)
FIELD_PIN: dict[str, str] = {
    "default_branch": "default_branch",
    "owner_group_id": "owner_group_id",
    "repo_url": "repo",
    "repo_type": "repo",
    "repo_path_prefix": "repo",
}


def normalize_repo_url(url: str) -> str:
    """https://GitLab.corp/Team/App.git/ → https://gitlab.corp/Team/App"""
    value = url.strip().rstrip("/")
    if value.endswith(".git"):
        value = value[:-4]
    parts = urlsplit(value)
    if parts.scheme and parts.netloc:
        value = urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", "")
        )
    return value


async def lineage(db: AsyncSession, entity: Entity) -> list[Entity]:
    """Узел и его предки: [узел, родитель, …, корень]."""
    chain = [entity]
    while chain[-1].parent_id is not None:
        chain.append(await db.get(Entity, chain[-1].parent_id))
    return chain


def own_source(entity: Entity, pin_key: str) -> str:
    if pin_key in entity.pinned_fields or entity.config_file is None:
        return "manual"
    return "file"


async def effective_settings(db: AsyncSession, entity: Entity) -> dict[str, dict[str, Any]]:
    chain = await lineage(db, entity)
    result: dict[str, dict[str, Any]] = {}
    for field, pin_key in FIELD_PIN.items():
        result[field] = {"value": None, "source": "unset", "inherited_from": None}
        for node in chain:
            value = getattr(node, field)
            if value is None:
                continue
            if isinstance(value, enum.Enum):
                value = value.value
            if node is entity:
                result[field] = {"value": value, "source": own_source(node, pin_key), "inherited_from": None}
            else:
                result[field] = {"value": value, "source": "inherited", "inherited_from": node.path_cache}
            break
    return result


async def find_repo_owner(
    db: AsyncSession, url: str, *, exclude_id: uuid.UUID | None = None
) -> Entity | None:
    q = select(Entity).where(Entity.repo_url == url)
    if exclude_id is not None:
        q = q.where(Entity.id != exclude_id)
    return await db.scalar(q)
