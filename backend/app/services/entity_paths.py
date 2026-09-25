"""Адрес проекта: slug узла и полный путь вида fintech/payments/backend-api."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity

_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
})
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
MAX_SLUG = 100


def slugify(name: str) -> str:
    slug = name.strip().lower().translate(_TRANSLIT)
    slug = re.sub(r"[^a-z0-9._-]+", "-", slug).strip("-._")
    return slug[:MAX_SLUG].rstrip("-._") or "project"


def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug))


def split_path(path: str) -> list[str]:
    parts = path.strip().strip("/").split("/")
    if not all(is_valid_slug(p) for p in parts):
        raise ValueError(
            f"Некорректный путь проекта «{path}»: части пути — латиница в нижнем регистре, "
            "цифры, «.», «_», «-», разделитель «/»"
        )
    return parts


async def unique_slug(
    db: AsyncSession, parent_id: uuid.UUID | None, base: str, *, exclude_id: uuid.UUID | None = None
) -> str:
    slug, n = base, 2
    while True:
        q = select(Entity.id).where(
            Entity.parent_id.is_not_distinct_from(parent_id), Entity.slug == slug
        )
        if exclude_id is not None:
            q = q.where(Entity.id != exclude_id)
        if await db.scalar(q) is None:
            return slug
        suffix = f"-{n}"
        slug = f"{base[: MAX_SLUG - len(suffix)]}{suffix}"
        n += 1


async def unique_name(
    db: AsyncSession, parent_id: uuid.UUID | None, base: str, *, exclude_id: uuid.UUID | None = None
) -> str:
    """Аналог unique_slug для имени: узел, автосоздаваемый ensure_path, получает имя = slug
    сегмента пути; если у соседа уже есть такое имя (при другом slug), подбираем «-2», «-3»,
    чтобы не упереться в uq_entities_parent_name на каждом повторе."""
    name, n = base, 2
    while True:
        q = select(Entity.id).where(
            Entity.parent_id.is_not_distinct_from(parent_id), Entity.name == name
        )
        if exclude_id is not None:
            q = q.where(Entity.id != exclude_id)
        if await db.scalar(q) is None:
            return name
        suffix = f"-{n}"
        name = f"{base[:255 - len(suffix)]}{suffix}"
        n += 1


async def build_path(db: AsyncSession, parent_id: uuid.UUID | None, slug: str) -> str:
    if parent_id is None:
        return slug
    parent = await db.get(Entity, parent_id)
    return f"{parent.path_cache}/{slug}"


async def refresh_path(db: AsyncSession, entity: Entity) -> None:
    """Пересчитать path_cache узла и всего поддерева (после смены slug или родителя)."""
    old = entity.path_cache
    new = await build_path(db, entity.parent_id, entity.slug)
    entity.path_cache = new
    await db.flush()
    if old and old != new:
        await db.execute(
            update(Entity)
            .where(func.starts_with(Entity.path_cache, old + "/"))
            .values(path_cache=func.concat(new, func.substr(Entity.path_cache, len(old) + 1)))
            .execution_options(synchronize_session=False)
        )


async def ensure_path(
    db: AsyncSession, path: str, *, create: bool
) -> tuple[Entity | None, list[Entity]]:
    """Найти узел по пути; при create=True создать недостающие узлы цепочки.

    Возвращает (узел или None, список созданных узлов). Не коммитит.
    """
    created: list[Entity] = []
    parent: Entity | None = None
    current = ""
    for slug in split_path(path):
        current = f"{current}/{slug}" if current else slug
        node = await db.scalar(select(Entity).where(Entity.path_cache == current))
        if node is None:
            if not create:
                return None, []
            parent_id = parent.id if parent else None
            node = Entity(
                name=await unique_name(db, parent_id, slug),
                slug=slug,
                parent_id=parent_id,
                path_cache=current,
                custom_fields={},
            )
            db.add(node)
            await db.flush()
            created.append(node)
        parent = node
    return parent, created


def subtree_ids(entity: Entity) -> Select:
    """id узла и всех его потомков — для фильтров «включая вложенные»."""
    return select(Entity.id).where(
        or_(Entity.id == entity.id, func.starts_with(Entity.path_cache, entity.path_cache + "/"))
    )
