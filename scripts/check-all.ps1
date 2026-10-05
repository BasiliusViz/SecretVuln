# Проверка всего проекта одной командой: backend pytest → сборка frontend → UI-тесты.
# Печатает итог по шагам; код выхода ≠ 0, если что-то упало. Dev-стенд и dev-базу не трогает.
#
# Использование:
#   powershell -File scripts\check-all.ps1          # pytest, build, e2e
#   powershell -File scripts\check-all.ps1 -Smoke   # + smoke-test.ps1 (нужны dev API, воркер и MinIO)
#
# Полный вывод каждого шага — backend\data\check-logs\<шаг>.log, на экран — хвост упавших.

param([switch]$Smoke)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$py = Join-Path $backend ".venv\Scripts\python.exe"
$logs = Join-Path $backend "data\check-logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$env:PYTHONIOENCODING = "utf-8"

$results = @()

# Шаг в отдельном процессе: вывод в лог (без обёрток PowerShell над stderr), итог — код выхода
function Invoke-Step($name, $exe, $argList, $dir) {
    Write-Host "`n== $name..." -ForegroundColor Yellow
    $log = Join-Path $logs "$name.log"
    $err = Join-Path $logs "$name.err.log"
    $started = Get-Date
    $p = Start-Process -FilePath $exe -ArgumentList $argList -WorkingDirectory $dir `
        -NoNewWindow -Wait -PassThru -RedirectStandardOutput $log -RedirectStandardError $err
    $seconds = [int]((Get-Date) - $started).TotalSeconds
    $errText = Get-Content $err -Raw -Encoding UTF8
    if ($errText) { Add-Content -Path $log -Value $errText -Encoding UTF8 }
    Remove-Item $err
    $ok = $p.ExitCode -eq 0
    # Строка-итог: pytest/playwright «N passed», vite «built in»
    $lines = Get-Content $log -Encoding UTF8 | Where-Object { $_.Trim() }
    $summary = ($lines | Where-Object { $_ -match '\d+ (passed|failed)|built in' } | Select-Object -Last 1)
    if (-not $summary) { $summary = $lines | Select-Object -Last 1 }
    $summary = "$summary".Trim()
    if ($ok) {
        Write-Host "   ok ($seconds с): $summary" -ForegroundColor Green
    } else {
        Write-Host "   УПАЛ ($seconds с), хвост лога ${log}:" -ForegroundColor Red
        Get-Content $log -Encoding UTF8 -Tail 40 | ForEach-Object { Write-Host "   $_" }
    }
    $script:results += [pscustomobject]@{ Шаг = $name; Итог = $(if ($ok) { "прошло" } else { "УПАЛО" }); Секунд = $seconds }
}

Push-Location $root
cmd /c "docker compose up -d postgres redis >nul 2>&1"
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    Write-Host "Не удалось поднять Postgres и Redis (docker compose up). Docker Desktop запущен?" -ForegroundColor Red
    exit 1
}
Pop-Location

Invoke-Step "pytest" $py @("-m", "pytest", "-q", "--tb=short") $backend
Invoke-Step "build" "cmd.exe" @("/c", "npm run build") $frontend
Invoke-Step "e2e" "powershell.exe" @("-NoProfile", "-File", (Join-Path $PSScriptRoot "e2e.ps1")) $root
if ($Smoke) {
    Invoke-Step "smoke" "powershell.exe" @("-NoProfile", "-File", (Join-Path $PSScriptRoot "smoke-test.ps1")) $root
}

Write-Host ""
$results | Format-Table -AutoSize | Out-String | Write-Host
$failed = @($results | Where-Object { $_.Итог -ne "прошло" })
if ($failed.Count -gt 0) {
    Write-Host "ИТОГ: упало шагов — $($failed.Count) из $($results.Count)" -ForegroundColor Red
    exit 1
}
Write-Host "ИТОГ: всё прошло" -ForegroundColor Green
exit 0
