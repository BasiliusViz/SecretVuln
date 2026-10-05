"""Группы пользователей: CRUD, ручное членство, синхронизация из LDAP.

Роли группа получает привязками — см. `api/bindings.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.bindings import record_cascade_delete
from app.api.deps import Principal, not_found, require_permission
from app.db.session import get_db
from app.models import Entity, Role, RoleBinding, User, UserGroup
from app.models.user import AuthSource
from app.models.user_group import GroupSource
from app.schemas.user_group import (
    GroupCreate,
    GroupDetail,
    GroupRead,
    GroupUpdate,
    SyncResult,
    UserBrief,
)
from app.services import audit
from app.services.access import casbin_rule, ancestors
from app.services.auth.ldap import LdapError, list_group_members

router = APIRouter(prefix="/api/v1", tags=["groups"])


def _to_read(group: UserGroup) -> GroupRead:
    return GroupRead(
        id=group.id,
        name=group.name,
        description=group.description,
        source=group.source.value,
        ldap_group=group.ldap_group,
        last_synced_at=group.last_synced_at,
        member_count=len(group.members),
    )


async def _get_or_404(group_id: uuid.UUID, db: AsyncSession) -> UserGroup:
    group = await db.get(UserGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Группа не найдена")
    return group


@router.get("/groups", response_model=list[GroupRead])
async def list_groups(
    entity_id: uuid.UUID | None = None,
    principal: Principal = Depends(require_permission("group", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[GroupRead]:
    result = list(await db.scalars(select(UserGroup).order_by(UserGroup.name)))
    if entity_id is None:
        return [_to_read(g) for g in result]
    entity = await db.get(Entity, entity_id)
    if entity is None or not principal.access.can_see(entity):
        raise not_found("Проект")
    with_access = await _groups_with_read(db, entity)
    return [_to_read(g).model_copy(update={"has_access": g.id in with_access}) for g in result]


async def _groups_with_read(db: AsyncSession, entity: Entity) -> set[uuid.UUID]:
    """Группы, у которых есть finding:read на проект (глобально или на предке-или-самом)."""
    lineage = ancestors(entity.path_cache) + [entity.path_cache]
    rows = await db.scalars(
        select(RoleBinding.group_id)
        .join(Role, Role.id == RoleBinding.role_id)
        .join(
            casbin_rule,
            (casbin_rule.c.ptype == "p")
            & (casbin_rule.c.v0 == Role.name)
            & (casbin_rule.c.v1 == "finding")
            & (casbin_rule.c.v2 == "read"),
        )
        .outerjoin(Entity, Entity.id == RoleBinding.entity_id)
        .where(RoleBinding.entity_id.is_(None) | Entity.path_cache.in_(lineage))
    )
    return set(rows)


def _record(
    db: AsyncSession,
    principal: Principal | None,
    request: Request,
    action: str,
    group: UserGroup,
    changes: dict,
) -> None:
    """Группы — глобальные объекты: события без проекта. `principal=None` — система."""
    audit.record_audit(
        db,
        principal.user if principal else None,
        action,
        target=("group", group.id, group.name),
        changes=changes,
        ip=audit.client_ip(request) if principal else None,
    )


@router.post("/groups", response_model=GroupDetail, status_code=status.HTTP_201_CREATED)
async def create_group(
    data: GroupCreate,
    request: Request,
    principal: Principal = Depends(require_permission("group", "write")),
    db: AsyncSession = Depends(get_db),
) -> GroupDetail:
    try:
        source = GroupSource(data.source)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестный источник группы")

    ldap_group = None
    if source == GroupSource.ldap:
        ldap_group = (data.ldap_group or data.name).strip()

    group = UserGroup(
        name=data.name.strip(),
        description=(data.description or "").strip() or None,
        source=source,
        ldap_group=ldap_group,
    )
    db.add(group)
    try:
        await db.flush()
        _record(db, principal, request, audit.GROUP_CREATE, group,
                audit.snapshot(group, audit.FIELDS["group"]))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Группа с таким именем уже существует")
    await db.refresh(group)
    return GroupDetail(**_to_read(group).model_dump(), members=[])


@router.get("/groups/{group_id}", response_model=GroupDetail)
async def get_group(
    group_id: uuid.UUID,
    _: object = Depends(require_permission("group", "read")),
    db: AsyncSession = Depends(get_db),
) -> GroupDetail:
    group = await _get_or_404(group_id, db)
    members = [UserBrief.model_validate(u) for u in group.members]
    return GroupDetail(**_to_read(group).model_dump(), members=members)


@router.patch("/groups/{group_id}", response_model=GroupDetail)
async def update_group(
    group_id: uuid.UUID,
    data: GroupUpdate,
    request: Request,
    principal: Principal = Depends(require_permission("group", "write")),
    db: AsyncSession = Depends(get_db),
) -> GroupDetail:
    group = await _get_or_404(group_id, db)
    before = audit.snapshot(group, audit.FIELDS["group"])
    fields = data.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"]:
        group.name = fields["name"].strip()
    if "description" in fields:
        group.description = (fields["description"] or "").strip() or None
    if "ldap_group" in fields and group.source == GroupSource.ldap:
        group.ldap_group = (fields["ldap_group"] or group.name).strip()
    changes = audit.diff(before, audit.snapshot(group, audit.FIELDS["group"]), audit.FIELDS["group"])
    if changes:
        _record(db, principal, request, audit.GROUP_UPDATE, group, changes)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Группа с таким именем уже существует")
    await db.refresh(group)
    members = [UserBrief.model_validate(u) for u in group.members]
    return GroupDetail(**_to_read(group).model_dump(), members=members)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_permission("group", "delete")),
    db: AsyncSession = Depends(get_db),
) -> None:
    group = await _get_or_404(group_id, db)
    await record_cascade_delete(
        db, principal, request, audit.GROUP_DELETE, where=RoleBinding.group_id == group.id
    )
    _record(db, principal, request, audit.GROUP_DELETE, group,
            audit.snapshot(group, audit.FIELDS["group"]))
    await db.delete(group)
    await db.commit()


@router.post("/groups/{group_id}/members/{user_id}", response_model=GroupDetail)
async def add_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_permission("group", "write")),
    db: AsyncSession = Depends(get_db),
) -> GroupDetail:
    group = await _get_or_404(group_id, db)
    if group.source != GroupSource.manual:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Состав LDAP-группы правится только синхронизацией"
        )
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    if user not in group.members:
        group.members.append(user)
        _record(db, principal, request, audit.GROUP_MEMBER_ADD, group, {"user": user.email})
        await db.commit()
        await db.refresh(group)
    members = [UserBrief.model_validate(u) for u in group.members]
    return GroupDetail(**_to_read(group).model_dump(), members=members)


@router.delete("/groups/{group_id}/members/{user_id}", response_model=GroupDetail)
async def remove_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_permission("group", "write")),
    db: AsyncSession = Depends(get_db),
) -> GroupDetail:
    group = await _get_or_404(group_id, db)
    if group.source != GroupSource.manual:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Состав LDAP-группы правится только синхронизацией"
        )
    user = await db.get(User, user_id)
    if user is not None and user in group.members:
        group.members.remove(user)
        _record(db, principal, request, audit.GROUP_MEMBER_REMOVE, group, {"user": user.email})
        await db.commit()
        await db.refresh(group)
    members = [UserBrief.model_validate(u) for u in group.members]
    return GroupDetail(**_to_read(group).model_dump(), members=members)


@router.post("/groups/{group_id}/sync", response_model=SyncResult)
async def sync_group(
    group_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_permission("group", "write")),
    db: AsyncSession = Depends(get_db),
) -> SyncResult:
    group = await _get_or_404(group_id, db)
    if group.source != GroupSource.ldap or not group.ldap_group:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Группа не привязана к LDAP")

    try:
        ldap_members = list_group_members(group.ldap_group)
    except LdapError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"LDAP недоступен: {e}")

    provisioned = 0
    desired: list[User] = []
    for m in ldap_members:
        email = m.email.lower()
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                full_name=m.full_name,
                auth_source=AuthSource.ldap,
                ldap_dn=m.dn,
            )
            db.add(user)
            await db.flush()  # получить id
            provisioned += 1
        desired.append(user)

    current = {u.id: u for u in group.members}
    desired_ids = {u.id for u in desired}

    # состав меняет LDAP — события участников от имени системы, запуск — от пользователя
    added = 0
    for user in desired:
        if user.id not in current:
            group.members.append(user)
            _record(db, None, request, audit.GROUP_MEMBER_ADD, group, {"user": user.email})
            added += 1

    removed = 0
    for uid, user in list(current.items()):
        if uid not in desired_ids:
            group.members.remove(user)
            _record(db, None, request, audit.GROUP_MEMBER_REMOVE, group, {"user": user.email})
            removed += 1

    if added or removed or provisioned:
        _record(db, principal, request, audit.GROUP_SYNC, group,
                {"added": added, "removed": removed, "provisioned": provisioned})

    group.last_synced_at = datetime.now(timezone.utc)
    await db.commit()

    return SyncResult(
        added=added, removed=removed, provisioned=provisioned, total=len(desired)
    )


@router.get("/users", response_model=list[UserBrief])
async def list_users(
    _: object = Depends(require_permission("group", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[UserBrief]:
    result = await db.scalars(select(User).order_by(User.email))
    return [UserBrief.model_validate(u) for u in result]
