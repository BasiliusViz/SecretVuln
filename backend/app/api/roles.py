"""Роли и права. Метаданные роли — в таблице roles, права — в casbin_rule."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.authz import permissions as perms
from app.authz.enforcer import (
    delete_role_policies,
    rename_role_policies,
    role_permissions,
    set_role_permissions,
)
from app.db.session import get_db
from app.models import Role
from app.schemas.role import (
    Permission,
    PermissionsUpdate,
    RoleCreate,
    RoleRead,
    RoleUpdate,
)

router = APIRouter(prefix="/api/v1", tags=["roles"])


def _to_read(role: Role) -> RoleRead:
    return RoleRead(
        id=role.id,
        name=role.name,
        description=role.description,
        is_builtin=role.is_builtin,
        permissions=[Permission(resource=r, action=a) for r, a in role_permissions(role.name)],
    )


async def _get_or_404(role_id: uuid.UUID, db: AsyncSession) -> Role:
    role = await db.get(Role, role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Роль не найдена")
    return role


def _validate(perm_list: list[Permission]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for p in perm_list:
        if not perms.is_valid(p.resource, p.action):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Недопустимое право: {p.resource}:{p.action}",
            )
        out.append((p.resource, p.action))
    return out


@router.get("/permissions/catalog")
async def permission_catalog(_: object = Depends(require_permission("role", "read"))) -> dict:
    """Каталог для UI: ресурс → допустимые действия, какие права только глобальные."""
    return {
        "catalog": perms.CATALOG,
        "actions": perms.ACTIONS,
        "global_only": sorted(perms.GLOBAL_ONLY),
        "any_binding": sorted(perms.ANY_BINDING),
    }


@router.get("/roles", response_model=list[RoleRead])
async def list_roles(
    _: object = Depends(require_permission("role", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[RoleRead]:
    result = await db.scalars(select(Role).order_by(Role.name))
    return [_to_read(r) for r in result]


@router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(
    data: RoleCreate,
    _: object = Depends(require_permission("role", "write")),
    db: AsyncSession = Depends(get_db),
) -> RoleRead:
    validated = _validate(data.permissions)
    role = Role(name=data.name.strip(), description=(data.description or "").strip() or None)
    db.add(role)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Роль с таким именем уже существует")
    await db.refresh(role)
    set_role_permissions(role.name, validated)
    return _to_read(role)


@router.get("/roles/{role_id}", response_model=RoleRead)
async def get_role(
    role_id: uuid.UUID,
    _: object = Depends(require_permission("role", "read")),
    db: AsyncSession = Depends(get_db),
) -> RoleRead:
    return _to_read(await _get_or_404(role_id, db))


@router.patch("/roles/{role_id}", response_model=RoleRead)
async def update_role(
    role_id: uuid.UUID,
    data: RoleUpdate,
    _: object = Depends(require_permission("role", "write")),
    db: AsyncSession = Depends(get_db),
) -> RoleRead:
    role = await _get_or_404(role_id, db)
    if role.is_builtin and data.name and data.name.strip() != role.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Встроенную роль нельзя переименовать")
    old_name = role.name
    if data.name and data.name.strip():
        role.name = data.name.strip()
    if data.description is not None:
        role.description = data.description.strip() or None
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Роль с таким именем уже существует")
    await db.refresh(role)
    if role.name != old_name:
        rename_role_policies(old_name, role.name)
    return _to_read(role)


@router.put("/roles/{role_id}/permissions", response_model=RoleRead)
async def set_permissions(
    role_id: uuid.UUID,
    data: PermissionsUpdate,
    _: object = Depends(require_permission("role", "write")),
    db: AsyncSession = Depends(get_db),
) -> RoleRead:
    role = await _get_or_404(role_id, db)
    validated = _validate(data.permissions)
    set_role_permissions(role.name, validated)
    return _to_read(role)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: uuid.UUID,
    _: object = Depends(require_permission("role", "delete")),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = await _get_or_404(role_id, db)
    if role.is_builtin:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Встроенную роль нельзя удалить")
    delete_role_policies(role.name)
    await db.delete(role)
    await db.commit()
