"""Применение распарсенного SARIF к базе: создание, дедупликация, переоткрытие."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding, FindingStatus
from app.models.import_ import Import
from app.services.entity_tree import branch_allowed, branch_rejection_message, resolve_default_branch
from app.services.sarif import SarifRun, get_normalizer


class ImportRejected(Exception):
    """Импорт не должен попадать в бэклог (например, не основная ветка)."""


def _apply_provenance(imp: Import, runs: list[SarifRun]) -> None:
    for run in runs:
        imp.branch = imp.branch or run.branch
        imp.commit_sha = imp.commit_sha or run.revision


async def apply_import(db: AsyncSession, imp: Import, runs: list[SarifRun]) -> dict[str, Any]:
    """Пишет находки импорта в сессию. Не коммитит — это делает вызывающий."""
    _apply_provenance(imp, runs)
    default_branch = await resolve_default_branch(db, imp.entity_id)
    if not branch_allowed(imp.branch, default_branch):
        raise ImportRejected(branch_rejection_message(imp.branch, default_branch))

    created = updated = duplicates = total_results = 0
    scanner_name: str | None = None
    now = datetime.now(timezone.utc)

    for run in runs:
        scanner_name = run.scanner
        normalizer = get_normalizer(run.scanner)

        for result in run.results:
            total_results += 1
            existing = await db.scalar(
                select(Finding).where(
                    Finding.entity_id == imp.entity_id,
                    Finding.fingerprint == result.fingerprint,
                )
            )

            if existing:
                existing.last_seen = now
                existing.import_id = imp.id
                existing.raw = result.raw
                existing.scan_scope = imp.scan_scope
                existing.commit_sha = imp.commit_sha
                if existing.status == FindingStatus.fixed:
                    existing.status = FindingStatus.new
                    updated += 1
                else:
                    duplicates += 1
            else:
                db.add(
                    Finding(
                        entity_id=imp.entity_id,
                        import_id=imp.id,
                        title=result.title,
                        description=result.description,
                        severity=normalizer.severity(result),
                        status=FindingStatus.new,
                        scanner=run.scanner,
                        rule_id=result.rule_id,
                        cwe=result.cwe,
                        file_path=result.file_path,
                        line_start=result.line_start,
                        line_end=result.line_end,
                        fingerprint=result.fingerprint,
                        scan_scope=imp.scan_scope,
                        commit_sha=imp.commit_sha,
                        raw=result.raw,
                    )
                )
                created += 1

        await db.flush()

    imp.scanner = scanner_name
    return {
        "created": created,
        "updated": updated,
        "duplicates": duplicates,
        "total_results": total_results,
    }
