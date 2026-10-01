from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import dia_services, ledger
from inventory.ledger_dia_jobs import open_card, post_entry
from inventory.models import StockDocument
from inventory.tests.conftest import KARIGAR

pytestmark = pytest.mark.django_db
D = Decimal
S = StockDocument.Status


def _card(user, diamonds, parties, karigar=True):
    card = open_card(user, parties["karigar"] if karigar else None)
    post_entry(user, card, "issue", diamonds["round"], D("1"), ref="CH 2026/0417")
    return card


def _get(client, user, query=""):
    client.force_login(user)
    return client.get(reverse("inventory:dia_jobs") + query).content.decode()


def test_the_job_card_page_reads_as_the_prototype(client, accounts_user, diamonds, parties):
    card = _card(accounts_user, diamonds, parties)
    body = _get(client, accounts_user)
    for text in ("Job cards", "Karigar", "Opened", "Status", f"Ledger — {card.number}", "Stock control", "Line",
                 "Debit (ct)", "Credit (ct)", "Balance", "Totals", "Issue to job card", "CH 2026/0417",
                 "1 ct outstanding", KARIGAR, "Post an entry", "Issue to job card — debit",
                 "Returned unused — credit", "Breakage — credit", "Challan / ref", "＋ New job card",
                 "↺ Undo last entry", "Reverse", "NRD-000001 · DRFGH VS-SI · +6-12 · B-771"):
        assert text in body, text
    assert "A job card is a" not in body and "Debit = out to the karigar" not in body       # prose stripped
    assert "balanced — can close" not in body
    assert reverse("inventory:dia_job_close", args=[card.pk]) not in body                     # Close only at zero


def test_open_cards_by_default_and_closed_on_request(client, accounts_user, diamonds, parties):
    shut = open_card(accounts_user, None)
    ledger.close_document(accounts_user, shut)
    live = _card(accounts_user, diamonds, parties)
    body = _get(client, accounts_user)
    assert live.number in body and shut.number not in body and "Show closed" in body
    body = _get(client, accounts_user, "?closed=1")
    assert shut.number in body and "(closed)" in body and "Open only" in body
    body = _get(client, accounts_user, f"?card={shut.pk}")
    assert f"Ledger — {shut.number}" in body and "In-house" in body and "Post an entry" not in body


def test_a_balanced_card_offers_close(client, accounts_user, diamonds, parties):
    card = _card(accounts_user, diamonds, parties)
    post_entry(accounts_user, card, "set", diamonds["round"], D("1"))
    body = _get(client, accounts_user)
    assert "balanced — can close" in body and reverse("inventory:dia_job_close", args=[card.pk]) in body


def test_posting_from_the_page(client, accounts_user, diamonds, parties):
    client.force_login(accounts_user)
    response = client.post(reverse("inventory:dia_job_new"),
                           {"karigar": parties["karigar"].pk, "opened_on": "2026-05-04", "note": ""})
    card = StockDocument.objects.get(kind=StockDocument.Kind.DIA_JOB)
    assert response["Location"] == reverse("inventory:dia_jobs") + f"?card={card.pk}"
    url = reverse("inventory:dia_job_post", args=[card.pk])
    client.post(url, {"entry": "issue", "line": diamonds["round"].pk, "ct": "2", "occurred_on": "2026-05-04",
                      "ref": "CH 2026/0417"})
    client.post(url, {"entry": "loose", "line": diamonds["round"].pk, "ct": "0.5", "occurred_on": "", "ref": ""})
    assert ledger.outstanding(card) == {diamonds["round"].pk: (0, D("1.5"))}
    response = client.post(url, {"entry": "set", "line": diamonds["round"].pk, "ct": "9"}, follow=True)
    assert "cannot exceed what is outstanding" in response.content.decode()
    response = client.post(reverse("inventory:dia_job_close", args=[card.pk]), follow=True)
    assert "can close only at zero: 1.5 ct outstanding" in response.content.decode()


def test_an_unknown_karigar_is_refused_not_taken_as_in_house(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    response = client.post(reverse("inventory:dia_job_new"), {"karigar": "999999", "opened_on": ""}, follow=True)
    assert "Choose the karigar" in response.content.decode() and not StockDocument.objects.exists()


def test_close_undo_and_reverse_from_the_page(client, accounts_user, diamonds, parties):
    card = _card(accounts_user, diamonds, parties)
    client.force_login(accounts_user)
    client.post(reverse("inventory:dia_job_post", args=[card.pk]),
                {"entry": "unused", "line": diamonds["round"].pk, "ct": "1"})
    response = client.post(reverse("inventory:dia_job_close", args=[card.pk]), follow=True)
    card.refresh_from_db()
    assert card.status == S.CLOSED and f"{card.number} closed." in response.content.decode()
    response = client.post(reverse("inventory:dia_job_undo", args=[card.pk]), follow=True)
    card.refresh_from_db()
    assert card.status == S.OPEN and "Undone: Returned unused." in response.content.decode()
    response = client.post(reverse("inventory:dia_job_reverse", args=[card.pk]), follow=True)
    card.refresh_from_db()
    assert card.status == S.REVERSED and "Reversed by REV-000001" in response.content.decode()
    assert dia_services.stocked_lines().get(pk=diamonds["round"].pk).on_ct == D("3.40")


def test_every_internal_role_reads_a_card_and_only_job_cards_may_write(
        client, sales_user, graphic_user, karigar_user, accounts_user, diamonds, parties):
    card = _card(accounts_user, diamonds, parties)
    for user, label in ((sales_user, "Sales / Showroom"), (graphic_user, "Graphic / Media")):
        body = _get(client, user)
        assert card.number in body and f"read only for {label}" in body
        assert KARIGAR not in body and "Post an entry" not in body and "＋ New job card" not in body
    body = _get(client, karigar_user)
    assert KARIGAR in body and "Post an entry" in body and "read only" not in body


def test_an_admin_preview_reads_as_the_role_with_every_form_hidden(client, admin_user_, diamonds, parties):
    _card(admin_user_, diamonds, parties)
    body = _get(client, admin_user_, "?as=SALES")
    assert "read only for Sales / Showroom" in body and KARIGAR not in body and "Post an entry" not in body
    body = _get(client, admin_user_, "?as=PRODUCTION")
    assert KARIGAR in body and "read only" not in body
    for form in ("Post an entry", "＋ New job card", "↺ Undo last entry"):
        assert form not in body, form


def test_the_writes_need_job_cards(client, sales_user, accounts_user, diamonds, parties):
    card = _card(accounts_user, diamonds, parties)
    client.force_login(sales_user)
    for name, args, data in [
        ("inventory:dia_job_new", [], {}),
        ("inventory:dia_job_post", [card.pk], {"entry": "loose", "line": diamonds["round"].pk, "ct": "1"}),
        ("inventory:dia_job_close", [card.pk], {}),
        ("inventory:dia_job_undo", [card.pk], {}),
        ("inventory:dia_job_reverse", [card.pk], {}),
    ]:
        assert client.post(reverse(name, args=args), data).status_code == 403, name
    assert card.movements.count() == 1 and StockDocument.objects.count() == 1
