"""Привязки ролей: доступ группы к проекту и делегирование (`access:manage`).

Правило «не сильнее своих»: выдать или снять роль R на проекте N можно, только
если каждое действующее на поддереве право R есть у вызывающего на N. Глобальный
`group:write` управляет любыми привязками без этого правила; глобальные привязки
(на всё дерево) — только он.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, ensure, get_current_principal, not_found, require_permission
from app.api.entities import get_entity_checked
from app.db.session import get_db
from app.models import Entity, Role, RoleBinding, UserGroup
from app.schemas.binding import BindingCreate, BindingRead, EntityBindings, GroupBindingCreate, RoleGrant
from app.services.bindings import (
    bindings_for_entity,
    is_access_admin,
    missing_for,
    role_permissions,
    to_read,
)

router = APIRouter(prefix="/api/v1", tags=["bindings"])

DUPLICATE = "У группы уже есть эта роль на этом проекте"


def _too_strong(missing: list[str]) -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Роль сильнее ваших прав на проекте — не хватает: " + ", ".join(missing),
    )


async def _role_or_422(db: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await db.get(Role, role_id)
    if role is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Роль не найдена")
    return role


async def _check_grant(db: AsyncSession, principal: Principal, role: Role, entity: Entity) -> None:
    """Выдать/снять роль на проекте: `access:manage` + «не сильнее своих»."""
    access = principal.access
    if is_access_admin(access):
        return
    ensure(access, "access:manage", entity, what="Проект")
    perms = (await role_permissions(db, [role]))[role.id]
    missing = missing_for(access, perms, entity)
    if missing:
        raise _too_strong(missing)


async def _save(db: AsyncSession, binding: RoleBinding) -> BindingRead:
    db.add(binding)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_role_bindings_group_role_entity" in str(exc.orig):
            raise HTTPException(status.HTTP_409_CONFLICT, DUPLICATE)
        # группу, роль или проект удалили параллельно (нарушен внешний ключ)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Группа, роль или проект не найдены")
    await db.refresh(binding, ["group", "role", "entity"])
    return to_read(binding)


# --- привязки проекта ---


@router.get("/entities/{entity_id}/bindings", response_model=EntityBindings)
async def list_entity_bindings(
    entity_id: uuid.UUID,
    principal: Principal = Depends(require_permission("entity", "read")),
    db: AsyncSession = Depends(get_db),
) -> EntityBindings:
    entity = await get_entity_checked(db, principal, entity_id, "entity:read")
    own, inherited = await bindings_for_entity(db, entity)
    result = EntityBindings(
        own=[to_read(b) for b in own], inherited=[to_read(b) for b in inherited]
    )
    access = principal.access
    admin = is_access_admin(access)
    if admin or access.allows("access:manage", entity):
        roles = list(await db.scalars(select(Role).order_by(Role.name)))
        perms = await role_permissions(db, roles)
        grants = []
        for role in roles:
            missing = [] if admin else missing_for(access, perms[role.id], entity)
            grants.append(
                RoleGrant(id=role.id, name=role.name, grantable=not missing, missing=missing)
            )
        result.roles = grants
    return result


@router.post(
    "/entities/{entity_id}/bindings",
    response_model=BindingRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_entity_binding(
    entity_id: uuid.UUID,
    data: BindingCreate,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> BindingRead:
    entity = await db.get(Entity, entity_id)
    if entity is None or not principal.access.can_see(entity):
        raise not_found("Проект")
    if await db.get(UserGroup, data.group_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Группа не найдена")
    role = await _role_or_422(db, data.role_id)
    await _check_grant(db, principal, role, entity)
    return await _save(
        db,
        RoleBinding(
            group_id=data.group_id,
            role_id=role.id,
            entity_id=entity.id,
            created_by=principal.user.id,
        ),
    )


@router.delete("/bindings/{binding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_binding(
    binding_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> None:
    binding = await db.get(RoleBinding, binding_id)
    if binding is None:
        raise not_found("Привязка")
    if binding.entity_id is None:
        if not is_access_admin(principal.access):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Привязки на всё дерево снимает только администратор"
            )
    else:
        if not principal.access.can_see(binding.entity):
            raise not_found("Привязка")
        await _check_grant(db, principal, binding.role, binding.entity)
    await db.delete(binding)
    await db.commit()


# --- привязки группы ---


async def _group_or_404(db: AsyncSession, group_id: uuid.UUID) -> UserGroup:
    group = await db.get(UserGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Группа не найдена")
    return group


@router.get("/groups/{group_id}/bindings", response_model=list[BindingRead])
async def list_group_bindings(
    group_id: uuid.UUID,
    principal: Principal = Depends(require_permission("group", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[BindingRead]:
    """Привязки группы — только на видимых вызывающему проектах (и на всё дерево)."""
    await _group_or_404(db, group_id)
    rows = await db.scalars(
        select(RoleBinding)
        .outerjoin(Entity, Entity.id == RoleBinding.entity_id)
        .where(RoleBinding.group_id == group_id)
        .order_by(Entity.path_cache.nulls_first(), RoleBinding.created_at)
    )
    access = principal.access
    return [
        to_read(b) for b in rows if b.entity is None or access.can_see(b.entity)
    ]


@router.post(
    "/groups/{group_id}/bindings",
    response_model=BindingRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_group_binding(
    group_id: uuid.UUID,
    data: GroupBindingCreate,
    principal: Principal = Depends(require_permission("group", "write")),
    db: AsyncSession = Depends(get_db),
) -> BindingRead:
    await _group_or_404(db, group_id)
    role = await _role_or_422(db, data.role_id)
    if data.entity_id is not None and await db.get(Entity, data.entity_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Проект не найден")
    return await _save(
        db,
        RoleBinding(
            group_id=group_id,
            role_id=role.id,
            entity_id=data.entity_id,
            created_by=principal.user.id,
        ),
    )


@router.delete(
    "/groups/{group_id}/bindings/{binding_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_group_binding(
    group_id: uuid.UUID,
    binding_id: uuid.UUID,
    _: Principal = Depends(require_permission("group", "write")),
    db: AsyncSession = Depends(get_db),
) -> None:
    binding = await db.get(RoleBinding, binding_id)
    if binding is None or binding.group_id != group_id:
        raise not_found("Привязка")
    await db.delete(binding)
    await db.commit()
