"""decision requests (false positive / risk acceptance with approval)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("findings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "decision_type",
            sa.Enum("false_positive", "risk_accepted", name="decision_type"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", "expired", name="decision_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "reason_tag",
            sa.Enum(
                "data_not_user_controlled", "test_code", "sanitized", "dead_code", "other",
                name="reason_tag",
            ),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "requested_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "decided_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_decision_requests_finding_id", "decision_requests", ["finding_id"])
    op.create_index("ix_decision_requests_status", "decision_requests", ["status"])
    op.create_index(
        "uq_decision_requests_pending",
        "decision_requests",
        ["finding_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_decision_requests_pending", table_name="decision_requests")
    op.drop_index("ix_decision_requests_status", table_name="decision_requests")
    op.drop_index("ix_decision_requests_finding_id", table_name="decision_requests")
    op.drop_table("decision_requests")
    for name in ("reason_tag", "decision_status", "decision_type"):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
