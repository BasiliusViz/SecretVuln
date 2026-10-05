"""audit log

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-05

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    actor_type = postgresql.ENUM(name="actor_type", create_type=False)
    op.create_table(
        "audit_log",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("actor_type", actor_type, nullable=False),
        sa.Column("actor_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("actor_label", sa.String(255)),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(50)),
        sa.Column("target_id", UUID),
        sa.Column("target_label", sa.String(1024)),
        sa.Column("entity_id", UUID, sa.ForeignKey("entities.id", ondelete="SET NULL")),
        sa.Column("entity_path", sa.String(1024)),
        sa.Column(
            "changes",
            postgresql.JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("ip", sa.String(64)),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_entity_created", "audit_log", ["entity_id", "created_at"])
    op.create_index("ix_audit_log_actor_created", "audit_log", ["actor_id", "created_at"])


def downgrade() -> None:
    op.drop_table("audit_log")
