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


async def make_memory(db: AsyncSession, entity: Entity, **kw: Any):
    """Правило команды; по умолчанию действующее «ложное» по rule_id=rule.a."""
    from app.models import DecisionType, MemoryStatus, TriageMemory

    if not any(k in kw for k in ("scanner", "rule_id", "cwe", "path_glob")):
        kw["rule_id"] = "rule.a"
    memory = TriageMemory(
        entity_id=entity.id,
        decision=kw.pop("decision", DecisionType.false_positive),
        status=kw.pop("status", MemoryStatus.approved),
        reason=kw.pop("reason", "Тестовый код"),
        **kw,
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return memory


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


class FakeEmbedClient:
    """Детерминированные эмбеддинги без модели: мешок слов, свёрнутый в 1024 измерения.
    Тексты с общими словами — близкие векторы, так что порядок похожих осмыслен."""

    def __init__(self, model: str = "fake-embed", dim: int = 1024, error: bool = False,
                 poison: str | None = None):
        self.model = model
        self.dim = dim
        self.error = error
        self.poison = poison  # пачка с этой подстрокой падает (модель не принимает текст)
        self.calls: list[list[str]] = []

    def vector(self, text: str) -> list[float]:
        import hashlib
        import math
        import re

        v = [0.0] * self.dim
        for word in re.findall(r"\w+", text.lower()):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from app.services.llm import LlmError, LlmRejected

        self.calls.append(list(texts))
        if self.error:
            raise LlmError("модель эмбеддингов недоступна")
        if self.poison and any(self.poison in t for t in texts):
            raise LlmRejected("400: текст не принят")
        return [self.vector(t) for t in texts]
