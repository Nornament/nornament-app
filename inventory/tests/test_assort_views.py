from decimal import Decimal

import pytest
from django.urls import reverse

from inventory.models import Batch, Pouch, StockDocument

pytestmark = pytest.mark.django_db
D = Decimal


def _other():
    return Batch.objects.create(code="SP14B", box_colour_id="B", family="S", cls="P", seq="14")


def _split(client, user, pouch, **changes):
    data = {"out_pcs": "10", "out_ct": "6", "pouch_no": ["3", "4"], "pcs": ["6", "3"], "ct": ["3.5", "2"],
            "size_text": ["10*8", "14*10"], "remarks": ["", ""], "loss_pcs": "1", "loss_ct": "0.5", "note": ""}
    client.force_login(user)
    return client.post(reverse("inventory:split", args=[pouch.ref]), data | changes)


def test_the_split_screen_starts_from_the_whole_balance(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:split", args=[shelf["onyx"].ref])).content.decode()
    for text in ("Split pouch", "Source pouch", "＋ Add pouch", "Wastage / Loss in Process", "Post split",
                 "ct unaccounted — cannot post", "balances"):
        assert text in body, text
    assert 'name="out_ct" value="12.50"' in body and 'name="pouch_no" value="3"' in body


def test_a_balanced_split_posts_and_lands_on_its_document(client, accounts_user, shelf):
    response = _split(client, accounts_user, shelf["onyx"])
    doc = StockDocument.objects.get(kind=StockDocument.Kind.SPLIT)
    assert response["Location"] == reverse("inventory:document", args=[doc.pk])
    assert Pouch.objects.get(batch=shelf["batch"], pouch_no="3").parent == shelf["onyx"]


def test_an_unbalanced_split_comes_back_with_its_rows(client, accounts_user, shelf):
    response = _split(client, accounts_user, shelf["onyx"], loss_ct="")
    body = response.content.decode()
    assert response.status_code == 200 and "0.5 ct unaccounted" in body and 'value="3.5"' in body
    assert not StockDocument.objects.exists()


def test_an_uncountable_pouch_splits_by_weight_from_the_screen(client, accounts_user, shelf):
    response = _split(client, accounts_user, shelf["ruby"], out_pcs="", out_ct="40", pcs=["", ""], ct=["25", "15"],
                      loss_pcs="", loss_ct="")
    assert response.status_code == 302


def test_the_assort_screens_need_the_right(client, production_user, shelf):
    client.force_login(production_user)
    for name in ("inventory:split", "inventory:transfer"):
        assert client.get(reverse(name, args=[shelf["onyx"].ref])).status_code == 403, name


def test_transfer_suggests_a_number_and_re_files(client, accounts_user, shelf):
    other, onyx = _other(), shelf["onyx"]
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:transfer", args=[onyx.ref])).content.decode()
    assert "Transfer to another batch" in body and '"SP14B": 1' in body and '"SL01G":' not in body
    response = client.post(reverse("inventory:transfer", args=[onyx.ref]), {"batch": "sp14b", "pouch_no": "1"}, follow=True)
    onyx.refresh_from_db()
    assert onyx.batch == other and "Re-filed as SP14B · 1 on TRF-000001" in response.content.decode()


def test_a_taken_number_comes_back_on_the_form(client, accounts_user, shelf):
    other = _other()
    Pouch.objects.create(ref="NRN-000050", batch=other, pouch_no="1")
    client.force_login(accounts_user)
    response = client.post(reverse("inventory:transfer", args=[shelf["onyx"].ref]), {"batch": "SP14B", "pouch_no": "1"})
    assert response.status_code == 200 and "is taken" in response.content.decode()


def test_the_pouch_page_opens_the_split(client, accounts_user, sales_user, shelf):
    url = reverse("inventory:split", args=[shelf["onyx"].ref])
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()
    assert url in body and "⤴ Split pouch" in body
    client.force_login(sales_user)
    assert url not in client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()


def test_client_view_reaches_neither_screen(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    for name in ("inventory:split", "inventory:transfer"):
        assert client.get(reverse(name, args=[shelf["onyx"].ref])).status_code == 302
