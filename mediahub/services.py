"""Resolving many media URLs in one pass, for a page that shows a grid."""
from collections import defaultdict

from django.urls import reverse

from . import storage
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
