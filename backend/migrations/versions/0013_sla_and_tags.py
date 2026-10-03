"""SLA policies, entity tags, finding due dates

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-04

"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "sla_policies",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("days_critical", sa.Integer(), nullable=True),
        sa.Column("days_high", sa.Integer(), nullable=True),
        sa.Column("days_medium", sa.Integer(), nullable=True),
        sa.Column("days_low", sa.Integer(), nullable=True),
        sa.Column("days_info", sa.Integer(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "uq_sla_policies_default", "sla_policies", ["is_default"], unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.add_column("entities", sa.Column(
        "sla_policy_id", UUID, sa.ForeignKey("sla_policies.id", ondelete="RESTRICT"), nullable=True,
    ))
    op.add_column("entities", sa.Column(
        "tags", postgresql.ARRAY(sa.String(64)), nullable=False, server_default="{}",
    ))
    op.create_index("ix_entities_tags", "entities", ["tags"], postgresql_using="gin")

    op.add_column("findings", sa.Column("sla_start_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("findings", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("findings", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_findings_due_at", "findings", ["due_at"])

    policy_id = uuid.uuid4()
    op.execute(sa.text(
        "INSERT INTO sla_policies (id, name, days_critical, days_high, days_medium, days_low, "
        "days_info, is_default) VALUES (:id, 'Стандартная', 15, 30, 90, 180, NULL, true)"
    ).bindparams(id=policy_id))
    # Простой backfill: точность для старых находок не важна (решение этапа 3)
    op.execute(
        "UPDATE findings SET sla_start_at = first_seen, "
        "due_at = first_seen + make_interval(days => CASE severity "
        "  WHEN 'critical' THEN 15 WHEN 'high' THEN 30 WHEN 'medium' THEN 90 "
        "  WHEN 'low' THEN 180 END), "
        "resolved_at = CASE WHEN status IN ('fixed', 'false_positive', 'risk_accepted') "
        "  THEN last_seen END"
    )


def downgrade() -> None:
    op.drop_index("ix_findings_due_at", table_name="findings")
    for col in ("resolved_at", "due_at", "sla_start_at"):
        op.drop_column("findings", col)
    op.drop_index("ix_entities_tags", table_name="entities")
    op.drop_column("entities", "tags")
    op.drop_column("entities", "sla_policy_id")
    op.drop_index("uq_sla_policies_default", table_name="sla_policies")
    op.drop_table("sla_policies")
