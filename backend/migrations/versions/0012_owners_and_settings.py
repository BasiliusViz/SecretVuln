"""owners, project settings with pinning, ownership rules, help requests

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-24

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    for value in ("assigned", "comment", "help_requested", "help_resolved"):
        op.execute(f"ALTER TYPE finding_event_type ADD VALUE IF NOT EXISTS '{value}'")

    repo_type = postgresql.ENUM("gitlab", "github", "gitea", "bitbucket", name="repo_type")
    repo_type.create(op.get_bind(), checkfirst=True)

    op.add_column("entities", sa.Column(
        "owner_group_id", UUID, sa.ForeignKey("user_groups.id", ondelete="SET NULL"), nullable=True,
    ))
    op.add_column("entities", sa.Column("repo_url", sa.String(1024), nullable=True))
    op.add_column("entities", sa.Column(
        "repo_type", postgresql.ENUM(name="repo_type", create_type=False), nullable=True,
    ))
    op.add_column("entities", sa.Column("repo_path_prefix", sa.String(512), nullable=True))
    op.add_column("entities", sa.Column(
        "pinned_fields", postgresql.ARRAY(sa.String(50)), nullable=False, server_default="{}",
    ))
    op.add_column("entities", sa.Column("config_file", postgresql.JSONB(), nullable=True))
    op.add_column("entities", sa.Column("config_commit_sha", sa.String(64), nullable=True))
    op.add_column("entities", sa.Column("config_applied_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_entities_repo_url", "entities", ["repo_url"], unique=True,
        postgresql_where=sa.text("repo_url IS NOT NULL"),
    )

    op.create_table(
        "ownership_rules",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("entity_id", UUID, sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pattern", sa.String(512), nullable=False),
        sa.Column("group_id", UUID, sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source", sa.Enum("file", "manual", name="rule_source"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ownership_rules_entity_id", "ownership_rules", ["entity_id"])

    op.add_column("findings", sa.Column(
        "assignee_group_id", UUID, sa.ForeignKey("user_groups.id", ondelete="SET NULL"), nullable=True,
    ))
    op.add_column("findings", sa.Column(
        "assignee_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    ))
    op.create_index("ix_findings_assignee_group_id", "findings", ["assignee_group_id"])
    op.create_index("ix_findings_assignee_user_id", "findings", ["assignee_user_id"])
    op.add_column("findings", sa.Column(
        "assigned_manually", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.add_column("findings", sa.Column("help_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("findings", sa.Column("help_text", sa.Text(), nullable=True))

    op.add_column("imports", sa.Column("repo_url", sa.String(1024), nullable=True))
    op.add_column("imports", sa.Column(
        "config_warnings", postgresql.JSONB(), nullable=False, server_default="[]",
    ))


def downgrade() -> None:
    op.drop_column("imports", "config_warnings")
    op.drop_column("imports", "repo_url")
    for col in ("help_text", "help_requested_at", "assigned_manually"):
        op.drop_column("findings", col)
    op.drop_index("ix_findings_assignee_user_id", table_name="findings")
    op.drop_index("ix_findings_assignee_group_id", table_name="findings")
    op.drop_column("findings", "assignee_user_id")
    op.drop_column("findings", "assignee_group_id")
    op.drop_index("ix_ownership_rules_entity_id", table_name="ownership_rules")
    op.drop_table("ownership_rules")
    sa.Enum(name="rule_source").drop(op.get_bind(), checkfirst=True)
    op.drop_index("uq_entities_repo_url", table_name="entities")
    for col in (
        "config_applied_at", "config_commit_sha", "config_file", "pinned_fields",
        "repo_path_prefix", "repo_type", "repo_url", "owner_group_id",
    ):
        op.drop_column("entities", col)
    sa.Enum(name="repo_type").drop(op.get_bind(), checkfirst=True)
    # значения finding_event_type в PostgreSQL удалить нельзя — остаются
