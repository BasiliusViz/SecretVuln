"""entity slug and materialized path

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-24

"""
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Копия slugify из app/services/entity_paths.py на момент миграции —
# миграции не импортируют код приложения, чтобы не меняться вместе с ним.
_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
})


def _slugify(name: str) -> str:
    slug = name.strip().lower().translate(_TRANSLIT)
    slug = re.sub(r"[^a-z0-9._-]+", "-", slug).strip("-._")
    return slug[:100].rstrip("-._") or "project"


def upgrade() -> None:
    op.add_column("entities", sa.Column("slug", sa.String(100), nullable=True))
    op.add_column("entities", sa.Column("path_cache", sa.String(2048), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, name, parent_id FROM entities")).all()
    children: dict = {}
    for id_, name, parent_id in rows:
        children.setdefault(parent_id, []).append((id_, name))

    stack: list[tuple[object, str]] = [(None, "")]
    while stack:
        parent_id, parent_path = stack.pop()
        used: set[str] = set()
        for id_, name in sorted(children.get(parent_id, []), key=lambda r: r[1]):
            base = _slugify(name)
            slug, n = base, 2
            while slug in used:
                slug = f"{base[:95]}-{n}"
                n += 1
            used.add(slug)
            path = f"{parent_path}/{slug}" if parent_path else slug
            conn.execute(
                sa.text("UPDATE entities SET slug = :s, path_cache = :p WHERE id = :id"),
                {"s": slug, "p": path, "id": id_},
            )
            stack.append((id_, path))

    op.alter_column("entities", "slug", nullable=False)
    op.alter_column("entities", "path_cache", nullable=False)
    op.execute(
        "ALTER TABLE entities ADD CONSTRAINT uq_entities_parent_slug "
        "UNIQUE NULLS NOT DISTINCT (parent_id, slug)"
    )
    op.create_index(
        "ix_entities_path_cache", "entities", ["path_cache"], unique=True,
        postgresql_ops={"path_cache": "text_pattern_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_entities_path_cache", table_name="entities")
    op.drop_constraint("uq_entities_parent_slug", "entities", type_="unique")
    op.drop_column("entities", "path_cache")
    op.drop_column("entities", "slug")
