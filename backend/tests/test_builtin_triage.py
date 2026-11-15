"""Этап 7: встроенный разбор находки и автозапуск после импорта."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import AiAnalysis, AiAnalysisKind, Finding, FindingStatus
from app.models.ai_analysis import AiReviewStatus, AiVerdict
from app.models.import_ import ImportStatus
from app.services import builtin_triage
from app.services.builtin_triage import BUILTIN_AGENT, pick_auto_triage, triage_finding
from app.services.import_processing import apply_import
from app.services.llm import LlmError
from app.services.llm.prompts import TriageAnswer
from app.services.sarif import parse_sarif
from tests.factories import make_entity, make_finding, make_import, make_sarif

ANSWER = TriageAnswer(
    title_plain="Инъекция SQL",
    explanation="Ввод попадает в запрос",
    remediation="Параметризуйте запрос",
    verdict="false_positive",
    confidence=0.7,
    reasoning="Значение берётся из константы",
)


class FakeClient:
    model = "fake-model"

    def __init__(self, answer: TriageAnswer | None = ANSWER, error: bool = False):
        self.answer, self.error = answer, error
        self.calls: list[list[dict]] = []

    async def chat_json(self, messages, schema):
        self.calls.append(messages)
        if self.error:
            raise LlmError("нет связи")
        return self.answer


@pytest.fixture
def ai_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "ai_base_url", "http://llm.local/v1")
    monkeypatch.setattr(s, "ai_model", "fake-model")
    monkeypatch.setattr(s, "ai_auto_limit", 50)
    return s


# --- триажёр --------------------------------------------------------------------------


async def test_triage_writes_summary_and_triage(db):
    entity = await make_entity(db)
    finding = await make_finding(db, entity)
    client = FakeClient()

    rows = await triage_finding(db, finding.id, client)
    await db.commit()

    assert len(client.calls) == 1
    stored = list(await db.scalars(select(AiAnalysis).where(AiAnalysis.finding_id == finding.id)))
    assert {r.kind for r in stored} == {AiAnalysisKind.summary, AiAnalysisKind.triage}
    assert len(rows) == 2
    for r in stored:
        assert r.agent == BUILTIN_AGENT == "sv-builtin"
        assert r.model == "fake-model"
        assert r.prompt_version == "triage-v3"
        assert r.similar_ids == []  # векторы выключены — без похожих
        assert r.created_by is None
        assert r.review_status == AiReviewStatus.pending
    summary = next(r for r in stored if r.kind == AiAnalysisKind.summary)
    triage = next(r for r in stored if r.kind == AiAnalysisKind.triage)
    assert summary.verdict is None
    assert summary.title_plain == "Инъекция SQL"
    assert summary.remediation == "Параметризуйте запрос"
    assert triage.verdict == AiVerdict.false_positive
    assert triage.confidence == 0.7
    assert triage.explanation == "Значение берётся из константы"

    await db.refresh(finding)
    assert finding.ai_verdict == AiVerdict.false_positive
    assert finding.status == FindingStatus.new  # ИИ статус не меняет


async def test_triage_secret_has_no_snippet(db):
    entity = await make_entity(db)
    secret = "ghp_verysecretvalue1234567890"
    raw = {"locations": [{"physicalLocation": {"region": {"snippet": {"text": secret}}}}]}
    finding = await make_finding(db, entity, scanner="gitleaks", rule_id="github-pat", raw=raw)
    client = FakeClient()

    await triage_finding(db, finding.id, client)

    sent = "\n".join(m["content"] for m in client.calls[0])
    assert secret not in sent and "github-pat" in sent


async def test_triage_model_error_writes_nothing(db):
    entity = await make_entity(db)
    finding = await make_finding(db, entity)

    with pytest.raises(LlmError):
        await triage_finding(db, finding.id, FakeClient(error=True))
    await db.rollback()

    assert await db.scalar(select(AiAnalysis.id)) is None


async def test_triage_missing_finding(db):
    import uuid

    assert await triage_finding(db, uuid.uuid4(), FakeClient()) == []


# --- автозапуск ------------------------------------------------------------------------


async def _imported(db, entity, fps, **imp_kw):
    imp = await make_import(db, entity, **imp_kw)
    runs = parse_sarif(make_sarif(results=[{"fp": fp} for fp in fps]))
    await apply_import(db, imp, runs)
    imp.status = ImportStatus.done
    await db.commit()
    return imp


async def _ids(db, fps) -> set:
    rows = await db.scalars(select(Finding.id).where(Finding.fingerprint.in_(fps)))
    return set(rows)


async def test_pick_new_findings_of_import(db, ai_on):
    entity = await make_entity(db)
    await _imported(db, entity, ["a"])
    imp2 = await _imported(db, entity, ["a", "b", "c"])

    picked = await pick_auto_triage(db, imp2.id)

    assert set(picked) == await _ids(db, ["b", "c"])  # «a» не новая


async def test_pick_respects_limit(db, ai_on, monkeypatch):
    monkeypatch.setattr(ai_on, "ai_auto_limit", 2)
    entity = await make_entity(db)
    imp = await _imported(db, entity, ["a", "b", "c"])

    assert len(await pick_auto_triage(db, imp.id)) == 2

    monkeypatch.setattr(ai_on, "ai_auto_limit", 0)
    assert await pick_auto_triage(db, imp.id) == []


async def test_pick_skips_already_triaged(db, ai_on):
    entity = await make_entity(db)
    imp = await _imported(db, entity, ["a", "b"])
    [done] = await _ids(db, ["a"])
    await triage_finding(db, done, FakeClient())
    await db.commit()

    assert set(await pick_auto_triage(db, imp.id)) == await _ids(db, ["b"])


async def test_pick_disabled_without_url(db, ai_on, monkeypatch):
    monkeypatch.setattr(ai_on, "ai_base_url", "")
    entity = await make_entity(db)
    imp = await _imported(db, entity, ["a"])

    assert await pick_auto_triage(db, imp.id) == []


async def test_pick_only_main_branch(db, ai_on):
    entity = await make_entity(db, default_branch="main")
    imp = await _imported(db, entity, ["a"], branch="main")
    assert len(await pick_auto_triage(db, imp.id)) == 1

    # импорт не из основной ветки не проходит в бэклог — и в разбор тоже
    feature = await make_import(db, entity, branch="feature/x", status=ImportStatus.failed)
    assert await pick_auto_triage(db, feature.id) == []


async def test_worker_enqueues_after_import(db, ai_on, monkeypatch):
    entity = await make_entity(db)
    imp = await _imported(db, entity, ["a", "b"])
    queued: list[tuple] = []

    class Redis:
        async def enqueue_job(self, name, *args, _job_id=None):
            queued.append((name, args, _job_id))

    from app import worker

    await worker.enqueue_auto_triage({"redis": Redis()}, db, imp.id)

    ids = await _ids(db, ["a", "b"])
    assert {q[1][0] for q in queued} == {str(i) for i in ids}
    assert all(q[0] == "ai_triage_finding" and q[2] == f"ai:{q[1][0]}" for q in queued)


async def test_worker_job_swallows_model_error(db, ai_on, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app import worker

    entity = await make_entity(db)
    finding = await make_finding(db, entity)
    monkeypatch.setattr(builtin_triage, "client_from_settings", lambda: FakeClient(error=True))
    factory = async_sessionmaker(db.bind, expire_on_commit=False)

    await worker.ai_triage_finding({"session_factory": factory}, str(finding.id))  # не падает
    assert await db.scalar(select(AiAnalysis.id)) is None

    monkeypatch.setattr(builtin_triage, "client_from_settings", lambda: FakeClient())
    await worker.ai_triage_finding({"session_factory": factory}, str(finding.id))
    assert len(list(await db.scalars(select(AiAnalysis.id)))) == 2

async def test_worker_defers_when_ai_slot_busy(ai_on):
    from arq import Retry

    from app import worker

    async with worker._ai_slots:  # другой разбор уже идёт — слот воркера не держим
        with pytest.raises(Retry):
            await worker.ai_triage_finding({}, "00000000-0000-0000-0000-000000000000")


async def test_worker_auto_enqueue_failure_is_swallowed(db, ai_on):
    entity = await make_entity(db)
    imp = await _imported(db, entity, ["a"])

    class Redis:
        async def enqueue_job(self, *args, **kwargs):
            raise ConnectionError("redis down")

    from app import worker

    await worker.enqueue_auto_triage({"redis": Redis()}, db, imp.id)  # не падает


def test_builtin_agent_name_is_reserved():
    from pydantic import ValidationError

    from app.schemas.ai_analysis import AiAnalysisCreate

    with pytest.raises(ValidationError):
        AiAnalysisCreate(kind=AiAnalysisKind.summary, explanation="x", agent=" SV-Builtin ")


# --- triage-v2: похожие решённые ------------------------------------------------------


async def _decided(db, entity, fp, message, status, reason="тестовые данные"):
    from datetime import datetime, timezone

    from app.models import FindingEvent
    from app.models.finding_event import ActorType, FindingEventType

    f = await make_finding(db, entity, fp, raw={"message": {"text": message}}, status=status)
    db.add(FindingEvent(
        finding_id=f.id, event_type=FindingEventType.status_changed, actor_type=ActorType.user,
        to_status=status, reason=reason, created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return f


async def test_triage_v2_uses_decided_similar_from_subtree(db, embeddings_on):
    from app.services.embeddings import embed_pending

    root = await make_entity(db, "root")
    svc = await make_entity(db, "svc", parent_id=root.id)
    sub = await make_entity(db, "sub", parent_id=svc.id)
    sibling = await make_entity(db, "svc2", parent_id=root.id)
    target = await make_finding(db, svc, "t", raw={"message": {"text": "ssrf in fetch url"}})
    key = "AKIAIOSFODNN7EXAMPLE"
    fp = await _decided(db, sub, "fp", f"ssrf in fetch url {key}", FindingStatus.false_positive)
    conf = await _decided(db, svc, "c", "ssrf in fetch", FindingStatus.confirmed)
    # открытая без решения, предок, соседняя ветка, решение не человека — не берутся
    await make_finding(db, svc, "open", raw={"message": {"text": "ssrf in fetch url"}})
    await _decided(db, root, "r", "ssrf in fetch url", FindingStatus.false_positive)
    await _decided(db, sibling, "o", "ssrf in fetch url", FindingStatus.false_positive)
    sys_f = await make_finding(db, svc, "sys", raw={"message": {"text": "ssrf in fetch url"}},
                               status=FindingStatus.risk_accepted)
    await embed_pending(db)
    client = FakeClient()

    rows = await triage_finding(db, target.id, client)
    await db.commit()

    expected = {str(fp.id), str(conf.id)}
    for r in rows:
        assert r.prompt_version == "triage-v3"
        assert set(r.similar_ids) == expected
    sent = client.calls[0][1]["content"]
    assert key not in sent and "[MASKED]" in sent
    assert "тестовые данные" in sent
    assert f"SV-{sys_f.number}" not in sent
    # похожие — внутри границы недоверенных данных
    assert sent.index("ssrf in fetch") < sent.rindex("</finding_data")
    assert len(sent.split("Похожая находка")) - 1 == 2


async def test_triage_v2_limits_to_three(db, embeddings_on):
    from app.services.embeddings import embed_pending

    root = await make_entity(db, "root")
    target = await make_finding(db, root, "t", raw={"message": {"text": "xss a"}})
    for i in range(5):
        await _decided(db, root, f"d{i}", f"xss a {i}", FindingStatus.false_positive)
    await embed_pending(db)
    rows = await triage_finding(db, target.id, FakeClient())
    assert len(rows[0].similar_ids) == 3


async def test_triage_v2_embedding_error_goes_without_similar(db, embeddings_on):
    root = await make_entity(db, "root")
    target = await make_finding(db, root, "t")
    embeddings_on.error = True
    client = FakeClient()
    rows = await triage_finding(db, target.id, client)
    assert rows[0].similar_ids == [] and len(client.calls) == 1
