"""Векторы находок для «Похожих» и поиска по смыслу.

Канонический текст находки (всё через маскирование) → OpenAI-совместимый `/embeddings` →
`finding_embeddings`. `content_hash` = sha256(модель + текст): изменился текст или модель —
вектор пересчитывается (`embed_pending` в воркере после импорта и раз в час).
"""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Finding, FindingEmbedding
from app.services.llm import LlmError
from app.services.llm import client as llm_client
from app.services.masking import is_secret_finding, mask, message_of, snippet_of

log = logging.getLogger(__name__)

BATCH = 32  # текстов в одном запросе к модели
SNIPPET_LIMIT = 2000
TEXT_LIMIT = 2000


def embed_client():
    """Клиент эмбеддингов или None, если векторы выключены."""
    if not get_settings().embeddings_enabled:
        return None
    return llm_client.get_embed_client()


def canonical_text(finding: Finding) -> str:
    """Текст находки для вектора. У секрета — только сканер, правило, CWE и путь."""
    raw = finding.raw or {}
    secret = is_secret_finding(finding)
    parts = [
        ("Сканер", finding.scanner),
        ("Правило", finding.rule_id),
        ("CWE", finding.cwe),
        ("Файл", finding.file_path),
    ]
    if not secret:
        parts[2:2] = [("Название", finding.title)]
        parts += [
            ("Сообщение", mask(message_of(raw))[:TEXT_LIMIT]),
            ("Код", mask(snippet_of(raw))[:SNIPPET_LIMIT]),
        ]
    return "\n".join(f"{k}: {v}" for k, v in parts if v)


def content_hash(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()


async def _upsert(db: AsyncSession, rows: list[dict]) -> None:
    stmt = insert(FindingEmbedding).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[FindingEmbedding.finding_id],
        set_={
            "model": stmt.excluded.model,
            "content_hash": stmt.excluded.content_hash,
            "embedding": stmt.excluded.embedding,
            "created_at": func.now(),
        },
    )
    await db.execute(stmt)


async def embed_pending(db: AsyncSession, client=None, limit: int = 500) -> int:
    """Посчитать векторы находок без вектора, со сменившейся моделью или текстом.

    Возвращает число пересчитанных. Ошибка модели — `LlmError` (уже записанные пачки
    сохранены). Без клиента и при выключенных векторах — 0.
    """
    client = client or embed_client()
    if client is None:
        return 0
    rows = (await db.execute(
        select(Finding, FindingEmbedding.content_hash)
        .outerjoin(FindingEmbedding, FindingEmbedding.finding_id == Finding.id)
        .where(or_(
            FindingEmbedding.finding_id.is_(None),
            FindingEmbedding.model != client.model,
            # находка менялась после расчёта вектора — сверить хеш текста
            Finding.updated_at > FindingEmbedding.created_at,
        ))
        .order_by(Finding.created_at)
        .limit(limit)
    )).all()

    todo: list[tuple[Finding, str, str]] = []
    unchanged: list = []
    for finding, old_hash in rows:
        text = canonical_text(finding)
        new_hash = content_hash(client.model, text)
        if new_hash == old_hash:
            unchanged.append(finding.id)
        else:
            todo.append((finding, text, new_hash))
    if unchanged:
        # текст тот же — только отметить проверку, чтобы не попадать в выборку снова
        await db.execute(
            update(FindingEmbedding)
            .where(FindingEmbedding.finding_id.in_(unchanged))
            .values(created_at=func.now())
        )
        await db.commit()

    for i in range(0, len(todo), BATCH):
        chunk = todo[i : i + BATCH]
        vectors = await client.embed([text for _, text, _ in chunk])
        await _upsert(db, [
            {"finding_id": f.id, "model": client.model, "content_hash": h, "embedding": v}
            for (f, _, h), v in zip(chunk, vectors, strict=True)
        ])
        await db.commit()
    return len(todo)


async def ensure_embedding(db: AsyncSession, finding: Finding, client=None) -> bool:
    """Актуальный вектор одной находки сразу (для триажёра). False — векторы выключены
    или модель недоступна; разбор тогда идёт без похожих."""
    client = client or embed_client()
    if client is None:
        return False
    text = canonical_text(finding)
    new_hash = content_hash(client.model, text)
    old_hash = await db.scalar(
        select(FindingEmbedding.content_hash).where(FindingEmbedding.finding_id == finding.id)
    )
    if old_hash == new_hash:
        return True
    try:
        [vector] = await client.embed([text])
    except LlmError as exc:
        log.warning("Вектор находки %s не посчитан: %s", finding.id, exc)
        return False
    await _upsert(db, [{"finding_id": finding.id, "model": client.model,
                        "content_hash": new_hash, "embedding": vector}])
    await db.commit()
    return True
