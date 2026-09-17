"""Per-scanner severity normalizers.

Each scanner uses its own severity scheme; normalizers map to our unified
Severity enum (critical, high, medium, low, info).
"""

from __future__ import annotations

from typing import Protocol

from app.models.finding import Severity
from app.services.sarif.parser import SarifResult


class Normalizer(Protocol):
    name: str

    def severity(self, result: SarifResult) -> Severity: ...


class _SemgrepNormalizer:
    name = "semgrep"

    _MAP = {
        "error": Severity.high,
        "warning": Severity.medium,
        "note": Severity.low,
        "none": Severity.info,
    }

    def severity(self, result: SarifResult) -> Severity:
        tags = result.raw.get("properties", {}).get("tags", [])
        for tag in tags:
            tl = tag.lower()
            if tl in ("critical", "high", "medium", "low", "info"):
                return Severity(tl)
        return self._MAP.get(result.level, Severity.medium)


class _TrivyNormalizer:
    name = "trivy"

    _MAP = {
        "error": Severity.high,
        "warning": Severity.medium,
        "note": Severity.low,
        "none": Severity.info,
    }

    def severity(self, result: SarifResult) -> Severity:
        precision = result.raw.get("properties", {}).get("precision", "")
        if precision.lower() == "very-high":
            return Severity.critical
        tags = result.raw.get("properties", {}).get("tags", [])
        for tag in tags:
            tl = tag.lower()
            if tl in ("critical", "high", "medium", "low", "info"):
                return Severity(tl)
        return self._MAP.get(result.level, Severity.medium)


class _GitleaksNormalizer:
    """Secrets are always high or critical — a leaked secret is never 'low'."""
    name = "gitleaks"

    def severity(self, result: SarifResult) -> Severity:
        rule_id = (result.rule_id or "").lower()
        if any(kw in rule_id for kw in ("private-key", "jwt", "token", "password")):
            return Severity.critical
        return Severity.high


class _CheckovNormalizer:
    name = "checkov"

    _MAP = {
        "error": Severity.high,
        "warning": Severity.medium,
        "note": Severity.low,
        "none": Severity.info,
    }

    def severity(self, result: SarifResult) -> Severity:
        sev = result.raw.get("properties", {}).get("severity", "")
        if sev.lower() in ("critical", "high", "medium", "low", "info"):
            return Severity(sev.lower())
        return self._MAP.get(result.level, Severity.medium)


class _DefaultNormalizer:
    name = "unknown"

    _MAP = {
        "error": Severity.high,
        "warning": Severity.medium,
        "note": Severity.low,
        "none": Severity.info,
    }

    def severity(self, result: SarifResult) -> Severity:
        return self._MAP.get(result.level, Severity.medium)


_REGISTRY: dict[str, Normalizer] = {}


def _register(cls: type) -> None:
    inst = cls()
    _REGISTRY[inst.name.lower()] = inst


_register(_SemgrepNormalizer)
_register(_TrivyNormalizer)
_register(_GitleaksNormalizer)
_register(_CheckovNormalizer)
_register(_DefaultNormalizer)


def get_normalizer(scanner_name: str) -> Normalizer:
    key = scanner_name.lower()
    for name, norm in _REGISTRY.items():
        if name in key or key in name:
            return norm
    return _REGISTRY["unknown"]
