# План этапа 3 «Сроки и метрики»

Спека: `docs/superpowers/specs/2026-10-04-stage3-sla-and-metrics.md`. Каждый пункт — тест вперёд, затем код, `/sv-test` зелёный, коммит.

## Сессия 1 — бэкенд

1. Модель `SlaPolicy`, поля `entities.sla_policy_id/tags`, `findings.sla_start_at/due_at/resolved_at`; миграция с политикой по умолчанию и backfill — `models/sla_policy.py`, `models/entity.py`, `models/finding.py`, `models/__init__.py`, `alembic/versions/`.
2. Резолвер наследования: эффективная политика и теги, поддерево по `path_cache` без LIKE — `services/entity_tree.py`.
3. `services/finding_state.py`: `set_status`, `compute_due`, `recompute_due`; тесты переходов.
4. Перевести 6 мест смены статуса на `set_status`, создание находки — на `compute_due` — `api/findings.py` (PATCH, bulk), `services/decisions.py`, `services/import_processing.py`, `services/risk_expiry.py`.
5. Права `sla:read`/`sla:manage` в каталог и встроенные роли — `authz/permissions.py`, `cli.py`.
6. CRUD `/sla-policies` + схемы, пересчёт при изменении дней и default — `api/sla_policies.py`, `schemas/sla_policy.py`, `main.py`.
7. Настройки проекта: `sla_policy_id`, `tags` (валидация), эффективные значения с источником, пересчёт поддерева; `GET /tags` — `api/entity_settings.py`, `schemas/`.
8. `GET /findings`: `overdue`, `tag`, сортировка по сроку, поля в ответе — `api/findings.py`, `schemas/finding.py`.
9. `GET /findings/noisy-rules` — `api/findings.py` (или `services/noisy_rules.py`).
10. `POST /metrics/aggregate` с белыми списками — `api/metrics.py`, `services/metrics.py`, `schemas/metrics.py`.
11. Смоук `/sv-smoke`, записка-передача `docs/handoff-stage3-backend.md`, коммит.

## Сессия 2 — фронтенд

12. Типы и клиент API для политик, тегов, метрик — `api/`.
13. Раздел «Политики SLA» + маршрут и пункт меню — `pages/SlaPolicies.tsx`, `App.tsx`, `components/Layout.tsx`.
14. Настройки проекта: политика («унаследовано от …»), редактор тегов — `pages/Assets.tsx`.
15. Уязвимости: колонка «Срок», фильтры «Просрочено»/«Тег», сортировка; окно уязвимости — строка срока — `pages/Findings.tsx` и окно находки.
16. Очередь AppSec: вкладки «Просрочены», «Шумные правила».
17. Дашборд: JSON-конфиги виджетов, плитки и недельный график — `pages/Dashboard.tsx`.
18. Строки в `i18n/ru.json`, проверка в браузере (bob и alice), `npm run build`.
19. Ревью `sv-reviewer` по диффу этапа, исправления, обновить статус в `CLAUDE.md`, замер `/usage`.
