"""pgvector: finding embeddings, ai_analyses.similar_ids

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-11

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "finding_embeddings",
        sa.Column("finding_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.execute(
        "CREATE INDEX ix_finding_embeddings_hnsw ON finding_embeddings "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.add_column(
        "ai_analyses",
        sa.Column("similar_ids", postgresql.JSONB(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("ai_analyses", "similar_ids")
    op.drop_table("finding_embeddings")
    # расширение vector не удаляем: им могут пользоваться другие базы/схемы
