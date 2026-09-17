"""SARIF 2.1.0 parser — extracts runs, tool info, and results from a SARIF file."""

from __future__ import annotations

import hashlib
import json
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


@dataclass
class SarifRun:
    scanner: str
    results: list[SarifResult] = field(default_factory=list)


def _extract_cwe(rule: dict[str, Any] | None) -> str | None:
    if not rule:
        return None
    for tag in rule.get("properties", {}).get("tags", []):
        tag_lower = tag.lower()
        if tag_lower.startswith("cwe-"):
            return tag.upper()
        if "external/cwe/" in tag_lower:
            parts = tag.split("/")
            return f"CWE-{parts[-1]}" if parts[-1].isdigit() else None
    for rel in rule.get("relationships", []):
        target = rel.get("target", {})
        tid = target.get("id", "")
        if tid.upper().startswith("CWE-"):
            return tid.upper()
    return None


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

        sarif_run = SarifRun(scanner=scanner)

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
            ))

        runs.append(sarif_run)

    return runs
