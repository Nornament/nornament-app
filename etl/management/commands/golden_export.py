"""Dump the legacy ``api`` views to CSV, unmasked, as the golden output.

The trick that makes the goldens complete is one line of SQL in the throwaway
legacy database::

    CREATE OR REPLACE FUNCTION app.has_cap(p_cap text) RETURNS boolean
      AS $$ SELECT true $$ LANGUAGE sql;

(The parameter must keep its name: Postgres refuses to rename an input
parameter through CREATE OR REPLACE, and dropping the function would take the
views with it.)

Every ``api`` view wraps its sensitive columns in ``CASE WHEN app.has_cap(...)``,
so with that shim in place the views emit the real numbers rather than nulls,
and the golden files cover costing and margin instead of stopping at the gate.
``--shim`` applies it; it is refused unless the target really is the legacy
database, because running it anywhere else would disable masking.

    manage.py golden_export --shim --out golden/
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from etl import legacy

VIEWS = [
    "api.jewel",
    "api.bom_line",
    "api.movement",
    "api.stock_summary",
    "api.sale_breakup",
    "api.stock_count",
    "api.rate_chart_line",
    "api.metal_purity",
    "api.material",
]


class Command(BaseCommand):
    help = "Export the legacy api views to CSV for the golden parity tests."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="golden", help="Directory to write the CSV files into.")
        parser.add_argument(
            "--shim",
            action="store_true",
            help="Make app.has_cap() return true in the legacy database so the views emit unmasked rows.",
        )
        parser.add_argument("--view", action="append", dest="views")

    def handle(self, *args, **options):
        try:
            connection = legacy.connection()
        except legacy.LegacyUnavailable as error:
            raise CommandError(str(error))

        if options["shim"]:
            self.apply_shim(connection)

        out = Path(options["out"])
        out.mkdir(parents=True, exist_ok=True)
        for view in options.get("views") or VIEWS:
            if not legacy.table_exists(view):
                self.stdout.write(self.style.WARNING(f"{view} is not in the dump — skipped"))
                continue
            target = out / f"{view.replace('.', '_')}.csv"
            with connection.cursor() as cursor, target.open("w", newline="") as handle:
                self.copy_out(cursor, f"COPY (SELECT * FROM {view}) TO STDOUT WITH CSV HEADER", handle)
            self.stdout.write(f"{view:<24} → {target}")
        self.stdout.write(self.style.SUCCESS("golden_export finished"))

    def copy_out(self, cursor, sql, handle):
        """COPY through psycopg3, falling back to psycopg2's copy_expert."""
        raw = getattr(cursor, "cursor", cursor)
        if hasattr(raw, "copy"):
            with raw.copy(sql) as copy:
                for chunk in copy:
                    handle.write(bytes(chunk).decode())
        else:  # pragma: no cover - psycopg2 only
            raw.copy_expert(sql, handle)

    def apply_shim(self, connection):
        """Only ever in the throwaway legacy database, and it says so out loud."""
        name = connection.settings_dict["NAME"]
        if "legacy" not in name.lower():
            raise CommandError(
                f"--shim would disable capability checks in {name!r}. It is only for the throwaway "
                "legacy database, whose name must contain 'legacy'."
            )
        with connection.cursor() as cursor:
            # the parameter name is load-bearing: CREATE OR REPLACE cannot
            # rename one, and DROP would cascade to every api view
            cursor.execute(
                "CREATE OR REPLACE FUNCTION app.has_cap(p_cap text) RETURNS boolean "
                "LANGUAGE sql AS $$ SELECT true $$"
            )
        self.stdout.write(self.style.WARNING(f"app.has_cap() now returns true in {name} — views are unmasked"))
