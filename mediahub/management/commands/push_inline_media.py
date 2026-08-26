"""Move media held on the row into object storage.

The CRM kept its photos as base64 inside a JSONB blob, so they arrive from
``load_legacy`` with their bytes in ``MediaAsset.inline_data`` and no object
behind them. This uploads each one under the normal key scheme, verifies it is
really there, and only then clears the column — so an interrupted run leaves
rows that still serve, and re-running finishes the job.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from mediahub import storage
from mediahub.models import MediaAsset


class Command(BaseCommand):
    help = "Upload MediaAsset rows whose bytes are still in the database."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Count them and stop.")
        parser.add_argument("--limit", type=int, default=0, help="Stop after this many.")

    def handle(self, *args, **options):
        pending = MediaAsset.objects.exclude(inline_data=None).exclude(inline_data=b"").order_by("media_id")
        total = pending.count()
        if options["limit"]:
            pending = pending[: options["limit"]]

        if options["dry_run"]:
            self.stdout.write(f"{total} asset(s) still carry their bytes.")
            return
        if not total:
            self.stdout.write("Nothing to push — every asset is in the bucket.")
            return

        pushed = failed = 0
        for asset in pending:
            payload = bytes(asset.inline_data)
            key = asset.storage_key or storage.build_key(
                asset.scope or "piece", asset.scope_id or asset.piece_id, asset.file_name or f"{asset.media_ref}.bin"
            )
            try:
                storage.put_bytes(key, payload, asset.mime_type or storage.guess_mime(asset.file_name or ""))
                storage.head(key)  # it is only uploaded when the bucket agrees
            except storage.StorageNotConfigured as error:
                raise SystemExit(f"Media storage is not configured: {error}")
            except Exception as error:  # noqa: BLE001 — one bad object must not stop the run
                failed += 1
                self.stderr.write(f"{asset.media_ref or asset.pk}: {error}")
                continue
            with transaction.atomic():
                asset.storage_key = key
                asset.storage_provider = "CONTABO"
                asset.inline_data = None
                asset.save(update_fields=["storage_key", "storage_provider", "inline_data"])
            pushed += 1

        self.stdout.write(f"pushed {pushed}, failed {failed}, {total - pushed} still on the row")
