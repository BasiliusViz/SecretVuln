# Этап 2 «Владельцы и окна» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** У каждой уязвимости появляется команда-владелец (правила по путям → владелец проекта), CI адресует проекты путём и создаёт их сам, настройки проекта живут в `.secretvuln.yml` с правкой из админки, а разработчик и AppSec получают свои экраны: окно уязвимости, очередь AppSec, «Мои уязвимости», настройки проекта.

**Architecture:** Бэкенд: хранилище файлов за интерфейсом `app/services/storage.py` (диск/S3); адрес узла — `entities.slug` + `entities.path_cache` (`app/services/entity_paths.py`); наследуемые настройки и их источник — `app/services/entity_settings.py`; файл настроек — `app/services/config_file.py`; назначение владельца — `app/services/ownership.py`, вызывается из `apply_import`; ссылки на код — `app/services/code_links.py`. Фронтенд: четыре новые страницы поверх общего `apiJson` и типов в `src/api/`.

**Tech Stack:** Python 3.14 (venv `backend/.venv`), FastAPI, SQLAlchemy 2.0 async + asyncpg, Alembic (psycopg), ARQ, Casbin, PyYAML, pytest + pytest-asyncio + httpx; фронтенд React 19 + TypeScript + react-router 7 + react-i18next.

**Spec:** `docs/superpowers/specs/2026-09-24-stage2-owners-and-screens.md` (опирается на `docs/superpowers/specs/2026-09-19-triage-workflow-and-ai-design.md`, разделы 5, 9, 10)

## Global Constraints

- Коммиты — только в ветке `feature/stage2-owners-and-screens` (создать перед Task 1: `git checkout -b feature/stage2-owners-and-screens`).
- Все env-переменные с префиксом `SV_`; API под `/api/v1`.
- Модели: UUID PK (`UUIDPKMixin`), `TimestampMixin`, enum'ы — `str, enum.Enum` + PG native enum. Новые модели импортировать в `app/models/__init__.py`.
- Миграции пишутся вручную, нумерация продолжается: `0010`, `0011`, `0012`. Запуск: `cd backend && .venv\Scripts\python -m alembic upgrade head`.
- Тесты: `docker compose up -d postgres`, затем `cd backend && .venv\Scripts\python -m pytest`. Перед каждым коммитом весь набор зелёный (на старте этапа — 45 тестов).
- Весь текст UI — на русском через `t()` в `frontend/src/i18n/ru.json`; сообщения API для пользователя — на русском.
- Термины UI: Entity → «Проект», Finding → «Уязвимость», группа пользователей → «Команда», нет команды → «Без владельца», `.secretvuln.yml` → «Файл настроек».
- **Кодировка:** все файлы — UTF-8. После правки `.tsx`/`.json` проверять, что нет «кракозябр»: `git diff | grep -E "вЂ|в–|вњ|В·"` должен быть пуст (в этапе UI-тем так сломались символы `—`, `▸`, `✕`). `.ps1` — UTF-8 **с BOM**.
- Фронтенд проверяется `cd frontend && npx tsc --noEmit -p .` и в браузере (`preview_start` с именем `frontend`; бэкенд и воркер запущены). Пользователи: `admin@secretvuln.local` / `Admin12345!`, `alice@secretvuln.local` и `bob@secretvuln.local` / `Passw0rd!`.
- Права остаются глобальными (Casbin без доменов). «Мои уязвимости» — фильтр, а не ограничение доступа.
- Уточнение к спеке: применение файла настроек при импорте требует права `entity:write` (как и автосоздание) — иначе 403. Иначе любой с правом импорта мог бы переписать владельцев.
- `PUT /entities/by-path` меняет только структуру (имя, описание). Настройки (ветка, владелец, репозиторий, правила) — через файл или `PATCH /entities/{id}/settings`.

## Карта файлов

| Файл | Что делает |
|---|---|
| `backend/app/services/storage.py` (новый) | `save_sarif`, `load_sarif`, `check_storage`: диск или S3 |
| `backend/app/services/s3.py` | Низкоуровневый S3: `put_object`, `get_object`, `bucket_available` |
| `backend/app/services/entity_paths.py` (новый) | `slugify`, `split_path`, `unique_slug`, `build_path`, `refresh_path`, `ensure_path`, `subtree_ids` |
| `backend/app/services/entity_settings.py` (новый) | `normalize_repo_url`, `lineage`, `effective_settings`, `find_repo_owner`, `PIN_KEYS`, `FIELD_PIN` |
| `backend/app/services/config_file.py` (новый) | `ProjectConfig`, `parse_config`, `apply_config`, `apply_stored_config`, `export_config` |
| `backend/app/services/ownership.py` (новый) | `compile_glob`, `path_matches`, `OwnerResolver`, `build_resolver`, `reassign_entity` |
| `backend/app/services/code_links.py` (новый) | `guess_repo_type`, `build_code_url` |
| `backend/app/models/ownership_rule.py` (новый) | `OwnershipRule`, `RuleSource` |
| `backend/app/api/entity_settings.py` (новый) | Настройки проекта, правила, закрепление, выгрузка файла, переназначение |
| `backend/app/schemas/entity_settings.py` (новый) | Схемы настроек |
| `backend/app/api/entities.py`, `backend/app/schemas/entity.py` | slug/путь, `by-path` |
| `backend/app/api/imports.py`, `backend/app/schemas/import_.py` | `POST /imports`, файл настроек |
| `backend/app/api/findings.py`, `backend/app/schemas/finding.py` | Владелец, карточка, фильтры, комментарии, помощь, массовые действия |
| `backend/app/services/import_processing.py`, `backend/app/services/sarif/parser.py` | Назначение при импорте, `help`, репозиторий из SARIF |
| `backend/migrations/versions/0010…0012` | Схема |
| `frontend/src/api/json.ts`, `frontend/src/api/types.ts`, `frontend/src/components/Modal.tsx` (новые) | Общий клиент, типы, модальное окно |
| `frontend/src/pages/FindingWindow.tsx`, `Inbox.tsx`, `MyVulns.tsx`, `ProjectSettings.tsx` (новые) | Экраны |
| `frontend/src/pages/Findings.tsx`, `Assets.tsx`, `components/Layout.tsx`, `App.tsx`, `auth/AuthContext.tsx`, `i18n/ru.json` | Доработки |
| `docker-compose.yml`, `scripts/dev.ps1`, `scripts/smoke-test.ps1`, `backend/.env.example`, `.gitignore`, `CLAUDE.md`, `frontend/DESIGN.md` | Инфраструктура и документация |

---

### Task 1: Хранилище файлов — диск по умолчанию, S3 настройкой

**Files:**
- Create: `backend/app/services/storage.py`, `backend/migrations/versions/0010_storage_key.py`, `backend/tests/test_storage.py`
- Modify: `backend/app/services/s3.py`, `backend/app/core/config.py`, `backend/app/models/import_.py`, `backend/app/api/imports.py`, `backend/app/worker.py`, `backend/app/main.py`, `backend/tests/conftest.py`, `backend/tests/factories.py`, `docker-compose.yml`, `scripts/dev.ps1`, `backend/.env.example`, `.gitignore`

**Interfaces:**
- Produces: `save_sarif(content: bytes, filename: str) -> str` (ключ `imports/<uuid>/<имя>`), `load_sarif(key: str) -> bytes`, `check_storage() -> bool`; колонка и атрибут `Import.storage_key`; настройки `storage_backend: str = "local"`, `storage_path: str = "./data/sarif"`.

- [ ] **Step 1: Ветка**

```bash
git checkout -b feature/stage2-owners-and-screens
```

- [ ] **Step 2: Написать падающие тесты `backend/tests/test_storage.py`**

```python
"""Хранилище SARIF-файлов: диск по умолчанию, защита от выхода из папки."""

import pytest

from app.core.config import Settings, get_settings
from app.services import storage


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    return tmp_path


def test_default_backend_is_local():
    assert Settings().storage_backend == "local"


def test_save_and_load_roundtrip(local_storage):
    key = storage.save_sarif(b'{"runs": []}', "semgrep.sarif")
    assert key.startswith("imports/")
    assert key.endswith("/semgrep.sarif")
    assert (local_storage / key).is_file()
    assert storage.load_sarif(key) == b'{"runs": []}'


def test_filename_is_sanitized(local_storage):
    key = storage.save_sarif(b"x", "../../etc/passwd")
    assert ".." not in key
    assert key.endswith("/passwd")


def test_load_rejects_path_traversal(local_storage):
    with pytest.raises(ValueError):
        storage.load_sarif("../outside.sarif")


def test_check_storage_local(local_storage):
    assert storage.check_storage() is True


async def test_health_reports_storage(client, local_storage):
    r = await client.get("/api/v1/health")
    body = r.json()
    assert body["storage"] == "up"
    assert body["storage_backend"] == "local"
```

- [ ] **Step 3: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_storage.py -v`
Expected: FAIL — `ImportError: cannot import name 'storage'`.

- [ ] **Step 4: Настройки в `backend/app/core/config.py`**

Перед блоком `# S3 / MinIO` добавить:

```python
    # Хранилище загруженных SARIF: local (папка на диске) или s3 (MinIO/S3, настройки ниже)
    storage_backend: str = "local"
    storage_path: str = "./data/sarif"
```

- [ ] **Step 5: Переписать `backend/app/services/s3.py` полностью**

```python
"""Бэкенд S3/MinIO для хранилища SARIF (включается SV_STORAGE_BACKEND=s3)."""

from io import BytesIO

import boto3
from botocore.config import Config

from app.core.config import get_settings


def _client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )


def put_object(key: str, content: bytes) -> None:
    _client().put_object(
        Bucket=get_settings().s3_bucket, Key=key, Body=content, ContentType="application/json"
    )


def get_object(key: str) -> bytes:
    buf = BytesIO()
    _client().download_fileobj(get_settings().s3_bucket, key, buf)
    return buf.getvalue()


def bucket_available() -> bool:
    try:
        _client().head_bucket(Bucket=get_settings().s3_bucket)
        return True
    except Exception:
        return False
```

- [ ] **Step 6: Создать `backend/app/services/storage.py`**

```python
"""Хранилище загруженных SARIF-файлов: папка на диске (по умолчанию) или S3."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from app.core.config import get_settings

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _make_key(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name
    name = _UNSAFE.sub("_", name).strip("._")[:200] or "upload.sarif"
    return f"imports/{uuid.uuid4()}/{name}"


def _root() -> Path:
    return Path(get_settings().storage_path).resolve()


def _local_path(key: str) -> Path:
    root = _root()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Недопустимый ключ хранилища: {key}")
    return path


def _is_s3() -> bool:
    return get_settings().storage_backend == "s3"


def save_sarif(content: bytes, filename: str) -> str:
    key = _make_key(filename)
    if _is_s3():
        from app.services import s3

        s3.put_object(key, content)
    else:
        path = _local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return key


def load_sarif(key: str) -> bytes:
    if _is_s3():
        from app.services import s3

        return s3.get_object(key)
    return _local_path(key).read_bytes()


def check_storage() -> bool:
    if _is_s3():
        from app.services import s3

        return s3.bucket_available()
    try:
        root = _root()
        root.mkdir(parents=True, exist_ok=True)
        return os.access(root, os.W_OK)
    except OSError:
        return False
```

- [ ] **Step 7: Миграция `backend/migrations/versions/0010_storage_key.py`**

```python
"""imports.s3_key -> storage_key (file storage can be local disk or S3)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-24

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("imports", "s3_key", new_column_name="storage_key")


def downgrade() -> None:
    op.alter_column("imports", "storage_key", new_column_name="s3_key")
```

- [ ] **Step 8: Переименовать поле в коде**

`backend/app/models/import_.py`: строку `s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)` заменить на
```python
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
```
и в `ImportStatus.pending` комментарий `# file stored in S3, ARQ job enqueued` → `# file stored, ARQ job enqueued`.

`backend/app/api/imports.py`: импорт `from app.services.s3 import upload_sarif` → `from app.services.storage import save_sarif`; строки
```python
    s3_key = upload_sarif(content, filename)
```
и `s3_key=s3_key,` → 
```python
    storage_key = save_sarif(content, filename)
```
и `storage_key=storage_key,`.

`backend/app/worker.py`: импорт `from app.services.s3 import download_sarif` → `from app.services.storage import load_sarif`; `runs = parse_sarif(download_sarif(imp.s3_key))` → `runs = parse_sarif(load_sarif(imp.storage_key))`.

`backend/tests/conftest.py`: `"app.api.imports.upload_sarif"` → `"app.api.imports.save_sarif"`.

`backend/tests/factories.py`: `s3_key=kw.pop("s3_key", "test/t.sarif"),` → `storage_key=kw.pop("storage_key", "test/t.sarif"),`.

Проверить, что старое имя больше нигде не используется:
Run: `git grep -n "s3_key\|upload_sarif\|download_sarif" -- backend/app backend/tests`
Expected: пусто.

- [ ] **Step 9: Health в `backend/app/main.py`**

Добавить импорт `from app.services.storage import check_storage` и заменить `return {...}` в `health` на:

```python
    storage_ok = check_storage()
    return {
        "status": "ok" if db_ok and storage_ok else "degraded",
        "database": "up" if db_ok else "down",
        "storage": "up" if storage_ok else "down",
        "storage_backend": settings.storage_backend,
    }
```

- [ ] **Step 10: Инфраструктура**

`docker-compose.yml`, сервис `minio`: `image: minio/minio:latest` → `image: minio/minio:RELEASE.2025-07-23T15-54-02Z-cpuv1`, и сразу под строкой `image:` добавить `    profiles: ["s3"]`. В сервисе `minio-init` под строкой `image: minio/mc:latest` добавить `    profiles: ["s3"]`. Над сервисом `minio` добавить комментарий:
```yaml
  # MinIO нужен только при SV_STORAGE_BACKEND=s3: docker compose --profile s3 up -d
```

`scripts/dev.ps1` (сохранить UTF-8 с BOM): заголовок `[1/4] Docker (postgres/redis/minio)...` → `[1/4] Docker (postgres/redis/ldap)...`; строки
```powershell
docker compose up -d postgres redis minio
docker compose run --rm minio-init | Out-Null
```
заменить на
```powershell
docker compose up -d postgres redis ldap
```
В комментарии в шапке `docker (postgres/redis/minio)` → `docker (postgres/redis/ldap)`. Строку `Write-Host "  MinIO UI:  http://localhost:9001  (minioadmin / minioadmin)"` заменить на `Write-Host "  Файлы SARIF: backend\data\sarif (S3 — SV_STORAGE_BACKEND=s3 + docker compose --profile s3 up -d)"`.

`backend/.env.example`: перед строкой `# Порт 9002...` добавить
```
# Хранилище SARIF: local (папка) или s3
SV_STORAGE_BACKEND=local
SV_STORAGE_PATH=./data/sarif
# Для s3:
```

`.gitignore`: добавить строку `backend/data/`.

- [ ] **Step 11: Миграция и тесты**

Run: `cd backend && .venv\Scripts\python -m alembic upgrade head && .venv\Scripts\python -m pytest -q`
Expected: все тесты PASS (45 старых + 6 новых).

- [ ] **Step 12: Commit**

```bash
git add backend docker-compose.yml scripts/dev.ps1 .gitignore
git commit -m "feat: local disk SARIF storage by default, S3 optional"
```

---

### Task 2: Путь проекта (slug + path_cache) и адресация по пути

**Files:**
- Create: `backend/app/services/entity_paths.py`, `backend/migrations/versions/0011_entity_paths.py`, `backend/tests/test_entity_paths.py`
- Modify: `backend/app/models/entity.py`, `backend/app/schemas/entity.py`, `backend/app/api/entities.py`, `backend/app/api/findings.py`, `backend/tests/factories.py`

**Interfaces:**
- Produces: `Entity.slug: str`, `Entity.path_cache: str`; в `app/services/entity_paths.py`: `slugify(name: str) -> str`, `is_valid_slug(slug: str) -> bool`, `split_path(path: str) -> list[str]` (ValueError на плохой путь), `async unique_slug(db, parent_id, base, *, exclude_id=None) -> str`, `async build_path(db, parent_id, slug) -> str`, `async refresh_path(db, entity) -> None`, `async ensure_path(db, path, *, create: bool) -> tuple[Entity | None, list[Entity]]`, `subtree_ids(entity: Entity) -> Select`; `EntityRead.slug`, `EntityRead.path`; эндпоинты `GET/PUT /api/v1/entities/by-path/{path}`; параметр `include_descendants` у `GET /findings` и `GET /findings/stats`.

- [ ] **Step 1: Фабрика — `make_entity` в `backend/tests/factories.py`**

Добавить импорт `from app.services.entity_paths import slugify` и заменить функцию `make_entity` на:

```python
async def make_entity(
    db: AsyncSession, name: str = "svc", parent_id=None, **kw: Any
) -> Entity:
    slug = kw.pop("slug", slugify(name))
    path = slug
    if parent_id is not None:
        parent = await db.get(Entity, parent_id)
        path = f"{parent.path_cache}/{slug}"
    entity = Entity(name=name, parent_id=parent_id, slug=slug, path_cache=path, **kw)
    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    return entity
```

- [ ] **Step 2: Написать падающие тесты `backend/tests/test_entity_paths.py`**

```python
"""Адрес проекта: slug, полный путь, адресация и автосоздание по пути."""

import pytest

from app.services.entity_paths import slugify, split_path
from tests.factories import make_entity, make_finding


def test_slugify_transliterates_and_cleans():
    assert slugify("Платежи API") == "platezhi-api"
    assert slugify("  Backend__v2! ") == "backend__v2"
    assert slugify("!!!") == "project"


def test_split_path_validates():
    assert split_path("/fintech/payments/") == ["fintech", "payments"]
    with pytest.raises(ValueError):
        split_path("Fintech/Платежи")
    with pytest.raises(ValueError):
        split_path("a//b")
    with pytest.raises(ValueError):
        split_path("")


async def _create(client, headers, name, parent_id=None, **extra):
    body = {"name": name, "parent_id": parent_id, **extra}
    r = await client.post("/api/v1/entities", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_sets_slug_and_path(client, admin):
    _, h = admin
    root = await _create(client, h, "Финтех")
    assert root["slug"] == "fintech"
    assert root["path"] == "fintech"
    child = await _create(client, h, "Payments", root["id"])
    assert child["path"] == "fintech/payments"


async def test_rename_slug_and_move_recompute_subtree(client, admin):
    _, h = admin
    a = await _create(client, h, "a")
    b = await _create(client, h, "b", a["id"])
    c = await _create(client, h, "c", b["id"])
    x = await _create(client, h, "x")

    r = await client.patch(f"/api/v1/entities/{a['id']}", json={"slug": "alpha"}, headers=h)
    assert r.status_code == 200
    assert r.json()["path"] == "alpha"
    c_now = (await client.get(f"/api/v1/entities/{c['id']}", headers=h)).json()
    assert c_now["path"] == "alpha/b/c"

    r = await client.patch(f"/api/v1/entities/{b['id']}", json={"parent_id": x["id"]}, headers=h)
    assert r.status_code == 200
    c_now = (await client.get(f"/api/v1/entities/{c['id']}", headers=h)).json()
    assert c_now["path"] == "x/b/c"


async def test_invalid_slug_rejected(client, admin):
    _, h = admin
    a = await _create(client, h, "a")
    r = await client.patch(f"/api/v1/entities/{a['id']}", json={"slug": "Bad Slug"}, headers=h)
    assert r.status_code == 422


async def test_auto_slug_is_unique_among_siblings(client, admin):
    _, h = admin
    await _create(client, h, "a")
    second = await _create(client, h, "A")
    assert second["slug"] == "a-2"
    r = await client.patch(f"/api/v1/entities/{second['id']}", json={"slug": "a"}, headers=h)
    assert r.status_code == 409


async def test_put_by_path_creates_chain_and_is_idempotent(client, admin):
    _, h = admin
    r = await client.put("/api/v1/entities/by-path/fintech/payments/api", json={}, headers=h)
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["path"] == "fintech/payments/api"
    assert first["name"] == "api"

    r = await client.put("/api/v1/entities/by-path/fintech/payments/api", json={}, headers=h)
    assert r.json()["id"] == first["id"]
    all_entities = (await client.get("/api/v1/entities", headers=h)).json()
    assert len(all_entities) == 3


async def test_put_by_path_updates_name_keeps_path(client, admin):
    _, h = admin
    r = await client.put(
        "/api/v1/entities/by-path/svc",
        json={"name": "Сервис оплаты", "description": "d"},
        headers=h,
    )
    body = r.json()
    assert body["name"] == "Сервис оплаты"
    assert body["description"] == "d"
    assert body["path"] == "svc"


async def test_get_by_path(client, admin):
    _, h = admin
    await client.put("/api/v1/entities/by-path/team/app", json={}, headers=h)
    r = await client.get("/api/v1/entities/by-path/team/app", headers=h)
    assert r.status_code == 200
    assert r.json()["path"] == "team/app"
    r = await client.get("/api/v1/entities/by-path/nope/x", headers=h)
    assert r.status_code == 404
    r = await client.get("/api/v1/entities/by-path/Bad Path", headers=h)
    assert r.status_code == 422


async def test_put_by_path_requires_entity_write(client, developer):
    _, h = developer
    r = await client.put("/api/v1/entities/by-path/svc", json={}, headers=h)
    assert r.status_code == 403


async def test_findings_include_descendants(client, admin, db):
    _, h = admin
    parent = await make_entity(db, "p")
    child = await make_entity(db, "c", parent_id=parent.id)
    await make_finding(db, parent, "f1")
    await make_finding(db, child, "f2")

    r = await client.get(f"/api/v1/findings?entity_id={parent.id}", headers=h)
    assert len(r.json()) == 1
    r = await client.get(
        f"/api/v1/findings?entity_id={parent.id}&include_descendants=true", headers=h
    )
    assert len(r.json()) == 2
    r = await client.get(
        f"/api/v1/findings/stats?entity_id={parent.id}&include_descendants=true", headers=h
    )
    assert r.json()["total"] == 2
```

- [ ] **Step 3: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_entity_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.entity_paths'` (падает и импорт в factories — это ожидаемо до Step 4).

- [ ] **Step 4: Сервис `backend/app/services/entity_paths.py`**

```python
"""Адрес проекта: slug узла и полный путь вида fintech/payments/backend-api."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity

_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
})
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
MAX_SLUG = 100


def slugify(name: str) -> str:
    slug = name.strip().lower().translate(_TRANSLIT)
    slug = re.sub(r"[^a-z0-9._-]+", "-", slug).strip("-._")
    return slug[:MAX_SLUG].rstrip("-._") or "project"


def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug))


def split_path(path: str) -> list[str]:
    parts = path.strip().strip("/").split("/")
    if not all(is_valid_slug(p) for p in parts):
        raise ValueError(
            f"Некорректный путь проекта «{path}»: части пути — латиница в нижнем регистре, "
            "цифры, «.», «_», «-», разделитель «/»"
        )
    return parts


async def unique_slug(
    db: AsyncSession, parent_id: uuid.UUID | None, base: str, *, exclude_id: uuid.UUID | None = None
) -> str:
    slug, n = base, 2
    while True:
        q = select(Entity.id).where(
            Entity.parent_id.is_not_distinct_from(parent_id), Entity.slug == slug
        )
        if exclude_id is not None:
            q = q.where(Entity.id != exclude_id)
        if await db.scalar(q) is None:
            return slug
        suffix = f"-{n}"
        slug = f"{base[: MAX_SLUG - len(suffix)]}{suffix}"
        n += 1


async def build_path(db: AsyncSession, parent_id: uuid.UUID | None, slug: str) -> str:
    if parent_id is None:
        return slug
    parent = await db.get(Entity, parent_id)
    return f"{parent.path_cache}/{slug}"


async def refresh_path(db: AsyncSession, entity: Entity) -> None:
    """Пересчитать path_cache узла и всего поддерева (после смены slug или родителя)."""
    old = entity.path_cache
    new = await build_path(db, entity.parent_id, entity.slug)
    entity.path_cache = new
    await db.flush()
    if old and old != new:
        await db.execute(
            update(Entity)
            .where(func.starts_with(Entity.path_cache, old + "/"))
            .values(path_cache=func.concat(new, func.substr(Entity.path_cache, len(old) + 1)))
            .execution_options(synchronize_session=False)
        )


async def ensure_path(
    db: AsyncSession, path: str, *, create: bool
) -> tuple[Entity | None, list[Entity]]:
    """Найти узел по пути; при create=True создать недостающие узлы цепочки.

    Возвращает (узел или None, список созданных узлов). Не коммитит.
    """
    created: list[Entity] = []
    parent: Entity | None = None
    current = ""
    for slug in split_path(path):
        current = f"{current}/{slug}" if current else slug
        node = await db.scalar(select(Entity).where(Entity.path_cache == current))
        if node is None:
            if not create:
                return None, []
            node = Entity(
                name=slug,
                slug=slug,
                parent_id=parent.id if parent else None,
                path_cache=current,
                custom_fields={},
            )
            db.add(node)
            await db.flush()
            created.append(node)
        parent = node
    return parent, created


def subtree_ids(entity: Entity) -> Select:
    """id узла и всех его потомков — для фильтров «включая вложенные»."""
    return select(Entity.id).where(
        or_(Entity.id == entity.id, func.starts_with(Entity.path_cache, entity.path_cache + "/"))
    )
```

- [ ] **Step 5: Модель `backend/app/models/entity.py`**

Импорт `from sqlalchemy import ForeignKey, String, Text, UniqueConstraint` → `from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint`. В `__table_args__` после `UniqueConstraint(...)` добавить:

```python
        UniqueConstraint(
            "parent_id", "slug", name="uq_entities_parent_slug", postgresql_nulls_not_distinct=True
        ),
        Index(
            "ix_entities_path_cache", "path_cache", unique=True,
            postgresql_ops={"path_cache": "text_pattern_ops"},
        ),
```

После поля `name` добавить:

```python
    # Адресная часть узла: [a-z0-9._-], уникальна среди соседей
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    # Полный путь fintech/payments/api — пересчитывается при смене slug/родителя (entity_paths)
    path_cache: Mapped[str] = mapped_column(String(2048), nullable=False)
```

- [ ] **Step 6: Миграция `backend/migrations/versions/0011_entity_paths.py`**

```python
"""entity slug and materialized path

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-24

"""
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Копия slugify из app/services/entity_paths.py на момент миграции —
# миграции не импортируют код приложения, чтобы не меняться вместе с ним.
_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
})


def _slugify(name: str) -> str:
    slug = name.strip().lower().translate(_TRANSLIT)
    slug = re.sub(r"[^a-z0-9._-]+", "-", slug).strip("-._")
    return slug[:100].rstrip("-._") or "project"


def upgrade() -> None:
    op.add_column("entities", sa.Column("slug", sa.String(100), nullable=True))
    op.add_column("entities", sa.Column("path_cache", sa.String(2048), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, name, parent_id FROM entities")).all()
    children: dict = {}
    for id_, name, parent_id in rows:
        children.setdefault(parent_id, []).append((id_, name))

    stack: list[tuple[object, str]] = [(None, "")]
    while stack:
        parent_id, parent_path = stack.pop()
        used: set[str] = set()
        for id_, name in sorted(children.get(parent_id, []), key=lambda r: r[1]):
            base = _slugify(name)
            slug, n = base, 2
            while slug in used:
                slug = f"{base[:95]}-{n}"
                n += 1
            used.add(slug)
            path = f"{parent_path}/{slug}" if parent_path else slug
            conn.execute(
                sa.text("UPDATE entities SET slug = :s, path_cache = :p WHERE id = :id"),
                {"s": slug, "p": path, "id": id_},
            )
            stack.append((id_, path))

    op.alter_column("entities", "slug", nullable=False)
    op.alter_column("entities", "path_cache", nullable=False)
    op.execute(
        "ALTER TABLE entities ADD CONSTRAINT uq_entities_parent_slug "
        "UNIQUE NULLS NOT DISTINCT (parent_id, slug)"
    )
    op.create_index(
        "ix_entities_path_cache", "entities", ["path_cache"], unique=True,
        postgresql_ops={"path_cache": "text_pattern_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_entities_path_cache", table_name="entities")
    op.drop_constraint("uq_entities_parent_slug", "entities", type_="unique")
    op.drop_column("entities", "path_cache")
    op.drop_column("entities", "slug")
```

- [ ] **Step 7: Схемы `backend/app/schemas/entity.py`**

Импорт `from pydantic import BaseModel, ConfigDict, Field` → `from pydantic import AliasChoices, BaseModel, ConfigDict, Field`. В `EntityCreate` и `EntityUpdate` после `name` добавить:

```python
    slug: str | None = Field(default=None, max_length=100)
```

В `EntityRead` после `name: str` добавить:

```python
    slug: str
    path: str = Field(validation_alias=AliasChoices("path_cache", "path"))
```

В конец файла добавить:

```python
class EntityUpsert(BaseModel):
    """PUT /entities/by-path: только структура; настройки — через файл или /settings."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
```

- [ ] **Step 8: API `backend/app/api/entities.py`**

Импорты заменить на:

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db
from app.models import Entity
from app.schemas.entity import EntityCreate, EntityRead, EntityUpdate, EntityUpsert
from app.services.entity_paths import (
    build_path,
    ensure_path,
    is_valid_slug,
    refresh_path,
    slugify,
    unique_slug,
)
```

После `_check_parent` добавить:

```python
def _require_valid_slug(slug: str | None) -> None:
    if slug is None or not is_valid_slug(slug):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Адрес проекта (slug): латиница в нижнем регистре, цифры, «.», «_», «-», до 100 символов",
        )


CONFLICT = "На этом уровне уже есть проект с таким названием или адресом"
```

Тело `create_entity` заменить на:

```python
    if data.parent_id is not None:
        await _check_parent(db, data.parent_id)
    if data.slug is not None:
        _require_valid_slug(data.slug)
    entity = Entity(**data.model_dump(exclude={"slug"}))
    entity.slug = data.slug or await unique_slug(db, data.parent_id, slugify(data.name))
    entity.path_cache = await build_path(db, data.parent_id, entity.slug)
    db.add(entity)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, CONFLICT)
    await db.refresh(entity)
    return entity
```

Тело `update_entity` заменить на:

```python
    entity = await _get_or_404(entity_id, db)
    fields = data.model_dump(exclude_unset=True)
    if "slug" in fields:
        _require_valid_slug(fields["slug"])
    if fields.get("parent_id") is not None:
        await _check_parent(db, fields["parent_id"], child_id=entity_id)
    moved = "parent_id" in fields and fields["parent_id"] != entity.parent_id
    renamed = "slug" in fields and fields["slug"] != entity.slug
    for key, value in fields.items():
        setattr(entity, key, value)
    try:
        if moved or renamed:
            await refresh_path(db, entity)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, CONFLICT)
    await db.refresh(entity)
    return entity
```

Перед `@router.get("/{entity_id}", ...)` добавить:

```python
@router.get("/by-path/{path:path}", response_model=EntityRead)
async def get_entity_by_path(
    path: str,
    _: object = Depends(require_permission("entity", "read")),
    db: AsyncSession = Depends(get_db),
) -> Entity:
    try:
        entity, _created = await ensure_path(db, path, create=False)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Проект «{path}» не найден")
    return entity


@router.put("/by-path/{path:path}", response_model=EntityRead)
async def upsert_entity_by_path(
    path: str,
    data: EntityUpsert,
    _: object = Depends(require_permission("entity", "write")),
    db: AsyncSession = Depends(get_db),
) -> Entity:
    """Идемпотентно: создаёт недостающие узлы пути и обновляет имя/описание последнего."""
    try:
        entity, _created = await ensure_path(db, path, create=True)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(entity, key, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, CONFLICT)
    await db.refresh(entity)
    return entity
```

- [ ] **Step 9: `include_descendants` в `backend/app/api/findings.py`**

Импорты: `from app.models import Finding` → `from app.models import Entity, Finding`; добавить `from app.services.entity_paths import subtree_ids`. После `router = ...` добавить:

```python
async def _entity_filter(db: AsyncSession, entity_id: uuid.UUID, include_descendants: bool):
    """Условие на Finding.entity_id: сам проект или всё его поддерево."""
    if not include_descendants:
        return Finding.entity_id == entity_id
    entity = await db.get(Entity, entity_id)
    if entity is None:
        return Finding.entity_id == entity_id  # пустой результат
    return Finding.entity_id.in_(subtree_ids(entity))
```

В `list_findings` добавить параметр `include_descendants: bool = False,` после `entity_id`, и строку `q = q.where(Finding.entity_id == entity_id)` заменить на `q = q.where(await _entity_filter(db, entity_id, include_descendants))`.

В `findings_stats` добавить тот же параметр; тело заменить на:

```python
    scope = await _entity_filter(db, entity_id, include_descendants) if entity_id else None
    q = select(Finding.severity, func.count()).group_by(Finding.severity)
    q2 = select(Finding.status, func.count()).group_by(Finding.status)
    if scope is not None:
        q = q.where(scope)
        q2 = q2.where(scope)
    by_severity = {sev.value: cnt for sev, cnt in (await db.execute(q)).all()}
    by_status = {st.value: cnt for st, cnt in (await db.execute(q2)).all()}
    total = sum(by_severity.values())
    return {"total": total, "by_severity": by_severity, "by_status": by_status}
```

- [ ] **Step 10: Миграция и тесты**

Run: `cd backend && .venv\Scripts\python -m alembic upgrade head && .venv\Scripts\python -m pytest -q`
Expected: все PASS.

- [ ] **Step 11: Commit**

```bash
git add backend
git commit -m "feat: project slug and path, by-path lookup/upsert, subtree finding filters"
```

---

### Task 3: Настройки проекта, правила владения, поля владельца (схема + API настроек)

**Files:**
- Create: `backend/app/models/ownership_rule.py`, `backend/migrations/versions/0012_owners_and_settings.py`, `backend/app/services/entity_settings.py`, `backend/app/schemas/entity_settings.py`, `backend/app/api/entity_settings.py`, `backend/tests/test_entity_settings.py`
- Modify: `backend/app/models/entity.py`, `backend/app/models/finding.py`, `backend/app/models/finding_event.py`, `backend/app/models/import_.py`, `backend/app/models/__init__.py`, `backend/app/main.py`, `backend/tests/factories.py`

**Interfaces:**
- Consumes: `Entity.path_cache` (Task 2).
- Produces:
  - `RepoType` (`gitlab|github|gitea|bitbucket`) в `app/models/entity.py`; поля `Entity.owner_group_id`, `repo_url`, `repo_type`, `repo_path_prefix`, `pinned_fields: list[str]`, `config_file: dict | None`, `config_commit_sha`, `config_applied_at`.
  - `OwnershipRule(entity_id, pattern, group_id, position, source: RuleSource)`, `RuleSource` (`file|manual`), отношение `OwnershipRule.group` (selectin).
  - `Finding.assignee_group_id`, `assignee_user_id`, `assigned_manually: bool`, `help_requested_at`, `help_text`; отношения `Finding.assignee_group`, `Finding.assignee_user` (selectin).
  - `Import.repo_url`, `Import.config_warnings: list[str]`.
  - `FindingEventType.assigned`, `comment`, `help_requested`, `help_resolved`.
  - В `app/services/entity_settings.py`: `PIN_KEYS: tuple[str, ...]`, `FIELD_PIN: dict[str, str]`, `normalize_repo_url(url: str) -> str`, `async lineage(db, entity) -> list[Entity]` (узел → корень), `async effective_settings(db, entity) -> dict[str, dict]` (`{"value", "source", "inherited_from"}`), `async find_repo_owner(db, url, *, exclude_id) -> Entity | None`.
  - API: `GET/PATCH /api/v1/entities/{id}/settings`, `PUT /api/v1/entities/{id}/ownership-rules`; `async settings_read(db, entity, warnings=()) -> EntitySettingsRead` в `app/api/entity_settings.py`.
  - Фабрика `make_group(db, name) -> UserGroup`.

- [ ] **Step 1: Фабрика групп в `backend/tests/factories.py`**

Импорт `from app.models import Entity, Finding, Import` → `from app.models import Entity, Finding, GroupSource, Import, UserGroup`. В конец файла:

```python
async def make_group(db: AsyncSession, name: str = "team") -> UserGroup:
    group = UserGroup(name=name, source=GroupSource.manual)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group
```

- [ ] **Step 2: Написать падающие тесты `backend/tests/test_entity_settings.py`**

```python
"""Настройки проекта: значения, источники, наследование, закрепление, правила владения."""

from tests.factories import make_entity, make_group


async def test_settings_default_unset(client, admin, db):
    _, h = admin
    e = await make_entity(db, "svc")
    r = await client.get(f"/api/v1/entities/{e.id}/settings", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == "svc"
    assert body["fields"]["owner_group_id"] == {"value": None, "source": "unset", "inherited_from": None}
    assert body["ownership_rules"] == []
    assert body["pinned_fields"] == []


async def test_patch_pins_and_normalizes_repo(client, admin, db):
    _, h = admin
    e = await make_entity(db, "svc")
    g = await make_group(db, "payments")
    r = await client.patch(
        f"/api/v1/entities/{e.id}/settings",
        json={
            "owner_group_id": str(g.id),
            "repo_url": "https://GitLab.Corp/Team/App.git/",
            "repo_type": "gitlab",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fields"]["owner_group_id"]["value"] == str(g.id)
    assert body["fields"]["owner_group_id"]["source"] == "manual"
    assert body["fields"]["repo_url"]["value"] == "https://gitlab.corp/Team/App"
    assert set(body["pinned_fields"]) == {"owner_group_id", "repo"}


async def test_settings_are_inherited(client, admin, db):
    _, h = admin
    g = await make_group(db, "payments")
    parent = await make_entity(db, "fintech", owner_group_id=g.id, default_branch="main")
    child = await make_entity(db, "api", parent_id=parent.id)
    body = (await client.get(f"/api/v1/entities/{child.id}/settings", headers=h)).json()
    assert body["fields"]["owner_group_id"] == {
        "value": str(g.id), "source": "inherited", "inherited_from": "fintech",
    }
    assert body["fields"]["default_branch"]["value"] == "main"


async def test_repo_bound_to_one_project(client, admin, db):
    _, h = admin
    a = await make_entity(db, "a", repo_url="https://gitlab.corp/team/app")
    b = await make_entity(db, "b")
    r = await client.patch(
        f"/api/v1/entities/{b.id}/settings",
        json={"repo_url": "https://gitlab.corp/team/app.git"},
        headers=h,
    )
    assert r.status_code == 409
    assert "a" in r.json()["detail"]
    assert a.id  # a остаётся владельцем репозитория


async def test_unknown_group_rejected(client, admin, db):
    _, h = admin
    e = await make_entity(db, "svc")
    r = await client.patch(
        f"/api/v1/entities/{e.id}/settings",
        json={"owner_group_id": "00000000-0000-0000-0000-000000000000"},
        headers=h,
    )
    assert r.status_code == 422


async def test_ownership_rules_replace_and_inherit(client, admin, db):
    _, h = admin
    g1 = await make_group(db, "payments")
    g2 = await make_group(db, "identity")
    parent = await make_entity(db, "fintech")
    child = await make_entity(db, "api", parent_id=parent.id)
    r = await client.put(
        f"/api/v1/entities/{parent.id}/ownership-rules",
        json=[
            {"pattern": "app/payments/**", "group_id": str(g1.id)},
            {"pattern": "app/auth/**", "group_id": str(g2.id)},
        ],
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["pattern"] for x in body["ownership_rules"]] == ["app/payments/**", "app/auth/**"]
    assert body["ownership_rules"][0]["group_name"] == "payments"
    assert body["rules_source"] == "manual"
    assert "ownership_rules" in body["pinned_fields"]

    child_body = (await client.get(f"/api/v1/entities/{child.id}/settings", headers=h)).json()
    assert [x["entity_path"] for x in child_body["inherited_rules"]] == ["fintech", "fintech"]


async def test_settings_write_requires_permission(client, developer, db):
    _, h = developer
    e = await make_entity(db, "svc")
    r = await client.get(f"/api/v1/entities/{e.id}/settings", headers=h)
    assert r.status_code == 200
    r = await client.patch(f"/api/v1/entities/{e.id}/settings", json={}, headers=h)
    assert r.status_code == 403
```

- [ ] **Step 3: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_entity_settings.py -v`
Expected: FAIL — `TypeError: 'owner_group_id' is an invalid keyword argument for Entity` / 404 на `/settings`.

- [ ] **Step 4: Модель `backend/app/models/ownership_rule.py`**

```python
import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class RuleSource(str, enum.Enum):
    file = "file"      # пришло из .secretvuln.yml
    manual = "manual"  # задано в админке (список закреплён)


class OwnershipRule(Base, UUIDPKMixin, TimestampMixin):
    """Маска пути → команда. Действует на проект и его поддерево."""

    __tablename__ = "ownership_rules"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), index=True, nullable=False
    )
    pattern: Mapped[str] = mapped_column(String(512), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[RuleSource] = mapped_column(Enum(RuleSource, name="rule_source"), nullable=False)

    group = relationship("UserGroup", lazy="selectin")
```

- [ ] **Step 5: Поля моделей**

`backend/app/models/entity.py`: импорт `import uuid` дополнить `import enum` и `from datetime import datetime`; импорт sqlalchemy → `from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, text`; `from sqlalchemy.dialects.postgresql import JSONB, UUID` → `from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID`. Перед классом `Entity`:

```python
class RepoType(str, enum.Enum):
    gitlab = "gitlab"
    github = "github"
    gitea = "gitea"
    bitbucket = "bitbucket"
```

В `__table_args__` добавить:

```python
        Index(
            "uq_entities_repo_url", "repo_url", unique=True,
            postgresql_where=text("repo_url IS NOT NULL"),
        ),
```

После `default_branch` добавить:

```python
    # Наследуемые настройки (NULL — берётся у ближайшего предка), см. services/entity_settings.py
    owner_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_groups.id", ondelete="SET NULL")
    )
    repo_url: Mapped[str | None] = mapped_column(String(1024))
    repo_type: Mapped[RepoType | None] = mapped_column(Enum(RepoType, name="repo_type"))
    repo_path_prefix: Mapped[str | None] = mapped_column(String(512))
    # Поля, изменённые в админке: файл .secretvuln.yml их больше не перезаписывает
    pinned_fields: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, nullable=False)
    # Последний применённый .secretvuln.yml (нормализованный)
    config_file: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    config_commit_sha: Mapped[str | None] = mapped_column(String(64))
    config_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

`backend/app/models/finding.py`: импорт `from sqlalchemy ...` — добавить `Boolean`, `DateTime` (если их нет), `Text`; после `commit_sha` добавить:

```python
    # Владелец: команда (по правилам/владельцу проекта или вручную) и, необязательно, человек
    assignee_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_groups.id", ondelete="SET NULL"), index=True
    )
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # Назначено вручную — повторные импорты не переназначают по правилам
    assigned_manually: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # «Нужна помощь AppSec»: момент запроса, снимается ответом AppSec
    help_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Рекомендация сканера (SARIF rule.help)
    help_text: Mapped[str | None] = mapped_column(Text)
```

и рядом с остальными отношениями:

```python
    assignee_group = relationship("UserGroup", lazy="selectin")
    assignee_user = relationship("User", lazy="selectin")
```

(проверить, что `ForeignKey`, `UUID`, `relationship`, `datetime` уже импортированы в файле; добавить недостающие).

`backend/app/models/finding_event.py`: в `FindingEventType` после `request_decided` добавить:

```python
    assigned = "assigned"
    comment = "comment"
    help_requested = "help_requested"
    help_resolved = "help_resolved"
```

`backend/app/models/import_.py`: после `pipeline_url` добавить

```python
    # Репозиторий из SARIF versionControlProvenance (для ссылок на код)
    repo_url: Mapped[str | None] = mapped_column(String(1024))
```

а после `confirm_empty`:

```python
    # Предупреждения применения .secretvuln.yml (неизвестная группа и т. п.)
    config_warnings: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
```

`backend/app/models/__init__.py`: `from app.models.entity import Entity` → `from app.models.entity import Entity, RepoType`; добавить `from app.models.ownership_rule import OwnershipRule, RuleSource`; в `__all__` добавить `"RepoType"`, `"OwnershipRule"`, `"RuleSource"`.

- [ ] **Step 6: Миграция `backend/migrations/versions/0012_owners_and_settings.py`**

```python
"""owners, project settings with pinning, ownership rules, help requests

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-24

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    for value in ("assigned", "comment", "help_requested", "help_resolved"):
        op.execute(f"ALTER TYPE finding_event_type ADD VALUE IF NOT EXISTS '{value}'")

    repo_type = postgresql.ENUM("gitlab", "github", "gitea", "bitbucket", name="repo_type")
    repo_type.create(op.get_bind(), checkfirst=True)

    op.add_column("entities", sa.Column(
        "owner_group_id", UUID, sa.ForeignKey("user_groups.id", ondelete="SET NULL"), nullable=True,
    ))
    op.add_column("entities", sa.Column("repo_url", sa.String(1024), nullable=True))
    op.add_column("entities", sa.Column(
        "repo_type", postgresql.ENUM(name="repo_type", create_type=False), nullable=True,
    ))
    op.add_column("entities", sa.Column("repo_path_prefix", sa.String(512), nullable=True))
    op.add_column("entities", sa.Column(
        "pinned_fields", postgresql.ARRAY(sa.String(50)), nullable=False, server_default="{}",
    ))
    op.add_column("entities", sa.Column("config_file", postgresql.JSONB(), nullable=True))
    op.add_column("entities", sa.Column("config_commit_sha", sa.String(64), nullable=True))
    op.add_column("entities", sa.Column("config_applied_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_entities_repo_url", "entities", ["repo_url"], unique=True,
        postgresql_where=sa.text("repo_url IS NOT NULL"),
    )

    op.create_table(
        "ownership_rules",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("entity_id", UUID, sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pattern", sa.String(512), nullable=False),
        sa.Column("group_id", UUID, sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source", sa.Enum("file", "manual", name="rule_source"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ownership_rules_entity_id", "ownership_rules", ["entity_id"])

    op.add_column("findings", sa.Column(
        "assignee_group_id", UUID, sa.ForeignKey("user_groups.id", ondelete="SET NULL"), nullable=True,
    ))
    op.add_column("findings", sa.Column(
        "assignee_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    ))
    op.create_index("ix_findings_assignee_group_id", "findings", ["assignee_group_id"])
    op.create_index("ix_findings_assignee_user_id", "findings", ["assignee_user_id"])
    op.add_column("findings", sa.Column(
        "assigned_manually", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.add_column("findings", sa.Column("help_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("findings", sa.Column("help_text", sa.Text(), nullable=True))

    op.add_column("imports", sa.Column("repo_url", sa.String(1024), nullable=True))
    op.add_column("imports", sa.Column(
        "config_warnings", postgresql.JSONB(), nullable=False, server_default="[]",
    ))


def downgrade() -> None:
    op.drop_column("imports", "config_warnings")
    op.drop_column("imports", "repo_url")
    for col in ("help_text", "help_requested_at", "assigned_manually"):
        op.drop_column("findings", col)
    op.drop_index("ix_findings_assignee_user_id", table_name="findings")
    op.drop_index("ix_findings_assignee_group_id", table_name="findings")
    op.drop_column("findings", "assignee_user_id")
    op.drop_column("findings", "assignee_group_id")
    op.drop_index("ix_ownership_rules_entity_id", table_name="ownership_rules")
    op.drop_table("ownership_rules")
    sa.Enum(name="rule_source").drop(op.get_bind(), checkfirst=True)
    op.drop_index("uq_entities_repo_url", table_name="entities")
    for col in (
        "config_applied_at", "config_commit_sha", "config_file", "pinned_fields",
        "repo_path_prefix", "repo_type", "repo_url", "owner_group_id",
    ):
        op.drop_column("entities", col)
    sa.Enum(name="repo_type").drop(op.get_bind(), checkfirst=True)
    # значения finding_event_type в PostgreSQL удалить нельзя — остаются
```

- [ ] **Step 7: Сервис `backend/app/services/entity_settings.py`**

```python
"""Наследуемые настройки проекта и их источник (файл / вручную / унаследовано)."""

from __future__ import annotations

import enum
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity

# Ключи закрепления: правка в админке закрепляет ключ, файл его больше не трогает
PIN_KEYS: tuple[str, ...] = ("default_branch", "owner_group_id", "repo", "ownership_rules")
# Наследуемое поле → ключ закрепления (поля репозитория закрепляются вместе)
FIELD_PIN: dict[str, str] = {
    "default_branch": "default_branch",
    "owner_group_id": "owner_group_id",
    "repo_url": "repo",
    "repo_type": "repo",
    "repo_path_prefix": "repo",
}


def normalize_repo_url(url: str) -> str:
    """https://GitLab.corp/Team/App.git/ → https://gitlab.corp/Team/App"""
    value = url.strip().rstrip("/")
    if value.endswith(".git"):
        value = value[:-4]
    parts = urlsplit(value)
    if parts.scheme and parts.netloc:
        value = urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", "")
        )
    return value


async def lineage(db: AsyncSession, entity: Entity) -> list[Entity]:
    """Узел и его предки: [узел, родитель, …, корень]."""
    chain = [entity]
    while chain[-1].parent_id is not None:
        chain.append(await db.get(Entity, chain[-1].parent_id))
    return chain


def own_source(entity: Entity, pin_key: str) -> str:
    if pin_key in entity.pinned_fields or entity.config_file is None:
        return "manual"
    return "file"


async def effective_settings(db: AsyncSession, entity: Entity) -> dict[str, dict[str, Any]]:
    chain = await lineage(db, entity)
    result: dict[str, dict[str, Any]] = {}
    for field, pin_key in FIELD_PIN.items():
        result[field] = {"value": None, "source": "unset", "inherited_from": None}
        for node in chain:
            value = getattr(node, field)
            if value is None:
                continue
            if isinstance(value, enum.Enum):
                value = value.value
            if node is entity:
                result[field] = {"value": value, "source": own_source(node, pin_key), "inherited_from": None}
            else:
                result[field] = {"value": value, "source": "inherited", "inherited_from": node.path_cache}
            break
    return result


async def find_repo_owner(
    db: AsyncSession, url: str, *, exclude_id: uuid.UUID | None = None
) -> Entity | None:
    q = select(Entity).where(Entity.repo_url == url)
    if exclude_id is not None:
        q = q.where(Entity.id != exclude_id)
    return await db.scalar(q)
```

- [ ] **Step 8: Схемы `backend/app/schemas/entity_settings.py`**

```python
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.entity import RepoType


class SettingValue(BaseModel):
    value: Any
    source: Literal["manual", "file", "inherited", "unset"]
    inherited_from: str | None


class RuleRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    pattern: str
    group_id: uuid.UUID
    group_name: str
    position: int
    source: str


class InheritedRule(BaseModel):
    entity_path: str
    pattern: str
    group_id: uuid.UUID
    group_name: str


class EntitySettingsRead(BaseModel):
    entity_id: uuid.UUID
    path: str
    fields: dict[str, SettingValue]
    ownership_rules: list[RuleRead]
    rules_source: Literal["manual", "file"]
    inherited_rules: list[InheritedRule]
    pinned_fields: list[str]
    has_config_file: bool
    config_commit_sha: str | None
    config_applied_at: datetime | None
    warnings: list[str] = []


class EntitySettingsUpdate(BaseModel):
    default_branch: str | None = Field(default=None, max_length=255)
    owner_group_id: uuid.UUID | None = None
    repo_url: str | None = Field(default=None, max_length=1024)
    repo_type: RepoType | None = None
    repo_path_prefix: str | None = Field(default=None, max_length=512)


class RuleIn(BaseModel):
    pattern: str = Field(min_length=1, max_length=512)
    group_id: uuid.UUID


class UnpinRequest(BaseModel):
    field: Literal["default_branch", "owner_group_id", "repo", "ownership_rules"]
```

- [ ] **Step 9: Роутер `backend/app/api/entity_settings.py`**

```python
"""Настройки проекта: чтение с источниками, правка (закрепляет поле), правила владения."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db
from app.models import Entity, OwnershipRule, RuleSource, UserGroup
from app.schemas.entity_settings import (
    EntitySettingsRead,
    EntitySettingsUpdate,
    InheritedRule,
    RuleIn,
    RuleRead,
)
from app.services.entity_settings import (
    FIELD_PIN,
    effective_settings,
    find_repo_owner,
    lineage,
    normalize_repo_url,
    own_source,
)

router = APIRouter(prefix="/api/v1/entities", tags=["entity-settings"])


async def _entity_or_404(db: AsyncSession, entity_id: uuid.UUID) -> Entity:
    entity = await db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    return entity


async def _rules(db: AsyncSession, entity_id: uuid.UUID) -> list[OwnershipRule]:
    result = await db.scalars(
        select(OwnershipRule)
        .where(OwnershipRule.entity_id == entity_id)
        .order_by(OwnershipRule.position)
    )
    return list(result)


async def settings_read(
    db: AsyncSession, entity: Entity, warnings: Sequence[str] = ()
) -> EntitySettingsRead:
    own = await _rules(db, entity.id)
    inherited: list[InheritedRule] = []
    for node in (await lineage(db, entity))[1:]:
        for rule in await _rules(db, node.id):
            inherited.append(InheritedRule(
                entity_path=node.path_cache, pattern=rule.pattern,
                group_id=rule.group_id, group_name=rule.group.name,
            ))
    return EntitySettingsRead(
        entity_id=entity.id,
        path=entity.path_cache,
        fields=await effective_settings(db, entity),
        ownership_rules=[
            RuleRead(
                id=r.id, pattern=r.pattern, group_id=r.group_id, group_name=r.group.name,
                position=r.position, source=r.source.value,
            )
            for r in own
        ],
        rules_source=own_source(entity, "ownership_rules"),
        inherited_rules=inherited,
        pinned_fields=list(entity.pinned_fields),
        has_config_file=entity.config_file is not None,
        config_commit_sha=entity.config_commit_sha,
        config_applied_at=entity.config_applied_at,
        warnings=list(warnings),
    )


def _pin(entity: Entity, *keys: str) -> None:
    entity.pinned_fields = sorted(set(entity.pinned_fields) | set(keys))


@router.get("/{entity_id}/settings", response_model=EntitySettingsRead)
async def get_settings_(
    entity_id: uuid.UUID,
    _: object = Depends(require_permission("entity", "read")),
    db: AsyncSession = Depends(get_db),
) -> EntitySettingsRead:
    return await settings_read(db, await _entity_or_404(db, entity_id))


@router.patch("/{entity_id}/settings", response_model=EntitySettingsRead)
async def update_settings(
    entity_id: uuid.UUID,
    data: EntitySettingsUpdate,
    _: object = Depends(require_permission("entity", "write")),
    db: AsyncSession = Depends(get_db),
) -> EntitySettingsRead:
    entity = await _entity_or_404(db, entity_id)
    fields = data.model_dump(exclude_unset=True)

    group_id = fields.get("owner_group_id")
    if group_id is not None and await db.get(UserGroup, group_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Команда не найдена")
    for key in ("default_branch", "repo_url", "repo_path_prefix"):
        if key in fields and isinstance(fields[key], str):
            fields[key] = fields[key].strip() or None
    if fields.get("repo_url"):
        fields["repo_url"] = normalize_repo_url(fields["repo_url"])
        other = await find_repo_owner(db, fields["repo_url"], exclude_id=entity.id)
        if other is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Репозиторий уже привязан к проекту {other.path_cache}",
            )

    for key, value in fields.items():
        setattr(entity, key, value)
    _pin(entity, *(FIELD_PIN[key] for key in fields))
    await db.commit()
    return await settings_read(db, entity)


@router.put("/{entity_id}/ownership-rules", response_model=EntitySettingsRead)
async def replace_rules(
    entity_id: uuid.UUID,
    rules: list[RuleIn] = Body(..., max_length=200),
    _: object = Depends(require_permission("entity", "write")),
    db: AsyncSession = Depends(get_db),
) -> EntitySettingsRead:
    entity = await _entity_or_404(db, entity_id)
    for rule in rules:
        if await db.get(UserGroup, rule.group_id) is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"Команда для правила «{rule.pattern}» не найдена"
            )
    await db.execute(delete(OwnershipRule).where(OwnershipRule.entity_id == entity.id))
    for position, rule in enumerate(rules):
        db.add(OwnershipRule(
            entity_id=entity.id, pattern=rule.pattern.strip(), group_id=rule.group_id,
            position=position, source=RuleSource.manual,
        ))
    _pin(entity, "ownership_rules")
    await db.commit()
    return await settings_read(db, entity)
```

- [ ] **Step 10: Подключить роутер в `backend/app/main.py`**

Добавить `from app.api.entity_settings import router as entity_settings_router` и `app.include_router(entity_settings_router)` после `app.include_router(entities_router)`.

- [ ] **Step 11: Миграция и тесты**

Run: `cd backend && .venv\Scripts\python -m alembic upgrade head && .venv\Scripts\python -m pytest -q`
Expected: все PASS.

- [ ] **Step 12: Commit**

```bash
git add backend
git commit -m "feat: project settings with source and pinning, ownership rules, owner fields"
```

---

### Task 4: Файл `.secretvuln.yml` и единая загрузка `POST /imports` с автосозданием

**Files:**
- Create: `backend/app/services/config_file.py`, `backend/tests/test_config_file.py`, `backend/tests/test_import_by_path.py`
- Modify: `backend/pyproject.toml`, `backend/app/api/imports.py`, `backend/app/schemas/import_.py`, `backend/app/api/entity_settings.py`

**Interfaces:**
- Consumes: `ensure_path` (Task 2); `normalize_repo_url`, `find_repo_owner`, `settings_read` (Task 3); `save_sarif` (Task 1).
- Produces: в `app/services/config_file.py`: `ProjectConfig`, `ConfigError`, `parse_config(content: bytes) -> ProjectConfig`, `async apply_config(db, entity, config, *, commit_sha=None) -> list[str]`, `async apply_stored_config(db, entity, *, only: set[str] | None = None) -> list[str]`, `async export_config(db, entity) -> str`; эндпоинты `POST /api/v1/imports`, `POST /api/v1/entities/{id}/settings/unpin`, `GET /api/v1/entities/{id}/config.yml`; схема `ImportCreated` (`ImportRead` + `entity_path`, `created_entities`), `ImportRead.config_warnings`, `ImportRead.repo_url`.

- [ ] **Step 1: Зависимость**

В `backend/pyproject.toml` в `dependencies` после `"pyjwt>=2.8",` добавить `"pyyaml>=6.0",`.
Run: `cd backend && .venv\Scripts\python -m pip install "pyyaml>=6.0"`

- [ ] **Step 2: Падающие тесты `backend/tests/test_config_file.py`**

```python
"""Файл настроек .secretvuln.yml: разбор, применение, закрепление, выгрузка."""

import pytest
from sqlalchemy import select

from app.models import OwnershipRule
from app.services.config_file import ConfigError, apply_config, export_config, parse_config
from tests.factories import make_entity, make_group

GOOD = b"""
version: 1
default_branch: main
owner: payments
repo:
  url: https://gitlab.corp/fintech/payments.git
  type: gitlab
  path_prefix: services/api
ownership:
  - path: "app/payments/**"
    owner: payments
  - path: "app/auth/**"
    owner: identity
"""


def test_parse_valid():
    cfg = parse_config(GOOD)
    assert cfg.default_branch == "main"
    assert cfg.repo.type.value == "gitlab"
    assert [o.path for o in cfg.ownership] == ["app/payments/**", "app/auth/**"]


@pytest.mark.parametrize("content", [
    b"version: 1\nowner: [unclosed",
    b"- just a list",
    b"version: 2",
    b"version: 1\nunknown_key: 1",
    b"version: 1\nrepo:\n  type: svn",
])
def test_parse_invalid(content):
    with pytest.raises(ConfigError):
        parse_config(content)


async def test_apply_sets_fields_and_rules(db):
    payments = await make_group(db, "payments")
    e = await make_entity(db, "svc")
    warnings = await apply_config(db, e, parse_config(GOOD), commit_sha="abc")
    await db.commit()

    assert e.default_branch == "main"
    assert e.owner_group_id == payments.id
    assert e.repo_url == "https://gitlab.corp/fintech/payments"
    assert e.repo_path_prefix == "services/api"
    assert e.config_commit_sha == "abc"
    rules = list(await db.scalars(select(OwnershipRule).where(OwnershipRule.entity_id == e.id)))
    assert [r.pattern for r in rules] == ["app/payments/**"]  # identity нет
    assert warnings == [
        "ownership: группа «identity» не найдена — правило «app/auth/**» пропущено"
    ]


async def test_pinned_fields_are_kept(db):
    await make_group(db, "payments")
    manual = await make_group(db, "manual-team")
    e = await make_entity(db, "svc", owner_group_id=manual.id, pinned_fields=["owner_group_id"])
    await apply_config(db, e, parse_config(GOOD))
    await db.commit()
    assert e.owner_group_id == manual.id
    assert e.default_branch == "main"


async def test_unpin_restores_file_value(client, admin, db):
    _, h = admin
    payments = await make_group(db, "payments")
    manual = await make_group(db, "manual-team")
    e = await make_entity(db, "svc")
    await apply_config(db, e, parse_config(GOOD))
    await db.commit()

    r = await client.patch(
        f"/api/v1/entities/{e.id}/settings", json={"owner_group_id": str(manual.id)}, headers=h
    )
    assert r.json()["fields"]["owner_group_id"]["source"] == "manual"

    r = await client.post(
        f"/api/v1/entities/{e.id}/settings/unpin", json={"field": "owner_group_id"}, headers=h
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fields"]["owner_group_id"] == {
        "value": str(payments.id), "source": "file", "inherited_from": None,
    }
    assert "owner_group_id" not in body["pinned_fields"]


async def test_export_roundtrip(client, admin, db):
    _, h = admin
    await make_group(db, "payments")
    e = await make_entity(db, "svc")
    await apply_config(db, e, parse_config(GOOD))
    await db.commit()

    text = await export_config(db, e)
    cfg = parse_config(text.encode())
    assert cfg.owner == "payments"
    assert cfg.repo.url == "https://gitlab.corp/fintech/payments"

    r = await client.get(f"/api/v1/entities/{e.id}/config.yml", headers=h)
    assert r.status_code == 200
    assert "owner: payments" in r.text
    assert ".secretvuln.yml" in r.headers["content-disposition"]
```

- [ ] **Step 3: Падающие тесты `backend/tests/test_import_by_path.py`**

```python
"""POST /imports: адрес проекта путём, автосоздание, файл настроек."""

from sqlalchemy import func, select

from app.authz.enforcer import set_role_permissions
from app.models import Import
from tests.factories import make_entity, make_group, make_sarif

SARIF = make_sarif("Semgrep", [{"fp": "a"}])
CONFIG = b"version: 1\ndefault_branch: main\nowner: payments\n"


def _files(config: bytes | None = None):
    files = {"file": ("s.sarif", SARIF, "application/json")}
    if config is not None:
        files["config"] = (".secretvuln.yml", config, "application/x-yaml")
    return files


async def test_auto_create_by_path(client, admin):
    _, h = admin
    r = await client.post(
        "/api/v1/imports",
        data={"project_path": "fintech/payments/api", "auto_create": "true"},
        files=_files(), headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["entity_path"] == "fintech/payments/api"
    assert [e["path"] for e in body["created_entities"]] == [
        "fintech", "fintech/payments", "fintech/payments/api",
    ]
    assert client.enqueued == [body["id"]]

    r = await client.post(
        "/api/v1/imports",
        data={"project_path": "fintech/payments/api", "auto_create": "true"},
        files=_files(), headers=h,
    )
    assert r.json()["created_entities"] == []
    assert r.json()["entity_id"] == body["entity_id"]


async def test_missing_path_without_auto_create_404(client, admin):
    _, h = admin
    r = await client.post(
        "/api/v1/imports", data={"project_path": "nope/x"}, files=_files(), headers=h
    )
    assert r.status_code == 404
    assert "auto_create" in r.json()["detail"]


async def test_entity_id_or_path_exactly_one(client, admin, db):
    _, h = admin
    e = await make_entity(db, "svc")
    r = await client.post(
        "/api/v1/imports",
        data={"project_path": "svc", "entity_id": str(e.id)},
        files=_files(), headers=h,
    )
    assert r.status_code == 422
    r = await client.post("/api/v1/imports", files=_files(), headers=h)
    assert r.status_code == 422


async def test_ci_role_without_entity_write(client, make_user, db):
    set_role_permissions("CI", [("import", "import")])
    _, h = await make_user("ci@test.local", roles=("CI",))
    await make_entity(db, "svc")

    r = await client.post(
        "/api/v1/imports", data={"project_path": "new/app", "auto_create": "true"},
        files=_files(), headers=h,
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/v1/imports", data={"project_path": "svc"}, files=_files(CONFIG), headers=h
    )
    assert r.status_code == 403
    r = await client.post("/api/v1/imports", data={"project_path": "svc"}, files=_files(), headers=h)
    assert r.status_code == 201


async def test_bad_config_rejects_import(client, admin, db):
    _, h = admin
    await make_entity(db, "svc")
    r = await client.post(
        "/api/v1/imports", data={"project_path": "svc"},
        files=_files(b"version: 1\nbogus: 1"), headers=h,
    )
    assert r.status_code == 422
    assert ".secretvuln.yml" in r.json()["detail"]
    assert await db.scalar(select(func.count()).select_from(Import)) == 0


async def test_config_applied_with_warnings(client, admin, db):
    _, h = admin
    payments = await make_group(db, "payments")
    config = CONFIG + b"ownership:\n  - path: 'x/**'\n    owner: ghost\n"
    r = await client.post(
        "/api/v1/imports", data={"project_path": "svc", "auto_create": "true", "commit_sha": "c1"},
        files=_files(config), headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["config_warnings"] == [
        "ownership: группа «ghost» не найдена — правило «x/**» пропущено"
    ]
    settings = (await client.get(f"/api/v1/entities/{r.json()['entity_id']}/settings", headers=h)).json()
    assert settings["fields"]["owner_group_id"]["value"] == str(payments.id)
    assert settings["fields"]["owner_group_id"]["source"] == "file"
    assert settings["config_commit_sha"] == "c1"


async def test_config_branch_applies_before_branch_check(client, admin):
    _, h = admin
    r = await client.post(
        "/api/v1/imports",
        data={"project_path": "svc", "auto_create": "true", "branch": "feature-x"},
        files=_files(b"version: 1\ndefault_branch: main\n"), headers=h,
    )
    assert r.status_code == 422
    assert "main" in r.json()["detail"]


async def test_legacy_endpoint_accepts_config(client, admin, db):
    _, h = admin
    await make_group(db, "payments")
    e = await make_entity(db, "svc")
    r = await client.post(f"/api/v1/entities/{e.id}/imports", files=_files(CONFIG), headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["entity_path"] == "svc"
```

- [ ] **Step 4: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_config_file.py tests/test_import_by_path.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.config_file'`.

- [ ] **Step 5: Сервис `backend/app/services/config_file.py`**

```python
"""Файл настроек проекта .secretvuln.yml: разбор, применение с учётом закреплённых полей, выгрузка."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity, OwnershipRule, RuleSource, UserGroup
from app.models.entity import RepoType
from app.services.entity_settings import find_repo_owner, normalize_repo_url

MAX_CONFIG_SIZE = 64 * 1024


class RepoSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, max_length=1024)
    type: RepoType | None = None
    path_prefix: str | None = Field(default=None, max_length=512)


class OwnershipEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=512)
    owner: str = Field(min_length=1, max_length=150)


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    default_branch: str | None = Field(default=None, max_length=255)
    owner: str | None = Field(default=None, max_length=150)
    repo: RepoSection | None = None
    ownership: list[OwnershipEntry] | None = Field(default=None, max_length=200)


class ConfigError(Exception):
    """Файл настроек не разобран — импорт отклоняется (422)."""


def parse_config(content: bytes) -> ProjectConfig:
    if len(content) > MAX_CONFIG_SIZE:
        raise ConfigError(".secretvuln.yml: файл больше 64 КБ")
    try:
        data = yaml.safe_load(content.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ConfigError(f".secretvuln.yml: не удалось разобрать YAML — {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(".secretvuln.yml: ожидается словарь, первая строка — version: 1")
    try:
        return ProjectConfig.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigError(f".secretvuln.yml: {details}") from exc


async def _group_by_name(db: AsyncSession, name: str) -> UserGroup | None:
    return await db.scalar(select(UserGroup).where(UserGroup.name == name))


async def apply_config(
    db: AsyncSession, entity: Entity, config: ProjectConfig, *, commit_sha: str | None = None
) -> list[str]:
    """Сохраняет файл в узле и переносит значения в незакреплённые поля. Не коммитит."""
    entity.config_file = config.model_dump(mode="json", exclude_none=True)
    entity.config_commit_sha = commit_sha
    entity.config_applied_at = datetime.now(timezone.utc)
    return await apply_stored_config(db, entity)


async def apply_stored_config(
    db: AsyncSession, entity: Entity, *, only: set[str] | None = None
) -> list[str]:
    """Переносит сохранённый config_file в поля узла, пропуская закреплённые. Не коммитит."""
    if entity.config_file is None:
        return []
    cfg = ProjectConfig.model_validate(entity.config_file)
    pinned = set(entity.pinned_fields)
    warnings: list[str] = []

    def wanted(key: str) -> bool:
        return key not in pinned and (only is None or key in only)

    if wanted("default_branch"):
        entity.default_branch = cfg.default_branch

    if wanted("owner_group_id"):
        if cfg.owner is None:
            entity.owner_group_id = None
        else:
            group = await _group_by_name(db, cfg.owner)
            if group is None:
                warnings.append(f"owner: группа «{cfg.owner}» не найдена — владелец не изменён")
            else:
                entity.owner_group_id = group.id

    if wanted("repo"):
        repo = cfg.repo or RepoSection()
        url = normalize_repo_url(repo.url) if repo.url else None
        other = await find_repo_owner(db, url, exclude_id=entity.id) if url else None
        if other is not None:
            warnings.append(
                f"repo.url: репозиторий уже привязан к проекту {other.path_cache} — не изменён"
            )
        else:
            entity.repo_url = url
            entity.repo_type = repo.type
            entity.repo_path_prefix = repo.path_prefix

    if wanted("ownership_rules"):
        await db.execute(delete(OwnershipRule).where(OwnershipRule.entity_id == entity.id))
        position = 0
        for entry in cfg.ownership or []:
            group = await _group_by_name(db, entry.owner)
            if group is None:
                warnings.append(
                    f"ownership: группа «{entry.owner}» не найдена — правило «{entry.path}» пропущено"
                )
                continue
            db.add(OwnershipRule(
                entity_id=entity.id, pattern=entry.path, group_id=group.id,
                position=position, source=RuleSource.file,
            ))
            position += 1

    await db.flush()
    return warnings


async def export_config(db: AsyncSession, entity: Entity) -> str:
    """Собственные настройки узла в формате .secretvuln.yml (без унаследованных)."""
    data: dict[str, Any] = {"version": 1}
    if entity.default_branch:
        data["default_branch"] = entity.default_branch
    if entity.owner_group_id:
        owner = await db.get(UserGroup, entity.owner_group_id)
        if owner is not None:
            data["owner"] = owner.name
    repo = {
        "url": entity.repo_url,
        "type": entity.repo_type.value if entity.repo_type else None,
        "path_prefix": entity.repo_path_prefix,
    }
    repo = {k: v for k, v in repo.items() if v}
    if repo:
        data["repo"] = repo
    rules = await db.scalars(
        select(OwnershipRule)
        .where(OwnershipRule.entity_id == entity.id)
        .order_by(OwnershipRule.position)
    )
    ownership = [{"path": r.pattern, "owner": r.group.name} for r in rules]
    if ownership:
        data["ownership"] = ownership
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
```

- [ ] **Step 6: Эндпоинты закрепления и выгрузки в `backend/app/api/entity_settings.py`**

Импорты: `from fastapi.responses import PlainTextResponse`; `from app.schemas.entity_settings import ..., UnpinRequest`; `from app.services.config_file import apply_stored_config, export_config`. В конец файла:

```python
@router.post("/{entity_id}/settings/unpin", response_model=EntitySettingsRead)
async def unpin_setting(
    entity_id: uuid.UUID,
    data: UnpinRequest,
    _: object = Depends(require_permission("entity", "write")),
    db: AsyncSession = Depends(get_db),
) -> EntitySettingsRead:
    """«Вернуть к файлу»: снять закрепление и сразу подставить значение из файла."""
    entity = await _entity_or_404(db, entity_id)
    entity.pinned_fields = [f for f in entity.pinned_fields if f != data.field]
    warnings = await apply_stored_config(db, entity, only={data.field})
    await db.commit()
    return await settings_read(db, entity, warnings)


@router.get("/{entity_id}/config.yml", response_class=PlainTextResponse)
async def download_config(
    entity_id: uuid.UUID,
    _: object = Depends(require_permission("entity", "read")),
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    entity = await _entity_or_404(db, entity_id)
    return PlainTextResponse(
        await export_config(db, entity),
        media_type="application/yaml; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename=".secretvuln.yml"'},
    )
```

- [ ] **Step 7: Схемы `backend/app/schemas/import_.py`**

В `ImportRead` после `pipeline_url` добавить `repo_url: str | None`, после `confirm_empty` — `config_warnings: list[str] = []`. В конец файла:

```python
class CreatedEntity(BaseModel):
    id: uuid.UUID
    path: str


class ImportCreated(ImportRead):
    # Заполняются в API через model_copy — у ORM-объекта Import этих атрибутов нет
    entity_path: str = ""
    created_entities: list[CreatedEntity] = []
```

- [ ] **Step 8: API `backend/app/api/imports.py` — заменить всё до `@router.get("/entities/{entity_id}/imports"...)`**

```python
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, has_permission, require_permission
from app.db.session import get_db
from app.models import Entity, Import
from app.models.import_ import ImportStatus
from app.schemas.import_ import CreatedEntity, ImportCreated, ImportRead
from app.services.config_file import ConfigError, ProjectConfig, apply_config, parse_config
from app.services.entity_paths import ensure_path
from app.services.entity_tree import branch_allowed, branch_rejection_message, resolve_default_branch
from app.services.storage import save_sarif

router = APIRouter(prefix="/api/v1", tags=["imports"])

MAX_SARIF_SIZE = 50 * 1024 * 1024  # 50 MB


async def _read_config(config: UploadFile | None) -> ProjectConfig | None:
    if config is None:
        return None
    try:
        return parse_config(await config.read())
    except ConfigError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


async def _create_import(
    db: AsyncSession,
    principal: Principal,
    entity: Entity,
    file: UploadFile,
    *,
    config: ProjectConfig | None,
    created: list[Entity],
    branch: str | None,
    commit_sha: str | None,
    pipeline_url: str | None,
    scan_scope: str | None,
    close_missing: bool,
    confirm_empty: bool,
) -> ImportCreated:
    warnings: list[str] = []
    if config is not None:
        if not has_permission(principal, "entity", "write"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Файл настроек проекта применяется только с правом entity:write",
            )
        warnings = await apply_config(db, entity, config, commit_sha=commit_sha or None)

    branch = branch or None
    default_branch = await resolve_default_branch(db, entity.id)
    if not branch_allowed(branch, default_branch):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            branch_rejection_message(branch, default_branch),
        )

    content = await file.read()
    if len(content) > MAX_SARIF_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large (max 50 MB)")

    filename = file.filename or "upload.sarif"
    storage_key = save_sarif(content, filename)

    import_record = Import(
        entity_id=entity.id,
        uploaded_by_id=principal.user.id,
        filename=filename,
        storage_key=storage_key,
        status=ImportStatus.pending,
        branch=branch,
        commit_sha=commit_sha or None,
        pipeline_url=pipeline_url or None,
        scan_scope=scan_scope or None,
        close_missing=close_missing,
        confirm_empty=confirm_empty,
        config_warnings=warnings,
    )
    db.add(import_record)
    await db.commit()
    await db.refresh(import_record)

    from app.worker import enqueue_import
    await enqueue_import(str(import_record.id))

    return ImportCreated.model_validate(import_record).model_copy(update={
        "entity_path": entity.path_cache,
        "created_entities": [CreatedEntity(id=e.id, path=e.path_cache) for e in created],
    })


@router.post(
    "/entities/{entity_id}/imports",
    response_model=ImportCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_import(
    entity_id: uuid.UUID,
    file: UploadFile,
    config: UploadFile | None = File(None),
    branch: str | None = Form(None),
    commit_sha: str | None = Form(None),
    pipeline_url: str | None = Form(None),
    scan_scope: str | None = Form(None),
    close_missing: bool = Form(True),
    confirm_empty: bool = Form(False),
    principal: Principal = Depends(require_permission("import", "import")),
    db: AsyncSession = Depends(get_db),
) -> ImportCreated:
    parsed = await _read_config(config)
    entity = await db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found")
    return await _create_import(
        db, principal, entity, file, config=parsed, created=[],
        branch=branch, commit_sha=commit_sha, pipeline_url=pipeline_url,
        scan_scope=scan_scope, close_missing=close_missing, confirm_empty=confirm_empty,
    )


@router.post("/imports", response_model=ImportCreated, status_code=status.HTTP_201_CREATED)
async def create_import_by_path(
    file: UploadFile,
    entity_id: uuid.UUID | None = Form(None),
    project_path: str | None = Form(None),
    auto_create: bool = Form(False),
    config: UploadFile | None = File(None),
    branch: str | None = Form(None),
    commit_sha: str | None = Form(None),
    pipeline_url: str | None = Form(None),
    scan_scope: str | None = Form(None),
    close_missing: bool = Form(True),
    confirm_empty: bool = Form(False),
    principal: Principal = Depends(require_permission("import", "import")),
    db: AsyncSession = Depends(get_db),
) -> ImportCreated:
    """Единая точка загрузки для CI: проект по entity_id или по пути (с автосозданием)."""
    project_path = (project_path or "").strip() or None
    if (entity_id is None) == (project_path is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите entity_id или project_path (одно из двух)"
        )
    parsed = await _read_config(config)

    created: list[Entity] = []
    if entity_id is not None:
        entity = await db.get(Entity, entity_id)
        if entity is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found")
    else:
        try:
            entity, _ = await ensure_path(db, project_path, create=False)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
        if entity is None:
            if not auto_create:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    f"Проект «{project_path}» не найден. Передайте auto_create=true, чтобы создать его",
                )
            if not has_permission(principal, "entity", "write"):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "Автосоздание проектов требует права entity:write"
                )
            entity, created = await ensure_path(db, project_path, create=True)

    return await _create_import(
        db, principal, entity, file, config=parsed, created=created,
        branch=branch, commit_sha=commit_sha, pipeline_url=pipeline_url,
        scan_scope=scan_scope, close_missing=close_missing, confirm_empty=confirm_empty,
    )
```

(Эндпоинты `GET` ниже в файле не меняются; `ImportRead` в них по-прежнему используется.)

- [ ] **Step 9: Тесты**

Run: `cd backend && .venv\Scripts\python -m pytest -q`
Expected: все PASS.

- [ ] **Step 10: Commit**

```bash
git add backend
git commit -m "feat: .secretvuln.yml project config with pinning, unified POST /imports with auto-create"
```

---

### Task 5: Назначение владельца при импорте и вручную

**Files:**
- Create: `backend/app/services/ownership.py`, `backend/tests/test_ownership.py`
- Modify: `backend/app/models/finding.py`, `backend/app/services/import_processing.py`, `backend/app/services/sarif/parser.py`, `backend/app/api/findings.py`, `backend/app/schemas/finding.py`, `backend/app/api/entity_settings.py`

**Interfaces:**
- Consumes: `OwnershipRule`, `Finding.assignee_*`, `lineage` (Task 3); `subtree_ids` (Task 2).
- Produces:
  - `OPEN_STATUSES` переезжает в `app/models/finding.py` (из `import_processing` по-прежнему импортируется).
  - `app/services/ownership.py`: `compile_glob(pattern) -> re.Pattern`, `path_matches(pattern, path) -> bool`, `OwnerResolver.resolve(file_path) -> uuid | None`, `async build_resolver(db, entity_id) -> OwnerResolver`, `async reassign_entity(db, entity_id, *, actor_id=None) -> int`.
  - `SarifResult.help: str | None`; `Finding.help_text` заполняется импортом; `Import.repo_url` — из SARIF.
  - `apply_import` → `stats["reassigned"]`.
  - `POST /api/v1/findings/{id}/assign` (`FindingAssign{group_id, user_id, by_rules}`), `POST /api/v1/entities/{id}/reassign` → `{"reassigned": n}`.
  - `FindingRead` += `assignee_group_id`, `assignee_user_id`, `assigned_manually`, `help_requested_at`, `assignee_group: GroupBrief | None`, `assignee_user: UserBriefLite | None`; `async load_finding(db, finding_id) -> Finding` в `app/api/findings.py` (перечитывает с отношениями).

- [ ] **Step 1: Падающие тесты `backend/tests/test_ownership.py`**

```python
"""Команда-владелец: маски путей, порядок правил, наследование, ручное назначение."""

import json

import pytest
from sqlalchemy import select

from app.models import FindingEvent, FindingEventType, OwnershipRule, RuleSource
from app.models.finding import Finding
from app.services.import_processing import apply_import
from app.services.ownership import path_matches
from app.services.sarif import parse_sarif
from tests.factories import make_entity, make_group, make_import, make_sarif


@pytest.mark.parametrize("pattern,path,expected", [
    ("app/payments/**", "app/payments/x/y.py", True),
    ("app/payments/**", "app/paymentsx/y.py", False),
    ("*.py", "a.py", True),
    ("*.py", "dir/a.py", False),
    ("**/test_*.py", "a/b/test_x.py", True),
    ("**/test_*.py", "test_x.py", True),
    ("app/auth/", "app/auth/login.py", True),
    ("./app/*.py", "/app/main.py", True),
    ("app/?.py", "app/a.py", True),
    ("app/?.py", "app/ab.py", False),
])
def test_path_matches(pattern, path, expected):
    assert path_matches(pattern, path) is expected


async def _rule(db, entity, pattern, group, position=0):
    db.add(OwnershipRule(
        entity_id=entity.id, pattern=pattern, group_id=group.id,
        position=position, source=RuleSource.manual,
    ))
    await db.commit()


async def _import(db, entity, results):
    imp = await make_import(db, entity)
    stats = await apply_import(db, imp, parse_sarif(make_sarif("Semgrep", results)))
    await db.commit()
    return stats


async def _by_fp(db, fp):
    return await db.scalar(select(Finding).where(Finding.fingerprint == fp))


async def test_rule_then_owner_then_nobody(db):
    payments = await make_group(db, "payments")
    platform = await make_group(db, "platform")
    owned = await make_entity(db, "svc", owner_group_id=platform.id)
    await _rule(db, owned, "app/payments/**", payments)
    await _import(db, owned, [
        {"fp": "p", "path": "app/payments/pay.py"},
        {"fp": "o", "path": "app/other.py"},
    ])
    assert (await _by_fp(db, "p")).assignee_group_id == payments.id
    assert (await _by_fp(db, "o")).assignee_group_id == platform.id

    orphan = await make_entity(db, "orphan")
    await _import(db, orphan, [{"fp": "n", "path": "x.py"}])
    assert (await _by_fp(db, "n")).assignee_group_id is None


async def test_rules_inherited_and_child_first(db):
    parent_team = await make_group(db, "parent-team")
    child_team = await make_group(db, "child-team")
    parent = await make_entity(db, "fintech")
    child = await make_entity(db, "api", parent_id=parent.id)
    await _rule(db, parent, "app/**", parent_team)
    await _rule(db, child, "app/core/**", child_team)
    await _import(db, child, [
        {"fp": "core", "path": "app/core/a.py"},
        {"fp": "misc", "path": "app/misc.py"},
    ])
    assert (await _by_fp(db, "core")).assignee_group_id == child_team.id
    assert (await _by_fp(db, "misc")).assignee_group_id == parent_team.id


async def test_rule_change_reassigns_on_next_import(db):
    a = await make_group(db, "a")
    b = await make_group(db, "b")
    e = await make_entity(db, "svc", owner_group_id=a.id)
    await _import(db, e, [{"fp": "x", "path": "app/x.py"}])
    assert (await _by_fp(db, "x")).assignee_group_id == a.id

    await _rule(db, e, "app/**", b)
    stats = await _import(db, e, [{"fp": "x", "path": "app/x.py"}])
    finding = await _by_fp(db, "x")
    assert finding.assignee_group_id == b.id
    assert stats["reassigned"] == 1
    events = list(await db.scalars(
        select(FindingEvent).where(
            FindingEvent.finding_id == finding.id,
            FindingEvent.event_type == FindingEventType.assigned,
        )
    ))
    assert len(events) == 1
    assert events[0].payload["to_group_id"] == str(b.id)


async def test_manual_assignment_survives_reimport(client, admin, db):
    _, h = admin
    a = await make_group(db, "a")
    manual = await make_group(db, "manual")
    e = await make_entity(db, "svc", owner_group_id=a.id)
    await _import(db, e, [{"fp": "x", "path": "app/x.py"}])
    finding = await _by_fp(db, "x")

    r = await client.post(
        f"/api/v1/findings/{finding.id}/assign", json={"group_id": str(manual.id)}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["assignee_group"]["name"] == "manual"
    assert r.json()["assigned_manually"] is True

    await _import(db, e, [{"fp": "x", "path": "app/x.py"}])
    await db.refresh(finding)
    assert finding.assignee_group_id == manual.id

    r = await client.post(f"/api/v1/findings/{finding.id}/assign", json={"by_rules": True}, headers=h)
    assert r.json()["assignee_group_id"] == str(a.id)
    assert r.json()["assigned_manually"] is False


async def test_assign_requires_triage_and_valid_group(client, make_user, admin, db):
    _, h = admin
    e = await make_entity(db, "svc")
    await _import(db, e, [{"fp": "x"}])
    finding = await _by_fp(db, "x")
    r = await client.post(
        f"/api/v1/findings/{finding.id}/assign",
        json={"group_id": "00000000-0000-0000-0000-000000000000"},
        headers=h,
    )
    assert r.status_code == 422
    _, viewer = await make_user("viewer@test.local")
    r = await client.post(f"/api/v1/findings/{finding.id}/assign", json={"by_rules": True}, headers=viewer)
    assert r.status_code == 403


async def test_reassign_subtree_endpoint(client, admin, db):
    _, h = admin
    team = await make_group(db, "team")
    parent = await make_entity(db, "p")
    child = await make_entity(db, "c", parent_id=parent.id)
    await _import(db, child, [{"fp": "x", "path": "app/x.py"}])
    assert (await _by_fp(db, "x")).assignee_group_id is None

    await _rule(db, parent, "app/**", team)
    r = await client.post(f"/api/v1/entities/{parent.id}/reassign", headers=h)
    assert r.status_code == 200
    assert r.json() == {"reassigned": 1}
    finding = await _by_fp(db, "x")
    await db.refresh(finding)
    assert finding.assignee_group_id == team.id


def test_parser_reads_rule_help_and_repo():
    sarif = {
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "Semgrep", "rules": [
                {"id": "r1", "help": {"text": "Use parameters", "markdown": "Use **parameters**"}},
            ]}},
            "versionControlProvenance": [{"repositoryUri": "https://gitlab.corp/t/app"}],
            "results": [{
                "ruleId": "r1", "message": {"text": "m"},
                "partialFingerprints": {"primaryLocationLineHash": "h"},
            }],
        }],
    }
    run = parse_sarif(json.dumps(sarif).encode())[0]
    assert run.results[0].help == "Use **parameters**"
    assert run.repository_uri == "https://gitlab.corp/t/app"
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_ownership.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ownership'`.

- [ ] **Step 3: `OPEN_STATUSES` в `backend/app/models/finding.py`**

Сразу после класса `FindingStatus` добавить:

```python
# Открытые статусы: участвуют в автозакрытии и переназначении владельца.
# Решения людей (ложное/риск) и fixed не трогаем.
OPEN_STATUSES: tuple[FindingStatus, ...] = (
    FindingStatus.new,
    FindingStatus.triaged,
    FindingStatus.confirmed,
    FindingStatus.in_progress,
)
```

В `backend/app/services/import_processing.py` удалить локальное определение `OPEN_STATUSES` (вместе с комментарием над ним) и заменить импорт `from app.models.finding import Finding, FindingStatus` на `from app.models.finding import OPEN_STATUSES, Finding, FindingStatus`.

- [ ] **Step 4: Сервис `backend/app/services/ownership.py`**

```python
"""Команда-владелец уязвимости: правила по путям → владелец проекта → никто."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActorType, Entity, FindingEventType, OwnershipRule
from app.models.finding import OPEN_STATUSES, Finding
from app.services.entity_settings import lineage
from app.services.events import record_event


def normalize_path(path: str) -> str:
    value = path.replace("\\", "/")
    if value.startswith("file://"):
        value = value[len("file://"):]
    while value.startswith("./"):
        value = value[2:]
    return value.lstrip("/")


@lru_cache(maxsize=1024)
def compile_glob(pattern: str) -> re.Pattern[str]:
    """Маска в стиле CODEOWNERS: ** — любые папки, * — внутри одной папки, ? — один символ."""
    p = normalize_path(pattern.strip())
    if p.endswith("/"):
        p += "**"
    out: list[str] = []
    i = 0
    while i < len(p):
        if p.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif p.startswith("**", i):
            out.append(".*")
            i += 2
        elif p[i] == "*":
            out.append("[^/]*")
            i += 1
        elif p[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(p[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def path_matches(pattern: str, path: str) -> bool:
    return bool(compile_glob(pattern).match(normalize_path(path)))


@dataclass
class OwnerResolver:
    # (маска, команда) в порядке приоритета: правила узла, затем предков вверх по дереву
    rules: list[tuple[str, uuid.UUID]]
    default_owner: uuid.UUID | None

    def resolve(self, file_path: str | None) -> uuid.UUID | None:
        if file_path:
            for pattern, group_id in self.rules:
                if path_matches(pattern, file_path):
                    return group_id
        return self.default_owner


async def build_resolver(db: AsyncSession, entity_id: uuid.UUID) -> OwnerResolver:
    entity = await db.get(Entity, entity_id)
    rules: list[tuple[str, uuid.UUID]] = []
    default_owner: uuid.UUID | None = None
    for node in await lineage(db, entity):
        result = await db.scalars(
            select(OwnershipRule)
            .where(OwnershipRule.entity_id == node.id)
            .order_by(OwnershipRule.position)
        )
        rules.extend((r.pattern, r.group_id) for r in result)
        if default_owner is None and node.owner_group_id is not None:
            default_owner = node.owner_group_id
    return OwnerResolver(rules=rules, default_owner=default_owner)


async def reassign_entity(
    db: AsyncSession, entity_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
) -> int:
    """Переназначить открытые уязвимости проекта по правилам (кроме назначенных вручную)."""
    resolver = await build_resolver(db, entity_id)
    findings = await db.scalars(
        select(Finding).where(
            Finding.entity_id == entity_id,
            Finding.assigned_manually.is_(False),
            Finding.status.in_(OPEN_STATUSES),
        )
    )
    changed = 0
    for finding in findings:
        group_id = resolver.resolve(finding.file_path)
        if group_id == finding.assignee_group_id:
            continue
        record_event(
            db, finding.id, FindingEventType.assigned,
            actor_type=ActorType.user if actor_id else ActorType.system,
            actor_id=actor_id,
            reason="Назначено по правилам владения",
            payload={
                "from_group_id": str(finding.assignee_group_id) if finding.assignee_group_id else None,
                "to_group_id": str(group_id) if group_id else None,
                "by_rules": True,
            },
        )
        finding.assignee_group_id = group_id
        changed += 1
    await db.flush()
    return changed
```

- [ ] **Step 5: Парсер `backend/app/services/sarif/parser.py`**

В `SarifResult` последним полем добавить `help: str | None = None`. Перед `def parse_sarif` добавить:

```python
def _rule_help(rule: dict[str, Any] | None) -> str | None:
    if not rule:
        return None
    help_ = rule.get("help") or {}
    return help_.get("markdown") or help_.get("text")
```

В вызове `SarifResult(...)` после `raw=result,` добавить `help=_rule_help(rule),`.

- [ ] **Step 6: Импорт — `backend/app/services/import_processing.py`**

Добавить импорт `from app.services.ownership import build_resolver, reassign_entity`.

`_apply_provenance` дополнить строкой в цикле:

```python
        imp.repo_url = imp.repo_url or run.repository_uri
```

В `apply_import` сразу после проверки ветки (`raise ImportRejected(...)`) добавить:

```python
    resolver = await build_resolver(db, imp.entity_id)
```

В ветке `if existing:` после `existing.commit_sha = imp.commit_sha` добавить `existing.help_text = result.help`.

В `Finding(...)` для новой находки после `raw=result.raw,` добавить:

```python
                        help_text=result.help,
                        assignee_group_id=assignee_group_id,
```

и перед `db.add(Finding(...))` строку `assignee_group_id = resolver.resolve(result.file_path)`. В событии `imported` payload заменить на:

```python
                    payload={
                        "import_id": str(imp.id),
                        "assignee_group_id": str(assignee_group_id) if assignee_group_id else None,
                    },
```

После блока `if imp.close_missing: ...` (перед `imp.scanner = scanner_name`) добавить:

```python
    reassigned = await reassign_entity(db, imp.entity_id)
```

и в `stats` добавить ключ `"reassigned": reassigned,`.

- [ ] **Step 7: Схемы `backend/app/schemas/finding.py`**

Перед `FindingRead` добавить:

```python
class GroupBrief(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str


class UserBriefLite(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    full_name: str | None
```

В `FindingRead` после `commit_sha` добавить:

```python
    assignee_group_id: uuid.UUID | None
    assignee_user_id: uuid.UUID | None
    assigned_manually: bool
    help_requested_at: datetime | None
    assignee_group: GroupBrief | None
    assignee_user: UserBriefLite | None
```

В конец файла:

```python
class FindingAssign(BaseModel):
    group_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    # true — снять ручное назначение и назначить по правилам
    by_rules: bool = False
```

- [ ] **Step 8: API назначения в `backend/app/api/findings.py`**

Импорты: `from app.models import Entity, Finding` → `from app.models import Entity, Finding, User, UserGroup`; `from app.schemas.finding import FindingRead, FindingStatusUpdate` → `from app.schemas.finding import FindingAssign, FindingRead, FindingStatusUpdate`; добавить `from app.services.ownership import build_resolver`.

После `_entity_filter` добавить:

```python
async def load_finding(db: AsyncSession, finding_id: uuid.UUID) -> Finding:
    """Перечитать находку вместе с командой/исполнителем (selectin) — для ответа после изменений."""
    return await db.scalar(
        select(Finding).where(Finding.id == finding_id).execution_options(populate_existing=True)
    )
```

В `update_finding_status` заменить
```python
        await db.commit()
        await db.refresh(finding)
    return finding
```
на
```python
        await db.commit()
    return await load_finding(db, finding.id)
```

В конец файла:

```python
@router.post("/findings/{finding_id}/assign", response_model=FindingRead)
async def assign_finding(
    finding_id: uuid.UUID,
    data: FindingAssign,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> Finding:
    finding = await db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")

    if data.by_rules:
        new_group = (await build_resolver(db, finding.entity_id)).resolve(finding.file_path)
        finding.assigned_manually = False
        finding.assignee_user_id = None
    else:
        if data.group_id is not None and await db.get(UserGroup, data.group_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Команда не найдена")
        if data.user_id is not None and await db.get(User, data.user_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Пользователь не найден")
        new_group = data.group_id
        finding.assigned_manually = True
        finding.assignee_user_id = data.user_id

    record_event(
        db, finding.id, FindingEventType.assigned,
        actor_type=ActorType.user, actor_id=principal.user.id,
        payload={
            "from_group_id": str(finding.assignee_group_id) if finding.assignee_group_id else None,
            "to_group_id": str(new_group) if new_group else None,
            "user_id": str(data.user_id) if data.user_id and not data.by_rules else None,
            "by_rules": data.by_rules,
        },
    )
    finding.assignee_group_id = new_group
    await db.commit()
    return await load_finding(db, finding.id)
```

- [ ] **Step 9: Переназначение поддерева в `backend/app/api/entity_settings.py`**

Импорты: `from app.api.deps import Principal, require_permission`; `from app.services.entity_paths import subtree_ids`; `from app.services.ownership import reassign_entity`. В конец файла:

```python
@router.post("/{entity_id}/reassign")
async def reassign_subtree(
    entity_id: uuid.UUID,
    principal: Principal = Depends(require_permission("entity", "write")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """«Переназначить по правилам»: применить правила к открытым уязвимостям поддерева сейчас."""
    entity = await _entity_or_404(db, entity_id)
    total = 0
    for node_id in list(await db.scalars(subtree_ids(entity))):
        total += await reassign_entity(db, node_id, actor_id=principal.user.id)
    await db.commit()
    return {"reassigned": total}
```

- [ ] **Step 10: Тесты**

Run: `cd backend && .venv\Scripts\python -m pytest -q`
Expected: все PASS (включая старые `test_import_processing.py`, `test_auto_close.py` — у них появился ключ `reassigned` в stats; если какой-то тест сравнивает stats целиком через `==`, дополнить ожидаемый словарь `"reassigned": 0`).

- [ ] **Step 11: Commit**

```bash
git add backend
git commit -m "feat: assign owner team on import by path rules and project owner, manual reassign"
```

---

### Task 6: Карточка уязвимости со ссылкой на код и фильтры списка

**Files:**
- Create: `backend/app/services/code_links.py`, `backend/tests/test_code_links.py`, `backend/tests/test_finding_filters.py`
- Modify: `backend/app/schemas/finding.py`, `backend/app/api/findings.py`

**Interfaces:**
- Consumes: `effective_settings` (Task 3), `Import.repo_url` (Task 3/5), `Finding.help_text` (Task 5), `load_finding` (Task 5).
- Produces: `guess_repo_type(url) -> RepoType | None`, `build_code_url(*, repo_url, repo_type, ref, path, line, ref_is_commit, path_prefix=None) -> str | None`; схема `FindingDetail(FindingRead)` с `entity_name`, `entity_path`, `code_url`, `code_url_head`, `help_text`; `GET /findings/{id}` и `GET /findings/by-number/{n}` отдают `FindingDetail`; у `GET /findings` параметры `status` (можно повторять), `assignee_group_id`, `unassigned`, `mine`, `help_requested`, `pending_decision`, `order` (`last_seen|severity|number`).

- [ ] **Step 1: Падающие тесты `backend/tests/test_code_links.py`**

```python
"""Ссылки на строку кода для четырёх типов репозиториев и карточка уязвимости."""

import pytest

from app.models.entity import RepoType
from app.services.code_links import build_code_url, guess_repo_type
from tests.factories import make_entity, make_finding

REPO = "https://git.corp/team/app"


@pytest.mark.parametrize("rtype,commit,expected", [
    (RepoType.gitlab, True, f"{REPO}/-/blob/abc/src/a.py#L7"),
    (RepoType.github, True, f"{REPO}/blob/abc/src/a.py#L7"),
    (RepoType.gitea, True, f"{REPO}/src/commit/abc/src/a.py#L7"),
    (RepoType.gitea, False, f"{REPO}/src/branch/abc/src/a.py#L7"),
    (RepoType.bitbucket, True, f"{REPO}/browse/src/a.py?at=abc#7"),
])
def test_templates(rtype, commit, expected):
    url = build_code_url(
        repo_url=REPO, repo_type=rtype, ref="abc", path="src/a.py", line=7, ref_is_commit=commit
    )
    assert url == expected


def test_prefix_no_line_and_missing_parts():
    url = build_code_url(
        repo_url=REPO + ".git", repo_type=RepoType.gitlab, ref="main", path="./a b.py",
        line=None, ref_is_commit=False, path_prefix="services/api/",
    )
    assert url == f"{REPO}/-/blob/main/services/api/a%20b.py"
    assert build_code_url(
        repo_url=REPO, repo_type=RepoType.gitlab, ref="main",
        path="services/api/x.py", line=1, ref_is_commit=False, path_prefix="services/api",
    ) == f"{REPO}/-/blob/main/services/api/x.py#L1"
    assert build_code_url(
        repo_url=None, repo_type=RepoType.gitlab, ref="a", path="x", line=1, ref_is_commit=True
    ) is None
    assert build_code_url(
        repo_url="https://unknown.host/x", repo_type=None, ref="a", path="x", line=1,
        ref_is_commit=True,
    ) is None


def test_guess_repo_type():
    assert guess_repo_type("https://github.com/o/r") == RepoType.github
    assert guess_repo_type("https://gitlab.corp/o/r") == RepoType.gitlab
    assert guess_repo_type("https://code.corp/o/r") is None


async def test_detail_has_links_and_path(client, admin, db):
    _, h = admin
    parent = await make_entity(
        db, "fintech", repo_url="https://gitlab.corp/fin/app", repo_type=RepoType.gitlab,
        default_branch="main",
    )
    child = await make_entity(db, "api", parent_id=parent.id)
    f = await make_finding(
        db, child, "fp", file_path="src/a.py", line_start=3, commit_sha="c0ffee",
        help_text="Use parameters",
    )
    r = await client.get(f"/api/v1/findings/by-number/{f.number}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["entity_path"] == "fintech/api"
    assert body["entity_name"] == "api"
    assert body["code_url"] == "https://gitlab.corp/fin/app/-/blob/c0ffee/src/a.py#L3"
    assert body["code_url_head"] == "https://gitlab.corp/fin/app/-/blob/main/src/a.py#L3"
    assert body["help_text"] == "Use parameters"


async def test_detail_without_repo_has_no_links(client, admin, db):
    _, h = admin
    e = await make_entity(db, "svc")
    f = await make_finding(db, e, "fp", file_path="a.py", commit_sha="c")
    body = (await client.get(f"/api/v1/findings/{f.id}", headers=h)).json()
    assert body["code_url"] is None
    assert body["code_url_head"] is None
```

- [ ] **Step 2: Падающие тесты `backend/tests/test_finding_filters.py`**

```python
"""Фильтры списка уязвимостей: мои, без владельца, команда, несколько статусов, сортировка."""

from datetime import datetime, timezone

from app.models import user_group_members
from app.models.finding import FindingStatus, Severity
from tests.factories import make_entity, make_finding, make_group


async def _numbers(client, h, query):
    r = await client.get(f"/api/v1/findings?{query}", headers=h)
    assert r.status_code == 200, r.text
    return sorted(x["fingerprint"] for x in r.json())


async def test_mine_unassigned_and_team(client, developer, db):
    user, h = developer
    team = await make_group(db, "team")
    other = await make_group(db, "other")
    await db.execute(user_group_members.insert().values(group_id=team.id, user_id=user.id))
    await db.commit()
    e = await make_entity(db, "svc")
    await make_finding(db, e, "team", assignee_group_id=team.id)
    await make_finding(db, e, "other", assignee_group_id=other.id)
    await make_finding(db, e, "personal", assignee_group_id=other.id, assignee_user_id=user.id)
    await make_finding(db, e, "nobody")

    assert await _numbers(client, h, "mine=true") == ["personal", "team"]
    assert await _numbers(client, h, "unassigned=true") == ["nobody"]
    assert await _numbers(client, h, f"assignee_group_id={other.id}") == ["other", "personal"]


async def test_multi_status_help_and_order(client, admin, db):
    _, h = admin
    e = await make_entity(db, "svc")
    await make_finding(db, e, "low", severity=Severity.low, status=FindingStatus.confirmed)
    await make_finding(db, e, "crit", severity=Severity.critical, status=FindingStatus.in_progress)
    await make_finding(db, e, "new", status=FindingStatus.new,
                       help_requested_at=datetime.now(timezone.utc))

    assert await _numbers(client, h, "status=confirmed&status=in_progress") == ["crit", "low"]
    assert await _numbers(client, h, "help_requested=true") == ["new"]
    r = await client.get("/api/v1/findings?order=severity&status=confirmed&status=in_progress", headers=h)
    assert [x["fingerprint"] for x in r.json()] == ["crit", "low"]


async def test_pending_decision_filter(client, developer, db):
    _, h = developer
    e = await make_entity(db, "svc")
    a = await make_finding(db, e, "asked")
    await make_finding(db, e, "quiet")
    r = await client.post(
        f"/api/v1/findings/{a.id}/decisions",
        json={"decision_type": "false_positive", "reason_tag": "test_code"},
        headers=h,
    )
    assert r.status_code == 201
    assert await _numbers(client, h, "pending_decision=true") == ["asked"]
```

- [ ] **Step 3: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_code_links.py tests/test_finding_filters.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.code_links'`.

- [ ] **Step 4: Сервис `backend/app/services/code_links.py`**

```python
"""Ссылки «открыть в GitLab/GitHub/Gitea/Bitbucket» на строку кода."""

from __future__ import annotations

from urllib.parse import quote, urlsplit

from app.models.entity import RepoType


def guess_repo_type(url: str) -> RepoType | None:
    host = urlsplit(url).netloc.lower()
    for rtype in RepoType:
        if rtype.value in host:
            return rtype
    return None


def build_code_url(
    *,
    repo_url: str | None,
    repo_type: RepoType | None,
    ref: str | None,
    path: str | None,
    line: int | None,
    ref_is_commit: bool,
    path_prefix: str | None = None,
) -> str | None:
    if not (repo_url and ref and path):
        return None
    rtype = repo_type or guess_repo_type(repo_url)
    if rtype is None:
        return None

    repo = repo_url.strip().rstrip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    file_path = path.replace("\\", "/")
    while file_path.startswith("./"):
        file_path = file_path[2:]
    file_path = file_path.lstrip("/")
    prefix = (path_prefix or "").strip("/")
    if prefix and not file_path.startswith(prefix + "/"):
        file_path = f"{prefix}/{file_path}"

    qpath = quote(file_path, safe="/")
    qref = quote(ref, safe="/")
    if rtype == RepoType.gitlab:
        url, anchor = f"{repo}/-/blob/{qref}/{qpath}", f"#L{line}"
    elif rtype == RepoType.github:
        url, anchor = f"{repo}/blob/{qref}/{qpath}", f"#L{line}"
    elif rtype == RepoType.gitea:
        kind = "commit" if ref_is_commit else "branch"
        url, anchor = f"{repo}/src/{kind}/{qref}/{qpath}", f"#L{line}"
    else:
        url, anchor = f"{repo}/browse/{qpath}?at={qref}", f"#{line}"
    return url + (anchor if line else "")
```

- [ ] **Step 5: Схема `FindingDetail` в `backend/app/schemas/finding.py`**

В конец файла:

```python
class FindingDetail(FindingRead):
    """Карточка для окна уязвимости: адрес проекта, ссылки на код, рекомендация сканера."""

    entity_name: str = ""
    entity_path: str = ""
    code_url: str | None = None
    code_url_head: str | None = None
    help_text: str | None = None
```

- [ ] **Step 6: API `backend/app/api/findings.py`**

Импорты: `from sqlalchemy import func, select` → `from sqlalchemy import func, or_, select`; `from app.models import Entity, Finding, User, UserGroup` → `from app.models import DecisionRequest, DecisionStatus, Entity, Finding, Import, User, UserGroup, user_group_members`; добавить `from typing import Literal`, `from app.models.entity import RepoType`, `from app.services.code_links import build_code_url`, `from app.services.entity_settings import effective_settings`; в импорт схем добавить `FindingDetail`.

После `load_finding` добавить:

```python
async def to_detail(db: AsyncSession, finding: Finding) -> FindingDetail:
    entity = await db.get(Entity, finding.entity_id)
    settings = await effective_settings(db, entity)
    imp = await db.get(Import, finding.import_id) if finding.import_id else None
    repo_url = (imp.repo_url if imp else None) or settings["repo_url"]["value"]
    repo_type_value = settings["repo_type"]["value"]
    common = dict(
        repo_url=repo_url,
        repo_type=RepoType(repo_type_value) if repo_type_value else None,
        path=finding.file_path,
        line=finding.line_start,
        path_prefix=settings["repo_path_prefix"]["value"],
    )
    return FindingDetail.model_validate(finding).model_copy(update={
        "entity_name": entity.name,
        "entity_path": entity.path_cache,
        "code_url": build_code_url(ref=finding.commit_sha, ref_is_commit=True, **common),
        "code_url_head": build_code_url(
            ref=settings["default_branch"]["value"], ref_is_commit=False, **common
        ),
    })
```

`get_finding_by_number` и `get_finding`: `response_model=FindingRead` → `response_model=FindingDetail`, аннотацию возврата → `FindingDetail`, последнюю строку `return finding` → `return await to_detail(db, finding)`.

Сигнатуру и тело `list_findings` заменить на:

```python
@router.get("/findings", response_model=list[FindingRead])
async def list_findings(
    entity_id: uuid.UUID | None = None,
    include_descendants: bool = False,
    severity: Severity | None = None,
    finding_status: list[FindingStatus] | None = Query(None, alias="status"),
    scanner: str | None = None,
    assignee_group_id: uuid.UUID | None = None,
    unassigned: bool = False,
    mine: bool = False,
    help_requested: bool = False,
    pending_decision: bool = False,
    order: Literal["last_seen", "severity", "number"] = "last_seen",
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[Finding]:
    q = select(Finding)
    if entity_id:
        q = q.where(await _entity_filter(db, entity_id, include_descendants))
    if severity:
        q = q.where(Finding.severity == severity)
    if finding_status:
        q = q.where(Finding.status.in_(finding_status))
    if scanner:
        q = q.where(Finding.scanner == scanner)
    if assignee_group_id:
        q = q.where(Finding.assignee_group_id == assignee_group_id)
    if unassigned:
        q = q.where(Finding.assignee_group_id.is_(None))
    if help_requested:
        q = q.where(Finding.help_requested_at.is_not(None))
    if pending_decision:
        q = q.where(
            select(DecisionRequest.id)
            .where(
                DecisionRequest.finding_id == Finding.id,
                DecisionRequest.status == DecisionStatus.pending,
            )
            .exists()
        )
    if mine:
        my_groups = select(user_group_members.c.group_id).where(
            user_group_members.c.user_id == principal.user.id
        )
        q = q.where(or_(
            Finding.assignee_user_id == principal.user.id,
            Finding.assignee_group_id.in_(my_groups),
        ))
    if order == "severity":
        q = q.order_by(Finding.severity, Finding.first_seen)
    elif order == "number":
        q = q.order_by(Finding.number.desc())
    else:
        q = q.order_by(Finding.last_seen.desc())
    result = await db.scalars(q.offset(offset).limit(limit))
    return list(result)
```

(Порядок `Finding.severity` по возрастанию = critical → info: так объявлен PG enum.)

- [ ] **Step 7: Тесты**

Run: `cd backend && .venv\Scripts\python -m pytest -q`
Expected: все PASS.

- [ ] **Step 8: Commit**

```bash
git add backend
git commit -m "feat: finding detail with code links, list filters for mine/unassigned/team/help"
```

---

### Task 7: Комментарии, «Нужна помощь AppSec», массовые действия, права в `/auth/me`

**Files:**
- Create: `backend/tests/test_collaboration.py`
- Modify: `backend/app/api/findings.py`, `backend/app/schemas/finding.py`, `backend/app/schemas/finding_event.py`, `backend/app/api/auth.py`, `backend/app/schemas/auth.py`

**Interfaces:**
- Consumes: `create_request`, `DecisionError` (этап 1, `app/services/decisions.py`), `DecisionCreate` (`app/schemas/decision.py`), `load_finding`, `to_detail` (Task 5–6).
- Produces: `POST /findings/{id}/comments` (`CommentCreate{text, resolve_help}` → `FindingEventRead`, 201), `POST /findings/{id}/help` (`HelpRequest{text}` → `FindingDetail`), `POST /findings/bulk` (`BulkAction` → `BulkResult{applied, skipped:[{id, reason}]}`); `FindingEventRead.actor_name`; `UserRead.permissions: list[str]` (`"finding:approve"` и т. п.).

- [ ] **Step 1: Падающие тесты `backend/tests/test_collaboration.py`**

```python
"""Комментарии, запрос помощи AppSec, массовые действия, права текущего пользователя."""

from app.models.finding import FindingStatus
from tests.factories import make_entity, make_finding, make_group


async def test_comment_listed_with_author(client, developer, db):
    user, h = developer
    f = await make_finding(db, await make_entity(db, "svc"), "fp")
    r = await client.post(f"/api/v1/findings/{f.id}/comments", json={"text": "  Смотрю  "}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["event_type"] == "comment"
    assert r.json()["reason"] == "Смотрю"
    events = (await client.get(f"/api/v1/findings/{f.id}/events", headers=h)).json()
    assert events[-1]["actor_name"] == user.email


async def test_help_request_and_resolution(client, developer, appsec, db):
    _, dev_h = developer
    _, sec_h = appsec
    f = await make_finding(db, await make_entity(db, "svc"), "fp")

    r = await client.post(f"/api/v1/findings/{f.id}/help", json={"text": "Это правда уязвимость?"}, headers=dev_h)
    assert r.status_code == 200, r.text
    assert r.json()["help_requested_at"] is not None
    r = await client.post(f"/api/v1/findings/{f.id}/help", json={"text": "ещё"}, headers=dev_h)
    assert r.status_code == 409

    r = await client.post(
        f"/api/v1/findings/{f.id}/comments", json={"text": "ok", "resolve_help": True}, headers=dev_h
    )
    assert r.status_code == 403

    r = await client.post(
        f"/api/v1/findings/{f.id}/comments", json={"text": "Да, исправляйте", "resolve_help": True},
        headers=sec_h,
    )
    assert r.status_code == 201
    detail = (await client.get(f"/api/v1/findings/{f.id}", headers=sec_h)).json()
    assert detail["help_requested_at"] is None
    types = [e["event_type"] for e in (await client.get(f"/api/v1/findings/{f.id}/events", headers=sec_h)).json()]
    # комментарий и снятие флага пишутся в одной транзакции (одинаковый created_at) — порядок между ними не гарантирован
    assert types[-3] == "help_requested"
    assert set(types[-2:]) == {"comment", "help_resolved"}


async def test_help_on_closed_finding_rejected(client, developer, db):
    _, h = developer
    f = await make_finding(db, await make_entity(db, "svc"), "fp", status=FindingStatus.fixed)
    r = await client.post(f"/api/v1/findings/{f.id}/help", json={"text": "?"}, headers=h)
    assert r.status_code == 409


async def test_bulk_confirm_skips_closed(client, appsec, db):
    _, h = appsec
    e = await make_entity(db, "svc")
    a = await make_finding(db, e, "a")
    b = await make_finding(db, e, "b", status=FindingStatus.fixed)
    r = await client.post(
        "/api/v1/findings/bulk",
        json={"ids": [str(a.id), str(b.id), "00000000-0000-0000-0000-000000000000"], "action": "confirm"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] == 1
    assert {s["id"] for s in body["skipped"]} == {str(b.id), "00000000-0000-0000-0000-000000000000"}
    await db.refresh(a)
    assert a.status == FindingStatus.confirmed


async def test_bulk_false_positive_needs_approve(client, developer, appsec, db):
    e = await make_entity(db, "svc")
    a = await make_finding(db, e, "a")
    body = {"ids": [str(a.id)], "action": "false_positive", "reason_tag": "test_code"}
    _, dev_h = developer
    assert (await client.post("/api/v1/findings/bulk", json=body, headers=dev_h)).status_code == 403

    _, sec_h = appsec
    r = await client.post("/api/v1/findings/bulk", json=body, headers=sec_h)
    assert r.json()["applied"] == 1
    await db.refresh(a)
    assert a.status == FindingStatus.false_positive

    r = await client.post(
        "/api/v1/findings/bulk",
        json={"ids": [str(a.id)], "action": "false_positive", "reason_tag": "other"},
        headers=sec_h,
    )
    assert r.status_code == 422


async def test_bulk_assign(client, appsec, db):
    _, h = appsec
    team = await make_group(db, "team")
    a = await make_finding(db, await make_entity(db, "svc"), "a")
    r = await client.post(
        "/api/v1/findings/bulk",
        json={"ids": [str(a.id)], "action": "assign", "group_id": str(team.id)},
        headers=h,
    )
    assert r.json()["applied"] == 1
    await db.refresh(a)
    assert a.assignee_group_id == team.id
    assert a.assigned_manually is True
    r = await client.post("/api/v1/findings/bulk", json={"ids": [str(a.id)], "action": "assign"}, headers=h)
    assert r.status_code == 422


async def test_me_lists_permissions(client, developer):
    _, h = developer
    perms = (await client.get("/api/v1/auth/me", headers=h)).json()["permissions"]
    assert "finding:triage" in perms
    assert "finding:approve" not in perms
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_collaboration.py -v`
Expected: FAIL — 404/405 на новых эндпоинтах, `KeyError: 'permissions'`.

- [ ] **Step 3: Схемы**

`backend/app/schemas/finding_event.py`: в `FindingEventRead` последним полем добавить `actor_name: str | None = None`.

`backend/app/schemas/finding.py`: импорт `from pydantic import BaseModel, Field` → `from pydantic import BaseModel, Field, model_validator`; добавить `from typing import Literal` и `from app.models.decision_request import ReasonTag`. В конец файла:

```python
class CommentCreate(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    # AppSec отвечает на «Нужна помощь» и снимает флаг
    resolve_help: bool = False


class HelpRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class BulkAction(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    action: Literal["confirm", "false_positive", "assign"]
    reason_tag: ReasonTag | None = None
    reason: str | None = Field(default=None, max_length=2000)
    group_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check(self) -> "BulkAction":
        if self.action == "assign" and self.group_id is None:
            raise ValueError("Для назначения укажите команду")
        return self


class BulkSkipped(BaseModel):
    id: uuid.UUID
    reason: str


class BulkResult(BaseModel):
    applied: int
    skipped: list[BulkSkipped]
```

`backend/app/schemas/auth.py`: в `UserRead` последним полем добавить `permissions: list[str] = []`.

- [ ] **Step 4: `/auth/me` в `backend/app/api/auth.py`**

Добавить импорты `from app.api.deps import has_permission` (если `deps` уже импортируется — дополнить список) и `from app.authz.permissions import CATALOG`. В `me` в конструктор `UserRead(...)` добавить аргумент:

```python
        permissions=[
            f"{resource}:{action}"
            for resource, actions in CATALOG.items()
            for action in actions
            if has_permission(principal, resource, action)
        ],
```

- [ ] **Step 5: Эндпоинты в `backend/app/api/findings.py`**

Импорты: `from datetime import datetime, timezone`; `from pydantic import ValidationError`; `from app.models.decision_request import DecisionType`; `from app.schemas.decision import DecisionCreate`; `from app.services.decisions import DecisionError, create_request`; в импорт схем добавить `BulkAction, BulkResult, BulkSkipped, CommentCreate, HelpRequest`.

`list_finding_events` заменить на:

```python
@router.get("/findings/{finding_id}/events", response_model=list[FindingEventRead])
async def list_finding_events(
    finding_id: uuid.UUID,
    _: object = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[FindingEventRead]:
    if await db.get(Finding, finding_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    rows = await db.execute(
        select(FindingEvent, User.full_name, User.email)
        .outerjoin(User, User.id == FindingEvent.actor_id)
        .where(FindingEvent.finding_id == finding_id)
        .order_by(FindingEvent.created_at, FindingEvent.id)
    )
    return [
        FindingEventRead.model_validate(event).model_copy(update={"actor_name": full_name or email})
        for event, full_name, email in rows
    ]
```

В конец файла:

```python
CLOSED_FOR_HELP = {FindingStatus.fixed, *DECISION_STATUSES}


async def _finding_or_404(db: AsyncSession, finding_id: uuid.UUID) -> Finding:
    finding = await db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    return finding


@router.post(
    "/findings/{finding_id}/comments",
    response_model=FindingEventRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    finding_id: uuid.UUID,
    data: CommentCreate,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> FindingEventRead:
    finding = await _finding_or_404(db, finding_id)
    text = data.text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Комментарий пустой")
    if data.resolve_help and not has_permission(principal, "finding", "approve"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Закрыть вопрос может только AppSec (право finding:approve)"
        )
    event = record_event(
        db, finding.id, FindingEventType.comment,
        actor_type=ActorType.user, actor_id=principal.user.id, reason=text,
    )
    if data.resolve_help and finding.help_requested_at is not None:
        finding.help_requested_at = None
        record_event(
            db, finding.id, FindingEventType.help_resolved,
            actor_type=ActorType.user, actor_id=principal.user.id,
        )
    await db.commit()
    await db.refresh(event)
    return FindingEventRead.model_validate(event).model_copy(update={
        "actor_name": principal.user.full_name or principal.user.email,
    })


@router.post("/findings/{finding_id}/help", response_model=FindingDetail)
async def request_help(
    finding_id: uuid.UUID,
    data: HelpRequest,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> FindingDetail:
    finding = await _finding_or_404(db, finding_id)
    if finding.status in CLOSED_FOR_HELP:
        raise HTTPException(status.HTTP_409_CONFLICT, "Уязвимость уже закрыта")
    if finding.help_requested_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Вопрос AppSec уже задан — дождитесь ответа")
    finding.help_requested_at = datetime.now(timezone.utc)
    record_event(
        db, finding.id, FindingEventType.help_requested,
        actor_type=ActorType.user, actor_id=principal.user.id, reason=data.text.strip(),
    )
    await db.commit()
    return await to_detail(db, await load_finding(db, finding.id))


def _first_error(exc: ValidationError) -> str:
    return str(exc.errors()[0]["msg"]).removeprefix("Value error, ")


@router.post("/findings/bulk", response_model=BulkResult)
async def bulk_action(
    data: BulkAction,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> BulkResult:
    decision: DecisionCreate | None = None
    if data.action == "false_positive":
        if not has_permission(principal, "finding", "approve"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Отметить ложным сразу может только AppSec (право finding:approve)",
            )
        try:
            decision = DecisionCreate(
                decision_type=DecisionType.false_positive,
                reason_tag=data.reason_tag,
                reason=data.reason,
            )
        except ValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, _first_error(exc))
    if data.action == "assign" and await db.get(UserGroup, data.group_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Команда не найдена")

    found = {f.id: f for f in await db.scalars(select(Finding).where(Finding.id.in_(data.ids)))}
    applied = 0
    skipped: list[BulkSkipped] = []
    for finding_id in data.ids:
        finding = found.get(finding_id)
        if finding is None:
            skipped.append(BulkSkipped(id=finding_id, reason="Уязвимость не найдена"))
            continue
        if data.action == "confirm":
            if finding.status not in MANUAL_STATUSES:
                skipped.append(BulkSkipped(id=finding_id, reason="Уже закрыта или решена"))
                continue
            if finding.status == FindingStatus.confirmed:
                skipped.append(BulkSkipped(id=finding_id, reason="Уже подтверждена"))
                continue
            previous = finding.status
            finding.status = FindingStatus.confirmed
            record_event(
                db, finding.id, FindingEventType.status_changed,
                actor_type=ActorType.user, actor_id=principal.user.id,
                from_status=previous, to_status=FindingStatus.confirmed,
            )
        elif data.action == "false_positive":
            try:
                await create_request(
                    db, finding, decision, user_id=principal.user.id, can_approve=True
                )
            except DecisionError as exc:
                skipped.append(BulkSkipped(id=finding_id, reason=exc.message))
                continue
        else:
            record_event(
                db, finding.id, FindingEventType.assigned,
                actor_type=ActorType.user, actor_id=principal.user.id,
                payload={
                    "from_group_id": str(finding.assignee_group_id) if finding.assignee_group_id else None,
                    "to_group_id": str(data.group_id),
                    "by_rules": False,
                },
            )
            finding.assignee_group_id = data.group_id
            finding.assigned_manually = True
        applied += 1
    await db.commit()
    return BulkResult(applied=applied, skipped=skipped)
```

(`MANUAL_STATUSES` и `DECISION_STATUSES` уже определены в файле выше — новые эндпоинты должны стоять ниже них.)

- [ ] **Step 6: Тесты**

Run: `cd backend && .venv\Scripts\python -m pytest -q`
Expected: все PASS.

- [ ] **Step 7: Commit**

```bash
git add backend
git commit -m "feat: finding comments, AppSec help requests, bulk triage, permissions in /auth/me"
```

---

### Task 8: Фронтенд — основа: права, клиент, типы, общие компоненты, переводы

**Files:**
- Create: `frontend/src/api/json.ts`, `frontend/src/api/types.ts`, `frontend/src/components/Modal.tsx`, `frontend/src/components/Tabs.tsx`, `frontend/src/components/DecisionDialog.tsx`, `frontend/src/components/ui.ts`
- Modify: `frontend/src/auth/AuthContext.tsx`, `frontend/src/i18n/ru.json`

**Interfaces:**
- Consumes: `UserRead.permissions` (Task 7).
- Produces:
  - `useCan(): (permission: string) => boolean` из `src/auth/AuthContext.tsx` (мемоизирован по пользователю).
  - `apiJson<T>(url, method = "GET", body?) -> Promise<ApiResult<T>>`, `ApiResult<T> = {ok, status, data: T | null, error: string | null}` из `src/api/json.ts`.
  - Типы из `src/api/types.ts`: `Finding`, `FindingDetail`, `FindingEvent`, `Decision`, `Group`, `EntityNode`, `EntitySettings`, `SettingField`, `SettingValue`, `OwnershipRuleRead`, `BulkResult`, `ReasonTag`, константы `REASON_TAGS`, `OPEN_STATUSES`.
  - Компоненты: `Modal({title, onClose, children})`, `Tabs<T>({tabs, value, onChange, label})`, `DecisionDialog({mode, onSubmit, onClose})` + тип `DecisionBody`; из `src/components/ui.ts`: `PRIMARY_BUTTON`, `MONO`, `formatDate`, `formatDateTime`.
  - Ключи `ru.json`: `nav.inbox`, `nav.my`, `common.*` (новые), `vulns.project|includeChildren|allProjects`, разделы `team`, `decision`, `window`, `inbox`, `my`, `settings`.

- [ ] **Step 1: `frontend/src/auth/AuthContext.tsx`**

Первую строку `import { createContext, useCallback, useContext, useEffect, useState } from "react";` оставить как есть. В `interface CurrentUser` после `roles: string[];` добавить:

```ts
  // Права вида "finding:approve" — считает бэкенд (/auth/me), у суперюзера все
  permissions: string[];
```

В конец файла:

```ts
/** Проверка права текущего пользователя, например can("finding:approve"). */
export function useCan(): (permission: string) => boolean {
  const { user } = useAuth();
  return useCallback(
    (permission: string) => !!user && user.permissions.includes(permission),
    [user],
  );
}
```

- [ ] **Step 2: `frontend/src/api/json.ts`**

```ts
import { apiFetch } from "./client";

export interface ApiResult<T> {
  ok: boolean;
  status: number;
  data: T | null;
  /** Текст ошибки из `detail` ответа FastAPI (строка или список ошибок валидации) */
  error: string | null;
}

/** JSON-запрос к API с токеном: разбирает ответ и текст ошибки. Не бросает исключений. */
export async function apiJson<T>(url: string, method = "GET", body?: unknown): Promise<ApiResult<T>> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const res = await apiFetch(url, init).catch(() => null);
  if (!res) return { ok: false, status: 0, data: null, error: null };

  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = text;
  }
  if (res.ok) return { ok: true, status: res.status, data: parsed as T, error: null };

  const detail = (parsed as { detail?: unknown } | null)?.detail;
  let error: string | null = null;
  if (typeof detail === "string") error = detail;
  else if (Array.isArray(detail)) error = detail.map((d: { msg?: string }) => d.msg ?? "").join("; ");
  return { ok: false, status: res.status, data: null, error };
}
```

- [ ] **Step 3: `frontend/src/api/types.ts`**

```ts
import type { Severity } from "../theme/severity";

export const OPEN_STATUSES = ["new", "triaged", "confirmed", "in_progress"];

export const REASON_TAGS = [
  "data_not_user_controlled",
  "test_code",
  "sanitized",
  "dead_code",
  "other",
] as const;
export type ReasonTag = (typeof REASON_TAGS)[number];

export interface GroupBrief {
  id: string;
  name: string;
}

export interface Group extends GroupBrief {
  description: string | null;
  source: string;
  member_count: number;
}

export interface Finding {
  id: string;
  number: number;
  entity_id: string;
  import_id: string | null;
  title: string;
  description: string | null;
  severity: Severity;
  status: string;
  scanner: string;
  rule_id: string | null;
  cwe: string | null;
  file_path: string | null;
  line_start: number | null;
  line_end: number | null;
  scan_scope: string | null;
  commit_sha: string | null;
  fingerprint: string;
  first_seen: string;
  last_seen: string;
  created_at: string;
  assignee_group_id: string | null;
  assignee_user_id: string | null;
  assigned_manually: boolean;
  help_requested_at: string | null;
  assignee_group: GroupBrief | null;
  assignee_user: { id: string; email: string; full_name: string | null } | null;
}

export interface FindingDetail extends Finding {
  entity_name: string;
  entity_path: string;
  code_url: string | null;
  code_url_head: string | null;
  help_text: string | null;
}

export interface FindingEvent {
  id: string;
  event_type: string;
  actor_type: string;
  actor_id: string | null;
  actor_name: string | null;
  from_status: string | null;
  to_status: string | null;
  reason: string | null;
  reason_tag: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Decision {
  id: string;
  finding_id: string;
  finding_number: number | null;
  finding_title: string | null;
  decision_type: "false_positive" | "risk_accepted";
  status: "pending" | "approved" | "rejected" | "expired";
  reason_tag: ReasonTag | null;
  reason: string | null;
  expires_at: string | null;
  requested_by_id: string | null;
  decision_comment: string | null;
  created_at: string;
}

export interface EntityNode {
  id: string;
  name: string;
  slug: string;
  path: string;
  parent_id: string | null;
  description: string | null;
}

export type SettingField =
  | "default_branch"
  | "owner_group_id"
  | "repo_url"
  | "repo_type"
  | "repo_path_prefix";

export interface SettingValue {
  value: string | null;
  source: "manual" | "file" | "inherited" | "unset";
  inherited_from: string | null;
}

export interface OwnershipRuleRead {
  id: string;
  pattern: string;
  group_id: string;
  group_name: string;
  position: number;
  source: string;
}

export interface EntitySettings {
  entity_id: string;
  path: string;
  fields: Record<SettingField, SettingValue>;
  ownership_rules: OwnershipRuleRead[];
  rules_source: "manual" | "file";
  inherited_rules: { entity_path: string; pattern: string; group_id: string; group_name: string }[];
  pinned_fields: string[];
  has_config_file: boolean;
  config_commit_sha: string | null;
  config_applied_at: string | null;
  warnings: string[];
}

export interface BulkResult {
  applied: number;
  skipped: { id: string; reason: string }[];
}
```

- [ ] **Step 4: `frontend/src/components/ui.ts`**

```ts
import type { CSSProperties } from "react";

export const PRIMARY_BUTTON: CSSProperties = {
  background: "var(--accent)",
  color: "var(--on-accent)",
  borderColor: "var(--accent)",
};

export const MONO: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 12,
};

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU");
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}
```

- [ ] **Step 5: `frontend/src/components/Modal.tsx`**

```tsx
import { useEffect } from "react";

/** Модальное окно: закрывается по Esc и клику на фон. */
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0, 0, 0, 0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
        padding: 16,
      }}
    >
      <div
        className="card"
        onClick={(e) => e.stopPropagation()}
        style={{ width: "100%", maxWidth: 520, maxHeight: "90vh", overflow: "auto" }}
      >
        <h2 style={{ marginTop: 0, fontSize: 16 }}>{title}</h2>
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 6: `frontend/src/components/Tabs.tsx`**

```tsx
/** Вкладки-переключатель (очередь AppSec, «Мои уязвимости»). */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--border)", marginBottom: 12 }}
    >
      {tabs.map((tab) => {
        const active = tab.id === value;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.id)}
            style={{
              border: "none",
              borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
              borderRadius: 0,
              background: "transparent",
              color: active ? "var(--accent)" : "var(--text-secondary)",
              padding: "8px 12px",
            }}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 7: `frontend/src/components/DecisionDialog.tsx`**

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { REASON_TAGS, type ReasonTag } from "../api/types";
import { Modal } from "./Modal";
import { PRIMARY_BUTTON } from "./ui";

export interface DecisionBody {
  decision_type: "false_positive" | "risk_accepted";
  reason_tag?: ReasonTag;
  reason?: string;
  expires_at?: string;
}

/**
 * «Ложное срабатывание» (причина из списка) или «Принять риск» (срок + пояснение).
 * onSubmit возвращает текст ошибки или null — тогда окно закрывается.
 */
export function DecisionDialog({
  mode,
  onSubmit,
  onClose,
}: {
  mode: DecisionBody["decision_type"];
  onSubmit: (body: DecisionBody) => Promise<string | null>;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [tag, setTag] = useState<ReasonTag>("data_not_user_controlled");
  const [reason, setReason] = useState("");
  const [expires, setExpires] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reasonRequired = mode === "risk_accepted" || tag === "other";

  const submit = async () => {
    setBusy(true);
    setError(null);
    const text = reason.trim() || undefined;
    const body: DecisionBody =
      mode === "false_positive"
        ? { decision_type: mode, reason_tag: tag, reason: text }
        : { decision_type: mode, reason: text, expires_at: expires ? `${expires}T23:59:59Z` : undefined };
    const err = await onSubmit(body);
    setBusy(false);
    if (err) setError(err);
    else onClose();
  };

  return (
    <Modal title={t(mode === "false_positive" ? "decision.fpTitle" : "decision.riskTitle")} onClose={onClose}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {mode === "false_positive" ? (
          <fieldset style={{ border: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
            <legend style={{ fontSize: 13, marginBottom: 6 }}>{t("decision.reasonTag")}</legend>
            {REASON_TAGS.map((value) => (
              <label key={value} style={{ display: "flex", gap: 8, fontSize: 13, alignItems: "center" }}>
                <input type="radio" name="reason_tag" checked={tag === value} onChange={() => setTag(value)} />
                {t(`decision.tags.${value}`)}
              </label>
            ))}
          </fieldset>
        ) : (
          <label style={{ fontSize: 13 }}>
            {t("decision.expiresAt")}
            <input
              type="date"
              value={expires}
              onChange={(e) => setExpires(e.target.value)}
              style={{ display: "block", marginTop: 4 }}
            />
          </label>
        )}
        <label style={{ fontSize: 13 }}>
          {t(reasonRequired ? "decision.reasonRequired" : "decision.reasonOptional")}
          <textarea
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            style={{ display: "block", width: "100%", marginTop: 4, boxSizing: "border-box" }}
          />
        </label>
        {error && (
          <p role="alert" style={{ color: "var(--sev-critical)", margin: 0, fontSize: 13 }}>
            {error}
          </p>
        )}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose}>{t("common.cancel")}</button>
          <button onClick={submit} disabled={busy || (reasonRequired && !reason.trim())} style={PRIMARY_BUTTON}>
            {t("decision.submit")}
          </button>
        </div>
      </div>
    </Modal>
  );
}
```

- [ ] **Step 8: Переводы `frontend/src/i18n/ru.json`**

В `nav` после `"imports": "Импорты",` добавить:

```json
    "inbox": "Очередь AppSec",
    "my": "Мои уязвимости",
```

В `vulns` после `"number": "№",` добавить:

```json
    "project": "Проект",
    "allProjects": "Все проекты",
    "includeChildren": "Включая вложенные",
```

В `common` после `"loading": "Загрузка…",` добавить:

```json
    "cancel": "Отмена",
    "save": "Сохранить",
    "saved": "Сохранено",
    "forbidden": "Недостаточно прав",
    "notFound": "Не найдено",
    "copyLink": "Скопировать ссылку",
    "copied": "Ссылка скопирована",
    "none": "—",
```

Перед разделом `"auth": {` добавить разделы:

```json
  "team": {
    "label": "Команда",
    "none": "Без владельца",
    "all": "Все команды",
    "manual": "назначена вручную"
  },
  "decision": {
    "fpTitle": "Ложное срабатывание",
    "riskTitle": "Принять риск",
    "reasonTag": "Почему это ложное срабатывание?",
    "reasonRequired": "Пояснение (обязательно)",
    "reasonOptional": "Пояснение (необязательно)",
    "expiresAt": "Риск принят до",
    "submit": "Отправить",
    "pending": "Запрос на рассмотрении",
    "approve": "Одобрить",
    "reject": "Отклонить",
    "rejectComment": "Почему запрос отклонён?",
    "type": {
      "false_positive": "Ложное срабатывание",
      "risk_accepted": "Принятие риска"
    },
    "tags": {
      "data_not_user_controlled": "Данные не приходят от пользователя",
      "test_code": "Тестовый или демо-код",
      "sanitized": "Уже есть проверка или экранирование",
      "dead_code": "Код не используется",
      "other": "Другое"
    }
  },
  "window": {
    "back": "К списку уязвимостей",
    "project": "Проект",
    "where": "Где",
    "openInRepo": "Открыть в репозитории",
    "openHead": "Актуальная версия",
    "howToFix": "Как исправить",
    "noHelp": "Сканер не дал рекомендации — спросите AppSec",
    "fixHint": "Исправили? Уязвимость закроется сама после следующего скана основной ветки.",
    "take": "Беру в работу",
    "falsePositive": "Ложное срабатывание",
    "needHelp": "Нужна помощь AppSec",
    "helpAsked": "Вопрос AppSec задан {{date}}",
    "helpPlaceholder": "Что непонятно? AppSec ответит в комментариях",
    "send": "Отправить",
    "confirm": "Подтвердить",
    "acceptRisk": "Принять риск",
    "reassign": "Переназначить",
    "byRules": "По правилам владения",
    "details": "Подробнее для специалистов",
    "history": "История и комментарии",
    "commentPlaceholder": "Написать комментарий",
    "resolveHelp": "Это ответ на вопрос — снять флаг",
    "addComment": "Добавить",
    "scanner": "Сканер",
    "rule": "Правило",
    "cwe": "CWE",
    "commit": "Коммит",
    "firstSeen": "Впервые обнаружена",
    "lastSeen": "Последний раз",
    "system": "Система",
    "events": {
      "imported": "Обнаружена сканером",
      "status_changed": "Статус изменён",
      "reopened": "Переоткрыта",
      "auto_fixed": "Закрыта автоматически",
      "request_created": "Запрос на решение",
      "request_decided": "Решение по запросу",
      "assigned": "Назначена команде",
      "comment": "Комментарий",
      "help_requested": "Нужна помощь AppSec",
      "help_resolved": "Вопрос закрыт"
    }
  },
  "inbox": {
    "title": "Очередь AppSec",
    "tabs": {
      "new": "Новые",
      "requests": "Запросы на одобрение",
      "questions": "Вопросы от команд",
      "unassigned": "Без владельца"
    },
    "empty": "Здесь пусто — всё разобрано",
    "selected": "Выбрано: {{count}}",
    "confirm": "Подтвердить",
    "falsePositive": "Ложное",
    "assign": "Назначить команде",
    "pickTeam": "Выберите команду",
    "result": "Применено: {{applied}}, пропущено: {{skipped}}",
    "hotkeys": "J/K — вниз/вверх, X — отметить, C — подтвердить, F — ложное, A — назначить, Enter — открыть"
  },
  "my": {
    "title": "Мои уязвимости",
    "tabs": {
      "vulns": "Уязвимости",
      "requests": "Мои запросы"
    },
    "scope": {
      "active": "Подтверждённые и в работе",
      "open": "Все открытые"
    },
    "empty": "Уязвимостей ваших команд нет",
    "noRequests": "Вы ещё не отправляли запросов",
    "requestStatus": {
      "pending": "На рассмотрении",
      "approved": "Одобрен",
      "rejected": "Отклонён",
      "expired": "Истёк"
    }
  },
  "settings": {
    "title": "Настройки проекта",
    "open": "Настройки",
    "back": "К проектам",
    "slug": "Адрес (slug)",
    "defaultBranch": "Основная ветка",
    "owner": "Команда-владелец",
    "repoUrl": "Репозиторий",
    "repoType": "Тип репозитория",
    "repoPrefix": "Подпапка в монорепо",
    "choose": "— не задано —",
    "source": {
      "manual": "вручную",
      "file": "из файла",
      "inherited": "унаследовано от {{from}}",
      "unset": "не задано"
    },
    "revert": "Вернуть к файлу",
    "rules": "Правила владения",
    "rulesHint": "Первое совпавшее правило задаёт команду. Маски: ** — любые папки, * — имя внутри папки.",
    "inheritedRules": "Унаследованные правила",
    "pattern": "Маска пути",
    "addRule": "Добавить правило",
    "saveRules": "Сохранить правила",
    "up": "Выше",
    "down": "Ниже",
    "remove": "Убрать",
    "configFile": "Файл настроек",
    "configApplied": "Применён {{date}}, коммит {{commit}}",
    "noConfig": "Файл настроек ещё не приходил — значения заданы вручную",
    "downloadConfig": "Скачать .secretvuln.yml",
    "reassign": "Переназначить по правилам",
    "reassigned": "Переназначено уязвимостей: {{count}}",
    "repoConflict": "Этот репозиторий уже привязан к другому проекту"
  },
```

- [ ] **Step 9: Проверка**

Run: `cd frontend && npx tsc --noEmit -p . && node -e "JSON.parse(require('fs').readFileSync('src/i18n/ru.json','utf8').replace(/^﻿/,''))" && git diff | grep -E "вЂ|в–|вњ|В·" ; echo done`
Expected: tsc без ошибок, JSON валиден, grep ничего не печатает перед `done`.

- [ ] **Step 10: Commit**

```bash
git add frontend/src
git commit -m "feat(ui): permissions hook, JSON client, shared types, modal/tabs/decision dialog, translations"
```

---

### Task 9: Окно уязвимости `/f/SV-N`

**Files:**
- Create: `frontend/src/pages/FindingWindow.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `GET /findings/by-number/{n}` (`FindingDetail`), `GET /findings/{id}/events`, `GET /findings/{id}/decisions`, `PATCH /findings/{id}`, `POST /findings/{id}/decisions|help|comments|assign`, `POST /decisions/{id}/approve|reject`, `GET /groups`; всё из Task 8.
- Produces: маршрут `/f/:ref` (`SV-123` или `123`).

- [ ] **Step 1: `frontend/src/pages/FindingWindow.tsx`**

```tsx
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { apiJson } from "../api/json";
import { OPEN_STATUSES, type Decision, type FindingDetail, type FindingEvent, type Group } from "../api/types";
import { useCan } from "../auth/AuthContext";
import { DecisionDialog, type DecisionBody } from "../components/DecisionDialog";
import { Modal } from "../components/Modal";
import { SeverityBadge } from "../components/SeverityBadge";
import { MONO, PRIMARY_BUTTON, formatDate, formatDateTime } from "../components/ui";

const SECTION = { marginBottom: 16 } as const;
const MUTED = { color: "var(--text-muted)" } as const;

export function FindingWindow() {
  const { ref = "" } = useParams();
  const number = Number(ref.replace(/^SV-/i, ""));
  const { t } = useTranslation();
  const can = useCan();
  const [finding, setFinding] = useState<FindingDetail | null>(null);
  const [events, setEvents] = useState<FindingEvent[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"false_positive" | "risk_accepted" | "help" | null>(null);
  const [helpText, setHelpText] = useState("");
  const [comment, setComment] = useState("");
  const [resolveHelp, setResolveHelp] = useState(false);

  const load = useCallback(async () => {
    if (!Number.isInteger(number) || number <= 0) {
      setLoadError(t("common.notFound"));
      return;
    }
    const res = await apiJson<FindingDetail>(`/api/v1/findings/by-number/${number}`);
    if (!res.ok || !res.data) {
      setLoadError(
        res.status === 404 ? t("common.notFound") : res.status === 403 ? t("common.forbidden") : t("common.error"),
      );
      return;
    }
    const found = res.data;
    setFinding(found);
    const [ev, dec] = await Promise.all([
      apiJson<FindingEvent[]>(`/api/v1/findings/${found.id}/events`),
      apiJson<Decision[]>(`/api/v1/findings/${found.id}/decisions`),
    ]);
    setEvents(ev.data ?? []);
    setDecisions(dec.data ?? []);
  }, [number, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const canTriage = can("finding:triage");
  const canApprove = can("finding:approve");
  const canAssign = canTriage && can("group:read");
  useEffect(() => {
    if (canAssign) void apiJson<Group[]>("/api/v1/groups").then((r) => setGroups(r.data ?? []));
  }, [canAssign]);

  if (loadError) return <p style={MUTED}>{loadError}</p>;
  if (!finding) return <p style={MUTED}>{t("common.loading")}</p>;

  const base = `/api/v1/findings/${finding.id}`;
  const isOpen = OPEN_STATUSES.includes(finding.status);
  const pending = decisions.find((d) => d.status === "pending") ?? null;

  const act = async (request: Promise<{ ok: boolean; error: string | null }>) => {
    setMessage(null);
    const res = await request;
    if (!res.ok) setMessage(res.error ?? t("common.error"));
    await load();
  };
  const setStatus = (status: string) => void act(apiJson(base, "PATCH", { status }));
  const submitDecision = async (body: DecisionBody) => {
    const res = await apiJson(`${base}/decisions`, "POST", body);
    if (!res.ok) return res.error ?? t("common.error");
    await load();
    return null;
  };
  const submitHelp = async () => {
    setDialog(null);
    await act(apiJson(`${base}/help`, "POST", { text: helpText.trim() }));
    setHelpText("");
  };
  const addComment = async () => {
    await act(apiJson(`${base}/comments`, "POST", { text: comment.trim(), resolve_help: resolveHelp }));
    setComment("");
    setResolveHelp(false);
  };
  const reassign = (value: string) => {
    if (!value) return;
    void act(apiJson(`${base}/assign`, "POST", value === "__rules" ? { by_rules: true } : { group_id: value }));
  };
  const decide = async (decision: Decision, approve: boolean) => {
    if (approve) {
      await act(apiJson(`/api/v1/decisions/${decision.id}/approve`, "POST", { comment: null }));
      return;
    }
    const reason = window.prompt(t("decision.rejectComment"));
    if (!reason?.trim()) return;
    await act(apiJson(`/api/v1/decisions/${decision.id}/reject`, "POST", { comment: reason.trim() }));
  };
  const copyLink = async () => {
    await navigator.clipboard
      .writeText(`${window.location.origin}/f/SV-${finding.number}`)
      .catch(() => undefined);
    setMessage(t("common.copied"));
  };

  const location = finding.file_path
    ? `${finding.file_path}${finding.line_start ? `:${finding.line_start}` : ""}`
    : t("common.none");

  return (
    <div style={{ maxWidth: 900 }}>
      <Link to="/vulnerabilities" style={{ fontSize: 12 }}>
        ← {t("window.back")}
      </Link>

      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", margin: "12px 0 4px" }}>
        <SeverityBadge severity={finding.severity} />
        <span style={MONO}>SV-{finding.number}</span>
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{t(`status.${finding.status}`)}</span>
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
          {t("team.label")}: {finding.assignee_group?.name ?? t("team.none")}
          {finding.assigned_manually && ` (${t("team.manual")})`}
        </span>
        <span style={{ fontSize: 12, ...MUTED }}>
          {t("window.project")}: {finding.entity_path}
        </span>
        <button onClick={copyLink} style={{ marginLeft: "auto", fontSize: 12 }}>
          {t("common.copyLink")}
        </button>
      </div>

      <h1 style={{ marginTop: 4 }}>{finding.title}</h1>
      {finding.description && finding.description !== finding.title && (
        <p style={{ color: "var(--text-secondary)", whiteSpace: "pre-wrap" }}>{finding.description}</p>
      )}
      {message && (
        <p role="status" style={{ fontSize: 13, color: "var(--accent)" }}>
          {message}
        </p>
      )}

      <section className="card" style={SECTION}>
        <div className="section-label">{t("window.where")}</div>
        <div style={MONO}>{location}</div>
        {(finding.code_url || finding.code_url_head) && (
          <div style={{ display: "flex", gap: 12, marginTop: 8, fontSize: 13 }}>
            {finding.code_url && (
              <a href={finding.code_url} target="_blank" rel="noopener noreferrer">
                {t("window.openInRepo")}
              </a>
            )}
            {finding.code_url_head && (
              <a href={finding.code_url_head} target="_blank" rel="noopener noreferrer">
                {t("window.openHead")}
              </a>
            )}
          </div>
        )}
      </section>

      <section className="card" style={SECTION}>
        <div className="section-label">{t("window.howToFix")}</div>
        <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{finding.help_text ?? t("window.noHelp")}</p>
        {isOpen && <p style={{ fontSize: 12, ...MUTED, marginBottom: 0 }}>{t("window.fixHint")}</p>}
      </section>

      {pending && (
        <section className="card" style={SECTION}>
          <div className="section-label">{t("decision.pending")}</div>
          <p style={{ margin: "0 0 8px" }}>
            {t(`decision.type.${pending.decision_type}`)}
            {pending.reason_tag && ` — ${t(`decision.tags.${pending.reason_tag}`)}`}
            {pending.expires_at && ` — ${t("decision.expiresAt")} ${formatDate(pending.expires_at)}`}
          </p>
          {pending.reason && <p style={{ whiteSpace: "pre-wrap" }}>{pending.reason}</p>}
          {canApprove && (
            <div style={{ display: "flex", gap: 8 }}>
              <button style={PRIMARY_BUTTON} onClick={() => void decide(pending, true)}>
                {t("decision.approve")}
              </button>
              <button onClick={() => void decide(pending, false)}>{t("decision.reject")}</button>
            </div>
          )}
        </section>
      )}

      {canTriage && isOpen && (
        <section style={{ ...SECTION, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {finding.status !== "in_progress" && (
            <button style={PRIMARY_BUTTON} onClick={() => setStatus("in_progress")}>
              {t("window.take")}
            </button>
          )}
          {canApprove && ["new", "triaged"].includes(finding.status) && (
            <button onClick={() => setStatus("confirmed")}>{t("window.confirm")}</button>
          )}
          {!pending && <button onClick={() => setDialog("false_positive")}>{t("window.falsePositive")}</button>}
          {canApprove && !pending && (
            <button onClick={() => setDialog("risk_accepted")}>{t("window.acceptRisk")}</button>
          )}
          {finding.help_requested_at ? (
            <span style={{ fontSize: 12, ...MUTED }}>
              {t("window.helpAsked", { date: formatDateTime(finding.help_requested_at) })}
            </span>
          ) : (
            <button onClick={() => setDialog("help")}>{t("window.needHelp")}</button>
          )}
          {canAssign && groups.length > 0 && (
            <select
              value=""
              onChange={(e) => reassign(e.target.value)}
              aria-label={t("window.reassign")}
              style={{ fontSize: 12 }}
            >
              <option value="">{t("window.reassign")}…</option>
              <option value="__rules">{t("window.byRules")}</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          )}
        </section>
      )}

      <section className="card" style={SECTION}>
        <div className="section-label">{t("window.history")}</div>
        <ol style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          {events.map((ev) => (
            <li key={ev.id} style={{ fontSize: 13, borderLeft: "2px solid var(--border)", paddingLeft: 10 }}>
              <div style={{ fontSize: 12, ...MUTED }}>
                {formatDateTime(ev.created_at)} · {ev.actor_name ?? t("window.system")} ·{" "}
                {t(`window.events.${ev.event_type}`)}
                {ev.from_status && ev.to_status && ` · ${t(`status.${ev.from_status}`)} → ${t(`status.${ev.to_status}`)}`}
                {!ev.from_status && ev.to_status && ` · ${t(`status.${ev.to_status}`)}`}
              </div>
              {ev.reason && <div style={{ whiteSpace: "pre-wrap" }}>{ev.reason}</div>}
            </li>
          ))}
        </ol>
        {canTriage && (
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
            <textarea
              rows={2}
              value={comment}
              placeholder={t("window.commentPlaceholder")}
              aria-label={t("window.commentPlaceholder")}
              onChange={(e) => setComment(e.target.value)}
              style={{ width: "100%", boxSizing: "border-box" }}
            />
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              {canApprove && finding.help_requested_at && (
                <label style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "center" }}>
                  <input type="checkbox" checked={resolveHelp} onChange={(e) => setResolveHelp(e.target.checked)} />
                  {t("window.resolveHelp")}
                </label>
              )}
              <button onClick={addComment} disabled={!comment.trim()} style={{ marginLeft: "auto" }}>
                {t("window.addComment")}
              </button>
            </div>
          </div>
        )}
      </section>

      <details className="card" style={SECTION}>
        <summary style={{ cursor: "pointer" }}>{t("window.details")}</summary>
        <dl
          style={{
            display: "grid",
            gridTemplateColumns: "max-content 1fr",
            gap: "4px 16px",
            fontSize: 13,
            margin: "12px 0 0",
          }}
        >
          <dt>{t("window.scanner")}</dt>
          <dd style={{ margin: 0 }}>{finding.scanner}</dd>
          <dt>{t("window.rule")}</dt>
          <dd style={{ margin: 0, ...MONO }}>{finding.rule_id ?? t("common.none")}</dd>
          <dt>{t("window.cwe")}</dt>
          <dd style={{ margin: 0 }}>{finding.cwe ?? t("common.none")}</dd>
          <dt>{t("window.commit")}</dt>
          <dd style={{ margin: 0, ...MONO }}>{finding.commit_sha?.slice(0, 12) ?? t("common.none")}</dd>
          <dt>{t("window.firstSeen")}</dt>
          <dd style={{ margin: 0 }}>{formatDateTime(finding.first_seen)}</dd>
          <dt>{t("window.lastSeen")}</dt>
          <dd style={{ margin: 0 }}>{formatDateTime(finding.last_seen)}</dd>
        </dl>
      </details>

      {(dialog === "false_positive" || dialog === "risk_accepted") && (
        <DecisionDialog mode={dialog} onSubmit={submitDecision} onClose={() => setDialog(null)} />
      )}
      {dialog === "help" && (
        <Modal title={t("window.needHelp")} onClose={() => setDialog(null)}>
          <textarea
            rows={4}
            value={helpText}
            placeholder={t("window.helpPlaceholder")}
            aria-label={t("window.helpPlaceholder")}
            onChange={(e) => setHelpText(e.target.value)}
            style={{ width: "100%", boxSizing: "border-box" }}
          />
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 10 }}>
            <button onClick={() => setDialog(null)}>{t("common.cancel")}</button>
            <button style={PRIMARY_BUTTON} disabled={!helpText.trim()} onClick={submitHelp}>
              {t("window.send")}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Маршрут в `frontend/src/App.tsx`**

Добавить `import { FindingWindow } from "./pages/FindingWindow";` и внутри защищённого `<Route element={<RequireAuth>...}>` после `<Route path="vulnerabilities" .../>`:

```tsx
              <Route path="f/:ref" element={<FindingWindow />} />
```

- [ ] **Step 3: Проверка типов**

Run: `cd frontend && npx tsc --noEmit -p .`
Expected: без ошибок.

- [ ] **Step 4: Проверка в браузере**

Бэкенд и воркер запущены, миграции `0010–0012` применены. Прогнать `powershell -File scripts\smoke-test.ps1`, чтобы были данные. `preview_start` `frontend`, войти под `bob@secretvuln.local` (разработчик), открыть `/f/SV-1`:
- видны критичность, номер, статус, «Команда: …», путь проекта, раздел «Где», «Как исправить», история;
- «Беру в работу» → статус «В работе», в истории событие «Статус изменён»;
- «Нужна помощь AppSec» → окно, текст, «Отправить» → строка «Вопрос AppSec задан …»;
- «Ложное срабатывание» → причина «Тестовый или демо-код» → блок «Запрос на рассмотрении».
Выйти, войти под `alice@secretvuln.local` (AppSec; группа `secops-admins` должна иметь роль «Инженер ИБ» — назначить в «Группы и доступ», если ещё нет): на той же уязвимости видны «Одобрить/Отклонить», галка «Это ответ на вопрос» у комментария, выпадашка «Переназначить». Одобрить запрос → статус «Ложное срабатывание». Консоль браузера без ошибок (`read_console_messages`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(ui): vulnerability window with actions, decisions, help requests and history"
```

---

### Task 10: Очередь AppSec `/inbox`

**Files:**
- Create: `frontend/src/pages/Inbox.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/components/Layout.tsx`

**Interfaces:**
- Consumes: `GET /findings` с `pending_decision`, `help_requested`, `unassigned`, `status`, `order` (Task 6); `POST /findings/bulk` (Task 7); `GET /entities` (`path`, Task 2); `Tabs`, `DecisionDialog`, `useCan` (Task 8).
- Produces: маршрут `/inbox`; пункт меню «Очередь AppSec» (только с правом `finding:approve`); `NAV_ITEMS` с полем `perm`.

- [ ] **Step 1: `frontend/src/pages/Inbox.tsx`**

```tsx
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { apiJson } from "../api/json";
import type { BulkResult, EntityNode, Finding, Group } from "../api/types";
import { DecisionDialog, type DecisionBody } from "../components/DecisionDialog";
import { SeverityBadge } from "../components/SeverityBadge";
import { Tabs } from "../components/Tabs";
import { MONO } from "../components/ui";

type Tab = "new" | "requests" | "questions" | "unassigned";
const TABS: Tab[] = ["new", "requests", "questions", "unassigned"];
const OPEN = "status=new&status=triaged&status=confirmed&status=in_progress";
const QUERIES: Record<Tab, string> = {
  new: "status=new&order=number",
  requests: "pending_decision=true&order=number",
  questions: `help_requested=true&${OPEN}&order=number`,
  unassigned: `unassigned=true&${OPEN}&order=severity`,
};
const CELL = { padding: "8px 12px" } as const;

export function Inbox() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("new");
  const [items, setItems] = useState<Finding[] | null>(null);
  const [cursor, setCursor] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [groups, setGroups] = useState<Group[]>([]);
  const [paths, setPaths] = useState<Record<string, string>>({});
  const [team, setTeam] = useState("");
  const [fpOpen, setFpOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const teamRef = useRef<HTMLSelectElement>(null);

  const load = useCallback(async () => {
    const res = await apiJson<Finding[]>(`/api/v1/findings?${QUERIES[tab]}&limit=200`);
    setItems(res.data ?? []);
    setCursor(0);
    setSelected(new Set());
  }, [tab]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void apiJson<Group[]>("/api/v1/groups").then((r) => setGroups(r.data ?? []));
    void apiJson<EntityNode[]>("/api/v1/entities").then((r) =>
      setPaths(Object.fromEntries((r.data ?? []).map((e) => [e.id, e.path]))),
    );
  }, []);

  // Действие применяется к отмеченным, а если ничего не отмечено — к строке под курсором
  const targets = useMemo(() => {
    if (selected.size > 0) return [...selected];
    const current = items?.[cursor];
    return current ? [current.id] : [];
  }, [selected, items, cursor]);

  const bulk = useCallback(
    async (body: Record<string, unknown>): Promise<string | null> => {
      if (targets.length === 0) return null;
      const res = await apiJson<BulkResult>("/api/v1/findings/bulk", "POST", { ids: targets, ...body });
      if (!res.ok || !res.data) return res.error ?? t("common.error");
      setMessage(t("inbox.result", { applied: res.data.applied, skipped: res.data.skipped.length }));
      await load();
      return null;
    },
    [targets, load, t],
  );

  const confirm = useCallback(async () => {
    const err = await bulk({ action: "confirm" });
    if (err) setMessage(err);
  }, [bulk]);

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (fpOpen || ["INPUT", "TEXTAREA", "SELECT"].includes(tag) || e.ctrlKey || e.metaKey || e.altKey) return;
      const list = items ?? [];
      const key = e.key.toLowerCase();
      if (key === "j") setCursor((c) => Math.min(c + 1, Math.max(list.length - 1, 0)));
      else if (key === "k") setCursor((c) => Math.max(c - 1, 0));
      else if (key === "x" && list[cursor]) toggle(list[cursor].id);
      else if (key === "c") void confirm();
      else if (key === "f") setFpOpen(true);
      else if (key === "a") teamRef.current?.focus();
      else if (e.key === "Enter" && list[cursor]) navigate(`/f/SV-${list[cursor].number}`);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, cursor, fpOpen, confirm, toggle, navigate]);

  const assign = async () => {
    if (!team) return;
    const err = await bulk({ action: "assign", group_id: team });
    if (err) setMessage(err);
    setTeam("");
  };
  const submitFp = (body: DecisionBody) =>
    bulk({ action: "false_positive", reason_tag: body.reason_tag, reason: body.reason });

  return (
    <div>
      <h1>{t("inbox.title")}</h1>
      <Tabs
        label={t("inbox.title")}
        tabs={TABS.map((id) => ({ id, label: t(`inbox.tabs.${id}`) }))}
        value={tab}
        onChange={setTab}
      />

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {t("inbox.selected", { count: targets.length })}
        </span>
        <button onClick={() => void confirm()} disabled={targets.length === 0}>
          {t("inbox.confirm")}
        </button>
        <button onClick={() => setFpOpen(true)} disabled={targets.length === 0}>
          {t("inbox.falsePositive")}
        </button>
        <select ref={teamRef} value={team} onChange={(e) => setTeam(e.target.value)} aria-label={t("inbox.pickTeam")}>
          <option value="">{t("inbox.pickTeam")}</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
        <button onClick={assign} disabled={!team || targets.length === 0}>
          {t("inbox.assign")}
        </button>
        {message && (
          <span role="status" style={{ fontSize: 12, color: "var(--accent)" }}>
            {message}
          </span>
        )}
      </div>
      <p style={{ fontSize: 11, color: "var(--text-muted)", margin: "0 0 8px" }}>{t("inbox.hotkeys")}</p>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {items === null ? (
          <p style={{ padding: 16, margin: 0, color: "var(--text-muted)" }}>{t("common.loading")}</p>
        ) : items.length === 0 ? (
          <p style={{ padding: 16, margin: 0, color: "var(--text-muted)" }}>{t("inbox.empty")}</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <tbody>
              {items.map((f, i) => (
                <tr
                  key={f.id}
                  onClick={() => setCursor(i)}
                  aria-current={i === cursor}
                  style={{
                    borderBottom: "1px solid var(--border)",
                    background: i === cursor ? "var(--accent-bg)" : undefined,
                  }}
                >
                  <td style={{ ...CELL, width: 24 }}>
                    <input
                      type="checkbox"
                      checked={selected.has(f.id)}
                      onChange={() => toggle(f.id)}
                      aria-label={`SV-${f.number}`}
                    />
                  </td>
                  <td style={CELL}>
                    <SeverityBadge severity={f.severity} />
                  </td>
                  <td style={{ ...CELL, ...MONO, whiteSpace: "nowrap" }}>
                    <Link to={`/f/SV-${f.number}`}>SV-{f.number}</Link>
                  </td>
                  <td style={CELL}>
                    <div style={{ fontWeight: 500 }}>{f.title.slice(0, 120)}</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                      {f.scanner} · {paths[f.entity_id] ?? "…"} · {f.assignee_group?.name ?? t("team.none")}
                    </div>
                  </td>
                  <td style={{ ...CELL, fontSize: 12 }}>{t(`status.${f.status}`)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {fpOpen && <DecisionDialog mode="false_positive" onSubmit={submitFp} onClose={() => setFpOpen(false)} />}
    </div>
  );
}
```

- [ ] **Step 2: Маршрут и меню**

`frontend/src/App.tsx`: `import { Inbox } from "./pages/Inbox";` и `<Route path="inbox" element={<Inbox />} />` после маршрута `f/:ref`.

`frontend/src/components/Layout.tsx`: импорт `import { useAuth } from "../auth/AuthContext";` → `import { useAuth, useCan } from "../auth/AuthContext";`. Определение `NAV_ITEMS` заменить на:

```tsx
const NAV_ITEMS: { to: string; key: string; end?: boolean; perm?: string }[] = [
  { to: "/", key: "nav.dashboard", end: true },
  { to: "/my", key: "nav.my" },
  { to: "/inbox", key: "nav.inbox", perm: "finding:approve" },
  { to: "/projects", key: "nav.projects" },
  { to: "/vulnerabilities", key: "nav.vulns" },
  { to: "/imports", key: "nav.imports" },
  { to: "/groups", key: "nav.groups" },
  { to: "/roles", key: "nav.rolesNav" },
];
```

В `Layout()` после `const { user, logout } = useAuth();` добавить `const can = useCan();`; `{NAV_ITEMS.map((item) => (` → `{NAV_ITEMS.filter((item) => !item.perm || can(item.perm)).map((item) => (`; `end={"end" in item && item.end}` → `end={item.end}`.

(Пункт «Мои уязвимости» ведёт на страницу из Task 11; до неё маршрут пуст — это нормально внутри ветки.)

- [ ] **Step 3: Проверка типов**

Run: `cd frontend && npx tsc --noEmit -p .`
Expected: без ошибок.

- [ ] **Step 4: Проверка в браузере**

Под `alice`: в меню есть «Очередь AppSec»; вкладка «Новые» показывает уязвимости smoke-теста; `J`/`K` двигают подсветку, `X` отмечает, `C` подтверждает («Применено: N, пропущено: 0», строки уходят из «Новых»); `F` открывает окно причин, подтверждение ставит «Ложное срабатывание»; выбор команды + «Назначить команде» меняет команду в подписи строки; `Enter` открывает окно уязвимости. Вкладка «Запросы на одобрение» показывает уязвимость, по которой bob запросил «ложное» (Task 9), «Вопросы от команд» — его вопрос. Под `bob` пункта «Очередь AppSec» в меню нет.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(ui): AppSec inbox with tabs, bulk actions and hotkeys"
```

---

### Task 11: «Мои уязвимости» `/my` и список своих запросов

**Files:**
- Create: `frontend/src/pages/MyVulns.tsx`, `backend/tests/test_my_requests.py`
- Modify: `backend/app/api/decisions.py`, `backend/app/schemas/decision.py`, `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `GET /findings?mine=true` (Task 6), `Tabs` (Task 8).
- Produces: `GET /api/v1/decisions?mine=true`; `DecisionRead.finding_number`, `DecisionRead.finding_title`; маршрут `/my`.

- [ ] **Step 1: Падающий тест `backend/tests/test_my_requests.py`**

```python
"""GET /decisions?mine=true — мои запросы с номером и заголовком уязвимости."""

from tests.factories import make_entity, make_finding


async def test_my_requests(client, developer, appsec, db):
    _, dev_h = developer
    _, sec_h = appsec
    f = await make_finding(db, await make_entity(db, "svc"), "fp", title="XSS в шаблоне")
    r = await client.post(
        f"/api/v1/findings/{f.id}/decisions",
        json={"decision_type": "false_positive", "reason_tag": "test_code"},
        headers=dev_h,
    )
    assert r.status_code == 201

    mine = (await client.get("/api/v1/decisions?mine=true", headers=dev_h)).json()
    assert len(mine) == 1
    assert mine[0]["finding_number"] == f.number
    assert mine[0]["finding_title"] == "XSS в шаблоне"

    assert (await client.get("/api/v1/decisions?mine=true", headers=sec_h)).json() == []
    everyone = (await client.get("/api/v1/decisions", headers=sec_h)).json()
    assert everyone[0]["finding_number"] == f.number
```

- [ ] **Step 2: Убедиться, что падает**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_my_requests.py -v`
Expected: FAIL — `KeyError: 'finding_number'`.

- [ ] **Step 3: Бэкенд**

`backend/app/schemas/decision.py`: в `DecisionRead` после `finding_id: uuid.UUID` добавить:

```python
    finding_number: int | None = None
    finding_title: str | None = None
```

`backend/app/api/decisions.py`: убедиться, что импортированы `Principal` (из `app.api.deps`) и `Finding` (из `app.models`); `list_decisions` заменить на:

```python
@router.get("/decisions", response_model=list[DecisionRead])
async def list_decisions(
    decision_status: DecisionStatus | None = Query(None, alias="status"),
    mine: bool = False,
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionRead]:
    q = select(DecisionRequest, Finding.number, Finding.title).join(
        Finding, Finding.id == DecisionRequest.finding_id
    )
    if decision_status:
        q = q.where(DecisionRequest.status == decision_status)
    if mine:
        q = q.where(DecisionRequest.requested_by_id == principal.user.id)
    q = q.order_by(DecisionRequest.created_at.desc()).offset(offset).limit(limit)
    rows = await db.execute(q)
    return [
        DecisionRead.model_validate(req).model_copy(
            update={"finding_number": number, "finding_title": title}
        )
        for req, number, title in rows
    ]
```

(Порядок меняется на «новые сверху»; если тест этапа 1 в `test_decisions.py` полагается на порядок `/decisions`, поправить ожидание в нём.)

Run: `cd backend && .venv\Scripts\python -m pytest -q`
Expected: все PASS.

- [ ] **Step 4: `frontend/src/pages/MyVulns.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { apiJson } from "../api/json";
import type { Decision, Finding } from "../api/types";
import { SeverityBadge } from "../components/SeverityBadge";
import { Tabs } from "../components/Tabs";
import { MONO, formatDate } from "../components/ui";

type Tab = "vulns" | "requests";
const SCOPES = {
  active: "status=confirmed&status=in_progress",
  open: "status=new&status=triaged&status=confirmed&status=in_progress",
} as const;
type Scope = keyof typeof SCOPES;
const CELL = { padding: "8px 12px" } as const;
const EMPTY = { padding: 16, margin: 0, color: "var(--text-muted)" } as const;

export function MyVulns() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("vulns");
  const [scope, setScope] = useState<Scope>("active");
  const [items, setItems] = useState<Finding[] | null>(null);
  const [requests, setRequests] = useState<Decision[] | null>(null);

  useEffect(() => {
    setItems(null);
    void apiJson<Finding[]>(`/api/v1/findings?mine=true&${SCOPES[scope]}&order=severity&limit=200`).then((r) =>
      setItems(r.data ?? []),
    );
  }, [scope]);

  useEffect(() => {
    if (tab === "requests") {
      void apiJson<Decision[]>("/api/v1/decisions?mine=true").then((r) => setRequests(r.data ?? []));
    }
  }, [tab]);

  return (
    <div>
      <h1>{t("my.title")}</h1>
      <Tabs
        label={t("my.title")}
        tabs={[
          { id: "vulns" as Tab, label: t("my.tabs.vulns") },
          { id: "requests" as Tab, label: t("my.tabs.requests") },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === "vulns" ? (
        <>
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value as Scope)}
            aria-label={t("status.label")}
            style={{ marginBottom: 12 }}
          >
            {(Object.keys(SCOPES) as Scope[]).map((s) => (
              <option key={s} value={s}>
                {t(`my.scope.${s}`)}
              </option>
            ))}
          </select>
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            {items === null ? (
              <p style={EMPTY}>{t("common.loading")}</p>
            ) : items.length === 0 ? (
              <p style={EMPTY}>{t("my.empty")}</p>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <tbody>
                  {items.map((f) => (
                    <tr key={f.id} style={{ borderBottom: "1px solid var(--border)" }}>
                      <td style={CELL}>
                        <SeverityBadge severity={f.severity} />
                      </td>
                      <td style={{ ...CELL, ...MONO, whiteSpace: "nowrap" }}>
                        <Link to={`/f/SV-${f.number}`}>SV-{f.number}</Link>
                      </td>
                      <td style={CELL}>
                        <Link to={`/f/SV-${f.number}`} style={{ fontWeight: 500, color: "inherit" }}>
                          {f.title.slice(0, 120)}
                        </Link>
                        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                          {f.assignee_group?.name ?? t("team.none")} · {f.file_path ?? t("common.none")}
                        </div>
                      </td>
                      <td style={{ ...CELL, fontSize: 12 }}>{t(`status.${f.status}`)}</td>
                      <td style={{ ...CELL, fontSize: 12, color: "var(--text-muted)" }}>{formatDate(f.first_seen)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      ) : (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          {requests === null ? (
            <p style={EMPTY}>{t("common.loading")}</p>
          ) : requests.length === 0 ? (
            <p style={EMPTY}>{t("my.noRequests")}</p>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <tbody>
                {requests.map((d) => (
                  <tr key={d.id} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ ...CELL, ...MONO, whiteSpace: "nowrap" }}>
                      {d.finding_number && <Link to={`/f/SV-${d.finding_number}`}>SV-{d.finding_number}</Link>}
                    </td>
                    <td style={CELL}>
                      <div style={{ fontWeight: 500 }}>{d.finding_title}</div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                        {t(`decision.type.${d.decision_type}`)}
                        {d.reason_tag && ` — ${t(`decision.tags.${d.reason_tag}`)}`}
                      </div>
                      {d.decision_comment && <div style={{ fontSize: 12 }}>{d.decision_comment}</div>}
                    </td>
                    <td style={{ ...CELL, fontSize: 12 }}>{t(`my.requestStatus.${d.status}`)}</td>
                    <td style={{ ...CELL, fontSize: 12, color: "var(--text-muted)" }}>{formatDate(d.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Маршрут**

`frontend/src/App.tsx`: `import { MyVulns } from "./pages/MyVulns";` и `<Route path="my" element={<MyVulns />} />` после маршрута `inbox`.

- [ ] **Step 6: Проверка**

Run: `cd frontend && npx tsc --noEmit -p .`
Expected: без ошибок.

Браузер: bob должен состоять в команде, которой назначены уязвимости (в «Группы и доступ» группа `developers` из LDAP — назначить ей несколько уязвимостей через очередь AppSec под alice). Под `bob` → «Мои уязвимости»: видны назначенные подтверждённые/в работе, переключатель «Все открытые» показывает и новые; вкладка «Мои запросы» — запрос из Task 9 со статусом «Одобрен» или «На рассмотрении».

- [ ] **Step 7: Commit**

```bash
git add backend frontend/src
git commit -m "feat: My vulnerabilities page and own decision requests list"
```

---

### Task 12: Настройки проекта

**Files:**
- Create: `frontend/src/pages/ProjectSettings.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/pages/Assets.tsx`

**Interfaces:**
- Consumes: `GET/PATCH /entities/{id}`, `GET/PATCH /entities/{id}/settings`, `PUT /entities/{id}/ownership-rules`, `POST /entities/{id}/settings/unpin`, `GET /entities/{id}/config.yml`, `POST /entities/{id}/reassign` (Tasks 2–5); `apiFetch`; типы и `useCan` (Task 8).
- Produces: маршрут `/projects/:id/settings`; кнопка «Настройки» в дереве проектов.

- [ ] **Step 1: `frontend/src/pages/ProjectSettings.tsx`**

```tsx
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { apiFetch } from "../api/client";
import { apiJson, type ApiResult } from "../api/json";
import type { EntityNode, EntitySettings, Group, SettingField, SettingValue } from "../api/types";
import { useCan } from "../auth/AuthContext";
import { MONO, PRIMARY_BUTTON, formatDateTime } from "../components/ui";

const FIELDS: SettingField[] = ["default_branch", "owner_group_id", "repo_url", "repo_type", "repo_path_prefix"];
const REPO_TYPES = ["gitlab", "github", "gitea", "bitbucket"];
const LABELS: Record<SettingField, string> = {
  default_branch: "settings.defaultBranch",
  owner_group_id: "settings.owner",
  repo_url: "settings.repoUrl",
  repo_type: "settings.repoType",
  repo_path_prefix: "settings.repoPrefix",
};
// Поля репозитория закрепляются и возвращаются к файлу вместе (ключ "repo")
const PIN_OF: Record<SettingField, string> = {
  default_branch: "default_branch",
  owner_group_id: "owner_group_id",
  repo_url: "repo",
  repo_type: "repo",
  repo_path_prefix: "repo",
};
const SHOW_REVERT: SettingField[] = ["default_branch", "owner_group_id", "repo_url"];
const SECTION = { marginBottom: 16 } as const;
const HINT = { fontSize: 11, color: "var(--text-muted)" } as const;

type Draft = Record<SettingField, string>;
interface RuleDraft {
  pattern: string;
  group_id: string;
}

/** Собственное значение узла (не унаследованное) — то, что редактируется. */
function ownValue(v: SettingValue): string {
  return v.source === "manual" || v.source === "file" ? String(v.value ?? "") : "";
}

export function ProjectSettings() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const can = useCan();
  const editable = can("entity:write");
  const [entity, setEntity] = useState<EntityNode | null>(null);
  const [settings, setSettings] = useState<EntitySettings | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [rules, setRules] = useState<RuleDraft[]>([]);
  const [slug, setSlug] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const apply = useCallback((s: EntitySettings) => {
    setSettings(s);
    setDraft(Object.fromEntries(FIELDS.map((f) => [f, ownValue(s.fields[f])])) as Draft);
    setRules(s.ownership_rules.map((r) => ({ pattern: r.pattern, group_id: r.group_id })));
    if (s.warnings.length > 0) setMessage(s.warnings.join("; "));
  }, []);

  const load = useCallback(async () => {
    const [e, s] = await Promise.all([
      apiJson<EntityNode>(`/api/v1/entities/${id}`),
      apiJson<EntitySettings>(`/api/v1/entities/${id}/settings`),
    ]);
    if (!e.ok || !e.data || !s.ok || !s.data) {
      setLoadError(e.status === 404 ? t("common.notFound") : t("common.error"));
      return;
    }
    setEntity(e.data);
    setSlug(e.data.slug);
    apply(s.data);
  }, [id, t, apply]);

  useEffect(() => {
    void load();
  }, [load]);

  const canSeeGroups = can("group:read");
  useEffect(() => {
    if (canSeeGroups) void apiJson<Group[]>("/api/v1/groups").then((r) => setGroups(r.data ?? []));
  }, [canSeeGroups]);

  if (loadError) return <p style={{ color: "var(--text-muted)" }}>{loadError}</p>;
  if (!entity || !settings || !draft) return <p style={{ color: "var(--text-muted)" }}>{t("common.loading")}</p>;

  const base = `/api/v1/entities/${id}`;
  const report = (res: ApiResult<unknown>) =>
    setMessage(res.ok ? t("common.saved") : res.error ?? (res.status === 409 ? t("settings.repoConflict") : t("common.error")));
  const applyResult = (res: ApiResult<EntitySettings>) => {
    report(res);
    if (res.ok && res.data) apply(res.data);
  };

  const saveFields = async () => {
    const changed: Record<string, string | null> = {};
    for (const f of FIELDS) {
      if (draft[f] !== ownValue(settings.fields[f])) changed[f] = draft[f].trim() || null;
    }
    if (Object.keys(changed).length === 0) return;
    applyResult(await apiJson<EntitySettings>(`${base}/settings`, "PATCH", changed));
  };
  const saveSlug = async () => {
    const res = await apiJson<EntityNode>(base, "PATCH", { slug: slug.trim() });
    report(res);
    if (res.ok && res.data) {
      setEntity(res.data);
      await load();
    }
  };
  const saveRules = async () => {
    const body = rules
      .filter((r) => r.pattern.trim() && r.group_id)
      .map((r) => ({ pattern: r.pattern.trim(), group_id: r.group_id }));
    applyResult(await apiJson<EntitySettings>(`${base}/ownership-rules`, "PUT", body));
  };
  const revert = async (field: string) =>
    applyResult(await apiJson<EntitySettings>(`${base}/settings/unpin`, "POST", { field }));
  const reassign = async () => {
    const res = await apiJson<{ reassigned: number }>(`${base}/reassign`, "POST");
    setMessage(res.ok && res.data ? t("settings.reassigned", { count: res.data.reassigned }) : res.error ?? t("common.error"));
  };
  const download = async () => {
    const res = await apiFetch(`${base}/config.yml`);
    if (!res.ok) {
      setMessage(t("common.error"));
      return;
    }
    const url = URL.createObjectURL(await res.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = ".secretvuln.yml";
    link.click();
    URL.revokeObjectURL(url);
  };
  const moveRule = (index: number, delta: number) =>
    setRules((prev) => {
      const target = index + delta;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  const updateRule = (index: number, patch: Partial<RuleDraft>) =>
    setRules((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  const groupName = (groupId: string | null) => groups.find((g) => g.id === groupId)?.name ?? groupId ?? "";
  const sourceLabel = (v: SettingValue) =>
    v.source === "inherited"
      ? t("settings.source.inherited", { from: v.inherited_from })
      : t(`settings.source.${v.source}`);
  const canRevert = (pin: string) => editable && settings.has_config_file && settings.pinned_fields.includes(pin);

  const renderInput = (f: SettingField, v: SettingValue) => {
    const inherited = v.source === "inherited" ? String(v.value ?? "") : "";
    const onChange = (value: string) => setDraft({ ...draft, [f]: value });
    if (f === "owner_group_id" || f === "repo_type") {
      const options = f === "owner_group_id" ? groups.map((g) => ({ value: g.id, label: g.name })) : REPO_TYPES.map((r) => ({ value: r, label: r }));
      const emptyLabel = inherited ? (f === "owner_group_id" ? groupName(inherited) : inherited) : t("settings.choose");
      return (
        <select id={`sv-${f}`} disabled={!editable} value={draft[f]} onChange={(e) => onChange(e.target.value)}>
          <option value="">{emptyLabel}</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      );
    }
    return (
      <input
        id={`sv-${f}`}
        disabled={!editable}
        value={draft[f]}
        placeholder={inherited}
        onChange={(e) => onChange(e.target.value)}
        style={{ minWidth: 280 }}
      />
    );
  };

  return (
    <div style={{ maxWidth: 900 }}>
      <Link to="/projects" style={{ fontSize: 12 }}>
        ← {t("settings.back")}
      </Link>
      <h1 style={{ marginBottom: 4 }}>{entity.name}</h1>
      <div style={{ ...MONO, color: "var(--text-secondary)", marginBottom: 16 }}>{entity.path}</div>
      {message && (
        <p role="status" style={{ fontSize: 13, color: "var(--accent)" }}>
          {message}
        </p>
      )}

      <section className="card" style={SECTION}>
        <div className="section-label">{t("settings.configFile")}</div>
        <p style={{ fontSize: 13, marginTop: 0 }}>
          {settings.has_config_file && settings.config_applied_at
            ? t("settings.configApplied", {
                date: formatDateTime(settings.config_applied_at),
                commit: settings.config_commit_sha?.slice(0, 12) ?? t("common.none"),
              })
            : t("settings.noConfig")}
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button onClick={download}>{t("settings.downloadConfig")}</button>
          {editable && <button onClick={reassign}>{t("settings.reassign")}</button>}
        </div>
      </section>

      <section className="card" style={SECTION}>
        <div className="section-label">{t("settings.title")}</div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(160px, max-content) 1fr",
            gap: "10px 16px",
            alignItems: "center",
          }}
        >
          <label htmlFor="sv-slug" style={{ fontSize: 13 }}>
            {t("settings.slug")}
          </label>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              id="sv-slug"
              disabled={!editable}
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              style={{ ...MONO, minWidth: 200 }}
            />
            {editable && slug !== entity.slug && <button onClick={saveSlug}>{t("common.save")}</button>}
          </div>
          {FIELDS.map((f) => {
            const v = settings.fields[f];
            return (
              <div key={f} style={{ display: "contents" }}>
                <label htmlFor={`sv-${f}`} style={{ fontSize: 13 }}>
                  {t(LABELS[f])}
                </label>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  {renderInput(f, v)}
                  <span style={HINT}>{sourceLabel(v)}</span>
                  {SHOW_REVERT.includes(f) && canRevert(PIN_OF[f]) && (
                    <button style={{ fontSize: 11 }} onClick={() => void revert(PIN_OF[f])}>
                      {t("settings.revert")}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
        {editable && (
          <button style={{ ...PRIMARY_BUTTON, marginTop: 12 }} onClick={saveFields}>
            {t("common.save")}
          </button>
        )}
      </section>

      <section className="card" style={SECTION}>
        <div className="section-label">
          {t("settings.rules")} <span style={HINT}>({t(`settings.source.${settings.rules_source}`)})</span>
        </div>
        <p style={{ ...HINT, fontSize: 12, marginTop: 0 }}>{t("settings.rulesHint")}</p>
        {rules.map((rule, i) => (
          <div key={i} style={{ display: "flex", gap: 6, marginBottom: 6, alignItems: "center" }}>
            <input
              aria-label={t("settings.pattern")}
              placeholder="app/payments/**"
              disabled={!editable}
              value={rule.pattern}
              onChange={(e) => updateRule(i, { pattern: e.target.value })}
              style={{ ...MONO, flex: 1 }}
            />
            <select
              aria-label={t("team.label")}
              disabled={!editable}
              value={rule.group_id}
              onChange={(e) => updateRule(i, { group_id: e.target.value })}
            >
              <option value="">{t("settings.choose")}</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
            {editable && (
              <>
                <button aria-label={t("settings.up")} onClick={() => moveRule(i, -1)}>
                  ↑
                </button>
                <button aria-label={t("settings.down")} onClick={() => moveRule(i, 1)}>
                  ↓
                </button>
                <button aria-label={t("settings.remove")} onClick={() => setRules(rules.filter((_, j) => j !== i))}>
                  ✕
                </button>
              </>
            )}
          </div>
        ))}
        {editable && (
          <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
            <button onClick={() => setRules([...rules, { pattern: "", group_id: "" }])}>+ {t("settings.addRule")}</button>
            <button style={PRIMARY_BUTTON} onClick={saveRules}>
              {t("settings.saveRules")}
            </button>
            {canRevert("ownership_rules") && (
              <button onClick={() => void revert("ownership_rules")}>{t("settings.revert")}</button>
            )}
          </div>
        )}
        {settings.inherited_rules.length > 0 && (
          <>
            <div className="section-label" style={{ marginTop: 16 }}>
              {t("settings.inheritedRules")}
            </div>
            <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
              <tbody>
                {settings.inherited_rules.map((r, i) => (
                  <tr key={i}>
                    <td style={{ ...MONO, padding: "4px 8px 4px 0" }}>{r.pattern}</td>
                    <td style={{ padding: "4px 8px" }}>{r.group_name}</td>
                    <td style={{ padding: "4px 0", color: "var(--text-muted)" }}>{r.entity_path}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Маршрут и ссылка из дерева**

`frontend/src/App.tsx`: `import { ProjectSettings } from "./pages/ProjectSettings";` и `<Route path="projects/:id/settings" element={<ProjectSettings />} />` после `<Route path="projects" .../>`.

`frontend/src/pages/Assets.tsx`: добавить `import { Link } from "react-router-dom";` после импорта `react-i18next`. В строке дерева перед кнопкой `+ {t("projects.addChild")}` вставить:

```tsx
          <Link to={`/projects/${node.id}/settings`} style={{ fontSize: 12, padding: "2px 10px" }}>
            {t("settings.open")}
          </Link>
```

- [ ] **Step 3: Проверка**

Run: `cd frontend && npx tsc --noEmit -p . && git diff | grep -E "вЂ|в–|вњ|В·" ; echo done`
Expected: без ошибок, grep пуст.

Браузер под `admin`: «Проекты» → «Настройки» у проекта smoke-теста:
- задать основную ветку `main`, команду-владельца, репозиторий `https://gitlab.corp/team/app` + тип `gitlab` → «Сохранено», у полей «вручную»;
- у дочернего проекта те же поля показывают «унаследовано от <путь>»;
- добавить правило `app/**` → команда, «Сохранить правила», «Переназначить по правилам» → «Переназначено уязвимостей: N»; в окне уязвимости команда сменилась, появилась ссылка «Открыть в репозитории»;
- «Скачать .secretvuln.yml» сохраняет файл с `owner:` и `ownership:`;
- под `bob` страница открывается, но поля недоступны для правки.

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "feat(ui): project settings page with sources, pinning, ownership rules and config export"
```

---

### Task 13: Таблица «Уязвимости» — команда, проект с вложенными, ссылки в окно

**Files:**
- Modify: `frontend/src/pages/Findings.tsx` (полная замена)

**Interfaces:**
- Consumes: `Finding`, `EntityNode`, `Group`, `apiJson`, `useCan`, `MONO` (Task 8); фильтры `entity_id` + `include_descendants`, `assignee_group_id`, `unassigned` (Tasks 2, 6).

- [ ] **Step 1: Заменить `frontend/src/pages/Findings.tsx` целиком**

```tsx
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { apiJson } from "../api/json";
import type { EntityNode, Finding, Group } from "../api/types";
import { useCan } from "../auth/AuthContext";
import { SeverityBadge } from "../components/SeverityBadge";
import { MONO } from "../components/ui";
import { SEVERITY_ORDER } from "../theme/severity";

const STATUSES = ["new", "triaged", "confirmed", "in_progress", "false_positive", "risk_accepted", "fixed"];
const UNASSIGNED = "__none";
const CELL = { padding: "8px 12px" } as const;
const HEAD = { padding: "8px 12px", fontWeight: 500 } as const;

export function Findings() {
  const { t } = useTranslation();
  const can = useCan();
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [entities, setEntities] = useState<EntityNode[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [severityFilter, setSeverityFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [entityFilter, setEntityFilter] = useState("");
  const [withChildren, setWithChildren] = useState(true);
  const [teamFilter, setTeamFilter] = useState("");

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (severityFilter) params.set("severity", severityFilter);
    if (statusFilter) params.set("status", statusFilter);
    if (entityFilter) {
      params.set("entity_id", entityFilter);
      if (withChildren) params.set("include_descendants", "true");
    }
    if (teamFilter === UNASSIGNED) params.set("unassigned", "true");
    else if (teamFilter) params.set("assignee_group_id", teamFilter);
    params.set("limit", "200");
    void apiJson<Finding[]>(`/api/v1/findings?${params}`).then((r) => setFindings(r.data ?? []));
  }, [severityFilter, statusFilter, entityFilter, withChildren, teamFilter]);

  useEffect(load, [load]);

  useEffect(() => {
    void apiJson<EntityNode[]>("/api/v1/entities").then((r) =>
      setEntities([...(r.data ?? [])].sort((a, b) => a.path.localeCompare(b.path))),
    );
  }, []);

  const canSeeGroups = can("group:read");
  useEffect(() => {
    if (canSeeGroups) void apiJson<Group[]>("/api/v1/groups").then((r) => setGroups(r.data ?? []));
  }, [canSeeGroups]);

  const inputStyle = {
    fontFamily: "inherit",
    fontSize: 13,
    color: "var(--text-primary)",
    background: "var(--bg-page)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius)",
    padding: "6px 10px",
  };

  return (
    <div>
      <h1>{t("vulns.title")}</h1>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <select
          style={{ ...inputStyle, minWidth: 140 }}
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          aria-label={t("severity.label")}
        >
          <option value="">
            {t("severity.label")}: {t("vulns.all")}
          </option>
          {SEVERITY_ORDER.map((sev) => (
            <option key={sev} value={sev}>
              {t(`severity.${sev}`)}
            </option>
          ))}
        </select>
        <select
          style={{ ...inputStyle, minWidth: 160 }}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label={t("status.label")}
        >
          <option value="">
            {t("status.label")}: {t("vulns.all")}
          </option>
          {STATUSES.map((st) => (
            <option key={st} value={st}>
              {t(`status.${st}`)}
            </option>
          ))}
        </select>
        <select
          style={{ ...inputStyle, minWidth: 200 }}
          value={entityFilter}
          onChange={(e) => setEntityFilter(e.target.value)}
          aria-label={t("vulns.project")}
        >
          <option value="">{t("vulns.allProjects")}</option>
          {entities.map((e) => (
            <option key={e.id} value={e.id}>
              {e.path}
            </option>
          ))}
        </select>
        {entityFilter && (
          <label style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={withChildren} onChange={(e) => setWithChildren(e.target.checked)} />
            {t("vulns.includeChildren")}
          </label>
        )}
        <select
          style={{ ...inputStyle, minWidth: 160 }}
          value={teamFilter}
          onChange={(e) => setTeamFilter(e.target.value)}
          aria-label={t("team.label")}
        >
          <option value="">{t("team.all")}</option>
          <option value={UNASSIGNED}>{t("team.none")}</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
        {findings !== null && (
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("vulns.count", { count: findings.length })}</span>
        )}
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {findings === null ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{t("common.loading")}</p>
        ) : findings.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{t("vulns.empty")}</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                <th style={HEAD}>{t("vulns.number")}</th>
                <th style={HEAD}>{t("severity.label")}</th>
                <th style={{ ...HEAD, minWidth: 200 }}>{t("vulns.title")}</th>
                <th style={HEAD}>{t("team.label")}</th>
                <th style={HEAD}>{t("vulns.scanner")}</th>
                <th style={HEAD}>{t("vulns.file")}</th>
                <th style={HEAD}>{t("status.label")}</th>
                <th style={HEAD}>{t("vulns.lastSeen")}</th>
              </tr>
            </thead>
            <tbody>
              {findings.map((f) => (
                <tr key={f.id} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td style={{ ...CELL, ...MONO, whiteSpace: "nowrap" }}>
                    <Link to={`/f/SV-${f.number}`}>SV-{f.number}</Link>
                  </td>
                  <td style={CELL}>
                    <SeverityBadge severity={f.severity} />
                  </td>
                  <td style={CELL}>
                    <Link to={`/f/SV-${f.number}`} style={{ fontWeight: 500, color: "inherit" }}>
                      {f.title.slice(0, 100)}
                    </Link>
                    {f.rule_id && <div style={{ ...MONO, fontSize: 11, color: "var(--text-muted)" }}>{f.rule_id}</div>}
                  </td>
                  <td style={{ ...CELL, fontSize: 12 }}>{f.assignee_group?.name ?? t("team.none")}</td>
                  <td style={CELL}>{f.scanner}</td>
                  <td
                    style={{
                      ...CELL,
                      ...MONO,
                      maxWidth: 250,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {f.file_path ? `${f.file_path}${f.line_start ? `:${f.line_start}` : ""}` : t("common.none")}
                  </td>
                  <td style={{ ...CELL, fontSize: 12 }}>{t(`status.${f.status}`)}</td>
                  <td style={{ ...CELL, color: "var(--text-muted)", fontSize: 12 }}>
                    {new Date(f.last_seen).toLocaleString("ru-RU")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Проверка**

Run: `cd frontend && npx tsc --noEmit -p . && git diff | grep -E "вЂ|в–|вњ|В·" ; echo done`
Expected: без ошибок, grep пуст.

Браузер под `admin`: колонка «Команда»; фильтр по корневому проекту smoke-теста с галкой «Включая вложенные» показывает уязвимости дочернего `svc`, без галки — только собственные; «Без владельца» оставляет строки без команды; клик по номеру или заголовку открывает окно уязвимости.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Findings.tsx
git commit -m "feat(ui): vulnerabilities table with team column, project subtree and team filters, links to window"
```

---

### Task 14: Smoke-тест, документация

**Files:**
- Modify: `scripts/smoke-test.ps1`, `CLAUDE.md`, `frontend/DESIGN.md`

**Interfaces:**
- Consumes: всё выше.

- [ ] **Step 1: `scripts/smoke-test.ps1` (сохранить UTF-8 с BOM)**

В шапке списка шагов добавить строку `#   8. импорт по пути проекта с автосозданием и .secretvuln.yml — проверка владельца`.

В блоке `# --- 0. Проверка сервисов ---` после строки `if ($h.database -ne "up") ...` добавить:

```powershell
    if ($h.storage -ne "up") { Fail "хранилище файлов недоступно ($($h.storage_backend))" }
```

Перед финальной строкой `Write-Host "`nГотово..."` вставить:

```powershell
# --- 8. Импорт по пути: автосоздание проектов + файл настроек + владелец ---
Write-Host "`n== Импорт по пути (auto_create + .secretvuln.yml) ==" -ForegroundColor Cyan
$teamName = "smoke-team"
try {
    Invoke-RestMethod "$api/groups" -Method Post -ContentType "application/json" -Headers $headers `
        -Body (@{ name = $teamName; source = "manual" } | ConvertTo-Json) | Out-Null
    Ok "создана команда $teamName"
} catch { Ok "команда $teamName уже есть" }

$stamp = Get-Date -Format 'HHmmss'
$projectPath = "smoke/run-$stamp/svc"
$cfg = Join-Path $env:TEMP "sv-smoke.secretvuln.yml"
Set-Content -Path $cfg -Encoding ascii -Value "version: 1`ndefault_branch: main`nowner: $teamName`nownership:`n  - path: 'app/**'`n    owner: $teamName"
$resp = curl.exe -s -X POST "$api/imports" -H $authArg `
    -F "file=@$(Join-Path $samples 'semgrep.sarif')" -F "config=@$cfg" `
    -F "project_path=$projectPath" -F "auto_create=true" -F "branch=main" | ConvertFrom-Json
if (-not $resp.id) { Fail "импорт по пути не удался: $($resp | ConvertTo-Json -Compress)" }
if ($resp.created_entities.Count -ne 3) { Fail "ожидали 3 созданных проекта, получили $($resp.created_entities.Count)" }
Ok "проекты созданы: $($resp.created_entities.path -join ', ')"

$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Seconds 2
    $imp = Invoke-RestMethod "$api/imports/$($resp.id)" -Headers $headers
} while ($imp.status -in @("pending", "processing") -and (Get-Date) -lt $deadline)
if ($imp.status -ne "done") { Fail "импорт не обработан: $($imp.status) $($imp.error)" }

$vulns = Invoke-RestMethod "$api/findings?entity_id=$($resp.entity_id)" -Headers $headers
$owned = @($vulns | Where-Object { $_.assignee_group.name -eq $teamName }).Count
if ($owned -eq 0 -or $owned -ne @($vulns).Count) {
    Fail "ожидали, что все $(@($vulns).Count) уязвимостей назначены $teamName, назначено $owned"
}
Ok "владелец назначен: $owned уязвимостей → $teamName"
```

- [ ] **Step 2: Прогон smoke-теста**

Бэкенд и воркер перезапущены на новом коде. Run: `powershell -File scripts\smoke-test.ps1`
Expected: все шаги «✓», в конце «Готово».

- [ ] **Step 3: `frontend/DESIGN.md`**

В таблицу словаря терминов (раздел «Локализация») после строки `| scanner | ... |` добавить:

```markdown
| owner / assignee_group | Команда (нет команды — «Без владельца») |
| .secretvuln.yml   | Файл настроек       |
| inbox             | Очередь AppSec      |
| help request      | Нужна помощь AppSec |
| slug / path       | Адрес проекта       |
```

- [ ] **Step 4: `CLAUDE.md`**

1. В разделе «Стек», строку про файлы заменить на:
   `- **Файлы**: загруженные SARIF — на диске (`SV_STORAGE_PATH`, по умолчанию `backend/data/sarif`) или в S3/MinIO при `SV_STORAGE_BACKEND=s3` (`app/services/storage.py`). MinIO в docker-compose — профиль `s3`, S3 API на порту 9002 (localhost:9000 перехватывает wslrelay.exe)`
2. В «Модель данных», пункт **Entity**, дописать: `slug` (адрес узла, `[a-z0-9._-]`, уникален среди соседей) и `path_cache` (полный путь `fintech/payments/api`, пересчитывается в `app/services/entity_paths.py`); наследуемые настройки `owner_group_id`, `repo_url` (уникален), `repo_type`, `repo_path_prefix`, `default_branch`; `pinned_fields`, `config_file`. Таблица `ownership_rules` (маска → команда, `source` file|manual).
3. После раздела «Пайплайн импорта» добавить раздел:

```markdown
## Владельцы и окна (этап 2 — РЕАЛИЗОВАН)

Спека `docs/superpowers/specs/2026-09-24-stage2-owners-and-screens.md`, план `docs/superpowers/plans/2026-09-24-stage2-owners-and-screens.md`.

- **Адрес проекта**: `GET/PUT /entities/by-path/{path}`; `POST /imports` принимает `entity_id` или `project_path` + `auto_create=true` (нужно право `entity:write`), ответ содержит `entity_path` и `created_entities`. Фильтр `include_descendants` у `/findings` и `/findings/stats`.
- **Файл настроек `.secretvuln.yml`** (`app/services/config_file.py`): CI прикладывает полем `config`; битый файл → 422; неизвестная группа → предупреждение в `imports.config_warnings`. Правка поля в админке закрепляет его (`pinned_fields`), файл его больше не перезаписывает; `POST /entities/{id}/settings/unpin` — «Вернуть к файлу»; `GET /entities/{id}/config.yml` — выгрузка. Применение файла требует `entity:write`.
- **Настройки**: `GET/PATCH /entities/{id}/settings` (значение + источник manual/file/inherited/unset), `PUT /entities/{id}/ownership-rules`, `POST /entities/{id}/reassign`.
- **Владелец уязвимости** (`app/services/ownership.py`): правила узла → правила предков → владелец проекта → «Без владельца». Считается при импорте для новых и открытых незакреплённых (`assigned_manually=false`); `POST /findings/{id}/assign` (группа/человек или `by_rules`).
- **Карточка** `GET /findings/{id}` и `/by-number/{n}` — `FindingDetail` с `entity_path`, `code_url` (коммит), `code_url_head` (основная ветка), `help_text` (SARIF rule.help). Шаблоны ссылок — `app/services/code_links.py`.
- **Совместная работа**: `POST /findings/{id}/comments`, `POST /findings/{id}/help` (флаг `help_requested_at`, снимает AppSec комментарием с `resolve_help`), `POST /findings/bulk` (confirm/false_positive/assign), `GET /decisions?mine=true`. `/auth/me` отдаёт `permissions`, фронтенд проверяет их через `useCan()`.
- **Фильтры `/findings`**: `status` (повторяемый), `mine`, `unassigned`, `assignee_group_id`, `help_requested`, `pending_decision`, `order=last_seen|severity|number`.
- **Экраны**: окно уязвимости `/f/SV-N` (`FindingWindow.tsx`), очередь AppSec `/inbox` (только с `finding:approve`, горячие клавиши J/K/X/C/F/A/Enter), «Мои уязвимости» `/my`, настройки проекта `/projects/:id/settings`; общий клиент `src/api/json.ts`, типы `src/api/types.ts`.
```

4. В «Конвенции» строку про `minio/minio:latest` заменить на: `MinIO нужен только при SV_STORAGE_BACKEND=s3: образ закреплён на minio/minio:RELEASE.2025-07-23T15-54-02Z-cpuv1, запуск docker compose --profile s3 up -d`.
5. В «Статус (...)» заголовок → `## Статус (2026-09-24)`, после абзаца про этап 1 добавить: `**Этап 2 «Владельцы и окна» — сделано**: хранилище на диске, адрес проекта и автосоздание из CI, файл настроек с закреплением полей, команда-владелец по правилам путей, ссылки на код, окно уязвимости, очередь AppSec, «Мои уязвимости», настройки проекта.` Строку «**Дальше:**» заменить на: `**Дальше:** этап 3 «Сроки и метрики» — SLA-политики и due_at, просрочки, «Шумные правила», теги проектов (решено 24.09: теги идут вместе со SLA), метрики на дашборде.`

- [ ] **Step 5: Полная проверка**

Run: `cd backend && .venv\Scripts\python -m pytest -q` и `cd frontend && npx tsc --noEmit -p .`
Expected: все тесты PASS, tsc без ошибок.

- [ ] **Step 6: Commit**

```bash
git add scripts/smoke-test.ps1 CLAUDE.md frontend/DESIGN.md
git commit -m "docs: stage 2 owners and screens; smoke test covers path import, config file and owner"
```
