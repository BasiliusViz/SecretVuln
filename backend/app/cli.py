"""CLI-утилиты SecretVuln.

Запуск (из каталога backend, с активным venv):
    python -m app.cli create-admin --email admin@example.com --password ...

Значения можно передать и через окружение: SV_ADMIN_EMAIL / SV_ADMIN_PASSWORD /
SV_ADMIN_NAME. Без аргументов утилита спросит их интерактивно.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import func, select

from app.core.security import hash_password
from app.db.session import async_session_factory, engine
from app.models import User
from app.models.user import AuthSource

MIN_PASSWORD_LEN = 8


async def create_admin(email: str, password: str, full_name: str | None) -> None:
    async with async_session_factory() as db:
        total_users = await db.scalar(select(func.count()).select_from(User))
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                full_name=full_name,
                hashed_password=hash_password(password),
                auth_source=AuthSource.local,
                is_superuser=True,
                is_active=True,
            )
            db.add(user)
            action = "создан"
        else:
            user.hashed_password = hash_password(password)
            user.auth_source = AuthSource.local
            user.is_superuser = True
            user.is_active = True
            action = "обновлён (пароль сброшен, выданы права суперадмина)"
        await db.commit()

    await engine.dispose()
    print(f"✓ Суперадмин {action}: {email}")
    if total_users == 0:
        print("  Это первый пользователь в системе — теперь можно войти через веб-интерфейс.")


# Встроенные роли: имя → список (ресурс, действие).
_R = ["entity", "finding", "import", "group", "role", "sla"]
BUILTIN_ROLES: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "Наблюдатель": (
        "Только чтение во всех разделах",
        [(r, "read") for r in _R],
    ),
    "Разработчик": (
        "Видит находки, берёт в работу, запрашивает «ложное срабатывание» и принятие риска",
        [
            ("entity", "read"), ("finding", "read"), ("finding", "triage"), ("import", "read"),
            ("sla", "read"),
        ],
    ),
    "Аудитор": (
        "Чтение везде + разбор находок",
        [(r, "read") for r in _R] + [("finding", "triage")],
    ),
    "Инженер ИБ": (
        "Полный доступ к активам, находкам и импортам, одобряет решения по находкам",
        [
            ("entity", "read"), ("entity", "write"), ("entity", "delete"),
            ("finding", "read"), ("finding", "write"), ("finding", "delete"),
            ("finding", "triage"), ("finding", "approve"),
            ("import", "read"), ("import", "import"), ("import", "delete"),
            ("group", "read"),
            ("sla", "read"), ("sla", "manage"),
        ],
    ),
    "Администратор": (
        "Все права, включая управление группами и ролями",
        [
            ("entity", "read"), ("entity", "write"), ("entity", "delete"),
            ("finding", "read"), ("finding", "write"), ("finding", "delete"),
            ("finding", "triage"), ("finding", "approve"),
            ("import", "read"), ("import", "import"), ("import", "delete"),
            ("group", "read"), ("group", "write"), ("group", "delete"),
            ("role", "read"), ("role", "write"), ("role", "delete"),
            ("sla", "read"), ("sla", "manage"),
        ],
    ),
}


async def seed_roles() -> None:
    from sqlalchemy import select

    from app.authz.enforcer import set_role_permissions
    from app.models import Role

    async with async_session_factory() as db:
        for name, (desc, perms) in BUILTIN_ROLES.items():
            role = await db.scalar(select(Role).where(Role.name == name))
            if role is None:
                role = Role(name=name, description=desc, is_builtin=True)
                db.add(role)
                action = "создана"
            else:
                role.description = desc
                role.is_builtin = True
                action = "обновлена"
            await db.commit()
            set_role_permissions(name, perms)
            print(f"✓ роль «{name}» {action} ({len(perms)} прав)")

    await engine.dispose()


def _cmd_seed_roles(args: argparse.Namespace) -> int:
    asyncio.run(seed_roles())
    return 0


def _cmd_create_admin(args: argparse.Namespace) -> int:
    email = (args.email or input("Email суперадмина: ")).strip().lower()
    password = args.password or getpass.getpass("Пароль: ")
    if not email or not password:
        print("Нужны и email, и пароль.", file=sys.stderr)
        return 1
    if len(password) < MIN_PASSWORD_LEN:
        print(f"Пароль должен быть не короче {MIN_PASSWORD_LEN} символов.", file=sys.stderr)
        return 1
    asyncio.run(create_admin(email, password, args.name))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-admin", help="Создать/обновить локального суперадмина")
    p.add_argument("--email", default=os.getenv("SV_ADMIN_EMAIL"))
    p.add_argument("--password", default=os.getenv("SV_ADMIN_PASSWORD"))
    p.add_argument("--name", default=os.getenv("SV_ADMIN_NAME", "Администратор"))
    p.set_defaults(func=_cmd_create_admin)

    ps = sub.add_parser("seed-roles", help="Создать встроенные роли с правами")
    ps.set_defaults(func=_cmd_seed_roles)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
