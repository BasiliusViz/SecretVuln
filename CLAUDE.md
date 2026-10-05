# SecretVuln — минималистичный аналог DefectDojo

Vulnerability management платформа: импорт находок безопасности **только в формате SARIF**, нормализация под разные сканеры, дедупликация, владельцы, процесс разбора, дашборды.

Этот файл грузится в каждую сессию и в каждого агента — держать коротким (до ~150 строк). Подробности подсистем — в `docs/architecture.md`, процедуры и грабли — в скилле `secretvuln-dev`.

## Стек

- **Backend**: Python 3.12+ (venv `backend/.venv`, 3.14), FastAPI, SQLAlchemy 2.0 async (asyncpg) + Alembic (sync, psycopg), PostgreSQL
- **Фоновые задачи**: Redis + ARQ (`app/worker.py`: `process_import`, cron `expire_risks`)
- **Авторизация**: Casbin, роли и права настраиваются в админке; **аутентификация**: local (bcrypt напрямую, НЕ passlib) + LDAP (ldap3, dev — контейнер lldap), JWT (pyjwt)
- **Файлы SARIF**: диск (`SV_STORAGE_PATH`, путь относительный — API и воркер запускать из `backend/`) или S3/MinIO (`SV_STORAGE_BACKEND=s3`, порт 9002)
- **Frontend**: React 19 + TypeScript (Vite 7), react-router 7, react-i18next, Recharts; dev-сервер проксирует /api на :8000
- **Деплой**: docker-compose (dev); Helm — заглушка

## Ключевые решения (не нарушать)

- **Одна сущность Entity («Проект»)** вместо Product/Engagement/Test — дерево-папка без типов и ограничений вложенности. Узел может и содержать детей, и принимать импорты. Адрес — `path_cache` (`fintech/payments/api`), настройки (`owner_group_id`, `repo_url`, `default_branch`…) наследуются вниз.
- **Finding («Уязвимость»)**: дедуп по `(entity_id, fingerprint)`; `raw` JSONB — исходный SARIF result, источник правды. Номер `SV-N`. История — `finding_events` через `record_event`.
- **Процесс**: бэклог только из основной ветки; автозакрытие исчезнувших находок в объёме `(актив, сканер, scan_scope)`; «ложное»/«риск принят» — через `decision_requests` с одобрением правом `finding:approve`.
- **Права**: пользователь → группы → привязки (группа + роль + проект, `NULL` = всё дерево) → casbin-политики роли (ресурс + действие, каталог `app/authz/permissions.py`). Привязка к узлу действует на поддерево. `require_permission` на эндпоинте + `ensure` на объекте (чужое → 404), `Access` из `services/access.py`; `is_superuser` обходит.
- **Группы LDAP** маппятся в веб-интерфейсе, не в конфиге. В env — только подключение к LDAP.
- **AI** (план): отдельная таблица `ai_analyses` (one-to-many к findings), не встраивать выводы в findings.
- **Дашборд**: виджет = JSON `{chart_type, group_by, period, filters}`, generic-агрегаты на бэкенде, ничего не хардкодить под конкретный график.
- **UI только на русском** (`i18n/ru.json`, в компонентах только `t()`), код/API/enum — английские. Severity: цвет + текст + иконка; цвета — из переменных темы (`useSeverityColors`). Подробно — `frontend/DESIGN.md`.

## Карта файлов

Чтобы не искать: где что лежит. Подробные инструкции по запуску, миграциям и
известным граблям — в скилле `secretvuln-dev` (вызывать `/secretvuln-dev`),
команды `/sv-test`, `/sv-stack`, `/sv-smoke`, `/sv-check` (всё сразу).

**Backend (`backend/app/`)**

| Файл | За что отвечает |
|---|---|
| `main.py` | Сборка FastAPI, подключение роутеров, `/api/v1/health` |
| `core/config.py` | Настройки (`SV_*`), `database_url_sync` для Alembic и Casbin |
| `core/security.py` | bcrypt-пароли, JWT (создание и разбор) |
| `db/session.py` | Async engine, зависимость `get_db` |
| `api/deps.py` | `Principal` (с `access`), `get_current_principal`, `require_permission`, `ensure` |
| `api/entities.py` | CRUD дерева проектов, защита от циклов |
| `api/imports.py` | Загрузка SARIF: метаданные CI, проверка ветки |
| `api/findings.py` | Список, статистика, история, поиск по номеру, смена статуса |
| `api/decisions.py` | Запросы «ложное / риск принят», одобрение и отклонение |
| `api/auth.py`, `api/groups.py`, `api/roles.py` | Вход и LDAP, группы, роли и каталог прав |
| `api/bindings.py` | Привязки «группа + роль + проект», делегирование |
| `authz/enforcer.py`, `authz/permissions.py`, `authz/rbac_model.conf` | Casbin: enforcer, каталог прав, модель |
| `models/` | SQLAlchemy: `entity`, `finding`, `finding_event`, `decision_request`, `import_`, `user`, `user_group`, `role` |
| `schemas/` | Pydantic по тем же сущностям |
| `services/import_processing.py` | `apply_import`: создание, дедуп, переоткрытие, автозакрытие |
| `services/access.py` | `Access`: права по поддеревьям, SQL-фильтры видимости |
| `services/entity_tree.py` | Наследование настроек вниз по дереву (`resolve_default_branch`) |
| `services/events.py` | `record_event` — запись истории |
| `services/decisions.py` | Создание, одобрение, отклонение запросов |
| `services/risk_expiry.py` | Истечение принятого риска |
| `services/sarif/` | `parser.py` (разбор + `versionControlProvenance`), `normalizers.py` (severity по сканерам) |
| `services/audit.py` | `record_audit`, `snapshot`/`diff`, белые списки `FIELDS`, список действий |
| `services/storage.py` | Хранилище SARIF: диск или S3/MinIO по `SV_STORAGE_BACKEND` |
| `worker.py` | ARQ: `process_import`, cron `expire_risks` |
| `cli.py` | `create-admin`, `create-user`, `seed-roles` (там же список встроенных ролей) |
| `tests/conftest.py`, `tests/factories.py` | Тестовая БД, фикстуры пользователей и клиента, фабрики данных |

**Frontend (`frontend/src/`)**

| Файл | За что отвечает |
|---|---|
| `App.tsx` | Маршруты, гард авторизации, `ThemeProvider` |
| `components/Layout.tsx` | Сайдбар, переключатель тем, пользователь |
| `theme/global.css` | Пять тем (`data-theme`), базовые стили |
| `theme/themes.ts`, `theme/ThemeContext.tsx` | Список тем и их состояние |
| `theme/severity.ts` | Цвета критичности из переменных темы (`useSeverityColors`) |
| `i18n/ru.json` | **Все строки интерфейса** |
| `pages/` | `Dashboard`, `Assets` (раздел «Проекты»), `Findings` (раздел «Уязвимости»), `Imports`, `Groups`, `Roles`, `Audit` (журнал аудита), `Login` |
| `components/AuditTable.tsx` | Таблица журнала: раскрытие изменений, пагинация (страница `/audit` и вкладка проекта) |
| `api/client.ts` | `apiFetch`: Bearer-токен, редирект на логин при 401 |

**UI-тесты и проверка всего (`frontend/e2e/`, `scripts/`)**

| Файл | За что отвечает |
|---|---|
| `scripts/check-all.ps1` | pytest → build → e2e, итоговая таблица (`/sv-check`) |
| `scripts/e2e.ps1` | Изолированный стенд (БД `secretvuln_e2e`, API :8001, Vite :5174) + `playwright test` |
| `frontend/playwright.config.ts` | Chrome, `workers: 1`, без ретраев, трейсы упавших |
| `e2e/api.ts`, `e2e/i18n.ts`, `e2e/global-setup.ts` | Данные через API, строки из `ru.json`, вход админа |
| `e2e/*.spec.ts` | Сценарии: вход, проекты, импорт, окно SV-N, решения, доступ, аудит, все страницы |

## Конвенции

- Все env-переменные с префиксом `SV_` (см. backend/.env.example)
- API под `/api/v1`, Swagger — `/api/docs`
- Модели: UUID PK (`UUIDPKMixin`), created_at/updated_at (`TimestampMixin`), enum'ы — Python `str, enum.Enum` + PG native enum
- Alembic использует sync-драйвер psycopg (URL выводится из async URL в `config.database_url_sync`); новые модели импортировать в `app/models/__init__.py`, иначе autogenerate их не увидит
- Миграции: `cd backend && alembic upgrade head`; тесты: `/sv-test`; всё сразу (pytest + build + UI): `/sv-check`; стенд: `/sv-stack`
- MinIO нужен только при SV_STORAGE_BACKEND=s3: образ закреплён на minio/minio:RELEASE.2025-07-23T15-54-02Z-cpuv1, запуск docker compose --profile s3 up -d


## Статус (2026-10-05)

- **Этапы 1–2** — в `main`, запушены в `github.com/BasiliusViz/SecretVuln`. **Этап 3 «Сроки и метрики»** — сделан и прошёл ревью, в `main`, запушен: SLA-политики и `due_at`, теги проектов, просрочки, «Шумные правила», метрики на дашборде (`POST /metrics/aggregate`).
- Метрики `resolved`/`mttr_days` считаются по `finding_events` (переход открытый → закрытый), переоткрытие их не стирает.
- **Этап 4 «Права на поддерево»** — сделан, прошёл ревью, в `main`: привязки группа+роль+проект (`role_bindings`), заглушки предков в дереве, делегирование `access:manage`, `sla:assign`, вкладка проекта «Доступ». Подробно — `docs/architecture.md`, раздел «Авторизация».
- **Этап 5а «Журнал аудита»** — сделан, прошёл ревью, в `main`: `audit_log` + `record_audit`, `GET /audit` с правом `audit:read` на поддерево, сторож покрытия мутаций, страница `/audit`, вкладка проекта «Журнал», «Загрузил» в импортах. Подробно — `docs/architecture.md`, раздел «Журнал аудита».
- **UI-тесты** — сделаны: Playwright, 11 тестов в 8 файлах на изолированном стенде, `scripts/check-all.ps1` / `/sv-check` проверяет всё одной командой. **Дальше**: обсуждать AI-разбор (`docs/proposals/`).
- **Отложено, пока не попросят**: Helm/деплой (Dockerfile ещё нет — понадобятся при первом реальном деплое), конструктор дашборд-виджетов — `docs/superpowers/specs/2026-10-05-stage6-dashboard-widgets.md`.

## Документы

- `docs/testing.md` — тесты: `check-all`, UI-тесты на Playwright, как писать новые
- `docs/architecture.md` — подробно по подсистемам: модель данных, импорт, владельцы, auth/LDAP, группы, Casbin, история проекта
- `docs/superpowers/specs/` — спеки этапов; `docs/superpowers/plans/` — планы
- `docs/proposals/` — исследования (процесс разбора, хранилище для ИИ, дерево и API)
- `frontend/DESIGN.md` — дизайн, словарь терминов, переводы enum'ов

## Как работаем над этапом (экономия токенов)

1. **Одна основная сессия (Opus) пишет код сама.** Субагентов-исполнителей не заводим. Большой этап — две сессии (бэкенд → фронтенд), между ними короткая записка в `docs/`.
2. **План короткий**: задача — одна строка + файлы, без кода.
3. **Поиск шире 2–3 файлов** — через Explore (Haiku), чтобы мусор поиска не копился в основном контексте.
4. **Ревью одно на этап**: агент `sv-reviewer` по диффу этапа. Исправления — в основной сессии, перепроверка — тем же ревьюером через `SendMessage`.
5. **Тесты** — `/sv-test` (вывод уже сжат: `-q --tb=short`).
6. В конце этапа — замер расхода (`/usage`) и запись в память.
