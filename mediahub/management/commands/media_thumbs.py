"""Make the list-sized thumbnail for every photo that does not have one yet.

New uploads get theirs as they arrive. This is the other half: the photos that
were in the bucket before thumbnails existed. Safe to stop and re-run — a photo
with a thumbnail is skipped because its row already names one.
"""
from django.core.management.base import BaseCommand

from mediahub import services, storage
from mediahub.models import MediaAsset


class Command(BaseCommand):
    help = "Make list thumbnails for photos in the bucket that have none."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Count what would be made and stop.")
        parser.add_argument("--limit", type=int, default=0, help="Stop after this many.")

    def handle(self, *args, **options):
        pending = (
            MediaAsset.objects.filter(
                thumb_key__isnull=True,
                inline_data__isnull=True,
                mime_type__in=sorted(storage.DRAWABLE_TYPES),
                is_archived=False,
                confirmed_at__isnull=False,
            )
            .exclude(storage_key__isnull=True)
            .exclude(storage_key="")
            .defer("embedding")
            .order_by("media_id")
        )
        total = pending.count()
        self.stdout.write(f"{total} photo(s) have no thumbnail.")
        if options["dry_run"] or not total:
            return
        if options["limit"]:
            pending = pending[: options["limit"]]

        made = failed = 0
        for asset in pending:
            try:
                if services.make_thumb(asset):
                    made += 1
            except storage.StorageNotConfigured as error:
                raise SystemExit(f"Media storage is not configured: {error}")
            except Exception as error:  # noqa: BLE001 — one bad object must not stop the run
                failed += 1
                self.stderr.write(f"{asset.media_ref or asset.pk}: {error}")
        self.stdout.write(f"made {made}, failed {failed}")
