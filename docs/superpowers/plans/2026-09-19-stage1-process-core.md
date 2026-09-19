# Этап 1 «Ядро процесса» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Находки получают процесс: метаданные ветки/коммита у импорта, бэклог только из основной ветки, автозакрытие исчезнувших находок, статус «В работе», история событий, короткие номера SV-N, запросы «ложное / риск принят» с одобрением AppSec и автоистечение принятого риска.

**Architecture:** Логика обработки импорта выносится из ARQ-воркера в сервис `app/services/import_processing.py`, чтобы её можно было тестировать без S3/Redis. История пишется через `app/services/events.py` в таблицу `finding_events`. Решения «ложное / риск» — отдельная сущность `decision_requests` с сервисом `app/services/decisions.py` и роутером `app/api/decisions.py`. Права — новое действие Casbin `finding:approve` и встроенная роль «Разработчик».

**Tech Stack:** Python 3.14 (venv `backend/.venv`), FastAPI, SQLAlchemy 2.0 async + asyncpg, Alembic (psycopg), ARQ, Casbin, pytest + pytest-asyncio + httpx; фронтенд React 19 + TS + react-i18next.

**Spec:** `docs/superpowers/specs/2026-09-19-triage-workflow-and-ai-design.md` (разделы 2, 3, 4, 7, 8; этап 1 из раздела 14)

## Global Constraints

- Все env-переменные с префиксом `SV_`; API под `/api/v1`.
- Модели: UUID PK (`UUIDPKMixin`), `TimestampMixin`, enum'ы — `str, enum.Enum` + PG native enum. Новые модели импортировать в `app/models/__init__.py`.
- Миграции пишутся вручную, нумерация продолжается: `0006`, `0007`, `0008`, `0009`. Запуск: `cd backend && .venv\Scripts\python -m alembic upgrade head`.
- Весь текст UI — на русском через `t()` в `frontend/src/i18n/ru.json`; сообщения об ошибках API для пользователя — на русском (как в `app/api/deps.py`).
- Термины: `in_progress` → «В работе», `approve` → «Одобрение», `false_positive` → «Ложное срабатывание», `risk_accepted` → «Риск принят».
- Кнопки «Исправил» нет: статус `fixed` ставится только автозакрытием при повторном скане.
- Ложное срабатывание от разработчика подтверждает AppSec (право `finding:approve`); пользователь с `approve` ставит решение сразу.
- `.ps1` сохранять в UTF-8 **с BOM**.
- Тесты требуют Postgres из docker-compose: `docker compose up -d postgres` (из корня репозитория). Тестовая БД `secretvuln_test` создаётся автоматически.
- Отступление от спеки: поле импорта `source` (manual/api, раздел 4.1) не делаем — отличать загрузку из UI от API станет возможно только с API-токенами (этап 6).
- Коммиты — только в ветке `feature/stage1-process-core` (создать перед Task 1: `git checkout -b feature/stage1-process-core`).

## Карта файлов

| Файл | Что делает |
|---|---|
| `backend/tests/conftest.py` (новый) | Тестовая БД, миграции, очистка, HTTP-клиент, пользователи с токенами |
| `backend/tests/factories.py` (новый) | `make_sarif`, `make_entity`, `make_import`, `make_finding` |
| `backend/app/services/import_processing.py` (новый) | `apply_import` — создание/дедуп/переоткрытие/автозакрытие, проверка ветки |
| `backend/app/services/entity_tree.py` (новый) | `resolve_default_branch`, `branch_allowed` |
| `backend/app/services/events.py` (новый) | `record_event` |
| `backend/app/services/decisions.py` (новый) | Создание, одобрение, отклонение запросов |
| `backend/app/services/risk_expiry.py` (новый) | Истечение принятого риска |
| `backend/app/models/finding_event.py` (новый) | `FindingEvent`, `FindingEventType`, `ActorType` |
| `backend/app/models/decision_request.py` (новый) | `DecisionRequest`, `DecisionType`, `DecisionStatus`, `ReasonTag` |
| `backend/app/api/decisions.py` (новый) | Эндпоинты запросов |
| `backend/app/schemas/finding_event.py`, `backend/app/schemas/decision.py` (новые) | Pydantic-схемы |
| `backend/app/worker.py` | Тонкая обёртка над сервисом + cron истечения риска |
| `backend/app/api/findings.py` | PATCH с телом и причиной, история, поиск по номеру |
| `backend/app/api/imports.py` | Поля ветки/коммита/объёма, проверка ветки |
| `backend/app/api/deps.py` | `has_permission` |
| `backend/app/authz/permissions.py`, `backend/app/cli.py` | `approve`, роль «Разработчик» |
| `backend/app/services/sarif/parser.py` | Чтение `versionControlProvenance` |
| `backend/migrations/versions/0006…0009` | Схема |
| `frontend/src/i18n/ru.json`, `frontend/src/pages/Findings.tsx`, `frontend/DESIGN.md` | Статус «В работе», номер SV-N, право «Одобрение» |
| `scripts/smoke-test.ps1`, `scripts/samples/semgrep-rescan.sarif` | Логин + проверка автозакрытия |
| `CLAUDE.md` | Документация этапа |

---

### Task 1: Тестовая инфраструктура

**Files:**
- Create: `backend/tests/__init__.py` (пустой)
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/factories.py`
- Create: `backend/tests/test_smoke.py`
- Modify: `backend/pyproject.toml` (секция `[tool.pytest.ini_options]`)

**Interfaces:**
- Produces: фикстуры `migrated_db`, `clean_db` (autouse), `db` (`AsyncSession`), `client` (`httpx.AsyncClient` с атрибутом `enqueued: list[str]`), `make_user` (`async (email, *, superuser=False, roles=()) -> (User, dict[str,str] headers)`), `builtin_policies`, `admin` (`(User, headers)`).
- Produces: `factories.make_sarif(scanner: str = "Semgrep", results: list[dict] = (), provenance: dict | None = None) -> bytes`; каждый элемент `results` — dict с ключом `fp` и необязательными `rule_id`, `path`, `line`, `level`, `message`. `make_entity(db, name="svc", parent_id=None, **kw) -> Entity`; `make_import(db, entity, **kw) -> Import`; `make_finding(db, entity, fingerprint="fp1", **kw) -> Finding`.

- [ ] **Step 1: Поднять Postgres**

Run (из корня репозитория): `docker compose up -d postgres`
Expected: контейнер postgres в статусе `Up`.

- [ ] **Step 2: Настроить pytest**

В `backend/pyproject.toml` заменить секцию `[tool.pytest.ini_options]` на:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 3: Написать `backend/tests/factories.py`**

```python
"""Фабрики тестовых данных."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity, Finding, Import
from app.models.finding import Severity
from app.models.import_ import ImportStatus


def make_sarif(
    scanner: str = "Semgrep",
    results: list[dict[str, Any]] | tuple = (),
    provenance: dict[str, Any] | None = None,
) -> bytes:
    run: dict[str, Any] = {
        "tool": {"driver": {"name": scanner, "rules": []}},
        "results": [
            {
                "ruleId": r.get("rule_id", "rule.a"),
                "level": r.get("level", "error"),
                "message": {"text": r.get("message", "msg")},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": r.get("path", "app/a.py")},
                            "region": {"startLine": r.get("line", 1)},
                        }
                    }
                ],
                "partialFingerprints": {"primaryLocationLineHash": r["fp"]},
            }
            for r in results
        ],
    }
    if provenance is not None:
        run["versionControlProvenance"] = [provenance]
    return json.dumps({"version": "2.1.0", "runs": [run]}).encode()


async def make_entity(
    db: AsyncSession, name: str = "svc", parent_id=None, **kw: Any
) -> Entity:
    entity = Entity(name=name, parent_id=parent_id, **kw)
    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    return entity


async def make_import(db: AsyncSession, entity: Entity, **kw: Any) -> Import:
    imp = Import(
        entity_id=entity.id,
        filename=kw.pop("filename", "t.sarif"),
        s3_key=kw.pop("s3_key", "test/t.sarif"),
        status=kw.pop("status", ImportStatus.processing),
        **kw,
    )
    db.add(imp)
    await db.commit()
    await db.refresh(imp)
    return imp


async def make_finding(
    db: AsyncSession, entity: Entity, fingerprint: str = "fp1", **kw: Any
) -> Finding:
    finding = Finding(
        entity_id=entity.id,
        title=kw.pop("title", "SQL injection"),
        severity=kw.pop("severity", Severity.high),
        scanner=kw.pop("scanner", "Semgrep"),
        fingerprint=fingerprint,
        raw=kw.pop("raw", {}),
        **kw,
    )
    db.add(finding)
    await db.commit()
    await db.refresh(finding)
    return finding
```

- [ ] **Step 4: Написать `backend/tests/conftest.py`**

```python
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
            conn.execute(f'CREATE DATABASE "{dbname}"')


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
```

И пустой `backend/tests/__init__.py`.

- [ ] **Step 5: Написать `backend/tests/test_smoke.py`**

```python
from app.services.sarif import parse_sarif
from tests.factories import make_sarif


async def test_health(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["database"] == "up"


async def test_findings_require_auth(client):
    r = await client.get("/api/v1/findings")
    assert r.status_code == 401


async def test_admin_can_list_findings(client, admin):
    _, headers = admin
    r = await client.get("/api/v1/findings", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_make_sarif_roundtrip():
    runs = parse_sarif(make_sarif("Semgrep", [{"fp": "a"}, {"fp": "b", "path": "x.py", "line": 3}]))
    assert runs[0].scanner == "Semgrep"
    assert [r.fingerprint for r in runs[0].results] == ["a", "b"]
    assert runs[0].results[1].file_path == "x.py"
    assert runs[0].results[1].line_start == 3
```

- [ ] **Step 6: Запустить тесты**

Run: `cd backend && .venv\Scripts\python -m pytest -v`
Expected: 4 passed. Если `psycopg.OperationalError` — не запущен Postgres (Step 1).

- [ ] **Step 7: Commit**

```bash
git add backend/tests backend/pyproject.toml
git commit -m "test: pytest infrastructure with isolated test database"
```

---

### Task 2: Вынос обработки импорта в сервис

Чистый рефакторинг: поведение не меняется, но логика становится тестируемой без S3 и Redis.

**Files:**
- Create: `backend/app/services/import_processing.py`
- Modify: `backend/app/worker.py:23-116` (тело `process_import`)
- Test: `backend/tests/test_import_processing.py`

**Interfaces:**
- Consumes: `parse_sarif`, `SarifRun`, `get_normalizer` из `app.services.sarif`; фабрики из Task 1.
- Produces: `async def apply_import(db: AsyncSession, imp: Import, runs: list[SarifRun]) -> dict[str, Any]` — пишет находки, выставляет `imp.scanner`, НЕ коммитит; возвращает статистику `{"created","updated","duplicates","total_results"}`.

- [ ] **Step 1: Написать падающие тесты `backend/tests/test_import_processing.py`**

```python
from sqlalchemy import select

from app.models import Finding
from app.models.finding import FindingStatus
from app.services.import_processing import apply_import
from app.services.sarif import parse_sarif
from tests.factories import make_entity, make_import, make_sarif


async def _run(db, entity, results, **import_kw):
    imp = await make_import(db, entity, **import_kw)
    stats = await apply_import(db, imp, parse_sarif(make_sarif("Semgrep", results)))
    await db.commit()
    return imp, stats


async def test_creates_findings(db):
    entity = await make_entity(db)
    imp, stats = await _run(db, entity, [{"fp": "a"}, {"fp": "b"}])
    assert stats["created"] == 2
    assert stats["total_results"] == 2
    assert imp.scanner == "Semgrep"
    rows = (await db.scalars(select(Finding).where(Finding.entity_id == entity.id))).all()
    assert {f.fingerprint for f in rows} == {"a", "b"}


async def test_reimport_counts_duplicates(db):
    entity = await make_entity(db)
    await _run(db, entity, [{"fp": "a"}, {"fp": "b"}])
    _, stats = await _run(db, entity, [{"fp": "a"}, {"fp": "b"}])
    assert stats["created"] == 0
    assert stats["duplicates"] == 2


async def test_fixed_finding_reopens(db):
    entity = await make_entity(db)
    await _run(db, entity, [{"fp": "a"}])
    finding = await db.scalar(select(Finding).where(Finding.fingerprint == "a"))
    finding.status = FindingStatus.fixed
    await db.commit()

    _, stats = await _run(db, entity, [{"fp": "a"}])
    await db.refresh(finding)
    assert finding.status == FindingStatus.new
    assert stats["updated"] == 1
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_import_processing.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.services.import_processing'`.

- [ ] **Step 3: Создать `backend/app/services/import_processing.py`**

```python
"""Применение распарсенного SARIF к базе: создание, дедупликация, переоткрытие."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding, FindingStatus
from app.models.import_ import Import
from app.services.sarif import SarifRun, get_normalizer


async def apply_import(db: AsyncSession, imp: Import, runs: list[SarifRun]) -> dict[str, Any]:
    """Пишет находки импорта в сессию. Не коммитит — это делает вызывающий."""
    created = updated = duplicates = total_results = 0
    scanner_name: str | None = None
    now = datetime.now(timezone.utc)

    for run in runs:
        scanner_name = run.scanner
        normalizer = get_normalizer(run.scanner)

        for result in run.results:
            total_results += 1
            existing = await db.scalar(
                select(Finding).where(
                    Finding.entity_id == imp.entity_id,
                    Finding.fingerprint == result.fingerprint,
                )
            )

            if existing:
                existing.last_seen = now
                existing.import_id = imp.id
                existing.raw = result.raw
                if existing.status == FindingStatus.fixed:
                    existing.status = FindingStatus.new
                    updated += 1
                else:
                    duplicates += 1
            else:
                db.add(
                    Finding(
                        entity_id=imp.entity_id,
                        import_id=imp.id,
                        title=result.title,
                        description=result.description,
                        severity=normalizer.severity(result),
                        status=FindingStatus.new,
                        scanner=run.scanner,
                        rule_id=result.rule_id,
                        cwe=result.cwe,
                        file_path=result.file_path,
                        line_start=result.line_start,
                        line_end=result.line_end,
                        fingerprint=result.fingerprint,
                        raw=result.raw,
                    )
                )
                created += 1

        await db.flush()

    imp.scanner = scanner_name
    return {
        "created": created,
        "updated": updated,
        "duplicates": duplicates,
        "total_results": total_results,
    }
```

Проверить, что `SarifRun` экспортируется из `app/services/sarif/__init__.py`; если нет — добавить `from app.services.sarif.parser import SarifRun` и имя в `__all__`.

- [ ] **Step 4: Переписать `process_import` в `backend/app/worker.py`**

Заменить функцию `process_import` (строки 23–116) и импорты сверху на:

```python
"""ARQ worker — processes SARIF imports in the background."""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.import_ import Import, ImportStatus
from app.services.import_processing import apply_import
from app.services.s3 import download_sarif
from app.services.sarif import parse_sarif

logger = logging.getLogger("arq.worker")


async def _mark_failed(session_factory: async_sessionmaker, import_id: str, error: str) -> None:
    async with session_factory() as db:
        imp = await db.get(Import, import_id)
        if imp:
            imp.status = ImportStatus.failed
            imp.error = error[-2000:]
            imp.finished_at = datetime.now(timezone.utc)
            await db.commit()


async def process_import(ctx: dict, import_id: str) -> None:
    session_factory: async_sessionmaker = ctx["session_factory"]

    async with session_factory() as db:
        imp = await db.get(Import, import_id)
        if imp is None:
            logger.error("Import %s not found", import_id)
            return

        imp.status = ImportStatus.processing
        await db.commit()

        try:
            runs = parse_sarif(download_sarif(imp.s3_key))
            stats = await apply_import(db, imp, runs)
            imp.status = ImportStatus.done
            imp.stats = stats
            imp.finished_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info("Import %s done: %s", import_id, stats)
        except Exception:
            await db.rollback()
            await _mark_failed(session_factory, import_id, traceback.format_exc())
            logger.exception("Import %s failed", import_id)
```

Остальное (`startup`, `shutdown`, `WorkerSettings`, `enqueue_import`) — без изменений; убрать ставшие ненужными импорты `select`, `pg_insert`, `AsyncSession`, `Finding`, `FindingStatus`, `get_normalizer`.

- [ ] **Step 5: Запустить тесты**

Run: `cd backend && .venv\Scripts\python -m pytest -v`
Expected: все PASS (7 тестов).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/import_processing.py backend/app/services/sarif/__init__.py backend/app/worker.py backend/tests/test_import_processing.py
git commit -m "refactor: move SARIF import processing from worker into a testable service"
```

---

### Task 3: Право `finding:approve` и роль «Разработчик»

**Files:**
- Modify: `backend/app/authz/permissions.py:10-19`
- Modify: `backend/app/cli.py:57-87` (`BUILTIN_ROLES`)
- Modify: `backend/app/api/deps.py:54-67` (добавить `has_permission`, `require_permission` через него)
- Modify: `backend/tests/conftest.py` (фикстуры `appsec`, `developer`)
- Modify: `frontend/src/i18n/ru.json` (`perm.action.approve`)
- Test: `backend/tests/test_permissions.py`

**Interfaces:**
- Produces: `def has_permission(principal: Principal, resource: str, action: str) -> bool` в `app/api/deps.py` (суперюзер → True).
- Produces: фикстуры `appsec` (роль «Инженер ИБ», email `alice@test.local`) и `developer` (роль «Разработчик», email `bob@test.local`), обе возвращают `(User, headers)`.

- [ ] **Step 1: Добавить фикстуры в конец `backend/tests/conftest.py`**

```python
@pytest.fixture
async def appsec(make_user, builtin_policies):
    return await make_user("alice@test.local", roles=("Инженер ИБ",))


@pytest.fixture
async def developer(make_user, builtin_policies):
    return await make_user("bob@test.local", roles=("Разработчик",))
```

- [ ] **Step 2: Написать падающие тесты `backend/tests/test_permissions.py`**

```python
from app.authz.enforcer import check
from app.authz.permissions import ACTIONS, is_valid


def test_catalog_has_approve():
    assert is_valid("finding", "approve")
    assert "approve" in ACTIONS


async def test_appsec_can_approve_developer_cannot(appsec, developer):
    assert check(["Инженер ИБ"], "finding", "approve")
    assert check(["Администратор"], "finding", "approve")
    assert not check(["Разработчик"], "finding", "approve")


async def test_developer_reads_findings_but_cannot_create_entities(client, developer):
    _, headers = developer
    assert (await client.get("/api/v1/findings", headers=headers)).status_code == 200
    r = await client.post("/api/v1/entities", json={"name": "x"}, headers=headers)
    assert r.status_code == 403
```

- [ ] **Step 3: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_permissions.py -v`
Expected: FAIL (`is_valid("finding","approve")` → False; фикстура `developer` получает 403 на чтение, т.к. роли «Разработчик» нет).

- [ ] **Step 4: Обновить `backend/app/authz/permissions.py`**

```python
CATALOG: dict[str, list[str]] = {
    "entity": ["read", "write", "delete"],
    "finding": ["read", "write", "delete", "triage", "approve"],
    "import": ["read", "import", "delete"],
    "group": ["read", "write", "delete"],
    "role": ["read", "write", "delete"],
}

RESOURCES: list[str] = list(CATALOG.keys())
ACTIONS: list[str] = ["read", "write", "delete", "import", "triage", "approve"]
```

- [ ] **Step 5: Обновить `BUILTIN_ROLES` в `backend/app/cli.py`**

```python
BUILTIN_ROLES: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "Наблюдатель": (
        "Только чтение во всех разделах",
        [(r, "read") for r in _R],
    ),
    "Разработчик": (
        "Видит находки, берёт в работу, запрашивает «ложное срабатывание» и принятие риска",
        [("entity", "read"), ("finding", "read"), ("finding", "triage"), ("import", "read")],
    ),
    "Аудитор": (
        "Чтение везде + разбор находок",
        [(r, "read") for r in _R] + [("finding", "triage")],
    ),
    "Инженер ИБ": (
        "Полный доступ к активам, находкам и импортам, одобряет решения по находкам",
        [
            ("entity", "read"), ("entity", "write"), ("entity", "delete"),
            ("finding", "read"), ("finding", "write"), ("finding", "delete"),
            ("finding", "triage"), ("finding", "approve"),
            ("import", "read"), ("import", "import"), ("import", "delete"),
            ("group", "read"),
        ],
    ),
    "Администратор": (
        "Все права, включая управление группами и ролями",
        [
            ("entity", "read"), ("entity", "write"), ("entity", "delete"),
            ("finding", "read"), ("finding", "write"), ("finding", "delete"),
            ("finding", "triage"), ("finding", "approve"),
            ("import", "read"), ("import", "import"), ("import", "delete"),
            ("group", "read"), ("group", "write"), ("group", "delete"),
            ("role", "read"), ("role", "write"), ("role", "delete"),
        ],
    ),
}
```

- [ ] **Step 6: Добавить `has_permission` в `backend/app/api/deps.py`**

Заменить функцию `require_permission` (строки 54–67) на:

```python
def has_permission(principal: Principal, resource: str, action: str) -> bool:
    """Суперюзер может всё; иначе — хотя бы одна роль с правом (resource, action)."""
    from app.authz.enforcer import check

    return principal.user.is_superuser or check(principal.roles, resource, action)


def require_permission(resource: str, action: str):
    """Зависимость: пропускает суперюзера или роль с правом (resource, action)."""

    async def _dep(principal: Principal = Depends(get_current_principal)) -> Principal:
        if has_permission(principal, resource, action):
            return principal
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Недостаточно прав: {resource}:{action}"
        )

    return _dep
```

- [ ] **Step 7: Перевод права в `frontend/src/i18n/ru.json`**

В объект `perm.action` добавить после `"triage": "Разбор"`:

```json
      "triage": "Разбор",
      "approve": "Одобрение"
```

- [ ] **Step 8: Запустить тесты**

Run: `cd backend && .venv\Scripts\python -m pytest -v`
Expected: все PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/authz/permissions.py backend/app/cli.py backend/app/api/deps.py backend/tests frontend/src/i18n/ru.json
git commit -m "feat: finding:approve permission and built-in Developer role"
```

После слияния на dev-стенде выполнить `cd backend && .venv\Scripts\python -m app.cli seed-roles`.

---

### Task 4: Метаданные импорта и основная ветка

**Files:**
- Create: `backend/migrations/versions/0006_import_metadata_default_branch.py`
- Create: `backend/app/services/entity_tree.py`
- Modify: `backend/app/models/finding.py` (enum `in_progress`, поля `scan_scope`, `commit_sha`)
- Modify: `backend/app/models/import_.py` (поля метаданных)
- Modify: `backend/app/models/entity.py` (`default_branch`)
- Modify: `backend/app/schemas/import_.py`, `backend/app/schemas/entity.py`, `backend/app/schemas/finding.py`
- Modify: `backend/app/services/sarif/parser.py` (`SarifRun.branch/revision/repository_uri`)
- Modify: `backend/app/services/import_processing.py`
- Modify: `backend/app/worker.py` (обработка `ImportRejected`)
- Modify: `backend/app/api/imports.py` (поля формы, проверка ветки)
- Test: `backend/tests/test_branches.py`

**Interfaces:**
- Consumes: `apply_import` (Task 2), фикстуры (Task 1, 3).
- Produces: `FindingStatus.in_progress`; `Import.branch/commit_sha/pipeline_url/scan_scope/close_missing/confirm_empty`; `Entity.default_branch`; `Finding.scan_scope/commit_sha`; `SarifRun.branch/revision/repository_uri: str | None`.
- Produces: `async def resolve_default_branch(db: AsyncSession, entity_id: uuid.UUID) -> str | None`; `def branch_allowed(branch: str | None, default_branch: str | None) -> bool`; `def branch_rejection_message(branch: str, default_branch: str) -> str`.
- Produces: `class ImportRejected(Exception)` в `app/services/import_processing.py`; `apply_import` бросает его, если ветка из SARIF не основная.

- [ ] **Step 1: Написать падающие тесты `backend/tests/test_branches.py`**

```python
from sqlalchemy import select

import pytest

from app.models import Finding, Import
from app.services.entity_tree import branch_allowed, resolve_default_branch
from app.services.import_processing import ImportRejected, apply_import
from app.services.sarif import parse_sarif
from tests.factories import make_entity, make_import, make_sarif


def test_parser_reads_version_control_provenance():
    sarif = make_sarif(
        "Semgrep",
        [{"fp": "a"}],
        provenance={
            "repositoryUri": "https://gitlab.local/pay/api",
            "revisionId": "abc123",
            "branch": "main",
        },
    )
    run = parse_sarif(sarif)[0]
    assert run.repository_uri == "https://gitlab.local/pay/api"
    assert run.revision == "abc123"
    assert run.branch == "main"


def test_branch_allowed():
    assert branch_allowed(None, "main")
    assert branch_allowed("feature/x", None)
    assert branch_allowed("main", "main")
    assert not branch_allowed("feature/x", "main")


async def test_default_branch_is_inherited(db):
    root = await make_entity(db, "org", default_branch="master")
    child = await make_entity(db, "svc", parent_id=root.id)
    grandchild = await make_entity(db, "mod", parent_id=child.id, default_branch="main")
    assert await resolve_default_branch(db, child.id) == "master"
    assert await resolve_default_branch(db, grandchild.id) == "main"


async def test_upload_rejects_non_default_branch(client, admin, db):
    _, headers = admin
    entity = await make_entity(db, default_branch="main")
    r = await client.post(
        f"/api/v1/entities/{entity.id}/imports",
        files={"file": ("s.sarif", make_sarif("Semgrep", [{"fp": "a"}]), "application/json")},
        data={"branch": "feature/x"},
        headers=headers,
    )
    assert r.status_code == 422
    assert "feature/x" in r.json()["detail"]
    assert client.enqueued == []


async def test_upload_stores_metadata(client, admin, db):
    _, headers = admin
    entity = await make_entity(db, default_branch="main")
    r = await client.post(
        f"/api/v1/entities/{entity.id}/imports",
        files={"file": ("s.sarif", make_sarif("Semgrep", [{"fp": "a"}]), "application/json")},
        data={
            "branch": "main",
            "commit_sha": "deadbeef",
            "pipeline_url": "https://ci.local/p/1",
            "scan_scope": "api:latest",
            "close_missing": "false",
        },
        headers=headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["branch"] == "main"
    assert body["commit_sha"] == "deadbeef"
    assert body["scan_scope"] == "api:latest"
    assert body["close_missing"] is False
    assert body["confirm_empty"] is False
    assert client.enqueued == [body["id"]]


async def test_sarif_branch_fills_import_and_findings(db):
    entity = await make_entity(db)
    imp = await make_import(db, entity, scan_scope="api:latest")
    sarif = make_sarif("Semgrep", [{"fp": "a"}], provenance={"branch": "main", "revisionId": "c0ffee"})
    await apply_import(db, imp, parse_sarif(sarif))
    await db.commit()
    assert imp.branch == "main"
    assert imp.commit_sha == "c0ffee"
    finding = await db.scalar(select(Finding).where(Finding.fingerprint == "a"))
    assert finding.scan_scope == "api:latest"
    assert finding.commit_sha == "c0ffee"


async def test_sarif_branch_mismatch_is_rejected(db):
    entity = await make_entity(db, default_branch="main")
    imp = await make_import(db, entity)
    sarif = make_sarif("Semgrep", [{"fp": "a"}], provenance={"branch": "feature/x"})
    with pytest.raises(ImportRejected, match="feature/x"):
        await apply_import(db, imp, parse_sarif(sarif))
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_branches.py -v`
Expected: FAIL (`ModuleNotFoundError: app.services.entity_tree`).

- [ ] **Step 3: Миграция `backend/migrations/versions/0006_import_metadata_default_branch.py`**

```python
"""import metadata (branch/commit/scope), entity default branch, in_progress status

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PG >= 12 разрешает ADD VALUE в транзакции (значение не используется в этой же миграции)
    op.execute("ALTER TYPE finding_status ADD VALUE IF NOT EXISTS 'in_progress'")

    op.add_column("entities", sa.Column("default_branch", sa.String(255), nullable=True))

    op.add_column("imports", sa.Column("branch", sa.String(255), nullable=True))
    op.add_column("imports", sa.Column("commit_sha", sa.String(64), nullable=True))
    op.add_column("imports", sa.Column("pipeline_url", sa.String(1024), nullable=True))
    op.add_column("imports", sa.Column("scan_scope", sa.String(255), nullable=True))
    op.add_column(
        "imports",
        sa.Column("close_missing", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "imports",
        sa.Column("confirm_empty", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.add_column("findings", sa.Column("scan_scope", sa.String(255), nullable=True))
    op.add_column("findings", sa.Column("commit_sha", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("findings", "commit_sha")
    op.drop_column("findings", "scan_scope")
    for col in ("confirm_empty", "close_missing", "scan_scope", "pipeline_url", "commit_sha", "branch"):
        op.drop_column("imports", col)
    op.drop_column("entities", "default_branch")
    # значение enum 'in_progress' в PostgreSQL удалить нельзя — остаётся
```

- [ ] **Step 4: Модели**

`backend/app/models/finding.py` — в `FindingStatus` после `confirmed = "confirmed"` добавить:

```python
    in_progress = "in_progress"
```

В класс `Finding` после блока `line_end` добавить:

```python
    # Объём скана (например, имя образа) — определяет, какие находки закрывает автозакрытие
    scan_scope: Mapped[str | None] = mapped_column(String(255))
    # Коммит последнего импорта, в котором находку видели (для ссылки на строку кода)
    commit_sha: Mapped[str | None] = mapped_column(String(64))
```

`backend/app/models/import_.py` — импорт `Boolean` в строке `from sqlalchemy import ...`, после поля `scanner` добавить:

```python
    # Метаданные CI (все необязательные; ветка/коммит могут прийти из SARIF versionControlProvenance)
    branch: Mapped[str | None] = mapped_column(String(255))
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    pipeline_url: Mapped[str | None] = mapped_column(String(1024))
    scan_scope: Mapped[str | None] = mapped_column(String(255))
    # Закрывать находки объёма, которых нет в отчёте
    close_missing: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Разрешить автозакрытие по пустому отчёту (защита от сломанного сканера)
    confirm_empty: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

`backend/app/models/entity.py` — после `description`:

```python
    # Ветка, из которой строится бэклог; NULL — наследуется от родителя (или любая ветка)
    default_branch: Mapped[str | None] = mapped_column(String(255))
```

- [ ] **Step 5: Схемы**

`backend/app/schemas/import_.py` — в `ImportRead` после `scanner`:

```python
    branch: str | None
    commit_sha: str | None
    pipeline_url: str | None
    scan_scope: str | None
    close_missing: bool
    confirm_empty: bool
```

`backend/app/schemas/entity.py` — в `EntityCreate` и `EntityUpdate` добавить `default_branch: str | None = Field(default=None, max_length=255)`, в `EntityRead` — `default_branch: str | None`.

`backend/app/schemas/finding.py` — в `FindingRead` после `line_end`:

```python
    scan_scope: str | None
    commit_sha: str | None
```

- [ ] **Step 6: Парсер — `backend/app/services/sarif/parser.py`**

Заменить `SarifRun` на:

```python
@dataclass
class SarifRun:
    scanner: str
    results: list[SarifResult] = field(default_factory=list)
    # Из runs[].versionControlProvenance[0] — если сканер его заполнил
    branch: str | None = None
    revision: str | None = None
    repository_uri: str | None = None
```

В `parse_sarif` строку `sarif_run = SarifRun(scanner=scanner)` заменить на:

```python
        vcp = (run_data.get("versionControlProvenance") or [{}])[0]
        sarif_run = SarifRun(
            scanner=scanner,
            branch=vcp.get("branch"),
            revision=vcp.get("revisionId"),
            repository_uri=vcp.get("repositoryUri"),
        )
```

- [ ] **Step 7: `backend/app/services/entity_tree.py`**

```python
"""Настройки, наследуемые вниз по дереву активов."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity


async def resolve_default_branch(db: AsyncSession, entity_id: uuid.UUID) -> str | None:
    """Ближайшая заданная default_branch от узла вверх к корню."""
    current: uuid.UUID | None = entity_id
    while current is not None:
        entity = await db.get(Entity, current)
        if entity is None:
            return None
        if entity.default_branch:
            return entity.default_branch
        current = entity.parent_id
    return None


def branch_allowed(branch: str | None, default_branch: str | None) -> bool:
    """Ветка не указана или основная не задана — принимаем (как до этапа 1)."""
    return branch is None or default_branch is None or branch == default_branch


def branch_rejection_message(branch: str, default_branch: str) -> str:
    return (
        f"Ветка «{branch}» не основная для актива (основная — «{default_branch}»). "
        "Проверки веток появятся позже"
    )
```

- [ ] **Step 8: Сервис импорта — полный новый `backend/app/services/import_processing.py`**

```python
"""Применение распарсенного SARIF к базе: создание, дедупликация, переоткрытие."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding, FindingStatus
from app.models.import_ import Import
from app.services.entity_tree import branch_allowed, branch_rejection_message, resolve_default_branch
from app.services.sarif import SarifRun, get_normalizer


class ImportRejected(Exception):
    """Импорт не должен попадать в бэклог (например, не основная ветка)."""


def _apply_provenance(imp: Import, runs: list[SarifRun]) -> None:
    for run in runs:
        imp.branch = imp.branch or run.branch
        imp.commit_sha = imp.commit_sha or run.revision


async def apply_import(db: AsyncSession, imp: Import, runs: list[SarifRun]) -> dict[str, Any]:
    """Пишет находки импорта в сессию. Не коммитит — это делает вызывающий."""
    _apply_provenance(imp, runs)
    default_branch = await resolve_default_branch(db, imp.entity_id)
    if not branch_allowed(imp.branch, default_branch):
        raise ImportRejected(branch_rejection_message(imp.branch, default_branch))

    created = updated = duplicates = total_results = 0
    scanner_name: str | None = None
    now = datetime.now(timezone.utc)

    for run in runs:
        scanner_name = run.scanner
        normalizer = get_normalizer(run.scanner)

        for result in run.results:
            total_results += 1
            existing = await db.scalar(
                select(Finding).where(
                    Finding.entity_id == imp.entity_id,
                    Finding.fingerprint == result.fingerprint,
                )
            )

            if existing:
                existing.last_seen = now
                existing.import_id = imp.id
                existing.raw = result.raw
                existing.scan_scope = imp.scan_scope
                existing.commit_sha = imp.commit_sha
                if existing.status == FindingStatus.fixed:
                    existing.status = FindingStatus.new
                    updated += 1
                else:
                    duplicates += 1
            else:
                db.add(
                    Finding(
                        entity_id=imp.entity_id,
                        import_id=imp.id,
                        title=result.title,
                        description=result.description,
                        severity=normalizer.severity(result),
                        status=FindingStatus.new,
                        scanner=run.scanner,
                        rule_id=result.rule_id,
                        cwe=result.cwe,
                        file_path=result.file_path,
                        line_start=result.line_start,
                        line_end=result.line_end,
                        fingerprint=result.fingerprint,
                        scan_scope=imp.scan_scope,
                        commit_sha=imp.commit_sha,
                        raw=result.raw,
                    )
                )
                created += 1

        await db.flush()

    imp.scanner = scanner_name
    return {
        "created": created,
        "updated": updated,
        "duplicates": duplicates,
        "total_results": total_results,
    }
```

- [ ] **Step 9: Воркер — понятная ошибка для отклонённой ветки**

В `backend/app/worker.py` импорт заменить на `from app.services.import_processing import ImportRejected, apply_import`, а в `process_import` перед `except Exception:` добавить:

```python
        except ImportRejected as exc:
            await db.rollback()
            await _mark_failed(session_factory, import_id, str(exc))
            logger.warning("Import %s rejected: %s", import_id, exc)
```

- [ ] **Step 10: API загрузки — `backend/app/api/imports.py`**

Импорты: `from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status` и `from app.services.entity_tree import branch_allowed, branch_rejection_message, resolve_default_branch`.

Функцию `create_import` заменить на:

```python
@router.post(
    "/entities/{entity_id}/imports",
    response_model=ImportRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_import(
    entity_id: uuid.UUID,
    file: UploadFile,
    branch: str | None = Form(None),
    commit_sha: str | None = Form(None),
    pipeline_url: str | None = Form(None),
    scan_scope: str | None = Form(None),
    close_missing: bool = Form(True),
    confirm_empty: bool = Form(False),
    principal: Principal = Depends(require_permission("import", "import")),
    db: AsyncSession = Depends(get_db),
) -> Import:
    entity = await db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found")

    branch = branch or None
    default_branch = await resolve_default_branch(db, entity_id)
    if not branch_allowed(branch, default_branch):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            branch_rejection_message(branch, default_branch),
        )

    content = await file.read()
    if len(content) > MAX_SARIF_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large (max 50 MB)")

    filename = file.filename or "upload.sarif"
    s3_key = upload_sarif(content, filename)

    import_record = Import(
        entity_id=entity_id,
        uploaded_by_id=principal.user.id,
        filename=filename,
        s3_key=s3_key,
        status=ImportStatus.pending,
        branch=branch,
        commit_sha=commit_sha or None,
        pipeline_url=pipeline_url or None,
        scan_scope=scan_scope or None,
        close_missing=close_missing,
        confirm_empty=confirm_empty,
    )
    db.add(import_record)
    await db.commit()
    await db.refresh(import_record)

    from app.worker import enqueue_import
    await enqueue_import(str(import_record.id))

    return import_record
```

И импорт `from app.api.deps import Principal, require_permission`.

- [ ] **Step 11: Миграция и тесты**

Run: `cd backend && .venv\Scripts\python -m pytest -v`
Expected: все PASS (миграция 0006 применяется к тестовой БД автоматически).

Run: `cd backend && .venv\Scripts\python -m alembic upgrade head` (dev-БД)
Expected: `Running upgrade 0005 -> 0006`.

- [ ] **Step 12: Commit**

```bash
git add backend/migrations/versions/0006_import_metadata_default_branch.py backend/app backend/tests/test_branches.py
git commit -m "feat: import branch/commit/scope metadata and default-branch-only backlog"
```

---

### Task 5: История находки (`finding_events`)

**Files:**
- Create: `backend/app/models/finding_event.py`
- Create: `backend/migrations/versions/0007_finding_events.py`
- Create: `backend/app/services/events.py`
- Create: `backend/app/schemas/finding_event.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/services/import_processing.py` (события `imported`, `reopened`)
- Modify: `backend/app/api/findings.py` (`GET /findings/{id}/events`)
- Test: `backend/tests/test_events.py`

**Interfaces:**
- Produces: `FindingEventType` = `imported | status_changed | reopened | auto_fixed | request_created | request_decided`; `ActorType` = `user | agent | system`.
- Produces: `def record_event(db: AsyncSession, finding_id: uuid.UUID, event_type: FindingEventType, *, actor_type: ActorType = ActorType.system, actor_id: uuid.UUID | None = None, from_status: FindingStatus | None = None, to_status: FindingStatus | None = None, reason: str | None = None, reason_tag: str | None = None, payload: dict | None = None) -> FindingEvent` — только `db.add`, без commit.
- Produces: `GET /api/v1/findings/{id}/events` → `list[FindingEventRead]` по возрастанию времени.

- [ ] **Step 1: Написать падающие тесты `backend/tests/test_events.py`**

```python
from sqlalchemy import select

from app.models import Finding
from app.models.finding import FindingStatus
from app.services.import_processing import apply_import
from app.services.sarif import parse_sarif
from tests.factories import make_entity, make_import, make_sarif


async def _import(db, entity, fps):
    imp = await make_import(db, entity)
    await apply_import(db, imp, parse_sarif(make_sarif("Semgrep", [{"fp": fp} for fp in fps])))
    await db.commit()
    return imp


async def test_import_records_imported_event(client, admin, db):
    _, headers = admin
    entity = await make_entity(db)
    imp = await _import(db, entity, ["a"])
    finding = await db.scalar(select(Finding).where(Finding.fingerprint == "a"))

    r = await client.get(f"/api/v1/findings/{finding.id}/events", headers=headers)
    assert r.status_code == 200
    events = r.json()
    assert [e["event_type"] for e in events] == ["imported"]
    assert events[0]["actor_type"] == "system"
    assert events[0]["payload"]["import_id"] == str(imp.id)


async def test_reopen_records_event(client, admin, db):
    _, headers = admin
    entity = await make_entity(db)
    await _import(db, entity, ["a"])
    finding = await db.scalar(select(Finding).where(Finding.fingerprint == "a"))
    finding.status = FindingStatus.fixed
    await db.commit()
    await _import(db, entity, ["a"])

    events = (await client.get(f"/api/v1/findings/{finding.id}/events", headers=headers)).json()
    assert [e["event_type"] for e in events] == ["imported", "reopened"]
    assert events[1]["from_status"] == "fixed"
    assert events[1]["to_status"] == "new"


async def test_events_404_for_unknown_finding(client, admin):
    _, headers = admin
    r = await client.get(
        "/api/v1/findings/00000000-0000-0000-0000-000000000000/events", headers=headers
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_events.py -v`
Expected: FAIL (404 на `/events` — эндпоинта нет).

- [ ] **Step 3: Модель `backend/app/models/finding_event.py`**

```python
import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPKMixin
from app.models.finding import FindingStatus


class FindingEventType(str, enum.Enum):
    imported = "imported"
    status_changed = "status_changed"
    reopened = "reopened"
    auto_fixed = "auto_fixed"
    request_created = "request_created"
    request_decided = "request_decided"


class ActorType(str, enum.Enum):
    user = "user"
    agent = "agent"
    system = "system"


class FindingEvent(Base, UUIDPKMixin):
    """Запись истории находки. Только добавление — не редактируется и не удаляется."""

    __tablename__ = "finding_events"

    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    event_type: Mapped[FindingEventType] = mapped_column(
        Enum(FindingEventType, name="finding_event_type"), nullable=False
    )
    actor_type: Mapped[ActorType] = mapped_column(Enum(ActorType, name="actor_type"), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    from_status: Mapped[FindingStatus | None] = mapped_column(
        Enum(FindingStatus, name="finding_status", create_type=False)
    )
    to_status: Mapped[FindingStatus | None] = mapped_column(
        Enum(FindingStatus, name="finding_status", create_type=False)
    )
    reason: Mapped[str | None] = mapped_column(Text)
    reason_tag: Mapped[str | None] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
```

В `backend/app/models/__init__.py` добавить `from app.models.finding_event import ActorType, FindingEvent, FindingEventType` и эти имена в `__all__`.

- [ ] **Step 4: Миграция `backend/migrations/versions/0007_finding_events.py`**

```python
"""finding events (history / audit log)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    finding_status = postgresql.ENUM(name="finding_status", create_type=False)
    op.create_table(
        "finding_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("findings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_type",
            sa.Enum(
                "imported", "status_changed", "reopened", "auto_fixed",
                "request_created", "request_decided",
                name="finding_event_type",
            ),
            nullable=False,
        ),
        sa.Column("actor_type", sa.Enum("user", "agent", "system", name="actor_type"), nullable=False),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_status", finding_status, nullable=True),
        sa.Column("to_status", finding_status, nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reason_tag", sa.String(50), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_finding_events_finding_id", "finding_events", ["finding_id"])
    op.create_index("ix_finding_events_created_at", "finding_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_finding_events_created_at", table_name="finding_events")
    op.drop_index("ix_finding_events_finding_id", table_name="finding_events")
    op.drop_table("finding_events")
    sa.Enum(name="actor_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="finding_event_type").drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 5: Сервис `backend/app/services/events.py`**

```python
"""Запись истории находок."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import FindingStatus
from app.models.finding_event import ActorType, FindingEvent, FindingEventType


def record_event(
    db: AsyncSession,
    finding_id: uuid.UUID,
    event_type: FindingEventType,
    *,
    actor_type: ActorType = ActorType.system,
    actor_id: uuid.UUID | None = None,
    from_status: FindingStatus | None = None,
    to_status: FindingStatus | None = None,
    reason: str | None = None,
    reason_tag: str | None = None,
    payload: dict[str, Any] | None = None,
) -> FindingEvent:
    event = FindingEvent(
        finding_id=finding_id,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        reason_tag=reason_tag,
        payload=payload or {},
    )
    db.add(event)
    return event
```

- [ ] **Step 6: События — полный новый `backend/app/services/import_processing.py`**

```python
"""Применение распарсенного SARIF к базе: создание, дедупликация, переоткрытие."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding, FindingStatus
from app.models.finding_event import FindingEventType
from app.models.import_ import Import
from app.services.entity_tree import branch_allowed, branch_rejection_message, resolve_default_branch
from app.services.events import record_event
from app.services.sarif import SarifRun, get_normalizer


class ImportRejected(Exception):
    """Импорт не должен попадать в бэклог (например, не основная ветка)."""


def _apply_provenance(imp: Import, runs: list[SarifRun]) -> None:
    for run in runs:
        imp.branch = imp.branch or run.branch
        imp.commit_sha = imp.commit_sha or run.revision


async def apply_import(db: AsyncSession, imp: Import, runs: list[SarifRun]) -> dict[str, Any]:
    """Пишет находки импорта в сессию. Не коммитит — это делает вызывающий."""
    _apply_provenance(imp, runs)
    default_branch = await resolve_default_branch(db, imp.entity_id)
    if not branch_allowed(imp.branch, default_branch):
        raise ImportRejected(branch_rejection_message(imp.branch, default_branch))

    created = updated = duplicates = total_results = 0
    scanner_name: str | None = None
    now = datetime.now(timezone.utc)

    for run in runs:
        scanner_name = run.scanner
        normalizer = get_normalizer(run.scanner)

        for result in run.results:
            total_results += 1
            existing = await db.scalar(
                select(Finding).where(
                    Finding.entity_id == imp.entity_id,
                    Finding.fingerprint == result.fingerprint,
                )
            )

            if existing:
                existing.last_seen = now
                existing.import_id = imp.id
                existing.raw = result.raw
                existing.scan_scope = imp.scan_scope
                existing.commit_sha = imp.commit_sha
                if existing.status == FindingStatus.fixed:
                    existing.status = FindingStatus.new
                    record_event(
                        db, existing.id, FindingEventType.reopened,
                        from_status=FindingStatus.fixed, to_status=FindingStatus.new,
                        payload={"import_id": str(imp.id)},
                    )
                    updated += 1
                else:
                    duplicates += 1
            else:
                # id задаём явно, чтобы сразу сослаться на находку из события
                finding_id = uuid.uuid4()
                db.add(
                    Finding(
                        id=finding_id,
                        entity_id=imp.entity_id,
                        import_id=imp.id,
                        title=result.title,
                        description=result.description,
                        severity=normalizer.severity(result),
                        status=FindingStatus.new,
                        scanner=run.scanner,
                        rule_id=result.rule_id,
                        cwe=result.cwe,
                        file_path=result.file_path,
                        line_start=result.line_start,
                        line_end=result.line_end,
                        fingerprint=result.fingerprint,
                        scan_scope=imp.scan_scope,
                        commit_sha=imp.commit_sha,
                        raw=result.raw,
                    )
                )
                record_event(
                    db, finding_id, FindingEventType.imported,
                    to_status=FindingStatus.new, payload={"import_id": str(imp.id)},
                )
                created += 1

        await db.flush()

    imp.scanner = scanner_name
    return {
        "created": created,
        "updated": updated,
        "duplicates": duplicates,
        "total_results": total_results,
    }
```

(Событие ссылается на находку по FK; при flush SQLAlchemy вставляет `findings` раньше `finding_events` — unit of work упорядочивает таблицы по зависимостям внешних ключей.)

- [ ] **Step 7: Схема и эндпоинт**

`backend/app/schemas/finding_event.py`:

```python
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class FindingEventRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    finding_id: uuid.UUID
    event_type: str
    actor_type: str
    actor_id: uuid.UUID | None
    from_status: str | None
    to_status: str | None
    reason: str | None
    reason_tag: str | None
    payload: dict[str, Any]
    created_at: datetime
```

В `backend/app/api/findings.py` добавить импорты `from app.models.finding_event import FindingEvent` и `from app.schemas.finding_event import FindingEventRead`, и после `get_finding`:

```python
@router.get("/findings/{finding_id}/events", response_model=list[FindingEventRead])
async def list_finding_events(
    finding_id: uuid.UUID,
    _: object = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[FindingEvent]:
    if await db.get(Finding, finding_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    result = await db.scalars(
        select(FindingEvent)
        .where(FindingEvent.finding_id == finding_id)
        .order_by(FindingEvent.created_at, FindingEvent.id)
    )
    return list(result)
```

- [ ] **Step 8: Тесты**

Run: `cd backend && .venv\Scripts\python -m pytest -v`
Expected: все PASS.

Примечание: `created_at` двух событий одного импорта совпадает (`now()` транзакции) — поэтому сортировка ещё и по `id` для стабильности; в тестах события из разных импортов/транзакций.

- [ ] **Step 9: Commit**

```bash
git add backend/app backend/migrations/versions/0007_finding_events.py backend/tests/test_events.py
git commit -m "feat: finding history events (imported, reopened) with API"
```

---

### Task 6: Автозакрытие исчезнувших находок

**Files:**
- Modify: `backend/app/services/import_processing.py`
- Test: `backend/tests/test_auto_close.py`

**Interfaces:**
- Consumes: `record_event`, `FindingEventType.auto_fixed` (Task 5); `Import.close_missing/confirm_empty/scan_scope` (Task 4).
- Produces: `OPEN_STATUSES: tuple[FindingStatus, ...]` в `app/services/import_processing.py`; статистика импорта дополняется `"closed": int` и, при пропуске, `"warnings": list[str]`.

- [ ] **Step 1: Написать падающие тесты `backend/tests/test_auto_close.py`**

```python
from sqlalchemy import select

from app.models import Finding, FindingEvent
from app.models.finding import FindingStatus
from app.models.finding_event import FindingEventType
from app.services.import_processing import apply_import
from app.services.sarif import parse_sarif
from tests.factories import make_entity, make_import, make_sarif


async def _import(db, entity, fps, scanner="Semgrep", **kw):
    imp = await make_import(db, entity, **kw)
    stats = await apply_import(
        db, imp, parse_sarif(make_sarif(scanner, [{"fp": fp} for fp in fps]))
    )
    await db.commit()
    return stats


async def _status(db, fp):
    f = await db.scalar(select(Finding).where(Finding.fingerprint == fp))
    await db.refresh(f)
    return f.status


async def test_missing_finding_is_closed(db):
    entity = await make_entity(db)
    await _import(db, entity, ["a", "b"])
    stats = await _import(db, entity, ["a"])
    assert stats["closed"] == 1
    assert await _status(db, "b") == FindingStatus.fixed
    assert await _status(db, "a") == FindingStatus.new
    f = await db.scalar(select(Finding).where(Finding.fingerprint == "b"))
    ev = await db.scalar(
        select(FindingEvent).where(
            FindingEvent.finding_id == f.id, FindingEvent.event_type == FindingEventType.auto_fixed
        )
    )
    assert ev is not None and ev.from_status == FindingStatus.new


async def test_decided_findings_are_not_closed(db):
    entity = await make_entity(db)
    await _import(db, entity, ["a", "b"])
    f = await db.scalar(select(Finding).where(Finding.fingerprint == "b"))
    f.status = FindingStatus.false_positive
    await db.commit()
    stats = await _import(db, entity, ["a"])
    assert stats["closed"] == 0
    assert await _status(db, "b") == FindingStatus.false_positive


async def test_other_scope_and_scanner_untouched(db):
    entity = await make_entity(db)
    await _import(db, entity, ["api1"], scanner="Trivy", scan_scope="api:latest")
    await _import(db, entity, ["w1"], scanner="Trivy", scan_scope="worker:latest")
    await _import(db, entity, ["s1"], scanner="Semgrep")
    stats = await _import(db, entity, ["api2"], scanner="Trivy", scan_scope="api:latest")
    assert stats["closed"] == 1
    assert await _status(db, "api1") == FindingStatus.fixed
    assert await _status(db, "w1") == FindingStatus.new
    assert await _status(db, "s1") == FindingStatus.new


async def test_empty_report_needs_confirmation(db):
    entity = await make_entity(db)
    await _import(db, entity, ["a"])
    stats = await _import(db, entity, [])
    assert stats["closed"] == 0
    assert stats["warnings"]
    assert await _status(db, "a") == FindingStatus.new

    stats = await _import(db, entity, [], confirm_empty=True)
    assert stats["closed"] == 1
    assert await _status(db, "a") == FindingStatus.fixed


async def test_close_missing_disabled(db):
    entity = await make_entity(db)
    await _import(db, entity, ["a", "b"])
    stats = await _import(db, entity, ["a"], close_missing=False)
    assert stats["closed"] == 0
    assert await _status(db, "b") == FindingStatus.new


async def test_in_progress_is_closed(db):
    entity = await make_entity(db)
    await _import(db, entity, ["a", "b"])
    f = await db.scalar(select(Finding).where(Finding.fingerprint == "b"))
    f.status = FindingStatus.in_progress
    await db.commit()
    await _import(db, entity, ["a"])
    assert await _status(db, "b") == FindingStatus.fixed
```

Добавить `FindingEvent` в импорт из `app.models` (уже экспортирован в Task 5).

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_auto_close.py -v`
Expected: FAIL с `KeyError: 'closed'`.

- [ ] **Step 3: Реализация — полный новый `backend/app/services/import_processing.py`**

```python
"""Применение распарсенного SARIF к базе: создание, дедупликация, переоткрытие, автозакрытие."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding, FindingStatus
from app.models.finding_event import FindingEventType
from app.models.import_ import Import
from app.services.entity_tree import branch_allowed, branch_rejection_message, resolve_default_branch
from app.services.events import record_event
from app.services.sarif import SarifRun, get_normalizer

# Статусы, которые автозакрытие переводит в fixed. Решения людей (ложное/риск) не трогаем.
OPEN_STATUSES: tuple[FindingStatus, ...] = (
    FindingStatus.new,
    FindingStatus.triaged,
    FindingStatus.confirmed,
    FindingStatus.in_progress,
)


class ImportRejected(Exception):
    """Импорт не должен попадать в бэклог (например, не основная ветка)."""


def _apply_provenance(imp: Import, runs: list[SarifRun]) -> None:
    for run in runs:
        imp.branch = imp.branch or run.branch
        imp.commit_sha = imp.commit_sha or run.revision


async def _close_missing(
    db: AsyncSession, imp: Import, seen: dict[str, set[str]]
) -> tuple[int, list[str]]:
    """Закрывает открытые находки объёма (актив, сканер, scan_scope), которых нет в отчёте."""
    closed = 0
    warnings: list[str] = []
    for scanner, fingerprints in seen.items():
        q = select(Finding).where(
            Finding.entity_id == imp.entity_id,
            Finding.scanner == scanner,
            Finding.scan_scope.is_not_distinct_from(imp.scan_scope),
            Finding.status.in_(OPEN_STATUSES),
        )
        if fingerprints:
            q = q.where(Finding.fingerprint.not_in(fingerprints))
        missing = list(await db.scalars(q))
        if not missing:
            continue
        if not fingerprints and not imp.confirm_empty:
            warnings.append(
                f"{scanner}: отчёт пустой — автозакрытие {len(missing)} находок пропущено "
                "(передайте confirm_empty=true, если уязвимостей действительно нет)"
            )
            continue
        for finding in missing:
            previous = finding.status
            finding.status = FindingStatus.fixed
            record_event(
                db, finding.id, FindingEventType.auto_fixed,
                from_status=previous, to_status=FindingStatus.fixed,
                reason="Не обнаружена при повторном скане",
                payload={"import_id": str(imp.id)},
            )
            closed += 1
    return closed, warnings


async def apply_import(db: AsyncSession, imp: Import, runs: list[SarifRun]) -> dict[str, Any]:
    """Пишет находки импорта в сессию. Не коммитит — это делает вызывающий."""
    _apply_provenance(imp, runs)
    default_branch = await resolve_default_branch(db, imp.entity_id)
    if not branch_allowed(imp.branch, default_branch):
        raise ImportRejected(branch_rejection_message(imp.branch, default_branch))

    created = updated = duplicates = total_results = 0
    scanner_name: str | None = None
    now = datetime.now(timezone.utc)
    seen: dict[str, set[str]] = {}

    for run in runs:
        scanner_name = run.scanner
        # пустой отчёт сканера тоже участвует в автозакрытии
        scanner_seen = seen.setdefault(run.scanner, set())
        normalizer = get_normalizer(run.scanner)

        for result in run.results:
            total_results += 1
            scanner_seen.add(result.fingerprint)
            existing = await db.scalar(
                select(Finding).where(
                    Finding.entity_id == imp.entity_id,
                    Finding.fingerprint == result.fingerprint,
                )
            )

            if existing:
                existing.last_seen = now
                existing.import_id = imp.id
                existing.raw = result.raw
                existing.scan_scope = imp.scan_scope
                existing.commit_sha = imp.commit_sha
                if existing.status == FindingStatus.fixed:
                    existing.status = FindingStatus.new
                    record_event(
                        db, existing.id, FindingEventType.reopened,
                        from_status=FindingStatus.fixed, to_status=FindingStatus.new,
                        payload={"import_id": str(imp.id)},
                    )
                    updated += 1
                else:
                    duplicates += 1
            else:
                finding_id = uuid.uuid4()
                db.add(
                    Finding(
                        id=finding_id,
                        entity_id=imp.entity_id,
                        import_id=imp.id,
                        title=result.title,
                        description=result.description,
                        severity=normalizer.severity(result),
                        status=FindingStatus.new,
                        scanner=run.scanner,
                        rule_id=result.rule_id,
                        cwe=result.cwe,
                        file_path=result.file_path,
                        line_start=result.line_start,
                        line_end=result.line_end,
                        fingerprint=result.fingerprint,
                        scan_scope=imp.scan_scope,
                        commit_sha=imp.commit_sha,
                        raw=result.raw,
                    )
                )
                record_event(
                    db, finding_id, FindingEventType.imported,
                    to_status=FindingStatus.new, payload={"import_id": str(imp.id)},
                )
                created += 1

        await db.flush()

    closed, warnings = (0, [])
    if imp.close_missing:
        closed, warnings = await _close_missing(db, imp, seen)
        await db.flush()

    imp.scanner = scanner_name
    stats: dict[str, Any] = {
        "created": created,
        "updated": updated,
        "duplicates": duplicates,
        "total_results": total_results,
        "closed": closed,
    }
    if warnings:
        stats["warnings"] = warnings
    return stats
```

- [ ] **Step 4: Тесты**

Run: `cd backend && .venv\Scripts\python -m pytest -v`
Expected: все PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_processing.py backend/tests/test_auto_close.py
git commit -m "feat: auto-close findings missing from a rescan of the same scope"
```

---

### Task 7: Короткие номера SV-N

**Files:**
- Create: `backend/migrations/versions/0008_finding_numbers.py`
- Modify: `backend/app/models/finding.py` (поле `number`)
- Modify: `backend/app/schemas/finding.py` (`number: int`)
- Modify: `backend/app/api/findings.py` (`GET /findings/by-number/{number}`)
- Test: `backend/tests/test_numbers.py`

**Interfaces:**
- Produces: `Finding.number: int` (уникальный, из последовательности `finding_number_seq`); `GET /api/v1/findings/by-number/{number}` → `FindingRead`. Отображение `SV-{number}` — на фронтенде.

- [ ] **Step 1: Падающие тесты `backend/tests/test_numbers.py`**

```python
from tests.factories import make_entity, make_finding


async def test_findings_get_sequential_numbers(db):
    entity = await make_entity(db)
    f1 = await make_finding(db, entity, "a")
    f2 = await make_finding(db, entity, "b")
    assert f1.number > 0
    assert f2.number == f1.number + 1


async def test_get_by_number(client, admin, db):
    _, headers = admin
    entity = await make_entity(db)
    f = await make_finding(db, entity, "a")
    r = await client.get(f"/api/v1/findings/by-number/{f.number}", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == str(f.id)
    assert r.json()["number"] == f.number
    assert (await client.get("/api/v1/findings/by-number/999999", headers=headers)).status_code == 404
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_numbers.py -v`
Expected: FAIL (`AttributeError: 'Finding' object has no attribute 'number'`).

- [ ] **Step 3: Миграция `backend/migrations/versions/0008_finding_numbers.py`**

```python
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
```

- [ ] **Step 4: Модель и схема**

`backend/app/models/finding.py` — импорт `BigInteger, text` в строке `from sqlalchemy import ...`; после `import_id`:

```python
    # Короткий номер для ссылок (отображается как SV-<number>)
    number: Mapped[int] = mapped_column(
        BigInteger,
        server_default=text("nextval('finding_number_seq')"),
        unique=True,
        nullable=False,
    )
```

`backend/app/schemas/finding.py` — в `FindingRead` после `id`: `number: int`.

- [ ] **Step 5: Эндпоинт в `backend/app/api/findings.py`** (перед `get_finding`)

```python
@router.get("/findings/by-number/{number}", response_model=FindingRead)
async def get_finding_by_number(
    number: int,
    _: object = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> Finding:
    finding = await db.scalar(select(Finding).where(Finding.number == number))
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    return finding
```

- [ ] **Step 6: Тесты**

Run: `cd backend && .venv\Scripts\python -m pytest -v`
Expected: все PASS. (Если `f1.number` не заполнен после commit — SQLAlchemy 2.0 для PostgreSQL получает server default через `RETURNING`; `make_finding` дополнительно делает `refresh`.)

- [ ] **Step 7: Commit**

```bash
git add backend/app backend/migrations/versions/0008_finding_numbers.py backend/tests/test_numbers.py
git commit -m "feat: short sequential finding numbers (SV-N)"
```

---

### Task 8: Смена статуса с причиной

**Files:**
- Create: (схема) добавить `FindingStatusUpdate` в `backend/app/schemas/finding.py`
- Modify: `backend/app/api/findings.py` (`update_finding_status`)
- Test: `backend/tests/test_status_change.py`

**Interfaces:**
- Consumes: `has_permission`, фикстуры `appsec`/`developer` (Task 3); `record_event` (Task 5).
- Produces: `PATCH /api/v1/findings/{id}` с JSON-телом `{"status": "...", "reason": "..."}` (раньше — query-параметр `?status=`). Вручную разрешены только `new`, `triaged`, `confirmed`, `in_progress`.

- [ ] **Step 1: Падающие тесты `backend/tests/test_status_change.py`**

```python
from app.models.finding import FindingStatus
from tests.factories import make_entity, make_finding


async def test_developer_takes_finding_in_progress(client, developer, db):
    user, headers = developer
    f = await make_finding(db, await make_entity(db))
    r = await client.patch(
        f"/api/v1/findings/{f.id}",
        json={"status": "in_progress", "reason": "Чиню в MR !42"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"

    events = (await client.get(f"/api/v1/findings/{f.id}/events", headers=headers)).json()
    last = events[-1]
    assert last["event_type"] == "status_changed"
    assert last["actor_type"] == "user"
    assert last["actor_id"] == str(user.id)
    assert last["from_status"] == "new"
    assert last["to_status"] == "in_progress"
    assert last["reason"] == "Чиню в MR !42"


async def test_decision_statuses_go_through_requests(client, appsec, db):
    _, headers = appsec
    f = await make_finding(db, await make_entity(db))
    for st in ("false_positive", "risk_accepted"):
        r = await client.patch(f"/api/v1/findings/{f.id}", json={"status": st}, headers=headers)
        assert r.status_code == 400
        assert "decisions" in r.json()["detail"]


async def test_fixed_cannot_be_set_manually(client, appsec, db):
    _, headers = appsec
    f = await make_finding(db, await make_entity(db))
    r = await client.patch(f"/api/v1/findings/{f.id}", json={"status": "fixed"}, headers=headers)
    assert r.status_code == 400


async def test_only_appsec_can_undo_decision(client, developer, appsec, db):
    f = await make_finding(db, await make_entity(db), status=FindingStatus.false_positive)
    _, dev_h = developer
    _, sec_h = appsec
    r = await client.patch(f"/api/v1/findings/{f.id}", json={"status": "new"}, headers=dev_h)
    assert r.status_code == 403
    r = await client.patch(f"/api/v1/findings/{f.id}", json={"status": "new"}, headers=sec_h)
    assert r.status_code == 200
    assert r.json()["status"] == "new"


async def test_same_status_is_noop(client, developer, db):
    _, headers = developer
    f = await make_finding(db, await make_entity(db))
    r = await client.patch(f"/api/v1/findings/{f.id}", json={"status": "new"}, headers=headers)
    assert r.status_code == 200
    events = (await client.get(f"/api/v1/findings/{f.id}/events", headers=headers)).json()
    assert events == []
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_status_change.py -v`
Expected: FAIL (422 — эндпоинт ждёт `?status=` в query).

- [ ] **Step 3: Схема в `backend/app/schemas/finding.py`**

```python
from pydantic import BaseModel, Field

from app.models.finding import FindingStatus


class FindingStatusUpdate(BaseModel):
    status: FindingStatus
    reason: str | None = Field(default=None, max_length=2000)
```

- [ ] **Step 4: Эндпоинт в `backend/app/api/findings.py`**

Импорты: `from app.api.deps import Principal, has_permission, require_permission`, `from app.models.finding_event import ActorType, FindingEventType`, `from app.schemas.finding import FindingRead, FindingStatusUpdate`, `from app.services.events import record_event`.

Функцию `update_finding_status` заменить на:

```python
# Ставятся вручную. Ложное/риск — через запросы (decisions), «Исправлена» — только повторным сканом.
MANUAL_STATUSES = {
    FindingStatus.new,
    FindingStatus.triaged,
    FindingStatus.confirmed,
    FindingStatus.in_progress,
}
DECISION_STATUSES = {FindingStatus.false_positive, FindingStatus.risk_accepted}


@router.patch("/findings/{finding_id}", response_model=FindingRead)
async def update_finding_status(
    finding_id: uuid.UUID,
    data: FindingStatusUpdate,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> Finding:
    finding = await db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")

    if data.status in DECISION_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "«Ложное срабатывание» и «Риск принят» оформляются запросом: "
            f"POST /api/v1/findings/{finding_id}/decisions",
        )
    if data.status == FindingStatus.fixed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "«Исправлена» ставится автоматически, когда повторный скан не находит уязвимость",
        )
    if finding.status in DECISION_STATUSES and not has_permission(principal, "finding", "approve"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Снять решение может только AppSec (право finding:approve)"
        )

    if finding.status != data.status:
        previous = finding.status
        finding.status = data.status
        record_event(
            db, finding.id, FindingEventType.status_changed,
            actor_type=ActorType.user, actor_id=principal.user.id,
            from_status=previous, to_status=data.status,
            reason=(data.reason or "").strip() or None,
        )
        await db.commit()
        await db.refresh(finding)
    return finding
```

- [ ] **Step 5: Тесты**

Run: `cd backend && .venv\Scripts\python -m pytest -v`
Expected: все PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/findings.py backend/app/schemas/finding.py backend/tests/test_status_change.py
git commit -m "feat: status change with reason, history event and decision guards"
```

---

### Task 9: Запросы на решение (ложное / риск принят)

**Files:**
- Create: `backend/app/models/decision_request.py`
- Create: `backend/migrations/versions/0009_decision_requests.py`
- Create: `backend/app/schemas/decision.py`
- Create: `backend/app/services/decisions.py`
- Create: `backend/app/api/decisions.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py` (роутер)
- Test: `backend/tests/test_decisions.py`

**Interfaces:**
- Consumes: `has_permission` (Task 3), `record_event` (Task 5).
- Produces: `DecisionType` = `false_positive | risk_accepted`; `DecisionStatus` = `pending | approved | rejected | expired`; `ReasonTag` = `data_not_user_controlled | test_code | sanitized | dead_code | other`.
- Produces: `async def create_request(db, finding: Finding, data: DecisionCreate, *, user_id: uuid.UUID, can_approve: bool) -> DecisionRequest`; `async def approve_request(db, req: DecisionRequest, finding: Finding, *, user_id: uuid.UUID, comment: str | None) -> None`; `async def reject_request(db, req, finding, *, user_id, comment: str) -> None`; `class DecisionError(Exception)` с полями `status_code: int`, `message: str`.
- Produces API: `POST /findings/{id}/decisions` (triage), `GET /findings/{id}/decisions` (read), `GET /decisions?status=pending` (read), `POST /decisions/{id}/approve` (approve), `POST /decisions/{id}/reject` (approve).

- [ ] **Step 1: Падающие тесты `backend/tests/test_decisions.py`**

```python
from datetime import datetime, timedelta, timezone

from app.models.finding import FindingStatus
from tests.factories import make_entity, make_finding


def _fp(tag="test_code", reason=None):
    body = {"decision_type": "false_positive", "reason_tag": tag}
    if reason is not None:
        body["reason"] = reason
    return body


async def test_developer_request_waits_for_appsec(client, developer, db):
    _, headers = developer
    f = await make_finding(db, await make_entity(db))
    r = await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=headers)
    assert r.status_code == 201
    assert r.json()["status"] == "pending"
    finding = (await client.get(f"/api/v1/findings/{f.id}", headers=headers)).json()
    assert finding["status"] == "new"
    events = (await client.get(f"/api/v1/findings/{f.id}/events", headers=headers)).json()
    assert events[-1]["event_type"] == "request_created"
    assert events[-1]["reason_tag"] == "test_code"


async def test_second_pending_request_conflicts(client, developer, db):
    _, headers = developer
    f = await make_finding(db, await make_entity(db))
    await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=headers)
    r = await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=headers)
    assert r.status_code == 409


async def test_validation(client, developer, db):
    _, headers = developer
    f = await make_finding(db, await make_entity(db))
    url = f"/api/v1/findings/{f.id}/decisions"
    assert (await client.post(url, json=_fp(tag="other"), headers=headers)).status_code == 422
    assert (await client.post(url, json={"decision_type": "false_positive"}, headers=headers)).status_code == 422
    risk = {"decision_type": "risk_accepted", "reason": "Сервис выводим из эксплуатации"}
    assert (await client.post(url, json=risk, headers=headers)).status_code == 422
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert (await client.post(url, json={**risk, "expires_at": past}, headers=headers)).status_code == 422


async def test_appsec_approves(client, developer, appsec, db):
    _, dev_h = developer
    sec_user, sec_h = appsec
    f = await make_finding(db, await make_entity(db))
    req = (await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=dev_h)).json()

    r = await client.post(f"/api/v1/decisions/{req['id']}/approve", json={"comment": "Ок"}, headers=sec_h)
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert r.json()["decided_by_id"] == str(sec_user.id)
    finding = (await client.get(f"/api/v1/findings/{f.id}", headers=sec_h)).json()
    assert finding["status"] == "false_positive"
    events = (await client.get(f"/api/v1/findings/{f.id}/events", headers=sec_h)).json()
    assert events[-1]["event_type"] == "request_decided"
    assert events[-1]["to_status"] == "false_positive"


async def test_developer_cannot_approve(client, developer, db):
    _, headers = developer
    f = await make_finding(db, await make_entity(db))
    req = (await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=headers)).json()
    r = await client.post(f"/api/v1/decisions/{req['id']}/approve", json={}, headers=headers)
    assert r.status_code == 403


async def test_appsec_decision_applies_immediately(client, appsec, db):
    _, headers = appsec
    f = await make_finding(db, await make_entity(db))
    r = await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=headers)
    assert r.status_code == 201
    assert r.json()["status"] == "approved"
    finding = (await client.get(f"/api/v1/findings/{f.id}", headers=headers)).json()
    assert finding["status"] == "false_positive"


async def test_reject_requires_comment_and_keeps_status(client, developer, appsec, db):
    _, dev_h = developer
    _, sec_h = appsec
    f = await make_finding(db, await make_entity(db))
    req = (await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=dev_h)).json()
    url = f"/api/v1/decisions/{req['id']}/reject"
    assert (await client.post(url, json={}, headers=sec_h)).status_code == 422
    r = await client.post(url, json={"comment": "Данные приходят из query-параметра"}, headers=sec_h)
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    finding = (await client.get(f"/api/v1/findings/{f.id}", headers=sec_h)).json()
    assert finding["status"] == "new"
    # после отклонения можно подать новый запрос
    again = await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=dev_h)
    assert again.status_code == 201


async def test_request_on_closed_finding_conflicts(client, developer, db):
    _, headers = developer
    f = await make_finding(db, await make_entity(db), status=FindingStatus.fixed)
    r = await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=headers)
    assert r.status_code == 409


async def test_risk_acceptance_with_expiry(client, appsec, db):
    _, headers = appsec
    f = await make_finding(db, await make_entity(db))
    expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    r = await client.post(
        f"/api/v1/findings/{f.id}/decisions",
        json={"decision_type": "risk_accepted", "reason": "Компенсирующий WAF", "expires_at": expires},
        headers=headers,
    )
    assert r.status_code == 201
    assert r.json()["expires_at"] is not None
    finding = (await client.get(f"/api/v1/findings/{f.id}", headers=headers)).json()
    assert finding["status"] == "risk_accepted"


async def test_pending_list(client, developer, appsec, db):
    _, dev_h = developer
    _, sec_h = appsec
    f = await make_finding(db, await make_entity(db))
    await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=dev_h)
    r = await client.get("/api/v1/decisions", params={"status": "pending"}, headers=sec_h)
    assert r.status_code == 200
    assert [d["finding_id"] for d in r.json()] == [str(f.id)]
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_decisions.py -v`
Expected: FAIL (404 — эндпоинтов нет).

- [ ] **Step 3: Модель `backend/app/models/decision_request.py`**

```python
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class DecisionType(str, enum.Enum):
    false_positive = "false_positive"
    risk_accepted = "risk_accepted"


class DecisionStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"  # истёк срок принятия риска


class ReasonTag(str, enum.Enum):
    data_not_user_controlled = "data_not_user_controlled"  # Данные не приходят от пользователя
    test_code = "test_code"                                # Тестовый или демо-код
    sanitized = "sanitized"                                # Уже есть проверка или экранирование
    dead_code = "dead_code"                                # Код не используется
    other = "other"                                        # Другое (текст обязателен)


class DecisionRequest(Base, UUIDPKMixin, TimestampMixin):
    """Запрос «ложное срабатывание» / «риск принят». Правило двух ключей:
    разработчик запрашивает, AppSec (finding:approve) одобряет."""

    __tablename__ = "decision_requests"
    __table_args__ = (
        Index(
            "uq_decision_requests_pending",
            "finding_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    decision_type: Mapped[DecisionType] = mapped_column(
        Enum(DecisionType, name="decision_type"), nullable=False
    )
    status: Mapped[DecisionStatus] = mapped_column(
        Enum(DecisionStatus, name="decision_status"),
        default=DecisionStatus.pending,
        index=True,
        nullable=False,
    )
    reason_tag: Mapped[ReasonTag | None] = mapped_column(Enum(ReasonTag, name="reason_tag"))
    reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decision_comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

В `backend/app/models/__init__.py` добавить `from app.models.decision_request import DecisionRequest, DecisionStatus, DecisionType, ReasonTag` и имена в `__all__`.

- [ ] **Step 4: Миграция `backend/migrations/versions/0009_decision_requests.py`**

```python
"""decision requests (false positive / risk acceptance with approval)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("findings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "decision_type",
            sa.Enum("false_positive", "risk_accepted", name="decision_type"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", "expired", name="decision_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "reason_tag",
            sa.Enum(
                "data_not_user_controlled", "test_code", "sanitized", "dead_code", "other",
                name="reason_tag",
            ),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "requested_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "decided_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_decision_requests_finding_id", "decision_requests", ["finding_id"])
    op.create_index("ix_decision_requests_status", "decision_requests", ["status"])
    op.create_index(
        "uq_decision_requests_pending",
        "decision_requests",
        ["finding_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_decision_requests_pending", table_name="decision_requests")
    op.drop_index("ix_decision_requests_status", table_name="decision_requests")
    op.drop_index("ix_decision_requests_finding_id", table_name="decision_requests")
    op.drop_table("decision_requests")
    for name in ("reason_tag", "decision_status", "decision_type"):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 5: Схемы `backend/app/schemas/decision.py`**

```python
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator

from app.models.decision_request import DecisionType, ReasonTag


class DecisionCreate(BaseModel):
    decision_type: DecisionType
    reason_tag: ReasonTag | None = None
    reason: str | None = Field(default=None, max_length=2000)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _check(self) -> "DecisionCreate":
        reason = (self.reason or "").strip()
        if self.decision_type == DecisionType.false_positive:
            if self.reason_tag is None:
                raise ValueError("Укажите причину ложного срабатывания")
            if self.reason_tag == ReasonTag.other and not reason:
                raise ValueError("Для причины «Другое» опишите её текстом")
            if self.expires_at is not None:
                raise ValueError("Срок задаётся только для принятия риска")
        else:
            if not reason:
                raise ValueError("Опишите, почему риск можно принять")
            if self.expires_at is None:
                raise ValueError("Укажите срок, до которого риск принят")
            expires = self.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= datetime.now(timezone.utc):
                raise ValueError("Срок принятия риска должен быть в будущем")
            self.expires_at = expires
        self.reason = reason or None
        return self


class DecisionApprove(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class DecisionReject(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)


class DecisionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    finding_id: uuid.UUID
    decision_type: str
    status: str
    reason_tag: str | None
    reason: str | None
    expires_at: datetime | None
    requested_by_id: uuid.UUID | None
    decided_by_id: uuid.UUID | None
    decision_comment: str | None
    decided_at: datetime | None
    created_at: datetime
```

- [ ] **Step 6: Сервис `backend/app/services/decisions.py`**

```python
"""Запросы «ложное срабатывание» / «риск принят» и их рассмотрение."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_request import DecisionRequest, DecisionStatus
from app.models.finding import Finding, FindingStatus
from app.models.finding_event import ActorType, FindingEventType
from app.schemas.decision import DecisionCreate
from app.services.events import record_event

# Находка в этих статусах уже не нуждается в решении
CLOSED_STATUSES = (FindingStatus.false_positive, FindingStatus.risk_accepted, FindingStatus.fixed)


class DecisionError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _tag(req: DecisionRequest) -> str | None:
    return req.reason_tag.value if req.reason_tag else None


async def create_request(
    db: AsyncSession,
    finding: Finding,
    data: DecisionCreate,
    *,
    user_id: uuid.UUID,
    can_approve: bool,
) -> DecisionRequest:
    if finding.status in CLOSED_STATUSES:
        raise DecisionError(409, "Находка уже закрыта — решение не требуется")
    pending = await db.scalar(
        select(DecisionRequest).where(
            DecisionRequest.finding_id == finding.id,
            DecisionRequest.status == DecisionStatus.pending,
        )
    )
    if pending is not None:
        raise DecisionError(409, "По находке уже есть запрос на рассмотрении")

    req = DecisionRequest(
        id=uuid.uuid4(),
        finding_id=finding.id,
        decision_type=data.decision_type,
        status=DecisionStatus.pending,
        reason_tag=data.reason_tag,
        reason=data.reason,
        expires_at=data.expires_at,
        requested_by_id=user_id,
    )
    db.add(req)
    record_event(
        db, finding.id, FindingEventType.request_created,
        actor_type=ActorType.user, actor_id=user_id,
        reason=req.reason, reason_tag=_tag(req),
        payload={"decision_id": str(req.id), "decision_type": req.decision_type.value},
    )
    if can_approve:
        await approve_request(db, req, finding, user_id=user_id, comment=None)
    return req


async def approve_request(
    db: AsyncSession,
    req: DecisionRequest,
    finding: Finding,
    *,
    user_id: uuid.UUID,
    comment: str | None,
) -> None:
    if req.status != DecisionStatus.pending:
        raise DecisionError(409, "Запрос уже рассмотрен")
    req.status = DecisionStatus.approved
    req.decided_by_id = user_id
    req.decided_at = datetime.now(timezone.utc)
    req.decision_comment = comment
    previous = finding.status
    finding.status = FindingStatus(req.decision_type.value)
    record_event(
        db, finding.id, FindingEventType.request_decided,
        actor_type=ActorType.user, actor_id=user_id,
        from_status=previous, to_status=finding.status,
        reason=req.reason, reason_tag=_tag(req),
        payload={"decision_id": str(req.id), "result": "approved", "comment": comment},
    )


async def reject_request(
    db: AsyncSession,
    req: DecisionRequest,
    finding: Finding,
    *,
    user_id: uuid.UUID,
    comment: str,
) -> None:
    if req.status != DecisionStatus.pending:
        raise DecisionError(409, "Запрос уже рассмотрен")
    req.status = DecisionStatus.rejected
    req.decided_by_id = user_id
    req.decided_at = datetime.now(timezone.utc)
    req.decision_comment = comment
    record_event(
        db, finding.id, FindingEventType.request_decided,
        actor_type=ActorType.user, actor_id=user_id,
        reason=comment,
        payload={"decision_id": str(req.id), "result": "rejected"},
    )
```

- [ ] **Step 7: Роутер `backend/app/api/decisions.py`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, has_permission, require_permission
from app.db.session import get_db
from app.models import DecisionRequest, Finding
from app.models.decision_request import DecisionStatus
from app.schemas.decision import DecisionApprove, DecisionCreate, DecisionRead, DecisionReject
from app.services.decisions import DecisionError, approve_request, create_request, reject_request

router = APIRouter(prefix="/api/v1", tags=["decisions"])


async def _finding_or_404(db: AsyncSession, finding_id: uuid.UUID) -> Finding:
    finding = await db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    return finding


async def _request_or_404(db: AsyncSession, decision_id: uuid.UUID) -> DecisionRequest:
    req = await db.get(DecisionRequest, decision_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision request not found")
    return req


@router.post(
    "/findings/{finding_id}/decisions",
    response_model=DecisionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_decision(
    finding_id: uuid.UUID,
    data: DecisionCreate,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> DecisionRequest:
    finding = await _finding_or_404(db, finding_id)
    try:
        req = await create_request(
            db, finding, data,
            user_id=principal.user.id,
            can_approve=has_permission(principal, "finding", "approve"),
        )
    except DecisionError as exc:
        raise HTTPException(exc.status_code, exc.message)
    await db.commit()
    await db.refresh(req)
    return req


@router.get("/findings/{finding_id}/decisions", response_model=list[DecisionRead])
async def list_finding_decisions(
    finding_id: uuid.UUID,
    _: object = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionRequest]:
    await _finding_or_404(db, finding_id)
    result = await db.scalars(
        select(DecisionRequest)
        .where(DecisionRequest.finding_id == finding_id)
        .order_by(DecisionRequest.created_at.desc())
    )
    return list(result)


@router.get("/decisions", response_model=list[DecisionRead])
async def list_decisions(
    decision_status: DecisionStatus | None = Query(None, alias="status"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    _: object = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionRequest]:
    q = select(DecisionRequest)
    if decision_status:
        q = q.where(DecisionRequest.status == decision_status)
    q = q.order_by(DecisionRequest.created_at).offset(offset).limit(limit)
    return list(await db.scalars(q))


@router.post("/decisions/{decision_id}/approve", response_model=DecisionRead)
async def approve_decision(
    decision_id: uuid.UUID,
    data: DecisionApprove,
    principal: Principal = Depends(require_permission("finding", "approve")),
    db: AsyncSession = Depends(get_db),
) -> DecisionRequest:
    req = await _request_or_404(db, decision_id)
    finding = await _finding_or_404(db, req.finding_id)
    try:
        await approve_request(db, req, finding, user_id=principal.user.id, comment=data.comment)
    except DecisionError as exc:
        raise HTTPException(exc.status_code, exc.message)
    await db.commit()
    await db.refresh(req)
    return req


@router.post("/decisions/{decision_id}/reject", response_model=DecisionRead)
async def reject_decision(
    decision_id: uuid.UUID,
    data: DecisionReject,
    principal: Principal = Depends(require_permission("finding", "approve")),
    db: AsyncSession = Depends(get_db),
) -> DecisionRequest:
    req = await _request_or_404(db, decision_id)
    finding = await _finding_or_404(db, req.finding_id)
    try:
        await reject_request(db, req, finding, user_id=principal.user.id, comment=data.comment)
    except DecisionError as exc:
        raise HTTPException(exc.status_code, exc.message)
    await db.commit()
    await db.refresh(req)
    return req
```

В `backend/app/main.py`: `from app.api.decisions import router as decisions_router` и `app.include_router(decisions_router)` после `findings_router`.

- [ ] **Step 8: Тесты**

Run: `cd backend && .venv\Scripts\python -m pytest -v`
Expected: все PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app backend/migrations/versions/0009_decision_requests.py backend/tests/test_decisions.py
git commit -m "feat: false-positive / risk-acceptance requests with AppSec approval"
```

---

### Task 10: Истечение принятого риска

**Files:**
- Create: `backend/app/services/risk_expiry.py`
- Modify: `backend/app/worker.py` (cron-задача)
- Test: `backend/tests/test_risk_expiry.py`

**Interfaces:**
- Consumes: `DecisionRequest` (Task 9), `record_event` (Task 5).
- Produces: `async def expire_risk_acceptances(db: AsyncSession, now: datetime | None = None) -> int` — коммитит; возвращает число переоткрытых находок. ARQ cron `expire_risks` ежедневно в 03:00.

- [ ] **Step 1: Падающие тесты `backend/tests/test_risk_expiry.py`**

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import DecisionRequest, FindingEvent
from app.models.decision_request import DecisionStatus, DecisionType
from app.models.finding import FindingStatus
from app.models.finding_event import FindingEventType
from app.services.risk_expiry import expire_risk_acceptances
from tests.factories import make_entity, make_finding


async def _accepted(db, entity, fp, expires_at):
    f = await make_finding(db, entity, fp, status=FindingStatus.risk_accepted)
    req = DecisionRequest(
        finding_id=f.id,
        decision_type=DecisionType.risk_accepted,
        status=DecisionStatus.approved,
        reason="WAF",
        expires_at=expires_at,
    )
    db.add(req)
    await db.commit()
    return f, req


async def test_expired_risk_reopens(db):
    entity = await make_entity(db)
    now = datetime.now(timezone.utc)
    old, old_req = await _accepted(db, entity, "a", now - timedelta(hours=1))
    fresh, fresh_req = await _accepted(db, entity, "b", now + timedelta(days=10))

    assert await expire_risk_acceptances(db, now=now) == 1

    for obj in (old, old_req, fresh, fresh_req):
        await db.refresh(obj)
    assert old.status == FindingStatus.new
    assert old_req.status == DecisionStatus.expired
    assert fresh.status == FindingStatus.risk_accepted
    assert fresh_req.status == DecisionStatus.approved
    ev = await db.scalar(
        select(FindingEvent).where(
            FindingEvent.finding_id == old.id, FindingEvent.event_type == FindingEventType.reopened
        )
    )
    assert ev is not None and ev.from_status == FindingStatus.risk_accepted


async def test_expiry_is_idempotent(db):
    entity = await make_entity(db)
    now = datetime.now(timezone.utc)
    await _accepted(db, entity, "a", now - timedelta(hours=1))
    assert await expire_risk_acceptances(db, now=now) == 1
    assert await expire_risk_acceptances(db, now=now) == 0
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_risk_expiry.py -v`
Expected: FAIL (`ModuleNotFoundError: app.services.risk_expiry`).

- [ ] **Step 3: `backend/app/services/risk_expiry.py`**

```python
"""Истечение срока принятого риска: находка возвращается в «Новая»."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_request import DecisionRequest, DecisionStatus, DecisionType
from app.models.finding import Finding, FindingStatus
from app.models.finding_event import FindingEventType
from app.services.events import record_event


async def expire_risk_acceptances(db: AsyncSession, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    requests = await db.scalars(
        select(DecisionRequest).where(
            DecisionRequest.decision_type == DecisionType.risk_accepted,
            DecisionRequest.status == DecisionStatus.approved,
            DecisionRequest.expires_at <= now,
        )
    )
    reopened = 0
    for req in list(requests):
        req.status = DecisionStatus.expired
        finding = await db.get(Finding, req.finding_id)
        if finding is not None and finding.status == FindingStatus.risk_accepted:
            finding.status = FindingStatus.new
            record_event(
                db, finding.id, FindingEventType.reopened,
                from_status=FindingStatus.risk_accepted, to_status=FindingStatus.new,
                reason="Истёк срок принятия риска",
                payload={"decision_id": str(req.id)},
            )
            reopened += 1
    await db.commit()
    return reopened
```

- [ ] **Step 4: Cron в `backend/app/worker.py`**

Импорты: `from arq import create_pool, cron` и `from app.services.risk_expiry import expire_risk_acceptances`. После `process_import`:

```python
async def expire_risks(ctx: dict) -> None:
    session_factory: async_sessionmaker = ctx["session_factory"]
    async with session_factory() as db:
        reopened = await expire_risk_acceptances(db)
    logger.info("Risk expiry: %d findings reopened", reopened)
```

В `WorkerSettings` добавить:

```python
    cron_jobs = [cron(expire_risks, hour={3}, minute={0})]
```

- [ ] **Step 5: Тесты**

Run: `cd backend && .venv\Scripts\python -m pytest -v`
Expected: все PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/risk_expiry.py backend/app/worker.py backend/tests/test_risk_expiry.py
git commit -m "feat: reopen findings when accepted risk expires (daily ARQ cron)"
```

---

### Task 11: Фронтенд, smoke-тест, документация

**Files:**
- Modify: `frontend/src/i18n/ru.json` (`status.in_progress`, `findings.number`)
- Modify: `frontend/src/pages/Findings.tsx` (статус в фильтре, колонка номера)
- Modify: `frontend/DESIGN.md` (строка словаря)
- Create: `scripts/samples/semgrep-rescan.sarif`
- Modify: `scripts/smoke-test.ps1` (логин, проверка автозакрытия)
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: `FindingRead.number` (Task 7), `FindingStatus.in_progress` (Task 4), `stats.closed` (Task 6).

- [ ] **Step 1: Переводы в `frontend/src/i18n/ru.json`**

В `status` после `"confirmed": "Подтверждена",` добавить `"in_progress": "В работе",`. В `findings` после `"title": "Находки",` добавить `"number": "№",`.

- [ ] **Step 2: `frontend/src/pages/Findings.tsx`**

В `interface FindingRecord` после `id: string;` добавить `number: number;`.

Строку `const statuses = [...]` заменить на:

```tsx
  const statuses = ["new", "triaged", "confirmed", "in_progress", "false_positive", "risk_accepted", "fixed"];
```

В `<thead>` первой колонкой добавить:

```tsx
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>{t("findings.number")}</th>
```

В строке таблицы первой ячейкой добавить:

```tsx
                  <td style={{ padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-secondary)", whiteSpace: "nowrap" }}>
                    SV-{f.number}
                  </td>
```

- [ ] **Step 3: Сборка фронтенда**

Run: `cd frontend && npm run build`
Expected: сборка без ошибок TypeScript.

- [ ] **Step 4: `frontend/DESIGN.md`**

Строку словаря `| new/triaged/confirmed | Новая / В разборе / Подтверждена |` заменить на:

```markdown
| new/triaged/confirmed/in_progress | Новая / В разборе / Подтверждена / В работе |
```

В разделе «Статусы находок» строку заменить на: «Новая — синий (акцент), В разборе — янтарный, Подтверждена — оранжевый, В работе — фиолетовый, Исправлена — зелёный, Ложное срабатывание / Риск принят — серый.»

- [ ] **Step 5: Пример повторного скана `scripts/samples/semgrep-rescan.sarif`**

Скопировать `scripts/samples/semgrep.sarif` и удалить из `results` последний элемент (правило `python.lang.security.audit.eval-detected`, fingerprint `smg-hhh888`). Остальные 4 результата — без изменений.

- [ ] **Step 6: `scripts/smoke-test.ps1`**

После блока «0. Проверка сервисов» добавить логин:

```powershell
# --- 0.1 Логин (API закрыт авторизацией) ---
$adminEmail = if ($env:SV_ADMIN_EMAIL) { $env:SV_ADMIN_EMAIL } else { "admin@secretvuln.local" }
$adminPassword = if ($env:SV_ADMIN_PASSWORD) { $env:SV_ADMIN_PASSWORD } else { "Admin12345!" }
try {
    $login = Invoke-RestMethod "$api/auth/login" -Method Post -ContentType "application/json" `
        -Body (@{ email = $adminEmail; password = $adminPassword } | ConvertTo-Json)
} catch { Fail "не удалось войти как $adminEmail — создай админа: python -m app.cli create-admin" }
$headers = @{ Authorization = "Bearer $($login.access_token)" }
$authArg = "Authorization: Bearer $($login.access_token)"
Ok "вход выполнен ($adminEmail)"
```

Во всех вызовах `Invoke-RestMethod` к `$api/entities`, `$api/imports/...`, `$api/findings/...` добавить `-Headers $headers`; во всех `curl.exe` добавить `-H $authArg`.

Перед финальным `Write-Host "`nГотово..."` добавить:

```powershell
# --- 7. Автозакрытие (повторный скан без одной находки) ---
Write-Host "`n== Автозакрытие (semgrep-rescan: одна находка исчезла) ==" -ForegroundColor Cyan
$re = curl.exe -s -X POST "$api/entities/$eid/imports" -H $authArg `
    -F "file=@$(Join-Path $samples 'semgrep-rescan.sarif')" | ConvertFrom-Json
$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Seconds 2
    $imp = Invoke-RestMethod "$api/imports/$($re.id)" -Headers $headers
} while ($imp.status -in @("pending", "processing") -and (Get-Date) -lt $deadline)

if ($imp.stats.closed -eq 1) {
    Ok "автозакрытие работает: closed=1"
} else {
    Fail "ожидали closed=1, получили: $($imp.stats | ConvertTo-Json -Compress)"
}
```

Пересохранить в UTF-8 с BOM (Write/Edit сохраняют без BOM):

Run (PowerShell): `$p = "scripts\smoke-test.ps1"; $c = [IO.File]::ReadAllText($p); [IO.File]::WriteAllText($p, $c, [Text.UTF8Encoding]::new($true))`

- [ ] **Step 7: End-to-end прогон**

Run: `powershell -File scripts\dev.ps1` (поднимает инфраструктуру, API и воркер), затем `cd backend && .venv\Scripts\python -m alembic upgrade head` и `.venv\Scripts\python -m app.cli seed-roles`, затем `powershell -File scripts\smoke-test.ps1`
Expected: все шаги ✓, в конце «автозакрытие работает: closed=1».

- [ ] **Step 8: Проверка в браузере**

Открыть http://localhost:5173 → «Находки»: колонка «№» с `SV-N`, в фильтре статусов есть «В работе». «Роли» → в матрице есть столбец «Одобрение», у «Инженер ИБ» он отмечен для «Находки»; есть встроенная роль «Разработчик».

- [ ] **Step 9: Обновить `CLAUDE.md`**

В раздел «Пайплайн импорта» добавить абзац:

```markdown
**Процесс (этап 1, спека docs/superpowers/specs/2026-09-19-triage-workflow-and-ai-design.md):** логика импорта — `app/services/import_processing.py` (`apply_import`), воркер только скачивает и вызывает её. Импорт принимает `branch`, `commit_sha`, `pipeline_url`, `scan_scope`, `close_missing` (по умолчанию true), `confirm_empty`; ветка/коммит также берутся из SARIF `versionControlProvenance`. У актива `default_branch` (наследуется вниз, `app/services/entity_tree.py`) — импорт другой ветки отклоняется. **Автозакрытие**: открытые находки объёма `(актив, сканер, scan_scope)`, которых нет в новом отчёте, → `fixed` (пустой отчёт закрывает только с `confirm_empty`). История — `finding_events` (`app/services/events.py`, `GET /findings/{id}/events`). Номера `findings.number` → `SV-N` (`GET /findings/by-number/{n}`). Статус `in_progress`; `PATCH /findings/{id}` принимает JSON `{status, reason}` и только new/triaged/confirmed/in_progress. «Ложное»/«риск» — `decision_requests` (`POST /findings/{id}/decisions`, `POST /decisions/{id}/approve|reject`): разработчик запрашивает, право `finding:approve` одобряет (у кого оно есть — применяется сразу). Риск принимается со сроком; ARQ cron `expire_risks` (03:00) переоткрывает истёкшие. Встроенная роль «Разработчик».
```

В раздел «Конвенции» добавить: «Тесты: `docker compose up -d postgres`, затем `cd backend && .venv\Scripts\python -m pytest` (БД `secretvuln_test` создаётся и мигрируется автоматически).»

- [ ] **Step 10: Commit**

```bash
git add frontend scripts CLAUDE.md
git commit -m "feat: in-progress status and SV numbers in UI, smoke test covers auth and auto-close"
```
