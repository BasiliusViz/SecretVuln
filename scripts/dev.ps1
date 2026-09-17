# Запускает все сервисы SecretVuln для локальной разработки.
# Каждый сервис — в отдельном окне PowerShell, чтобы видеть логи.
#
#   docker (postgres/redis/minio)  — если ещё не подняты
#   backend  (uvicorn :8000)
#   worker   (ARQ, обработка импортов)
#   frontend (vite :5173)
#
# Использование:  powershell -File scripts\dev.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$py = Join-Path $backend ".venv\Scripts\python.exe"

Write-Host "== SecretVuln dev ==" -ForegroundColor Cyan

# 1. Docker-инфраструктура
Write-Host "`n[1/4] Docker (postgres/redis/minio)..." -ForegroundColor Yellow
Push-Location $root
docker compose up -d postgres redis minio
docker compose run --rm minio-init | Out-Null
Pop-Location

# 2. Миграции
Write-Host "`n[2/4] Alembic migrations..." -ForegroundColor Yellow
Push-Location $backend
& $py -m alembic upgrade head
Pop-Location

# 3. Backend + Worker + Frontend — каждый в своём окне
Write-Host "`n[3/4] Backend :8000, Worker, Frontend :5173 (в отдельных окнах)..." -ForegroundColor Yellow

Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$backend'; & '$py' -m uvicorn app.main:app --reload --port 8000"

Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$backend'; & '$py' -m arq app.worker.WorkerSettings"

Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$frontend'; npm run dev"

Write-Host "`n[4/4] Готово." -ForegroundColor Green
Write-Host "  Frontend:  http://localhost:5173"
Write-Host "  API docs:  http://localhost:8000/api/docs"
Write-Host "  MinIO UI:  http://localhost:9001  (minioadmin / minioadmin)"
Write-Host "`nДля smoke-теста пайплайна:  powershell -File scripts\smoke-test.ps1"
