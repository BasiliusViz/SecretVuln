"""Журнал аудита административных действий.

`record_audit` вызывается только в слое API (там есть principal и request) и
добавляет строку в текущую сессию — она коммитится вместе с самим действием.
В `changes` попадают только поля из белых списков `FIELDS`: пароли и токены
не пишутся никогда.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any, Iterable

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Entity, User
from app.models.finding_event import ActorType

# --- действия: `<объект>.<действие>` ---
AUTH_LOGIN = "auth.login"
AUTH_LOGIN_FAILED = "auth.login_failed"

ENTITY_CREATE = "entity.create"
ENTITY_UPDATE = "entity.update"
ENTITY_MOVE = "entity.move"
ENTITY_DELETE = "entity.delete"
ENTITY_SETTINGS_UPDATE = "entity.settings_update"
ENTITY_UNPIN = "entity.unpin"
OWNERSHIP_RULES_UPDATE = "ownership.rules_update"
FINDINGS_REASSIGN = "findings.reassign"

GROUP_CREATE = "group.create"
GROUP_UPDATE = "group.update"
GROUP_DELETE = "group.delete"
GROUP_MEMBER_ADD = "group.member_add"
GROUP_MEMBER_REMOVE = "group.member_remove"
GROUP_SYNC = "group.sync"

ROLE_CREATE = "role.create"
ROLE_UPDATE = "role.update"
ROLE_DELETE = "role.delete"
ROLE_PERMISSIONS_UPDATE = "role.permissions_update"

BINDING_CREATE = "binding.create"
BINDING_DELETE = "binding.delete"

SLA_POLICY_CREATE = "sla_policy.create"
SLA_POLICY_UPDATE = "sla_policy.update"
SLA_POLICY_DELETE = "sla_policy.delete"

IMPORT_CREATE = "import.create"

ACTIONS: tuple[str, ...] = tuple(
    v for k, v in dict(globals()).items() if k.isupper() and isinstance(v, str) and "." in v
)

# --- белые списки полей для `changes` ---
FIELDS: dict[str, tuple[str, ...]] = {
    "entity": ("name", "slug", "path_cache", "parent_id", "description", "default_branch"),
    "entity_settings": (
        "owner_group_id",
        "repo_url",
        "repo_type",
        "repo_path_prefix",
        "default_branch",
        "sla_policy_id",
        "tags",
        "custom_fields",
        "pinned_fields",
    ),
    "group": ("name", "description", "source", "ldap_group"),
    "role": ("name", "description", "ldap_group"),
    "binding": ("group_id", "role_id", "entity_id"),
    "sla_policy": (
        "name",
        "days_critical",
        "days_high",
        "days_medium",
        "days_low",
        "days_info",
        "is_default",
    ),
    "import": ("filename", "scanner", "branch", "commit_sha", "pipeline_url", "scan_scope"),
}

# Не попадают в журнал, даже если их по ошибке включат в список полей.
_SECRETS = frozenset({"password", "hashed_password", "token", "access_token", "secret"})


def _json(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return [_json(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    return value


def _allowed(fields: Iterable[str]) -> list[str]:
    return [f for f in fields if f not in _SECRETS]


def snapshot(obj: Any, fields: Iterable[str]) -> dict[str, Any]:
    """Значения разрешённых полей объекта в JSON-виде (для create/delete и как `before`)."""
    return {f: _json(getattr(obj, f, None)) for f in _allowed(fields)}


def diff(before: dict[str, Any], after: dict[str, Any], fields: Iterable[str]) -> dict[str, list]:
    """`{поле: [было, стало]}` только по разрешённым и реально изменившимся полям."""
    out: dict[str, list] = {}
    for f in _allowed(fields):
        old, new = _json(before.get(f)), _json(after.get(f))
        if old != new:
            out[f] = [old, new]
    return out


def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def record_audit(
    db: AsyncSession,
    actor: User | str | None,
    action: str,
    *,
    target: tuple[str, uuid.UUID | None, str | None] | None = None,
    entity: Entity | None = None,
    changes: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Добавить запись в журнал.

    actor: пользователь; строка — введённый логин при неудачном входе; None — система.
    entity: проект, к которому относится событие (`None` — глобальное событие).
    """
    if isinstance(actor, User):
        actor_type, actor_id, actor_label = ActorType.user, actor.id, actor.email
    elif isinstance(actor, str):
        actor_type, actor_id, actor_label = ActorType.user, None, actor
    else:
        actor_type, actor_id, actor_label = ActorType.system, None, None
    target_type, target_id, target_label = target or (None, None, None)
    row = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        actor_label=actor_label[:255] if actor_label else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_label=target_label[:1024] if target_label else None,
        entity_id=entity.id if entity is not None else None,
        entity_path=entity.path_cache if entity is not None else None,
        changes=_json(changes or {}),
        ip=ip,
    )
    db.add(row)
    return row


def entity_target(entity: Entity) -> tuple[str, uuid.UUID, str]:
    return ("entity", entity.id, entity.path_cache)


def record_entities_created(
    db: AsyncSession, actor: User | None, nodes: Iterable[Entity], *, ip: str | None = None
) -> None:
    """`entity.create` для каждого созданного узла (узлы уже получили id — после flush)."""
    for node in nodes:
        record_audit(
            db,
            actor,
            ENTITY_CREATE,
            target=entity_target(node),
            entity=node,
            changes=snapshot(node, FIELDS["entity"]),
            ip=ip,
        )
