"""The diamond Movements tab: recent diamond documents, and a ledger per line."""
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import dia_services, ledger, ledger_dia_jobs
from inventory.models import DiamondLine
from inventory.tests.conftest import DIA_COST, DIA_SUPPLIER, KARIGAR
from inventory.views_dia_movements import _ledger

pytestmark = pytest.mark.django_db
D = Decimal


def _get(client, user, url, query=None):
    client.force_login(user)
    return client.get(url, query or {})


def test_the_list_opens_each_document_on_its_own_screen_newest_first(client, accounts_user, dia_docs):
    card, assort, purchase = dia_docs["card"], dia_docs["assort"], dia_docs["purchase"]
    body = _get(client, accounts_user, reverse("inventory:dia_movements")).content.decode()
    assert body.index(purchase.number) < body.index(assort.number) < body.index(card.number)
    assert f'href="{reverse("inventory:dia_jobs")}?card={card.pk}"><b>{card.number}</b>' in body
    assert f'href="{reverse("inventory:dia_assorts")}?doc={assort.pk}"><b>{assort.number}</b>' in body
    assert f'href="{reverse("inventory:dia_purchase")}"><b>{purchase.number}</b>' in body
    assert KARIGAR in body and DIA_SUPPLIER in body
    assert f'class="on" href="{reverse("inventory:dia_movements")}">Movements</a>' in body


def test_the_kind_filter_and_stones_documents_never_listed(client, accounts_user, dia_docs, ledger_docs):
    url = reverse("inventory:dia_movements")
    body = _get(client, accounts_user, url, {"kind": "dia_assort"}).content.decode()
    assert dia_docs["assort"].number in body
    assert dia_docs["card"].number not in body and dia_docs["purchase"].number not in body
    every = _get(client, accounts_user, url).content.decode()
    assert ledger_docs["job"].number not in every and ledger_docs["purchase"].number not in every


def test_a_name_the_viewer_may_not_see_is_absent_never_in_house(client, sales_user, karigar_user, dia_docs):
    body = _get(client, sales_user, reverse("inventory:dia_movements")).content.decode()
    assert KARIGAR not in body and DIA_SUPPLIER not in body and "In-house" not in body
    assert dia_docs["card"].number in body
    assert _get(client, karigar_user, reverse("inventory:dia_movements")).status_code == 200


def test_the_line_ledger_runs_to_what_the_engine_holds(client, accounts_user, dia_docs):
    line, card = dia_docs["round"], dia_docs["card"]
    ledger_dia_jobs.post_entry(accounts_user, card, "set", line, D("0.25"))           # a settle: on hand unchanged
    ledger.undo_last(accounts_user, card)                                            # its reversal: unchanged too
    dia_services.recount_line(accounts_user, line, D("2"), note="re-imported from Sheet!9")    # 2.40 → 2.00
    reversal = ledger.reverse_document(accounts_user, card)                          # the issue undone: + 1
    moves = _ledger(accounts_user, line)
    held = dia_services.stocked_lines(DiamondLine.objects.filter(pk=line.pk)).get().on_ct
    assert [m["balance"] for m in moves] == [D("3.40"), D("2.40"), D("2.40"), D("2.40"), D("2.00"), D("3.00")]
    assert moves[-1]["balance"] == held
    assert moves[-1]["direction"] == "In" and moves[-1]["sym"] == "＋"       # the reversed issue reads In, not Out
    body = _get(client, accounts_user, reverse("inventory:dia_line", args=[line.ref])).content.decode()
    assert "＋ Out" not in body
    assert "Sheet!3" in body and "re-imported from Sheet!9" in body          # the import's source rows
    assert f'href="{reverse("inventory:dia_jobs")}?card={card.pk}">{card.number}</a>' in body
    assert f'href="{reverse("inventory:dia_jobs")}?card={card.pk}">{reversal.number}</a>' in body
    assert "3.00 ct" in body and "DRFGH VS-SI" in body and "B-771" in body


def test_value_reads_own_cost_first_and_needs_the_cost_right(client, accounts_user, sales_user, dia_docs):
    bought = dia_docs["purchase"].movements.get().diamond
    url = reverse("inventory:dia_line", args=[bought.ref])
    body = _get(client, accounts_user, url).content.decode()
    assert "₹23,456" in body and "₹46,912" in body and DIA_COST not in body      # own cost, not the rate card
    rnd = _get(client, accounts_user, reverse("inventory:dia_line", args=[dia_docs["round"].ref])).content.decode()
    assert f"₹{DIA_COST}" in rnd                                                  # no own cost: the rate card's
    body = _get(client, sales_user, url).content.decode()
    assert "23,456" not in body and "46,912" not in body and "<label>Value</label>" not in body


def test_the_lines_column_counts_lines_not_movements(client, accounts_user, dia_docs):
    card, line = dia_docs["card"], dia_docs["round"]
    ledger_dia_jobs.post_entry(accounts_user, card, "loose", line, D("0.5"))          # a second movement, same line
    body = _get(client, accounts_user, reverse("inventory:dia_movements")).content.decode()
    row = body[body.index(card.number):]
    assert '<td class="r">1</td>' in row[:row.index("</tr>")]


def test_an_unknown_line_is_404(client, accounts_user, diamonds):
    assert _get(client, accounts_user, reverse("inventory:dia_line", args=["NRD-999999"])).status_code == 404


def test_search_stock_links_each_line_to_its_ledger(client, admin_user_, diamonds):
    rnd = diamonds["round"]
    body = _get(client, admin_user_, reverse("inventory:diamonds")).content.decode()
    assert f'href="{reverse("inventory:dia_line", args=[rnd.ref])}">{rnd.ref}</a>' in body
    body = _get(client, admin_user_, reverse("inventory:diamonds"), {"as": "SALES"}).content.decode()
    assert f'href="{reverse("inventory:dia_line", args=[rnd.ref])}?as=SALES">{rnd.ref}</a>' in body
