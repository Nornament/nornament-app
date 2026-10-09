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


def test_a_form_or_import_upload_is_converted_too(piece, monkeypatch, settings):
    """``attach_uploads`` (CRM forms, the IVY import) used to store the JPEG as sent."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_WEBP_ON_UPLOAD = True
    settings.TASKS = {"default": {"BACKEND": "django_tasks.backends.immediate.ImmediateBackend"}}
    bucket = {}
    monkeypatch.setattr(storage, "get_bytes", lambda key: bucket[key])
    monkeypatch.setattr(storage, "put_bytes", lambda key, body, ct: bucket.update({key: body}))
    monkeypatch.setattr(storage, "head", lambda key: {"ContentLength": len(bucket[key])})
    monkeypatch.setattr("stock.identify.embed", lambda data: None)

    data = _jpeg()
    saved, refused = services.attach_uploads(
        [SimpleUploadedFile("24P00095.jpg", data, content_type="image/jpeg")], "piece", piece.pk, None
    )
    assert refused == []
    asset = saved[0]
    asset.refresh_from_db()
    assert asset.mime_type == "image/webp" and asset.storage_key.endswith(".webp")
    assert asset.bytes == len(bucket[asset.storage_key]) < len(data)


# ── list thumbnails ──────────────────────────────────────────────────────
def _rotated_jpeg(size=(1600, 1200)):
    """A landscape-shaped JPEG whose EXIF says "turn me" — a phone portrait."""
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90° clockwise to display
    buffer = io.BytesIO()
    _noise(size).save(buffer, format="JPEG", quality=90, exif=exif)
    return buffer.getvalue()


def test_a_thumbnail_is_list_sized_and_stood_upright():
    encoded, width, height = webp.thumbnail(_rotated_jpeg())
    assert (width, height) == (480, 640), "the long edge is 640, and the portrait stays a portrait"
    with Image.open(io.BytesIO(encoded)) as out:
        assert out.format == "WEBP" and out.size == (480, 640)


def test_a_small_photo_is_never_enlarged():
    _, width, height = webp.thumbnail(_jpeg((200, 100)))
    assert (width, height) == (200, 100)


def test_the_full_size_webp_keeps_a_phone_portrait_upright():
    _, width, height = webp.encode(_rotated_jpeg())
    assert (width, height) == (1200, 1600)


def test_an_upload_gets_a_thumbnail_and_lists_are_handed_it(piece, monkeypatch, settings):
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_WEBP_ON_UPLOAD = True
    settings.TASKS = {"default": {"BACKEND": "django_tasks.backends.immediate.ImmediateBackend"}}
    bucket = {}
    monkeypatch.setattr(storage, "put_bytes", lambda key, body, ct: bucket.update({key: body}))
    monkeypatch.setattr(storage, "head", lambda key: {"ContentLength": len(bucket[key])})
    monkeypatch.setattr(storage, "get_bytes", lambda key: bucket[key])
    monkeypatch.setattr(storage, "presign_get", lambda key, *args, **kwargs: f"https://bucket/{key}")
    monkeypatch.setattr("stock.identify.embed", lambda data: None)

    saved, _ = services.attach_uploads(
        [SimpleUploadedFile("p.jpg", _jpeg((1600, 1200)), content_type="image/jpeg")], "piece", piece.pk, None
    )
    asset = MediaAsset.objects.get(pk=saved[0].pk)
    assert asset.thumb_key.endswith(".thumb.webp")
    with Image.open(io.BytesIO(bucket[asset.thumb_key])) as thumb:
        assert max(thumb.size) == 640
    assert services.urls_for([asset], thumbs=True)[asset.pk] == f"https://bucket/{asset.thumb_key}"
    assert services.urls_for([asset])[asset.pk] == f"https://bucket/{asset.storage_key}"


def test_a_list_falls_back_to_the_photo_until_its_thumbnail_exists(piece, monkeypatch):
    monkeypatch.setattr(storage, "presign_get", lambda key, *args, **kwargs: f"https://bucket/{key}")
    asset = MediaAsset.objects.create(
        piece=Piece.objects.get(pk=piece.pk), storage_key="stock/piece/1/a.webp", mime_type="image/webp"
    )
    assert services.urls_for([asset], thumbs=True)[asset.pk] == "https://bucket/stock/piece/1/a.webp"


def test_the_backfill_makes_the_missing_thumbnails_once(piece, monkeypatch):
    from django.core.management import call_command
    from django.utils import timezone

    bucket = {"stock/piece/1/a.webp": _jpeg()}
    monkeypatch.setattr(storage, "get_bytes", lambda key: bucket[key])
    monkeypatch.setattr(storage, "put_bytes", lambda key, body, ct: bucket.update({key: body}))
    asset = MediaAsset.objects.create(
        piece=Piece.objects.get(pk=piece.pk), storage_key="stock/piece/1/a.webp", mime_type="image/webp",
        confirmed_at=timezone.now(),
    )
    call_command("media_thumbs")
    asset.refresh_from_db()
    assert asset.thumb_key == "stock/piece/1/a.thumb.webp" and asset.thumb_key in bucket

    out = io.StringIO()
    call_command("media_thumbs", stdout=out)
    assert "0 photo(s) have no thumbnail" in out.getvalue()
