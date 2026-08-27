"""The WebP re-encoder: what it converts, what it refuses, and what it rewrites."""
import io

import pytest
from PIL import Image

from mediahub import services, storage, webp
from mediahub.models import MediaAsset
from stock.models import Piece

pytestmark = pytest.mark.django_db


def _noise(size=(400, 400)):
    """A photograph-ish image: noisy enough that lossless WebP would be no help."""
    image = Image.new("RGB", size)
    image.putdata([((x * 7) % 256, (y * 11) % 256, (x * y) % 256) for y in range(size[1]) for x in range(size[0])])
    return image


def _jpeg(size=(400, 400)):
    image = _noise(size)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def _png_with_alpha(size=(200, 200)):
    buffer = io.BytesIO()
    Image.new("RGBA", size, (200, 30, 30, 128)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_a_photograph_comes_out_smaller_and_still_readable():
    data = _jpeg()
    encoded, width, height = webp.encode(data)
    assert len(encoded) < len(data)
    assert (width, height) == (400, 400)
    with Image.open(io.BytesIO(encoded)) as out:
        assert out.format == "WEBP"


def test_flat_art_with_transparency_is_encoded_losslessly():
    """A logo re-encoded lossily would fringe. Alpha means lossless."""
    data = _png_with_alpha()
    encoded, _, _ = webp.encode(data)
    with Image.open(io.BytesIO(encoded)) as out:
        assert out.convert("RGBA").getpixel((10, 10)) == (200, 30, 30, 128)


def test_a_conversion_that_would_grow_the_file_is_refused():
    """An encoder allowed to make files bigger is a regression with a nice name.

    A JPEG already crushed to quality 5 is smaller than any honest WebP of the
    same picture, so the guard is what stops the "optimisation" adding bytes.
    """
    crushed = io.BytesIO()
    _noise().save(crushed, format="JPEG", quality=5)
    with pytest.raises(webp.NotSmaller):
        webp.encode(crushed.getvalue())


def test_the_key_moves_to_webp_beside_the_original():
    assert webp.webp_key("stock/piece/12/abcdef.jpg") == "stock/piece/12/abcdef.webp"
    assert webp.webp_key("crm/customer/3/deadbeef") == "crm/customer/3/deadbeef.webp"
    assert webp.webp_name("IMG_0042.JPEG") == "IMG_0042.webp"


def test_converting_an_asset_repoints_the_row_and_leaves_the_original(piece, monkeypatch):
    """The old object stays in the bucket: a conversion is undone by pointing back."""
    data = _jpeg()
    put = {}
    monkeypatch.setattr(storage, "get_bytes", lambda key: data)
    monkeypatch.setattr(storage, "put_bytes", lambda key, body, ct: put.update(key=key, body=body, ct=ct))
    monkeypatch.setattr(storage, "head", lambda key: {"ContentLength": len(put["body"])})

    asset = MediaAsset.objects.create(
        piece=Piece.objects.get(pk=piece.pk),
        storage_key="stock/piece/1/original.jpg",
        file_name="original.jpg",
        mime_type="image/jpeg",
        bytes=len(data),
    )
    saved = services.to_webp(asset)

    assert saved > 0
    assert put["key"] == "stock/piece/1/original.webp" and put["ct"] == "image/webp"
    asset.refresh_from_db()
    assert asset.storage_key == "stock/piece/1/original.webp"
    assert asset.mime_type == "image/webp"
    assert asset.file_name == "original.webp"
    assert asset.bytes == len(put["body"]) < len(data)
    assert (asset.width_px, asset.height_px) == (400, 400)


def test_an_asset_that_is_already_webp_is_left_alone(piece):
    asset = MediaAsset.objects.create(
        piece=Piece.objects.get(pk=piece.pk), storage_key="stock/piece/1/x.webp", mime_type="image/webp"
    )
    assert services.to_webp(asset) is None


def test_a_video_is_never_re_encoded(piece):
    asset = MediaAsset.objects.create(
        piece=Piece.objects.get(pk=piece.pk), storage_key="stock/piece/1/clip.mp4", mime_type="video/mp4"
    )
    assert services.to_webp(asset) is None
