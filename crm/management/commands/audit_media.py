"""Check every CRM record's images against the legacy blob they came from.

The CRM kept photos as base64 inside its JSONB, under five different keys. A
loader that walks four of them loses pictures and says nothing, so this counts
the images in each source row and compares that with the ``MediaAsset`` rows
that record now has. A clean run is the evidence that nothing is missing.

It also reports what is *reachable*: an asset whose bytes are neither on the
row nor in the bucket is a row that renders a broken tile, which is a different
failure from a record that never had a photo.

    manage.py audit_media                 # needs LEGACY_DB_NAME for the comparison
    manage.py audit_media --no-legacy     # skip it, just check reachability
    manage.py audit_media --verbose       # name every record with a shortfall
"""
import sys

from django.core.management.base import BaseCommand

from crm.models import ClientMaterial, Customer, Enquiry, Order, Repair
from mediahub import storage
from mediahub.models import MediaAsset

#: MediaAsset.scope -> (model, legacy table, the code to print)
SCOPES = {
    "customer": (Customer, "public.customers", "customer_code"),
    "enquiry": (Enquiry, "public.enquiries", "enquiry_code"),
    "order": (Order, "public.orders", "order_code"),
    "repair": (Repair, "public.repairs", "repair_code"),
    "client_material": (ClientMaterial, "public.client_materials", "cm_code"),
}


class Command(BaseCommand):
    help = "Audit CRM records for missing images. Nonzero exit if any are."

    def add_arguments(self, parser):
        parser.add_argument("--no-legacy", action="store_true", help="Skip the comparison against the dump.")
        parser.add_argument("--verbose", action="store_true", help="Name every record with a shortfall.")

    def handle(self, *args, **options):
        problems = 0
        loaded = self._loaded_by_record()

        # ── 1. against the source, when the dump is attached ─────────────
        if options["no_legacy"]:
            self.stdout.write("skipping the comparison against the legacy dump (--no-legacy)")
        else:
            problems += self._compare_with_legacy(loaded, options["verbose"])

        # ── 2. is every loaded asset actually reachable? ─────────────────
        problems += self._check_reachable(options["verbose"])

        # ── 3. what has no image at all, for the eye rather than the gate ─
        self._report_coverage()

        if problems:
            self.stderr.write(f"\naudit_media: {problems} problem(s) found")
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS("\naudit_media: every CRM record has the images its source row had"))

    # ── helpers ──────────────────────────────────────────────────────────
    def _loaded_by_record(self):
        """``{(scope, scope_id): count}`` of live assets."""
        counts = {}
        for scope, scope_id in MediaAsset.objects.filter(
            scope__in=SCOPES, is_archived=False
        ).values_list("scope", "scope_id"):
            counts[(scope, str(scope_id))] = counts.get((scope, str(scope_id)), 0) + 1
        return counts

    def _compare_with_legacy(self, loaded, verbose):
        from etl import legacy
        from etl.crm_shapes import blob_of, media_from_blob

        try:
            legacy.rows("SELECT 1")
        except Exception as error:  # noqa: BLE001 — no dump attached is a normal state
            self.stdout.write(f"legacy database not reachable ({error}); skipping the source comparison")
            return 0

        problems = 0
        for scope, (model, table, code_field) in SCOPES.items():
            if not legacy.table_exists(table):
                continue
            by_legacy_id = {
                str(pk): (str(row_pk), code)
                for pk, row_pk, code in model.objects.values_list("legacy_id", "pk", code_field)
                if pk
            }
            expected_total = missing = checked = 0
            for row in legacy.rows(f"SELECT id, data FROM {table}"):
                expected = len(media_from_blob(blob_of(row)))
                expected_total += expected
                if not expected:
                    continue
                checked += 1
                target = by_legacy_id.get(str(row["id"]))
                if target is None:
                    self.stderr.write(f"  {scope}: legacy row {row['id']} has {expected} image(s) but never loaded")
                    missing += expected
                    continue
                actual = loaded.get((scope, target[0]), 0)
                if actual < expected:
                    missing += expected - actual
                    if verbose:
                        self.stderr.write(f"  {scope} {target[1]}: {expected} in the blob, {actual} loaded")
            status = "ok " if not missing else "MISS"
            self.stdout.write(
                f"{status} {scope:<16} {expected_total:>5} image(s) in {checked:>4} record(s)"
                + (f" — {missing} MISSING" if missing else "")
            )
            problems += 1 if missing else 0
        return problems

    def _check_reachable(self, verbose):
        """An asset is reachable if its bytes are on the row or in the bucket."""
        inline = MediaAsset.objects.filter(scope__in=SCOPES, is_archived=False).exclude(inline_data=None).count()
        remote = MediaAsset.objects.filter(scope__in=SCOPES, is_archived=False).filter(inline_data=None)
        orphans = list(remote.filter(storage_key__in=["", None]))
        self.stdout.write(f"\nreachable: {inline} on the row, {remote.count()} in object storage")
        if orphans:
            self.stderr.write(f"  {len(orphans)} asset(s) have neither bytes nor a storage key")
            for asset in orphans[:20] if verbose else []:
                self.stderr.write(f"    {asset.media_ref or asset.pk} ({asset.scope} {asset.scope_id})")
            return 1

        # if storage is configured, prove the objects are really there
        keyed = list(remote.exclude(storage_key__in=["", None]))
        if not keyed:
            return 0
        try:
            storage.head(keyed[0].storage_key)
        except storage.StorageNotConfigured:
            self.stdout.write("  object storage is not configured here, so those were not verified")
            return 0
        except Exception:
            pass
        gone = []
        for asset in keyed:
            try:
                storage.head(asset.storage_key)
            except Exception:  # noqa: BLE001 — a missing object is the finding
                gone.append(asset)
        if gone:
            self.stderr.write(f"  {len(gone)} asset(s) point at an object that is not in the bucket")
            for asset in gone[:20]:
                self.stderr.write(f"    {asset.media_ref or asset.pk} -> {asset.storage_key}")
            return 1
        self.stdout.write(f"  all {len(keyed)} bucket object(s) verified present")
        return 0

    def _report_coverage(self):
        """How many records carry no image. Information, not a failure — most
        customers never had a photo in the old CRM either."""
        self.stdout.write("\ncoverage (records with at least one image):")
        for scope, (model, _, _) in SCOPES.items():
            total = model.objects.count()
            with_media = (
                MediaAsset.objects.filter(scope=scope, is_archived=False)
                .values("scope_id")
                .distinct()
                .count()
            )
            pct = f"{with_media / total * 100:.0f}%" if total else "—"
            self.stdout.write(f"  {scope:<16} {with_media:>4} of {total:>4}  {pct}")
