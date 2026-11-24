"""findings.cwe: only the CWE id (Semgrep tags were stored as «CWE-89: Improper …»)

Revision ID: 0022
Revises: 0021
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        UPDATE findings
           SET cwe = 'CWE-' || substring(cwe from '^\s*[Cc][Ww][Ee]-(\d+)')
         WHERE cwe IS NOT NULL
           AND cwe !~ '^CWE-\d+$'
           AND cwe ~ '^\s*[Cc][Ww][Ee]-\d+'
        """
    )


def downgrade() -> None:
    # Исходный текст тега не сохранён — откатывать нечего
    pass
