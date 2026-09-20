---
description: Поднять локальный стенд: инфраструктура, миграции, API, воркер, фронтенд
---

Подними стенд SecretVuln:

1. `docker compose up -d postgres redis` из корня. MinIO поднимай только если он нужен для задачи (загрузка SARIF) — образ с Docker Hub не тянется, процедура запуска локального образа есть в скилле `secretvuln-dev`.
2. Миграции: `cd backend; .\.venv\Scripts\python -m alembic upgrade head`
3. API в фоне: `cd backend; .\.venv\Scripts\python -m uvicorn app.main:app --port 8000`
4. Воркер в фоне: `cd backend; .\.venv\Scripts\python -m arq app.worker.WorkerSettings`
5. Фронтенд — через `preview_start` с конфигурацией `frontend` (не через Bash).

Если база пустая, создай админа и роли:
`.\.venv\Scripts\python -m app.cli create-admin --email admin@secretvuln.local --password "Admin12345!"` и `.\.venv\Scripts\python -m app.cli seed-roles`.

В ответе: что поднялось и адреса (интерфейс, Swagger).
