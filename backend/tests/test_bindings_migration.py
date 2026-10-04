"""Миграция 0014: строки group_roles становятся глобальными привязками."""

from __future__ import annotations

import uuid

import psycopg
from alembic import command
from alembic.config import Config

from app.core.config import get_settings
from tests.conftest import BACKEND_DIR


def _cfg() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def test_group_roles_become_global_bindings():
    url = get_settings().database_url_sync.replace("+psycopg", "")
    cfg = _cfg()
    command.downgrade(cfg, "0013")
    try:
        gid, rid = uuid.uuid4(), uuid.uuid4()
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO user_groups (id, name, source) VALUES (%s, 'team', 'manual')",
                (gid,),
            )
            conn.execute(
                "INSERT INTO roles (id, name, is_builtin) VALUES (%s, 'Разработчик', false)",
                (rid,),
            )
            conn.execute(
                "INSERT INTO group_roles (group_id, role_id) VALUES (%s, %s)", (gid, rid)
            )
        command.upgrade(cfg, "head")
        with psycopg.connect(url) as conn:
            rows = conn.execute(
                "SELECT group_id, role_id, entity_id FROM role_bindings"
            ).fetchall()
            assert rows == [(gid, rid, None)]
            exists = conn.execute("SELECT to_regclass('group_roles')").fetchone()[0]
            assert exists is None
    finally:
        command.upgrade(cfg, "head")
