"""finding events (history / audit log)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    finding_status = postgresql.ENUM(name="finding_status", create_type=False)
    op.create_table(
        "finding_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("findings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_type",
            sa.Enum(
                "imported", "status_changed", "reopened", "auto_fixed",
                "request_created", "request_decided",
                name="finding_event_type",
            ),
            nullable=False,
        ),
        sa.Column("actor_type", sa.Enum("user", "agent", "system", name="actor_type"), nullable=False),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_status", finding_status, nullable=True),
        sa.Column("to_status", finding_status, nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reason_tag", sa.String(50), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_finding_events_finding_id", "finding_events", ["finding_id"])
    op.create_index("ix_finding_events_created_at", "finding_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_finding_events_created_at", table_name="finding_events")
    op.drop_index("ix_finding_events_finding_id", table_name="finding_events")
    op.drop_table("finding_events")
    sa.Enum(name="actor_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="finding_event_type").drop(op.get_bind(), checkfirst=True)
