"""Применение распарсенного SARIF к базе: создание, дедупликация, переоткрытие, автозакрытие."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import OPEN_STATUSES, Finding, FindingStatus
from app.models.finding_event import FindingEventType
from app.models.import_ import Import
from app.services.entity_settings import is_http_url, normalize_repo_url
from app.services.entity_tree import branch_allowed, branch_rejection_message, resolve_default_branch
from app.services.events import record_event
from app.services.ownership import build_resolver, reassign_entity
from app.services.sarif import SarifRun, get_normalizer


class ImportRejected(Exception):
    """Импорт не должен попадать в бэклог (например, не основная ветка)."""


def _apply_provenance(imp: Import, runs: list[SarifRun]) -> None:
    for run in runs:
        imp.branch = imp.branch or run.branch
        imp.commit_sha = imp.commit_sha or run.revision
        if imp.repo_url is None and run.repository_uri and is_http_url(run.repository_uri):
            imp.repo_url = normalize_repo_url(run.repository_uri)


async def _close_missing(
    db: AsyncSession, imp: Import, seen: dict[str, set[str]]
) -> tuple[int, list[str]]:
    """Закрывает открытые находки объёма (актив, сканер, scan_scope), которых нет в отчёте."""
    closed = 0
    warnings: list[str] = []
    for scanner, fingerprints in seen.items():
        q = select(Finding).where(
            Finding.entity_id == imp.entity_id,
            Finding.scanner == scanner,
            Finding.scan_scope.is_not_distinct_from(imp.scan_scope),
            Finding.status.in_(OPEN_STATUSES),
        )
        if fingerprints:
            q = q.where(Finding.fingerprint.not_in(fingerprints))
        missing = list(await db.scalars(q))
        if not missing:
            continue
        if not fingerprints and not imp.confirm_empty:
            warnings.append(
                f"{scanner}: отчёт пустой — автозакрытие {len(missing)} находок пропущено "
                "(передайте confirm_empty=true, если уязвимостей действительно нет)"
            )
            continue
        for finding in missing:
            previous = finding.status
            finding.status = FindingStatus.fixed
            record_event(
                db, finding.id, FindingEventType.auto_fixed,
                from_status=previous, to_status=FindingStatus.fixed,
                reason="Не обнаружена при повторном скане",
                payload={"import_id": str(imp.id)},
            )
            closed += 1
    return closed, warnings


async def apply_import(db: AsyncSession, imp: Import, runs: list[SarifRun]) -> dict[str, Any]:
    """Пишет находки импорта в сессию. Не коммитит — это делает вызывающий."""
    _apply_provenance(imp, runs)
    default_branch = await resolve_default_branch(db, imp.entity_id)
    if not branch_allowed(imp.branch, default_branch):
        raise ImportRejected(branch_rejection_message(imp.branch, default_branch))

    resolver = await build_resolver(db, imp.entity_id)

    created = updated = duplicates = total_results = 0
    scanner_name: str | None = None
    now = datetime.now(timezone.utc)
    seen: dict[str, set[str]] = {}

    for run in runs:
        scanner_name = run.scanner
        # пустой отчёт сканера тоже участвует в автозакрытии
        scanner_seen = seen.setdefault(run.scanner, set())
        normalizer = get_normalizer(run.scanner)

        for result in run.results:
            total_results += 1
            scanner_seen.add(result.fingerprint)
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
                existing.help_text = result.help
                if existing.status == FindingStatus.fixed:
                    existing.status = FindingStatus.new
                    record_event(
                        db, existing.id, FindingEventType.reopened,
                        from_status=FindingStatus.fixed, to_status=FindingStatus.new,
                        payload={"import_id": str(imp.id)},
                    )
                    updated += 1
                else:
                    duplicates += 1
            else:
                # id задаём явно, чтобы сразу сослаться на находку из события
                finding_id = uuid.uuid4()
                assignee_group_id = resolver.resolve(result.file_path)
                db.add(
                    Finding(
                        id=finding_id,
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
                        help_text=result.help,
                        assignee_group_id=assignee_group_id,
                    )
                )
                record_event(
                    db, finding_id, FindingEventType.imported,
                    to_status=FindingStatus.new,
                    payload={
                        "import_id": str(imp.id),
                        "assignee_group_id": str(assignee_group_id) if assignee_group_id else None,
                    },
                )
                created += 1

        await db.flush()

    closed, warnings = 0, []
    if imp.close_missing:
        closed, warnings = await _close_missing(db, imp, seen)
        await db.flush()

    reassigned = await reassign_entity(db, imp.entity_id)

    imp.scanner = scanner_name
    stats: dict[str, Any] = {
        "created": created,
        "updated": updated,
        "duplicates": duplicates,
        "total_results": total_results,
        "closed": closed,
        "reassigned": reassigned,
    }
    if warnings:
        stats["warnings"] = warnings
    return stats
