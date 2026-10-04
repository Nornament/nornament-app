"""Part 5d: the stock-take screens."""
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import stock_take
from inventory.models import StockDocument, StockTake

pytestmark = pytest.mark.django_db
D = Decimal
LIST = reverse("inventory:stock_takes")


def _sheet(take):
    return reverse("inventory:stock_take", args=[take.pk])


def test_the_rail_and_the_tab_open_the_list(client, sales_user, shelf):
    client.force_login(sales_user)
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert f'href="{LIST}"' in body and 'Stock takes<span class="ct">🔒' not in body and "Stock take 🔒" not in body
    assert 'Client lookbook<span class="ct">🔒' in body


def test_starting_from_the_list_opens_the_sheet(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(LIST).content.decode()
    assert "Start a stock take" in body and 'name="box_colour"' in body and 'name="batch"' in body
    response = client.post(LIST, {"batch": shelf["batch"].code})
    take = StockTake.objects.get()
    assert response.status_code == 302 and response["Location"] == _sheet(take)
    body = client.get(LIST).content.decode()
    assert take.number in body and "Batch SL01G" in body and "Open" in body


def test_an_overlap_comes_back_on_the_list(client, accounts_user, shelf):
    client.force_login(accounts_user)
    client.post(LIST, {"box_colour": "G"})
    body = client.post(LIST, {"batch": shelf["batch"].code}).content.decode()
    assert "ST-000001 is already counting Box colour G" in body and StockTake.objects.count() == 1


def test_the_sheet_saves_counts_and_shows_the_variance_and_its_value(client, accounts_user, sales_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    client.force_login(accounts_user)
    onyx = shelf["onyx"]
    response = client.post(_sheet(take), {"action": "save", f"pcs_{onyx.pk}": "20", f"ct_{onyx.pk}": "10.5",
                                          f"pcs_{shelf['ruby'].pk}": "", f"ct_{shelf['ruby'].pk}": ""})
    assert response.status_code == 302
    body = client.get(_sheet(take)).content.decode()
    assert 'value="10.5' in body
    assert "−2.00" in body or "-2.00" in body                     # whichever sign the ct filter prints
    assert "15,838" in body                                       # 2 ct × ₹7,919, to the cost right
    assert "Counted 1 of 2" in body
    client.force_login(sales_user)
    body = client.get(_sheet(take)).content.decode()
    assert "15,838" not in body and "Save counts" not in body     # read-only, no money


def test_close_needs_a_second_press_then_posts(client, accounts_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    client.force_login(accounts_user)
    onyx = shelf["onyx"]
    first = client.post(_sheet(take), {"action": "close", f"pcs_{onyx.pk}": "20", f"ct_{onyx.pk}": "12"})
    assert first.status_code == 200 and "Yes, close and post" in first.content.decode()
    take.refresh_from_db()
    assert take.status == StockTake.OPEN and take.counts.count() == 1        # the counts were saved
    second = client.post(_sheet(take), {"action": "close", "confirm": "1", f"pcs_{onyx.pk}": "20", f"ct_{onyx.pk}": "12"})
    take.refresh_from_db()
    assert second.status_code == 302 and take.status == StockTake.CLOSED
    body = client.get(_sheet(take)).content.decode()
    assert "Closed" in body and take.document.number in body
    assert f'href="{reverse("inventory:document", args=[take.document.pk])}"' in body and "Save counts" not in body


def test_cancel_and_reverse_from_the_sheet(client, accounts_user, shelf):
    client.force_login(accounts_user)
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(accounts_user, take, {shelf["onyx"].pk: (20, D("12"))})
    stock_take.close(accounts_user, take)
    client.post(_sheet(take), {"action": "reverse", "confirm": "1"})
    take.refresh_from_db()
    assert take.document.status == StockDocument.Status.REVERSED
    assert "Reversed" in client.get(_sheet(take)).content.decode()
    other = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    client.post(_sheet(other), {"action": "cancel", "confirm": "1"})
    other.refresh_from_db()
    assert other.status == StockTake.CANCELLED


def test_rights_and_client_view(client, sales_user, admin_user_, accounts_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    client.force_login(sales_user)
    assert client.get(LIST).status_code == 200 and "Start a stock take" not in client.get(LIST).content.decode()
    assert client.post(LIST, {"box_colour": "B"}).status_code == 403
    assert client.post(_sheet(take), {"action": "save"}).status_code == 403
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    for response in (client.get(LIST), client.get(_sheet(take)), client.post(_sheet(take), {"action": "save"})):
        assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf")


def test_a_diamond_stock_take_is_not_a_stones_page(client, accounts_user, diamonds):
    from inventory.models import DiamondTerm

    take = stock_take.start(accounts_user, StockTake.DIAMONDS,
                            category=DiamondTerm.objects.get(kind="category", value="Natural Diamond"))
    client.force_login(accounts_user)
    assert client.get(_sheet(take)).status_code == 404


def test_the_sheet_colspans_line_up_with_the_header(client, accounts_user, shelf):
    """The footer's totals sit under Variance ct and Variance value, not spilling onto
    Variance pcs — the brief's colspan of 7 missed the Variance pcs column it added."""
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    client.force_login(accounts_user)
    body = client.get(_sheet(take)).content.decode()
    assert '<th class="r">Variance ct</th>' in body
    header = body.split("<thead>")[1].split("</thead>")[0]
    assert header.count("<th") == 10        # Pouch, Stone, Size, Book/Counted pcs, Book/Counted ct, Variance pcs/ct, value
    assert 'colspan="8"' in body.split("<tfoot>")[1]


DIA_LIST = reverse("inventory:dia_stock_takes")


def _natural():
    from inventory.models import DiamondTerm

    return DiamondTerm.objects.get(kind="category", value="Natural Diamond")


def test_the_diamond_tab_opens_the_diamond_list_and_a_preview_carries(client, admin_user_, diamonds):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert f'href="{DIA_LIST}">Stock take</a>' in body and "Stock take 🔒" not in body
    previewed = client.get(reverse("inventory:diamonds"), {"as": "SALES"}).content.decode()
    assert f'href="{DIA_LIST}?as=SALES">Stock take</a>' in previewed


def test_a_diamond_stock_take_counts_carats_and_closes(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    response = client.post(DIA_LIST, {"category": _natural().pk})
    take = StockTake.objects.get()
    sheet = reverse("inventory:dia_stock_take", args=[take.pk])
    assert response["Location"] == sheet
    round_ = diamonds["round"]
    body = client.get(sheet).content.decode()
    assert round_.ref in body and f'name="pcs_{round_.pk}"' not in body
    client.post(sheet, {"action": "close", "confirm": "1", f"ct_{round_.pk}": "3"})
    take.refresh_from_db()
    assert take.status == StockTake.CLOSED and take.document.kind == StockDocument.Kind.DIA_COUNT
    movements = client.get(reverse("inventory:dia_movements")).content.decode()
    assert f'href="{sheet}"' in movements                       # the diamond Movements tab opens it


def test_a_preview_masks_and_hides_every_form(client, admin_user_, accounts_user, diamonds):
    take = stock_take.start(accounts_user, StockTake.DIAMONDS, category=_natural())
    stock_take.save_counts(accounts_user, take, {diamonds["round"].pk: (None, D("3"))})   # −0.4 ct × ₹16,517
    client.force_login(admin_user_)
    sheet = reverse("inventory:dia_stock_take", args=[take.pk])
    assert "6,607" in client.get(sheet).content.decode()
    previewed = client.get(sheet, {"as": "SALES"}).content.decode()
    assert "6,607" not in previewed and "Save counts" not in previewed and 'name="ct_' not in previewed
    assert "Start a stock take" not in client.get(DIA_LIST, {"as": "SALES"}).content.decode()


def test_a_stones_stock_take_is_not_a_diamond_page(client, accounts_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    client.force_login(accounts_user)
    assert client.get(reverse("inventory:dia_stock_take", args=[take.pk])).status_code == 404
