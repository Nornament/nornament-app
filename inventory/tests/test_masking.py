"""The SALES walk, for the inventory.

A showroom login sees stones and their sale side; it must never see a cost
rate, a valuation, a pouch value or a supplier. A new inventory screen that is
not listed here fails ``test_every_inventory_screen_is_walked``.
"""
from urllib.parse import urlencode

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from inventory.models import DiamondLine, Movement, StockDocument
from inventory.tests.conftest import (
    CUSTOMER, DIA_COST, DIA_COST_VALUE, DIA_LINE_COST, DIA_OVERRIDE, DIA_SALE, DIA_SALE_VALUE, DIA_SUPPLIER, KARIGAR,
    PURCHASE_COST, SUPPLIER, VALUE,
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
    # diamond ledger writes: POST-only; each refuses a login without its right (403), asserted in
    # test_the_diamond_ledger_writes_refuse_a_login_without_the_right below
    "inventory:dia_job_new", "inventory:dia_job_post", "inventory:dia_job_close", "inventory:dia_job_undo",
    "inventory:dia_job_reverse", "inventory:dia_assort_reverse", "inventory:dia_purchase_reverse",
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
    covered = ({name for name, _, _ in SCREENS} | {name for name, _ in DIAMOND_SCREENS} | LEDGER_SCREENS
               | DIA_LEDGER_SCREENS | FINDER_SCREENS | PRICE_SCREENS | STOCK_TAKE_SCREENS | LOOKBOOK_SCREENS)
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
                  "inventory:purchase", "inventory:split", "inventory:transfer", "inventory:merge"}

#: part 5d's stock-take screens, walked by test_no_stock_take_screen_shows_a_login_what_it_may_not_see
STOCK_TAKE_SCREENS = {"inventory:stock_takes", "inventory:stock_take", "inventory:dia_stock_takes",
                      "inventory:dia_stock_take"}

#: part 5e's lookbook screens, walked by test_no_lookbook_screen_shows_a_login_what_it_may_not_see
LOOKBOOK_SCREENS = {"inventory:lookbooks", "inventory:lookbook", "inventory:lookbook_add"}


@pytest.fixture
def lookbook(sales_user, shelf):
    from inventory import lookbooks

    book = lookbooks.create(sales_user, "Greens")
    lookbooks.add_stones(sales_user, book, shelf["onyx"].ref)
    return book


@pytest.mark.parametrize("fixture", ["sales_user", "karigar_user", "production_user", "graphic_user"])
def test_no_lookbook_screen_shows_a_login_what_it_may_not_see(client, lookbook, shelf, request, fixture):
    client.force_login(request.getfixturevalue(fixture))
    list_body = client.get(reverse("inventory:lookbooks")).content.decode()
    assert lookbook.title in list_body                          # non-vacuous: every role sees its lookbooks
    detail_body = client.get(reverse("inventory:lookbook", args=[lookbook.pk])).content.decode()
    assert shelf["onyx"].ref in detail_body                      # non-vacuous: every role sees its stones
    for body in (list_body, detail_body):
        for secret in ("7,919", VALUE, SUPPLIER):
            assert secret not in body, f"leaked {secret!r} to {fixture}"
    add_url = reverse("inventory:lookbook_add", args=[shelf["onyx"].ref])
    response = client.get(add_url)
    if fixture == "sales_user":
        # the sale right does see the add-to-lookbook form
        assert response.status_code == 200 and shelf["onyx"].ref in response.content.decode()
    else:
        assert response.status_code == 403, f"{add_url} returned {response.status_code} to {fixture}"


@pytest.fixture
def counted(admin_user_, shelf):
    from decimal import Decimal

    from inventory import stock_take
    from inventory.models import StockTake

    take = stock_take.start(admin_user_, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(admin_user_, take, {shelf["onyx"].pk: (20, Decimal("10.5"))})   # −2 ct × ₹7,919
    return take


@pytest.mark.parametrize("fixture", ["sales_user", "karigar_user", "production_user", "graphic_user"])
def test_no_stock_take_screen_shows_a_login_what_it_may_not_see(client, counted, request, fixture):
    client.force_login(request.getfixturevalue(fixture))
    for url in (reverse("inventory:stock_takes"), reverse("inventory:stock_take", args=[counted.pk])):
        response = client.get(url)
        assert response.status_code == 200, url
        assert "15,838" not in response.content.decode(), f"{url} leaked the variance value to {fixture}"


def test_accounts_sees_the_variance_value(client, accounts_user, counted):
    client.force_login(accounts_user)
    assert "15,838" in client.get(reverse("inventory:stock_take", args=[counted.pk])).content.decode()


@pytest.fixture
def dia_counted(admin_user_, diamonds):
    from decimal import Decimal

    from inventory import stock_take
    from inventory.models import DiamondTerm, StockTake

    natural = DiamondTerm.objects.get(kind="category", value="Natural Diamond")
    take = stock_take.start(admin_user_, StockTake.DIAMONDS, category=natural)
    stock_take.save_counts(admin_user_, take, {diamonds["round"].pk: (None, Decimal("3"))})   # −0.4 ct × ₹16,517
    return take


@pytest.mark.parametrize("fixture", ["sales_user", "karigar_user", "production_user", "graphic_user"])
def test_no_diamond_stock_take_screen_shows_a_login_what_it_may_not_see(client, dia_counted, request, fixture):
    client.force_login(request.getfixturevalue(fixture))
    for url in (reverse("inventory:dia_stock_takes"), reverse("inventory:dia_stock_take", args=[dia_counted.pk])):
        response = client.get(url)
        assert response.status_code == 200, url
        assert "6,607" not in response.content.decode(), f"{url} leaked the variance value to {fixture}"


def test_accounts_sees_the_diamond_variance_value(client, accounts_user, dia_counted):
    client.force_login(accounts_user)
    assert "6,607" in client.get(reverse("inventory:dia_stock_take", args=[dia_counted.pk])).content.decode()


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
        reverse("inventory:merge", args=[d["onyx"].ref]),
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
                reverse("inventory:document_reverse", args=[d["job"].pk]),
                reverse("inventory:merge", args=[d["onyx"].ref])):
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
        (reverse("inventory:merge", args=[d["onyx"].ref]), {"pouch": [d["onyx"].pk, d["ruby"].pk], "into": "new",
                                                           "new_pouch_no": "9"}),
    ]:
        assert client.post(url, data).status_code == 403, url
    assert Movement.objects.count() == before


#: the diamond ledgers' screens, walked by test_no_diamond_ledger_screen_shows_a_login_what_it_may_not_see
DIA_LEDGER_SCREENS = {"inventory:dia_jobs", "inventory:dia_assorts", "inventory:dia_purchase"}

#: what each role may not see on a diamond ledger screen (Production sees suppliers; the Karigar desk, karigars)
DIA_SECRETS = {
    "SALES": (KARIGAR, DIA_SUPPLIER, DIA_LINE_COST, DIA_OVERRIDE, DIA_COST),
    "KARIGAR": (DIA_SUPPLIER, DIA_LINE_COST, DIA_OVERRIDE, DIA_COST),
    "PRODUCTION": (DIA_LINE_COST, DIA_OVERRIDE, DIA_COST),
    "GRAPHIC": (KARIGAR, DIA_SUPPLIER, DIA_LINE_COST, DIA_OVERRIDE, DIA_COST),
}
#: the forms a page shows only to a login that may post, and never in a preview
DIA_FORMS = ("Post an entry", "＋ New job card", "↺ Undo last entry", "＋ New assortment", "Post purchase",
             ">Reverse</button>")


def _dia_ledger_urls(d):
    """Every diamond ledger screen, with each document picked."""
    jobs, assorts = reverse("inventory:dia_jobs"), reverse("inventory:dia_assorts")
    return [jobs, f"{jobs}?card={d['card'].pk}", f"{jobs}?closed=1", assorts, f"{assorts}?doc={d['assort'].pk}",
            reverse("inventory:dia_purchase")]


def _dia_urls(d):
    """The ledger screens plus Search and Settings, where a purchased or assorted line's own cost
    and a supplier's purchases now show."""
    return _dia_ledger_urls(d) + [reverse("inventory:diamonds"), reverse("inventory:dia_settings")]


@pytest.mark.parametrize("fixture, role", [("sales_user", "SALES"), ("karigar_user", "KARIGAR"),
                                           ("production_user", "PRODUCTION"), ("graphic_user", "GRAPHIC")])
def test_no_diamond_ledger_screen_shows_a_login_what_it_may_not_see(client, dia_docs, request, fixture, role):
    client.force_login(request.getfixturevalue(fixture))
    for url in _dia_urls(dia_docs):
        response = client.get(url)
        assert response.status_code == 200, f"{url} returned {response.status_code}"
        body = response.content.decode()
        for secret in DIA_SECRETS[role]:
            assert secret not in body, f"{url} leaked {secret!r} to {fixture}"


@pytest.mark.parametrize("role", ["SALES", "KARIGAR", "PRODUCTION", "GRAPHIC", "ACCOUNTS"])
def test_an_admin_preview_of_each_diamond_ledger_masks_like_the_role_and_hides_every_form(
        client, admin_user_, dia_docs, role):
    client.force_login(admin_user_)
    ledger_urls = _dia_ledger_urls(dia_docs)
    for url in _dia_urls(dia_docs):
        previewed = f"{url}{'&' if '?' in url else '?'}as={role}"
        body = client.get(previewed).content.decode()
        for secret in DIA_SECRETS.get(role, ()):
            assert secret not in body, f"{previewed} leaked {secret!r}"
        # Settings' rights matrix has a "Post purchase" column, so only the ledger screens are checked for forms
        for form in DIA_FORMS if url in ledger_urls else ():
            assert form not in body, f"{previewed} showed {form!r} in a preview"


def test_each_diamond_name_and_cost_reaches_those_who_may_see_it(client, accounts_user, karigar_user, dia_docs):
    client.force_login(karigar_user)
    assert KARIGAR in client.get(reverse("inventory:dia_jobs")).content.decode()
    client.force_login(accounts_user)
    assert KARIGAR in client.get(reverse("inventory:dia_jobs")).content.decode()
    purchases = client.get(reverse("inventory:dia_purchase")).content.decode()
    assert DIA_SUPPLIER in purchases and "₹46,912" in purchases                   # 2 ct × ₹23,456
    search = client.get(reverse("inventory:diamonds")).content.decode()
    assert DIA_LINE_COST in search and DIA_OVERRIDE in search
    assert "Cost / ct" in client.get(reverse("inventory:dia_assorts")).content.decode()


def test_the_diamond_ledger_writes_refuse_a_login_without_the_right(client, sales_user, dia_docs):
    d = dia_docs
    client.force_login(sales_user)
    before = (Movement.objects.count(), StockDocument.objects.count())
    for url, data in [
        (reverse("inventory:dia_job_new"), {}),
        (reverse("inventory:dia_job_post", args=[d["card"].pk]), {"entry": "loose", "line": d["round"].pk, "ct": "1"}),
        (reverse("inventory:dia_job_close", args=[d["card"].pk]), {}),
        (reverse("inventory:dia_job_undo", args=[d["card"].pk]), {}),
        (reverse("inventory:dia_job_reverse", args=[d["card"].pk]), {}),
        (reverse("inventory:dia_assorts"), {"source": d["round"].pk, "take_out": "1", "ct": "1"}),
        (reverse("inventory:dia_assort_reverse", args=[d["assort"].pk]), {}),
        (reverse("inventory:dia_purchase"), {"supplier": d["supplier"].pk}),
        (reverse("inventory:dia_purchase_reverse", args=[d["purchase"].pk]), {}),
    ]:
        assert client.post(url, data).status_code == 403, url
    assert (Movement.objects.count(), StockDocument.objects.count()) == before


def test_no_stones_screen_lists_or_opens_a_diamond_document(client, accounts_user, shelf, dia_docs):
    client.force_login(accounts_user)
    recent = client.get(reverse("inventory:recent")).content.decode()
    for doc in ("card", "assort", "purchase"):
        assert dia_docs[doc].number not in recent, doc
        assert client.get(reverse("inventory:document", args=[dia_docs[doc].pk])).status_code == 404, doc
    for url in (reverse("inventory:job_work_list") + "?closed=1", reverse("inventory:shelf")):
        assert dia_docs["card"].number not in client.get(url).content.decode(), url


#: part 5a's finders, walked by test_no_finder_shows_a_login_what_it_may_not_see
FINDER_SCREENS = {"inventory:search", "inventory:quality", "inventory:splits", "inventory:transfers",
                  "inventory:dia_movements", "inventory:dia_line"}

#: part 5b's price lists, walked by test_no_price_list_shows_a_login_what_it_may_not_see
PRICE_SCREENS = {"inventory:prices_cost", "inventory:prices_selling"}


@pytest.mark.parametrize("fixture, secrets", [
    ("sales_user", ("7,919", VALUE, TOTAL_VALUE, SUPPLIER)),
    ("karigar_user", ("7,919", VALUE, TOTAL_VALUE, SUPPLIER)),
    ("production_user", ("7,919", VALUE, TOTAL_VALUE)),
    ("graphic_user", ("7,919", VALUE, TOTAL_VALUE, SUPPLIER)),
])
def test_no_price_list_shows_a_login_what_it_may_not_see(client, shelf, request, fixture, secrets):
    client.force_login(request.getfixturevalue(fixture))
    for name in sorted(PRICE_SCREENS):
        for query in ("", "?f=1"):
            response = client.get(reverse(name) + query)
            assert response.status_code in (200, 403), f"{name} returned {response.status_code}"
            body = response.content.decode()
            for secret in secrets:
                assert secret not in body, f"{name}{query} leaked {secret!r} to {fixture}"


def test_the_cost_list_shows_cost_to_accounts(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:prices_cost")).content.decode()
    assert "7,919" in body and VALUE in body and TOTAL_VALUE in body


@pytest.mark.parametrize("fixture", ["sales_user", "karigar_user", "production_user", "graphic_user"])
def test_no_price_list_post_writes_for_a_login_without_the_right(client, shelf, request, fixture):
    from inventory.models import PriceEntry

    client.force_login(request.getfixturevalue(fixture))
    before = PriceEntry.objects.count()
    for name in sorted(PRICE_SCREENS):
        response = client.post(reverse(name), {"f": "1", "stock": "1", "count": "2", "rate": "1"})
        assert response.status_code == 403, f"{name} returned {response.status_code} to {fixture}"
    assert PriceEntry.objects.count() == before


#: what each login may not see on a finder (Production sees suppliers and karigars; the Karigar desk, karigars)
#: SUPPLIER, CUSTOMER and PURCHASE_COST never render on any finder screen today (none of search, the
#: quality filters, splits/transfers or the diamond Movements/line pages show a stones vendor, customer
#: or purchase cost), so their absence here guards against a future screen growing one rather than
#: proving masking now. The non-vacuous check for those three is
#: test_no_ledger_screen_shows_a_login_what_it_may_not_see, which walks the document and purchase
#: screens where an allowed role does see them (test_each_name_and_cost_reaches_those_who_may_see_it).
FINDER_SECRETS = {
    "sales_user": ("7,919", PURCHASE_COST, SUPPLIER, KARIGAR, DIA_SUPPLIER, DIA_LINE_COST, DIA_OVERRIDE, DIA_COST),
    "karigar_user": ("7,919", PURCHASE_COST, SUPPLIER, CUSTOMER, DIA_SUPPLIER, DIA_LINE_COST, DIA_OVERRIDE, DIA_COST),
    "production_user": ("7,919", PURCHASE_COST, CUSTOMER, DIA_LINE_COST, DIA_OVERRIDE, DIA_COST),
    "graphic_user": ("7,919", PURCHASE_COST, SUPPLIER, KARIGAR, CUSTOMER, DIA_SUPPLIER, DIA_LINE_COST, DIA_OVERRIDE,
                     DIA_COST),
}


def _dia_finder_urls():
    """The diamond Movements list, each kind of it, and every line's ledger."""
    movements = reverse("inventory:dia_movements")
    return ([movements] + [f"{movements}?kind={kind}" for kind in ("dia_job", "dia_assort", "dia_purchase")]
            + [reverse("inventory:dia_line", args=[ref]) for ref in DiamondLine.objects.values_list("ref", flat=True)])


def _stones_finder_urls(d):
    """Search (each kind of match), the four filters, and the two lists."""
    search = reverse("inventory:search")
    queries = ("SL01G", "Onyx", d["stones"]["onyx"].ref, "SL01G 7", "B-771", "DRFGH", "NRD-000001")
    return ([f"{search}?{urlencode({'q': q})}" for q in queries]
            + [reverse("inventory:quality", args=[check]) for check in ("misfiled", "no_pouch_no", "no_photo", "no_size")]
            + [reverse("inventory:splits"), reverse("inventory:transfers")])


@pytest.mark.parametrize("fixture", sorted(FINDER_SECRETS))
def test_no_finder_shows_a_login_what_it_may_not_see(client, finder_docs, request, fixture):
    client.force_login(request.getfixturevalue(fixture))
    for url in _stones_finder_urls(finder_docs) + _dia_finder_urls():
        response = client.get(url)
        assert response.status_code == 200, f"{url} returned {response.status_code}"
        body = response.content.decode()
        for secret in FINDER_SECRETS[fixture]:
            assert secret not in body, f"{url} leaked {secret!r} to {fixture}"


@pytest.mark.parametrize("role", ["SALES", "KARIGAR", "PRODUCTION", "GRAPHIC"])
def test_an_admin_preview_of_each_diamond_finder_masks_like_the_role(client, admin_user_, finder_docs, role):
    client.force_login(admin_user_)
    for url in _dia_finder_urls():
        previewed = f"{url}{'&' if '?' in url else '?'}as={role}"
        body = client.get(previewed).content.decode()
        for secret in DIA_SECRETS[role]:
            assert secret not in body, f"{previewed} leaked {secret!r}"


def test_each_finder_shows_names_and_cost_to_those_who_may_see_them(client, accounts_user, finder_docs):
    client.force_login(accounts_user)
    assert "₹7,919" in client.get(reverse("inventory:quality", args=["no_photo"])).content.decode()
    movements = client.get(reverse("inventory:dia_movements")).content.decode()
    assert KARIGAR in movements and DIA_SUPPLIER in movements
    assorted = finder_docs["dia"]["assort"].movements.get(reason=Movement.Reason.ASSORT_IN).diamond
    assert DIA_OVERRIDE in client.get(reverse("inventory:dia_line", args=[assorted.ref])).content.decode()
    bought = finder_docs["dia"]["purchase"].movements.get().diamond
    assert DIA_LINE_COST in client.get(reverse("inventory:dia_line", args=[bought.ref])).content.decode()
    round_line = finder_docs["dia"]["round"]
    assert DIA_COST in client.get(reverse("inventory:dia_line", args=[round_line.ref])).content.decode()
    splits = client.get(reverse("inventory:splits")).content.decode()
    assert finder_docs["split"].number in splits and "SL01G · 7" in splits
    assert "SL02G · 5" in client.get(reverse("inventory:transfers")).content.decode()


def test_client_view_reaches_no_stones_finder(client, admin_user_, finder_docs):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    for url in _stones_finder_urls(finder_docs):
        response = client.get(url)
        assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf"), url
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert f'action="{reverse("inventory:search")}"' not in body and "Search batch, pouch, stone… 🔒" in body
