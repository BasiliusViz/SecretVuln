# Этап 10 «Обогащение» — план

**Спека:** `docs/superpowers/specs/2026-11-21-stage10-enrichment-design.md` (исполнитель читает её вместе с планом).
**Как работаем:** основная сессия пишет сама, TDD, `/sv-test` после каждой задачи. Две сессии: бэкенд (1–9) →
записка `docs/stage10-handoff.md` → фронтенд (10–14). Ревью `sv-reviewer` одно на этап, в конце.

**Общие ограничения:** строки UI только в `ru.json`; цвета — из переменных темы; право `intel:manage` в
`GLOBAL_ONLY`; каждая загрузка заменяет таблицу источника целиком, при ошибке старые данные не трогаются.

## Сессия 1 — бэкенд

1. **Модели и миграция 0021**: таблицы `intel_*`, enum источника/статуса, поля находки `cves`/`epss_max`/`kev`/`has_bdu`
   с индексами. — `app/models/intel.py`, `app/models/finding.py`, `app/models/__init__.py`, `alembic/versions/0021_intel.py`
2. **Извлечение CVE из SARIF** (ruleId, rule.id, теги и свойства правила, свойства result; без дублей, верхний регистр).
   — `app/services/sarif/parser.py`, `tests/test_sarif_parser.py` (фикстуры Trivy, Grype)
3. **Парсеры четырёх форматов** (потоково: csv/gz, json, iterparse xml/zip; проверка формата → понятная ошибка).
   — `app/services/intel/parsers.py`, `tests/test_intel_parsers.py`, фикстуры `tests/fixtures/intel/` (в т.ч. битые и чужие)
4. **Загрузка в таблицу и пересчёт сводных полей** (замена в одной транзакции, `recompute_findings`, `enrich_findings`
   для набора находок). — `app/services/intel/loader.py`, `app/services/intel/enrich.py`, `tests/test_intel_loader.py`
5. **Право и API справочников**: `intel:manage` в каталоге и `GLOBAL_ONLY`, `POST /intel/{source}` (202/409, лимит
   `SV_INTEL_MAX_MB`, хранилище), `GET /intel`, задача ARQ `load_intel`, аудит `intel.load`.
   — `app/authz/permissions.py`, `app/api/intel.py`, `app/main.py`, `app/worker.py`, `app/core/config.py`,
   `app/services/audit.py`, `app/cli.py` (роль админа), `backend/.env.example`, `tests/test_intel_api.py`
6. **Обогащение при импорте** (`apply_import` заполняет `cves` и сводные поля) + CLI `backfill-intel` и загрузка
   встроенного CWE при `seed`. — `app/services/import_processing.py`, `app/cli.py`, `app/services/intel/data/cwe.json`
   (сгенерировать из MITRE 4.x + view 1400), `tests/test_import_intel.py`
7. **API находок**: блок `intel` в карточке (с `stale`), поля и фильтры списка (`kev`, `min_epss`, `has_bdu`,
   `cwe_category`), сортировка `epss_max`, `group_by: cwe_category` и фильтр `kev` в метриках.
   — `app/api/findings.py`, `app/schemas/finding.py`, `app/services/intel/read.py`, метрики (`api/metrics*`), `tests/test_findings_intel.py`
8. **ИИ и MCP**: промпт `triage-v4` с блоком «справочные данные», `get_finding` с `intel`, фильтры `kev`/`min_epss`
   в `search_findings`. — `app/services/llm/prompts.py`, `app/services/agent_tools.py`, `app/mcp_server.py`, тесты промпта и MCP
9. **Документация и записка**: раздел «Обогащение» в архитектуре, карта файлов в CLAUDE.md, `docs/stage10-handoff.md`.
   — `docs/architecture.md`, `CLAUDE.md`

## Сессия 2 — фронтенд

10. **Страница «Справочники» `/intel`**: четыре карточки, загрузка файла, опрос статуса, пункт сайдбара по праву.
    — `src/pages/Intel.tsx`, `src/App.tsx`, `src/components/Layout.tsx`, `src/i18n/ru.json`
11. **Блок «Угрозы» в окне SV-N**: CWE, EPSS, KEV, БДУ, «Данные устарели». — компонент окна находки, `ru.json`
12. **Список «Уязвимости»**: колонки EPSS/KEV, фильтры, сортировка. — `src/pages/Findings.tsx`, `ru.json`
13. **Дашборд**: плитка «Открытых в KEV» с переходом в отфильтрованный список. — `src/pages/Dashboard.tsx`, `ru.json`
14. **e2e**: загрузка KEV-фикстуры → плашка у находки → фильтр «Только KEV». — `frontend/e2e/intel.spec.ts`, `e2e/api.ts`

## Конец этапа

15. `/sv-check`, ревью `sv-reviewer` по диффу этапа, исправления, статус в CLAUDE.md, замер `/usage` → память.
