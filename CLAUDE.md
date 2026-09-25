# SecretVuln — минималистичный аналог DefectDojo

Vulnerability management платформа: импорт находок безопасности **только в формате SARIF**, нормализация под разные сканеры, дедупликация, дашборды.

## Стек

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0 (async, asyncpg) + Alembic (sync, psycopg), PostgreSQL
- **Фоновые задачи**: Redis + ARQ (обработка SARIF-импортов в воркере)
- **Авторизация**: Casbin (pycasbin + casbin-sqlalchemy-adapter) — роли настраиваются из админки, не хардкод
- **Аутентификация**: локальная (email/password + JWT, passlib/bcrypt, pyjwt) и LDAP (ldap3: bind, auto-provisioning, маппинг групп на роли)
- **Файлы**: загруженные SARIF — на диске (`SV_STORAGE_PATH`, по умолчанию `backend/data/sarif`, **путь относительный — API и воркер обязательно запускать из `backend/`**) или в S3/MinIO при `SV_STORAGE_BACKEND=s3` (`app/services/storage.py`). MinIO в docker-compose — профиль `s3`, S3 API на порту 9002 (localhost:9000 перехватывает wslrelay.exe)
- **Frontend**: React 19 + TypeScript (Vite 7), react-router 7, react-i18next, Recharts. Dev-сервер проксирует /api на :8000 (vite.config.ts)
- **Деплой**: docker-compose (dev), Helm chart (K8s, ещё не реализован — deploy/helm/README.md)

## Структура

```
backend/
  app/
    main.py            # FastAPI app, /api/v1/health, Swagger на /api/docs
    core/config.py     # pydantic-settings, env-префикс SV_, см. backend/.env.example
    db/session.py      # async engine + get_db dependency
    models/            # SQLAlchemy 2.0 модели (Mapped/mapped_column)
    schemas/           # Pydantic-схемы (Create/Update/Read)
    api/               # роутеры: entities (CRUD + дерево), imports (upload + список), findings (фильтры + stats)
    services/          # storage.py (диск/S3), sarif/ (parser + normalizers)
    worker.py          # ARQ-воркер: process_import
  migrations/          # Alembic; 0001–0003 написаны вручную (0003: products -> entities)
  pyproject.toml
frontend/
  src/
    theme/severity.ts  # цвета severity для графиков; бейджи — CSS-переменные --sev-* в global.css
    theme/global.css   # светлая/тёмная темы через [data-theme], CSS-переменные
    i18n/ru.json       # ВСЕ строки UI здесь, в компонентах только t()
    components/        # Layout (сайдбар + переключатель темы), SeverityBadge
    pages/             # Dashboard (stats из API), Assets (дерево), Findings (таблица+фильтры), Imports (upload+polling), Roles (заглушка)
deploy/helm/           # заглушка
docker-compose.yml     # postgres:16, redis:7, minio (+minio-init создаёт бакет)
```

## Модель данных

Ключевое решение (обсуждено с пользователем, миграции 0002–0003): **никаких Product/Engagement/Test — одна универсальная сущность Entity («актив»), работает как папка.** У каждой компании своя структура, платформа её не навязывает: Entity может содержать другие Entity и/или принимать результаты сканирования — и то и другое одновременно. Без типов узлов, без ограничений вложенности. В UI раздел называется «Активы».

- **User**: email (unique), hashed_password (NULL для LDAP-пользователей), auth_source enum(local|ldap), ldap_dn, is_superuser
- **Entity** (таблица `entities`): name (unique среди сиблингов: uq_entities_parent_name с NULLS NOT DISTINCT), parent_id (self-FK, ON DELETE CASCADE — удаление сносит поддерево с импортами и находками), description, **custom_fields JSONB**. API `/api/v1/entities` отдаёт плоский список, дерево собирает фронтенд; PATCH parent_id защищён от циклов (`_check_parent` в app/api/entities.py). `slug` (адрес узла, `[a-z0-9._-]`, уникален среди соседей) и `path_cache` (полный путь `fintech/payments/api`, пересчитывается в `app/services/entity_paths.py`); наследуемые настройки `owner_group_id`, `repo_url` (уникален), `repo_type`, `repo_path_prefix`, `default_branch`; `pinned_fields`, `config_file`. Таблица `ownership_rules` (маска → команда, `source` file|manual).
- **Import**: одна загрузка SARIF-файла в конкретный Entity (entity_id). filename, storage_key, scanner (определяется воркером из tool.driver.name), status enum(pending|processing|done|failed), stats JSONB ({"created","updated","duplicates"}), error, finished_at
- **Finding**: нормализованная находка, привязана к Entity (entity_id). severity enum(critical|high|medium|low|info), status enum(new|triaged|confirmed|false_positive|risk_accepted|fixed), scanner, rule_id, cwe, file_path, line_start/end, **fingerprint** (дедуп-ключ), raw JSONB (исходный SARIF result — источник правды для ре-нормализации), first_seen/last_seen. Уникальность: `(entity_id, fingerprint)` — область дедупа = узел, куда идут импорты; одинаковая уязвимость в соседних узлах = две находки
- **Role**: только метаданные для админки (name, description, ldap_group, is_builtin). Сами права и назначения user->role живут в таблице `casbin_rule` (создаётся адаптером Casbin автоматически, НЕ в наших миграциях). `Role.name` должен совпадать с subject в Casbin-политиках

### Дедупликация

Ключ `fingerprint` берётся из SARIF `partialFingerprints` (приоритет: `primaryLocationLineHash`, потом первый доступный ключ); fallback — sha256 от `rule_id + file_path + snippet`. При повторном импорте существующая находка обновляет `last_seen` и `import_id`, счётчик идёт в `Import.stats.duplicates`/`updated`.

### Расширение под AI (не реализовано, планируется Ollama)

Будущая таблица `ai_analyses`: FK на `findings.id`, one-to-many (несколько анализов на находку — разные модели/версии промпта). НЕ встраивать AI-выводы в саму таблицу findings.

## Пайплайн импорта (РЕАЛИЗОВАН, протестирован end-to-end)

1. `POST /api/v1/entities/{id}/imports` (multipart, поле `file`) → файл в хранилище (`app/services/storage.py`, диск или S3 — см. «Файлы» в Стеке), запись Import(pending), ARQ job `process_import` в Redis
2. Воркер (`app/worker.py`, запуск: `python -m arq app.worker.WorkerSettings`): скачивает из S3 → парсит SARIF (`app/services/sarif/parser.py`) → определяет сканер по `runs[].tool.driver.name` → нормализует severity (`app/services/sarif/normalizers.py`) → дедуп по fingerprint → пишет findings, обновляет Import.stats/status. Если ре-импорт видит находку в статусе fixed — переоткрывает в new (счётчик updated)

**Процесс (этап 1, спека docs/superpowers/specs/2026-09-19-triage-workflow-and-ai-design.md):** логика импорта — `app/services/import_processing.py` (`apply_import`), воркер только скачивает и вызывает её. Импорт принимает `branch`, `commit_sha`, `pipeline_url`, `scan_scope`, `close_missing` (по умолчанию true), `confirm_empty`; ветка/коммит также берутся из SARIF `versionControlProvenance`. У актива `default_branch` (наследуется вниз, `app/services/entity_tree.py`) — импорт другой ветки отклоняется. **Автозакрытие**: открытые находки объёма `(актив, сканер, scan_scope)`, которых нет в новом отчёте, → `fixed` (пустой отчёт закрывает только с `confirm_empty`). История — `finding_events` (`app/services/events.py`, `GET /findings/{id}/events`). Номера `findings.number` → `SV-N` (`GET /findings/by-number/{n}`). Статус `in_progress`; `PATCH /findings/{id}` принимает JSON `{status, reason}` и только new/triaged/confirmed/in_progress. «Ложное»/«риск» — `decision_requests` (`POST /findings/{id}/decisions`, `POST /decisions/{id}/approve|reject`): разработчик запрашивает, право `finding:approve` одобряет (у кого оно есть — применяется сразу). Риск принимается со сроком; ARQ cron `expire_risks` (03:00) переоткрывает истёкшие. Встроенная роль «Разработчик».

Нормализаторы: Semgrep, Trivy, Gitleaks (всегда high/critical — секреты), Checkov + Default (level→severity: error=high, warning=medium, note=low). Реестр `_REGISTRY` в normalizers.py, матчинг по подстроке имени драйвера.

API: `GET /api/v1/imports` (все), `GET /api/v1/imports/{id}`, `GET /api/v1/entities/{id}/imports`, `GET /api/v1/findings` (фильтры: entity_id, severity, status, scanner, limit/offset), `GET /api/v1/findings/stats` (total + by_severity + by_status), `PATCH /api/v1/findings/{id}` (JSON-тело `{status, reason}`)

## Владельцы и окна (этап 2 — РЕАЛИЗОВАН)

Спека `docs/superpowers/specs/2026-09-24-stage2-owners-and-screens.md`, план `docs/superpowers/plans/2026-09-24-stage2-owners-and-screens.md`.

- **Адрес проекта**: `GET/PUT /entities/by-path/{path}`; `POST /imports` принимает `entity_id` или `project_path` + `auto_create=true` (нужно право `entity:write`), ответ содержит `entity_path` и `created_entities`. Фильтр `include_descendants` у `/findings` и `/findings/stats`.
- **Файл настроек `.secretvuln.yml`** (`app/services/config_file.py`): CI прикладывает полем `config`; битый файл → 422; неизвестная группа → предупреждение в `imports.config_warnings`. Правка поля в админке закрепляет его (`pinned_fields`), файл его больше не перезаписывает; `POST /entities/{id}/settings/unpin` — «Вернуть к файлу»; `GET /entities/{id}/config.yml` — выгрузка. Применение файла требует `entity:write`.
- **Настройки**: `GET/PATCH /entities/{id}/settings` (значение + источник manual/file/inherited/unset), `PUT /entities/{id}/ownership-rules`, `POST /entities/{id}/reassign`.
- **Владелец уязвимости** (`app/services/ownership.py`): правила узла → правила предков → владелец проекта → «Без владельца». Считается при импорте для новых и открытых незакреплённых (`assigned_manually=false`); `POST /findings/{id}/assign` (группа/человек или `by_rules`).
- **Карточка** `GET /findings/{id}` и `/by-number/{n}` — `FindingDetail` с `entity_path`, `code_url` (коммит), `code_url_head` (основная ветка), `help_text` (SARIF rule.help). Шаблоны ссылок — `app/services/code_links.py`. **Ссылка на код**: свой `repo_url` проекта (унаследованный или свой) всегда в приоритете; SARIF `repositoryUri` из отчёта сканера (`Import.repo_url`) используется, только если у проекта репозитория нет — тогда `repo_type` угадывается по этому URL (`guess_repo_type`), а не берётся из настроек проекта. В обоих случаях URL принимается только со схемой `http(s)` — иначе ссылка не строится (`build_code_url` возвращает `None`); то же ограничение — на `repo_url` в `PATCH /entities/{id}/settings` и в `repo.url` файла `.secretvuln.yml` (422 при нарушении).
- **Совместная работа**: `POST /findings/{id}/comments`, `POST /findings/{id}/help` (флаг `help_requested_at`, снимает AppSec комментарием с `resolve_help`), `POST /findings/bulk` (confirm/false_positive/assign), `GET /decisions?mine=true`. `/auth/me` отдаёт `permissions`, фронтенд проверяет их через `useCan()`.
- **Фильтры `/findings`**: `status` (повторяемый), `mine`, `unassigned`, `assignee_group_id`, `help_requested`, `pending_decision`, `order=last_seen|severity|number`.
- **Экраны**: окно уязвимости `/f/SV-N` (`FindingWindow.tsx`), очередь AppSec `/inbox` (только с `finding:approve`, горячие клавиши J/K/X/C/F/A/Enter), «Мои уязвимости» `/my`, настройки проекта `/projects/:id/settings`; общий клиент `src/api/json.ts`, типы `src/api/types.ts`.

## Аутентификация (РЕАЛИЗОВАНА: local + LDAP)

- Единый эндпоинт `POST /api/v1/auth/login` (`app/api/auth.py`): сначала пробует локального пользователя с паролем (bcrypt), иначе — LDAP (если `ldap_enabled`). Возвращает JWT (`app/core/security.py`, pyjwt HS256). `GET /api/v1/auth/me` — текущий пользователь + роли (роли зашиты в JWT при логине)
- LDAP (`app/services/auth/ldap.py`, ldap3): сервисный bind → поиск по `(mail={email})` → повторный bind под DN пользователя (проверка пароля) → чтение групп из `memberof`. При успехе провижёнинг User (`auth_source=ldap`, `ldap_dn`), группы маппятся на роли через `Role.ldap_group`. **lldap строг к именам атрибутов — запрашивать только `cn`/`mail`/`memberof` в нижнем регистре, имя берём из `cn`**
- Dev-LDAP: контейнер **lldap** в docker-compose (LDAP :3890, веб-UI :17170, admin/adminpassword, база `dc=secretvuln,dc=local`). Сид тестовых юзеров/групп: `python scripts/seed_ldap.py` (alice→secops-admins, bob→developers, carol→auditors, пароль у всех `Passw0rd!`). Дефолты LDAP в `config.py` уже настроены на этот контейнер, `ldap_enabled=True`
- Фронтенд: `src/auth/AuthContext.tsx` (токен в localStorage, `/auth/me` при старте), `src/pages/Login.tsx`, гард маршрутов в `App.tsx` (`RequireAuth` → редирект на `/login`), в Layout — имя пользователя + выход. Форма логина `LoginRequest.email` — обычный `str`, НЕ `EmailStr` (email-validator режет `.local`/`.corp`)
- **API-эндпоинты (entities/findings/imports/groups) пока НЕ защищены** — авторизация ресурсов будет на этапе Casbin
- **Bootstrap-суперадмин**: `cd backend && python -m app.cli create-admin --email ... [--password ...]` (`app/cli.py`) — создаёт/обновляет локального суперюзера (bcrypt-пароль, `is_superuser=True`). Гарантирует вход, даже если LDAP лёг. Dev-админ: `admin@secretvuln.local` / `Admin12345!`
- **Хеширование паролей — `bcrypt` напрямую** (`app/core/security.py`), НЕ passlib: passlib 1.7.4 несовместим с новым bcrypt (`error reading bcrypt version` + падение на self-test). Пароль обрезается до 72 байт (лимит bcrypt)
- JWT-секрет по умолчанию удлинён до ≥32 байт (иначе pyjwt ругается `InsecureKeyLengthWarning`); в проде задать свой через `SV_JWT_SECRET`

## Группы пользователей (РЕАЛИЗОВАНО)

- Модель `UserGroup` (`app/models/user_group.py`, миграция 0004) + M2M `user_group_members`. Поля: `name`, `description`, `source` enum(`manual`|`ldap`), `ldap_group` (CN LDAP-группы для source=ldap, по умолчанию = name), `last_synced_at`. Группа = «кто» (состав), роли/права навесятся отдельно (Casbin)
- **Ручная** группа: состав правится в UI (`POST/DELETE /groups/{id}/members/{user_id}`). **LDAP** группа: состав — зеркало LDAP, ручное редактирование запрещено (400)
- Полная синхронизация `POST /api/v1/groups/{id}/sync` (`app/api/groups.py`): `list_group_members(cn)` в `app/services/auth/ldap.py` ищет `(memberof=cn=<group>,<group_search_base>)`, заводит отсутствующих пользователей (`auth_source=ldap`, без пароля — provisioned), синхронизирует состав (added/removed/provisioned). Ленивая синхронизация при LDAP-логине — `_sync_user_groups` в `app/api/auth.py` (добавляет вошедшего в совпадающие LDAP-группы)
- API: `GET/POST /groups`, `GET/PATCH/DELETE /groups/{id}`, `POST /groups/{id}/sync`, `POST/DELETE /groups/{id}/members/{user_id}`, `GET /users`
- Фронтенд: `src/pages/Groups.tsx` (раздел «Группы и доступ», раньше был `/roles` — Roles.tsx удалён). Таблица групп: бейдж источника, привязка `← ldap_group`, счётчик, кнопка «Синхронизировать», раскрытие состава, для ручных — добавить/убрать участника
- Идея (подтверждена пользователем, аналогия с DefectDojo): маппинг LDAP-групп задаётся **в веб-интерфейсе, не в конфиг-файле**. В env/config остаётся только подключение к LDAP (сервер, bind, base DN); вся бизнес-логика групп — в UI/БД
- Роли навешиваются на группы: M2M `group_roles` (миграция 0005), API `POST/DELETE /groups/{id}/roles/{role_id}`, в UI — бейджи ролей + выпадашка назначения в раскрытой группе

## Авторизация (Casbin — РЕАЛИЗОВАНО, фаза 1: глобальный RBAC)

- **Право = ресурс + действие.** Ресурсы: `entity|finding|import|group|role`. Действия: `read|write|delete|import|triage`. Каталог допустимых пар — `app/authz/permissions.py` (`CATALOG`), матрицу в UI рисуем по нему
- **Casbin** (`app/authz/enforcer.py`): модель `rbac_model.conf` (sub=имя роли, obj, act, wildcard `*`), sync-адаптер `casbin_sqlalchemy_adapter` на `database_url_sync`. Права роли (p-политики) хранятся в таблице `casbin_rule` (создаёт адаптер, НЕ в наших миграциях). enforcer — ленивый синглтон, `enforce()` in-memory
- **Роль**: метаданные в таблице `roles` (name = субъект Casbin), права — casbin p-политики. API `app/api/roles.py`: `GET /permissions/catalog`, CRUD `/roles`, `PUT /roles/{id}/permissions` (полная замена набора). Встроенные роли (`is_builtin`, нельзя удалить/переименовать) сидятся `python -m app.cli seed-roles`: Наблюдатель / Аудитор / Инженер ИБ / Администратор
- **Цепочка прав**: пользователь → группы (`user_group_members`) → роли (`group_roles`) → права (casbin). При логине роли пользователя вычисляются из его групп (`_roles_for_user` в `app/api/auth.py`) и кладутся в JWT (`roles`)
- **Enforcement**: `require_permission(resource, action)` в `app/api/deps.py` (FastAPI-зависимость на каждом эндпоинте). `is_superuser` обходит проверки. Нет токена → 401, нет права → 403. Закрыты entities/findings/imports/groups/roles
- **Фронтенд**: `src/api/client.ts` (`apiFetch` шлёт Bearer, на 401 → редирект на логин) — все страницы переведены на него. `src/pages/Roles.tsx` — конструктор (матрица чекбоксов ресурс×действие, создание/удаление ролей). Назначение роль→группа — в `Groups.tsx`
- **Фаза 2 (не сделано)**: привязка прав к поддереву активов (домены Casbin) — сейчас права глобальные

## Локализация и дизайн (см. frontend/DESIGN.md)

Продукт для русскоязычного рынка: **весь UI на русском** (react-i18next, плюрализация «находка/находки/находок», даты DD.MM.YYYY, локаль ru-RU). Код, API, enum-значения в БД — на английском, перевод только на фронтенде; словарь терминов и таблица переводов enum'ов — в frontend/DESIGN.md.

Дизайн: шрифт Inter (полная кириллица), светлая + тёмная темы (дефолт — системная). Severity-шкала по отраслевой конвенции: критичная `#A32D2D`, высокая `#D85A30`, средняя `#BA7517`, низкая `#378ADD` (синяя, не зелёная — дальтонизм), инфо `#888780`; severity всегда цвет + текст + иконка, не только цвет. Акцентный цвет — синий. Единый источник цветов для UI и Recharts: `src/theme/severity.ts`.

## Дашборд

Конфигурация виджета хранится как JSON (планируется таблица `dashboard_widgets`): `{chart_type, group_by, period, filters}`. Backend отдаёт агрегаты через generic endpoint (`GROUP BY` по любому полю Finding), Recharts рендерит по chart_type. Ничего не хардкодить под конкретные графики.

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

## Статус (2026-09-24)

**Этап 1 «Ядро процесса» — сделано и слито в main** (спека `docs/superpowers/specs/2026-09-19-triage-workflow-and-ai-design.md`, план `docs/superpowers/plans/2026-09-19-stage1-process-core.md`): метаданные импорта (ветка, коммит, объём скана), бэклог только из основной ветки, автозакрытие исчезнувших находок, статус `in_progress`, история `finding_events`, номера SV-N, запросы «ложное / риск принят» с одобрением (`finding:approve`), истечение принятого риска по cron, роль «Разработчик». 45 pytest + smoke-тест зелёные.

**Интерфейс:** переименован — «Проекты» (Entity) и «Уязвимости» (Finding); пять тем с переключателем (янтарная по умолчанию), цвета графиков из переменных темы.

**Этап 2 «Владельцы и окна» — сделано**: хранилище на диске, адрес проекта и автосоздание из CI, файл настроек с закреплением полей, команда-владелец по правилам путей, ссылки на код, окно уязвимости, очередь AppSec, «Мои уязвимости», настройки проекта.

**Дальше:** этап 3 «Сроки и метрики» — SLA-политики и due_at, просрочки, «Шумные правила», теги проектов (решено 24.09: теги идут вместе со SLA), метрики на дашборде.

## История (2026-07-06)

Сделано: инфраструктура (docker-compose: postgres/redis/minio на :9002/lldap), модели + миграции 0001–0003, CRUD активов (дерево), **SARIF-пайплайн end-to-end** (upload → S3 → ARQ worker → парсинг → нормализация → дедуп; проверено на 4 сканерах через `scripts/smoke-test.ps1`), страницы Находки/Импорты/Дашборд с реальными данными, **аутентификация local + LDAP end-to-end** (страница логина, JWT, гард маршрутов; проверено: alice/bob/carol через lldap). Backend venv: `backend/.venv`, Python 3.14.

Вспомогательные скрипты (Windows/PowerShell): `scripts/dev.ps1` (поднять всё), `scripts/smoke-test.ps1` (прогон пайплайна), `scripts/seed_ldap.py` (тестовые LDAP-юзеры), `scripts/samples/*.sarif` (примеры отчётов). `.ps1` сохранять в UTF-8 **с BOM**, иначе PowerShell 5.1 ломает кириллицу.

Группы пользователей (ручные + LDAP-синхронизируемые) — сделано end-to-end (модель/API/синк/UI, проверено: провижёнинг незалогинившихся из LDAP работает).

**Casbin/RBAC (фаза 1) — сделано end-to-end**: конструктор ролей (матрица прав), роли→группы, enforcement на всех эндпоинтах, роли в JWT из групп. Проверено: без токена 401, суперюзер обходит, bob (LDAP→группа→роль «Аудитор») читает находки/роли, но create group → 403. Bootstrap-админ `admin@secretvuln.local`, встроенные роли засижены.

Дальше по MVP: агрегация по поддереву (recursive CTE), привязка прав к поддереву активов (Casbin-домены, фаза 2), дашборд-виджеты (Recharts), аудит-лог + `uploaded_by`, Helm chart.
