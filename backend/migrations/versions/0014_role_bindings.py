"""role bindings: group + role + entity subtree (replaces group_roles)

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-05

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    # casbin_rule создаёт адаптер при первом запуске; права ролей теперь читаются
    # SQL-запросом, поэтому таблица должна существовать сразу (схема — как у адаптера).
    op.execute(
        "CREATE TABLE IF NOT EXISTS casbin_rule ("
        "id SERIAL PRIMARY KEY, ptype VARCHAR(255), "
        "v0 VARCHAR(255), v1 VARCHAR(255), v2 VARCHAR(255), "
        "v3 VARCHAR(255), v4 VARCHAR(255), v5 VARCHAR(255))"
    )
    op.create_table(
        "role_bindings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "group_id", UUID, sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role_id", UUID, sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "entity_id", UUID, sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.UniqueConstraint(
            "group_id",
            "role_id",
            "entity_id",
            name="uq_role_bindings_group_role_entity",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_role_bindings_group_id", "role_bindings", ["group_id"])
    op.create_index("ix_role_bindings_role_id", "role_bindings", ["role_id"])
    op.create_index("ix_role_bindings_entity_id", "role_bindings", ["entity_id"])
    op.execute(
        "INSERT INTO role_bindings (id, group_id, role_id, entity_id) "
        "SELECT gen_random_uuid(), group_id, role_id, NULL FROM group_roles"
    )
    op.drop_table("group_roles")


def downgrade() -> None:
    op.create_table(
        "group_roles",
        sa.Column(
            "group_id",
            UUID,
            sa.ForeignKey("user_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role_id", UUID, sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    )
    # Обратно переносятся только глобальные привязки: проектных в старой схеме не было.
    op.execute(
        "INSERT INTO group_roles (group_id, role_id) "
        "SELECT DISTINCT group_id, role_id FROM role_bindings WHERE entity_id IS NULL"
    )
    op.drop_table("role_bindings")
