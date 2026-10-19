"""Counting by picture: tap a tile, or photograph a piece with no tag."""
import pytest
from django.urls import reverse

from stock import services
from stock.models import Piece, StockCountScan, StockState

pytestmark = pytest.mark.django_db


def test_the_grid_offers_only_this_locations_uncounted_pieces(client, admin_user_, received_piece, locations):
    Piece.objects.create(
        jewel_code="HO00001", style=received_piece.style, metal_purity="18K",
        stock_state=StockState.IN_STOCK, location=locations["HO"], current_bom_version=1,
    )
    client.force_login(admin_user_)
    count = services.open_count(admin_user_, "MUM")
    page = client.get(reverse("stock:count_detail", kwargs={"count_id": count.pk})).content.decode()
    assert 'title="Count ER00738"' in page
    assert "HO00001" not in page  # another location's piece is never offered


def test_tapping_a_tile_scans_the_piece_and_takes_it_off_the_grid(client, admin_user_, received_piece):
    client.force_login(admin_user_)
    count = services.open_count(admin_user_, "MUM")
    response = client.post(reverse("stock:count_scan", kwargs={"count_id": count.pk}), {"code": "ER00738"},
                           HTTP_HX_REQUEST="true")
    body = response.content.decode()
    assert StockCountScan.objects.filter(count=count, piece=received_piece, verdict="FOUND").exists()
    assert "Found" in body and 'title="Count ER00738"' not in body
    # undo puts it back on the grid
    undone = client.post(reverse("stock:count_unscan", kwargs={"count_id": count.pk}), {"code": "ER00738"})
    assert 'title="Count ER00738"' in undone.content.decode()


def test_a_closed_count_has_no_tiles_and_refuses_a_tap(client, admin_user_, received_piece):
    client.force_login(admin_user_)
    count = services.open_count(admin_user_, "MUM")
    services.close_count(admin_user_, count)
    page = client.get(reverse("stock:count_detail", kwargs={"count_id": count.pk})).content.decode()
    assert 'title="Count ER00738"' not in page and "ER00738" in page  # the frozen list, not tiles
    tap = client.post(reverse("stock:count_scan", kwargs={"count_id": count.pk}), {"code": "ER00738"})
    assert "Not recorded" in tap.content.decode()
    assert not StockCountScan.objects.filter(count=count).exists()


def test_identify_from_a_count_offers_count_this(client, admin_user_, received_piece, monkeypatch):
    from stock import identify

    match = type("Match", (), {"piece_id": received_piece.pk, "media_id": 0, "score": 0.9})
    monkeypatch.setattr(identify, "embed", lambda data: None)
    monkeypatch.setattr(identify, "search", lambda user, vector: [match])
    client.force_login(admin_user_)
    count = services.open_count(admin_user_, "MUM")
    from django.core.files.uploadedfile import SimpleUploadedFile

    photo = SimpleUploadedFile("p.jpg", b"x", content_type="image/jpeg")
    body = client.post(reverse("stock:identify"), {"photo": photo, "count": count.pk},
                       HTTP_HX_REQUEST="true").content.decode()
    assert "Count this" in body and reverse("stock:count_scan", kwargs={"count_id": count.pk}) in body
    # the plain identify screen does not
    photo.seek(0)
    plain = client.post(reverse("stock:identify"), {"photo": photo}, HTTP_HX_REQUEST="true").content.decode()
    assert "Count this" not in plain
