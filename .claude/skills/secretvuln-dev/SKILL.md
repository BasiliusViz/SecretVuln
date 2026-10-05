---
name: secretvuln-dev
description: Рабочие процедуры SecretVuln — поднять локальный стенд, прогнать тесты, добавить миграцию или модель, новый эндпоинт, строку интерфейса или тему, плюс известные грабли окружения (MinIO, порт 9002, BOM в .ps1, кеш Vite). Использовать при запуске стенда, отладке окружения и перед изменениями в backend или frontend этого проекта.
---

# Рабочие процедуры SecretVuln

Карта файлов — в `CLAUDE.md`. Здесь то, что нужно целиком и изредка.

## Окружение

- Backend venv: `backend/.venv` (Python 3.14). Запускать как `backend\.venv\Scripts\python`.
- Инфраструктура: `docker compose up -d postgres redis` (+ `minio`, `ldap` при надобности).
- **S3 API на порту 9002**, не 9000: 9000 на этой машине занимает `wslrelay.exe` из WSL.
- Dev-админ: `admin@secretvuln.local` / `Admin12345!` (создаётся `python -m app.cli create-admin`).
- Встроенные роли создаются `python -m app.cli seed-roles` (Наблюдатель, Разработчик, Аудитор, Инженер ИБ, Администратор).

## Поднять стенд

```powershell
docker compose up -d postgres redis
cd backend; .\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000   # окно 1
.\.venv\Scripts\python -m arq app.worker.WorkerSettings               # окно 2
cd ..\frontend; npm run dev                                           # окно 3
```

Или `powershell -File scripts\dev.ps1` — поднимает всё в отдельных окнах.

## Тесты

```powershell
docker compose up -d postgres
docker compose exec postgres createdb -U secretvuln secretvuln_test   # один раз
cd backend; .\.venv\Scripts\python -m pytest -q
```

- Тестовая БД `secretvuln_test` мигрируется автоматически, таблицы чистятся перед каждым тестом.
- Фикстуры: `db`, `client` (с подменой S3 и очереди), `admin`, `appsec`, `developer`, `make_user`, `builtin_policies`.
- Фабрики: `make_entity`, `make_import`, `make_finding`, `make_sarif` (`tests/factories.py`).
- Сквозная проверка пайплайна: `powershell -File scripts\smoke-test.ps1` (нужны поднятые API, воркер и S3).

### Всё сразу и UI-тесты

- **Весь проект:** `powershell -File scripts\check-all.ps1` (или `/sv-check`) — pytest → `npm run build` → UI-тесты, итоговая таблица, код выхода ≠ 0 при падении. Логи шагов — `backend\data\check-logs\`.
- **Только UI-тесты:** `powershell -File scripts\e2e.ps1 [e2e/auth.spec.ts ...]` — аргументы уходят в `playwright test`.
- Стенд изолирован: БД `secretvuln_e2e` (пересоздаётся), Redis `/1`, API :8001, Vite :5174, SARIF в `backend\data\sarif-e2e`, LDAP выключен. Dev-стенд можно не гасить. Логи API/воркера/Vite — `backend\data\e2e-logs\`.
- Учётки стенда — `frontend\e2e\.env.example` (переопределить — `e2e\.env`). Админ входит один раз в `global-setup.ts`. Пользователя без прав каждый тест создаёт себе сам — `createUser()` (CLI `create-user`, работает только при БД `secretvuln_e2e`), роли выдаёт `Api.grant`; общих пользователей между тестами нет.
- Данные тесты создают сами через `e2e/api.ts` с уникальными именами (`uniq`); тексты сверяют через `t()`/`tc()` из `e2e/i18n.ts`, а не захардкоженным русским. Селекторы — роли и подписи; строки дерева проектов — `getByRole("group", { name: <путь> })`.
- Браузер — установленный Chrome (`channel: "chrome"`): скачивание Chromium Playwright здесь падает по таймауту. Пустая `SV_E2E_CHANNEL` — встроенный Chromium.
- Упавший тест: трейс и скриншот в `frontend\playwright-report\` → `cd frontend; npx playwright show-report`. Ретраев нет — флак чинить.
- `e2e/` проверяется `tsc` (`tsconfig.e2e.json`) в составе `npm run build`.

## Новая модель или миграция

1. Модель в `backend/app/models/`, обязательно добавить импорт в `app/models/__init__.py` — иначе Alembic её не увидит.
2. Миграция пишется **вручную** в `backend/migrations/versions/NNNN_описание.py`, нумерация по порядку, `down_revision` — предыдущий номер.
3. Новое значение в существующем PG-enum: `op.execute("ALTER TYPE finding_status ADD VALUE IF NOT EXISTS 'x'")`; удалить значение обратно нельзя, в `downgrade` это отмечается комментарием.
4. Использовать существующий enum в другой таблице: `postgresql.ENUM(name="finding_status", create_type=False)`.
5. Применить: `cd backend && .venv\Scripts\python -m alembic upgrade head`.

## Новый эндпоинт

- Роутер в `app/api/`, префикс `/api/v1`, подключить в `app/main.py`.
- Права: `Depends(require_permission("<ресурс>", "<действие>"))`; каталог допустимых пар — `app/authz/permissions.py`, новые действия добавлять и туда, и в `perm.action` в `frontend/src/i18n/ru.json`, и в встроенные роли в `app/cli.py`.
- Проверка «может ли одобрять» внутри обработчика: `has_permission(principal, "finding", "approve")`.
- Сообщения об ошибках для пользователя — на русском.
- Изменение статуса находки пишется в историю через `record_event`.

## Интерфейс

- **Любая строка** идёт в `frontend/src/i18n/ru.json`, в компонентах только `t()`. Плюрализация — ключи `_one/_few/_many/_other`.
- Термины: «Проекты» (Entity), «Уязвимости» (Finding). Код и API остаются английскими.
- Цвета берутся из переменных темы. Для графиков — `useSeverityColors()`, хардкодить нельзя.
- Новая тема: значения в `theme/global.css` под `[data-theme="id"]` + строка в `theme/themes.ts`. Обязательные токены: `--bg-page`, `--bg-card`, `--bg-sidebar`, `--border`, `--text-primary/secondary/muted`, `--accent`, `--on-accent`, `--accent-bg`, `--grid`, `--glow`, `--sev-*` и пары `--sev-*-bg/text`.
- Проверка сборки: `cd frontend && npm run build` (запускает `tsc -b`).

## Известные грабли

| Симптом | Причина и что делать |
|---|---|
| `pull access denied` на `minio/minio` | MinIO убрал образ с Docker Hub (2026-09). Запускать локальный образ: `docker run -d --name secretvuln-minio-tmp -p 9002:9000 -p 9001:9001 -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin minio/minio:RELEASE.2025-07-23T15-54-02Z-cpuv1 server /data --console-address ":9001"`, бакет `sarif-imports` создать через boto3 |
| Кириллица в `.ps1` превратилась в кракозябры | Файл сохранён без BOM. Пересохранить: `$c=[IO.File]::ReadAllText($p); [IO.File]::WriteAllText($p,$c,[Text.UTF8Encoding]::new($true))` |
| Страница не обновляется, в консоли `does not provide an export named ...` | Vite закешировал версию файла, сохранённую в середине правок. Перезапустить dev-сервер |
| `error reading bcrypt version` | Не подключать passlib: используется `bcrypt` напрямую в `app/core/security.py` |
| LDAP возвращает пустые атрибуты | lldap строг к именам: запрашивать только `cn`, `mail`, `memberof` в нижнем регистре |
| `.ps1` падает на `docker ... 2>&1` с `NativeCommandError` | PS 5.1 + `$ErrorActionPreference = "Stop"` превращает stderr нативной команды в исключение. Не писать `2>&1`, а заворачивать в `cmd /c "... >nul 2>&1"` |
| `UnicodeEncodeError: 'charmap'` из CLI | Вывод Python в пайп идёт в cp1251. Ставить `PYTHONIOENCODING=utf-8` (скрипты e2e/check-all уже ставят) |
| S3 не отвечает на 9000 | Порт занят `wslrelay.exe`, использовать 9002 |

## Документы

- Подсистемы подробно (модель данных, импорт, владельцы, auth/LDAP, группы, Casbin): `docs/architecture.md`
- Спека процесса и ИИ-слоя: `docs/superpowers/specs/2026-09-19-triage-workflow-and-ai-design.md`
- Этапы 1 и 2 (выполнены): спеки и планы в `docs/superpowers/specs/` и `docs/superpowers/plans/`
- Исследования: `docs/proposals/` (процесс разбора, хранилище для ИИ, универсальное дерево и API)
