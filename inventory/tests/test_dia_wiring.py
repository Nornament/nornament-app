from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import dia_rows, ledger
from inventory.ledger_dia_assort import Destination, post_assortment
from inventory.ledger_dia_jobs import open_card
from inventory.ledger_dia_purchase import DiaPurchaseLine, post_dia_purchase
from inventory.ledger_purchase import PurchaseHeader

pytestmark = pytest.mark.django_db
D = Decimal


def _search(client, user, query=""):
    client.force_login(user)
    return client.get(reverse("inventory:diamonds") + query).content.decode()


def test_the_rail_sub_tabs_and_search_open_the_ledgers_by_right(client, accounts_user, karigar_user, sales_user,
                                                                diamonds):
    urls = {name: reverse(f"inventory:{name}") for name in ("dia_jobs", "dia_assorts", "dia_purchase")}
    body = _search(client, accounts_user)
    assert all(f'href="{url}"' in body for url in urls.values())
    assert "⚒ Job card</a>" in body and "⇅ Assort</a>" in body and "＋ Purchase</a>" in body
    assert "Coming soon\">Job cards" not in body and "Job cards 🔒" not in body
    body = _search(client, karigar_user)
    assert f'href="{urls["dia_jobs"]}"' in body and "⚒ Job card</a>" in body
    assert f'href="{urls["dia_assorts"]}"' not in body and f'href="{urls["dia_purchase"]}"' not in body
    assert 'Assortments<span class="ct">🔒' in body and 'Purchases<span class="ct">🔒' in body     # the rail
    assert "Assortments 🔒" in body and "Purchases 🔒" in body                                     # the sub-tabs
    body = _search(client, sales_user)
    assert f'href="{urls["dia_jobs"]}"' in body                     # every internal role reads job cards
    assert "⚒ Job card" not in body and "⇅ Assort" not in body and "＋ Purchase" not in body


def test_a_preview_carries_into_the_ledgers(client, admin_user_, diamonds):
    body = _search(client, admin_user_, "?as=PRODUCTION")
    assert f'href="{reverse("inventory:dia_jobs")}?as=PRODUCTION">⚒ Job card</a>' in body
    assert f'href="{reverse("inventory:dia_jobs")}?as=PRODUCTION">Job cards</a>' in body
    assert "⇅ Assort</a>" not in body                               # Production holds no Assort right


def test_rail_counts_are_real(client, accounts_user, diamonds, parties):
    open_card(accounts_user, None)
    shut = open_card(accounts_user, parties["karigar"])
    ledger.close_document(accounts_user, shut)
    post_assortment(accounts_user, diamonds["round"], D("1"), [Destination("Round", "G", "VS1", "", D("1"))])
    undone = post_assortment(accounts_user, diamonds["princess"], D("0.5"),
                             [Destination("Princess", "G", "VS1", "", D("0.5"))])
    ledger.reverse_document(accounts_user, undone)
    counts = dia_rows.rail_counts()
    assert (counts["jobs"], counts["assorts"]) == (1, 1)
    body = _search(client, accounts_user)
    assert 'Job cards<span class="ct">1</span>' in body and 'Assortments<span class="ct">1</span>' in body


def test_settings_counts_each_suppliers_purchases(client, accounts_user, diamonds):
    line = DiaPurchaseLine("Natural Diamond", "Round", "F-G-H", "VS-SI", "+6-12", None, D("1"), D("16000"))
    supplier = diamonds["supplier"]
    post_dia_purchase(accounts_user, PurchaseHeader(supplier=supplier, occurred_on=date(2026, 8, 7), invoice_no="K-1"),
                      [line])
    gone = post_dia_purchase(accounts_user, PurchaseHeader(supplier=supplier, occurred_on=date(2026, 8, 7),
                                                           invoice_no="K-2"), [line])
    ledger.reverse_document(accounts_user, gone)
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:dia_settings")).content.decode()
    row = body.split("Kothari Exports</b>")[1].split("</tr>")[0]
    assert '<td class="r">1</td>' in row


def test_the_diamond_stock_take_tab_stays_locked(client, accounts_user, diamonds):
    body = _search(client, accounts_user)
    assert "Movements 🔒" not in body and "Stock take 🔒" in body


def test_the_stones_pouch_ledger_filters_by_stones_reasons_only(client, admin_user_, shelf):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:movements", args=[shelf["onyx"].ref])).content.decode()
    assert 'value="Sale"' in body
    for reason in ("Returned Unused", "Assort Out", "Assort In"):
        assert f'value="{reason}"' not in body, reason
