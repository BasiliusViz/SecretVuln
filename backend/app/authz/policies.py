"""Права ролей в casbin_rule — через сессию запроса, в одной транзакции с ролью и аудитом.

Проверки прав читают casbin_rule SQL-запросом (`services/access.py`), in-memory
enforcer в запросах не участвует — он остаётся для CLI и тестов (`enforcer.py`).
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.access import casbin_rule


async def get_permissions(db: AsyncSession, names: list[str]) -> dict[str, list[tuple[str, str]]]:
    """{имя роли: [(resource, action), ...]} в порядке ресурса и действия."""
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    if not names:
        return out
    rows = await db.execute(
        select(casbin_rule.c.v0, casbin_rule.c.v1, casbin_rule.c.v2)
        .where(casbin_rule.c.ptype == "p", casbin_rule.c.v0.in_(names))
        .order_by(casbin_rule.c.v1, casbin_rule.c.v2)
    )
    for name, resource, action in rows:
        out[name].append((resource, action))
    return out


async def replace_permissions(db: AsyncSession, name: str, perms: list[tuple[str, str]]) -> None:
    """Полностью заменяет набор прав роли (без коммита)."""
    await delete_permissions(db, name)
    unique = sorted(set(perms))
    if unique:
        await db.execute(
            insert(casbin_rule),
            [{"ptype": "p", "v0": name, "v1": r, "v2": a} for r, a in unique],
        )


async def rename_permissions(db: AsyncSession, old: str, new: str) -> None:
    await db.execute(
        update(casbin_rule)
        .where(casbin_rule.c.ptype == "p", casbin_rule.c.v0 == old)
        .values(v0=new)
    )


async def delete_permissions(db: AsyncSession, name: str) -> None:
    await db.execute(
        delete(casbin_rule).where(casbin_rule.c.ptype == "p", casbin_rule.c.v0 == name)
    )
