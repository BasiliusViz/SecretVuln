"""team memory: suggest_key for suggestions, memory_hint_removed event

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-20

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE finding_event_type ADD VALUE IF NOT EXISTS 'memory_hint_removed'")
    op.add_column("triage_memories", sa.Column("suggest_key", sa.String(800)))
    op.create_index(
        "ux_triage_memories_suggest_key", "triage_memories", ["suggest_key"], unique=True
    )
    # ключ происхождения для уже созданных предложений (по одному на ключ — самое раннее)
    op.execute(
        """
        UPDATE triage_memories t SET suggest_key = k.key
        FROM (
            SELECT DISTINCT ON (key) id, key FROM (
                SELECT id, created_at,
                       entity_id::text || '|' || lower(trim(coalesce(scanner, ''))) || '|'
                       || rule_id || '|' || decision::text AS key
                FROM triage_memories
                WHERE source = 'suggested' AND rule_id IS NOT NULL
            ) s
            ORDER BY key, created_at, id
        ) k
        WHERE t.id = k.id
        """
    )


def downgrade() -> None:
    op.drop_index("ux_triage_memories_suggest_key", table_name="triage_memories")
    op.drop_column("triage_memories", "suggest_key")
    # значение 'memory_hint_removed' в finding_event_type удалить нельзя — остаётся
