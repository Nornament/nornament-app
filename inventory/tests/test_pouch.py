from decimal import Decimal

import pytest
from django.urls import reverse

from inventory.models import PriceEntry
from inventory.tests.conftest import SUPPLIER, VALUE

pytestmark = pytest.mark.django_db


def _url(name, pouch):
    return reverse(name, args=[pouch.ref])


def test_the_detail_shows_value_shares_and_the_record(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(_url("inventory:pouch", shelf["onyx"])).content.decode()
    assert "SL01G · 1" in body and VALUE in body and SUPPLIER in body
    assert "of batch SL01G" in body and "98%" in body            # 98,988 of 1,00,988
    assert "Batch code" in body and "Stone" in body               # family decoded


def test_a_misfiled_pouch_says_so(client, admin_user_, shelf):
    client.force_login(admin_user_)
    body = client.get(_url("inventory:pouch", shelf["ruby"])).content.decode()
    assert "Colour mismatch — check filing" in body and "Filed under Green but recorded as Red" in body


def test_save_writes_the_four_fields(client, accounts_user, shelf):
    client.force_login(accounts_user)
    response = client.post(_url("inventory:pouch_save", shelf["onyx"]),
                           {"treatment": "Heated", "origin": "Zambia", "purchase_date": "2026-08-07",
                            "supplier": shelf["supplier"].pk})
    assert response.status_code == 302
    shelf["onyx"].refresh_from_db()
    assert (shelf["onyx"].treatment, shelf["onyx"].origin, str(shelf["onyx"].purchase_date)) == ("Heated", "Zambia", "2026-08-07")


def test_sales_may_not_save_or_price(client, sales_user, shelf):
    client.force_login(sales_user)
    assert client.post(_url("inventory:pouch_save", shelf["onyx"]), {"treatment": "Heated"}).status_code == 403
    assert client.post(_url("inventory:pouch_price", shelf["onyx"]),
                       {"kind": "list", "rate": "1", "effective_from": "2026-09-28"}).status_code == 403


def test_add_price_appends_a_dated_row(client, accounts_user, shelf):
    client.force_login(accounts_user)
    client.post(_url("inventory:pouch_price", shelf["onyx"]),
                {"kind": PriceEntry.LIST, "rate": "12000", "effective_from": "2026-09-28"})
    assert shelf["onyx"].prices.filter(kind=PriceEntry.LIST).get().rate == Decimal("12000")
    body = client.get(_url("inventory:pouch", shelf["onyx"])).content.decode()
    assert "12,000" in body


def test_photos_are_filed_under_the_pouch(client, accounts_user, shelf, monkeypatch):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from mediahub import storage
    from mediahub.models import MediaAsset

    monkeypatch.setattr(storage, "put_bytes", lambda key, data, mime: None)
    client.force_login(accounts_user)
    photo = SimpleUploadedFile("IMG_0001.jpg", b"\xff\xd8\xff", content_type="image/jpeg")
    client.post(_url("inventory:pouch_photos", shelf["onyx"]), {"photos": [photo]})
    asset = MediaAsset.objects.get(scope="pouch", scope_id=str(shelf["onyx"].pk))
    assert asset.file_name == "SL01G-1-01.jpg"
