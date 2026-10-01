from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import services
from inventory.models import Pouch, StockDocument
from stock.models import Vendor

pytestmark = pytest.mark.django_db
D = Decimal


def _post(client, user, shelf, **changes):
    data = {"supplier": shelf["supplier"].pk, "occurred_on": "2026-08-07", "invoice_no": "2026/0442",
            "currency": "INR", "fx_rate": "", "landed_extras": "5370",
            "batch": ["SL01G", "sl01g"], "pouch_no": ["3", "4"], "stone_name": ["Tanzanite", "Tanzanite"],
            "shape": ["Oval", "Round"], "colour": ["Blue", "Blue"], "pcs": ["12", ""], "ct": ["42.50", "11.20"],
            "cost": ["1,800", "2400"]}
    client.force_login(user)
    return client.post(reverse("inventory:purchase"), data | changes)


def test_the_screen_is_the_prototypes(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:purchase")).content.decode()
    for text in ("Record a purchase", "The purchase", "Supplier", "Purchase date", "Invoice / bill no.", "Currency",
                 "Landed extras — freight, duty, cutting", "Lines in this purchase", "Pieces", "Cost value",
                 "＋ Add line", "What posting will do", "selling price is <b>not</b> set here", "Post purchase",
                 "Price list", "Realised price", "Stock control", "Recount Adjustment"):
        assert text in body, text
    assert shelf["supplier"].name in body and '"SL01G": 3' in body       # the next free pouch no., for suggesting


@pytest.mark.parametrize("fixture", ["sales_user", "production_user", "karigar_user", "graphic_user"])
def test_the_screen_needs_the_purchase_right(client, shelf, request, fixture):
    client.force_login(request.getfixturevalue(fixture))
    assert client.get(reverse("inventory:purchase")).status_code == 403


def test_posting_opens_the_pouches_and_lands_on_the_document(client, accounts_user, shelf):
    response = _post(client, accounts_user, shelf)
    doc = StockDocument.objects.get(number="2026/0442")
    assert response.status_code == 302 and response["Location"] == reverse("inventory:document", args=[doc.pk])
    four = Pouch.objects.get(batch=shelf["batch"], pouch_no="4")
    assert not four.countable and services.stocked().get(pk=four.pk).rate == D("2500")


def test_a_refusal_comes_back_with_the_lines(client, accounts_user, shelf):
    response = _post(client, accounts_user, shelf, pouch_no=["1", "4"])
    body = response.content.decode()
    assert response.status_code == 200 and "SL01G · 1 already exists" in body
    assert 'value="Tanzanite"' in body and 'value="42.50"' in body
    assert not StockDocument.objects.exists()


def test_usd_needs_its_rate(client, accounts_user, shelf):
    assert "USD needs the rate" in _post(client, accounts_user, shelf, currency="USD").content.decode()


def test_a_purchase_files_into_a_valid_batch_code_and_refuses_any_other(client, accounts_user, shelf):
    from inventory.models import Batch

    body = _post(client, accounts_user, shelf, batch=["TANZ-1", "SL01G"]).content.decode()
    assert "TANZ-1 does not read as family · class · number · box colour." in body
    assert not Batch.objects.filter(code="TANZ-1").exists()
    _post(client, accounts_user, shelf, batch=["SP14B", "SL01G"])
    assert Batch.objects.filter(code="SP14B").exists()       # a new batch, created with the purchase


def test_a_new_supplier_is_created_with_the_purchase(client, accounts_user, shelf):
    _post(client, accounts_user, shelf, supplier="new", new_code="rls", new_name="Ratanlal & Sons")
    assert StockDocument.objects.get().vendor == Vendor.objects.get(code="RLS")


def test_a_refused_purchase_creates_no_supplier(client, accounts_user, shelf):
    _post(client, accounts_user, shelf, supplier="new", new_code="rls", new_name="Ratanlal & Sons", pouch_no=["1", "4"])
    assert not Vendor.objects.filter(code="RLS").exists()


def test_an_over_long_new_supplier_is_refused_on_the_form(client, accounts_user, shelf):
    response = _post(client, accounts_user, shelf, supplier="new", new_code="R" * 33, new_name="Ratanlal & Sons")
    assert response.status_code == 200 and "at most 32 characters" in response.content.decode()
    assert not Vendor.objects.filter(name="Ratanlal & Sons").exists()


def test_the_purchase_tab_opens_for_those_who_may(client, accounts_user, sales_user, shelf):
    client.force_login(accounts_user)
    assert f'href="{reverse("inventory:purchase")}">Purchase</a>' in client.get(reverse("inventory:shelf")).content.decode()
    client.force_login(sales_user)
    assert "<button disabled>Purchase</button>" in client.get(reverse("inventory:shelf")).content.decode()


def test_the_purchase_right_alone_opens_no_link(client, graphic_user, shelf):
    from django.contrib.auth.models import Permission

    graphic_user.user_permissions.add(Permission.objects.get(codename="inv_purchase"))
    client.force_login(graphic_user)
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert f'href="{reverse("inventory:purchase")}"' not in body
    assert "<button disabled>Purchase</button>" in body and 'Purchases<span class="ct">🔒' in body
    assert client.get(reverse("inventory:purchase")).status_code == 403


def test_client_view_never_opens_it(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    assert client.get(reverse("inventory:purchase")).status_code == 302
