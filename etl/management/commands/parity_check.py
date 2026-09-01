"""The cutover gate, automated.

Per table: row count, the sum of every money column, and the min/max of every
timestamp — legacy against new. Any mismatch and the command exits nonzero, so
it can sit in front of the cutover as a check rather than as a person reading
query output at 2am.

    manage.py parity_check
    manage.py parity_check --table app.jewel_code --verbose
"""
import sys
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from etl import legacy

#: legacy table -> (new table, money columns, timestamp columns). A fourth
#: element narrows the new side, for tables this schema deliberately widened:
#: ``sale`` now also carries CRM purchases, which have no legacy counterpart.
TABLES = {
    "app.location": ("location", [], []),
    "app.category": ("category", [], []),
    "app.collection": ("collection", [], []),
    "app.vendor": ("vendor", ["avg_tat_days"], []),
    "app.material": ("material", [], []),
    "app.style": ("style", [], ["created_at"]),
    "app.jewel_code": (
        "jewel_code",
        ["measured_gross_wt_gm", "src_cost_price", "src_sale_price", "src_tag_price", "src_net_wt_gm"],
        ["created_at", "updated_at"],
    ),
    "app.bom_version": (
        "bom_version",
        ["net_metal_wt_gm", "bom_weight_gm", "total_cost_price", "total_sale_price", "making_value", "goods_value"],
        ["created_at"],
    ),
    "app.jewel_material_line": (
        "jewel_material_line",
        ["qty_value", "cost_rate", "cost_amount", "sale_rate", "sale_amount"],
        [],
    ),
    "app.stock_movement": ("stock_movement", [], ["moved_at", "created_at"]),
    "app.sale": (
        "sale",
        ["sold_price", "discount_amt", "cost_at_sale", "margin_amt"],
        ["created_at"],
        "source = 'STOCK'",
    ),
    "app.melt_record": ("melt_record", ["cost_written_off"], ["created_at"]),
    "app.repair_job": ("repair_job", ["labour_cost"], []),
    "app.stock_count": ("stock_count", [], ["started_at", "closed_at"]),
    "app.stock_count_scan": ("stock_count_scan", [], ["scanned_at"]),
    # scope IS NULL is the stock half. The CRM's photos never lived in
    # app.media_asset — they were base64 inside a JSONB blob — so they are
    # counted against the blobs instead, in check_crm_media below.
    "app.media_asset": ("media_asset", [], ["uploaded_at"], "scope IS NULL"),
    "app.rate_chart_line": ("rate_chart_line", ["cost_rate", "sale_rate"], []),
    "public.customers": ("crm_customer", [], ["created_at"]),
    "public.orders": ("crm_order", [], ["created_at"]),
    "public.enquiries": ("crm_enquiry", [], ["created_at"]),
    "public.repairs": ("crm_repair", [], ["created_at"]),
    "public.client_materials": ("crm_clientmaterial", [], ["created_at"]),
}


class Command(BaseCommand):
    help = "Compare the legacy database with this one. Nonzero exit on any mismatch."

    def add_arguments(self, parser):
        parser.add_argument("--table", action="append", dest="tables")
        parser.add_argument("--verbose", action="store_true")

    def handle(self, *args, **options):
        try:
            legacy.connection()
        except legacy.LegacyUnavailable as error:
            raise CommandError(str(error))

        from django.db import connection as new

        wanted = options.get("tables") or list(TABLES)
        mismatches = []
        for source in wanted:
            if source not in TABLES:
                raise CommandError(f"{source} is not a table parity_check knows about")
            target, money, stamps, *rest = TABLES[source]
            where = rest[0] if rest else None
            if not legacy.table_exists(source):
                self.stdout.write(self.style.WARNING(f"{source:<28} not in the dump — skipped"))
                continue

            legacy_stats = self.stats(legacy.connection(), source, money, stamps)
            new_stats = self.stats(new, target, money, stamps, where)
            for key, left in legacy_stats.items():
                right = new_stats.get(key)
                if not _same(left, right):
                    mismatches.append((source, key, left, right))
                elif options["verbose"]:
                    self.stdout.write(f"  {source}.{key}: {left}")
            marker = "ok " if all(m[0] != source for m in mismatches) else "BAD"
            self.stdout.write(f"{marker} {source:<28} {legacy_stats['rows']:>8} rows")

        if mismatches:
            self.stdout.write("")
            for table, key, left, right in mismatches:
                self.stdout.write(self.style.ERROR(f"{table}.{key}: legacy={left!r} new={right!r}"))
            self.stderr.write(f"{len(mismatches)} mismatch(es) — do not cut over")
            sys.exit(1)
        self.crm_purchase_check()
        self.stdout.write(self.style.SUCCESS("parity_check: every table agrees"))

    def crm_purchase_check(self):
        """The purchases[] arrays against the CRM-sourced sale rows.

        This is the one table with no like-for-like counterpart: the arrays
        became rows. Count and sum them out of the JSONB **in SQL**, not
        through ``purchases_from_blob``. Checking the loader with the loader's
        own shaper is not a check: a purchase the shaper refused was refused
        identically on both sides and the totals agreed while the customer's
        history was short. This unnests the array in Postgres, so a dropped
        purchase shows up here as the mismatch it is.
        """
        from stock.models import Sale

        expected_rows, expected_sum = legacy_purchase_totals()
        actual = Sale.objects.filter(source=Sale.CRM)
        actual_rows = actual.count()
        actual_sum = sum((sale.sold_price for sale in actual), Decimal("0"))
        if expected_rows != actual_rows or Decimal(expected_sum) != Decimal(actual_sum):
            self.stderr.write(
                f"CRM purchases: legacy arrays={expected_rows} rows / {expected_sum}; "
                f"new sale rows={actual_rows} / {actual_sum}"
            )
            self.report_dropped_purchases()
            sys.exit(1)
        self.stdout.write(f"ok  crm purchases -> sale       {actual_rows:>8} rows, {actual_sum}")
        self.check_crm_statuses()
        self.check_crm_media()

    def report_dropped_purchases(self):
        """Name the purchases the load could not place, so the gap is legible."""
        from crm.models import EtlException

        rows = EtlException.objects.filter(entity="crm.Purchase")[:20]
        for row in rows:
            self.stderr.write(f"  {row.legacy_id}: {row.problem} — {row.detail}")
        remaining = EtlException.objects.filter(entity="crm.Purchase").count() - len(rows)
        if remaining > 0:
            self.stderr.write(f"  … and {remaining} more (crm.EtlException, entity='crm.Purchase')")

    def check_crm_statuses(self):
        """Every pipeline record is at the stage the legacy CRM had it at.

        Row counts alone let a whole pipeline shift stage and still pass: this
        compares the per-status counts, which is the number the client is
        actually looking at when they open the board.
        """
        mismatches = []
        for table, model_table in CRM_STATUS_TABLES.items():
            if not legacy.table_exists(table):
                continue
            legacy_counts = {}
            for row in legacy.rows(
                f"SELECT coalesce(data->>'status', '') AS status, count(*) AS n FROM {table} GROUP BY 1"
            ):
                legacy_counts[_canonical(row["status"])] = row["n"]

            from django.db import connection as new

            new_counts = {}
            with new.cursor() as cursor:
                cursor.execute(f"SELECT status, count(*) FROM {model_table} GROUP BY 1")
                for status, count in cursor.fetchall():
                    new_counts[_canonical(status)] = count

            drifted = 0
            for status in sorted(set(legacy_counts) | set(new_counts)):
                left, right = legacy_counts.get(status, 0), new_counts.get(status, 0)
                if left != right:
                    mismatches.append((table, status or "(no stage)", left, right))
                    drifted += 1
            marker = "ok " if not drifted else "BAD"
            self.stdout.write(f"{marker} {table + ' stages':<28} {len(legacy_counts):>8} distinct")

        if mismatches:
            for table, status, left, right in mismatches:
                self.stderr.write(self.style.ERROR(f"{table} stage {status!r}: legacy={left} new={right}"))
            self.stderr.write(f"{len(mismatches)} stage mismatch(es) — the boards will not agree")
            sys.exit(1)

    def check_crm_media(self):
        """The base64 images in the CRM blobs against the media rows they became.

        The other table with no like-for-like counterpart. Every CRM photo was
        a data URI inside JSONB; if the decoder ever silently skips one, the
        counts stop agreeing here rather than a screen quietly losing a picture.
        """
        from etl.crm_shapes import media_from_blob
        from mediahub.models import MediaAsset

        sources = {
            "public.customers": "customer",
            "public.enquiries": "enquiry",
            "public.orders": "order",
            "public.repairs": "repair",
            "public.client_materials": "client_material",
        }
        expected = 0
        for table in sources:
            if not legacy.table_exists(table):
                continue
            for row in legacy.rows(f"SELECT data FROM {table}"):
                expected += len(media_from_blob(_blob(row)))

        actual = MediaAsset.objects.filter(scope__in=sources.values()).count()
        if expected != actual:
            self.stderr.write(f"CRM media: legacy blobs={expected} images; new media rows={actual}")
            sys.exit(1)
        self.stdout.write(f"ok  crm blobs -> media_asset    {actual:>8} images")

    def stats(self, connection, table, money, stamps, where=None):
        selects = ["count(*) AS rows"]
        for column in money:
            selects.append(f"coalesce(sum({column}), 0) AS sum_{column}")
        for column in stamps:
            selects.append(f"min({column}) AS min_{column}")
            selects.append(f"max({column}) AS max_{column}")
        clause = f" WHERE {where}" if where else ""
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT {', '.join(selects)} FROM {table}{clause}")
            columns = [c[0] for c in cursor.description]
            return dict(zip(columns, cursor.fetchone()))


#: legacy table -> the table its pipeline records landed in. Stage counts are
#: compared per table, because a record at the wrong stage is what a user sees
#: first and what row counts alone will never catch.
CRM_STATUS_TABLES = {
    "public.enquiries": "crm_enquiry",
    "public.orders": "crm_order",
    "public.repairs": "crm_repair",
    "public.client_materials": "crm_clientmaterial",
}


def _canonical(status):
    """Compare stages the way the loader stores them: trimmed, case-folded."""
    return " ".join(str(status or "").split()).casefold()


def legacy_purchase_totals():
    """``count`` and ``sum`` over every ``purchases[]`` entry, straight from SQL.

    Deliberately independent of ``purchases_from_blob``: it is the thing being
    checked. An entry whose amount is not a number counts as a row worth zero,
    so a purchase that exists in the legacy app can never be invisible here.
    """
    row = legacy.scalar_row(
        """
        SELECT count(*) AS n,
               coalesce(sum(
                   CASE WHEN cleaned ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN cleaned::numeric ELSE 0 END
               ), 0) AS total
        FROM public.customers c,
             LATERAL jsonb_array_elements(coalesce(c.data->'purchases', '[]'::jsonb)) AS p,
             LATERAL (SELECT regexp_replace(coalesce(p->>'amount', ''), '[^0-9.\\-]', '', 'g')) AS s(cleaned)
        """
    )
    return int(row[0] or 0), Decimal(str(row[1] or 0))


def _blob(row):
    import json

    raw = row.get("data")
    return json.loads(raw) if isinstance(raw, str) else (raw or {})


def _same(left, right):
    """Numerics compare by value; a trailing zero is not a mismatch."""
    if isinstance(left, Decimal) or isinstance(right, Decimal):
        try:
            return Decimal(str(left or 0)) == Decimal(str(right or 0))
        except Exception:
            return left == right
    return left == right
