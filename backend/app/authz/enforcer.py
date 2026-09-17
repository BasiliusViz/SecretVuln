"""Casbin-enforcer (синглтон) на sync-адаптере SQLAlchemy.

Политики (роль→право) хранятся в таблице casbin_rule, которую создаёт сам
адаптер (в наших миграциях её нет). enforce() — in-memory, быстрый.
Изменения политик пишутся через адаптер сразу в БД.
"""

from __future__ import annotations

import os
import threading

import casbin
from casbin_sqlalchemy_adapter import Adapter

from app.core.config import get_settings

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "rbac_model.conf")
_enforcer: casbin.Enforcer | None = None
_lock = threading.Lock()


def get_enforcer() -> casbin.Enforcer:
    global _enforcer
    if _enforcer is None:
        with _lock:
            if _enforcer is None:
                settings = get_settings()
                adapter = Adapter(settings.database_url_sync)
                _enforcer = casbin.Enforcer(_MODEL_PATH, adapter)
    return _enforcer


def role_permissions(role: str) -> list[tuple[str, str]]:
    """Список (resource, action) для роли."""
    enf = get_enforcer()
    out: list[tuple[str, str]] = []
    for pol in enf.get_filtered_policy(0, role):
        # pol = [sub, obj, act]
        if len(pol) >= 3:
            out.append((pol[1], pol[2]))
    return out


def set_role_permissions(role: str, perms: list[tuple[str, str]]) -> None:
    """Полностью заменяет набор прав роли."""
    enf = get_enforcer()
    for pol in list(enf.get_filtered_policy(0, role)):
        enf.remove_policy(*pol)
    for resource, action in perms:
        enf.add_policy(role, resource, action)


def rename_role_policies(old: str, new: str) -> None:
    perms = role_permissions(old)
    set_role_permissions(old, [])
    set_role_permissions(new, perms)


def delete_role_policies(role: str) -> None:
    set_role_permissions(role, [])


def check(roles: list[str], resource: str, action: str) -> bool:
    enf = get_enforcer()
    return any(enf.enforce(r, resource, action) for r in roles)
