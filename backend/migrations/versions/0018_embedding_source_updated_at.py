"""finding_embeddings.source_updated_at: version of the finding the vector was built from

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-11

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL у старых строк — пересверка хеша при следующем embed_pending
    op.add_column(
        "finding_embeddings",
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("finding_embeddings", "source_updated_at")
