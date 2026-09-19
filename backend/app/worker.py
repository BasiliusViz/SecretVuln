"""ARQ worker — processes SARIF imports in the background."""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.import_ import Import, ImportStatus
from app.services.import_processing import ImportRejected, apply_import
from app.services.s3 import download_sarif
from app.services.sarif import parse_sarif

logger = logging.getLogger("arq.worker")


async def _mark_failed(session_factory: async_sessionmaker, import_id: str, error: str) -> None:
    async with session_factory() as db:
        imp = await db.get(Import, import_id)
        if imp:
            imp.status = ImportStatus.failed
            imp.error = error[-2000:]
            imp.finished_at = datetime.now(timezone.utc)
            await db.commit()


async def process_import(ctx: dict, import_id: str) -> None:
    session_factory: async_sessionmaker = ctx["session_factory"]

    async with session_factory() as db:
        imp = await db.get(Import, import_id)
        if imp is None:
            logger.error("Import %s not found", import_id)
            return

        imp.status = ImportStatus.processing
        await db.commit()

        try:
            runs = parse_sarif(download_sarif(imp.s3_key))
            stats = await apply_import(db, imp, runs)
            imp.status = ImportStatus.done
            imp.stats = stats
            imp.finished_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info("Import %s done: %s", import_id, stats)
        except ImportRejected as exc:
            await db.rollback()
            await _mark_failed(session_factory, import_id, str(exc))
            logger.warning("Import %s rejected: %s", import_id, exc)
        except Exception:
            await db.rollback()
            await _mark_failed(session_factory, import_id, traceback.format_exc())
            logger.exception("Import %s failed", import_id)


async def startup(ctx: dict) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    ctx["session_factory"] = async_sessionmaker(engine, expire_on_commit=False)


async def shutdown(ctx: dict) -> None:
    factory: async_sessionmaker = ctx.get("session_factory")
    if factory:
        await factory.kw["bind"].dispose()


class WorkerSettings:
    functions = [process_import]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4
    job_timeout = 300


_pool: ArqRedis | None = None


async def enqueue_import(import_id: str) -> None:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    await _pool.enqueue_job("process_import", import_id)
