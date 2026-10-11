"""Клиент OpenAI-совместимого /chat/completions: разбор, <think>, повтор, ошибки."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.services.llm import LlmClient, LlmError


class Answer(BaseModel):
    verdict: str
    confidence: float


def _reply(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _client(handler, **kw) -> LlmClient:
    return LlmClient(
        base_url="http://llm.local/v1",
        model=kw.pop("model", "m1"),
        api_key=kw.pop("api_key", None),
        timeout=5,
        transport=httpx.MockTransport(handler),
    )


MESSAGES = [{"role": "user", "content": "привет"}]


async def test_parses_json_and_sends_request():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_reply('{"verdict": "true_positive", "confidence": 0.9}'))

    answer = await _client(handler, api_key="k-123").chat_json(MESSAGES, Answer)

    assert answer == Answer(verdict="true_positive", confidence=0.9)
    req = seen[0]
    assert str(req.url) == "http://llm.local/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer k-123"
    body = json.loads(req.content)
    assert body["model"] == "m1"
    assert body["messages"] == MESSAGES
    assert body["response_format"] == {"type": "json_object"}


async def test_no_auth_header_without_key():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=_reply('{"verdict": "x", "confidence": 0}'))

    await _client(handler).chat_json(MESSAGES, Answer)
    assert "authorization" not in seen[0].headers


async def test_strips_think_and_code_fence():
    content = (
        "<think>рассуждаю\nдолго</think>\n```json\n"
        '{"verdict": "uncertain", "confidence": 0.5}\n```'
    )

    def handler(request):
        return httpx.Response(200, json=_reply(content))

    answer = await _client(handler).chat_json(MESSAGES, Answer)
    assert answer.verdict == "uncertain"


async def test_retries_once_on_invalid_answer():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=_reply("это не json"))
        return httpx.Response(200, json=_reply('{"verdict": "ok", "confidence": 1}'))

    answer = await _client(handler).chat_json(MESSAGES, Answer)
    assert answer.verdict == "ok"
    assert len(calls) == 2


async def test_gives_up_after_second_invalid_answer():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_reply('{"verdict": "ok"}'))  # нет confidence

    with pytest.raises(LlmError):
        await _client(handler).chat_json(MESSAGES, Answer)
    assert len(calls) == 2


async def test_http_error_is_llm_error():
    def handler(request):
        return httpx.Response(500, text="boom")

    with pytest.raises(LlmError):
        await _client(handler).chat_json(MESSAGES, Answer)


async def test_network_error_is_llm_error():
    def handler(request):
        raise httpx.ConnectError("нет связи")

    with pytest.raises(LlmError):
        await _client(handler).chat_json(MESSAGES, Answer)


async def test_malformed_envelope_is_llm_error():
    def handler(request):
        return httpx.Response(200, json={"oops": True})

    with pytest.raises(LlmError):
        await _client(handler).chat_json(MESSAGES, Answer)


def test_ai_enabled_depends_on_base_url():
    assert Settings(_env_file=None, ai_base_url="").ai_enabled is False
    assert Settings(_env_file=None, ai_base_url="http://llm.local/v1").ai_enabled is True
    s = Settings(_env_file=None)
    assert s.ai_timeout == 60 and s.ai_auto_limit == 50


# --- эмбеддинги -----------------------------------------------------------------------


def _embed_client(handler, dim: int = 3) -> LlmClient:
    return LlmClient(
        base_url="http://llm.local/v1/", model="bge", api_key="k", timeout=5,
        transport=httpx.MockTransport(handler), dim=dim,
    )


def _vectors(data: list[list[float]]) -> dict:
    # индексы в обратном порядке: клиент обязан упорядочить по index
    items = [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(data)]
    return {"object": "list", "data": list(reversed(items))}


async def test_embed_sends_batch_and_orders_by_index():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://llm.local/v1/embeddings"
        assert request.headers["authorization"] == "Bearer k"
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json=_vectors([[float(i)] * 3 for i in range(len(body["input"]))]))

    out = await _embed_client(handler).embed(["a", "b", "c"])
    assert out == [[0.0] * 3, [1.0] * 3, [2.0] * 3]
    assert seen == [{"model": "bge", "input": ["a", "b", "c"]}]


async def test_embed_empty_input_makes_no_request():
    def handler(request):  # pragma: no cover
        raise AssertionError("не должно быть запроса")

    assert await _embed_client(handler).embed([]) == []


@pytest.mark.parametrize("data", [
    [[1.0, 2.0, 3.0]],  # векторов меньше, чем текстов
    [[1.0, 2.0], [1.0, 2.0]],  # неверная размерность
])
async def test_embed_validates_shape(data):
    def handler(request):
        return httpx.Response(200, json=_vectors(data))

    with pytest.raises(LlmError):
        await _embed_client(handler).embed(["a", "b"])


@pytest.mark.parametrize("response", [
    httpx.Response(500, text="boom"),
    httpx.Response(200, text="not json"),
    httpx.Response(200, json={"data": [{"index": 0}]}),
])
async def test_embed_errors(response):
    with pytest.raises(LlmError):
        await _embed_client(lambda r: response).embed(["a"])


async def test_embed_network_error():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(LlmError):
        await _embed_client(handler).embed(["a"])


def test_get_embed_client_from_settings(monkeypatch):
    from app.services.llm import client as client_mod

    s = Settings(ai_base_url="http://chat/v1", ai_embed_model="bge-m3", ai_embed_dim=8)
    monkeypatch.setattr(client_mod, "get_settings", lambda: s)
    assert s.embeddings_enabled
    c = client_mod.get_embed_client()
    assert (c.base_url, c.model, c.dim) == ("http://chat/v1", "bge-m3", 8)

    s = Settings(ai_base_url="http://chat/v1", ai_embed_base_url="http://emb/v1",
                 ai_embed_model="bge-m3")
    monkeypatch.setattr(client_mod, "get_settings", lambda: s)
    assert client_mod.get_embed_client().base_url == "http://emb/v1"

    assert not Settings(ai_base_url="http://chat/v1").embeddings_enabled
    assert not Settings(ai_embed_model="bge-m3").embeddings_enabled
