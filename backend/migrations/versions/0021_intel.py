"""enrichment: intel_* reference tables, findings.cves/epss_max/kev/has_bdu

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-21

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
SOURCES = ("epss", "kev", "bdu", "cwe")


def upgrade() -> None:
    source = postgresql.ENUM(*SOURCES, name="intel_source")
    status = postgresql.ENUM("idle", "loading", "ok", "failed", name="intel_status")
    for t in (source, status):
        t.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "intel_epss",
        sa.Column("cve_id", sa.String(32), primary_key=True),
        sa.Column("epss", sa.Float, nullable=False),
        sa.Column("percentile", sa.Float, nullable=False),
        sa.Column("score_date", sa.Date),
    )
    op.create_table(
        "intel_kev",
        sa.Column("cve_id", sa.String(32), primary_key=True),
        sa.Column("date_added", sa.Date),
        sa.Column("name", sa.Text),
        sa.Column("ransomware", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("due_date", sa.Date),
    )
    op.create_table(
        "intel_bdu",
        sa.Column("bdu_id", sa.String(32), primary_key=True),
        sa.Column("name", sa.Text),
        sa.Column("severity", sa.Text),
    )
    op.create_table(
        "intel_bdu_cve",
        sa.Column("bdu_id", sa.String(32), primary_key=True),
        sa.Column("cve_id", sa.String(32), primary_key=True),
    )
    op.create_index("ix_intel_bdu_cve_cve_id", "intel_bdu_cve", ["cve_id"])
    op.create_table(
        "intel_cwe",
        sa.Column("cwe_id", sa.String(16), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("category", sa.Text),
    )
    op.create_table(
        "intel_sources",
        sa.Column("source", postgresql.ENUM(name="intel_source", create_type=False),
                  primary_key=True),
        sa.Column("status", postgresql.ENUM(name="intel_status", create_type=False),
                  server_default="idle", nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True)),
        sa.Column("loaded_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("file_date", sa.Date),
        sa.Column("record_count", sa.Integer),
        sa.Column("error", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        "INSERT INTO intel_sources (source, status) VALUES "
        "('epss', 'idle'), ('kev', 'idle'), ('bdu', 'idle'), ('cwe', 'idle')"
    )

    op.add_column(
        "findings",
        sa.Column("cves", postgresql.ARRAY(sa.String(32)), server_default="{}", nullable=False),
    )
    op.add_column("findings", sa.Column("epss_max", sa.Float))
    op.add_column(
        "findings", sa.Column("kev", sa.Boolean, server_default=sa.false(), nullable=False)
    )
    op.add_column(
        "findings", sa.Column("has_bdu", sa.Boolean, server_default=sa.false(), nullable=False)
    )
    op.create_index("ix_findings_cves", "findings", ["cves"], postgresql_using="gin")
    op.create_index("ix_findings_epss_max", "findings", ["epss_max"])
    op.create_index("ix_findings_kev", "findings", ["kev"])


def downgrade() -> None:
    op.drop_index("ix_findings_kev", table_name="findings")
    op.drop_index("ix_findings_epss_max", table_name="findings")
    op.drop_index("ix_findings_cves", table_name="findings")
    for col in ("has_bdu", "kev", "epss_max", "cves"):
        op.drop_column("findings", col)
    for table in ("intel_sources", "intel_cwe", "intel_bdu_cve", "intel_bdu", "intel_kev",
                  "intel_epss"):
        op.drop_table(table)
    for name in ("intel_status", "intel_source"):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
