import pytest
from sqlalchemy import select

from app.models import Finding
from app.services.entity_tree import branch_allowed, resolve_default_branch
from app.services.import_processing import ImportRejected, apply_import
from app.services.sarif import parse_sarif
from tests.factories import make_entity, make_import, make_sarif


def test_parser_reads_version_control_provenance():
    sarif = make_sarif(
        "Semgrep",
        [{"fp": "a"}],
        provenance={
            "repositoryUri": "https://gitlab.local/pay/api",
            "revisionId": "abc123",
            "branch": "main",
        },
    )
    run = parse_sarif(sarif)[0]
    assert run.repository_uri == "https://gitlab.local/pay/api"
    assert run.revision == "abc123"
    assert run.branch == "main"


def test_branch_allowed():
    assert branch_allowed(None, "main")
    assert branch_allowed("feature/x", None)
    assert branch_allowed("main", "main")
    assert not branch_allowed("feature/x", "main")


async def test_default_branch_is_inherited(db):
    root = await make_entity(db, "org", default_branch="master")
    child = await make_entity(db, "svc", parent_id=root.id)
    grandchild = await make_entity(db, "mod", parent_id=child.id, default_branch="main")
    assert await resolve_default_branch(db, child.id) == "master"
    assert await resolve_default_branch(db, grandchild.id) == "main"


async def test_upload_rejects_non_default_branch(client, admin, db):
    _, headers = admin
    entity = await make_entity(db, default_branch="main")
    r = await client.post(
        f"/api/v1/entities/{entity.id}/imports",
        files={"file": ("s.sarif", make_sarif("Semgrep", [{"fp": "a"}]), "application/json")},
        data={"branch": "feature/x"},
        headers=headers,
    )
    assert r.status_code == 422
    assert "feature/x" in r.json()["detail"]
    assert client.enqueued == []


async def test_upload_stores_metadata(client, admin, db):
    _, headers = admin
    entity = await make_entity(db, default_branch="main")
    r = await client.post(
        f"/api/v1/entities/{entity.id}/imports",
        files={"file": ("s.sarif", make_sarif("Semgrep", [{"fp": "a"}]), "application/json")},
        data={
            "branch": "main",
            "commit_sha": "deadbeef",
            "pipeline_url": "https://ci.local/p/1",
            "scan_scope": "api:latest",
            "close_missing": "false",
        },
        headers=headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["branch"] == "main"
    assert body["commit_sha"] == "deadbeef"
    assert body["scan_scope"] == "api:latest"
    assert body["close_missing"] is False
    assert body["confirm_empty"] is False
    assert client.enqueued == [body["id"]]


async def test_sarif_branch_fills_import_and_findings(db):
    entity = await make_entity(db)
    imp = await make_import(db, entity, scan_scope="api:latest")
    sarif = make_sarif("Semgrep", [{"fp": "a"}], provenance={"branch": "main", "revisionId": "c0ffee"})
    await apply_import(db, imp, parse_sarif(sarif))
    await db.commit()
    assert imp.branch == "main"
    assert imp.commit_sha == "c0ffee"
    finding = await db.scalar(select(Finding).where(Finding.fingerprint == "a"))
    assert finding.scan_scope == "api:latest"
    assert finding.commit_sha == "c0ffee"


async def test_sarif_branch_mismatch_is_rejected(db):
    entity = await make_entity(db, default_branch="main")
    imp = await make_import(db, entity)
    sarif = make_sarif("Semgrep", [{"fp": "a"}], provenance={"branch": "feature/x"})
    with pytest.raises(ImportRejected, match="feature/x"):
        await apply_import(db, imp, parse_sarif(sarif))
