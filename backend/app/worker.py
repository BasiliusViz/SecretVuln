"""ARQ worker — processes SARIF imports in the background."""

from __future__ import annotations

import logging
import traceback
import uuid
from datetime import datetime, timezone

from arq import create_pool, cron
from arq.connections import ArqRedis, RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.import_ import Import, ImportStatus
from app.services import builtin_triage
from app.services.import_processing import ImportRejected, apply_import
from app.services.llm import LlmError
from app.services.risk_expiry import expire_risk_acceptances
from app.services.storage import load_sarif
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
            runs = parse_sarif(load_sarif(imp.storage_key))
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
            return
        except Exception:
            await db.rollback()
            await _mark_failed(session_factory, import_id, traceback.format_exc())
            logger.exception("Import %s failed", import_id)
            return

        await enqueue_auto_triage(ctx, db, imp.id)


async def enqueue_auto_triage(ctx: dict, db: AsyncSession, import_id: uuid.UUID) -> None:
    """Новые находки импорта — в очередь встроенного ИИ. Сбой тут импорт не роняет."""
    try:
        ids = await builtin_triage.pick_auto_triage(db, import_id)
        for finding_id in ids:
            await ctx["redis"].enqueue_job(
                "ai_triage_finding", str(finding_id), _job_id=f"ai:{finding_id}"
            )
        if ids:
            logger.info("Import %s: %d findings queued for AI triage", import_id, len(ids))
    except Exception:
        logger.exception("Import %s: AI triage enqueue failed", import_id)


async def ai_triage_finding(ctx: dict, finding_id: str) -> None:
    if not get_settings().ai_enabled:
        logger.info("AI triage of %s skipped: built-in AI is off", finding_id)
        return
    session_factory: async_sessionmaker = ctx["session_factory"]
    async with session_factory() as db:
        try:
            rows = await builtin_triage.triage_with_settings(db, uuid.UUID(finding_id))
            await db.commit()
        except LlmError as exc:
            await db.rollback()
            logger.warning("AI triage of %s failed: %s", finding_id, exc)
            return
    logger.info("AI triage of %s done: %d rows", finding_id, len(rows))


async def expire_risks(ctx: dict) -> None:
    session_factory: async_sessionmaker = ctx["session_factory"]
    async with session_factory() as db:
        reopened = await expire_risk_acceptances(db)
    logger.info("Risk expiry: %d findings reopened", reopened)


async def startup(ctx: dict) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    ctx["session_factory"] = async_sessionmaker(engine, expire_on_commit=False)


async def shutdown(ctx: dict) -> None:
    factory: async_sessionmaker = ctx.get("session_factory")
    if factory:
        await factory.kw["bind"].dispose()


class WorkerSettings:
    functions = [process_import, ai_triage_finding]
    cron_jobs = [cron(expire_risks, hour={3}, minute={0})]
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


async def enqueue_ai_triage(finding_id: str) -> None:
    """Ручной запуск разбора: без `_job_id`, чтобы повторный разбор не отбрасывался."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    await _pool.enqueue_job("ai_triage_finding", finding_id)
