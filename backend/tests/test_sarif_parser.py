"""Извлечение CVE из SARIF (этап 10): Trivy, Grype и общие случаи."""

from __future__ import annotations

import json

from app.services.sarif.parser import extract_cves, parse_sarif


def _sarif(driver: str, rules: list[dict], results: list[dict]) -> bytes:
    return json.dumps({
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": driver, "rules": rules}}, "results": results}],
    }).encode()


def test_trivy_rule_id_is_cve():
    content = _sarif(
        "Trivy",
        [{"id": "CVE-2021-44228", "properties": {"tags": ["vulnerability", "security", "CRITICAL"]}}],
        [{"ruleId": "CVE-2021-44228", "level": "error", "message": {"text": "log4j"}}],
    )
    [run] = parse_sarif(content)
    assert run.results[0].cves == ["CVE-2021-44228"]


def test_grype_rule_id_with_package_suffix():
    content = _sarif(
        "grype",
        [{"id": "CVE-2022-22965-spring-beans", "properties": {"security-severity": "9.8"}}],
        [{"ruleId": "CVE-2022-22965-spring-beans", "message": {"text": "spring4shell"}}],
    )
    [run] = parse_sarif(content)
    assert run.results[0].cves == ["CVE-2022-22965"]


def test_ghsa_without_cve_gives_nothing():
    content = _sarif(
        "grype",
        [{"id": "GHSA-jfh8-c2jp-5v3q-log4j-core"}],
        [{"ruleId": "GHSA-jfh8-c2jp-5v3q-log4j-core", "message": {"text": "x"}}],
    )
    [run] = parse_sarif(content)
    assert run.results[0].cves == []


def test_tags_and_properties_lowercase_no_duplicates_in_order():
    rule = {
        "id": "pkg-vuln",
        "properties": {
            "tags": ["cve-2020-1234", "security"],
            "aliases": ["CVE-2019-99999", "CVE-2020-1234"],
        },
    }
    result = {"ruleId": "pkg-vuln", "properties": {"related": {"ids": ["cve-2018-0001"]}}}
    assert extract_cves(result, rule) == ["CVE-2020-1234", "CVE-2019-99999", "CVE-2018-0001"]


def test_message_text_is_not_scanned():
    # в тексте сообщения CVE может быть упомянут «для сравнения» — не берём
    result = {"ruleId": "semgrep.sqli", "message": {"text": "similar to CVE-2014-0160"}}
    assert extract_cves(result, None) == []


def test_extract_from_raw_only_for_backfill():
    # в raw лежит только result: rule недоступен, берём ruleId и свойства result
    assert extract_cves({"ruleId": "CVE-2023-4863"}, None) == ["CVE-2023-4863"]
