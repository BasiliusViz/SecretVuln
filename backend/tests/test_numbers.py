from tests.factories import make_entity, make_finding


async def test_findings_get_sequential_numbers(db):
    entity = await make_entity(db)
    f1 = await make_finding(db, entity, "a")
    f2 = await make_finding(db, entity, "b")
    assert f1.number > 0
    assert f2.number == f1.number + 1


async def test_get_by_number(client, admin, db):
    _, headers = admin
    entity = await make_entity(db)
    f = await make_finding(db, entity, "a")
    r = await client.get(f"/api/v1/findings/by-number/{f.number}", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == str(f.id)
    assert r.json()["number"] == f.number
    assert (await client.get("/api/v1/findings/by-number/999999", headers=headers)).status_code == 404
