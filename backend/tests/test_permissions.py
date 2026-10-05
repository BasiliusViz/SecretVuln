from app.authz.enforcer import check
from app.authz.permissions import ACTIONS, is_valid


def test_catalog_has_approve():
    assert is_valid("finding", "approve")
    assert "approve" in ACTIONS


async def test_appsec_can_approve_developer_cannot(appsec, developer):
    assert check(["Инженер ИБ"], "finding", "approve")
    assert check(["Администратор"], "finding", "approve")
    assert not check(["Разработчик"], "finding", "approve")


async def test_developer_reads_findings_but_cannot_create_entities(client, developer):
    _, headers = developer
    assert (await client.get("/api/v1/findings", headers=headers)).status_code == 200
    r = await client.post("/api/v1/entities", json={"name": "x"}, headers=headers)
    assert r.status_code == 403


def test_audit_read_in_catalog_and_scoped():
    from app.authz.permissions import ALL_PERMISSIONS, GLOBAL_ONLY, is_scoped

    assert "audit:read" in ALL_PERMISSIONS
    assert "audit:read" not in GLOBAL_ONLY
    assert is_scoped("audit:read")


async def test_audit_read_in_three_builtin_roles(builtin_policies):
    from app.authz.enforcer import role_permissions
    from app.cli import BUILTIN_ROLES

    with_audit = {n for n in BUILTIN_ROLES if ("audit", "read") in role_permissions(n)}
    assert with_audit == {"Аудитор", "Руководитель команды", "Администратор"}
