"""MCP-сервер для агентов: отдельный процесс рядом с API и воркером.

Запуск (из `backend/`): `python -m app.mcp_server` — streamable HTTP на
`SV_MCP_HOST:SV_MCP_PORT/mcp`. Авторизация — тот же API-токен `sv_…`
(`Authorization: Bearer`), права — привязки сервисного аккаунта.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import HTTPException
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.deps import Principal
from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import AiAnalysisKind, AiVerdict, FindingStatus, Severity
from app.schemas.ai_analysis import AiAnalysisCreate
from app.services import agent_tools, api_tokens
from app.services.access import load_access

server = MCPServer(
    name="SecretVuln",
    instructions=(
        "Уязвимости SecretVuln (SARIF). Можно искать и читать уязвимости и записывать "
        "выводы ИИ (submit_analysis). Статус уязвимости агент не меняет — решает человек. "
        + agent_tools.UNTRUSTED_NOTICE
    ),
)


def _bearer(headers) -> str | None:
    value = headers.get("authorization") or ""
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


async def _principal(db, ctx: Context) -> Principal:
    request = ctx.request_context.request
    raw = _bearer(request.headers) if request is not None else None
    if not raw or not api_tokens.is_api_token(raw):
        raise ToolError("Нужен API-токен sv_… в заголовке Authorization")
    user = await api_tokens.authenticate(db, raw)
    if user is None:
        raise ToolError("Токен недействителен, отозван или истёк")
    return Principal(user=user, access=await load_access(db, user))


async def _run(ctx: Context, call):
    """Сессия БД + владелец токена; HTTP-ошибки сервисов → ошибка инструмента."""
    async with async_session_factory() as db:
        principal = await _principal(db, ctx)
        try:
            return await call(db, principal)
        except HTTPException as e:
            raise ToolError(str(e.detail)) from None


def _uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ToolError(f"Некорректный идентификатор: {value}") from None


@server.tool()
async def search_findings(
    ctx: Context,
    entity_id: str | None = None,
    severity: Severity | None = None,
    status: list[FindingStatus] | None = None,
    scanner: str | None = None,
    tag: str | None = None,
    overdue: bool = False,
    ai_verdict: list[AiVerdict] | None = None,
    no_ai_verdict: bool = False,
    order: Literal["last_seen", "severity", "number", "due_at"] = "last_seen",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Найти уязвимости (видны только доступные токену). Фильтры как в списке, лимит 100.

    entity_id — проект вместе с подпроектами; no_ai_verdict — ещё без вердикта ИИ.
    """
    return await _run(ctx, lambda db, p: agent_tools.search_findings(
        db, p,
        entity_id=_uuid(entity_id), severity=severity, statuses=status, scanner=scanner,
        tag=tag, overdue=overdue, ai_verdicts=ai_verdict, no_ai_verdict=no_ai_verdict,
        order=order, limit=limit, offset=offset,
    ))


@server.tool()
async def get_finding(ctx: Context, finding: str) -> dict:
    """Уязвимость целиком: поля, история, выводы ИИ, repo_url и ветка проекта.

    finding — UUID или номер (`SV-123`).
    """
    return await _run(ctx, lambda db, p: agent_tools.get_finding(db, p, finding))


@server.tool()
async def get_stats(ctx: Context, entity_id: str | None = None) -> dict:
    """Счётчики уязвимостей по критичности и статусам (проект с подпроектами или всё доступное)."""
    return await _run(ctx, lambda db, p: agent_tools.get_stats(db, p, _uuid(entity_id)))


@server.tool()
async def submit_analysis(
    ctx: Context,
    finding: str,
    kind: AiAnalysisKind,
    verdict: AiVerdict | None = None,
    confidence: float | None = None,
    title_plain: str | None = None,
    explanation: str | None = None,
    remediation: str | None = None,
    agent: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
) -> dict:
    """Записать вывод ИИ по уязвимости. Статус не меняется — вывод рассматривает человек.

    kind=summary — «простыми словами» (title_plain, explanation, remediation);
    kind=triage — вердикт (verdict обязателен, confidence 0–1).
    """
    try:
        data = AiAnalysisCreate(
            kind=kind, verdict=verdict, confidence=confidence, title_plain=title_plain,
            explanation=explanation, remediation=remediation, agent=agent, model=model,
            prompt_version=prompt_version,
        )
    except ValueError as e:
        raise ToolError(str(e)) from None
    return await _run(ctx, lambda db, p: agent_tools.submit_analysis(db, p, finding, data))


class RequireApiToken:
    """Без заголовка с токеном `sv_…` — 401 до MCP (сам токен проверяют инструменты)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            raw = _bearer(headers)
            if not raw or not api_tokens.is_api_token(raw):
                response = JSONResponse({"detail": "Нужен API-токен sv_…"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_app() -> ASGIApp:
    settings = get_settings()
    # stateless: каждый запрос самодостаточен, токен проверяется на каждом вызове
    return RequireApiToken(
        server.streamable_http_app(stateless_http=True, json_response=True, host=settings.mcp_host)
    )


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(build_app(), host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    main()
