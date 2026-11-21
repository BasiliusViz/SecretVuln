"""Встроенный справочник CWE и дозаполнение CVE у старых находок.

`data/cwe.json` сгенерирован из MITRE (`cwec_v5.0.xml`) парсером `parsers._cwe`:
категория — из представления 1400. Загружается при `seed-roles`, только если
таблица пуста (загруженный администратором файл не перезаписываем).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Finding
from app.models.intel import IntelCwe, IntelSource, IntelStatus
from app.services.intel.enrich import recompute_findings
from app.services.intel.loader import BATCH, _insert, get_state
from app.services.sarif.parser import extract_cves

CWE_FILE = Path(__file__).parent / "data" / "cwe.json"


async def seed_builtin_cwe(db: AsyncSession) -> int:
    """Загрузить встроенный CWE в пустую таблицу. Возвращает число записей (0 — уже есть)."""
    if await db.scalar(select(func.count()).select_from(IntelCwe)):
        return 0
    data = json.loads(CWE_FILE.read_text(encoding="utf-8"))
    items = data["items"]
    for i in range(0, len(items), BATCH):
        await _insert(db, "cwe", items[i:i + BATCH])
    state = await get_state(db, IntelSource.cwe)
    state.status = IntelStatus.ok
    state.record_count = len(items)
    state.file_date = date.fromisoformat(data["file_date"])
    state.loaded_at = datetime.now(timezone.utc)
    state.loaded_by = None
    state.error = None
    await db.commit()
    return len(items)


async def backfill_cves(db: AsyncSession, batch: int = 1000) -> tuple[int, int]:
    """CVE по `raw` для всех находок + пересчёт сводных полей. Идемпотентно.

    В `raw` лежит только result SARIF (без правила), поэтому CVE из свойств правила
    у старых находок не восстановить — их подхватит следующий импорт.
    Возвращает (находок с изменёнными cves, находок с изменёнными сводными полями).
    """
    changed = 0
    last_number = 0
    while True:
        rows = (await db.execute(
            select(Finding.id, Finding.number, Finding.raw, Finding.cves)
            .where(Finding.number > last_number)
            .order_by(Finding.number)
            .limit(batch)
        )).all()
        if not rows:
            break
        for fid, number, raw, cves in rows:
            last_number = number
            new = extract_cves(raw or {}, None)
            # то, что импорт нашёл в свойствах правила, не теряем
            merged = list(dict.fromkeys([*(cves or []), *new]))
            if merged != list(cves or []):
                await db.execute(
                    Finding.__table__.update().where(Finding.id == fid).values(cves=merged)
                )
                changed += 1
        await db.commit()
    updated = await recompute_findings(db)
    await db.commit()
    return changed, updated
