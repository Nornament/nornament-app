"""Part 5d: the stock-take screens."""
import html
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


def _shown_field(body):
    """The hidden ``shown`` field's value, unescaped back to the JSON text the server rendered."""
    return html.unescape(body.split('name="shown" value="')[1].split('"')[0])


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
    second = client.post(_sheet(take), {"action": "close", "confirm": "close", f"pcs_{onyx.pk}": "20", f"ct_{onyx.pk}": "12"})
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
    client.post(_sheet(take), {"action": "reverse", "confirm": "reverse"})
    take.refresh_from_db()
    assert take.document.status == StockDocument.Status.REVERSED
    assert "Reversed" in client.get(_sheet(take)).content.decode()
    other = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    client.post(_sheet(other), {"action": "cancel", "confirm": "cancel"})
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
    client.post(sheet, {"action": "close", "confirm": "close", f"ct_{round_.pk}": "3"})
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


# C2: two people on one sheet — a stale page's blank box must not delete another person's count,
# and an emptied box must still remove one.


def test_a_stale_page_does_not_wipe_another_counters_save(client, accounts_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    onyx, ruby = shelf["onyx"], shelf["ruby"]
    client.force_login(accounts_user)
    sheet = _sheet(take)
    # A and B both load the sheet before either has counted anything: every box blank
    shown = _shown_field(client.get(sheet).content.decode())
    # A counts and saves the onyx
    client.post(sheet, {"action": "save", f"pcs_{onyx.pk}": "20", f"ct_{onyx.pk}": "12", "shown": shown})
    assert take.counts.count() == 1
    # B posts the stale page: onyx boxes still read blank (as B's page showed), ruby now counted
    client.post(sheet, {"action": "save", f"pcs_{onyx.pk}": "", f"ct_{onyx.pk}": "",
                        f"ct_{ruby.pk}": "39", "shown": shown})
    assert {c.pouch_id for c in take.counts.all()} == {onyx.pk, ruby.pk}        # A's onyx count survives


def test_an_emptied_box_still_removes_a_count_even_with_the_shown_field(client, accounts_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    onyx = shelf["onyx"]
    client.force_login(accounts_user)
    sheet = _sheet(take)
    client.post(sheet, {"action": "save", f"pcs_{onyx.pk}": "20", f"ct_{onyx.pk}": "12",
                        "shown": _shown_field(client.get(sheet).content.decode())})
    assert take.counts.count() == 1
    shown = _shown_field(client.get(sheet).content.decode())                    # now shows 20 / 12
    client.post(sheet, {"action": "save", f"pcs_{onyx.pk}": "", f"ct_{onyx.pk}": "", "shown": shown})
    assert not take.counts.exists()


# I1: the confirm flow — a different button after a confirm banner must ask again for its own action.


def test_pressing_a_different_button_after_a_confirm_banner_asks_again(client, accounts_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    client.force_login(accounts_user)
    sheet = _sheet(take)
    body = client.post(sheet, {"action": "close"}).content.decode()
    assert 'name="confirm" value="close"' in body
    # the stale confirm value rides along, but the button pressed names a different action
    body = client.post(sheet, {"action": "cancel", "confirm": "close"}).content.decode()
    take.refresh_from_db()
    assert take.status == StockTake.OPEN                                        # not cancelled
    assert 'name="confirm" value="cancel"' in body                              # asks to confirm Cancel instead
    # and the reverse: a stale "confirm cancel" does not let Close through either
    body = client.post(sheet, {"action": "close", "confirm": "cancel"}).content.decode()
    take.refresh_from_db()
    assert take.status == StockTake.OPEN                                        # not closed
    assert 'name="confirm" value="close"' in body
    # the matching confirm does go through
    client.post(sheet, {"action": "close", "confirm": "close"})
    take.refresh_from_db()
    assert take.status == StockTake.CLOSED


# Minors: a crafted non-numeric category, and the diamond sheet's own right check.


def test_a_non_numeric_category_post_is_a_message_not_a_500(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    response = client.post(DIA_LIST, {"category": "not-a-number"}, follow=True)
    assert response.status_code == 200
    assert "Choose the category to count." in response.content.decode()
    assert not StockTake.objects.exists()


def test_a_diamond_sheet_post_without_inv_move_is_403(client, sales_user, accounts_user, diamonds):
    take = stock_take.start(accounts_user, StockTake.DIAMONDS, category=_natural())
    client.force_login(sales_user)
    assert client.post(reverse("inventory:dia_stock_take", args=[take.pk]), {"action": "save"}).status_code == 403


# I4: a bad value in one row must not throw away everything typed, and must name the row.


def test_a_bad_value_in_one_row_keeps_the_other_rows_typed_value_and_saves_nothing(client, accounts_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    onyx, ruby = shelf["onyx"], shelf["ruby"]
    client.force_login(accounts_user)
    sheet = _sheet(take)
    shown = _shown_field(client.get(sheet).content.decode())
    body = client.post(sheet, {"action": "save", f"pcs_{onyx.pk}": "20", f"ct_{onyx.pk}": "1..2",
                               f"ct_{ruby.pk}": "39", "shown": shown}).content.decode()
    assert "SL01G · 1 — Carats: 1..2 is not a number." in body
    assert 'value="20"' in body and 'value="1..2"' in body        # the bad row's own typing survives
    assert 'value="39"' in body                                   # so does the other row's good typing
    assert not take.counts.exists()                                # nothing was saved
