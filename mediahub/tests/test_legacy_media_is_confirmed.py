"""A photo migrated from R2 must arrive visible, not looking abandoned.

``confirmed_at`` is this schema's column; legacy ``app.media_asset`` has no
such thing. Every media query filters ``confirmed_at__isnull=False``, so a
straight column-for-column load leaves 400-odd real photos invisible and the
Pieces screen renders no thumbnails at all. That is the bug this guards.
"""
import datetime as dt

import pytest

from etl import legacy
from etl.management.commands.load_legacy import Command
from mediahub.models import MediaAsset

pytestmark = pytest.mark.django_db

UPLOADED = dt.datetime(2025, 3, 4, 9, 30, tzinfo=dt.timezone.utc)

# A legacy row, shaped as the dump gives it: no confirmed_at anywhere.
LEGACY_ROW = {
    "media_id": 7,
    "media_ref": "M000007",
    "scope": "customer",
    "scope_id": "1",
    "kind": "PHOTO",
    "storage_provider": "R2",
    "storage_key": "24P00088/24P00088__PHOTO__r1__M000007.png",
    "file_name": "nornament_test.png",
    "mime_type": "image/png",
    "rank_order": 100,
    "is_archived": False,
    "uploaded_at": UPLOADED,
}


@pytest.fixture
def fake_legacy(monkeypatch):
    """Only ``app.media_asset`` exists; every other table is skipped."""
    monkeypatch.setattr(legacy, "table_exists", lambda table: table == "app.media_asset")
    monkeypatch.setattr(legacy, "rows", lambda sql, params=None: iter([dict(LEGACY_ROW)]))


def test_a_migrated_photo_is_confirmed_so_the_screens_can_see_it(fake_legacy):
    Command().load_stock()

    asset = MediaAsset.objects.get(pk=LEGACY_ROW["media_id"])
    assert asset.confirmed_at == UPLOADED, "the load left a real photo looking like an abandoned upload"
    assert asset.is_confirmed
    assert MediaAsset.objects.filter(confirmed_at=None).count() == 0
