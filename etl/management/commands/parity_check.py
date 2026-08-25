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
    "app.media_asset": ("media_asset", [], ["uploaded_at"]),
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
        became rows. Count and sum them out of the JSONB so the unnesting is
        checked rather than assumed.
        """
        from stock.models import Sale

        expected_rows = expected_sum = 0
        for row in legacy.rows("SELECT data FROM public.customers"):
            from etl.crm_shapes import purchases_from_blob

            for purchase in purchases_from_blob(_blob(row)):
                expected_rows += 1
                expected_sum += purchase["sold_price"]

        actual = Sale.objects.filter(source=Sale.CRM)
        actual_rows = actual.count()
        actual_sum = sum((sale.sold_price for sale in actual), Decimal("0"))
        if expected_rows != actual_rows or Decimal(expected_sum) != Decimal(actual_sum):
            self.stderr.write(
                f"CRM purchases: legacy arrays={expected_rows} rows / {expected_sum}; "
                f"new sale rows={actual_rows} / {actual_sum}"
            )
            sys.exit(1)
        self.stdout.write(f"ok  crm purchases -> sale       {actual_rows:>8} rows, {actual_sum}")

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
