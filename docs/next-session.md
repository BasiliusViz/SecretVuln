# Следующая сессия (записка от 21.11.2026)

## Состояние

- Этап 9 «Память команды» закрыт и запушен в `main` (последний коммит `75f1f2e`), ревью `sv-reviewer` пройдено,
  `/sv-check` зелёный (pytest, build, e2e 21/21). Подробности и открытые мелочи — `docs/stage9-handoff.md`, раздел «Открытое».
- После коммита закрыта дыра: REST находок (`api/findings.py`, `to_read` / `_memory_out_of_scope`) не отдаёт текст
  правила чужой ветки — та же проверка, что `hint_in_scope` в MCP и запросах.

## Сделать руками до работы

- dev-БД: `cd backend; .\.venv\Scripts\python -m alembic upgrade head; .\.venv\Scripts\python -m app.cli seed-roles`
  (миграции 0019–0020, право `memory:manage`).
- Замер расхода этапа 9 (`/usage`) — записать в память.

## Дальше — этап 10 «Обогащение»

Порядок этапов 7–10 — `docs/superpowers/specs/2026-10-10-stage6-ai-agent-output.md` (строка про этапы 7–10).
Идея — `docs/proposals/2026-09-19-ai-knowledge-hub.md`, раздел «L1. Обогащение без ИИ»:
CVE → EPSS и CISA KEV (опционально БДУ ФСТЭК), CWE → название и категория, справочники обновляет ARQ раз в сутки,
находки обогащаются при импорте. Спеки нет — начать с brainstorming и короткой спеки + плана.

## Грабли окружения

- Docker Desktop не стартует с `Wsl/Service/CreateInstance/CreateVm/HCS/0x800705aa` — не хватает памяти под WSL
  (`~/.wslconfig`: `memory=20GB` при 28 ГБ RAM). Освободить память или снизить до `memory=8GB`, затем `wsl --shutdown`
  и перезапуск Docker Desktop.
- Node.js 22.17.1 уязвим (CVE-2026-111497) — обновить до 22.23.4+.
