"""The SALES walk, for the inventory.

A showroom login sees stones and their sale side; it must never see a cost
rate, a valuation, a pouch value or a supplier. A new inventory screen that is
not listed here fails ``test_every_inventory_screen_is_walked``.
"""
import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from inventory.tests.conftest import SUPPLIER, VALUE

pytestmark = pytest.mark.django_db

SCREENS = [
    ("inventory:shelf", {}, ""),
    ("inventory:colour", {"code": "G"}, "?all=1"),
    ("inventory:batch", {"pk": "batch"}, ""),
    ("inventory:batch", {"pk": "batch"}, "?view=table"),
    ("inventory:pouch", {"ref": "onyx"}, ""),
    ("inventory:movements", {"ref": "onyx"}, ""),
]

#: POST-only, or gated whole on inv_masters and asserted to 403 below
EXEMPT = {
    "inventory:set_view", "inventory:pouch_save", "inventory:pouch_price", "inventory:pouch_photos",
    "inventory:import_home", "inventory:import_review", "inventory:import_commit",
}


def _url(name, kwargs, query, shelf):
    resolved = {}
    for key, value in kwargs.items():
        if key == "pk":
            resolved[key] = shelf[value].pk
        elif key == "ref":
            resolved[key] = shelf[value].ref
        else:
            resolved[key] = value
    return reverse(name, kwargs=resolved) + query


@pytest.mark.parametrize("fixture", ["sales_user", "karigar_user", "graphic_user"])
def test_no_cost_or_supplier_reaches_a_login_without_the_right(client, shelf, request, fixture):
    client.force_login(request.getfixturevalue(fixture))
    for name, kwargs, query in SCREENS:
        response = client.get(_url(name, kwargs, query, shelf))
        assert response.status_code == 200, f"{name} returned {response.status_code}"
        body = response.content.decode()
        for secret in (VALUE, "7,919", SUPPLIER):
            assert secret not in body, f"{name}{query} leaked {secret!r} to {fixture}"


def test_accounts_does_see_them(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(_url("inventory:pouch", {"ref": "onyx"}, "", shelf)).content.decode()
    assert VALUE in body and "7,919" in body and SUPPLIER in body


def test_the_writes_refuse_a_sales_login(client, sales_user, shelf):
    client.force_login(sales_user)
    ref = shelf["onyx"].ref
    for name in ("inventory:pouch_save", "inventory:pouch_price", "inventory:pouch_photos"):
        assert client.post(reverse(name, args=[ref]), {"kind": "list", "rate": "1"}).status_code == 403, name


def test_every_inventory_screen_is_walked():
    covered = {name for name, _, _ in SCREENS}
    named = set()
    for resolver in get_resolver().url_patterns:
        if isinstance(resolver, URLResolver) and resolver.app_name == "inventory":
            for pattern in resolver.url_patterns:
                if isinstance(pattern, URLPattern) and pattern.name:
                    named.add(f"inventory:{pattern.name}")
    missing = named - covered - EXEMPT
    assert not missing, f"inventory screens with no masking check: {sorted(missing)}"
