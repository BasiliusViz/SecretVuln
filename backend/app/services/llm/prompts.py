"""Промпт разбора находки встроенным ИИ. Общий, без подстройки под конкретную модель."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models import Finding
from app.services.sarif.normalizers import get_normalizer

PROMPT_VERSION = "triage-v1"
SNIPPET_LIMIT = 2000  # символов фрагмента кода
TEXT_LIMIT = 2000  # символов описания и сообщения


class TriageAnswer(BaseModel):
    title_plain: str
    explanation: str
    remediation: str
    verdict: Literal["true_positive", "false_positive", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    reasoning: str


SYSTEM_PROMPT = """Ты — специалист по безопасности приложений и разбираешь находку сканера.
Определи, настоящая ли это уязвимость, и объясни её разработчику простыми словами.
Ответь только одним JSON-объектом без пояснений вокруг, строго такой структуры:
{
  "title_plain": "короткое название проблемы простыми словами",
  "explanation": "что не так и чем это опасно, 2–5 предложений",
  "remediation": "как исправить, конкретно для этого кода",
  "verdict": "true_positive | false_positive | uncertain",
  "confidence": 0.0–1.0,
  "reasoning": "почему такой вердикт: на что в коде ты опирался"
}
Все тексты — на русском языке. Если данных мало, ставь "uncertain" и низкую уверенность."""


def is_secret_finding(finding: Finding) -> bool:
    """Находка-секрет: фрагмент кода в модель не отправляем (маскирование — этап 8)."""
    return get_normalizer(finding.scanner or "").name == "gitleaks" or "secret" in (
        finding.scanner or ""
    ).lower()


def _clip(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    return text if len(text) <= limit else text[:limit] + "…"


def _snippet(raw: dict[str, Any]) -> str | None:
    for loc in raw.get("locations") or []:
        phys = (loc or {}).get("physicalLocation") or {}
        for region_key in ("contextRegion", "region"):
            text = ((phys.get(region_key) or {}).get("snippet") or {}).get("text")
            if text:
                return text
    return None


def build_messages(finding: Finding) -> list[dict]:
    raw = finding.raw or {}
    location = finding.file_path
    if location and finding.line_start:
        location = f"{location}:{finding.line_start}"
    facts = {
        "Сканер": finding.scanner,
        "Правило": finding.rule_id,
        "Название правила": finding.title,
        "Описание правила": _clip(finding.description, TEXT_LIMIT),
        "Сообщение сканера": _clip(((raw.get("message") or {}).get("text")), TEXT_LIMIT),
        "Критичность": finding.severity.value if finding.severity else None,
        "CWE": finding.cwe,
        "Файл": location,
    }
    lines = [f"{k}: {v}" for k, v in facts.items() if v]
    if is_secret_finding(finding):
        lines.append("Фрагмент кода: не передаётся (находка — секрет).")
    else:
        snippet = _snippet(raw)
        if snippet:
            snippet = snippet[:SNIPPET_LIMIT]
            lines.append("Фрагмент кода:\n```\n" + snippet + "\n```")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Находка:\n" + "\n".join(lines)},
    ]

