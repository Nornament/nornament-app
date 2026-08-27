"""Re-encode everything already in the bucket as WebP.

New uploads are converted as they arrive. This is the other half: the photos
that were in R2 before any of that existed, copied across to Contabo as they
were. It is safe to stop and re-run — a converted asset is skipped on the next
pass because its row already says ``image/webp``.

The original object is left in the bucket. The row stops pointing at it, so a
conversion anyone dislikes is undone by pointing the row back, and nothing is
destroyed by a command whose whole purpose is to save a few megabytes.
"""
from django.core.management.base import BaseCommand

from mediahub import services, storage, webp
from mediahub.models import MediaAsset


class Command(BaseCommand):
    help = "Convert existing media objects to WebP and repoint their rows."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List what would convert and stop.")
        parser.add_argument("--limit", type=int, default=0, help="Stop after this many.")
        parser.add_argument("--quality", type=int, help="Override MEDIA_WEBP_QUALITY for this run.")

    def handle(self, *args, **options):
        pending = MediaAsset.objects.filter(mime_type__in=sorted(webp.CONVERTIBLE_TYPES)).order_by("media_id")
        total = pending.count()
        if options["limit"]:
            pending = pending[: options["limit"]]

        if options["dry_run"]:
            self.stdout.write(f"{total} asset(s) are still JPEG/PNG/TIFF/BMP.")
            for asset in pending[:20]:
                self.stdout.write(f"  {asset.media_ref or asset.pk}  {asset.mime_type}  {asset.storage_key}")
            return
        if not total:
            self.stdout.write("Nothing to convert — every image is already WebP.")
            return

        converted = skipped = failed = 0
        saved = 0
        for asset in pending:
            try:
                result = services.to_webp(asset, quality=options["quality"])
            except storage.StorageNotConfigured as error:
                raise SystemExit(f"Media storage is not configured: {error}")
            except Exception as error:  # noqa: BLE001 — one bad object must not stop the run
                failed += 1
                self.stderr.write(f"{asset.media_ref or asset.pk}: {error}")
                continue
            if result is None:
                skipped += 1
                continue
            converted += 1
            saved += result

        self.stdout.write(
            f"converted {converted}, skipped {skipped} (already small enough or unreadable), "
            f"failed {failed} — {saved / 1_000_000:.1f} MB saved"
        )
