"""Каталог прав: какие действия осмысленны для каждого ресурса.

Право = ресурс + действие. Роль — набор прав (хранится в casbin_rule как
p-политики: p, <role>, <resource>, <action>). UI рисует матрицу по этому каталогу.
"""

from __future__ import annotations

# ресурс → допустимые действия
CATALOG: dict[str, list[str]] = {
    "entity": ["read", "write", "delete"],
    "finding": ["read", "write", "delete", "triage", "approve"],
    "import": ["read", "import", "delete"],
    "group": ["read", "write", "delete"],
    "role": ["read", "write", "delete"],
    "sla": ["read", "manage"],
}

RESOURCES: list[str] = list(CATALOG.keys())
ACTIONS: list[str] = ["read", "write", "delete", "import", "triage", "approve", "manage"]


def is_valid(resource: str, action: str) -> bool:
    return action in CATALOG.get(resource, [])
