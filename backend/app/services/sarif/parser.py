"""SARIF 2.1.0 parser — extracts runs, tool info, and results from a SARIF file."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SarifResult:
    rule_id: str | None
    title: str
    description: str | None
    level: str
    file_path: str | None
    line_start: int | None
    line_end: int | None
    fingerprint: str
    cwe: str | None
    raw: dict[str, Any]
    help: str | None = None
    cves: list[str] = field(default_factory=list)


@dataclass
class SarifRun:
    scanner: str
    results: list[SarifResult] = field(default_factory=list)
    # Из runs[].versionControlProvenance[0] — если сканер его заполнил
    branch: str | None = None
    revision: str | None = None
    repository_uri: str | None = None


# Только номер: Semgrep пишет теги вида «CWE-89: Improper Neutralization …», справочник ищет «CWE-89»
CWE_PREFIX_RE = re.compile(r"CWE-(\d+)(?!\d)", re.IGNORECASE)


def _cwe_id(value: str) -> str | None:
    m = CWE_PREFIX_RE.match(value.strip())
    return f"CWE-{m.group(1)}" if m else None


def _extract_cwe(rule: dict[str, Any] | None) -> str | None:
    if not rule:
        return None
    for tag in rule.get("properties", {}).get("tags", []):
        if not isinstance(tag, str):
            continue
        tag_lower = tag.lower()
        if tag_lower.startswith("cwe-"):
            return _cwe_id(tag)
        if "external/cwe/" in tag_lower:
            last = tag.rstrip("/").split("/")[-1]  # CodeQL: external/cwe/cwe-502
            return f"CWE-{last}" if last.isdigit() else _cwe_id(last)
    for rel in rule.get("relationships", []):
        target = rel.get("target", {})
        tid = target.get("id", "")
        if isinstance(tid, str) and tid.upper().startswith("CWE-"):
            return _cwe_id(tid)
    return None


# длина ограничена: cve_id в БД — varchar(32)
CVE_RE = re.compile(r"CVE-\d{4}-\d{4,20}(?!\d)", re.IGNORECASE)


def _strings(value: Any):
    """Все строки внутри значения (строка, список, словарь — рекурсивно), по порядку."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def extract_cves(result: dict[str, Any], rule: dict[str, Any] | None) -> list[str]:
    """CVE находки: ruleId, rule.id, теги и свойства правила, свойства result.

    Верхний регистр, без дублей, по порядку. Текст сообщения не смотрим — там CVE
    бывает упомянут для сравнения. GHSA без CVE не разрешаем.
    """
    sources: list[Any] = [result.get("ruleId")]
    if rule:
        sources += [rule.get("id"), rule.get("properties")]
    sources.append(result.get("properties"))
    seen: dict[str, None] = {}
    for text in _strings(sources):
        for m in CVE_RE.findall(text):
            seen.setdefault(m.upper(), None)
    return list(seen)


def _compute_fingerprint(result: dict[str, Any], rule_id: str | None, file_path: str | None) -> str:
    pf = result.get("partialFingerprints", {})
    if pf:
        if "primaryLocationLineHash" in pf:
            return pf["primaryLocationLineHash"]
        return next(iter(pf.values()))

    snippet = ""
    locs = result.get("locations", [])
    if locs:
        region = locs[0].get("physicalLocation", {}).get("region", {})
        snippet = region.get("snippet", {}).get("text", "")

    raw = f"{rule_id or ''}|{file_path or ''}|{snippet}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _rule_help(rule: dict[str, Any] | None) -> str | None:
    if not rule:
        return None
    help_ = rule.get("help") or {}
    return help_.get("markdown") or help_.get("text")


def _build_rules_map(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    driver = run.get("tool", {}).get("driver", {})
    rules = driver.get("rules", [])
    return {r["id"]: r for r in rules if "id" in r}


def parse_sarif(content: bytes) -> list[SarifRun]:
    data = json.loads(content)
    runs: list[SarifRun] = []

    for run_data in data.get("runs", []):
        driver = run_data.get("tool", {}).get("driver", {})
        scanner = driver.get("name", "unknown")
        rules_map = _build_rules_map(run_data)

        vcp = (run_data.get("versionControlProvenance") or [{}])[0]
        sarif_run = SarifRun(
            scanner=scanner,
            branch=vcp.get("branch"),
            revision=vcp.get("revisionId"),
            repository_uri=vcp.get("repositoryUri"),
        )

        for result in run_data.get("results", []):
            rule_id = result.get("ruleId")
            rule = rules_map.get(rule_id) if rule_id else None

            title = (
                result.get("message", {}).get("text")
                or (rule.get("shortDescription", {}).get("text") if rule else None)
                or rule_id
                or "Unknown finding"
            )
            description = (
                rule.get("fullDescription", {}).get("text") if rule else None
            ) or result.get("message", {}).get("text")

            level = result.get("level", "warning")

            file_path = None
            line_start = None
            line_end = None
            locs = result.get("locations", [])
            if locs:
                phys = locs[0].get("physicalLocation", {})
                uri = phys.get("artifactLocation", {}).get("uri")
                if uri:
                    file_path = uri
                region = phys.get("region", {})
                line_start = region.get("startLine")
                line_end = region.get("endLine")

            fingerprint = _compute_fingerprint(result, rule_id, file_path)
            cwe = _extract_cwe(rule)

            sarif_run.results.append(SarifResult(
                rule_id=rule_id,
                title=title[:512] if title else "Unknown finding",
                description=description,
                level=level,
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                fingerprint=fingerprint,
                cwe=cwe,
                raw=result,
                help=_rule_help(rule),
                cves=extract_cves(result, rule),
            ))

        runs.append(sarif_run)

    return runs
