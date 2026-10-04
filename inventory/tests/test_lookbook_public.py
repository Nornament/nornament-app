"""Part 5e: what a client sees through a lookbook link — and everything they must not."""
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import lookbooks, services
from inventory.models import PriceEntry
from inventory.tests.conftest import SUPPLIER

pytestmark = pytest.mark.django_db


@pytest.fixture
def book(sales_user, admin_user_, shelf):
    services.add_price(admin_user_, shelf["onyx"], PriceEntry.LIST, Decimal("9500"), date(2026, 9, 1))
    b = lookbooks.create(sales_user, "Greens & golds")
    lookbooks.update(sales_user, b, "Greens & golds", "Picked for you", True)
    lookbooks.add_stones(sales_user, b, f"{shelf['onyx'].ref}, {shelf['ruby'].ref}")
    return b


def _get(client, book, **kw):
    return client.get(reverse("lookbook_public", args=[book.token]), **kw)


def test_no_login_and_only_client_safe_fields(client, book, shelf):
    response = _get(client, book)
    body = response.content.decode()
    assert response.status_code == 200 and response["X-Robots-Tag"] == "noindex" and 'content="noindex"' in body
    assert "Greens &amp; golds" in body and "Picked for you" in body
    assert shelf["onyx"].ref in body and "Green Onyx" in body and "12.50" in body and "Available" in body
    for secret in ("SL01G", "C-117", "keep away from light", "SL!2", "7,919", "9,500", SUPPLIER, "98,988"):
        assert secret not in body, secret


def test_an_empty_pouch_reads_no_longer_available(client, book, shelf, accounts_user, parties):
    from inventory import ledger_single
    from inventory.models import Movement

    ledger_single.post_single(accounts_user, shelf["ruby"], Movement.Reason.SALE, pcs=None, ct=Decimal("40"),
                              customer=parties["customer"])
    assert "No longer available" in _get(client, book).content.decode()


def test_off_and_unknown_links_answer_the_same(client, book, sales_user):
    unknown = client.get(reverse("lookbook_public", args=["not-a-token"]))
    lookbooks.update(sales_user, book, book.title, book.note, False)
    off = _get(client, book)
    assert unknown.status_code == off.status_code == 404
    assert "This lookbook is no longer shared." in off.content.decode()
    assert unknown.content == off.content


def test_enquire_by_whatsapp_else_email_else_hidden(client, book, shelf, settings):
    settings.LOOKBOOK_WHATSAPP, settings.LOOKBOOK_EMAIL = "919800000000", "hello@example.com"
    body = _get(client, book).content.decode()
    assert "https://wa.me/919800000000?text=Lookbook%20Greens%20%26%20golds%20%E2%80%94%20" + shelf["onyx"].ref in body
    settings.LOOKBOOK_WHATSAPP = ""
    assert "mailto:hello@example.com?subject=" in _get(client, book).content.decode()
    settings.LOOKBOOK_EMAIL = ""
    assert "Enquire" not in _get(client, book).content.decode()


def test_the_photo_route_serves_only_the_lookbooks_own_photos(client, book, shelf, sales_user):
    from mediahub.models import MediaAsset
    from stock.enums import MediaKind

    def photo(pouch, name):
        return MediaAsset.objects.create(media_ref=f"M-{name}", kind=MediaKind.PHOTO, storage_key=f"x/{name}.jpg",
                                         file_name=f"{name}.jpg", mime_type="image/jpeg", scope="pouch",
                                         scope_id=str(pouch.pk))

    mine = photo(shelf["onyx"], "a")
    url = reverse("lookbook_photo", args=[book.token, mine.pk])
    assert client.get(url).status_code in (302, 503)          # served (or storage not configured locally)
    body = _get(client, book).content.decode()
    assert url in body
    lookbooks.remove(sales_user, book, shelf["onyx"].pk)
    assert client.get(url).status_code == 404                  # no longer in the lookbook
    lookbooks.add_stones(sales_user, book, shelf["onyx"].ref)
    lookbooks.update(sales_user, book, book.title, book.note, False)
    assert client.get(url).status_code == 404                  # link off


def test_the_photo_route_serves_only_the_pouchs_first_photo_by_rank(client, book, shelf):
    from mediahub.models import MediaAsset
    from stock.enums import MediaKind

    def photo(name, rank=100, kind=MediaKind.PHOTO, archived=False):
        return MediaAsset.objects.create(media_ref=f"M-{name}", kind=kind, storage_key=f"x/{name}.jpg",
                                         file_name=f"{name}.jpg", mime_type="image/jpeg", scope="pouch",
                                         scope_id=str(shelf["onyx"].pk), rank_order=rank, is_archived=archived)

    first = photo("a", rank=1)
    second = photo("b", rank=2)
    archived = photo("c", rank=0, archived=True)
    other_kind = photo("d", rank=0, kind=MediaKind.CAD)
    assert client.get(reverse("lookbook_photo", args=[book.token, first.pk])).status_code in (302, 503)
    for not_shown in (second, archived, other_kind):
        assert client.get(reverse("lookbook_photo", args=[book.token, not_shown.pk])).status_code == 404


def test_a_nul_byte_token_404s_instead_of_raising(client):
    for url in ("/lookbook/%00/", "/lookbook/%00/photo/1/"):
        response = client.get(url)
        assert response.status_code == 404
        assert b"This lookbook is no longer shared." in response.content


def test_both_public_views_are_never_cached(client, book):
    assert "no-store" in _get(client, book)["Cache-Control"]
    photo = client.get(reverse("lookbook_photo", args=[book.token, 1]))
    assert photo.status_code == 404 and "no-store" in photo["Cache-Control"]


def test_head_works_on_both_public_views(client, book):
    assert client.head(reverse("lookbook_public", args=[book.token])).status_code == 200
    assert client.head(reverse("lookbook_photo", args=[book.token, 1])).status_code == 404


def test_the_cards_carry_only_the_allow_listed_keys(client, book):
    response = _get(client, book)
    allowed = {"ref", "stone_name", "colour", "shape", "cut", "size_display", "ct", "pcs", "countable",
               "photo_id", "available", "enquire"}
    assert response.context["cards"]
    for card in response.context["cards"]:
        assert set(card.keys()) == allowed


def test_a_blank_stone_name_shows_unidentified(client, sales_user, admin_user_, shelf):
    blank = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "9"}, pcs=1, ct=Decimal("1"), rate=None)
    b = lookbooks.create(sales_user, "Blank")
    lookbooks.add_stones(sales_user, b, blank.ref)
    body = client.get(reverse("lookbook_public", args=[b.token])).content.decode()
    assert "Unidentified" in body


def test_joining_colour_shape_cut_skips_blanks_without_a_stray_separator(client, sales_user, admin_user_, shelf):
    partial = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "11", "colour": "Pink"},
                                  pcs=1, ct=Decimal("1"), rate=None)
    b = lookbooks.create(sales_user, "Partial")
    lookbooks.add_stones(sales_user, b, partial.ref)
    body = client.get(reverse("lookbook_public", args=[b.token])).content.decode()
    assert "Pink</div>" in body


def test_the_503_for_unconfigured_storage_has_its_own_text(client, book, shelf, monkeypatch):
    from mediahub import storage
    from mediahub.models import MediaAsset
    from stock.enums import MediaKind

    asset = MediaAsset.objects.create(media_ref="M-x", kind=MediaKind.PHOTO, storage_key="x/x.jpg",
                                      file_name="x.jpg", mime_type="image/jpeg", scope="pouch",
                                      scope_id=str(shelf["onyx"].pk))

    def boom(*a, **k):
        raise storage.StorageNotConfigured

    monkeypatch.setattr(storage, "presign_get", boom)
    response = client.get(reverse("lookbook_photo", args=[book.token, asset.pk]))
    assert response.status_code == 503
    assert b"Photos are unavailable right now." in response.content
    assert b"This lookbook is no longer shared." not in response.content


def test_the_enquire_link_carries_no_inline_style(client, book, settings):
    settings.LOOKBOOK_WHATSAPP = "919800000000"
    body = _get(client, book).content.decode()
    assert '<a class="btn pri" href=' in body and "style=\"margin-top:8px" not in body
