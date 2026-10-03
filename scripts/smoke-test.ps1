# End-to-end проверка пайплайна импорта SARIF через публичный API.
# Требует запущенных backend (:8000) и worker (см. scripts\dev.ps1).
#
#   1. создаёт тестовый актив
#   2. загружает 4 примера SARIF (semgrep / gitleaks / trivy / checkov)
#   3. ждёт обработки воркером
#   4. печатает статистику импортов и находки по критичности
#   5. повторно грузит semgrep — проверка дедупликации
#   8. импорт по пути проекта с автосозданием и .secretvuln.yml — проверка владельца
#
# Использование:  powershell -File scripts\smoke-test.ps1

$ErrorActionPreference = "Stop"
$api = "http://localhost:8000/api/v1"
$samples = Join-Path $PSScriptRoot "samples"

function Fail($msg) { Write-Host "✗ $msg" -ForegroundColor Red; exit 1 }
function Ok($msg)   { Write-Host "✓ $msg" -ForegroundColor Green }

# --- 0. Проверка сервисов ---
Write-Host "== Smoke-тест пайплайна SARIF ==" -ForegroundColor Cyan
try {
    $h = Invoke-RestMethod "$api/health" -TimeoutSec 5
    if ($h.database -ne "up") { Fail "БД недоступна (health: $($h | ConvertTo-Json -Compress))" }
    if ($h.storage -ne "up") { Fail "хранилище файлов недоступно ($($h.storage_backend))" }
    Ok "backend + БД доступны"
} catch { Fail "backend не отвечает на :8000 — запусти scripts\dev.ps1" }

# --- 0.1 Логин (API закрыт авторизацией) ---
$adminEmail = if ($env:SV_ADMIN_EMAIL) { $env:SV_ADMIN_EMAIL } else { "admin@secretvuln.local" }
$adminPassword = if ($env:SV_ADMIN_PASSWORD) { $env:SV_ADMIN_PASSWORD } else { "Admin12345!" }
try {
    $login = Invoke-RestMethod "$api/auth/login" -Method Post -ContentType "application/json" `
        -Body (@{ email = $adminEmail; password = $adminPassword } | ConvertTo-Json)
} catch { Fail "не удалось войти как $adminEmail — создай админа: python -m app.cli create-admin" }
$headers = @{ Authorization = "Bearer $($login.access_token)" }
$authArg = "Authorization: Bearer $($login.access_token)"
Ok "вход выполнен ($adminEmail)"

# --- 1. Тестовый актив ---
$entityName = "smoke-test-$(Get-Date -Format 'HHmmss')"
$entity = Invoke-RestMethod "$api/entities" -Method Post -ContentType "application/json" `
    -Headers $headers -Body (@{ name = $entityName } | ConvertTo-Json)
$eid = $entity.id
Ok "создан актив '$entityName' ($eid)"

# --- 2. Загрузка примеров ---
$files = @("semgrep.sarif", "gitleaks.sarif", "trivy.sarif", "checkov.sarif")
$importIds = @()
foreach ($f in $files) {
    $path = Join-Path $samples $f
    if (-not (Test-Path $path)) { Fail "нет файла $path" }
    $resp = curl.exe -s -X POST "$api/entities/$eid/imports" -H $authArg -F "file=@$path" | ConvertFrom-Json
    if (-not $resp.id) { Fail "загрузка $f не удалась: $resp" }
    $importIds += $resp.id
    Ok "загружен $f (import $($resp.id.Substring(0,8)), статус $($resp.status))"
}

# --- 3. Ожидание обработки ---
Write-Host "`nЖдём обработки воркером..." -ForegroundColor Yellow
$deadline = (Get-Date).AddSeconds(60)
$pending = [System.Collections.ArrayList]@($importIds)
while ($pending.Count -gt 0 -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    $still = @()
    foreach ($id in $pending) {
        $imp = Invoke-RestMethod "$api/imports/$id" -Headers $headers
        if ($imp.status -in @("pending", "processing")) { $still += $id }
    }
    $pending = [System.Collections.ArrayList]$still
}
if ($pending.Count -gt 0) {
    Write-Host "⚠ воркер не обработал всё за 60с — запущен ли ARQ-воркер?" -ForegroundColor Yellow
    Write-Host "  (scripts\dev.ps1 стартует его отдельным окном)"
}

# --- 4. Итоги импортов ---
Write-Host "`n== Импорты ==" -ForegroundColor Cyan
$rows = foreach ($id in $importIds) {
    $imp = Invoke-RestMethod "$api/imports/$id" -Headers $headers
    [PSCustomObject]@{
        Файл       = $imp.filename
        Сканер     = $imp.scanner
        Статус     = $imp.status
        Создано    = $imp.stats.created
        Обновлено  = $imp.stats.updated
        Дубликаты  = $imp.stats.duplicates
        Ошибка     = if ($imp.error) { $imp.error.Substring(0, [Math]::Min(40, $imp.error.Length)) } else { "" }
    }
}
$rows | Format-Table -AutoSize | Out-String | Write-Host

# --- 5. Находки по критичности ---
Write-Host "== Находки в активе (по критичности) ==" -ForegroundColor Cyan
$stats = Invoke-RestMethod "$api/findings/stats?entity_id=$eid" -Headers $headers
Write-Host "  всего: $($stats.total)"
foreach ($sev in @("critical", "high", "medium", "low", "info")) {
    $c = $stats.by_severity.$sev
    if ($c) { Write-Host ("  {0,-9}: {1}" -f $sev, $c) }
}

# --- 6. Проверка дедупликации ---
Write-Host "`n== Дедупликация (повторная загрузка semgrep) ==" -ForegroundColor Cyan
$dup = curl.exe -s -X POST "$api/entities/$eid/imports" -H $authArg -F "file=@$(Join-Path $samples 'semgrep.sarif')" | ConvertFrom-Json
$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Seconds 2
    $imp = Invoke-RestMethod "$api/imports/$($dup.id)" -Headers $headers
} while ($imp.status -in @("pending", "processing") -and (Get-Date) -lt $deadline)

if ($imp.stats.duplicates -gt 0 -and $imp.stats.created -eq 0) {
    Ok "дедуп работает: created=0, duplicates=$($imp.stats.duplicates)"
} else {
    Write-Host "⚠ ожидали created=0/duplicates>0, получили: $($imp.stats | ConvertTo-Json -Compress)" -ForegroundColor Yellow
}

# --- 7. Автозакрытие (повторный скан без одной находки) ---
Write-Host "`n== Автозакрытие (semgrep-rescan: одна находка исчезла) ==" -ForegroundColor Cyan
$re = curl.exe -s -X POST "$api/entities/$eid/imports" -H $authArg `
    -F "file=@$(Join-Path $samples 'semgrep-rescan.sarif')" | ConvertFrom-Json
$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Seconds 2
    $imp = Invoke-RestMethod "$api/imports/$($re.id)" -Headers $headers
} while ($imp.status -in @("pending", "processing") -and (Get-Date) -lt $deadline)

if ($imp.stats.closed -eq 1) {
    Ok "автозакрытие работает: closed=1"
} else {
    Fail "ожидали closed=1, получили: $($imp.stats | ConvertTo-Json -Compress)"
}

# --- 8. Импорт по пути: автосоздание проектов + файл настроек + владелец ---
Write-Host "`n== Импорт по пути (auto_create + .secretvuln.yml) ==" -ForegroundColor Cyan
$teamName = "smoke-team"
try {
    Invoke-RestMethod "$api/groups" -Method Post -ContentType "application/json" -Headers $headers `
        -Body (@{ name = $teamName; source = "manual" } | ConvertTo-Json) | Out-Null
    Ok "создана команда $teamName"
} catch { Ok "команда $teamName уже есть" }

$stamp = Get-Date -Format 'HHmmss'
$projectPath = "smoke/run-$stamp/svc"
$cfg = Join-Path $env:TEMP "sv-smoke.secretvuln.yml"
Set-Content -Path $cfg -Encoding ascii -Value "version: 1`ndefault_branch: main`nowner: $teamName`nownership:`n  - path: 'app/**'`n    owner: $teamName"
$resp = curl.exe -s -X POST "$api/imports" -H $authArg `
    -F "file=@$(Join-Path $samples 'semgrep.sarif')" -F "config=@$cfg" `
    -F "project_path=$projectPath" -F "auto_create=true" -F "branch=main" | ConvertFrom-Json
if (-not $resp.id) { Fail "импорт по пути не удался: $($resp | ConvertTo-Json -Compress)" }
# Корень «smoke» мог остаться от прошлых прогонов — новыми обязаны быть run-* и svc
$createdPaths = @($resp.created_entities.path)
if ($createdPaths -notcontains $projectPath -or $createdPaths.Count -lt 2) {
    Fail "ожидали создание $projectPath (минимум 2 новых проекта), получили: $($createdPaths -join ', ')"
}
Ok "проекты созданы: $($resp.created_entities.path -join ', ')"

$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Seconds 2
    $imp = Invoke-RestMethod "$api/imports/$($resp.id)" -Headers $headers
} while ($imp.status -in @("pending", "processing") -and (Get-Date) -lt $deadline)
if ($imp.status -ne "done") { Fail "импорт не обработан: $($imp.status) $($imp.error)" }

$vulns = Invoke-RestMethod "$api/findings?entity_id=$($resp.entity_id)" -Headers $headers
$owned = @($vulns | Where-Object { $_.assignee_group.name -eq $teamName }).Count
if ($owned -eq 0 -or $owned -ne @($vulns).Count) {
    Fail "ожидали, что все $(@($vulns).Count) уязвимостей назначены $teamName, назначено $owned"
}
Ok "владелец назначен: $owned уязвимостей → $teamName"

Write-Host "`nГотово. Открой http://localhost:5173 → раздел «Находки» (актив '$entityName')." -ForegroundColor Green
