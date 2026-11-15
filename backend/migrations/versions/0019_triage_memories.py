"""team memory: triage_memories, findings.memory_id, decision_requests.memory_id

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-16

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.execute("ALTER TYPE finding_event_type ADD VALUE IF NOT EXISTS 'memory_hint'")

    status = postgresql.ENUM("suggested", "approved", "disabled", name="memory_status")
    source = postgresql.ENUM("manual", "suggested", name="memory_source")
    for t in (status, source):
        t.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "triage_memories",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("entity_id", UUID, sa.ForeignKey("entities.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("scanner", sa.String(100)),
        sa.Column("rule_id", sa.String(512)),
        sa.Column("cwe", sa.String(50)),
        sa.Column("path_glob", sa.String(1024)),
        sa.Column("decision", postgresql.ENUM(name="decision_type", create_type=False),
                  nullable=False),
        sa.Column("reason_tag", postgresql.ENUM(name="reason_tag", create_type=False)),
        sa.Column("reason", sa.Text),
        sa.Column("status", postgresql.ENUM(name="memory_status", create_type=False),
                  server_default="approved", nullable=False),
        sa.Column("source", postgresql.ENUM(name="memory_source", create_type=False),
                  server_default="manual", nullable=False),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "scanner IS NOT NULL OR rule_id IS NOT NULL OR cwe IS NOT NULL "
            "OR path_glob IS NOT NULL",
            name="ck_triage_memories_condition",
        ),
    )
    op.create_index("ix_triage_memories_entity_id", "triage_memories", ["entity_id"])
    op.create_index("ix_triage_memories_status", "triage_memories", ["status"])

    op.add_column(
        "findings",
        sa.Column("memory_id", UUID, sa.ForeignKey("triage_memories.id", ondelete="SET NULL")),
    )
    op.create_index("ix_findings_memory_id", "findings", ["memory_id"])
    op.add_column(
        "decision_requests",
        sa.Column("memory_id", UUID, sa.ForeignKey("triage_memories.id", ondelete="SET NULL")),
    )


def downgrade() -> None:
    op.drop_column("decision_requests", "memory_id")
    op.drop_index("ix_findings_memory_id", table_name="findings")
    op.drop_column("findings", "memory_id")
    op.drop_table("triage_memories")
    for name in ("memory_source", "memory_status"):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
    # значение 'memory_hint' в finding_event_type удалить нельзя — остаётся
