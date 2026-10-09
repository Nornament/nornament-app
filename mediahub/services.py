"""Resolving many media URLs in one pass, and re-encoding what is in the bucket."""
import logging
from collections import defaultdict

from django.conf import settings
from django.db.models import BooleanField, ExpressionWrapper, Q
from django.urls import reverse
from django.utils import timezone
from django_tasks import task

from . import storage, webp
from .models import MediaAsset

logger = logging.getLogger(__name__)


def without_bytes(assets):
    """Media rows for a list: everything but the photo bytes and the embedding.

    A thumbnail only needs the key. Loading whole rows dragged legacy CRM
    photos (``inline_data``) and 384-float embeddings out of Postgres for every
    row of a list, only to build a URL. ``has_inline`` is what ``urls_for``
    asks instead, so it never touches the deferred column.
    """
    return assets.defer("inline_data", "embedding").annotate(
        has_inline=ExpressionWrapper(
            Q(inline_data__isnull=False) & ~Q(inline_data=b""), output_field=BooleanField()
        )
    )


def for_pieces(piece_ids, limit_each=None):
    """``get_many`` — one query, then presigned URLs, keyed by piece id."""
    assets = without_bytes(MediaAsset.objects).filter(
        piece_id__in=list(piece_ids), is_archived=False, confirmed_at__isnull=False
    ).order_by("piece_id", "-is_catalogue_default", "rank_order")
    grouped = defaultdict(list)
    for asset in assets:
        bucket = grouped[asset.piece_id]
        if limit_each and len(bucket) >= limit_each:
            continue
        bucket.append(asset)
    return grouped


def urls_for(assets, thumbs=False):
    """A URL per asset, or ``None`` where there is nothing to serve.

    ``thumbs`` is for list pages: the list-sized copy where one has been made,
    the photo itself where it has not.

    An asset whose bytes are still in the row is served by Django from
    ``/media/<id>/`` rather than presigned — the CRM's photos arrived as base64
    in a JSONB blob and have never been in a bucket. Everything else is a
    presigned GET, and if storage is not configured those come back ``None`` so
    the screen falls back to a placeholder instead of failing.
    """
    urls = {}
    remote = []
    for asset in assets:
        inline = getattr(asset, "has_inline", None)
        if inline if inline is not None else asset.inline_data:
            urls[asset.pk] = reverse("mediahub:media", args=[asset.pk])
        else:
            remote.append(asset)
    try:
        urls |= {
            a.pk: storage.presign_get(a.thumb_key, "image/webp") if thumbs and a.thumb_key
            else storage.presign_get(a.storage_key, a.mime_type, a.file_name)
            for a in remote
        }
    except storage.StorageNotConfigured:
        urls |= {a.pk: None for a in remote}
    return urls


def to_webp(asset, data=None, quality=None):
    """Re-encode one asset as WebP, in the bucket and on the row.

    ``data`` is the bytes when the caller already has them — the proxy upload
    path does, the backfill does not and fetches them. The new object goes to a
    ``.webp`` key beside the old one and the old object is left where it is:
    the row stops pointing at it, so it costs storage and nothing else, and a
    bad conversion is undone by pointing the row back.

    Returns the bytes saved, or ``None`` when there was nothing worth doing —
    already WebP, not an image, a format Pillow will not open, or a result that
    came out no smaller.
    """
    if not webp.convertible(asset.mime_type):
        return None
    if data is None:
        data = bytes(asset.inline_data) if asset.inline_data else storage.get_bytes(asset.storage_key)
    try:
        encoded, width, height = webp.encode(data, quality)
    except webp.NotSmaller:
        return None

    fields = ["mime_type", "file_name", "bytes", "file_size_kb", "sha256", "width_px", "height_px"]
    if asset.inline_data:
        # never reached the bucket; it is still a row, and it stays one
        asset.inline_data = encoded
        fields.append("inline_data")
    else:
        key = webp.webp_key(asset.storage_key)
        storage.put_bytes(key, encoded, "image/webp")
        storage.head(key)  # it is only converted when the bucket agrees
        asset.storage_key = key
        fields += ["storage_key", "confirmed_at"]
        asset.confirmed_at = asset.confirmed_at or timezone.now()

    saved = len(data) - len(encoded)
    asset.mime_type = "image/webp"
    asset.file_name = webp.webp_name(asset.file_name)
    asset.bytes = len(encoded)
    asset.file_size_kb = int(len(encoded) / 1024) or None
    asset.sha256 = storage.sha256_of(encoded)
    asset.width_px, asset.height_px = width, height
    asset.save(update_fields=fields)
    return saved


@task()
def finish_upload_later(media_id):
    """:func:`finish_upload` on the queue, run by ``manage.py db_worker``.

    A WebP encode at ``method=6`` and a DINOv2 embedding take seconds per
    photo. Done inside the upload request, that held one of the web workers —
    and a form with several photos could outrun gunicorn's timeout.
    """
    asset = MediaAsset.objects.filter(pk=media_id).first()
    if asset is not None:
        finish_upload(asset)


def finish_upload(asset, data=None):
    """What every new upload gets once its object is in the bucket: WebP, then search.

    Every way in queues this — the browser's presigned PUT, the proxy, and
    ``attach_uploads`` (form posts and the IVY import). Best effort by design:
    the upload has already succeeded, so a failure here leaves the original
    intact, and ``media_to_webp`` / ``media_thumbs`` / ``embed_media`` pick it up later.
    """
    mime = asset.mime_type
    if data is None and asset.storage_key and (webp.convertible(mime) or storage.is_drawable(mime)):
        # fetched once for every step below, rather than once each
        data = storage.get_bytes(asset.storage_key)
    if settings.MEDIA_WEBP_ON_UPLOAD:
        try:
            to_webp(asset, data)
        except Exception:  # noqa: BLE001 — a smaller file is never worth losing an upload over
            logger.exception("webp conversion failed for media %s", asset.pk)
    try:
        make_thumb(asset, data)
    except Exception:  # noqa: BLE001 — a list falls back to the photo itself
        logger.exception("thumbnail failed for media %s", asset.pk)

    from stock import identify

    try:
        identify.embed_asset(asset, data)
    except Exception:  # noqa: BLE001 — search is never worth losing an upload over
        logger.exception("embedding failed for media %s", asset.pk)


def make_thumb(asset, data=None):
    """Put a list-sized WebP beside the photo and its key on the row.

    Returns the key, or ``None`` for anything a list cannot draw anyway — a
    video, a PDF, a HEIC — and for a photo still held in its row rather than
    the bucket (``push_inline_media`` moves those; ``media_thumbs`` follows).
    """
    if asset.inline_data or not asset.storage_key or not asset.is_image:
        return None
    if data is None:
        data = storage.get_bytes(asset.storage_key)
    encoded, _, _ = webp.thumbnail(data)
    key = webp.thumb_key(asset.storage_key)
    storage.put_bytes(key, encoded, "image/webp")
    asset.thumb_key = key
    asset.save(update_fields=["thumb_key"])
    return key


def _owner(scope, entity_id):
    """Stock media hangs off its FK, as the presigned upload does; CRM off scope.

    Piece pages read ``piece.media``. A piece photo saved with only
    ``scope='piece'`` is in the bucket and on no screen — which is where every
    photo the IVY import attached used to end up.
    """
    if scope == "piece":
        return {"piece_id": entity_id}
    if scope == "style":
        return {"style_id": entity_id}
    return {"scope": scope, "scope_id": str(entity_id)}


def attach_uploads(files, scope, entity_id, user, kind=None):
    """Take files off a normal form POST and put them in the bucket.

    The JS path (presign → PUT → confirm) needs an entity that already exists,
    which is why the legacy app could photograph an enquiry while creating it
    and this one could not. A form that posts ``multipart/form-data`` can:
    the row is saved first, then its files land here in the same request.

    Returns the assets that made it. A file the bucket refuses is skipped and
    reported, never silently dropped — the caller turns that into a message.
    """
    from django.contrib.auth import get_user_model  # noqa: F401  (kept lazy, as elsewhere)

    saved, refused = [], []
    for upload in files or []:
        mime = upload.content_type or storage.guess_mime(upload.name)
        if not storage.is_serveable(mime):
            refused.append(f"{upload.name} ({mime})")
            continue
        data = upload.read()
        key = storage.build_key(scope, entity_id, upload.name)
        try:
            storage.put_bytes(key, data, mime)
        except storage.StorageNotConfigured as error:
            refused.append(f"{upload.name} ({error})")
            continue
        asset = MediaAsset.objects.create(
            media_ref=next_media_ref(),
            kind=kind or kind_for(mime),
            storage_key=key,
            file_name=upload.name,
            mime_type=mime,
            bytes=len(data),
            file_size_kb=int(len(data) / 1024) or None,
            sha256=storage.sha256_of(data),
            confirmed_at=timezone.now(),
            uploaded_by=user,
            **_owner(scope, entity_id),
        )
        finish_upload_later.enqueue(asset.pk)
        saved.append(asset)
    return saved, refused


def kind_for(mime):
    """PHOTO / VIDEO / DOCUMENT off the content type."""
    from stock.enums import MediaKind

    mime = (mime or "").lower()
    if mime.startswith("video/"):
        return MediaKind.VIDEO
    if mime.startswith("image/"):
        return MediaKind.PHOTO
    return MediaKind.DOCUMENT


def next_media_ref():
    last = MediaAsset.objects.exclude(media_ref=None).order_by("-media_id").values_list("media_ref", flat=True).first()
    number = int(last[1:]) + 1 if last and last[1:].isdigit() else 1
    return f"M{number:06d}"
