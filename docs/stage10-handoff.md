# Этап 10 «Обогащение» — записка после бэкенда (21.11.2026)

Спека — `docs/superpowers/specs/2026-11-21-stage10-enrichment-design.md`, план — `docs/superpowers/plans/2026-11-21-stage10-enrichment.md`.
Подробно по устройству — `docs/architecture.md`, раздел «Обогащение».

## Сделано (задачи 1–9, в `main`, не запушено)

- Миграция `0021`: `intel_epss`, `intel_kev`, `intel_bdu`, `intel_bdu_cve`, `intel_cwe`, `intel_sources`; в `findings` — `cves`, `epss_max`, `kev`, `has_bdu`.
- CVE из SARIF при импорте + сводные поля; `python -m app.cli backfill-intel` для старых находок.
- Парсеры EPSS (csv/gz), KEV (json), БДУ (xml/zip), CWE (xml/zip, MITRE 4.x и 5.x).
- `POST /intel/{source}` → воркер `load_intel` → замена таблицы, пересчёт находок, аудит `intel.load`.
- Встроенный CWE (`services/intel/data/cwe.json`, MITRE 5.0) — грузит `seed-roles`, если таблица пуста.
- Блок `intel` в карточке, фильтры и сортировка списка, `cwe_category` и `kev` в метриках, промпт `triage-v4`, MCP.

## API-контракты для фронтенда

### Право

`intel:manage` («Управление справочниками») — только глобальное. Есть у роли «Администратор» (после
`seed-roles`). Пункт сайдбара «Справочники» — по `intel:manage` в правах пользователя. Видеть блок
«Угрозы» и фильтры может каждый, у кого есть `finding:read`. В `ru.json` нужен ресурс `intel`
(действие `manage` уже переведено).

### `GET /api/v1/intel` (право `intel:manage`)

Всегда четыре элемента в порядке `epss, kev, bdu, cwe`:

```json
{"source": "kev", "status": "ok", "loaded_at": "2026-11-21T12:00:00Z", "loaded_by": "admin@…",
 "file_date": "2026-11-19", "record_count": 1342, "error": null,
 "stale": false, "stale_after_days": 7}
```

- `status`: `idle` (ни разу не грузили) / `loading` / `ok` / `failed`. При `failed` в `error` — текст
  для показа как есть; `file_date`/`record_count` при этом описывают **прежние** данные, которые остались.
- `stale` — подсказка «Данные устарели» (EPSS > 30 дней, KEV > 7 дней по `file_date`); у БДУ и CWE
  `stale_after_days = null`, они не устаревают. `loaded_by = null` у встроенного CWE.
- Пока `loading` — опрашивать этот же эндпоинт (воркер меняет статус на `ok`/`failed`).

### `POST /api/v1/intel/{source}` (multipart, поле `file`; право `intel:manage`)

- `202` `{"source": "kev", "status": "loading"}`.
- `400` — не то расширение (`epss`: `.csv`, `.csv.gz`, `.gz`; `kev`: `.json`; `bdu`, `cwe`: `.xml`, `.zip`).
- `409` «Загрузка уже идёт», `413` «Файл больше N МБ» (`SV_INTEL_MAX_MB`, по умолчанию 1024),
  `503` — очередь недоступна. Тексты `detail` — на русском, показывать как есть.
- Формат файла проверяет воркер: ошибка придёт как `status: failed` + `error` в `GET /intel`.

### `GET /api/v1/findings/{id}` и `/findings/by-number/{n}` — поле `intel`

`null`, если у находки нет ни CVE, ни CWE (блок «Угрозы» не показывать). Иначе:

```json
{
  "cwe": {"id": "CWE-502", "name": "Deserialization of Untrusted Data", "category": "Resource Control"},
  "cves": [
    {"id": "CVE-2021-44228", "epss": 0.94358, "percentile": 0.99962,
     "kev": {"date_added": "2021-12-10", "due_date": "2021-12-24",
             "name": "Apache Log4j2 Remote Code Execution Vulnerability", "ransomware": true},
     "bdu": [{"id": "BDU:2021-05969", "name": "Уязвимость …", "severity": "Критический уровень опасности …"}]}
  ],
  "stale": ["kev"],
  "sources": {"epss": "2026-11-20", "kev": "2026-11-19", "bdu": null, "cwe": "2026-10-28"}
}
```

- `cwe` — `null`, если у находки нет CWE; `name`/`category` — `null`, если CWE нет в справочнике.
  Ссылка на MITRE: `https://cwe.mitre.org/data/definitions/<число>.html`.
- По CVE: `epss`/`percentile` (0–1, показывать в %) — `null`, если нет в EPSS; `kev` — `null`, если нет
  в каталоге; `bdu` — пустой список, если нет в БДУ. `severity` БДУ — текст ФСТЭК как есть.
- `stale` — источники с устаревшим файлом (`epss`, `kev`) → «Данные устарели»; `sources` — даты файлов.

### Список `GET /api/v1/findings`

- Новые поля каждой строки: `cves` (список), `epss_max` (0–1 или `null`), `kev` (bool), `has_bdu` (bool).
- Фильтры: `kev=true|false`, `min_epss=0.1` (0–1, вне диапазона — 422), `has_bdu=true|false`,
  `cwe_category=Injection` (точное название категории из справочника).
- Сортировка: `order=epss_max` (по убыванию, без EPSS — в конце).
- Список категорий для фильтра отдельного эндпоинта нет: можно взять ключи из
  `POST /metrics/aggregate {"metric": "count", "group_by": "cwe_category"}` (до 50 групп, `key = null` —
  без категории) или добавить эндпоинт, если понадобится.

### Метрики `POST /api/v1/metrics/aggregate`

- `group_by: "cwe_category"` — по категории CWE (`key`/`label` — название, `null` — без категории).
- `filters.kev: true|false`. Плитка «Открытых в KEV»: `{"metric": "count", "filters": {"kev": true}}`
  (метрика `count` уже считает только открытые), переход — `/findings?kev=true` с открытыми статусами.

## Что открыто

- **Фронтенд — задачи 10–14** плана: страница `/intel`, блок «Угрозы» в SV-N, колонки/фильтры в
  «Уязвимостях», плитка на дашборде, e2e `intel.spec.ts` (KEV-фикстура — `backend/tests/fixtures/intel/kev.json`).
- `backfill-intel` берёт CVE только из `raw` (там нет правила SARIF): CVE из свойств правила у старых
  находок появятся после следующего импорта того же отчёта.
- У БДУ нет даты файла (`file_date = null`) — в карточке показывать `loaded_at`.
- Проверка на настоящих файлах (EPSS ~300 тыс. строк, `vulxml.zip` БДУ) — не делалась, только фикстуры;
  CWE 5.0 от MITRE разобран целиком (1415 записей, 958 с категорией).
- e2e-стенд (`scripts/e2e.ps1`) уже поднимает воркер — загрузка справочника в UI-тесте пройдёт через `load_intel`.
- Node.js на машине — 22.17.1, уязвим (хук просит обновить до 22.23.4+) — сказать пользователю.
- Ревью `sv-reviewer` — в конце этапа по всему диффу (бэкенд + фронтенд).
