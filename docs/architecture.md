# SecretVuln — архитектура и реализованные подсистемы

Подробности, вынесенные из CLAUDE.md (он грузится в каждую сессию и каждого агента, поэтому держим его коротким). Читать нужный раздел, когда работа касается этой подсистемы.

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
- Роли навешиваются на группы через привязки «роль → область» (`role_bindings`, этап 4, см. «Авторизация»); старая M2M `group_roles` удалена миграцией 0014

## Авторизация (Casbin + права на поддерево — РЕАЛИЗОВАНО, этап 4)

- **Право = ресурс + действие.** Каталог — `app/authz/permissions.py` (`CATALOG`), матрицу в UI рисуем по нему. `GLOBAL_ONLY` (`group:write/delete`, `role:*`, `sla:manage`) действуют только из глобальной привязки; `ANY_BINDING` (`group:read`, `sla:read`) — из привязки на любом узле, дерево не открывают. Новые права этапа 4: `sla:assign` (назначить SLA-политику проекту), `access:manage` (управлять привязками в своём поддереве)
- **Роль**: метаданные в `roles` (name = субъект Casbin), права — p-политики в `casbin_rule` (миграция 0014 создаёт таблицу, если её нет; права ролей читаются SQL-запросом). API `app/api/roles.py`: `GET /permissions/catalog` (с `global_only`), CRUD `/roles`, `PUT /roles/{id}/permissions`. Встроенные роли — `python -m app.cli seed-roles` (в cp1251 — с `PYTHONIOENCODING=utf-8`): Наблюдатель / Аудитор / Инженер ИБ / Руководитель команды / Администратор
- **Привязка** (`role_bindings`, миграция 0014): группа + роль + проект; `entity_id = NULL` — всё дерево (`NULLS NOT DISTINCT`). Привязка к узлу действует на всё его поддерево (по `path_cache`). Цепочка: пользователь → группы → привязки → права ролей
- **`services/access.py`**: `load_access` одним запросом собирает `Access` (право → «везде» или набор префиксов путей). Методы `allows`, `anywhere`, `is_global`, `filter`/`visible_filter` (SQL-фильтр по поддеревьям), `entity_scope`, `can_see`, `scoped_permissions`. В JWT ролей больше нет — `Access` грузится на каждый запрос
- **Enforcement** (`app/api/deps.py`): `Principal.access`; `require_permission` — ворота «право есть хоть где-то» (иначе 403); `ensure(access, perm, target)` — проверка на конкретном объекте: невидимый → 404, видимый без права → 403. `is_superuser` обходит. `test_route_coverage` требует классифицировать каждый маршрут
- **Видимость**: `GET /entities` отдаёт предков доступных узлов как заглушки (`stub: true`). Чужое неотличимо от несуществующего: автосоздание по пути (`PUT /entities/by-path`, импорт с `auto_create`) при отказе — всегда 403, `POST /imports` по чужому `project_path` — как по несуществующему. Перенос проекта — права на обе ветки (+ `sla:assign`, если меняется SLA). Bulk по находкам — всё или ничего
- **Делегирование** (`app/api/bindings.py`): `GET/POST /entities/{id}/bindings` (свои и унаследованные, `roles` с `grantable`/`missing`), `DELETE /bindings/{id}`, `GET/POST/DELETE /groups/{id}/bindings`, `GET /groups?entity_id=` с `has_access`. С `access:manage` можно выдать в своём поддереве только роль, все права которой у тебя там уже есть
- **Фронтенд**: `useCan(perm, path)` по `/auth/me.scoped_permissions` (путь `"*"` — глобально); вкладка проекта «Доступ» (`pages/ProjectAccess.tsx`); привязки «роль → область» в «Группах»; значок «только глобально» в «Ролях»
- Спека: `docs/superpowers/specs/2026-10-05-subtree-access-design.md`

## Журнал аудита (этап 5а — РЕАЛИЗОВАН)

- Таблица `audit_log` (миграция `0015`): кто (`actor_type` user/system, `actor_label`), действие (`entity.update`, `binding.create`…, полный список — `ACTIONS` в `services/audit.py`), объект, проект (`entity_id` + `entity_path`, после удаления проекта `entity_id=NULL`, путь остаётся), IP, `changes`.
- Запись — `record_audit` в той же транзакции, что и изменение (откат убирает и запись). `changes`: `{поле: [было, стало]}` для правок (`diff`), снимок полей для create/delete (`snapshot`). Поля — только из белых списков `FIELDS`; пароли/токены отсекаются, из `*_url` вырезаются учётные данные.
- Импорт с `.secretvuln.yml` пишет `entity.settings_update` / `ownership.rules_update` с `source: "config"`.
- Чтение: `GET /api/v1/audit`, право `audit:read` на поддерево; глобальные события (без проекта) — только при глобальном праве. Фильтр `action` — точно или префикс `binding.`, повторяется (ИЛИ).
- Сторож `tests/test_audit_coverage.py`: новый POST/PUT/PATCH/DELETE без `record_audit(` роняет тест, исключения — в `EXEMPT` с причиной.
- UI: страница `/audit` (фильтры: период, кто, группа действий, проект), вкладка «Журнал» в настройках проекта; `components/AuditTable.tsx` различает снимок/разницу по действию (`*.create`/`*.delete` — снимок). Импорты: «Загрузил», «Только мои» (`?uploaded_by=me`).
- Каскады и переносы: удаление группы/роли пишет `binding.delete` на каждую снесённую привязку (`cascade: "group.delete"`/`"role.delete"`) — руководитель проекта видит пропажу доступа. `entity.move` пишется и на старого родителя, если узел ушёл из его ветки; путь новой ветки при этом виден аудитору старой (осознанно: `path_cache [было, стало]` был в записи и раньше).
- Имена рядом с UUID (`audit.with_names`): `parent_id` → `parent` (путь), `owner_group_id` → `owner_group`, `sla_policy_id` → `sla_policy`, той же формы; в правилах владения — `group`. Имя — на момент события.
- `repo_url`: учётные данные вырезаются, но их смена видна — `Snapshot` держит в памяти sha256 от userinfo, `diff` добавляет `credentials_changed: ["repo_url"]`.
- Бэклог: в `roles.set_permissions` Casbin применяется до коммита записи — при падении коммита права изменятся без записи; `entity.delete` не пишет `binding.delete` для привязок на удалённом поддереве; `record_entities_created` делает `with_names` на каждый узел (N+1 на длинной цепочке предков).

## Локализация и дизайн (см. frontend/DESIGN.md)

Продукт для русскоязычного рынка: **весь UI на русском** (react-i18next, плюрализация «находка/находки/находок», даты DD.MM.YYYY, локаль ru-RU). Код, API, enum-значения в БД — на английском, перевод только на фронтенде; словарь терминов и таблица переводов enum'ов — в frontend/DESIGN.md.

Дизайн: шрифт Inter (полная кириллица), светлая + тёмная темы (дефолт — системная). Severity-шкала по отраслевой конвенции: критичная `#A32D2D`, высокая `#D85A30`, средняя `#BA7517`, низкая `#378ADD` (синяя, не зелёная — дальтонизм), инфо `#888780`; severity всегда цвет + текст + иконка, не только цвет. Акцентный цвет — синий. Единый источник цветов для UI и Recharts: `src/theme/severity.ts`.

## Дашборд

Конфигурация виджета — JSON `{chart_type, group_by, period, filters}`; набор виджетов «Обзора» задан конфигами в коде фронтенда. Backend отдаёт агрегаты через generic `POST /metrics/aggregate` (этап 3), Recharts рендерит по chart_type. Ничего не хардкодить под конкретные графики. Личные дашборды (таблица `dashboard_widgets`, конструктор) — **отложены** до запроса пользователей, спека: `docs/superpowers/specs/2026-10-05-stage6-dashboard-widgets.md`.


## История (2026-07-06)

Сделано: инфраструктура (docker-compose: postgres/redis/minio на :9002/lldap), модели + миграции 0001–0003, CRUD активов (дерево), **SARIF-пайплайн end-to-end** (upload → S3 → ARQ worker → парсинг → нормализация → дедуп; проверено на 4 сканерах через `scripts/smoke-test.ps1`), страницы Находки/Импорты/Дашборд с реальными данными, **аутентификация local + LDAP end-to-end** (страница логина, JWT, гард маршрутов; проверено: alice/bob/carol через lldap). Backend venv: `backend/.venv`, Python 3.14.

Вспомогательные скрипты (Windows/PowerShell): `scripts/dev.ps1` (поднять всё), `scripts/smoke-test.ps1` (прогон пайплайна), `scripts/seed_ldap.py` (тестовые LDAP-юзеры), `scripts/samples/*.sarif` (примеры отчётов). `.ps1` сохранять в UTF-8 **с BOM**, иначе PowerShell 5.1 ломает кириллицу.

Группы пользователей (ручные + LDAP-синхронизируемые) — сделано end-to-end (модель/API/синк/UI, проверено: провижёнинг незалогинившихся из LDAP работает).

**Casbin/RBAC (фаза 1) — сделано end-to-end**: конструктор ролей (матрица прав), роли→группы, enforcement на всех эндпоинтах, роли в JWT из групп. Проверено: без токена 401, суперюзер обходит, bob (LDAP→группа→роль «Аудитор») читает находки/роли, но create group → 403. Bootstrap-админ `admin@secretvuln.local`, встроенные роли засижены.

Дальше по MVP: агрегация по поддереву (recursive CTE), привязка прав к поддереву активов (Casbin-домены, фаза 2), дашборд-виджеты (Recharts), Helm chart. Аудит-лог + `uploaded_by` — сделано на этапе 5а.
