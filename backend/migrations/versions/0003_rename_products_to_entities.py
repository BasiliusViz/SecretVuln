"""rename products to entities, drop item_type

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-02

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("products", "entities")
    op.drop_column("entities", "item_type")
    op.alter_column("findings", "product_id", new_column_name="entity_id")
    op.alter_column("imports", "product_id", new_column_name="entity_id")

    op.execute("ALTER INDEX ix_products_name RENAME TO ix_entities_name")
    op.execute("ALTER INDEX ix_products_parent_id RENAME TO ix_entities_parent_id")
    op.execute("ALTER INDEX uq_products_parent_name RENAME TO uq_entities_parent_name")
    op.execute("ALTER INDEX ix_findings_product_id RENAME TO ix_findings_entity_id")
    op.execute("ALTER INDEX ix_imports_product_id RENAME TO ix_imports_entity_id")
    op.execute(
        "ALTER TABLE findings RENAME CONSTRAINT uq_findings_product_fingerprint"
        " TO uq_findings_entity_fingerprint"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE findings RENAME CONSTRAINT uq_findings_entity_fingerprint"
        " TO uq_findings_product_fingerprint"
    )
    op.execute("ALTER INDEX ix_imports_entity_id RENAME TO ix_imports_product_id")
    op.execute("ALTER INDEX ix_findings_entity_id RENAME TO ix_findings_product_id")
    op.execute("ALTER INDEX uq_entities_parent_name RENAME TO uq_products_parent_name")
    op.execute("ALTER INDEX ix_entities_parent_id RENAME TO ix_products_parent_id")
    op.execute("ALTER INDEX ix_entities_name RENAME TO ix_products_name")

    op.alter_column("imports", "entity_id", new_column_name="product_id")
    op.alter_column("findings", "entity_id", new_column_name="product_id")
    op.add_column(
        "entities",
        sa.Column("item_type", sa.String(50), nullable=False, server_default="продукт"),
    )
    op.rename_table("entities", "products")
