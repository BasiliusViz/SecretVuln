# Этап 9. Память команды — план

Спека: `docs/superpowers/specs/2026-11-15-stage9-team-memory.md` (утверждена 15.11).
Две сессии; каждая начинается с чтения спеки и этого плана. Код пишет основная сессия, тесты — рядом с задачей.

## Сессия 1 — бэкенд

1. Модель и миграция 0019: `triage_memories`, `findings.memory_id`, `decision_requests.memory_id`, событие `memory_hint` — `models/triage_memory.py`, `models/__init__.py`, `models/finding.py`, `models/decision_request.py`, `models/finding_event.py`, `migrations/versions/0019_*.py`
2. Право `memory:manage` во встроенных ролях — `authz/permissions.py`, `cli.py`
3. Сопоставление: условия, маска пути, выбор самого точного, применение и пересчёт — `services/memories.py`, `tests/test_memories_matching.py`
4. Подсказка при импорте (новые и переоткрытые) — `services/import_processing.py`, `tests/`
5. API правил: список, карточка, создание, правка / утвердить / выключить с пересчётом, видимость предков, аудит — `api/memories.py`, `schemas/memory.py`, `main.py`, `services/audit.py`, `services/access.py`
6. Находки: фильтр `has_memory`, краткое `memory` в ответе — `api/findings.py`, `schemas/finding.py`
7. Запрос по правилу: `memory_id` в запросе решения и в истории — `schemas/decision.py`, `services/decisions.py`, `api/decisions.py`
8. Предложения после одобрения (порог 3, без повторов) — `services/decisions.py`, `services/memories.py`
9. MCP `list_memories`, правило в `get_finding` — `services/agent_tools.py`, `mcp_server.py`
10. Промпт `triage-v3` с правилом-подсказкой — `services/llm/`, `worker.py`
11. `/sv-test`, записка `docs/stage9-handoff.md` (что сделано, что осталось фронтенду, открытое)

## Сессия 2 — фронтенд

1. Типы и строки — `api/types.ts`, `i18n/ru.json` (в т.ч. `perm.action`)
2. Страница «Правила команды»: вкладки, фильтр по проекту, форма — `pages/Memories.tsx`, `App.tsx`
3. Пункт и счётчик предложенных в сайдбаре — `components/Layout.tsx`
4. Окно SV-N: блок «Правило команды», «Запросить по правилу» с заполненной формой — страница окна находки и форма запроса решения
5. «Уязвимости»: значок подсказки и фильтр — `pages/Findings.tsx`
6. e2e-сценарий и добавление `/memories` в `pages.spec.ts` — `e2e/memories.spec.ts`, `e2e/api.ts`
7. `/sv-check`, проверка в пяти темах, ревью `sv-reviewer` по диффу этапа, правки, обновить `CLAUDE.md` (статус, карта файлов) и `docs/architecture.md`
