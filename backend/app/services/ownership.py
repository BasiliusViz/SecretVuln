"""Команда-владелец уязвимости: правила по путям → владелец проекта → никто."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActorType, Entity, FindingEventType, OwnershipRule
from app.models.finding import OPEN_STATUSES, Finding
from app.services.entity_settings import lineage
from app.services.events import record_event


def normalize_path(path: str) -> str:
    value = path.replace("\\", "/")
    if value.startswith("file://"):
        value = value[len("file://"):]
    while value.startswith("./"):
        value = value[2:]
    return value.lstrip("/")


@lru_cache(maxsize=1024)
def compile_glob(pattern: str) -> re.Pattern[str]:
    """Маска в стиле CODEOWNERS: ** — любые папки, * — внутри одной папки, ? — один символ."""
    p = normalize_path(pattern.strip())
    if p.endswith("/"):
        p += "**"
    out: list[str] = []
    i = 0
    while i < len(p):
        if p.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif p.startswith("**", i):
            out.append(".*")
            i += 2
        elif p[i] == "*":
            out.append("[^/]*")
            i += 1
        elif p[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(p[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def path_matches(pattern: str, path: str) -> bool:
    return bool(compile_glob(pattern).match(normalize_path(path)))


@dataclass
class OwnerResolver:
    # (маска, команда) в порядке приоритета: правила узла, затем предков вверх по дереву
    rules: list[tuple[str, uuid.UUID]]
    default_owner: uuid.UUID | None

    def resolve(self, file_path: str | None) -> uuid.UUID | None:
        if file_path:
            for pattern, group_id in self.rules:
                if path_matches(pattern, file_path):
                    return group_id
        return self.default_owner


async def build_resolver(db: AsyncSession, entity_id: uuid.UUID) -> OwnerResolver:
    entity = await db.get(Entity, entity_id)
    rules: list[tuple[str, uuid.UUID]] = []
    default_owner: uuid.UUID | None = None
    for node in await lineage(db, entity):
        result = await db.scalars(
            select(OwnershipRule)
            .where(OwnershipRule.entity_id == node.id)
            .order_by(OwnershipRule.position)
        )
        rules.extend((r.pattern, r.group_id) for r in result)
        if default_owner is None and node.owner_group_id is not None:
            default_owner = node.owner_group_id
    return OwnerResolver(rules=rules, default_owner=default_owner)


async def reassign_entity(
    db: AsyncSession, entity_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
) -> int:
    """Переназначить открытые уязвимости проекта по правилам (кроме назначенных вручную)."""
    resolver = await build_resolver(db, entity_id)
    findings = await db.scalars(
        select(Finding).where(
            Finding.entity_id == entity_id,
            Finding.assigned_manually.is_(False),
            Finding.status.in_(OPEN_STATUSES),
        )
    )
    changed = 0
    for finding in findings:
        group_id = resolver.resolve(finding.file_path)
        if group_id == finding.assignee_group_id:
            continue
        record_event(
            db, finding.id, FindingEventType.assigned,
            actor_type=ActorType.user if actor_id else ActorType.system,
            actor_id=actor_id,
            reason="Назначено по правилам владения",
            payload={
                "from_group_id": str(finding.assignee_group_id) if finding.assignee_group_id else None,
                "to_group_id": str(group_id) if group_id else None,
                "by_rules": True,
            },
        )
        finding.assignee_group_id = group_id
        changed += 1
    await db.flush()
    return changed
