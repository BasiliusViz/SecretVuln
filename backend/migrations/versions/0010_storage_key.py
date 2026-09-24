"""imports.s3_key -> storage_key (file storage can be local disk or S3)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-24

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("imports", "s3_key", new_column_name="storage_key")


def downgrade() -> None:
    op.alter_column("imports", "storage_key", new_column_name="s3_key")
