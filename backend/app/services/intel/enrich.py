"""Сводные поля находки из справочников: `epss_max`, `kev`, `has_bdu` по её `cves`.

Пересчёт — один `UPDATE … FROM` в базе: после загрузки справочника — по всем
находкам с CVE, при импорте — по набору находок. Сырой SQL не трогает
`updated_at` (векторы и прочие «изменилась находка» не срабатывают).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.ext.asyncio import AsyncSession

_SQL = """
UPDATE findings f
SET epss_max = s.epss_max, kev = s.kev, has_bdu = s.has_bdu
FROM (
    SELECT x.id,
           (SELECT max(e.epss) FROM intel_epss e WHERE e.cve_id = ANY(x.cves)) AS epss_max,
           EXISTS (SELECT 1 FROM intel_kev k WHERE k.cve_id = ANY(x.cves)) AS kev,
           EXISTS (SELECT 1 FROM intel_bdu_cve b WHERE b.cve_id = ANY(x.cves)) AS has_bdu
    FROM findings x
    WHERE {where}
) s
WHERE f.id = s.id
  AND (f.epss_max IS DISTINCT FROM s.epss_max OR f.kev <> s.kev OR f.has_bdu <> s.has_bdu)
"""


async def recompute_findings(db: AsyncSession) -> int:
    """Все находки, у которых есть CVE (и те, где сводные поля остались от прошлых данных)."""
    result = await db.execute(
        text(_SQL.format(where="x.cves <> '{}' OR x.kev OR x.has_bdu OR x.epss_max IS NOT NULL"))
    )
    return result.rowcount or 0


async def enrich_findings(db: AsyncSession, ids: Sequence[uuid.UUID]) -> int:
    """Только указанные находки (новые и обновлённые при импорте)."""
    if not ids:
        return 0
    stmt = text(_SQL.format(where="x.id = ANY(:ids)")).bindparams(
        bindparam("ids", type_=ARRAY(UUID(as_uuid=True)))
    )
    result = await db.execute(stmt, {"ids": list(ids)})
    return result.rowcount or 0
