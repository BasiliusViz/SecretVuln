"""Общие фикстуры. Нужен Postgres из docker-compose (docker compose up -d postgres)."""

from __future__ import annotations

import os

os.environ.setdefault(
    "SV_DATABASE_URL",
    "postgresql+asyncpg://secretvuln:secretvuln@localhost:5432/secretvuln_test",
)
os.environ["SV_LDAP_ENABLED"] = "false"

from pathlib import Path  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models import User  # noqa: E402
from app.models.user import AuthSource  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _ensure_database() -> None:
    url = get_settings().database_url_sync  # postgresql+psycopg://.../secretvuln_test
    base, dbname = url.rsplit("/", 1)
    admin_url = base.replace("+psycopg", "") + "/postgres"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)
        ).fetchone()
    if not exists:
        pytest.exit(
            f"Нет тестовой БД «{dbname}». Создайте один раз: "
            f"docker compose exec postgres createdb -U secretvuln {dbname}",
            returncode=1,
        )


@pytest.fixture(scope="session", autouse=True)
def migrated_db() -> None:
    _ensure_database()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")


def _engine():
    return create_async_engine(get_settings().database_url, poolclass=NullPool)


@pytest.fixture(autouse=True)
async def clean_db(migrated_db):
    engine = _engine()
    async with engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        )
        names = [r[0] for r in rows]
        if names:
            quoted = ", ".join(f'"{n}"' for n in names)
            await conn.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
    await engine.dispose()

    import app.authz.enforcer as enforcer_module

    enforcer_module._enforcer = None  # политики перечитаются из очищенной БД
    yield


@pytest.fixture
async def db():
    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(monkeypatch):
    from app.db.session import get_db
    from app.main import app

    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    monkeypatch.setattr(
        "app.api.imports.upload_sarif", lambda content, filename: f"test/{filename}"
    )
    enqueued: list[str] = []

    async def _fake_enqueue(import_id: str) -> None:
        enqueued.append(import_id)

    monkeypatch.setattr("app.worker.enqueue_import", _fake_enqueue)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.enqueued = enqueued
        yield c

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
def make_user(db):
    async def _make(email: str, *, superuser: bool = False, roles: tuple[str, ...] = ()):
        user = User(
            email=email,
            auth_source=AuthSource.local,
            is_superuser=superuser,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = create_access_token(user.id, {"roles": list(roles)})
        return user, {"Authorization": f"Bearer {token}"}

    return _make


@pytest.fixture
def builtin_policies() -> None:
    from app.authz.enforcer import set_role_permissions
    from app.cli import BUILTIN_ROLES

    for name, (_desc, perms) in BUILTIN_ROLES.items():
        set_role_permissions(name, perms)


@pytest.fixture
async def admin(make_user):
    return await make_user("admin@test.local", superuser=True)
