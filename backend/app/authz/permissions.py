"""Каталог прав: какие действия осмысленны для каждого ресурса.

Право = ресурс + действие. Роль — набор прав (хранится в casbin_rule как
p-политики: p, <role>, <resource>, <action>). UI рисует матрицу по этому каталогу.

Роль выдаётся группе привязкой на проект (поддерево) или на всё дерево. Права
делятся на три вида:
- действующие на поддерево (`entity:*`, `finding:*`, `import:*`, `sla:assign`,
  `access:manage`) — проверяются по пути проекта;
- только глобальные (`GLOBAL_ONLY`) — в привязке к проекту игнорируются;
- из любой привязки (`ANY_BINDING`) — действуют глобально, даже если роль выдана
  на проект: без них команда не назначит находку и не увидит свою SLA-политику.
"""

from __future__ import annotations

# ресурс → допустимые действия
CATALOG: dict[str, list[str]] = {
    "entity": ["read", "write", "delete"],
    "finding": ["read", "write", "delete", "triage", "approve"],
    "import": ["read", "import", "delete"],
    "group": ["read", "write", "delete"],
    "role": ["read", "write", "delete"],
    "sla": ["read", "manage", "assign"],
    "access": ["manage"],
}

RESOURCES: list[str] = list(CATALOG.keys())
ACTIONS: list[str] = [
    "read", "write", "delete", "import", "triage", "approve", "manage", "assign",
]

GLOBAL_ONLY: frozenset[str] = frozenset(
    {"group:write", "group:delete", "role:read", "role:write", "role:delete", "sla:manage"}
)
ANY_BINDING: frozenset[str] = frozenset({"group:read", "sla:read"})

ALL_PERMISSIONS: list[str] = [f"{r}:{a}" for r, actions in CATALOG.items() for a in actions]


def is_valid(resource: str, action: str) -> bool:
    return action in CATALOG.get(resource, [])


def is_scoped(perm: str) -> bool:
    """Право проверяется по поддереву (а не глобально)."""
    return perm not in GLOBAL_ONLY and perm not in ANY_BINDING
