"""ARQ worker — processes SARIF imports in the background."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.finding import Finding, FindingStatus
from app.models.import_ import Import, ImportStatus
from app.services.s3 import download_sarif
from app.services.sarif import get_normalizer, parse_sarif

logger = logging.getLogger("arq.worker")


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
            content = download_sarif(imp.s3_key)
            runs = parse_sarif(content)

            created = 0
            updated = 0
            duplicates = 0
            total_results = 0
            scanner_name = None

            for run in runs:
                scanner_name = run.scanner
                normalizer = get_normalizer(run.scanner)

                for result in run.results:
                    total_results += 1
                    severity = normalizer.severity(result)

                    existing = await db.scalar(
                        select(Finding).where(
                            Finding.entity_id == imp.entity_id,
                            Finding.fingerprint == result.fingerprint,
                        )
                    )

                    if existing:
                        existing.last_seen = datetime.now(timezone.utc)
                        existing.import_id = imp.id
                        existing.raw = result.raw
                        if existing.status == FindingStatus.fixed:
                            existing.status = FindingStatus.new
                            updated += 1
                        else:
                            duplicates += 1
                    else:
                        finding = Finding(
                            entity_id=imp.entity_id,
                            import_id=imp.id,
                            title=result.title,
                            description=result.description,
                            severity=severity,
                            status=FindingStatus.new,
                            scanner=run.scanner,
                            rule_id=result.rule_id,
                            cwe=result.cwe,
                            file_path=result.file_path,
                            line_start=result.line_start,
                            line_end=result.line_end,
                            fingerprint=result.fingerprint,
                            raw=result.raw,
                        )
                        db.add(finding)
                        created += 1

                await db.flush()

            imp.scanner = scanner_name
            imp.status = ImportStatus.done
            imp.stats = {
                "created": created,
                "updated": updated,
                "duplicates": duplicates,
                "total_results": total_results,
            }
            imp.finished_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(
                "Import %s done: %d created, %d updated, %d duplicates",
                import_id, created, updated, duplicates,
            )

        except Exception:
            await db.rollback()
            async with session_factory() as db2:
                imp2 = await db2.get(Import, import_id)
                if imp2:
                    imp2.status = ImportStatus.failed
                    import traceback
                    imp2.error = traceback.format_exc()[-2000:]
                    imp2.finished_at = datetime.now(timezone.utc)
                    await db2.commit()
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
