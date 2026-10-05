import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, ensure, get_current_principal, require_permission
from app.db.session import get_db
from app.models import Entity
from app.schemas.entity import EntityCreate, EntityRead, EntityStub, EntityUpdate, EntityUpsert
from app.services import audit
from app.services.access import Access
from app.services.entity_paths import (
    build_path,
    ensure_path,
    is_valid_slug,
    nearest_existing,
    refresh_path,
    slugify,
    split_path,
    subtree_ids,
    unique_slug,
)
from app.services.entity_tree import default_policy, effective_sla
from app.services.finding_state import recompute_due

router = APIRouter(prefix="/api/v1/entities", tags=["entities"])


NOT_FOUND = "Проект не найден"


async def _get_or_404(entity_id: uuid.UUID, db: AsyncSession) -> Entity:
    entity = await db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return entity


async def get_entity_checked(
    db: AsyncSession, access: Access | Principal, entity_id: uuid.UUID, perm: str
) -> Entity:
    """Загрузить проект и проверить право на него (404 — не виден, 403 — нет права)."""
    entity = await _get_or_404(entity_id, db)
    ensure(access, perm, entity, what="Проект")
    return entity


async def ensure_parent_write(
    db: AsyncSession, access: Access | Principal, parent_id: uuid.UUID | None
) -> None:
    """Создать/перенести узел под parent: `entity:write` на родителе, в корень — глобально."""
    if parent_id is None:
        ensure(access, "entity:write", None)
    else:
        await get_entity_checked(db, access, parent_id, "entity:write")


async def ensure_path_write(db: AsyncSession, access: Access | Principal, path: str) -> None:
    """Автосоздание узлов по пути: `entity:write` на ближайшем существующем предке.

    Если узел уже есть — право на него самого; если нет ни одного предка — глобально.
    """
    try:
        split_path(path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    if isinstance(access, Principal):
        access = access.access
    # Всегда 403, не 404: иначе по ответу видно, существует ли невидимый предок
    if not access.allows("entity:write", await nearest_existing(db, path)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав: entity:write")


async def _ensure_sla_on_move(
    db: AsyncSession, principal: Principal, entity: Entity, new_parent_id: uuid.UUID | None
) -> None:
    """Перенос, меняющий эффективную SLA-политику узла, требует `sla:assign` на узле."""
    if entity.sla_policy_id is not None:
        return  # своя политика переносом не меняется
    before = (await effective_sla(db, [entity]))[entity.id].policy_id
    if new_parent_id is None:
        default = await default_policy(db)
        after = default.id if default else None
    else:
        parent = await db.get(Entity, new_parent_id)
        after = (await effective_sla(db, [parent]))[parent.id].policy_id
    if before != after:
        ensure(principal, "sla:assign", entity, what="Проект")


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


@router.get("", response_model=list[EntityRead | EntityStub])
async def list_entities(
    # без ворот entity:read: заглушки своих веток видны по любому праву на поддерево
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[EntityRead | EntityStub]:
    """Плоский список видимых узлов; дерево собирает клиент по parent_id.

    С `entity:read` узел отдаётся полностью, иначе (предок своего проекта) — заглушкой.
    """
    access = principal.access
    result = await db.scalars(
        select(Entity).where(access.visible_filter(Entity.path_cache)).order_by(Entity.name)
    )
    return [
        EntityRead.model_validate(e)
        if access.allows("entity:read", e)
        else EntityStub.model_validate(e)
        for e in result
    ]


@router.post("", response_model=EntityRead, status_code=status.HTTP_201_CREATED)
async def create_entity(
    data: EntityCreate,
    request: Request,
    principal: Principal = Depends(require_permission("entity", "write")),
    db: AsyncSession = Depends(get_db),
) -> Entity:
    await ensure_parent_write(db, principal, data.parent_id)
    if data.parent_id is not None:
        await _check_parent(db, data.parent_id)
    if data.slug is not None:
        _require_valid_slug(data.slug)
    entity = Entity(**data.model_dump(exclude={"slug"}))
    entity.slug = data.slug or await unique_slug(db, data.parent_id, slugify(data.name))
    entity.path_cache = await build_path(db, data.parent_id, entity.slug)
    db.add(entity)
    try:
        await db.flush()
        await audit.record_entities_created(db, principal.user, [entity], ip=audit.client_ip(request))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, CONFLICT)
    await db.refresh(entity)
    return entity


@router.get("/by-path/{path:path}", response_model=EntityRead)
async def get_entity_by_path(
    path: str,
    principal: Principal = Depends(require_permission("entity", "read")),
    db: AsyncSession = Depends(get_db),
) -> Entity:
    try:
        entity, _created = await ensure_path(db, path, create=False)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    if entity is None or not principal.access.allows("entity:read", entity):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Проект «{path}» не найден")
    return entity


@router.put("/by-path/{path:path}", response_model=EntityRead)
async def upsert_entity_by_path(
    path: str,
    data: EntityUpsert,
    request: Request,
    principal: Principal = Depends(require_permission("entity", "write")),
    db: AsyncSession = Depends(get_db),
) -> Entity:
    """Идемпотентно: создаёт недостающие узлы пути и обновляет имя/описание последнего."""
    await ensure_path_write(db, principal, path)
    try:
        entity, created = await ensure_path(db, path, create=True)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, CONFLICT)
    ip = audit.client_ip(request)
    before = audit.snapshot(entity, audit.FIELDS["entity"])
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(entity, key, value)
    if created:
        await audit.record_entities_created(db, principal.user, created, ip=ip)
    else:
        await _record_update(db, principal, entity, before, audit.ENTITY_UPDATE, ip)
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
    principal: Principal = Depends(require_permission("entity", "read")),
    db: AsyncSession = Depends(get_db),
) -> Entity:
    return await get_entity_checked(db, principal, entity_id, "entity:read")


@router.patch("/{entity_id}", response_model=EntityRead)
async def update_entity(
    entity_id: uuid.UUID,
    data: EntityUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("entity", "write")),
    db: AsyncSession = Depends(get_db),
) -> Entity:
    entity = await get_entity_checked(db, principal, entity_id, "entity:write")
    fields = data.model_dump(exclude_unset=True)
    if "slug" in fields:
        _require_valid_slug(fields["slug"])
    moved = "parent_id" in fields and fields["parent_id"] != entity.parent_id
    if moved:
        await ensure_parent_write(db, principal, fields["parent_id"])
        if fields["parent_id"] is not None:
            await _check_parent(db, fields["parent_id"], child_id=entity_id)
        await _ensure_sla_on_move(db, principal, entity, fields["parent_id"])
    renamed = "slug" in fields and fields["slug"] != entity.slug
    old_parent = await db.get(Entity, entity.parent_id) if moved and entity.parent_id else None
    before = audit.snapshot(entity, audit.FIELDS["entity"])
    for key, value in fields.items():
        setattr(entity, key, value)
    try:
        if moved or renamed:
            await refresh_path(db, entity)
        action = audit.ENTITY_MOVE if moved else audit.ENTITY_UPDATE
        await _record_update(
            db, principal, entity, before, action, audit.client_ip(request),
            also_for=old_parent if old_parent and not _under(entity, old_parent) else None,
        )
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
    request: Request,
    principal: Principal = Depends(require_permission("entity", "delete")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Deletes the node and its whole subtree with imports and findings (FK CASCADE)."""
    entity = await get_entity_checked(db, principal, entity_id, "entity:delete")
    # пишем на родителя: событие увидит руководитель поддерева (у корня — глобальное)
    parent = await db.get(Entity, entity.parent_id) if entity.parent_id else None
    audit.record_audit(
        db,
        principal.user,
        audit.ENTITY_DELETE,
        target=audit.entity_target(entity),
        entity=parent,
        changes=await audit.with_names(db, audit.snapshot(entity, audit.FIELDS["entity"])),
        ip=audit.client_ip(request),
    )
    await db.delete(entity)
    await db.commit()


async def _record_update(
    db: AsyncSession,
    principal: Principal,
    entity: Entity,
    before: dict,
    action: str,
    ip: str | None,
    also_for: Entity | None = None,
) -> None:
    """also_for: второй проект, в журнал которого попадает то же событие
    (старый родитель при переносе — иначе аудитор старой ветки не увидит ухода узла)."""
    after = audit.snapshot(entity, audit.FIELDS["entity"])
    changes = audit.diff(before, after, audit.FIELDS["entity"])
    if not changes:
        return
    changes = await audit.with_names(db, changes)
    for where in (entity, also_for):
        if where is not None:
            audit.record_audit(
                db,
                principal.user,
                action,
                target=audit.entity_target(entity),
                entity=where,
                changes=changes,
                ip=ip,
            )


def _under(node: Entity, ancestor: Entity) -> bool:
    return node.path_cache.startswith(ancestor.path_cache + "/")
