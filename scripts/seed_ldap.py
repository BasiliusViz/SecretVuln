"""Наполняет dev-LDAP (lldap) тестовыми пользователями и группами.

lldap управляется через GraphQL API (по LDAP-протоколу пользователи read-only).
Пароли ставятся утилитой lldap_set_password внутри контейнера.

Запуск:  python scripts/seed_ldap.py
Требует запущенного контейнера lldap (docker compose up -d ldap).
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")  # чтобы кириллица/✓ не падали на cp1251

BASE = "http://localhost:17170"
CONTAINER = "secretvuln-ldap-1"
ADMIN_USER = "admin"
ADMIN_PASS = "adminpassword"
PASSWORD = "Passw0rd!"

GROUPS = ["secops-admins", "developers", "auditors"]

USERS = [
    ("alice", "alice@secretvuln.local", "Алиса Смирнова", "Алиса", "Смирнова", "secops-admins"),
    ("bob", "bob@secretvuln.local", "Борис Петров", "Борис", "Петров", "developers"),
    ("carol", "carol@secretvuln.local", "Кэрол Иванова", "Кэрол", "Иванова", "auditors"),
]


def _login() -> str:
    body = json.dumps({"username": ADMIN_USER, "password": ADMIN_PASS}).encode()
    req = urllib.request.Request(
        f"{BASE}/auth/simple/login", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)["token"]


def _gql(token: str, query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/graphql",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        return {"errors": [{"message": e.read().decode()}]}
    return data


def _set_password(username: str) -> None:
    subprocess.run(
        [
            "docker", "exec", CONTAINER, "/app/lldap_set_password",
            "--base-url", "http://localhost:17170",
            "--admin-username", ADMIN_USER,
            "--admin-password", ADMIN_PASS,
            "--username", username,
            "--password", PASSWORD,
        ],
        check=True,
        capture_output=True,
    )


def main() -> int:
    token = _login()
    print("✓ вход admin в lldap")

    # Группы (id → name). Существующие пропускаем.
    group_ids: dict[str, int] = {}
    existing = _gql(token, "{ groups { id displayName } }")
    for g in existing.get("data", {}).get("groups", []):
        group_ids[g["displayName"]] = g["id"]

    for name in GROUPS:
        if name in group_ids:
            print(f"· группа {name} уже есть (id={group_ids[name]})")
            continue
        res = _gql(token, "mutation($n: String!){ createGroup(name: $n){ id } }", {"n": name})
        if "errors" in res:
            print(f"✗ группа {name}: {res['errors']}")
            continue
        gid = res["data"]["createGroup"]["id"]
        group_ids[name] = gid
        print(f"✓ группа {name} (id={gid})")

    # Пользователи.
    for uid, email, display, first, last, group in USERS:
        res = _gql(
            token,
            "mutation($u: CreateUserInput!){ createUser(user: $u){ id } }",
            {"u": {"id": uid, "email": email, "displayName": display,
                   "firstName": first, "lastName": last}},
        )
        if "errors" in res:
            msg = res["errors"][0].get("message", "")
            if "already exists" in msg.lower() or "duplicate" in msg.lower():
                print(f"· пользователь {uid} уже есть")
            else:
                print(f"✗ пользователь {uid}: {msg}")
        else:
            print(f"✓ пользователь {uid} ({email})")

        _set_password(uid)

        gid = group_ids.get(group)
        if gid is not None:
            addres = _gql(
                token,
                "mutation($u: String!, $g: Int!){ addUserToGroup(userId: $u, groupId: $g){ ok } }",
                {"u": uid, "g": gid},
            )
            if "errors" in addres:
                print(f"  ⚠ группа {group}: {addres['errors'][0].get('message','')}")
            else:
                print(f"  → в группе {group}")

    print(f"\nГотово. Пароль всех тестовых пользователей: {PASSWORD}")
    print(f"Веб-интерфейс lldap: {BASE}  (admin / {ADMIN_PASS})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
