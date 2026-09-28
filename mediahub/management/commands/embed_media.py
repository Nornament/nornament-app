"""Give every piece photo already in the bucket its "Identify piece" vector.

New uploads are embedded as they are confirmed. This is the other half: the
photos from before, and anything a bulk import brought in. It is safe to stop
and re-run — an embedded row is skipped next pass because its column is no
longer null.
"""
from django.core.management.base import BaseCommand

from mediahub import storage
from stock import identify


class Command(BaseCommand):
    help = "Embed piece photos that have no vector yet, for photo search."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Count what would be embedded and stop.")
        parser.add_argument("--limit", type=int, default=0, help="Stop after this many.")

    def handle(self, *args, **options):
        pending = identify.searchable_photos().filter(embedding__isnull=True).order_by("media_id")
        total = pending.count()
        if options["limit"]:
            pending = pending[: options["limit"]]

        if options["dry_run"]:
            self.stdout.write(f"{total} piece photo(s) have no vector yet.")
            return
        if not total:
            self.stdout.write("Nothing to embed — every piece photo is searchable.")
            return

        embedded = failed = 0
        for asset in pending:
            try:
                identify.embed_asset(asset)
            except (storage.StorageNotConfigured, identify.ModelMissing) as error:
                raise SystemExit(f"Cannot embed on this server: {error}")
            except Exception as error:  # noqa: BLE001 — one bad object must not stop the run
                failed += 1
                self.stderr.write(f"{asset.media_ref or asset.pk}: {error}")
                continue
            embedded += 1

        self.stdout.write(f"embedded {embedded}, failed {failed}, of {total} waiting")
