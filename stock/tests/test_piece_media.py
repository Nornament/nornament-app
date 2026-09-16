"""The media, similar and marketing tabs — segregation, linking and the copy.

The three things worth a check here are the three that are easy to get wrong:
a design's files must not appear as a piece's own, a link made from one piece
must read from the other, and every write must refuse a login without
``edit_bom``.
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from mediahub.models import MediaAsset
from stock.enums import MediaKind, StockState
from stock.models import Piece, PieceLink, Style

pytestmark = pytest.mark.django_db


def _asset(kind, *, piece=None, style=None, name="file.jpg", mime="image/jpeg"):
    return MediaAsset.objects.create(
        media_ref=f"M{MediaAsset.objects.count() + 1:06d}",
        piece=piece,
        style=style,
        kind=kind,
        storage_key=f"stock/x/{name}",
        file_name=name,
        mime_type=mime,
        bytes=2048,
        confirmed_at=timezone.now(),
    )


def _detail(client, piece, tab):
    return client.get(reverse("stock:piece_detail", kwargs={"jewel_code": piece.jewel_code}), {"tab": tab})


# ── media ────────────────────────────────────────────────────────────────
def test_each_kind_gets_its_own_section_and_an_empty_kind_gets_none(client, received_piece, admin_user_):
    _asset(MediaKind.PHOTO, piece=received_piece, name="front.jpg")
    _asset(MediaKind.CAD, style=received_piece.style, name="ring.3dm", mime="application/octet-stream")
    client.force_login(admin_user_)

    sections = _detail(client, received_piece, "media").context["media_sections"]
    by_kind = {section["kind"]: section for section in sections}

    assert set(by_kind) == {MediaKind.PHOTO, MediaKind.CAD}, "a kind with no files must not be drawn"
    assert by_kind[MediaKind.PHOTO]["on"] == "piece"
    assert by_kind[MediaKind.CAD]["on"] == "design"
    assert [tile["asset"].file_name for tile in by_kind[MediaKind.CAD]["tiles"]] == ["ring.3dm"]


def test_a_design_file_never_shows_as_a_piece_file(client, received_piece, admin_user_):
    """Both are photographs; only the piece's own belongs in the piece section."""
    _asset(MediaKind.PHOTO, piece=received_piece, name="mine.jpg")
    _asset(MediaKind.PHOTO, style=received_piece.style, name="the-designs.jpg")
    client.force_login(admin_user_)

    photos = next(s for s in _detail(client, received_piece, "media").context["media_sections"])
    assert [tile["asset"].file_name for tile in photos["tiles"]] == ["mine.jpg"]


def test_an_upload_nobody_confirmed_is_not_drawn(client, received_piece, admin_user_):
    asset = _asset(MediaKind.PHOTO, piece=received_piece)
    MediaAsset.objects.filter(pk=asset.pk).update(confirmed_at=None)
    client.force_login(admin_user_)
    assert _detail(client, received_piece, "media").context["media_sections"] == []


def test_the_display_picture_toggles_and_is_what_the_lists_pull(client, received_piece, admin_user_):
    first = _asset(MediaKind.PHOTO, piece=received_piece, name="a.jpg")
    second = _asset(MediaKind.PHOTO, piece=received_piece, name="b.jpg")
    client.force_login(admin_user_)
    url = reverse("stock:piece_media_display", kwargs={"jewel_code": received_piece.jewel_code, "media_id": second.pk})

    client.post(url)
    assert MediaAsset.objects.get(pk=second.pk).is_catalogue_default is True

    from mediahub import services as media_services

    assert media_services.for_pieces([received_piece.pk], limit_each=1)[received_piece.pk][0].pk == second.pk

    client.post(url)  # pressing it again unsets it
    assert MediaAsset.objects.get(pk=second.pk).is_catalogue_default is False
    assert MediaAsset.objects.get(pk=first.pk).is_catalogue_default is False


def test_only_a_photograph_can_be_the_display_picture(client, received_piece, admin_user_):
    card = _asset(MediaKind.JOB_CARD_SCAN, piece=received_piece, name="job.pdf", mime="application/pdf")
    client.force_login(admin_user_)
    client.post(
        reverse("stock:piece_media_display", kwargs={"jewel_code": received_piece.jewel_code, "media_id": card.pk})
    )
    assert MediaAsset.objects.get(pk=card.pk).is_catalogue_default is False


def test_a_tiff_is_a_file_card_not_a_broken_image(client, received_piece, admin_user_):
    """An ``<img>`` cannot draw a TIFF, so the tile says so rather than showing a hole."""
    tiff = _asset(MediaKind.PHOTO, piece=received_piece, name="studio.tif", mime="image/tiff")
    assert tiff.is_image is False
    assert _asset(MediaKind.PHOTO, piece=received_piece, name="ok.jpg").is_image is True

    client.force_login(admin_user_)
    body = _detail(client, received_piece, "media").content.decode()
    assert "browsers cannot draw this" in body or "open it to view" in body
    assert "TIF" in body


def test_a_cad_file_may_be_reserved_even_though_it_is_never_served_from_here(client, received_piece, admin_user_):
    """A 3DM is legitimate stock media and is not in ``SERVEABLE_TYPES``."""
    from mediahub import storage

    assert storage.is_storable("application/octet-stream", "ring.3dm") is True
    assert storage.is_serveable("application/octet-stream") is False
    assert storage.is_storable("text/html", "evil.html") is False


# ── similar ──────────────────────────────────────────────────────────────
@pytest.fixture
def sibling(received_piece, locations, admin_user_):
    other = Piece.objects.create(
        jewel_code="ER00739",
        style=Style.objects.create(style_code="ER00739", name="Leaf studs", category=received_piece.style.category),
        metal_purity="18K",
        stock_state=StockState.IN_STOCK,
        location=received_piece.location,
    )
    return other


def test_a_link_reads_from_both_ends_and_is_made_once(client, received_piece, sibling, admin_user_):
    client.force_login(admin_user_)
    response = client.post(
        reverse("stock:piece_link", kwargs={"jewel_code": received_piece.jewel_code}),
        {"other": sibling.jewel_code, "kind": "Matching set"},
    )
    assert response.status_code == 302
    assert PieceLink.objects.count() == 1

    mine = _detail(client, received_piece, "similar").context["links"]
    theirs = _detail(client, sibling, "similar").context["links"]
    assert [entry["piece"].jewel_code for entry in mine] == [sibling.jewel_code]
    assert [entry["piece"].jewel_code for entry in theirs] == [received_piece.jewel_code]
    assert theirs[0]["kind"] == "Matching set"

    # and the automatic suggestions stop offering what a person already chose
    assert sibling.pk not in {e["piece"].pk for e in _detail(client, received_piece, "similar").context["similar"]}


def test_a_link_is_refused_twice_to_itself_and_with_an_unknown_relationship(
    client, received_piece, sibling, admin_user_
):
    client.force_login(admin_user_)
    url = reverse("stock:piece_link", kwargs={"jewel_code": received_piece.jewel_code})
    client.post(url, {"other": sibling.jewel_code, "kind": "Matching set"})

    client.post(url, {"other": sibling.jewel_code, "kind": "Upsell"})  # already linked
    client.post(url, {"other": received_piece.jewel_code, "kind": "Upsell"})  # itself
    client.post(url, {"other": sibling.jewel_code, "kind": "Pals"})  # not a relationship
    assert PieceLink.objects.count() == 1


def test_unlinking_removes_it_from_both_pieces(client, received_piece, sibling, admin_user_):
    link = PieceLink.objects.create(piece=received_piece, other=sibling, kind="Upsell")
    client.force_login(admin_user_)
    client.post(reverse("stock:piece_unlink", kwargs={"jewel_code": sibling.jewel_code, "link_id": link.pk}))
    assert PieceLink.objects.count() == 0
    assert _detail(client, received_piece, "similar").context["links"] == []


# ── marketing ────────────────────────────────────────────────────────────
def test_keywords_and_talking_points_live_on_the_design(client, received_piece, admin_user_):
    client.force_login(admin_user_)
    url = reverse("stock:piece_marketing", kwargs={"jewel_code": received_piece.jewel_code})

    client.post(url, {"action": "add_keyword", "value": "bridal"})
    client.post(url, {"action": "add_point", "value": "Lead with the setting"})
    client.post(url, {"action": "add_point", "value": "The objection is always weight"})

    context = _detail(client, received_piece, "marketing").context
    assert [tag.name for tag in context["keywords"]] == ["bridal"]
    assert context["talking_points"] == ["Lead with the setting", "The objection is always weight"]

    client.post(url, {"action": "remove_point", "value": "0"})
    client.post(url, {"action": "remove_keyword", "value": "bridal"})
    context = _detail(client, received_piece, "marketing").context
    assert context["talking_points"] == ["The objection is always weight"]
    assert context["keywords"] == []


def test_the_sell_video_is_the_designs_and_is_not_in_the_media_tab(client, received_piece, admin_user_):
    _asset(MediaKind.SELL_VIDEO, style=received_piece.style, name="pitch.mp4", mime="video/mp4")
    client.force_login(admin_user_)
    assert _detail(client, received_piece, "marketing").context["sell_video"].file_name == "pitch.mp4"
    assert _detail(client, received_piece, "media").context["media_sections"] == []


def test_a_stale_talking_point_index_is_refused_rather_than_popping_the_wrong_line(
    client, received_piece, admin_user_
):
    received_piece.style.talking_points = "only one"
    received_piece.style.save(update_fields=["talking_points"])
    client.force_login(admin_user_)
    client.post(
        reverse("stock:piece_marketing", kwargs={"jewel_code": received_piece.jewel_code}),
        {"action": "remove_point", "value": "7"},
    )
    received_piece.style.refresh_from_db()
    assert received_piece.style.talking_points == "only one"


# ── the gates ────────────────────────────────────────────────────────────
def test_every_write_on_these_tabs_refuses_a_login_without_edit_bom(client, received_piece, sibling, sales_user):
    asset = _asset(MediaKind.PHOTO, piece=received_piece)
    link = PieceLink.objects.create(piece=received_piece, other=sibling, kind="Upsell")
    code = received_piece.jewel_code
    client.force_login(sales_user)
    for url, data in (
        (reverse("stock:piece_media_display", kwargs={"jewel_code": code, "media_id": asset.pk}), {}),
        (reverse("stock:piece_link", kwargs={"jewel_code": code}), {"other": sibling.jewel_code}),
        (reverse("stock:piece_unlink", kwargs={"jewel_code": code, "link_id": link.pk}), {}),
        (reverse("stock:piece_marketing", kwargs={"jewel_code": code}), {"action": "add_keyword", "value": "x"}),
    ):
        assert client.post(url, data).status_code == 403, url
    assert PieceLink.objects.count() == 1
    assert MediaAsset.objects.get(pk=asset.pk).is_catalogue_default is False
