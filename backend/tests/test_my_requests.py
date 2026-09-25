"""GET /decisions?mine=true — мои запросы с номером и заголовком уязвимости."""

from tests.factories import make_entity, make_finding


async def test_my_requests(client, developer, appsec, db):
    _, dev_h = developer
    _, sec_h = appsec
    f = await make_finding(db, await make_entity(db, "svc"), "fp", title="XSS в шаблоне")
    r = await client.post(
        f"/api/v1/findings/{f.id}/decisions",
        json={"decision_type": "false_positive", "reason_tag": "test_code"},
        headers=dev_h,
    )
    assert r.status_code == 201

    mine = (await client.get("/api/v1/decisions?mine=true", headers=dev_h)).json()
    assert len(mine) == 1
    assert mine[0]["finding_number"] == f.number
    assert mine[0]["finding_title"] == "XSS в шаблоне"

    assert (await client.get("/api/v1/decisions?mine=true", headers=sec_h)).json() == []
    everyone = (await client.get("/api/v1/decisions", headers=sec_h)).json()
    assert everyone[0]["finding_number"] == f.number
