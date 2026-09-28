"""In client mode the server never sends the shelf layout, the money, or the flags.

The prototype hid these with CSS over the same data. Here they are never
rendered at all, and this walk is what keeps it that way.
"""
import pytest
from django.urls import reverse

from inventory.tests.conftest import SUPPLIER, VALUE

pytestmark = pytest.mark.django_db

LAYOUT = ["SL01G", "C-117", "keep away from light", "SL!2", VALUE, "7,919", SUPPLIER, "misfiled", "no pouch no."]


def _client_mode(client, user):
    client.force_login(user)
    client.post(reverse("inventory:set_view"), {"view": "client"})


def _screens(shelf):
    return [
        reverse("inventory:shelf"),
        reverse("inventory:colour", args=["G"]),
        reverse("inventory:batch", args=[shelf["batch"].pk]),
        reverse("inventory:batch", args=[shelf["batch"].pk]) + "?view=table",
        reverse("inventory:pouch", args=[shelf["onyx"].ref]),
        reverse("inventory:pouch", args=[shelf["ruby"].ref]),
    ]


def test_a_client_is_sent_no_layout_no_money_no_flags(client, admin_user_, shelf):
    _client_mode(client, admin_user_)
    for url in _screens(shelf):
        body = client.get(url).content.decode()
        for secret in LAYOUT:
            assert secret not in body, f"{url} sent {secret!r} in client view"


def test_a_client_sees_the_reference_and_can_enquire(client, admin_user_, shelf):
    _client_mode(client, admin_user_)
    body = client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()
    assert shelf["onyx"].ref in body and "enquire for price" in body and "✉ Enquire" in body
    assert "In stock" in body


def test_the_enquiry_arrives_carrying_the_reference(client, admin_user_, shelf):
    client.force_login(admin_user_)
    body = client.get(reverse("crm:pipeline_new", args=["enquiry"]), {"item": f"{shelf['onyx'].ref} Green Onyx"}).content.decode()
    assert f'value="{shelf["onyx"].ref} Green Onyx"' in body


def test_internal_again_brings_everything_back(client, admin_user_, shelf):
    _client_mode(client, admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "internal"})
    assert "SL01G" in client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()


def test_a_photo_reaches_a_client_named_by_its_reference(client, admin_user_, shelf, monkeypatch):
    from mediahub import storage
    from mediahub.models import MediaAsset
    from stock.enums import MediaKind

    asset = MediaAsset.objects.create(
        media_ref="M-PHOTO-1", kind=MediaKind.PHOTO, storage_key="crm/pouch/1/abc.jpg", file_name="SL01G-1-01.jpg",
        mime_type="image/jpeg", scope="pouch", scope_id=str(shelf["onyx"].pk),
    )
    monkeypatch.setattr(storage, "presign_get", lambda key, mime, name: f"https://bucket.example/{key}?name={name}")
    _client_mode(client, admin_user_)
    assert f'src="{reverse("inventory:photo", args=[asset.pk])}"' in client.get(
        reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()
    location = client.get(reverse("inventory:photo", args=[asset.pk]))["Location"]
    assert "SL01G" not in location and f"name={shelf['onyx'].ref}.jpg" in location
