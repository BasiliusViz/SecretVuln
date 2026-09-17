"""product hierarchy: parent_id + item_type, name unique per parent

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-02

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "products",
        sa.Column("item_type", sa.String(50), nullable=False, server_default="продукт"),
    )
    op.create_index("ix_products_parent_id", "products", ["parent_id"])
    # Name is now unique among siblings, not globally
    op.drop_index("ix_products_name", table_name="products")
    op.create_index("ix_products_name", "products", ["name"])
    op.create_index(
        "uq_products_parent_name",
        "products",
        ["parent_id", "name"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_index("uq_products_parent_name", table_name="products")
    op.drop_index("ix_products_name", table_name="products")
    op.create_index("ix_products_name", "products", ["name"], unique=True)
    op.drop_index("ix_products_parent_id", table_name="products")
    op.drop_column("products", "item_type")
    op.drop_column("products", "parent_id")
