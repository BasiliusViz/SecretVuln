"""Доступ пользователя: право → «везде» или набор префиксов путей проектов.

Собирается на каждый запрос одним SQL-запросом (`load_access`): группы
пользователя → привязки → путь узла → права роли из `casbin_rule`. Права читаются
из БД, а не из in-memory enforcer: иначе правка роли в одном процессе API не видна
другим. Права только складываются, запретов нет.

Проект E разрешён префиксом p, если `path(E) == p` или начинается с `p + "/"`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, String, and_, column, false, func, or_, select, table, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz.permissions import ALL_PERMISSIONS, ANY_BINDING, GLOBAL_ONLY, is_scoped
from app.models import Entity, RoleBinding, user_group_members
from app.models.role import Role

# None в значении — «везде» (на всё дерево)
Scope = frozenset[str] | None

casbin_rule = table(
    "casbin_rule",
    column("ptype", String),
    column("v0", String),
    column("v1", String),
    column("v2", String),
)


def in_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def ancestors(path: str) -> list[str]:
    """Пути строгих предков: `a/b/c` → [`a`, `a/b`]."""
    parts = path.split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts))]


def collapse(prefixes: Iterable[str]) -> frozenset[str]:
    """Убирает префиксы, вложенные в другие (`fintech` поглощает `fintech/payments`)."""
    items = set(prefixes)
    return frozenset(p for p in items if not any(a in items for a in ancestors(p)))


def _path_of(target: Entity | str) -> str:
    return target if isinstance(target, str) else target.path_cache


@dataclass(frozen=True)
class Access:
    user_id: uuid.UUID | None = None
    is_superuser: bool = False
    grants: dict[str, Scope] = field(default_factory=dict)
    role_names: frozenset[str] = frozenset()

    @classmethod
    def build(
        cls,
        rows: Iterable[tuple[str | None, str, str]],
        *,
        user_id: uuid.UUID | None = None,
        is_superuser: bool = False,
        role_names: Iterable[str] = (),
    ) -> Access:
        """rows: (путь узла привязки или None для глобальной, ресурс, действие)."""
        if is_superuser:
            grants: dict[str, Scope] = {p: None for p in ALL_PERMISSIONS}
            return cls(user_id, True, grants, frozenset(role_names))
        everywhere: set[str] = set()
        prefixes: dict[str, set[str]] = {}
        for path, resource, action in rows:
            perm = f"{resource}:{action}"
            if path is None or perm in ANY_BINDING:
                everywhere.add(perm)
            elif perm in GLOBAL_ONLY:
                continue  # в привязке к проекту не действует
            else:
                prefixes.setdefault(perm, set()).add(path)
        grants = {p: None for p in everywhere}
        for perm, paths in prefixes.items():
            if perm not in grants:
                grants[perm] = collapse(paths)
        return cls(user_id, False, grants, frozenset(role_names))

    # --- проверки ---

    def anywhere(self, perm: str) -> bool:
        """Право есть хоть где-то (ворота эндпоинта, пункты меню)."""
        return perm in self.grants

    def is_global(self, perm: str) -> bool:
        return perm in self.grants and self.grants[perm] is None

    def allows(self, perm: str, target: Entity | str | None) -> bool:
        """Право на проект (и всё его поддерево). `None` — глобальное действие."""
        if perm not in self.grants:
            return False
        scope = self.grants[perm]
        if scope is None:
            return True
        if target is None:
            return False
        path = _path_of(target)
        return any(in_prefix(path, p) for p in scope)

    def prefixes(self, perm: str) -> Scope:
        """None — везде; иначе префиксы (пустой набор — нигде)."""
        if perm not in self.grants:
            return frozenset()
        return self.grants[perm]

    def filter(self, perm: str, path_column) -> ColumnElement[bool]:
        """SQL-условие «проект разрешён по праву» для списков."""
        scope = self.prefixes(perm)
        if scope is None:
            return true()
        return _prefix_condition(scope, path_column)

    def entity_scope(self, perm: str, entity_id_column) -> ColumnElement[bool]:
        """SQL-условие на колонку `entity_id`: проект разрешён по праву."""
        scope = self.prefixes(perm)
        if scope is None:
            return true()
        if not scope:
            return false()
        return entity_id_column.in_(
            select(Entity.id).where(_prefix_condition(scope, Entity.path_cache))
        )

    # --- видимость заглушек ---

    def _all_prefixes(self) -> Scope:
        """Объединение областей прав на поддерево (глобальные справочные права —
        `group:read`, `role:*` и т. п. — видимости проектов не дают)."""
        out: set[str] = set()
        for perm, scope in self.grants.items():
            if not is_scoped(perm):
                continue
            if scope is None:
                return None
            out |= scope
        return collapse(out)

    def can_see(self, target: Entity | str) -> bool:
        """Узел виден хотя бы заглушкой: любое право на него, его потомка или предка."""
        scope = self._all_prefixes()
        if scope is None:
            return True
        path = _path_of(target)
        return any(in_prefix(path, p) or in_prefix(p, path) for p in scope)

    def visible_filter(self, path_column) -> ColumnElement[bool]:
        """SQL-условие видимости заглушкой (узлы под правами + их предки)."""
        scope = self._all_prefixes()
        if scope is None:
            return true()
        if not scope:
            return false()
        anc = sorted({a for p in scope for a in ancestors(p)})
        cond = _prefix_condition(scope, path_column)
        return or_(cond, path_column.in_(anc)) if anc else cond

    def scoped_permissions(self) -> dict[str, str | list[str]]:
        return {
            perm: "*" if scope is None else sorted(scope)
            for perm, scope in sorted(self.grants.items())
        }


def _prefix_condition(scope: frozenset[str], path_column) -> ColumnElement[bool]:
    if not scope:
        return false()
    return or_(
        *[
            or_(path_column == p, func.starts_with(path_column, p + "/"))
            for p in sorted(scope)
        ]
    )


async def load_access(db: AsyncSession, user) -> Access:
    stmt = (
        select(Entity.path_cache, casbin_rule.c.v1, casbin_rule.c.v2, Role.name)
        .select_from(user_group_members)
        .join(RoleBinding, RoleBinding.group_id == user_group_members.c.group_id)
        .join(Role, Role.id == RoleBinding.role_id)
        .outerjoin(Entity, Entity.id == RoleBinding.entity_id)
        .outerjoin(
            casbin_rule,
            and_(casbin_rule.c.ptype == "p", casbin_rule.c.v0 == Role.name),
        )
        .where(user_group_members.c.user_id == user.id)
    )
    rows = (await db.execute(stmt)).all()
    return Access.build(
        [(path, res, act) for path, res, act, _ in rows if res is not None],
        user_id=user.id,
        is_superuser=user.is_superuser,
        role_names={name for *_, name in rows},
    )
