"""Serving media, and the rule that a stored MIME is not to be trusted.

The CRM's photos arrive as base64 inside a JSONB blob and are served from this
app's own origin until they reach the bucket. The MIME on them came out of a
data URI header that whoever uploaded through the old CRM controlled, so an
``image/svg+xml`` or a ``text/html`` would be stored XSS with the viewer's
session. These are the two halves that stop it: refused on the way in, and
coerced to a download on the way out.
"""
import pytest
from django.urls import reverse

from mediahub import storage
from mediahub.models import MediaAsset

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _asset(mime, data=PNG, **extra):
    return MediaAsset.objects.create(
        media_ref=extra.pop("ref", "M900001"),
        scope="order",
        scope_id="1",
        kind="PHOTO",
        mime_type=mime,
        inline_data=data,
        bytes=len(data),
        file_name=extra.pop("name", "front.png"),
        **extra,
    )


def test_an_image_is_served_inline_with_its_own_type(client, admin_user_):
    client.force_login(admin_user_)
    asset = _asset("image/png")
    response = client.get(reverse("mediahub:media", args=[asset.pk]))
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response["Content-Disposition"].startswith("inline")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in response["Content-Security-Policy"]
    assert response.content == PNG


@pytest.mark.parametrize("mime", ["text/html", "image/svg+xml", "application/javascript", "text/xml"])
def test_a_scriptable_type_is_never_served_as_itself(client, admin_user_, mime):
    """Even if one somehow reached the column, it comes back as a download."""
    client.force_login(admin_user_)
    asset = _asset(mime, data=b"<svg onload=alert(1)>", ref="M900002", name="x.svg")
    response = client.get(reverse("mediahub:media", args=[asset.pk]))
    assert response["Content-Type"] == "application/octet-stream"
    assert response["Content-Disposition"].startswith("attachment")
    assert response["X-Content-Type-Options"] == "nosniff"


def test_the_allowlist_names_what_may_be_served():
    assert storage.is_serveable("image/jpeg")
    assert storage.is_serveable("IMAGE/PNG")
    assert storage.is_serveable("image/png; charset=utf-8")
    assert not storage.is_serveable("image/svg+xml")
    assert not storage.is_serveable("text/html")
    assert not storage.is_serveable(None)


def test_the_importer_refuses_a_type_it_would_not_serve():
    """Cheaper to keep it out than to remember to be careful later."""
    from etl.crm_shapes import media_from_blob

    assert media_from_blob({"photo": "data:image/svg+xml;base64,PHN2Zy8+"}) == []
    assert media_from_blob({"photo": "data:text/html;base64,PGgxPmhpPC9oMT4="}) == []


def test_any_file_type_may_be_uploaded(client, admin_user_, received_piece, settings):
    settings.MEDIA_DIRECT_UPLOAD = False
    client.force_login(admin_user_)
    response = client.post(
        reverse("mediahub:presign"),
        data=f'{{"scope":"piece","entity_id":{received_piece.pk},"file_name":"x.svg","mime_type":"image/svg+xml"}}',
        content_type="application/json",
    )
    assert response.status_code == 200


def test_a_cad_file_is_signed_with_the_type_the_browser_will_send(client, admin_user_, received_piece, monkeypatch):
    """A browser gives a .3dm no type at all. The PUT must carry the type the
    URL was signed for, so presign says which one that is."""
    signed = {}
    monkeypatch.setattr(storage, "presign_put", lambda key, content_type: signed.setdefault("type", content_type))
    client.force_login(admin_user_)
    response = client.post(
        reverse("mediahub:presign"),
        data=f'{{"scope":"style","entity_id":{received_piece.style_id},"file_name":"ring.3dm","mime_type":"","kind":"CAD"}}',
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["content_type"] == signed["type"] == "application/octet-stream"


def test_a_type_we_would_not_show_comes_back_as_a_download(monkeypatch):
    """Anything may go up, so what comes down decides: an SVG or HTML page in
    the bucket must never render, only save."""
    from django.core.cache import cache

    cache.clear()
    signed = {}

    class Client:
        def generate_presigned_url(self, op, Params, ExpiresIn):
            signed.update(Params)
            return "https://bucket/x"

    monkeypatch.setattr(storage, "client", lambda: Client())
    storage.presign_get("stock/piece/1/a.svg", "image/svg+xml", 'evil".svg')
    assert signed["ResponseContentType"] == "application/octet-stream"
    assert signed["ResponseContentDisposition"] == 'attachment; filename="evil.svg"'

    storage.presign_get("stock/piece/1/b.jpg", "image/jpeg", "front.jpg")
    assert signed["ResponseContentType"] == "image/jpeg"
    assert signed["ResponseContentDisposition"] == 'inline; filename="front.jpg"'


def test_push_inline_media_moves_bytes_into_the_bucket_and_clears_the_row(monkeypatch, admin_user_):
    """And only clears it once the bucket agrees the object is there."""
    from django.core.management import call_command

    asset = _asset("image/png", ref="M900003")
    put = {}
    monkeypatch.setattr(storage, "put_bytes", lambda key, data, ct: put.update(key=key, data=data, ct=ct))
    monkeypatch.setattr(storage, "head", lambda key: {"ContentLength": len(PNG)})

    call_command("push_inline_media")

    asset.refresh_from_db()
    assert asset.inline_data in (None, b"")
    assert asset.storage_key == put["key"]
    assert asset.storage_key.startswith("crm/order/1/")
    assert put["data"] == PNG


def test_a_failed_upload_leaves_the_bytes_where_they_were(monkeypatch, admin_user_):
    """An interrupted run must still serve; re-running finishes the job."""
    from django.core.management import call_command

    asset = _asset("image/png", ref="M900004")

    def boom(key, data, ct):
        raise RuntimeError("bucket said no")

    monkeypatch.setattr(storage, "put_bytes", boom)
    call_command("push_inline_media")

    asset.refresh_from_db()
    assert bytes(asset.inline_data) == PNG
    assert not asset.storage_key
