"""Identify a piece by photo: the embedder, the search, and the screen.

Everything except one test runs on a fake embedder, so CI never needs the
88 MB model. The one that needs it skips when the file is absent.
"""
import io

import numpy as np
import pytest
from django.conf import settings
from django.utils import timezone
from PIL import Image

from mediahub.models import MediaAsset
from stock import identify
from stock.enums import MediaKind


def _jpeg(size=(640, 480), colour=(200, 160, 40), exif_orientation=None):
    image = Image.new("RGB", size, colour)
    # a stripe, so a crop or rotation actually changes the picture
    for x in range(size[0] // 3):
        for y in range(size[1]):
            image.putpixel((x, y), (20, 20, 20))
    buffer = io.BytesIO()
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        image.save(buffer, format="JPEG", exif=exif)
    else:
        image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_preprocess_is_the_models_own_recipe():
    pixels = identify.preprocess(_jpeg())
    assert pixels.shape == (1, 3, 224, 224)
    assert pixels.dtype == np.float32
    # a mid-gold pixel from the right of the frame, normalised per channel
    r, g, b = (200 / 255 - 0.485) / 0.229, (160 / 255 - 0.456) / 0.224, (40 / 255 - 0.406) / 0.225
    # abs=0.1 in normalised units is ~6 levels of 255: room for JPEG, not for a wrong mean/std
    assert pixels[0, :, 112, 200] == pytest.approx([r, g, b], abs=0.1)


def test_a_phone_photo_stored_sideways_is_turned_upright_first():
    """Orientation 6 means "rotate 90° to view": the stripe must end up on top."""
    upright = identify.preprocess(_jpeg(size=(480, 640)))
    sideways = identify.preprocess(_jpeg(size=(640, 480), exif_orientation=6))
    assert upright.shape == sideways.shape
    # the dark stripe runs along one edge either way; after transpose the
    # sideways shot's stripe is a top band, not a left band
    assert sideways[0, 0, 5, 112] < sideways[0, 0, 200, 112]


def test_bytes_that_are_not_an_image_are_refused():
    with pytest.raises(identify.NotAnImage):
        identify.preprocess(b"%PDF-1.7 not a photo")


def test_a_missing_model_says_so(settings, tmp_path):
    settings.IDENTIFY_MODEL_PATH = tmp_path / "absent.onnx"
    identify._session.cache_clear()
    with pytest.raises(identify.ModelMissing):
        identify.embed(_jpeg())
    identify._session.cache_clear()


@pytest.mark.skipif(not settings.IDENTIFY_MODEL_PATH.exists(), reason="model file not downloaded")
def test_the_real_model_knows_a_photo_from_a_different_one():
    photo = _jpeg()
    same = np.asarray(identify.embed(photo))
    assert np.linalg.norm(same) == pytest.approx(1.0, abs=1e-4)
    assert same.shape == (384,)
    assert float(same @ np.asarray(identify.embed(photo))) > 0.99

    cropped = Image.open(io.BytesIO(photo)).crop((20, 20, 620, 460)).rotate(8)
    buffer = io.BytesIO()
    cropped.save(buffer, format="JPEG")
    other = io.BytesIO()
    Image.new("RGB", (640, 480), (30, 90, 200)).save(other, format="JPEG")

    near = float(same @ np.asarray(identify.embed(buffer.getvalue())))
    far = float(same @ np.asarray(identify.embed(other.getvalue())))
    assert near > far


def _unit(*values):
    vector = np.zeros(384, dtype=np.float32)
    vector[: len(values)] = values
    return (vector / np.linalg.norm(vector)).tolist()


def _photo(piece, vector, *, kind=MediaKind.PHOTO, archived=False, confirmed=True):
    return MediaAsset.objects.create(
        media_ref=f"M{MediaAsset.objects.count() + 1:06d}",
        piece=piece,
        kind=kind,
        storage_key=f"stock/piece/{piece.pk}/{MediaAsset.objects.count()}.webp",
        file_name="p.webp",
        mime_type="image/webp",
        confirmed_at=timezone.now() if confirmed else None,
        is_archived=archived,
        embedding=vector,
    )


def _another_piece(piece, code):
    from stock.models import Piece

    return Piece.objects.create(
        jewel_code=code, style=piece.style, metal_purity="18K", stock_state=piece.stock_state,
        location=piece.location, current_bom_version=1,
    )


@pytest.mark.django_db
def test_the_closest_piece_comes_first_with_one_card_per_piece(received_piece, admin_user_):
    other = _another_piece(received_piece, "ER00739")
    _photo(received_piece, _unit(1, 0.1))
    _photo(received_piece, _unit(1, 0.05))  # a second, even closer angle
    _photo(other, _unit(0.2, 1))

    matches = identify.search(admin_user_, _unit(1, 0))

    assert [m.piece_id for m in matches] == [received_piece.pk, other.pk]
    assert matches[0].score > 0.99
    assert matches[0].score > matches[1].score


@pytest.mark.django_db
def test_only_confirmed_live_piece_photos_are_candidates(received_piece, admin_user_):
    _photo(received_piece, _unit(1), kind=MediaKind.CAD)
    _photo(received_piece, _unit(1), archived=True)
    _photo(received_piece, _unit(1), confirmed=False)
    assert identify.search(admin_user_, _unit(1)) == []


@pytest.mark.django_db
def test_a_piece_the_user_cannot_see_is_never_returned(received_piece, sales_user, locations):
    """The piece sits in MUM; a HO-only login must not learn it exists."""
    _photo(received_piece, _unit(1))
    sales_user.home_location = locations["HO"]
    sales_user.save(update_fields=["home_location"])
    assert identify.search(sales_user, _unit(1)) == []


@pytest.mark.django_db
def test_coverage_counts_pieces_with_an_embedded_photo(received_piece, admin_user_):
    _another_piece(received_piece, "ER00739")
    _photo(received_piece, _unit(1))
    assert identify.coverage(admin_user_) == {"searchable": 1, "total": 2}
