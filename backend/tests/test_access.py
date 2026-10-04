"""Юнит-тесты Access: префиксы, схлопывание, глобальные права, суперюзер."""

from __future__ import annotations

from app.services.access import Access, collapse


def test_prefix_boundary_is_slash():
    a = Access.build([("fintech/pay", "finding", "read")])
    assert a.allows("finding:read", "fintech/pay")
    assert a.allows("finding:read", "fintech/pay/api")
    assert not a.allows("finding:read", "fintech/payments")
    assert not a.allows("finding:read", "fintech")
    assert not a.allows("finding:read", None)


def test_collapse_nested_prefixes():
    assert collapse(["fintech", "fintech/payments", "retail/x"]) == {"fintech", "retail/x"}
    a = Access.build([("fintech/payments", "entity", "read"), ("fintech", "entity", "read")])
    assert a.prefixes("entity:read") == {"fintech"}


def test_union_of_bindings_and_global_wins():
    a = Access.build(
        [("a", "finding", "read"), ("b", "finding", "read"), (None, "finding", "triage")]
    )
    assert a.prefixes("finding:read") == {"a", "b"}
    assert a.is_global("finding:triage")
    assert a.allows("finding:triage", "anything/at/all")
    b = Access.build([("a", "entity", "read"), (None, "entity", "read")])
    assert b.is_global("entity:read")


def test_global_only_ignored_in_project_binding():
    a = Access.build([("a", "role", "write"), ("a", "sla", "manage"), ("a", "group", "write")])
    assert not a.anywhere("role:write")
    assert not a.anywhere("sla:manage")
    assert not a.anywhere("group:write")
    g = Access.build([(None, "role", "write")])
    assert g.is_global("role:write")


def test_any_binding_perms_are_global():
    a = Access.build([("a", "group", "read"), ("a", "sla", "read")])
    assert a.is_global("group:read")
    assert a.is_global("sla:read")


def test_superuser_has_everything():
    a = Access.build([], is_superuser=True)
    assert a.is_global("access:manage")
    assert a.allows("finding:approve", "x/y")
    assert a.can_see("x")


def test_no_grants():
    a = Access.build([])
    assert not a.anywhere("finding:read")
    assert a.prefixes("finding:read") == frozenset()
    assert not a.can_see("a")


def test_stub_visibility_covers_ancestors_and_descendants():
    a = Access.build([("fintech/payments", "finding", "read")])
    assert a.can_see("fintech")
    assert a.can_see("fintech/payments")
    assert a.can_see("fintech/payments/api")
    assert not a.can_see("fintech/cards")
    assert not a.can_see("retail")


def test_scoped_permissions_shape():
    a = Access.build([("b", "finding", "read"), ("a", "finding", "read"), (None, "sla", "read")])
    assert a.scoped_permissions() == {"finding:read": ["a", "b"], "sla:read": "*"}


def test_global_reference_perms_do_not_open_tree():
    a = Access.build([("a", "finding", "read"), ("a", "group", "read"), (None, "role", "read")])
    assert a.can_see("a")
    assert not a.can_see("b")
