"""Справочники обогащения: загрузка файлов EPSS / KEV / БДУ / CWE и их состояние.

Право `intel:manage` — только глобальное (`GLOBAL_ONLY`): справочник один на систему.
Файл сохраняется в хранилище, разбирает его воркер (`load_intel`) — он же пишет
журнал аудита (`intel.load`) с итогом или ошибкой.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_permission
from app.core.config import get_settings
from app.db.session import get_db
from app.models.intel import IntelSource, IntelStatus
from app.services import storage
from app.services.intel.loader import get_state
from app.services.intel.read import is_loading, sources_overview

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/intel", tags=["intel"])

# допустимые окончания имени файла (как их отдаёт источник)
EXTENSIONS: dict[IntelSource, tuple[str, ...]] = {
    IntelSource.epss: (".csv", ".csv.gz", ".gz"),
    IntelSource.kev: (".json",),
    IntelSource.bdu: (".xml", ".zip"),
    IntelSource.cwe: (".xml", ".zip"),
}


class IntelSourceRead(BaseModel):
    source: IntelSource
    status: IntelStatus
    loaded_at: datetime | None
    loaded_by: str | None  # email
    file_date: date | None
    record_count: int | None
    error: str | None
    stale: bool
    stale_after_days: int | None


class IntelUploadAccepted(BaseModel):
    source: IntelSource
    status: IntelStatus


def _size(file: UploadFile) -> int:
    if file.size is not None:
        return file.size
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    return size


@router.get("", response_model=list[IntelSourceRead])
async def list_sources(
    _: Principal = Depends(require_permission("intel", "manage")),
    db: AsyncSession = Depends(get_db),
) -> list[IntelSourceRead]:
    return [IntelSourceRead(**s) for s in await sources_overview(db)]


@router.post(
    "/{source}", response_model=IntelUploadAccepted, status_code=status.HTTP_202_ACCEPTED
)
async def upload_source(
    source: IntelSource,
    file: UploadFile,
    principal: Principal = Depends(require_permission("intel", "manage")),
    db: AsyncSession = Depends(get_db),
) -> IntelUploadAccepted:
    user_id = str(principal.user.id)  # до rollback: он истекает объекты сессии
    name = (file.filename or "").lower()
    allowed = EXTENSIONS[source]
    if not name.endswith(allowed):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Недопустимый файл: для этого справочника нужен {', '.join(allowed)}",
        )
    limit_mb = get_settings().intel_max_mb
    if _size(file) > limit_mb * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Файл больше {limit_mb} МБ"
        )
    if is_loading(await get_state(db, source)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Загрузка уже идёт")
    await db.rollback()  # не держим транзакцию, пока файл копируется в хранилище

    file.file.seek(0)
    key = storage.save_stream(file.file, file.filename or "intel", prefix=f"intel/{source.value}")
    state = await get_state(db, source, lock=True)  # параллельный запрос ждёт здесь
    if is_loading(state):
        await db.rollback()
        storage.delete(key)
        raise HTTPException(status.HTTP_409_CONFLICT, "Загрузка уже идёт")
    state.status = IntelStatus.loading
    state.started_at = datetime.now(timezone.utc)
    state.error = None
    await db.commit()

    from app.worker import enqueue_intel

    try:
        await enqueue_intel(source.value, key, user_id)
    except Exception:
        logger.exception("Intel %s: enqueue failed", source.value)
        state = await get_state(db, source)
        state.status = IntelStatus.failed
        state.error = "Очередь задач недоступна — попробуйте позже"
        await db.commit()
        storage.delete(key)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, state.error)
    return IntelUploadAccepted(source=source, status=IntelStatus.loading)
