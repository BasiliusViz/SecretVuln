"""Привязки «группа + роль + проект»: права ролей и правило «не сильнее своих»."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz.permissions import ANY_BINDING, is_scoped
from app.models import Entity, Role, RoleBinding
from app.schemas.binding import BindingRead
from app.services.access import Access, casbin_rule, ancestors


async def role_permissions(db: AsyncSession, roles: list[Role]) -> dict[uuid.UUID, set[str]]:
    """Права ролей из casbin_rule (из БД, как и в load_access)."""
    by_name = {r.name: r.id for r in roles}
    out: dict[uuid.UUID, set[str]] = defaultdict(set)
    if not by_name:
        return out
    rows = await db.execute(
        select(casbin_rule.c.v0, casbin_rule.c.v1, casbin_rule.c.v2).where(
            casbin_rule.c.ptype == "p", casbin_rule.c.v0.in_(list(by_name))
        )
    )
    for name, resource, action in rows:
        out[by_name[name]].add(f"{resource}:{action}")
    return out


def missing_for(access: Access, perms: set[str], entity: Entity) -> list[str]:
    """Действующие на поддереве права роли, которых нет у вызывающего на проекте.

    Глобальные права роли не учитываются: в привязке к проекту они не действуют.
    Права «из любой привязки» (`group:read`, `sla:read`) действуют везде — их нужно иметь хоть где-то.
    """
    return sorted(
        p
        for p in perms
        if (p in ANY_BINDING and not access.anywhere(p))
        or (is_scoped(p) and not access.allows(p, entity))
    )


def is_access_admin(access: Access) -> bool:
    """Глобальный group:write управляет любыми привязками без правила «не сильнее своих»."""
    return access.is_global("group:write")


def to_read(binding: RoleBinding) -> BindingRead:
    return BindingRead(
        id=binding.id,
        group_id=binding.group_id,
        group_name=binding.group.name,
        role_id=binding.role_id,
        role_name=binding.role.name,
        entity_id=binding.entity_id,
        entity_path=binding.entity.path_cache if binding.entity is not None else None,
        created_at=binding.created_at,
        created_by=binding.created_by,
    )


async def bindings_for_entity(
    db: AsyncSession, entity: Entity
) -> tuple[list[RoleBinding], list[RoleBinding]]:
    """(свои, унаследованные — глобальные и на предках)."""
    anc = ancestors(entity.path_cache)
    ancestor_ids = (
        list(await db.scalars(select(Entity.id).where(Entity.path_cache.in_(anc)))) if anc else []
    )
    rows = await db.scalars(
        select(RoleBinding)
        .outerjoin(Entity, Entity.id == RoleBinding.entity_id)
        .where(
            (RoleBinding.entity_id == entity.id)
            | RoleBinding.entity_id.is_(None)
            | RoleBinding.entity_id.in_(ancestor_ids)
        )
        .order_by(Entity.path_cache.nulls_first(), RoleBinding.created_at)
    )
    own, inherited = [], []
    for b in rows:
        (own if b.entity_id == entity.id else inherited).append(b)
    return own, inherited
