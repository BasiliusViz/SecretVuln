# UI-тесты (Playwright) на изолированном стенде — рабочую базу и dev-стенд не трогает.
#
#   БД secretvuln_e2e (пересоздаётся), Redis база /1, API :8001, Vite :5174,
#   хранилище SARIF — local, backend\data\sarif-e2e.
#
# Использование:
#   powershell -File scripts\e2e.ps1                      # все сценарии
#   powershell -File scripts\e2e.ps1 e2e/auth.spec.ts     # аргументы уходят в playwright test
#
# Логи API, воркера и Vite — backend\data\e2e-logs. Отчёт — frontend\playwright-report.
# Переменные SV_* ставятся на время прогона и восстанавливаются в конце — даже при запуске
# из открытой сессии (.\scripts\e2e.ps1), dev-команды в этом терминале не уедут на e2e-стенд.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$py = Join-Path $backend ".venv\Scripts\python.exe"
$logs = Join-Path $backend "data\e2e-logs"
$storage = Join-Path $backend "data\sarif-e2e"
$apiPort = 8001
$webPort = 5174

# Прежние значения переменных — вернуть в finally
$savedEnv = @{}
function Set-RunEnv($name, $value) {
    if (-not $savedEnv.ContainsKey($name)) {
        $savedEnv[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }
    [Environment]::SetEnvironmentVariable($name, $value, "Process")
}
$startDir = Get-Location

# Учётки тестового стенда: frontend\e2e\.env, если есть, иначе .env.example
$envFile = Join-Path $frontend "e2e\.env"
if (-not (Test-Path $envFile)) { $envFile = Join-Path $frontend "e2e\.env.example" }
foreach ($line in Get-Content $envFile -Encoding UTF8) {
    if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') {
        Set-RunEnv $Matches[1] $Matches[2].Trim()
    }
}

# Окружение backend — наследуется дочерними процессами
Set-RunEnv "SV_DATABASE_URL" "postgresql+asyncpg://secretvuln:secretvuln@localhost:5432/secretvuln_e2e"
Set-RunEnv "SV_REDIS_URL" "redis://localhost:6379/1"
Set-RunEnv "SV_STORAGE_BACKEND" "local"
Set-RunEnv "SV_STORAGE_PATH" "./data/sarif-e2e"
Set-RunEnv "SV_LDAP_ENABLED" "false"
# Вывод CLI с кириллицей и «✓» не должен падать, когда консоль в cp1251 или вывод в пайпе
Set-RunEnv "PYTHONIOENCODING" "utf-8"
# Окружение Vite и Playwright
Set-RunEnv "SV_API_PROXY" "http://127.0.0.1:$apiPort"
Set-RunEnv "SV_WEB_PORT" "$webPort"
Set-RunEnv "SV_E2E_BASE_URL" "http://127.0.0.1:$webPort"
Set-RunEnv "SV_E2E_API_URL" "http://127.0.0.1:$apiPort"

function Step($text) { Write-Host "`n== $text" -ForegroundColor Yellow }

function Assert-PortFree($port) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Порт $port занят — остался прошлый прогон? Освободите порт и повторите."
    }
}

function Wait-Http($url, $name, $proc, $seconds = 60) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if ($proc.HasExited) { throw "$name завершился при старте, см. $logs" }
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    throw "$name не ответил за $seconds с ($url), см. $logs"
}

function Start-Bg($name, $exe, $argList, $dir) {
    $p = Start-Process -FilePath $exe -ArgumentList $argList -WorkingDirectory $dir `
        -NoNewWindow -PassThru `
        -RedirectStandardOutput (Join-Path $logs "$name.out.log") `
        -RedirectStandardError (Join-Path $logs "$name.err.log")
    return $p
}

$procs = @()
$exitCode = 1
try {
    Assert-PortFree $apiPort
    Assert-PortFree $webPort
    New-Item -ItemType Directory -Force $logs | Out-Null
    if (Test-Path $storage) { Remove-Item -Recurse -Force $storage }

    Step "Postgres и Redis"
    Push-Location $root
    docker compose up -d postgres redis | Out-Null
    # pg_isready: после старта контейнера база принимает соединения не сразу
    for ($i = 0; $i -lt 30; $i++) {
        docker compose exec -T postgres pg_isready -U secretvuln -q
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 1
    }
    docker compose exec -T postgres psql -U secretvuln -d postgres -q -c "DROP DATABASE IF EXISTS secretvuln_e2e WITH (FORCE)"
    if ($LASTEXITCODE -ne 0) { throw "Не удалось удалить secretvuln_e2e" }
    docker compose exec -T postgres psql -U secretvuln -d postgres -q -c "CREATE DATABASE secretvuln_e2e"
    if ($LASTEXITCODE -ne 0) { throw "Не удалось создать secretvuln_e2e" }
    docker compose exec -T redis redis-cli -n 1 FLUSHDB | Out-Null
    Pop-Location

    Step "Миграции, админ, роли"
    Push-Location $backend
    & $py -m alembic -q upgrade head
    if ($LASTEXITCODE -ne 0) { throw "alembic upgrade head упал" }
    & $py -m app.cli create-admin --email $env:SV_E2E_ADMIN_EMAIL --password $env:SV_E2E_ADMIN_PASSWORD
    if ($LASTEXITCODE -ne 0) { throw "create-admin упал" }
    & $py -m app.cli seed-roles | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "seed-roles упал" }
    Pop-Location

    Step "API :$apiPort, воркер, Vite :$webPort"
    $api = Start-Bg "api" $py @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$apiPort") $backend
    $procs += $api
    $worker = Start-Bg "worker" $py @("-m", "arq", "app.worker.WorkerSettings") $backend
    $procs += $worker
    $vite = Start-Bg "vite" "node" @("node_modules/vite/bin/vite.js", "--host", "127.0.0.1") $frontend
    $procs += $vite
    Wait-Http "http://127.0.0.1:$apiPort/api/v1/health" "API" $api
    Wait-Http "http://127.0.0.1:$webPort/" "Vite" $vite
    if ($worker.HasExited) { throw "Воркер завершился при старте, см. $logs" }

    Step "Playwright"
    Push-Location $frontend
    & npx playwright test @args
    $exitCode = $LASTEXITCODE
    Pop-Location
}
catch {
    Write-Host "`nОШИБКА: $_" -ForegroundColor Red
    $exitCode = 1
}
finally {
    Step "Остановка стенда"
    # cmd /c: в PS 5.1 stderr нативной команды при Stop стал бы исключением и оборвал цикл
    foreach ($p in $procs) {
        if ($p -and -not $p.HasExited) { cmd /c "taskkill /T /F /PID $($p.Id) >nul 2>&1" }
    }
    Set-Location $startDir
    foreach ($name in $savedEnv.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnv[$name], "Process")
    }
}

if ($exitCode -eq 0) {
    Write-Host "`nUI-тесты: ПРОШЛИ" -ForegroundColor Green
} else {
    Write-Host "`nUI-тесты: УПАЛИ (отчёт: frontend\playwright-report, логи: $logs)" -ForegroundColor Red
}
exit $exitCode
