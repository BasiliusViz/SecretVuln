# Этап 3 — записка после сессии 1 (бэкенд)

План: `docs/superpowers/plans/2026-10-04-stage3-sla-and-metrics.md`, шаги 1–11 сделаны. Дальше — сессия 2 (фронтенд, шаги 12–19).

## Что готово (API для фронтенда)

| Что | Где |
|---|---|
| `GET/POST/PATCH/DELETE /api/v1/sla-policies` (`sla:read` / `sla:manage`). В ответе есть `entities_count` — сколько проектов назначили политику напрямую. Ошибки 409: удаление default или назначенной политики, `PATCH {is_default:false}` у default, дубль имени | `api/sla_policies.py`, `schemas/sla_policy.py` |
| Настройки проекта: в `PATCH /entities/{id}/settings` добавлены `sla_policy_id` (null — наследовать) и `tags`; в `GET` — `sla {policy_id, policy_name, own, inherited_from, is_default}`, `tags` (свои), `effective_tags [{tag, inherited_from}]`. Политика и теги не закрепляются (pinned) — в `.secretvuln.yml` их нет | `api/entity_settings.py` |
| `GET /api/v1/tags` — все существующие теги (`entity:read`) | там же, `tags_router` |
| `GET /findings`: `overdue=true`, `tag=`, `order=due_at` (NULL в конце); в ответе `sla_start_at`, `due_at`, `resolved_at` | `api/findings.py` |
| `GET /findings/noisy-rules?min_decided=10&min_fp_ratio=0.7` → `[{scanner, rule_id, decided, false_positive, fp_ratio, top_reasons:[{reason_tag,count}]}]` | `services/noisy_rules.py` |
| `POST /metrics/aggregate` → `{metric, group_by, period, rows:[{key,label,value}]}`. `count`/`overdue`/`sla_ratio` — срезы «сейчас» (период к ним не применяется, кроме `group_by=week`); `sla_ratio` и `mttr_days` могут вернуть `value: null`. `team`: `key` = id группы, `label` = имя, `null` — без команды; `entity`: `label` = путь; `week`: `key` = дата понедельника `YYYY-MM-DD`, по возрастанию | `services/metrics.py`, `schemas/metrics.py` |
| Права `sla:read`/`sla:manage` в каталоге и ролях (AppSec и админ — manage, остальные — read); строки `perm.resource.sla`, `perm.action.manage` уже в `ru.json` | `authz/permissions.py`, `cli.py` |

## Внутреннее устройство

- Статус меняется только через `services/finding_state.set_status` (запись события остаётся у вызывающего). Там же `compute_due`, `recompute_due` (только открытые), `recompute_for_policy`.
- Наследование политики и тегов — `services/entity_tree.py` (`effective_sla`, `effective_tags`, `entities_with_tag`, `normalize_tags`); поддерево — через `starts_with`/`left()`, без LIKE.
- Миграция `0013`: таблица политик, политика «Стандартная» 15/30/90/180/— по умолчанию, простой backfill.
- **Смена severity** пересчёта не требует: severity сейчас нигде не меняется (повторный импорт её не обновляет). Если появится — вызвать `compute_due`.
- Тесты чистят все таблицы, поэтому политики по умолчанию в тестах нет — фабрика `make_policy(db, ..., is_default=True)`.

## Проверено

- `pytest`: 159 зелёных (новые: `test_sla.py`, `test_sla_api.py`, `test_noisy_rules.py`, `test_metrics.py`, дополнения в `test_auto_close.py`, `test_finding_filters.py`).
- Смоук `scripts/smoke-test.ps1` зелёный; у находки, закрытой при повторном импорте, стоит `resolved_at`. В скрипте поправлена проверка «импорт по пути»: корень `smoke` остаётся от прошлых прогонов, поэтому новых проектов может быть 2, а не 3.

## Перед стендом для сессии 2

- `alembic upgrade head` (0013) и `python -m app.cli seed-roles`, иначе у ролей не будет прав `sla:*`.
