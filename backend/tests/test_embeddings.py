"""Векторы находок: канонический текст, embed_pending, ensure_embedding."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models import FindingEmbedding
from app.services.embeddings import canonical_text, embed_pending, ensure_embedding
from tests.factories import FakeEmbedClient, make_entity, make_finding


def _raw(message: str = "Ввод попадает в SQL", snippet: str = "db.execute(q + uid)") -> dict:
    return {
        "message": {"text": message},
        "locations": [{"physicalLocation": {
            "artifactLocation": {"uri": "app/db.py"},
            "region": {"startLine": 3, "snippet": {"text": snippet}},
        }}],
    }


async def _count(db) -> int:
    return await db.scalar(select(func.count()).select_from(FindingEmbedding))


async def test_canonical_text_contains_fields_and_masks(db):
    entity = await make_entity(db)
    key = "AKIAIOSFODNN7EXAMPLE"
    f = await make_finding(db, entity, rule_id="python.sqli", cwe="CWE-89", file_path="app/db.py",
                           raw=_raw(snippet=f"x = '{key}'\n" + "y" * 5000))
    text = canonical_text(f)
    for part in ("Semgrep", "python.sqli", "SQL injection", "CWE-89", "Ввод попадает в SQL",
                 "app/db.py", "x ="):
        assert part in text
    assert key not in text
    assert len(text) < 3000  # код обрезан


async def test_canonical_text_secret_has_only_metadata(db):
    entity = await make_entity(db)
    f = await make_finding(db, entity, scanner="gitleaks", rule_id="aws-access-token",
                           file_path="conf/.env", raw=_raw("found hunter2", "KEY=hunter2"))
    text = canonical_text(f)
    assert "hunter2" not in text
    assert "aws-access-token" in text and "conf/.env" in text


async def test_embed_pending_only_new_and_changed(db):
    entity = await make_entity(db)
    a = await make_finding(db, entity, "a", raw=_raw())
    await make_finding(db, entity, "b", raw=_raw("другое"))
    client = FakeEmbedClient()

    assert await embed_pending(db, client) == 2
    assert await _count(db) == 2
    client.calls.clear()

    # ничего не изменилось — модель не вызывается
    assert await embed_pending(db, client) == 0
    assert client.calls == []

    # изменился текст одной находки — пересчитывается только она
    a.title = "Совсем другое название"
    await db.commit()
    await embed_pending(db, client)
    assert sum(len(c) for c in client.calls) == 1
    row = await db.get(FindingEmbedding, a.id)
    await db.refresh(row)
    assert list(row.embedding) == pytest.approx(client.vector(canonical_text(a)), abs=1e-6)


async def test_embed_pending_batches(db):
    entity = await make_entity(db)
    for i in range(40):
        await make_finding(db, entity, f"fp{i}", raw=_raw(f"сообщение {i}"))
    client = FakeEmbedClient()
    assert await embed_pending(db, client, limit=500) == 40
    assert [len(c) for c in client.calls] == [32, 8]


async def test_embed_pending_reindexes_on_model_change(db):
    entity = await make_entity(db)
    f = await make_finding(db, entity, raw=_raw())
    await embed_pending(db, FakeEmbedClient(model="m1"))
    other = FakeEmbedClient(model="m2")
    assert await embed_pending(db, other) == 1
    row = await db.get(FindingEmbedding, f.id)
    await db.refresh(row)
    assert row.model == "m2"


async def test_embed_pending_disabled_without_model(db):
    entity = await make_entity(db)
    await make_finding(db, entity)
    assert await embed_pending(db) == 0  # SV_AI_EMBED_MODEL пустой
    assert await _count(db) == 0


async def test_embed_pending_error_keeps_nothing(db):
    entity = await make_entity(db)
    await make_finding(db, entity)


    from app.services.llm import LlmError

    with pytest.raises(LlmError):
        await embed_pending(db, FakeEmbedClient(error=True))
    assert await _count(db) == 0


async def test_ensure_embedding(db, embeddings_on):
    entity = await make_entity(db)
    f = await make_finding(db, entity, raw=_raw())
    assert await ensure_embedding(db, f) is True
    assert await _count(db) == 1
    embeddings_on.calls.clear()
    assert await ensure_embedding(db, f) is True  # уже актуален — без вызова модели
    assert embeddings_on.calls == []


async def test_ensure_embedding_disabled_or_error(db):
    entity = await make_entity(db)
    f = await make_finding(db, entity, raw=_raw())
    assert await ensure_embedding(db, f) is False  # выключено
    assert await ensure_embedding(db, f, FakeEmbedClient(error=True)) is False
    assert await _count(db) == 0


# --- воркер ---------------------------------------------------------------------------


class _Redis:
    def __init__(self, fail: bool = False):
        self.queued: list[tuple] = []
        self.fail = fail

    async def enqueue_job(self, name, *args, _job_id=None):
        if self.fail:
            raise ConnectionError("redis down")
        self.queued.append((name, args, _job_id))


async def test_worker_enqueues_embedding_job(embeddings_on):
    from app import worker

    redis = _Redis()
    await worker.enqueue_embeddings({"redis": redis})
    assert redis.queued == [("embed_pending", (), "embed")]
    await worker.embed_cron({"redis": redis})
    assert len(redis.queued) == 2


async def test_worker_skips_embedding_job_when_off():
    from app import worker

    redis = _Redis()
    await worker.enqueue_embeddings({"redis": redis})
    await worker.enqueue_embeddings({"redis": _Redis(fail=True)})  # сбой не роняет импорт
    assert redis.queued == []


async def test_worker_embed_job(db, embeddings_on, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app import worker
    from app.services import embeddings

    entity = await make_entity(db)
    for i in range(3):
        await make_finding(db, entity, f"fp{i}", raw=_raw(f"m{i}"))
    monkeypatch.setattr(embeddings, "BATCH", 2)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    monkeypatch.setattr(worker, "EMBED_LIMIT", 2)  # несколько кругов по 2

    await worker.embed_pending({"session_factory": factory})
    assert await _count(db) == 3

    embeddings_on.error = True
    await make_finding(db, entity, "new", raw=_raw("new"))
    await worker.embed_pending({"session_factory": factory})  # ошибка модели — в лог
    assert await _count(db) == 3


async def test_embed_pending_new_findings_first_after_reimport(db):
    """Повторный импорт сдвигает updated_at у старых — новые не должны ждать за ними."""
    entity = await make_entity(db)
    client = FakeEmbedClient()
    old = [await make_finding(db, entity, f"old{i}", raw=_raw(f"старая {i}")) for i in range(3)]
    await embed_pending(db, client)
    for f in old:
        # «повторный импорт»: last_seen и updated_at сдвинулись, текст тот же
        f.updated_at = func.now() + timedelta(minutes=1)
    new = await make_finding(db, entity, "new", raw=_raw("новая"))
    await db.commit()

    await embed_pending(db, client, limit=2)
    assert await db.get(FindingEmbedding, new.id) is not None


async def test_embed_pending_counts_checked_unchanged(db):
    """Круг из одних «текст тот же» — тоже работа: воркер не должен на нём останавливаться."""
    entity = await make_entity(db)
    client = FakeEmbedClient()
    f = await make_finding(db, entity, raw=_raw())
    await embed_pending(db, client)
    f.updated_at = func.now() + timedelta(minutes=1)
    await db.commit()
    assert await embed_pending(db, client) == 1
    assert await embed_pending(db, client) == 0


async def test_embed_pending_change_committed_before_vector_time(db):
    """Импорт начался раньше расчёта вектора, а закоммитил новый текст позже: updated_at
    меньше времени вектора, но вектор всё равно пересчитывается."""
    entity = await make_entity(db)
    client = FakeEmbedClient()
    f = await make_finding(db, entity, raw=_raw("было"))
    await embed_pending(db, client)
    row = await db.get(FindingEmbedding, f.id)
    old_hash = row.content_hash
    f.raw = _raw("стало другое")
    f.updated_at = row.created_at - timedelta(seconds=1) + timedelta(microseconds=1) \
        if f.updated_at < row.created_at - timedelta(seconds=1) else f.updated_at + timedelta(microseconds=1)
    await db.commit()

    assert await embed_pending(db, client) == 1
    await db.refresh(row)
    assert row.content_hash != old_hash


async def test_embed_pending_skips_poisoned_finding(db):
    """Модель стабильно не принимает одну находку — остальные всё равно получают векторы."""
    entity = await make_entity(db)
    bad = await make_finding(db, entity, "bad", raw=_raw("ЯД"))
    good = [await make_finding(db, entity, f"ok{i}", raw=_raw(f"норм {i}")) for i in range(3)]
    client = FakeEmbedClient(poison="ЯД")

    await embed_pending(db, client)
    for g in good:
        assert await db.get(FindingEmbedding, g.id) is not None
    assert await db.get(FindingEmbedding, bad.id) is None
    # следующий запуск: ядовитая не считается работой — воркер не крутится впустую
    assert await embed_pending(db, client) == 0


async def test_embed_pending_model_down_still_raises(db):
    entity = await make_entity(db)
    for i in range(3):
        await make_finding(db, entity, f"x{i}", raw=_raw(f"x {i}"))
    from app.services.llm import LlmError

    with pytest.raises(LlmError):
        await embed_pending(db, FakeEmbedClient(error=True))


async def test_ensure_embedding_db_error_returns_false(db, embeddings_on, monkeypatch):
    """Ошибка записи вектора (например, не та размерность) не роняет разбор ИИ."""
    from app.services import embeddings as emb

    entity = await make_entity(db)
    f = await make_finding(db, entity, raw=_raw())
    monkeypatch.setattr(emb, "embed_client", lambda: FakeEmbedClient(dim=8))
    assert await ensure_embedding(db, f) is False
    assert await _count(db) == 0


def test_settings_reject_embed_dim_other_than_column():
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(ai_embed_dim=768)


async def test_embed_pending_everything_rejected_is_config_error(db):
    """Модель не принимает ничего (неверная настройка) — ошибка, а не молчаливый пропуск."""
    entity = await make_entity(db)
    for i in range(3):
        await make_finding(db, entity, f"r{i}", raw=_raw(f"ЯД {i}"))
    from app.services.llm import LlmError

    with pytest.raises(LlmError):
        await embed_pending(db, FakeEmbedClient(poison="ЯД"))
