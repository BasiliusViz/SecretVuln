"""Промпт разбора: что уходит в модель и схема ответа."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import Finding
from app.models.finding import Severity
from app.services.llm.prompts import (
    PROMPT_VERSION,
    SNIPPET_LIMIT,
    TriageAnswer,
    build_messages,
    is_secret_finding,
)


def _raw(snippet: str) -> dict:
    return {
        "ruleId": "python.sqli",
        "message": {"text": "Пользовательский ввод попадает в SQL"},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": "app/db.py"},
                    "region": {"startLine": 42, "snippet": {"text": snippet}},
                }
            }
        ],
    }


def _finding(**kw) -> Finding:
    values = dict(
        title="SQL injection",
        description="Формирование SQL из строки",
        severity=Severity.high,
        scanner="Semgrep",
        rule_id="python.sqli",
        cwe="CWE-89",
        file_path="app/db.py",
        line_start=42,
        raw=_raw('cur.execute("SELECT * FROM t WHERE id=" + uid)'),
    )
    return Finding(**(values | kw))


def _user_text(messages: list[dict]) -> str:
    assert messages[0]["role"] == "system"
    return messages[-1]["content"]


def test_prompt_version():
    assert PROMPT_VERSION == "triage-v1"


def test_messages_contain_finding_facts():
    messages = build_messages(_finding())
    system = messages[0]["content"]
    assert "JSON" in system and "русском" in system
    text = _user_text(messages)
    for part in (
        "python.sqli",
        "SQL injection",
        "Формирование SQL из строки",
        "Пользовательский ввод попадает в SQL",
        "Semgrep",
        "high",
        "CWE-89",
        "app/db.py:42",
        'cur.execute("SELECT * FROM t WHERE id=" + uid)',
    ):
        assert part in text, part


def test_snippet_is_truncated():
    long = "x" * (SNIPPET_LIMIT * 3)
    text = _user_text(build_messages(_finding(raw=_raw(long))))
    assert "x" * SNIPPET_LIMIT in text
    assert "x" * (SNIPPET_LIMIT + 1) not in text


def test_secret_finding_has_no_snippet():
    secret = "AKIAIOSFODNN7EXAMPLE-super-secret"
    finding = _finding(scanner="gitleaks", rule_id="aws-access-token", raw=_raw(secret))
    assert is_secret_finding(finding)
    text = _user_text(build_messages(finding))
    assert secret not in text
    assert "aws-access-token" in text


def test_non_secret_scanner():
    assert not is_secret_finding(_finding(scanner="Trivy"))


def test_answer_schema():
    ok = TriageAnswer.model_validate(
        {
            "title_plain": "Инъекция SQL",
            "explanation": "…",
            "remediation": "Параметризуйте запрос",
            "verdict": "true_positive",
            "confidence": 0.8,
            "reasoning": "Ввод не очищается",
        }
    )
    assert ok.verdict == "true_positive"
    with pytest.raises(ValidationError):
        TriageAnswer.model_validate(ok.model_dump() | {"verdict": "maybe"})
    with pytest.raises(ValidationError):
        TriageAnswer.model_validate(ok.model_dump() | {"confidence": 1.5})
