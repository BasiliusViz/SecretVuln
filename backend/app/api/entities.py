import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db
from app.models import Entity
from app.schemas.entity import EntityCreate, EntityRead, EntityUpdate, EntityUpsert
from app.services.entity_paths import (
    build_path,
    ensure_path,
    is_valid_slug,
    refresh_path,
    slugify,
    subtree_ids,
    unique_slug,
)
from app.services.finding_state import recompute_due

router = APIRouter(prefix="/api/v1/entities", tags=["entities"])


async def _get_or_404(entity_id: uuid.UUID, db: AsyncSession) -> Entity:
    entity = await db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found")
    return entity


async def _check_parent(
    db: AsyncSession, parent_id: uuid.UUID, child_id: uuid.UUID | None = None
) -> None:
    """Parent must exist; moving a node under itself or its descendant is forbidden."""
    current: uuid.UUID | None = parent_id
    while current is not None:
        if current == child_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Cannot move a node under itself or its descendant"
            )
        parent = await db.get(Entity, current)
        if parent is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Parent not found")
        current = parent.parent_id


def _require_valid_slug(slug: str | None) -> None:
    if slug is None or not is_valid_slug(slug):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Адрес проекта (slug): латиница в нижнем регистре, цифры, «.», «_», «-», до 100 символов",
        )


CONFLICT = "На этом уровне уже есть проект с таким названием или адресом"


@router.get("", response_model=list[EntityRead])
async def list_entities(
    _: object = Depends(require_permission("entity", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[Entity]:
    """Flat list of all nodes; the tree is assembled client-side via parent_id."""
    result = await db.scalars(select(Entity).order_by(Entity.name))
    return list(result)


@router.post("", response_model=EntityRead, status_code=status.HTTP_201_CREATED)
async def create_entity(
    data: EntityCreate,
    _: object = Depends(require_permission("entity", "write")),
    db: AsyncSession = Depends(get_db),
) -> Entity:
    if data.parent_id is not None:
        await _check_parent(db, data.parent_id)
    if data.slug is not None:
        _require_valid_slug(data.slug)
    entity = Entity(**data.model_dump(exclude={"slug"}))
    entity.slug = data.slug or await unique_slug(db, data.parent_id, slugify(data.name))
    entity.path_cache = await build_path(db, data.parent_id, entity.slug)
    db.add(entity)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, CONFLICT)
    await db.refresh(entity)
    return entity


@router.get("/by-path/{path:path}", response_model=EntityRead)
async def get_entity_by_path(
    path: str,
    _: object = Depends(require_permission("entity", "read")),
    db: AsyncSession = Depends(get_db),
) -> Entity:
    try:
        entity, _created = await ensure_path(db, path, create=False)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Проект «{path}» не найден")
    return entity


@router.put("/by-path/{path:path}", response_model=EntityRead)
async def upsert_entity_by_path(
    path: str,
    data: EntityUpsert,
    _: object = Depends(require_permission("entity", "write")),
    db: AsyncSession = Depends(get_db),
) -> Entity:
    """Идемпотентно: создаёт недостающие узлы пути и обновляет имя/описание последнего."""
    try:
        entity, _created = await ensure_path(db, path, create=True)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, CONFLICT)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(entity, key, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, CONFLICT)
    await db.refresh(entity)
    return entity


@router.get("/{entity_id}", response_model=EntityRead)
async def get_entity(
    entity_id: uuid.UUID,
    _: object = Depends(require_permission("entity", "read")),
    db: AsyncSession = Depends(get_db),
) -> Entity:
    return await _get_or_404(entity_id, db)


@router.patch("/{entity_id}", response_model=EntityRead)
async def update_entity(
    entity_id: uuid.UUID,
    data: EntityUpdate,
    _: object = Depends(require_permission("entity", "write")),
    db: AsyncSession = Depends(get_db),
) -> Entity:
    entity = await _get_or_404(entity_id, db)
    fields = data.model_dump(exclude_unset=True)
    if "slug" in fields:
        _require_valid_slug(fields["slug"])
    if fields.get("parent_id") is not None:
        await _check_parent(db, fields["parent_id"], child_id=entity_id)
    moved = "parent_id" in fields and fields["parent_id"] != entity.parent_id
    renamed = "slug" in fields and fields["slug"] != entity.slug
    for key, value in fields.items():
        setattr(entity, key, value)
    try:
        if moved or renamed:
            await refresh_path(db, entity)
        if moved:
            # унаследованная политика SLA могла смениться у всего поддерева
            await db.flush()
            await recompute_due(db, entity_ids=list(await db.scalars(subtree_ids(entity))))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, CONFLICT)
    await db.refresh(entity)
    return entity


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(
    entity_id: uuid.UUID,
    _: object = Depends(require_permission("entity", "delete")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Deletes the node and its whole subtree with imports and findings (FK CASCADE)."""
    entity = await _get_or_404(entity_id, db)
    await db.delete(entity)
    await db.commit()
