"""Настройки, наследуемые вниз по дереву активов."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import Select, func, or_, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Entity, SlaPolicy


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


TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*(:[a-z0-9_./-]+)?$")
MAX_TAG_LEN = 64
MAX_TAGS = 20


def normalize_tags(raw: list[str]) -> list[str]:
    """Нижний регистр, без дублей, проверка формата. ValueError — с текстом для пользователя."""
    tags = list(dict.fromkeys(t.strip().lower() for t in raw if t.strip()))
    if len(tags) > MAX_TAGS:
        raise ValueError(f"Не больше {MAX_TAGS} тегов на проект")
    for tag in tags:
        if len(tag) > MAX_TAG_LEN or not TAG_RE.match(tag):
            raise ValueError(
                f"Некорректный тег «{tag}»: латиница в нижнем регистре, цифры, «_», «.», «-», "
                f"необязательное значение через «:» (например env:prod), до {MAX_TAG_LEN} символов"
            )
    return tags


def _prefixes(path: str) -> list[str]:
    """fintech/payments/api → [fintech/payments/api, fintech/payments, fintech]"""
    parts = path.split("/")
    return ["/".join(parts[:i]) for i in range(len(parts), 0, -1)]


@dataclass
class EffectiveSla:
    policy_id: uuid.UUID | None
    # путь узла, от которого политика унаследована; None — своя или по умолчанию
    inherited_from: str | None
    is_default: bool


async def default_policy(db: AsyncSession) -> SlaPolicy | None:
    return await db.scalar(select(SlaPolicy).where(SlaPolicy.is_default.is_(True)))


async def _nodes_by_path(db: AsyncSession, entities: Iterable[Entity]) -> dict[str, Entity]:
    paths = {p for e in entities for p in _prefixes(e.path_cache)}
    if not paths:
        return {}
    rows = await db.scalars(select(Entity).where(Entity.path_cache.in_(paths)))
    return {e.path_cache: e for e in rows}


async def effective_sla(db: AsyncSession, entities: list[Entity]) -> dict[uuid.UUID, EffectiveSla]:
    """Эффективная политика каждого узла: своя → ближайший предок → по умолчанию."""
    nodes = await _nodes_by_path(db, entities)
    default = await default_policy(db)
    result: dict[uuid.UUID, EffectiveSla] = {}
    for entity in entities:
        found = EffectiveSla(default.id if default else None, None, True)
        for path in _prefixes(entity.path_cache):
            node = nodes.get(path)
            if node is not None and node.sla_policy_id is not None:
                inherited = None if node.id == entity.id else node.path_cache
                found = EffectiveSla(node.sla_policy_id, inherited, False)
                break
        result[entity.id] = found
    return result


async def effective_tags(db: AsyncSession, entity: Entity) -> list[dict[str, str | None]]:
    """Свои теги и теги предков: [{tag, inherited_from}] (inherited_from=None — свой)."""
    nodes = await _nodes_by_path(db, [entity])
    seen: dict[str, str | None] = {}
    for path in _prefixes(entity.path_cache):
        node = nodes.get(path)
        if node is None:
            continue
        for tag in node.tags:
            seen.setdefault(tag, None if node.id == entity.id else node.path_cache)
    return [{"tag": t, "inherited_from": src} for t, src in sorted(seen.items())]


def subtree_condition(column, path: str):
    """path_cache узла path и всех потомков — без LIKE (в slug бывают «_»)."""
    return or_(column == path, func.left(column, len(path) + 1) == path + "/")


def entities_with_tag(tag: str) -> Select:
    """id проектов, у которых tag среди эффективных (свой или у предка)."""
    owner = aliased(Entity)
    return (
        select(Entity.id)
        .join(owner, or_(
            Entity.id == owner.id,
            func.left(Entity.path_cache, func.length(owner.path_cache) + 1)
            == owner.path_cache + "/",
        ))
        .where(owner.tags.contains(array([tag])))
    )
