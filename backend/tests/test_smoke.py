from app.services.sarif import parse_sarif
from tests.factories import make_sarif


async def test_health(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["database"] == "up"


async def test_findings_require_auth(client):
    r = await client.get("/api/v1/findings")
    assert r.status_code == 401


async def test_admin_can_list_findings(client, admin):
    _, headers = admin
    r = await client.get("/api/v1/findings", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_make_sarif_roundtrip():
    runs = parse_sarif(make_sarif("Semgrep", [{"fp": "a"}, {"fp": "b", "path": "x.py", "line": 3}]))
    assert runs[0].scanner == "Semgrep"
    assert [r.fingerprint for r in runs[0].results] == ["a", "b"]
    assert runs[0].results[1].file_path == "x.py"
    assert runs[0].results[1].line_start == 3
