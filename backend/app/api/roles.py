"""Роли и права. Метаданные роли — в таблице roles, права — в casbin_rule."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_permission
from app.authz import permissions as perms
from app.authz.enforcer import (
    delete_role_policies,
    rename_role_policies,
    role_permissions,
    set_role_permissions,
)
from app.db.session import get_db
from app.models import Role
from app.services import audit
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


def _perm_list(pairs) -> list[str]:
    return sorted(f"{r}:{a}" for r, a in pairs)


def _record(
    db: AsyncSession, principal: Principal, request: Request, action: str, role: Role, changes: dict
) -> None:
    """Роли — глобальные объекты: события без проекта."""
    audit.record_audit(
        db,
        principal.user,
        action,
        target=("role", role.id, role.name),
        changes=changes,
        ip=audit.client_ip(request),
    )


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
    request: Request,
    principal: Principal = Depends(require_permission("role", "write")),
    db: AsyncSession = Depends(get_db),
) -> RoleRead:
    validated = _validate(data.permissions)
    role = Role(name=data.name.strip(), description=(data.description or "").strip() or None)
    db.add(role)
    try:
        await db.flush()
        _record(db, principal, request, audit.ROLE_CREATE, role, {
            **audit.snapshot(role, audit.FIELDS["role"]),
            "permissions": _perm_list(validated),
        })
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
    request: Request,
    principal: Principal = Depends(require_permission("role", "write")),
    db: AsyncSession = Depends(get_db),
) -> RoleRead:
    role = await _get_or_404(role_id, db)
    if role.is_builtin and data.name and data.name.strip() != role.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Встроенную роль нельзя переименовать")
    old_name = role.name
    before = audit.snapshot(role, audit.FIELDS["role"])
    if data.name and data.name.strip():
        role.name = data.name.strip()
    if data.description is not None:
        role.description = data.description.strip() or None
    changes = audit.diff(before, audit.snapshot(role, audit.FIELDS["role"]), audit.FIELDS["role"])
    if changes:
        _record(db, principal, request, audit.ROLE_UPDATE, role, changes)
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
    request: Request,
    principal: Principal = Depends(require_permission("role", "write")),
    db: AsyncSession = Depends(get_db),
) -> RoleRead:
    role = await _get_or_404(role_id, db)
    validated = _validate(data.permissions)
    before = set(_perm_list(role_permissions(role.name)))
    after = set(_perm_list(validated))
    if before != after:
        _record(db, principal, request, audit.ROLE_PERMISSIONS_UPDATE, role, {
            "added": sorted(after - before),
            "removed": sorted(before - after),
        })
        await db.commit()
    set_role_permissions(role.name, validated)
    return _to_read(role)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_permission("role", "delete")),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = await _get_or_404(role_id, db)
    if role.is_builtin:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Встроенную роль нельзя удалить")
    _record(db, principal, request, audit.ROLE_DELETE, role, {
        **audit.snapshot(role, audit.FIELDS["role"]),
        "permissions": _perm_list(role_permissions(role.name)),
    })
    delete_role_policies(role.name)
    await db.delete(role)
    await db.commit()
