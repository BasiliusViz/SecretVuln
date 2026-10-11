"""Маскирование секретов перед отправкой текста находки наружу (эмбеддинги, LLM).

Находка-секрет (`is_secret_finding`) не отдаёт ни сообщения, ни кода — только сканер,
правило, CWE и путь. Для остальных `mask()` заменяет похожее на секрет на `[MASKED]`:
известные префиксы ключей, присваивания `password = …`, высокоэнтропийные строки.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from app.models import Finding
from app.services.sarif.normalizers import get_normalizer

MASK = "[MASKED]"

# --- находка-секрет ---------------------------------------------------------------------

# Признаки секрета помимо сканера: CWE, слова в правиле, теги/категория SARIF. Лучше лишний
# раз не отправить фрагмент, чем отправить ключ наружу.
_SECRET_CWES = {798, 259, 321, 522, 312, 256, 260}
_SECRET_WORDS = (
    "secret", "credential", "password", "passwd", "token", "private", "-key", "_key", ".key",
    "apikey", "jwt", "webhook", "leak",
)
_CWE_NUM = re.compile(r"CWE[-_ ]?(\d+)", re.IGNORECASE)


def _cwe_numbers(text: str) -> set[int]:
    return {int(n) for n in _CWE_NUM.findall(text)}


def _raw_markers(raw: dict[str, Any]) -> str:
    props = raw.get("properties") or {}
    tags = props.get("tags") or []
    parts = [str(t) for t in tags if isinstance(t, str)]
    for key in ("category", "class", "type"):
        if isinstance(props.get(key), str):
            parts.append(props[key])
    return " ".join(parts).lower()


def is_secret_finding(finding: Finding) -> bool:
    """Находка-секрет: ни фрагмент кода, ни сообщение сканера наружу не отправляем."""
    scanner = (finding.scanner or "").lower()
    if get_normalizer(scanner).name == "gitleaks" or "secret" in scanner:
        return True
    markers = _raw_markers(finding.raw or {})
    if _cwe_numbers(f"{finding.cwe or ''} {markers}") & _SECRET_CWES:
        return True
    text = f"{finding.rule_id or ''} {finding.title or ''} {markers}".lower()
    return any(word in text for word in _SECRET_WORDS)


def message_of(raw: dict[str, Any]) -> str | None:
    """Сообщение сканера из SARIF result."""
    return (raw.get("message") or {}).get("text") or None


def snippet_of(raw: dict[str, Any]) -> str | None:
    """Фрагмент кода из первой локации SARIF result (contextRegion приоритетнее)."""
    for loc in raw.get("locations") or []:
        phys = (loc or {}).get("physicalLocation") or {}
        for region_key in ("contextRegion", "region"):
            text = ((phys.get(region_key) or {}).get("snippet") or {}).get("text")
            if text:
                return text
    return None


# --- маскирование текста ----------------------------------------------------------------

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)
_PREFIXES = re.compile(
    r"\b(?:"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sv_[A-Za-z0-9_-]{16,}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}"
    r"|sk-[A-Za-z0-9_-]{20,}"
    r"|eyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]+"
    r")"
)
_ASSIGN = re.compile(
    r"(?i)(\b[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key"
    r"|private[_-]?key)[\w.-]*[\"']?\s*[:=]\s*)"
    r"(?:([\"'])([^\"'\n]*)\2|([^\s\"'=,;()\[\]{}]+))"
)
# значения, которые точно не секрет: типы, пустые и служебные слова
_NOT_SECRET = {"none", "null", "nil", "true", "false", "str", "string", "int", "bool", "bytes"}
_TOKEN = re.compile(r"[A-Za-z0-9+_=-]{20,}")
ENTROPY_MIN_LEN = 20
ENTROPY_THRESHOLD = 4.0


def _entropy(s: str) -> float:
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


def _mask_assign(m: re.Match) -> str:
    quote, quoted, bare = m.group(2), m.group(3), m.group(4)
    value = quoted if quote else bare
    if not value or value.lower() in _NOT_SECRET:
        return m.group(0)
    if not quote:
        # без кавычек: вызов или обращение к атрибуту — это код, а не значение
        rest = m.string[m.end():m.end() + 1]
        if rest in ("(", ".") or "." in value:
            return m.group(0)
        return m.group(1) + MASK
    return f"{m.group(1)}{quote}{MASK}{quote}"


def _mask_entropy(m: re.Match) -> str:
    s = m.group(0)
    # только смесь букв и цифр: длинные идентификаторы вида snake_case не трогаем
    if not (re.search(r"\d", s) and re.search(r"[A-Za-z]", s)):
        return s
    return MASK if _entropy(s) >= ENTROPY_THRESHOLD else s


def mask(text: str | None) -> str:
    """Заменить похожее на секрет на `[MASKED]`. Обычный код не меняется."""
    if not text:
        return ""
    text = _PRIVATE_KEY.sub(MASK, text)
    text = _PREFIXES.sub(MASK, text)
    text = _ASSIGN.sub(_mask_assign, text)
    return _TOKEN.sub(_mask_entropy, text)
