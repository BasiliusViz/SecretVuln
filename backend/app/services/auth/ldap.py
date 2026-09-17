"""LDAP-аутентификация (ldap3).

Поток: сервисный bind → поиск пользователя по mail → повторный bind под
DN пользователя с его паролем (проверка) → чтение групп. Группы маппятся на
роли SecretVuln выше по стеку (в api/auth.py через Role.ldap_group).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ldap3 import ALL, Connection, Server
from ldap3.core.exceptions import LDAPException

from app.core.config import get_settings


class LdapError(Exception):
    """LDAP недоступен или неверная конфигурация (не путать с неверным паролем)."""


@dataclass
class LdapUser:
    dn: str
    email: str
    full_name: str | None
    groups: list[str] = field(default_factory=list)


@dataclass
class LdapMember:
    """Участник LDAP-группы (для полной синхронизации состава группы)."""

    dn: str
    email: str
    full_name: str | None


def _server() -> Server:
    settings = get_settings()
    return Server(settings.ldap_server, get_info=ALL, connect_timeout=5)


def _service_connection() -> Connection:
    settings = get_settings()
    try:
        return Connection(
            _server(),
            user=settings.ldap_bind_dn,
            password=settings.ldap_bind_password,
            auto_bind=True,
            receive_timeout=5,
        )
    except LDAPException as e:
        raise LdapError(f"Сервисный bind не удался: {e}") from e


def list_group_members(group_cn: str) -> list[LdapMember]:
    """Возвращает всех пользователей LDAP-группы (по её CN).

    Ищем в базе пользователей записи с memberof=<DN группы>. Бросает LdapError
    при проблемах с сервером; пустой список — группа не найдена или пуста.
    """
    settings = get_settings()
    conn = _service_connection()

    group_dn = f"cn={group_cn},{settings.ldap_group_search_base}"
    search_filter = f"(memberof={group_dn})"
    try:
        conn.search(
            search_base=settings.ldap_user_search_base,
            search_filter=search_filter,
            attributes=["cn", "mail"],
        )
    except LDAPException as e:
        conn.unbind()
        raise LdapError(f"Поиск участников группы не удался: {e}") from e

    members: list[LdapMember] = []
    for entry in conn.entries:
        mail = entry["mail"].value if "mail" in entry else None
        if isinstance(mail, list):
            mail = mail[0] if mail else None
        if not mail:
            continue
        cn = entry["cn"].value if "cn" in entry else None
        if isinstance(cn, list):
            cn = cn[0] if cn else None
        members.append(LdapMember(dn=entry.entry_dn, email=mail, full_name=cn))

    conn.unbind()
    return members


def authenticate(email: str, password: str) -> LdapUser | None:
    """Возвращает LdapUser при успехе, None при неверных учётных данных.

    Бросает LdapError, если сервер недоступен или сервисный bind не удался.
    """
    settings = get_settings()
    server = _server()

    # 1. Сервисный bind — ищем пользователя по mail.
    try:
        svc = Connection(
            server,
            user=settings.ldap_bind_dn,
            password=settings.ldap_bind_password,
            auto_bind=True,
            receive_timeout=5,
        )
    except LDAPException as e:
        raise LdapError(f"Сервисный bind не удался: {e}") from e

    user_filter = settings.ldap_user_filter.format(email=email)
    try:
        svc.search(
            search_base=settings.ldap_user_search_base,
            search_filter=user_filter,
            # lldap строг к именам атрибутов — берём только гарантированно
            # существующие (в нижнем регистре).
            attributes=["cn", "mail", "memberof"],
        )
    except LDAPException as e:
        svc.unbind()
        raise LdapError(f"Поиск пользователя не удался: {e}") from e

    if not svc.entries:
        svc.unbind()
        return None  # нет такого пользователя

    entry = svc.entries[0]
    user_dn = entry.entry_dn
    svc.unbind()

    # 2. Проверка пароля — bind под DN пользователя.
    try:
        user_conn = Connection(server, user=user_dn, password=password, receive_timeout=5)
        if not user_conn.bind():
            return None  # неверный пароль
    except LDAPException:
        return None

    # 3. Атрибуты и группы.
    def _attr(name: str) -> str | None:
        val = entry[name].value if name in entry else None
        if isinstance(val, list):
            return val[0] if val else None
        return val

    full_name = _attr("cn")
    mail = _attr("mail") or email

    groups: list[str] = []
    member_of = entry["memberof"].value if "memberof" in entry else None
    if member_of:
        raw = member_of if isinstance(member_of, list) else [member_of]
        for dn in raw:
            # cn=secops-admins,ou=groups,... → secops-admins
            first = dn.split(",", 1)[0]
            if first.lower().startswith("cn="):
                groups.append(first[3:])

    user_conn.unbind()
    return LdapUser(dn=user_dn, email=mail, full_name=full_name, groups=groups)
