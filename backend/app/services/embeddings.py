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
from app.services.llm import LlmError, LlmRejected
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
            "source_updated_at": stmt.excluded.source_updated_at,
            "created_at": func.now(),
        },
    )
    await db.execute(stmt)


async def embed_pending(db: AsyncSession, client=None, limit: int = 500) -> int:
    """Посчитать векторы находок без вектора, со сменившейся моделью или текстом.

    Возвращает число обработанных: пересчитанных и сверенных «текст тот же» — воркер крутит
    круги, пока не 0. Находки без вектора идут первыми: после повторного импорта старые
    (сдвинулся updated_at) не задерживают новые. Пачку, которую модель не приняла, повторяем
    по одной и пропускаем упавшие (их не считаем — следующий круг не крутится впустую).
    Модель недоступна — `LlmError` (записанное сохранено).
    Без клиента и при выключенных векторах — 0.
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
            # находка менялась после сверки — сверить хеш текста
            FindingEmbedding.source_updated_at.is_(None),
            Finding.updated_at != FindingEmbedding.source_updated_at,
        ))
        .order_by(FindingEmbedding.finding_id.is_(None).desc(), Finding.created_at)
        .limit(limit)
    )).all()

    todo: list[tuple[Finding, str, str]] = []
    unchanged: list[Finding] = []
    for finding, old_hash in rows:
        text = canonical_text(finding)
        new_hash = content_hash(client.model, text)
        if new_hash == old_hash:
            unchanged.append(finding)
        else:
            todo.append((finding, text, new_hash))
    for finding in unchanged:
        # текст тот же — только отметить сверку, чтобы не попадать в выборку снова
        await db.execute(
            update(FindingEmbedding)
            .where(FindingEmbedding.finding_id == finding.id)
            .values(source_updated_at=finding.updated_at)
        )
    if unchanged:
        await db.commit()

    done = 0
    for i in range(0, len(todo), BATCH):
        chunk = todo[i : i + BATCH]
        try:
            vectors = await client.embed([text for _, text, _ in chunk])
        except LlmRejected:
            vectors = await _embed_one_by_one(client, chunk)
        rows_ = [
            {"finding_id": f.id, "model": client.model, "content_hash": h, "embedding": v,
             "source_updated_at": f.updated_at}
            for (f, _, h), v in zip(chunk, vectors, strict=True)
            if v is not None
        ]
        if rows_:
            await _upsert(db, rows_)
            await db.commit()
        done += len(rows_)
    return done + len(unchanged)


async def _embed_one_by_one(client, chunk: list[tuple[Finding, str, str]]) -> list:
    """Пачку модель не приняла: по одной, непринятые — None (недоступность — `LlmError`).
    Не принята ни одна из нескольких — это настройка (имя модели, параметры), а не текст:
    `LlmError`, чтобы не пропускать молча все находки."""
    vectors: list = []
    for finding, text, _ in chunk:
        try:
            [vector] = await client.embed([text])
        except LlmRejected as exc:
            log.warning("Вектор находки %s не посчитан, пропущена: %s", finding.id, exc)
            vector = None
        vectors.append(vector)
    if len(chunk) > 1 and all(v is None for v in vectors):
        raise LlmError("Модель эмбеддингов не приняла ни одной находки — проверьте настройку модели")
    return vectors


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
        # savepoint: ошибка записи (например, не та размерность) не откатывает и не
        # «протухает» объекты вызывающего — разбор ИИ продолжается без похожих
        async with db.begin_nested():
            await _upsert(db, [{"finding_id": finding.id, "model": client.model,
                                "content_hash": new_hash, "embedding": vector,
                                "source_updated_at": finding.updated_at}])
    except Exception as exc:  # noqa: BLE001 — любая ошибка вектора: разбор идёт без похожих
        log.warning("Вектор находки %s не посчитан: %s", finding.id, exc)
        return False
    await db.commit()
    return True
