"""short sequential finding numbers (SV-N)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE finding_number_seq")
    # Существующие строки получат номера из последовательности при добавлении столбца
    op.add_column(
        "findings",
        sa.Column(
            "number",
            sa.BigInteger(),
            server_default=sa.text("nextval('finding_number_seq')"),
            nullable=False,
        ),
    )
    op.execute("ALTER SEQUENCE finding_number_seq OWNED BY findings.number")
    op.create_index("ix_findings_number", "findings", ["number"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_findings_number", table_name="findings")
    op.drop_column("findings", "number")  # последовательность удалится вместе со столбцом (OWNED BY)
