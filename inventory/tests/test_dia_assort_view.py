from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

from accounts.models import User
from inventory import ledger
from inventory.models import Movement, StockDocument

pytestmark = pytest.mark.django_db
D = Decimal


def _post(client, user, diamonds, **changes):
    """The prototype's AS card: 2.00 ct out of the round line, two destinations, 0.05 ct sorting loss.
    A change of ``None`` leaves that field out of the post."""
    data = {"source": diamonds["round"].pk, "take_out": "2.00", "occurred_on": "2026-08-02",
            "note": "re-sieved after client return", "shape": ["Round", "Round"], "colour": ["E-F", "I-J"],
            "clarity": ["VVS-VS", "SI-I"], "size_text": ["+6-12", "+2"], "ct": ["1.20", "0.75"],
            "cost": ["", ""], "loss": "0.05"}
    client.force_login(user)
    return client.post(reverse("inventory:dia_assorts"),
                       {key: value for key, value in (data | changes).items() if value is not None})


def test_the_assortment_screen_reads_as_the_prototype(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:dia_assorts")).content.decode()
    for text in ("Assortments", "＋ New assortment", "Source line", "Take out", "Reason", "＋ Add destination",
                 "Shape", "Colour", "Clarity", "Size", "Carats", "Cost / ct", "Sorting loss",
                 "ct unaccounted — cannot post", "balances", "Post assortment",
                 "NRD-000001 · DRFGH VS-SI · +6-12 · B-771 — 3.40 ct"):
        assert text in body, text
    assert "Same ledger idea" not in body and "Debits and credits must match" not in body      # prose stripped


def test_a_balanced_assortment_posts_and_shows_its_ledger(client, accounts_user, diamonds):
    response = _post(client, accounts_user, diamonds)
    doc = StockDocument.objects.get(kind=StockDocument.Kind.DIA_ASSORT)
    assert response["Location"] == reverse("inventory:dia_assorts") + f"?doc={doc.pk}"
    body = client.get(response["Location"]).content.decode()
    for text in (f"Assortment {doc.number} posted.", f"Ledger — {doc.number}", "Posted by", "Balance", "balances",
                 "re-sieved after client return", "Code", "Movement", "Note", "Debit (ct)", "Credit (ct)", "Running",
                 "Assort out", "Assort in", "Sorting loss", "written off", "Totals",
                 "DRFGH VS-SI · +6-11", "DREF VVS-VS · +6-11", "DRIJ SI-I · +2-6", "2.00", "1.20", "0.75", "0.05"):
        assert text in body, text


def test_an_unbalanced_assortment_comes_back_with_its_rows(client, accounts_user, diamonds):
    response = _post(client, accounts_user, diamonds, loss="")
    body = response.content.decode()
    assert response.status_code == 200 and "0.05 ct unaccounted — an assortment must balance" in body
    assert 'value="1.20"' in body and 'value="0.75"' in body and 'value="+6-12"' in body
    assert not StockDocument.objects.exists()


def test_the_cost_column_needs_sight_of_cost(client, accounts_user, diamonds):
    Group.objects.get(name="ACCOUNTS").permissions.remove(Permission.objects.get(codename="view_cost"))
    blind = User.objects.get(pk=accounts_user.pk)
    client.force_login(blind)
    body = client.get(reverse("inventory:dia_assorts")).content.decode()
    assert "＋ New assortment" in body and "Cost / ct" not in body
    assert _post(client, blind, diamonds, cost=None).status_code == 302          # a carried cost needs no sight of it
    response = _post(client, blind, diamonds, cost=["20000", ""])
    assert response.status_code == 403                                          # an override does


def test_others_are_not_permitted(client, production_user, sales_user, diamonds):
    for user, label in ((production_user, "Production"), (sales_user, "Sales / Showroom")):
        client.force_login(user)
        body = client.get(reverse("inventory:dia_assorts")).content.decode()
        assert f"Not permitted for {label}" in body and "＋ New assortment" not in body
    assert _post(client, production_user, diamonds).status_code == 403
    assert not StockDocument.objects.exists()


def test_an_admin_preview_reads_as_the_role(client, admin_user_, diamonds):
    _post(client, admin_user_, diamonds)
    body = client.get(reverse("inventory:dia_assorts"), {"as": "SALES"}).content.decode()
    assert "Not permitted for Sales / Showroom" in body and "Assort out" not in body
    body = client.get(reverse("inventory:dia_assorts"), {"as": "ACCOUNTS"}).content.decode()
    assert "Assort out" in body and "＋ New assortment" not in body and ">Reverse</button>" not in body


def test_reverse_from_the_screen_and_its_refusal(client, accounts_user, diamonds):
    _post(client, accounts_user, diamonds)
    doc = StockDocument.objects.get(kind=StockDocument.Kind.DIA_ASSORT)
    up = doc.movements.filter(reason=Movement.Reason.ASSORT_IN).order_by("pk").first().diamond
    card = ledger.open_document(accounts_user, StockDocument.Kind.DIA_JOB)
    ledger.post(accounts_user, card, [ledger.Line(up, Movement.Reason.JOB_WORK_OUT, Movement.OUT, None, D("0.5"))])
    response = client.post(reverse("inventory:dia_assort_reverse", args=[doc.pk]), follow=True)
    assert "has moved since" in response.content.decode()
    ledger.reverse_document(accounts_user, card)
    response = client.post(reverse("inventory:dia_assort_reverse", args=[doc.pk]), follow=True)
    body = response.content.decode()
    assert "Reversed by REV-000002" in body and "(reversed)" in body and ">Reverse</button>" not in body
