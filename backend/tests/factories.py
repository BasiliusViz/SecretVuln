"""Фабрики тестовых данных."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity, Finding, GroupSource, Import, SlaPolicy, UserGroup
from app.models.finding import Severity
from app.models.import_ import ImportStatus
from app.services.entity_paths import slugify


def make_sarif(
    scanner: str = "Semgrep",
    results: list[dict[str, Any]] | tuple = (),
    provenance: dict[str, Any] | None = None,
) -> bytes:
    run: dict[str, Any] = {
        "tool": {"driver": {"name": scanner, "rules": []}},
        "results": [
            {
                "ruleId": r.get("rule_id", "rule.a"),
                "level": r.get("level", "error"),
                "message": {"text": r.get("message", "msg")},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": r.get("path", "app/a.py")},
                            "region": {"startLine": r.get("line", 1)},
                        }
                    }
                ],
                "partialFingerprints": {"primaryLocationLineHash": r["fp"]},
            }
            for r in results
        ],
    }
    if provenance is not None:
        run["versionControlProvenance"] = [provenance]
    return json.dumps({"version": "2.1.0", "runs": [run]}).encode()


async def make_entity(
    db: AsyncSession, name: str = "svc", parent_id=None, **kw: Any
) -> Entity:
    slug = kw.pop("slug", slugify(name))
    path = slug
    if parent_id is not None:
        parent = await db.get(Entity, parent_id)
        path = f"{parent.path_cache}/{slug}"
    entity = Entity(name=name, parent_id=parent_id, slug=slug, path_cache=path, **kw)
    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    return entity


async def make_import(db: AsyncSession, entity: Entity, **kw: Any) -> Import:
    imp = Import(
        entity_id=entity.id,
        filename=kw.pop("filename", "t.sarif"),
        storage_key=kw.pop("storage_key", "test/t.sarif"),
        status=kw.pop("status", ImportStatus.processing),
        **kw,
    )
    db.add(imp)
    await db.commit()
    await db.refresh(imp)
    return imp


async def make_finding(
    db: AsyncSession, entity: Entity, fingerprint: str = "fp1", **kw: Any
) -> Finding:
    finding = Finding(
        entity_id=entity.id,
        title=kw.pop("title", "SQL injection"),
        severity=kw.pop("severity", Severity.high),
        scanner=kw.pop("scanner", "Semgrep"),
        fingerprint=fingerprint,
        raw=kw.pop("raw", {}),
        **kw,
    )
    db.add(finding)
    await db.commit()
    await db.refresh(finding)
    return finding


async def make_group(db: AsyncSession, name: str = "team") -> UserGroup:
    group = UserGroup(name=name, source=GroupSource.manual)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


async def make_policy(
    db: AsyncSession, name: str = "Стандартная", *, is_default: bool = False, **days: Any
) -> SlaPolicy:
    values = {"critical": 15, "high": 30, "medium": 90, "low": 180, "info": None} | days
    policy = SlaPolicy(
        name=name, is_default=is_default, **{f"days_{k}": v for k, v in values.items()}
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return policy
