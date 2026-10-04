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
- **Права**: пользователь → группы → роли → casbin-политики (ресурс + действие, каталог `app/authz/permissions.py`). `require_permission` на каждом эндпоинте, `is_superuser` обходит. Права пока глобальные (фаза 2 — поддеревья).
- **Группы LDAP** маппятся в веб-интерфейсе, не в конфиге. В env — только подключение к LDAP.
- **AI** (план): отдельная таблица `ai_analyses` (one-to-many к findings), не встраивать выводы в findings.
- **Дашборд**: виджет = JSON `{chart_type, group_by, period, filters}`, generic-агрегаты на бэкенде, ничего не хардкодить под конкретный график.
- **UI только на русском** (`i18n/ru.json`, в компонентах только `t()`), код/API/enum — английские. Severity: цвет + текст + иконка; цвета — из переменных темы (`useSeverityColors`). Подробно — `frontend/DESIGN.md`.

## Карта файлов

Чтобы не искать: где что лежит. Подробные инструкции по запуску, миграциям и
известным граблям — в скилле `secretvuln-dev` (вызывать `/secretvuln-dev`),
команды `/sv-test`, `/sv-stack`, `/sv-smoke`.

**Backend (`backend/app/`)**

| Файл | За что отвечает |
|---|---|
| `main.py` | Сборка FastAPI, подключение роутеров, `/api/v1/health` |
| `core/config.py` | Настройки (`SV_*`), `database_url_sync` для Alembic и Casbin |
| `core/security.py` | bcrypt-пароли, JWT (создание и разбор) |
| `db/session.py` | Async engine, зависимость `get_db` |
| `api/deps.py` | `Principal`, `get_current_principal`, `has_permission`, `require_permission` |
| `api/entities.py` | CRUD дерева проектов, защита от циклов |
| `api/imports.py` | Загрузка SARIF: метаданные CI, проверка ветки |
| `api/findings.py` | Список, статистика, история, поиск по номеру, смена статуса |
| `api/decisions.py` | Запросы «ложное / риск принят», одобрение и отклонение |
| `api/auth.py`, `api/groups.py`, `api/roles.py` | Вход и LDAP, группы, роли и каталог прав |
| `authz/enforcer.py`, `authz/permissions.py`, `authz/rbac_model.conf` | Casbin: enforcer, каталог прав, модель |
| `models/` | SQLAlchemy: `entity`, `finding`, `finding_event`, `decision_request`, `import_`, `user`, `user_group`, `role` |
| `schemas/` | Pydantic по тем же сущностям |
| `services/import_processing.py` | `apply_import`: создание, дедуп, переоткрытие, автозакрытие |
| `services/entity_tree.py` | Наследование настроек вниз по дереву (`resolve_default_branch`) |
| `services/events.py` | `record_event` — запись истории |
| `services/decisions.py` | Создание, одобрение, отклонение запросов |
| `services/risk_expiry.py` | Истечение принятого риска |
| `services/sarif/` | `parser.py` (разбор + `versionControlProvenance`), `normalizers.py` (severity по сканерам) |
| `services/storage.py` | Хранилище SARIF: диск или S3/MinIO по `SV_STORAGE_BACKEND` |
| `worker.py` | ARQ: `process_import`, cron `expire_risks` |
| `cli.py` | `create-admin`, `seed-roles` (там же список встроенных ролей) |
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
| `pages/` | `Dashboard`, `Assets` (раздел «Проекты»), `Findings` (раздел «Уязвимости»), `Imports`, `Groups`, `Roles`, `Login` |
| `api/client.ts` | `apiFetch`: Bearer-токен, редирект на логин при 401 |

## Конвенции

- Все env-переменные с префиксом `SV_` (см. backend/.env.example)
- API под `/api/v1`, Swagger — `/api/docs`
- Модели: UUID PK (`UUIDPKMixin`), created_at/updated_at (`TimestampMixin`), enum'ы — Python `str, enum.Enum` + PG native enum
- Alembic использует sync-драйвер psycopg (URL выводится из async URL в `config.database_url_sync`); новые модели импортировать в `app/models/__init__.py`, иначе autogenerate их не увидит
- Миграции: `cd backend && alembic upgrade head`; тесты: `/sv-test`; стенд: `/sv-stack`
- MinIO нужен только при SV_STORAGE_BACKEND=s3: образ закреплён на minio/minio:RELEASE.2025-07-23T15-54-02Z-cpuv1, запуск docker compose --profile s3 up -d


## Статус (2026-10-05)

- **Этапы 1–2** — в `main`, запушены в `github.com/BasiliusViz/SecretVuln`. **Этап 3 «Сроки и метрики»** — сделан и прошёл ревью, в `main`, запушен: SLA-политики и `due_at`, теги проектов, просрочки, «Шумные правила», метрики на дашборде (`POST /metrics/aggregate`).
- Открыто по этапу 3: переоткрытие обнуляет `resolved_at`, поэтому `resolved`/`mttr_days` задним числом теряют прошлые закрытия (по спеке; позже — брать из `finding_events`).
- **Этап 4 «Права на поддерево»** — спека `docs/superpowers/specs/2026-10-05-subtree-access-design.md` (привязки группа+роль+проект, делегирование `access:manage`, `sla:assign`).
- Бэклог MVP: дашборд-виджеты, аудит-лог + `uploaded_by`, Helm chart.

## Документы

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
