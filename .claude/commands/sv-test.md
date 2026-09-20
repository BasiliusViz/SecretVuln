---
description: Поднять Postgres и прогнать тесты backend
---

Выполни по порядку, без лишних объяснений:

1. `docker compose up -d postgres` (из корня репозитория)
2. `cd backend; .\.venv\Scripts\python -m pytest -q -p no:warnings`

Если pytest пишет, что нет базы `secretvuln_test`, создай её:
`docker compose exec -T postgres createdb -U secretvuln secretvuln_test` — и повтори прогон.

В ответе: сколько тестов прошло, и полный текст падений, если они есть.
