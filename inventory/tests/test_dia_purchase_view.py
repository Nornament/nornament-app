import pytest
from django.urls import reverse

from inventory.models import StockDocument
from stock.models import Vendor

pytestmark = pytest.mark.django_db


def _post(client, user, diamonds, **changes):
    """The prototype's purchase: 14.20 ct round at ₹16,500 and 3.60 ct princess at ₹21,000, ₹1,780 extras.
    A change of ``None`` leaves that field out of the post."""
    data = {"supplier": diamonds["supplier"].pk, "occurred_on": "2026-08-07", "invoice_no": "2026/0442",
            "currency": "INR", "fx_rate": "", "landed_extras": "1780", "note": "",
            "category": ["Natural Diamond", "Natural Diamond"], "shape": ["Round", "Princess"],
            "colour": ["F-G-H", "E-F"], "clarity": ["VS-SI", "VVS-VS"], "size_text": ["+6-12", "+2"],
            "batch_no": ["B-901", ""], "pcs": ["", "40"], "ct": ["14.20", "3.60"], "cost": ["16500", "21000"]}
    client.force_login(user)
    return client.post(reverse("inventory:dia_purchase"),
                       {key: value for key, value in (data | changes).items() if value is not None})


def test_the_purchase_screen_reads_as_the_prototype(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:dia_purchase")).content.decode()
    for text in ("Purchase — the only way diamond stock enters", "The purchase", "Supplier", "Purchase date",
                 "Invoice no.", "Currency", "INR ₹", "USD $", "Lines — each becomes a stock line", "Category",
                 "Shape", "Colour", "Clarity", "Size", "Pieces", "Carats", "Cost / ct", "＋ Add line",
                 "Landed extras — freight, duty, certification", "What posting will do",
                 "reason <code>Purchase</code>", "sale price is <b>not</b> set here", "Post purchase",
                 "Recent purchases", "Kothari Exports, Mumbai", "＋ New supplier…"):
        assert text in body, text
    assert "There is no separate" not in body and "Suppliers are maintained in Settings" not in body   # prose stripped


def test_a_purchase_posts_and_lists_as_recent(client, accounts_user, diamonds):
    response = _post(client, accounts_user, diamonds)
    assert response["Location"] == reverse("inventory:dia_purchase")
    doc = StockDocument.objects.get(kind=StockDocument.Kind.DIA_PURCHASE)
    assert doc.movements.count() == 2
    body = client.get(response["Location"]).content.decode()
    assert "Purchase 2026/0442 posted." in body and "17.80" in body
    assert "₹3,11,680" in body                     # 14.20 × ₹16,600 + 3.60 × ₹21,100: landed, extras spread by weight


def test_a_refusal_comes_back_with_what_was_typed(client, accounts_user, diamonds):
    response = _post(client, accounts_user, diamonds, clarity=["VS-SI", ""])
    body = response.content.decode()
    assert response.status_code == 200 and "needs category, shape, colour, clarity and size" in body
    assert 'value="14.20"' in body and 'value="B-901"' in body and not StockDocument.objects.exists()


def test_usd_needs_its_rate(client, accounts_user, diamonds):
    assert "USD needs the rate" in _post(client, accounts_user, diamonds, currency="USD").content.decode()


def test_a_fancy_colour_line_posts_with_a_blank_clarity(client, accounts_user, diamonds):
    """code_for's ruling (clarity optional only for a Fancy colour), reachable from the screen."""
    response = _post(client, accounts_user, diamonds, category=["Natural Diamond"], shape=["Round"],
                     colour=["Fancy Yellow"], clarity=[""], size_text=["+6"], batch_no=[""],
                     pcs=[""], ct=["1"], cost=["50000"])
    assert response["Location"] == reverse("inventory:dia_purchase")
    doc = StockDocument.objects.get(kind=StockDocument.Kind.DIA_PURCHASE)
    assert doc.movements.count() == 1


def test_a_new_supplier_stands_or_falls_with_its_purchase(client, admin_user_, diamonds):
    _post(client, admin_user_, diamonds, supplier="new", new_code="SRT", new_name="Surat Diamonds",
          clarity=["VS-SI", ""])
    assert not Vendor.objects.filter(code="SRT").exists()
    _post(client, admin_user_, diamonds, supplier="new", new_code="SRT", new_name="Surat Diamonds")
    assert StockDocument.objects.get(kind=StockDocument.Kind.DIA_PURCHASE).vendor.name == "Surat Diamonds"


def test_others_are_not_permitted(client, production_user, sales_user, karigar_user, diamonds):
    for user, label in ((production_user, "Production"), (sales_user, "Sales / Showroom"),
                        (karigar_user, "Karigar desk")):
        client.force_login(user)
        body = client.get(reverse("inventory:dia_purchase")).content.decode()
        assert f"Not permitted for {label}" in body and "Post purchase" not in body
    assert _post(client, production_user, diamonds).status_code == 403
    assert not StockDocument.objects.exists()


def test_an_admin_preview_lists_without_the_form(client, admin_user_, diamonds):
    _post(client, admin_user_, diamonds)
    body = client.get(reverse("inventory:dia_purchase"), {"as": "ACCOUNTS"}).content.decode()
    assert "Recent purchases" in body and "2026/0442" in body
    assert "Post purchase" not in body and ">Reverse</button>" not in body
    body = client.get(reverse("inventory:dia_purchase"), {"as": "PRODUCTION"}).content.decode()
    assert "Not permitted for Production" in body and "2026/0442" not in body


def test_reverse_from_recent_purchases(client, accounts_user, diamonds):
    _post(client, accounts_user, diamonds)
    doc = StockDocument.objects.get(kind=StockDocument.Kind.DIA_PURCHASE)
    body = client.post(reverse("inventory:dia_purchase_reverse", args=[doc.pk]), follow=True).content.decode()
    assert "Reversed by REV-000001" in body and "Reversed</span>" in body


def test_the_diamond_purchase_tab(client, accounts_user, production_user, diamonds):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert f'href="{reverse("inventory:dia_purchase")}">Purchase</a>' in body
    assert f'href="{reverse("inventory:dia_movements")}">Movements</a>' in body and "Stock take 🔒" in body
    client.force_login(production_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert "<button disabled>Purchase 🔒</button>" in body


def test_reversing_a_purchase_needs_every_purchase_right(client, accounts_user, diamonds):
    from django.contrib.auth.models import Group, Permission

    from accounts.models import User

    _post(client, accounts_user, diamonds)
    doc = StockDocument.objects.get(kind=StockDocument.Kind.DIA_PURCHASE)
    Group.objects.get(name="ACCOUNTS").permissions.remove(Permission.objects.get(codename="view_cost"))
    client.force_login(User.objects.get(pk=accounts_user.pk))
    assert client.post(reverse("inventory:dia_purchase_reverse", args=[doc.pk])).status_code == 403
    doc.refresh_from_db()
    assert doc.status == StockDocument.Status.CLOSED
