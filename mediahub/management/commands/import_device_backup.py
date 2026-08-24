"""Import a CRM device backup: base64 photos out of localStorage into S3.

The old CRM kept photos as base64 in ``localStorage['nornament_media_v4']``,
origin-scoped, existing nowhere else — iOS Safari evicts after seven days
unvisited. Phase 0's ``backupDevice()`` writes those out as JSON; this command
is what turns each file into real objects and ``MediaAsset`` rows.

Idempotent on the content hash, so running it twice for the same device, or for
two devices that both hold the same photo, imports it once.

    manage.py import_device_backup backups/preet-iphone.json
    manage.py import_device_backup backups/*.json --dry-run
"""
import base64
import binascii
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from crm.models import ClientMaterial, Customer, Enquiry, Order, Repair
from mediahub import storage
from mediahub.models import MediaAsset

#: the localStorage key prefix -> the CRM model it belongs to
SCOPES = {
    "customer": Customer,
    "order": Order,
    "enquiry": Enquiry,
    "repair": Repair,
    "clientMaterial": ClientMaterial,
    "client_material": ClientMaterial,
}
LEGACY_FIELD = {
    "customer": "legacy_id",
    "order": "legacy_id",
    "enquiry": "legacy_id",
    "repair": "legacy_id",
    "clientMaterial": "legacy_id",
    "client_material": "legacy_id",
}


class Command(BaseCommand):
    help = "Import base64 media from a CRM device backup JSON file into object storage."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+")
        parser.add_argument("--dry-run", action="store_true", help="Parse and report, upload nothing.")

    def handle(self, *args, **options):
        totals = {"items": 0, "uploaded": 0, "already": 0, "unmatched": 0, "unreadable": 0}
        for raw_path in options["paths"]:
            path = Path(raw_path)
            if not path.exists():
                raise CommandError(f"{path} does not exist")
            payload = json.loads(path.read_text())
            store = payload.get("nornament_media_v4") or payload.get("media") or payload
            if not isinstance(store, dict):
                raise CommandError(f"{path}: no media store in this file")

            self.stdout.write(f"\n{path.name}: {len(store)} entries")
            for key, items in store.items():
                scope, _, entity_legacy_id = key.partition("_")
                model = SCOPES.get(scope)
                if model is None or not isinstance(items, list):
                    continue
                owner = model.objects.filter(**{LEGACY_FIELD[scope]: entity_legacy_id}).first()
                for item in items:
                    totals["items"] += 1
                    outcome = self.import_item(scope, entity_legacy_id, owner, item, options["dry_run"])
                    totals[outcome] += 1

        for name, count in totals.items():
            self.stdout.write(f"{name:<12} {count:>6}")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("dry run — nothing uploaded"))
        if totals["unmatched"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{totals['unmatched']} item(s) belong to entities this database does not have. "
                    "Load the CRM first (manage.py load_legacy --only crm), then re-run — this command is idempotent."
                )
            )
        return None

    def import_item(self, scope, entity_legacy_id, owner, item, dry_run):
        data_url = item.get("data") or item.get("dataUrl") or item.get("src") or ""
        if not data_url.startswith("data:"):
            return "unreadable"
        header, _, encoded = data_url.partition(",")
        mime_type = header[5:].split(";", 1)[0] or "application/octet-stream"
        try:
            blob = base64.b64decode(encoded)
        except (binascii.Error, ValueError):
            return "unreadable"

        digest = storage.sha256_of(blob)
        if MediaAsset.objects.filter(sha256=digest).exists():
            return "already"
        if owner is None:
            return "unmatched"

        file_name = item.get("name") or f"{digest[:12]}.{mime_type.rsplit('/', 1)[-1]}"
        key = storage.build_key(_scope_name(scope), owner.pk, file_name)
        if dry_run:
            return "uploaded"

        try:
            storage.put_bytes(key, blob, mime_type)
        except storage.StorageNotConfigured as error:
            raise CommandError(str(error))
        MediaAsset.objects.create(
            scope=_scope_name(scope),
            scope_id=str(owner.pk),
            kind="VIDEO" if mime_type.startswith("video/") else "PHOTO",
            storage_key=key,
            file_name=file_name,
            mime_type=mime_type,
            bytes=len(blob),
            file_size_kb=int(len(blob) / 1024) or None,
            sha256=digest,
            caption=item.get("caption") or "",
            confirmed_at=timezone.now(),
        )
        return "uploaded"


def _scope_name(scope):
    return "client_material" if scope in ("clientMaterial", "client_material") else scope
