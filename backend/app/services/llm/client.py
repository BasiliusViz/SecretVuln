"""Клиент OpenAI-совместимых `/chat/completions` и `/embeddings` на httpx (Ollama, vLLM,
шлюз, облако).

Под конкретную модель не подстраиваемся: просим `json_object`, вырезаем `<think>` и
markdown-ограду, проверяем ответ Pydantic-схемой; невалидный ответ — один повтор.
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings

T = TypeVar("T", bound=BaseModel)

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class LlmError(Exception):
    """Модель недоступна или так и не вернула валидный ответ."""


def extract_json(content: str) -> str:
    text = _THINK.sub("", content).strip()
    text = _FENCE.sub("", text).strip()
    # модель могла добавить текст вокруг объекта — берём от первой { до последней }
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


class LlmClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 60,
        transport: httpx.AsyncBaseTransport | None = None,
        dim: int | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or None
        self.timeout = timeout
        self.transport = transport
        self.dim = dim  # ожидаемая размерность эмбеддингов; None — не проверять

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def _complete(self, http: httpx.AsyncClient, messages: list[dict]) -> str:
        try:
            resp = await http.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                },
            )
        except httpx.HTTPError as exc:
            raise LlmError(f"Модель недоступна: {exc!r}") from exc
        if not resp.is_success:
            raise LlmError(f"Модель ответила {resp.status_code}: {resp.text[:500]}")
        try:
            return resp.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LlmError(f"Непонятный ответ модели: {resp.text[:500]}") from exc

    async def chat_json(self, messages: list[dict], schema: type[T]) -> T:
        history = list(messages)
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as http:
            for attempt in range(2):
                content = await self._complete(http, history)
                try:
                    return schema.model_validate(json.loads(extract_json(content)))
                except (ValueError, ValidationError) as exc:
                    if attempt == 1:
                        raise LlmError(f"Невалидный ответ модели: {exc}") from exc
                    history += [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": "Ответ не прошёл проверку. Верни только один "
                            f"JSON-объект нужной структуры. Ошибка: {str(exc)[:500]}",
                        },
                    ]
        raise LlmError("unreachable")  # pragma: no cover

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Векторы текстов одним запросом, в порядке входа. Пачки режет вызывающий."""
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as http:
                resp = await http.post(
                    f"{self.base_url}/embeddings",
                    headers=self._headers(),
                    json={"model": self.model, "input": texts},
                )
        except httpx.HTTPError as exc:
            raise LlmError(f"Модель эмбеддингов недоступна: {exc!r}") from exc
        if not resp.is_success:
            raise LlmError(f"Модель эмбеддингов ответила {resp.status_code}: {resp.text[:500]}")
        try:
            items = sorted(resp.json()["data"], key=lambda d: d["index"])
            vectors = [[float(x) for x in d["embedding"]] for d in items]
        except (ValueError, KeyError, TypeError) as exc:
            raise LlmError(f"Непонятный ответ модели эмбеддингов: {resp.text[:500]}") from exc
        if len(vectors) != len(texts):
            raise LlmError(f"Модель вернула {len(vectors)} векторов на {len(texts)} текстов")
        if self.dim is not None and any(len(v) != self.dim for v in vectors):
            raise LlmError(
                f"Размерность вектора {len(vectors[0])} не совпадает с SV_AI_EMBED_DIM={self.dim}"
            )
        return vectors


def client_from_settings() -> LlmClient:
    s = get_settings()
    return LlmClient(s.ai_base_url, s.ai_model, s.ai_api_key, s.ai_timeout)


def get_embed_client() -> LlmClient:
    s = get_settings()
    return LlmClient(s.embed_base_url, s.ai_embed_model, s.ai_api_key, s.ai_timeout,
                     dim=s.ai_embed_dim)
