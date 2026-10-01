"""The SALES walk, for the inventory.

A showroom login sees stones and their sale side; it must never see a cost
rate, a valuation, a pouch value or a supplier. A new inventory screen that is
not listed here fails ``test_every_inventory_screen_is_walked``.
"""
import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from inventory.models import Movement
from inventory.tests.conftest import (
    CUSTOMER, DIA_COST, DIA_COST_VALUE, DIA_SALE, DIA_SALE_VALUE, DIA_SUPPLIER, KARIGAR, PURCHASE_COST, SUPPLIER, VALUE,
)

pytestmark = pytest.mark.django_db

#: shelf/box-colour total: onyx (98,987.5) + ruby (40 ct × ₹50 = 2,000), rounded.
#: Both pouches share box colour G, so this is also the only colour's total.
TOTAL_VALUE = "1,00,988"

SCREENS = [
    ("inventory:shelf", {}, ""),
    ("inventory:colour", {"code": "G"}, "?all=1"),
    ("inventory:batch", {"pk": "batch"}, ""),
    ("inventory:batch", {"pk": "batch"}, "?view=table"),
    ("inventory:pouch", {"ref": "onyx"}, ""),
    ("inventory:movements", {"ref": "onyx"}, ""),
]

#: POST-only, a redirect to the bucket (test_client_view checks its name), or
#: gated whole on inv_masters and asserted to 403 below
EXEMPT = {
    "inventory:set_view", "inventory:pouch_save", "inventory:pouch_price", "inventory:pouch_photos", "inventory:photo",
    "inventory:import_home", "inventory:import_review", "inventory:import_commit",
    # diamond writes: POST-only and gated on inv_masters (the rights toggle on admin); each is asserted
    # to 403 for a SALES login in test_dia_settings.test_every_diamond_write_refuses_a_login_without_inv_masters
    "inventory:dia_term_add", "inventory:dia_term_rename", "inventory:dia_term_delete", "inventory:dia_expansion",
    "inventory:dia_code_save", "inventory:dia_rate_save", "inventory:dia_rates_ivy", "inventory:dia_supplier_save",
    "inventory:dia_right_toggle",
    # gated whole on inv_masters, asserted in the same test
    "inventory:dia_import_home", "inventory:dia_import_review", "inventory:dia_import_commit",
    # ledger writes: POST-only; each refuses a login without its right (403), asserted in
    # test_the_ledger_writes_refuse_a_login_without_the_right below
    "inventory:movement_post", "inventory:document_settle", "inventory:document_undo", "inventory:document_reverse",
}

DIAMOND_SCREENS = [
    ("inventory:diamonds", ""),
    ("inventory:diamonds", "?cat=Natural+Diamond"),
    ("inventory:dia_settings", ""),
]


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
        for secret in (VALUE, "7,919", SUPPLIER, TOTAL_VALUE):
            assert secret not in body, f"{name}{query} leaked {secret!r} to {fixture}"


def test_accounts_does_see_them(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(_url("inventory:pouch", {"ref": "onyx"}, "", shelf)).content.decode()
    assert VALUE in body and "7,919" in body and SUPPLIER in body
    shelf_body = client.get(_url("inventory:shelf", {}, "", shelf)).content.decode()
    assert TOTAL_VALUE in shelf_body, "accounts should see the shelf's stock-value total"


def test_the_writes_refuse_a_sales_login(client, sales_user, shelf):
    client.force_login(sales_user)
    ref = shelf["onyx"].ref
    for name in ("inventory:pouch_save", "inventory:pouch_price", "inventory:pouch_photos"):
        assert client.post(reverse(name, args=[ref]), {"kind": "list", "rate": "1"}).status_code == 403, name
    #: whole screen gated on inv_masters; the permission check runs before the
    #: batch lookup, so a nonexistent batch_id still gets 403, not 404.
    assert client.get(reverse("inventory:import_review", args=[1])).status_code == 403


@pytest.mark.parametrize("fixture, secrets", [
    ("sales_user", (DIA_COST, DIA_COST_VALUE, DIA_SUPPLIER)),
    ("karigar_user", (DIA_COST, DIA_COST_VALUE, DIA_SALE, DIA_SALE_VALUE, DIA_SUPPLIER)),
    ("graphic_user", (DIA_COST, DIA_COST_VALUE, DIA_SALE, DIA_SALE_VALUE, DIA_SUPPLIER)),
])
def test_no_diamond_money_reaches_a_login_without_the_right(client, diamonds, request, fixture, secrets):
    client.force_login(request.getfixturevalue(fixture))
    for name, query in DIAMOND_SCREENS:
        response = client.get(reverse(name) + query)
        assert response.status_code == 200, f"{name} returned {response.status_code}"
        body = response.content.decode()
        for secret in secrets:
            assert secret not in body, f"{name}{query} leaked {secret!r} to {fixture}"


def test_accounts_sees_diamond_money(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert DIA_COST in body and DIA_COST_VALUE in body and DIA_SALE_VALUE in body
    assert DIA_SUPPLIER in client.get(reverse("inventory:dia_settings")).content.decode()


def test_an_admin_preview_masks_like_the_role(client, admin_user_, diamonds):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:diamonds"), {"as": "KARIGAR"}).content.decode()
    for secret in (DIA_COST, DIA_SALE, DIA_SALE_VALUE):
        assert secret not in body


def test_every_inventory_screen_is_walked():
    covered = {name for name, _, _ in SCREENS} | {name for name, _ in DIAMOND_SCREENS} | LEDGER_SCREENS
    named = set()
    for resolver in get_resolver().url_patterns:
        if isinstance(resolver, URLResolver) and resolver.app_name == "inventory":
            for pattern in resolver.url_patterns:
                if isinstance(pattern, URLPattern) and pattern.name:
                    named.add(f"inventory:{pattern.name}")
    missing = named - covered - EXEMPT
    assert not missing, f"inventory screens with no masking check: {sorted(missing)}"


#: the ledger's screens, walked by test_no_ledger_screen_shows_a_login_what_it_may_not_see
LEDGER_SCREENS = {"inventory:document", "inventory:job_work_list", "inventory:memo_list", "inventory:recent",
                  "inventory:purchase", "inventory:split", "inventory:transfer"}


def _ledger_urls(d):
    """Every ledger screen, plus the shelf, pouch and movements pages the documents now show on."""
    return [
        reverse("inventory:movements", args=[d["onyx"].ref]), reverse("inventory:movements", args=[d["ruby"].ref]),
        reverse("inventory:movements", args=[d["bought"].ref]),
        reverse("inventory:document", args=[d["job"].pk]), reverse("inventory:document", args=[d["memo"].pk]),
        reverse("inventory:document", args=[d["purchase"].pk]),
        reverse("inventory:job_work_list"), reverse("inventory:job_work_list") + "?closed=1",
        reverse("inventory:memo_list"), reverse("inventory:memo_list") + "?closed=1",
        reverse("inventory:recent"), reverse("inventory:recent") + "?kind=job_work",
        reverse("inventory:purchase"),
        reverse("inventory:split", args=[d["onyx"].ref]), reverse("inventory:transfer", args=[d["onyx"].ref]),
        reverse("inventory:shelf"), reverse("inventory:pouch", args=[d["bought"].ref]),
    ]


@pytest.mark.parametrize("fixture, secrets", [
    ("sales_user", ("7,919", PURCHASE_COST, SUPPLIER, KARIGAR)),
    ("karigar_user", ("7,919", PURCHASE_COST, SUPPLIER, CUSTOMER)),
    ("production_user", ("7,919", PURCHASE_COST, CUSTOMER)),
    ("graphic_user", ("7,919", PURCHASE_COST, SUPPLIER, KARIGAR, CUSTOMER)),
])
def test_no_ledger_screen_shows_a_login_what_it_may_not_see(client, ledger_docs, request, fixture, secrets):
    client.force_login(request.getfixturevalue(fixture))
    for url in _ledger_urls(ledger_docs):
        response = client.get(url)
        assert response.status_code in (200, 403), f"{url} returned {response.status_code}"
        body = response.content.decode()
        for secret in secrets:
            assert secret not in body, f"{url} leaked {secret!r} to {fixture}"


def test_each_name_and_cost_reaches_those_who_may_see_it(client, ledger_docs, accounts_user, karigar_user, sales_user):
    def body(user, doc):
        client.force_login(user)
        return client.get(reverse("inventory:document", args=[ledger_docs[doc].pk])).content.decode()

    assert KARIGAR in body(karigar_user, "job")
    assert CUSTOMER in body(sales_user, "memo")
    assert KARIGAR in body(accounts_user, "job") and "₹7,919" in body(accounts_user, "job")
    assert CUSTOMER in body(accounts_user, "memo")
    purchase = body(accounts_user, "purchase")
    assert PURCHASE_COST in purchase and SUPPLIER in purchase
    assert "Out on job work / memo" in client.get(reverse("inventory:shelf")).content.decode()


def test_client_view_reaches_no_ledger_screen_or_write(client, admin_user_, ledger_docs):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    d = ledger_docs
    client_screens = {reverse("inventory:shelf"), reverse("inventory:pouch", args=[d["bought"].ref])}
    for url in _ledger_urls(d):
        if url not in client_screens:
            assert client.get(url).status_code == 302, url
    for url in (reverse("inventory:movement_post", args=[d["onyx"].ref]),
                reverse("inventory:document_settle", args=[d["job"].pk]),
                reverse("inventory:document_undo", args=[d["job"].pk]),
                reverse("inventory:document_reverse", args=[d["job"].pk])):
        assert client.post(url, {"reason": "Sale", "ct": "1"}).status_code == 302, url
    for url in client_screens:
        body = client.get(url).content.decode()
        for secret in (KARIGAR, CUSTOMER, SUPPLIER, "2026/0431", "MEMO-0088", "2026/0442"):
            assert secret not in body, f"{url} sent {secret!r} in client view"


def test_the_ledger_writes_refuse_a_login_without_the_right(client, sales_user, ledger_docs):
    d = ledger_docs
    client.force_login(sales_user)
    before = Movement.objects.count()
    for url, data in [
        (reverse("inventory:movement_post", args=[d["onyx"].ref]), {"reason": "Sale", "ct": "1"}),
        (reverse("inventory:document_settle", args=[d["job"].pk]), {"pouch": d["onyx"].pk, "how": "in", "ct": "1"}),
        (reverse("inventory:document_undo", args=[d["job"].pk]), {}),
        (reverse("inventory:document_reverse", args=[d["purchase"].pk]), {}),
        (reverse("inventory:purchase"), {"supplier": d["supplier"].pk}),
        (reverse("inventory:split", args=[d["onyx"].ref]), {"out_ct": "1", "pouch_no": "9", "ct": "1"}),
        (reverse("inventory:transfer", args=[d["onyx"].ref]), {"batch": "SL01G", "pouch_no": "9"}),
    ]:
        assert client.post(url, data).status_code == 403, url
    assert Movement.objects.count() == before
