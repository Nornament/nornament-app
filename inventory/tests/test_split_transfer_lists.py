"""The stones rail's Splits & merges and Transfers lists."""
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import ledger, ledger_assort, services
from inventory.ledger_assort import SplitPart, split_pouch, transfer_pouch
from inventory.models import Batch

pytestmark = pytest.mark.django_db
D = Decimal

ONYX = {"stone_name": "Green Onyx", "colour": "Green", "shape": "Oval", "quality": "B"}


def _body(client, user, name):
    client.force_login(user)
    return client.get(reverse(name)).content.decode()


def _row(body, number):
    return body.split(f"<b>{number}</b>")[1].split("</tr>")[0]


def test_splits_list_every_split_newest_first(client, accounts_user, sales_user, shelf):
    assert "No splits or merges yet." in _body(client, sales_user, "inventory:splits")
    first = split_pouch(accounts_user, shelf["onyx"], 4, D("2.5"),
                        [SplitPart("3", 2, D("1")), SplitPart("4", 2, D("1"))], loss_ct=D("0.5"))
    second = split_pouch(accounts_user, shelf["ruby"], None, D("10"), [SplitPart("5", None, D("10"))])
    body = _body(client, sales_user, "inventory:splits")
    assert body.index(second.number) < body.index(first.number)
    row = _row(body, first.number)
    assert "SL01G · 1" in row and shelf["onyx"].ref in row and "SL01G · 3, SL01G · 4" in row
    assert "2.50" in row and "Accounts" in row and "Reversed" not in row
    assert f'href="{reverse("inventory:document", args=[first.pk])}"' in body
    assert f'class="on" href="{reverse("inventory:splits")}"' in body


def test_a_reversed_split_reads_reversed_and_its_reversal_is_not_listed(client, accounts_user, shelf):
    doc = split_pouch(accounts_user, shelf["onyx"], 2, D("1"), [SplitPart("3", 2, D("1"))])
    reversal = ledger.reverse_document(accounts_user, doc)
    body = _body(client, accounts_user, "inventory:splits")
    assert "Reversed" in _row(body, doc.number) and reversal.number not in body


def test_transfers_list_where_each_pouch_was_filed_and_where_it_went(client, accounts_user, karigar_user, shelf):
    assert "No transfers yet." in _body(client, karigar_user, "inventory:transfers")
    to = Batch.objects.create(code="SL02G", box_colour_id="G", family="S", cls="L", seq="02")
    doc = transfer_pouch(accounts_user, shelf["ruby"], to, "5")
    body = _body(client, karigar_user, "inventory:transfers")
    row = _row(body, doc.number)
    assert shelf["ruby"].ref in row and "SL01G · 2" in row and "SL02G · 5" in row and "Accounts" in row
    assert f'href="{reverse("inventory:document", args=[doc.pk])}"' in body
    reversal = ledger.reverse_document(accounts_user, doc)
    body = _body(client, karigar_user, "inventory:transfers")
    assert "Reversed" in _row(body, doc.number) and reversal.number not in body


def test_neither_list_is_reachable_in_client_view(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    for name in ("inventory:splits", "inventory:transfers"):
        response = client.get(reverse(name))
        assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf"), name


def test_merges_are_listed_beside_splits(client, accounts_user, admin_user_, sales_user, shelf):
    twin = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "5", **ONYX}, pcs=10, ct=D("7.5"), rate=None)
    split = split_pouch(accounts_user, shelf["ruby"], None, D("10"), [SplitPart("6", None, D("10"))])
    merge, _ = ledger_assort.merge_pouches(accounts_user, [shelf["onyx"], twin], into=shelf["onyx"], loss_ct=D("0.5"))
    body = _body(client, sales_user, "inventory:splits")
    assert body.index(merge.number) < body.index(split.number)
    row = _row(body, merge.number)
    assert "Merge" in row and "SL01G · 5" in row and twin.ref in row and "SL01G · 1" in row
    assert "7.50" in row                                              # what went in, not the loss
    assert "Split" in _row(body, split.number)
    assert "<th>Kind</th>" in body and "<th>Out of</th>" in body and "<th>Into</th>" in body


def test_a_reversed_merge_reads_reversed_and_its_reversal_is_not_listed(client, accounts_user, admin_user_, shelf):
    twin = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "5", **ONYX}, pcs=10, ct=D("7.5"), rate=None)
    merge, _ = ledger_assort.merge_pouches(accounts_user, [shelf["onyx"], twin], into=shelf["onyx"])
    reversal = ledger.reverse_document(accounts_user, merge)
    body = _body(client, accounts_user, "inventory:splits")
    assert "Reversed" in _row(body, merge.number) and reversal.number not in body


def test_the_recent_list_offers_merge(client, accounts_user, shelf):
    body = _body(client, accounts_user, "inventory:recent")
    assert '<option value="merge"' in body
