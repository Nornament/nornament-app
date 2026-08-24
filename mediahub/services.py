"""Resolving many media URLs in one pass, for a page that shows a grid."""
from collections import defaultdict

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
    """Presigned GET URLs, or ``None`` each when storage is not configured."""
    try:
        return {asset.pk: storage.presign_get(asset.storage_key, asset.mime_type, asset.file_name) for asset in assets}
    except storage.StorageNotConfigured:
        return {asset.pk: None for asset in assets}
