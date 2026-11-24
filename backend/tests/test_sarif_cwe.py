"""CWE из правила SARIF: в находку пишется только номер «CWE-N»."""

from __future__ import annotations

import json

import pytest

from app.services.sarif import parse_sarif


def _sarif(rule: dict) -> bytes:
    rule = {"id": "r1", **rule}
    return json.dumps({
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "Semgrep", "rules": [rule]}},
            "results": [{
                "ruleId": "r1", "level": "error", "message": {"text": "m"},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": "a.py"},
                                                    "region": {"startLine": 1}}}],
                "partialFingerprints": {"primaryLocationLineHash": "x"},
            }],
        }],
    }).encode()


@pytest.mark.parametrize(("rule", "expected"), [
    ({"properties": {"tags": ["CWE-89: Improper Neutralization of Special Elements"]}}, "CWE-89"),
    ({"properties": {"tags": ["security", "cwe-79"]}}, "CWE-79"),
    ({"properties": {"tags": ["external/cwe/cwe-502"]}}, "CWE-502"),
    ({"relationships": [{"target": {"id": "CWE-22: Path Traversal"}}]}, "CWE-22"),
    ({"properties": {"tags": ["CWE-abc"]}}, None),
])
def test_cwe_normalized_to_id(rule, expected):
    [run] = parse_sarif(_sarif(rule))
    assert run.results[0].cwe == expected
