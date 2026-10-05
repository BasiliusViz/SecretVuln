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
from urllib.parse import urlsplit, urlunsplit

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Entity, SlaPolicy, User, UserGroup
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

# Ссылки, рядом с которыми пишется имя: UUID в журнале ничего не скажет аудитору,
# а объект к моменту чтения может быть удалён или переименован.
NAMED_REFS: dict[str, tuple[str, Any]] = {
    "parent_id": ("parent", Entity.path_cache),
    "owner_group_id": ("owner_group", UserGroup.name),
    "sla_policy_id": ("sla_policy", SlaPolicy.name),
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


def _strip_userinfo(value: Any) -> Any:
    """`https://user:token@host/x` → `https://host/x`: учётные данные в URL — тоже секрет."""
    if not isinstance(value, str) or "@" not in value:
        return value
    parts = urlsplit(value)
    if not parts.username and not parts.password:
        return value
    # netloc после «@», а не hostname: у IPv6 сохраняются скобки
    return urlunsplit(parts._replace(netloc=parts.netloc.rpartition("@")[2]))


def snapshot(obj: Any, fields: Iterable[str]) -> dict[str, Any]:
    """Значения разрешённых полей объекта в JSON-виде (для create/delete и как `before`)."""
    return {
        f: _json(_strip_userinfo(getattr(obj, f, None)) if f.endswith("_url") else getattr(obj, f, None))
        for f in _allowed(fields)
    }


def diff(before: dict[str, Any], after: dict[str, Any], fields: Iterable[str]) -> dict[str, list]:
    """`{поле: [было, стало]}` только по разрешённым и реально изменившимся полям."""
    out: dict[str, list] = {}
    for f in _allowed(fields):
        old, new = _json(before.get(f)), _json(after.get(f))
        if old != new:
            out[f] = [old, new]
    return out


async def with_names(db: AsyncSession, changes: dict[str, Any]) -> dict[str, Any]:
    """Добавить к `parent_id`/`owner_group_id`/`sla_policy_id` соседний ключ с именем.

    Форма значения та же: скаляр для снимка, `[было, стало]` для разницы.
    """
    def ids(value: Any) -> list[Any]:
        return value if isinstance(value, list) else [value]

    names: dict[str, str] = {}
    for key, (_, column) in NAMED_REFS.items():
        if key not in changes:
            continue
        wanted = {uuid.UUID(str(v)) for v in ids(changes[key]) if v}
        if wanted:
            model = column.class_
            rows = await db.execute(select(model.id, column).where(model.id.in_(wanted)))
            names.update({str(i): n for i, n in rows.all()})
    out: dict[str, Any] = {}
    for key, value in changes.items():
        out[key] = value
        if key in NAMED_REFS:
            name_key = NAMED_REFS[key][0]
            if isinstance(value, list):
                out[name_key] = [names.get(str(v)) if v else None for v in value]
            else:
                out[name_key] = names.get(str(value)) if value else None
    return out


async def rules_with_names(
    db: AsyncSession, before: list[dict], after: list[dict]
) -> list[list[dict]]:
    """Правила владения `[было, стало]` с именем группы рядом с `group_id`."""
    wanted = {uuid.UUID(r["group_id"]) for r in (*before, *after)}
    rows = await db.execute(select(UserGroup.id, UserGroup.name).where(UserGroup.id.in_(wanted)))
    names = {str(i): n for i, n in rows.all()}
    return [[{**r, "group": names.get(r["group_id"])} for r in side] for side in (before, after)]


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


async def record_entities_created(
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
            changes=await with_names(db, snapshot(node, FIELDS["entity"])),
            ip=ip,
        )
