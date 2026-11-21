"""Загрузка файла справочника: замена таблицы источника целиком, пересчёт находок, аудит.

Всё в одной транзакции: удалить старые строки → вставить новые пачками → пересчитать
сводные поля находок → отметить источник `ok` → `record_audit`. Любая ошибка — откат
(старые данные остаются), источник `failed` с понятным текстом, ошибка тоже в журнале.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.intel import (
    IntelBdu,
    IntelBduCve,
    IntelCwe,
    IntelEpss,
    IntelKev,
    IntelSource,
    IntelSourceState,
    IntelStatus,
)
from app.services import audit
from app.services.intel.enrich import recompute_findings
from app.services.intel.parsers import IntelFormatError, parse_file

logger = logging.getLogger(__name__)

BATCH = 5000  # строк на INSERT: ≤ 5 колонок × 5000 — в пределах 32767 параметров

TABLES = {
    "epss": IntelEpss.__table__,
    "kev": IntelKev.__table__,
    "bdu": IntelBdu.__table__,
    "bdu_cve": IntelBduCve.__table__,
    "cwe": IntelCwe.__table__,
}
SOURCE_TABLES: dict[IntelSource, tuple[str, ...]] = {
    IntelSource.epss: ("epss",),
    IntelSource.kev: ("kev",),
    IntelSource.bdu: ("bdu_cve", "bdu"),
    IntelSource.cwe: ("cwe",),
}


async def get_state(db: AsyncSession, source: IntelSource, *, lock: bool = False) -> IntelSourceState:
    """Строка состояния источника; создаётся, если её нет (миграция создаёт все четыре)."""
    await db.execute(
        insert(IntelSourceState)
        .values(source=source, status=IntelStatus.idle)
        .on_conflict_do_nothing(index_elements=["source"])
    )
    return await db.get(
        IntelSourceState, source, with_for_update=lock, populate_existing=True
    )


async def _insert(db: AsyncSession, table_key: str, rows: list[dict[str, Any]]) -> None:
    # дубли внутри файла не роняют загрузку: первая запись остаётся
    await db.execute(insert(TABLES[table_key]).on_conflict_do_nothing(), rows)


async def replace_source(db: AsyncSession, source: IntelSource, path: Path):
    """Заменить таблицы источника содержимым файла. Не коммитит."""
    parsed = parse_file(source, path)
    for key in SOURCE_TABLES[source]:
        await db.execute(delete(TABLES[key]))
    batch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key, row in parsed.rows:
        batch[key].append(row)
        if len(batch[key]) >= BATCH:
            await _insert(db, key, batch.pop(key))
    for key, rows in batch.items():
        if rows:
            await _insert(db, key, rows)
    return parsed


def _changes(source: IntelSource, state: IntelSourceState, error: str | None) -> dict[str, Any]:
    return {
        "source": source.value,
        "status": state.status.value,
        "record_count": state.record_count,
        "file_date": state.file_date.isoformat() if state.file_date else None,
        **({"error": error} if error else {}),
    }


async def load_source(
    db: AsyncSession, source: IntelSource, path: Path, *, user_id: uuid.UUID | None = None
) -> IntelSourceState:
    """Загрузить файл в справочник. Коммитит сам; ошибка не поднимается — она в состоянии."""
    user = await db.get(User, user_id) if user_id else None
    error: str | None = None
    try:
        parsed = await replace_source(db, source, path)
        updated = await recompute_findings(db)
        state = await get_state(db, source)
        state.status = IntelStatus.ok
        state.record_count = parsed.count
        state.file_date = parsed.file_date
        state.loaded_at = datetime.now(timezone.utc)
        state.loaded_by = user_id
        state.error = None
        logger.info("Intel %s: %d records, %d findings updated", source.value, parsed.count, updated)
    except IntelFormatError as e:
        error = str(e)
    except Exception as e:  # noqa: BLE001 — любая ошибка: откат и понятный статус
        logger.exception("Intel %s load failed", source.value)
        error = f"Не удалось загрузить справочник: {type(e).__name__}"
    if error is not None:
        await db.rollback()
        user = await db.get(User, user_id) if user_id else None
        state = await get_state(db, source)
        state.status = IntelStatus.failed
        state.error = error[:2000]
    audit.record_audit(
        db, user, audit.INTEL_LOAD,
        target=("intel_source", None, source.value),
        changes=_changes(source, state, error),
    )
    await db.commit()
    return state
