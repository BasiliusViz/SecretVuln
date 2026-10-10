"""service accounts, api tokens, ai analyses

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def _timestamps() -> list[sa.Column]:
    # clock_timestamp: несколько выводов в одной транзакции различимы по времени
    return [
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("clock_timestamp()"), nullable=False),
    ]


def upgrade() -> None:
    op.execute("ALTER TYPE auth_source ADD VALUE IF NOT EXISTS 'service'")

    op.create_table(
        "api_tokens",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_timestamps(),
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])

    kind = postgresql.ENUM("summary", "triage", name="ai_analysis_kind")
    verdict = postgresql.ENUM("true_positive", "false_positive", "uncertain", name="ai_verdict")
    review = postgresql.ENUM("pending", "accepted", "rejected", name="ai_review_status")
    for t in (kind, verdict, review):
        t.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ai_analyses",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("finding_id", UUID, sa.ForeignKey("findings.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", postgresql.ENUM(name="ai_analysis_kind", create_type=False),
                  nullable=False),
        sa.Column("verdict", postgresql.ENUM(name="ai_verdict", create_type=False)),
        sa.Column("confidence", sa.Float),
        sa.Column("title_plain", sa.String(500)),
        sa.Column("explanation", sa.Text),
        sa.Column("remediation", sa.Text),
        sa.Column("agent", sa.String(100)),
        sa.Column("model", sa.String(100)),
        sa.Column("prompt_version", sa.String(50)),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("review_status", postgresql.ENUM(name="ai_review_status", create_type=False),
                  server_default="pending", nullable=False),
        sa.Column("reviewed_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_comment", sa.Text),
        *_timestamps(),
        sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
                           name="ck_ai_analyses_confidence"),
    )
    op.create_index("ix_ai_analyses_finding_id", "ai_analyses", ["finding_id"])

    op.add_column(
        "findings",
        sa.Column("ai_verdict", postgresql.ENUM(name="ai_verdict", create_type=False)),
    )
    op.create_index("ix_findings_ai_verdict", "findings", ["ai_verdict"])


def downgrade() -> None:
    op.drop_index("ix_findings_ai_verdict", table_name="findings")
    op.drop_column("findings", "ai_verdict")
    op.drop_table("ai_analyses")
    op.drop_table("api_tokens")
    for name in ("ai_review_status", "ai_verdict", "ai_analysis_kind"):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
    # значение 'service' в auth_source удалить нельзя — остаётся
