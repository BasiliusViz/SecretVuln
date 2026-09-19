"""import metadata (branch/commit/scope), entity default branch, in_progress status

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PG >= 12 разрешает ADD VALUE в транзакции (значение не используется в этой же миграции)
    op.execute("ALTER TYPE finding_status ADD VALUE IF NOT EXISTS 'in_progress'")

    op.add_column("entities", sa.Column("default_branch", sa.String(255), nullable=True))

    op.add_column("imports", sa.Column("branch", sa.String(255), nullable=True))
    op.add_column("imports", sa.Column("commit_sha", sa.String(64), nullable=True))
    op.add_column("imports", sa.Column("pipeline_url", sa.String(1024), nullable=True))
    op.add_column("imports", sa.Column("scan_scope", sa.String(255), nullable=True))
    op.add_column(
        "imports",
        sa.Column("close_missing", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "imports",
        sa.Column("confirm_empty", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.add_column("findings", sa.Column("scan_scope", sa.String(255), nullable=True))
    op.add_column("findings", sa.Column("commit_sha", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("findings", "commit_sha")
    op.drop_column("findings", "scan_scope")
    for col in ("confirm_empty", "close_missing", "scan_scope", "pipeline_url", "commit_sha", "branch"):
        op.drop_column("imports", col)
    op.drop_column("entities", "default_branch")
    # значение enum 'in_progress' в PostgreSQL удалить нельзя — остаётся
