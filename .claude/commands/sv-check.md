---
description: Проверить весь проект одной командой — pytest, сборка frontend, UI-тесты
---

Выполни из корня репозитория, без лишних объяснений:

`powershell -File scripts\check-all.ps1` (с `-Smoke` — ещё и smoke-тест, если пользователь попросил; ему нужны dev API, воркер и MinIO)

Скрипт сам поднимает Postgres и Redis, UI-тесты гоняет на изолированном стенде (БД `secretvuln_e2e`, API :8001, Vite :5174) — dev-стенд можно не останавливать.

В ответе: итоговая таблица шагов. Если что-то упало — хвост лога упавшего шага (полные логи в `backend\data\check-logs\`, отчёт Playwright с трейсами — `frontend\playwright-report\`, открыть: `cd frontend; npx playwright show-report`).
