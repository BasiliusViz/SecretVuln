# SecretVuln — минималистичный аналог DefectDojo

Vulnerability management платформа: импорт находок безопасности **только в формате SARIF**, нормализация под разные сканеры, дедупликация, дашборды.

## Стек

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0 (async, asyncpg) + Alembic (sync, psycopg), PostgreSQL
- **Фоновые задачи**: Redis + ARQ (обработка SARIF-импортов в воркере)
- **Авторизация**: Casbin (pycasbin + casbin-sqlalchemy-adapter) — роли настраиваются из админки, не хардкод
- **Аутентификация**: локальная (email/password + JWT, passlib/bcrypt, pyjwt) и LDAP (ldap3: bind, auto-provisioning, маппинг групп на роли)
- **Файлы**: MinIO/S3 (boto3, path-style addressing) — загруженные SARIF-файлы хранятся в бакете `sarif-imports`. **ВАЖНО: S3 API проброшен на порт 9002** (localhost:9000 на этой машине перехватывает wslrelay.exe из WSL)
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
    services/          # s3.py (MinIO), sarif/ (parser + normalizers)
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
- **Entity** (таблица `entities`): name (unique среди сиблингов: uq_entities_parent_name с NULLS NOT DISTINCT), parent_id (self-FK, ON DELETE CASCADE — удаление сносит поддерево с импортами и находками), description, **custom_fields JSONB**. API `/api/v1/entities` отдаёт плоский список, дерево собирает фронтенд; PATCH parent_id защищён от циклов (`_check_parent` в app/api/entities.py)
- **Import**: одна загрузка SARIF-файла в конкретный Entity (entity_id). filename, s3_key, scanner (определяется воркером из tool.driver.name), status enum(pending|processing|done|failed), stats JSONB ({"created","updated","duplicates"}), error, finished_at
- **Finding**: нормализованная находка, привязана к Entity (entity_id). severity enum(critical|high|medium|low|info), status enum(new|triaged|confirmed|false_positive|risk_accepted|fixed), scanner, rule_id, cwe, file_path, line_start/end, **fingerprint** (дедуп-ключ), raw JSONB (исходный SARIF result — источник правды для ре-нормализации), first_seen/last_seen. Уникальность: `(entity_id, fingerprint)` — область дедупа = узел, куда идут импорты; одинаковая уязвимость в соседних узлах = две находки
- **Role**: только метаданные для админки (name, description, ldap_group, is_builtin). Сами права и назначения user->role живут в таблице `casbin_rule` (создаётся адаптером Casbin автоматически, НЕ в наших миграциях). `Role.name` должен совпадать с subject в Casbin-политиках

### Дедупликация

Ключ `fingerprint` берётся из SARIF `partialFingerprints` (приоритет: `primaryLocationLineHash`, потом первый доступный ключ); fallback — sha256 от `rule_id + file_path + snippet`. При повторном импорте существующая находка обновляет `last_seen` и `import_id`, счётчик идёт в `Import.stats.duplicates`/`updated`.

### Расширение под AI (не реализовано, планируется Ollama)

Будущая таблица `ai_analyses`: FK на `findings.id`, one-to-many (несколько анализов на находку — разные модели/версии промпта). НЕ встраивать AI-выводы в саму таблицу findings.

## Пайплайн импорта (РЕАЛИЗОВАН, протестирован end-to-end)

1. `POST /api/v1/entities/{id}/imports` (multipart, поле `file`) → файл в S3 (`app/services/s3.py`), запись Import(pending), ARQ job `process_import` в Redis
2. Воркер (`app/worker.py`, запуск: `python -m arq app.worker.WorkerSettings`): скачивает из S3 → парсит SARIF (`app/services/sarif/parser.py`) → определяет сканер по `runs[].tool.driver.name` → нормализует severity (`app/services/sarif/normalizers.py`) → дедуп по fingerprint → пишет findings, обновляет Import.stats/status. Если ре-импорт видит находку в статусе fixed — переоткрывает в new (счётчик updated)

Нормализаторы: Semgrep, Trivy, Gitleaks (всегда high/critical — секреты), Checkov + Default (level→severity: error=high, warning=medium, note=low). Реестр `_REGISTRY` в normalizers.py, матчинг по подстроке имени драйвера.

API: `GET /api/v1/imports` (все), `GET /api/v1/imports/{id}`, `GET /api/v1/entities/{id}/imports`, `GET /api/v1/findings` (фильтры: entity_id, severity, status, scanner, limit/offset), `GET /api/v1/findings/stats` (total + by_severity + by_status), `PATCH /api/v1/findings/{id}?status=...`

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

## Конвенции

- Все env-переменные с префиксом `SV_` (см. backend/.env.example)
- API под `/api/v1`, Swagger — `/api/docs`
- Модели: UUID PK (`UUIDPKMixin`), created_at/updated_at (`TimestampMixin`), enum'ы — Python `str, enum.Enum` + PG native enum
- Alembic использует sync-драйвер psycopg (URL выводится из async URL в `config.database_url_sync`); новые модели импортировать в `app/models/__init__.py`, иначе autogenerate их не увидит
- Миграции: `cd backend && alembic upgrade head`
- Запуск API: `cd backend && uvicorn app.main:app --reload`
- Запуск воркера: `cd backend && python -m arq app.worker.WorkerSettings`

## Статус (2026-07-06)

Сделано: инфраструктура (docker-compose: postgres/redis/minio на :9002/lldap), модели + миграции 0001–0003, CRUD активов (дерево), **SARIF-пайплайн end-to-end** (upload → S3 → ARQ worker → парсинг → нормализация → дедуп; проверено на 4 сканерах через `scripts/smoke-test.ps1`), страницы Находки/Импорты/Дашборд с реальными данными, **аутентификация local + LDAP end-to-end** (страница логина, JWT, гард маршрутов; проверено: alice/bob/carol через lldap). Backend venv: `backend/.venv`, Python 3.14.

Вспомогательные скрипты (Windows/PowerShell): `scripts/dev.ps1` (поднять всё), `scripts/smoke-test.ps1` (прогон пайплайна), `scripts/seed_ldap.py` (тестовые LDAP-юзеры), `scripts/samples/*.sarif` (примеры отчётов). `.ps1` сохранять в UTF-8 **с BOM**, иначе PowerShell 5.1 ломает кириллицу.

Группы пользователей (ручные + LDAP-синхронизируемые) — сделано end-to-end (модель/API/синк/UI, проверено: провижёнинг незалогинившихся из LDAP работает).

**Casbin/RBAC (фаза 1) — сделано end-to-end**: конструктор ролей (матрица прав), роли→группы, enforcement на всех эндпоинтах, роли в JWT из групп. Проверено: без токена 401, суперюзер обходит, bob (LDAP→группа→роль «Аудитор») читает находки/роли, но create group → 403. Bootstrap-админ `admin@secretvuln.local`, встроенные роли засижены.

Дальше по MVP: агрегация по поддереву (recursive CTE), привязка прав к поддереву активов (Casbin-домены, фаза 2), дашборд-виджеты (Recharts), аудит-лог + `uploaded_by`, Helm chart.
