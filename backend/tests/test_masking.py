"""Маскирование секретов перед эмбеддингом и промптом."""

from __future__ import annotations

import pytest

from app.models import Finding
from app.models.finding import Severity
from app.services.masking import MASK, is_secret_finding, mask


@pytest.mark.parametrize("secret", [
    "AKIAIOSFODNN7EXAMPLE",
    "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
    "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz",
    "sv_0123456789abcdef0123456789abcdef",
    "xoxb-1234567890-abcdefghij",
    "sk-proj-abcdefghijklmnopqrstuvwx",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlLXNpZ24",
])
def test_known_prefixes(secret):
    out = mask(f"key = '{secret}' # used")
    assert secret not in out
    assert MASK in out


def test_private_key_block():
    text = "a\n-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nIBAAK\n-----END RSA PRIVATE KEY-----\nb"
    out = mask(text)
    assert "MIIEow" not in out and "PRIVATE KEY" not in out
    assert out.startswith("a\n") and out.endswith("\nb")


@pytest.mark.parametrize("line", [
    'password = "hunter2"',
    "DB_PASSWD: s3cr3t",
    "api_key='abc'",
    'client_secret = "zzz"',
    "AUTH_TOKEN=qwerty",
])
def test_assignments(line):
    out = mask(line)
    value = line.split("=")[-1].split(":")[-1].strip(" '\"")
    assert value not in out
    assert MASK in out


def test_high_entropy_string():
    blob = "Zx9Qw3Er7Ty1Ui5Op2As8Df4"  # 24 символа, все разные — энтропия > 4
    assert blob not in mask(f"x = call('{blob}')")


def test_plain_code_untouched():
    code = (
        "def get_user(user_id):\n"
        "    query = 'SELECT * FROM users WHERE id = ' + user_id\n"
        "    return db.execute(query)  # CWE-89 sql injection\n"
        "src/main/java/com/example/controllers/UserController.java\n"
    )
    assert mask(code) == code


def test_mask_none_and_empty():
    assert mask(None) == ""
    assert mask("") == ""


def test_secret_finding_detection_moved_here():
    finding = Finding(scanner="gitleaks", rule_id="aws", title="t", severity=Severity.high, raw={})
    assert is_secret_finding(finding)
    assert not is_secret_finding(
        Finding(scanner="Semgrep", rule_id="python.sqli", title="SQLi", raw={})
    )
