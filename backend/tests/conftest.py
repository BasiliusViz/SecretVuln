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
        "app.api.imports.save_sarif", lambda content, filename: f"test/{filename}"
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


async def _role(db, name: str):
    from sqlalchemy import select

    from app.models import Role

    role = await db.scalar(select(Role).where(Role.name == name))
    if role is None:
        role = Role(name=name, is_builtin=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


@pytest.fixture
def grant(db):
    """Выдать пользователю роль на проект (None — на всё дерево) через свою группу."""
    from app.models import RoleBinding, UserGroup
    from app.models.user_group import GroupSource

    async def _grant(user, role_name: str, entity=None):
        group_name = f"personal:{user.email}"
        from sqlalchemy import select

        group = await db.scalar(select(UserGroup).where(UserGroup.name == group_name))
        if group is None:
            group = UserGroup(name=group_name, source=GroupSource.manual)
            group.members.append(user)
            db.add(group)
            await db.commit()
            await db.refresh(group)
        role = await _role(db, role_name)
        db.add(
            RoleBinding(
                group_id=group.id,
                role_id=role.id,
                entity_id=entity.id if entity is not None else None,
            )
        )
        await db.commit()
        return group

    return _grant


@pytest.fixture
def make_user(db, grant):
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
        for role_name in roles:
            await grant(user, role_name)
        token = create_access_token(user.id)
        return user, {"Authorization": f"Bearer {token}"}

    return _make


@pytest.fixture
async def builtin_policies(db) -> None:
    from app.authz.enforcer import set_role_permissions
    from app.cli import BUILTIN_ROLES

    for name, (_desc, perms) in BUILTIN_ROLES.items():
        await _role(db, name)
        set_role_permissions(name, perms)


@pytest.fixture
async def admin(make_user):
    return await make_user("admin@test.local", superuser=True)


@pytest.fixture
async def appsec(make_user, builtin_policies):
    return await make_user("alice@test.local", roles=("Инженер ИБ",))


@pytest.fixture
async def developer(make_user, builtin_policies):
    return await make_user("bob@test.local", roles=("Разработчик",))


@pytest.fixture
async def two_teams(db, make_user, grant, builtin_policies):
    """Две ветки `a` и `b` (у каждой — сервис `svc`) и команды на них.

    lead_a / lead_b — «Руководитель команды» на своей ветке, dev_a — «Разработчик» на `a`.
    Каждый пользователь — кортеж (user, headers).
    """
    from types import SimpleNamespace

    from tests.factories import make_entity

    a = await make_entity(db, "a")
    a_svc = await make_entity(db, "svc", parent_id=a.id)
    b = await make_entity(db, "b")
    b_svc = await make_entity(db, "svc", parent_id=b.id)
    lead_a = await make_user("lead-a@test.local")
    await grant(lead_a[0], "Руководитель команды", a)
    lead_b = await make_user("lead-b@test.local")
    await grant(lead_b[0], "Руководитель команды", b)
    dev_a = await make_user("dev-a@test.local")
    await grant(dev_a[0], "Разработчик", a)
    return SimpleNamespace(
        a=a, a_svc=a_svc, b=b, b_svc=b_svc, lead_a=lead_a, lead_b=lead_b, dev_a=dev_a
    )
