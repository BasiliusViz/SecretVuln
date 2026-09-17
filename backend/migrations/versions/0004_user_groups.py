"""user groups + membership

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-07

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_groups",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.Enum("manual", "ldap", name="group_source"),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("ldap_group", sa.String(512), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_groups_name", "user_groups", ["name"], unique=True)
    op.create_index("ix_user_groups_ldap_group", "user_groups", ["ldap_group"])

    op.create_table(
        "user_group_members",
        sa.Column(
            "group_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("user_group_members")
    op.drop_index("ix_user_groups_ldap_group", table_name="user_groups")
    op.drop_index("ix_user_groups_name", table_name="user_groups")
    op.drop_table("user_groups")
    sa.Enum(name="group_source").drop(op.get_bind(), checkfirst=True)
