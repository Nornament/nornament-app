"""Resolving many media URLs in one pass, and re-encoding what is in the bucket."""
from collections import defaultdict

from django.urls import reverse
from django.utils import timezone

from . import storage, webp
from .models import MediaAsset


def for_pieces(piece_ids, limit_each=None):
    """``get_many`` — one query, then presigned URLs, keyed by piece id."""
    assets = MediaAsset.objects.filter(
        piece_id__in=list(piece_ids), is_archived=False, confirmed_at__isnull=False
    ).order_by("piece_id", "rank_order")
    grouped = defaultdict(list)
    for asset in assets:
        bucket = grouped[asset.piece_id]
        if limit_each and len(bucket) >= limit_each:
            continue
        bucket.append(asset)
    return grouped


def urls_for(assets):
    """A URL per asset, or ``None`` where there is nothing to serve.

    An asset whose bytes are still in the row is served by Django from
    ``/media/<id>/`` rather than presigned — the CRM's photos arrived as base64
    in a JSONB blob and have never been in a bucket. Everything else is a
    presigned GET, and if storage is not configured those come back ``None`` so
    the screen falls back to a placeholder instead of failing.
    """
    urls = {}
    remote = []
    for asset in assets:
        if asset.inline_data:
            urls[asset.pk] = reverse("mediahub:media", args=[asset.pk])
        else:
            remote.append(asset)
    try:
        urls |= {a.pk: storage.presign_get(a.storage_key, a.mime_type, a.file_name) for a in remote}
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
            scope=scope,
            scope_id=str(entity_id),
        )
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
