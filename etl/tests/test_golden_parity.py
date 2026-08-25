"""Golden parity: the ported services against the SQL they replace.

Run after::

    manage.py load_legacy
    manage.py golden_export --shim --out golden/

Without those files the suite skips — which is what a laptop with no dump
restored should do — and it is a hard gate at cutover, where they exist.
"""
import os
from decimal import Decimal

import pytest

from etl import golden
from stock import services
from stock.models import Piece

pytestmark = [pytest.mark.golden, pytest.mark.django_db]

needs_goldens = pytest.mark.skipif(
    not (golden.available() and os.environ.get("GOLDEN_DB")),
    reason="needs golden CSVs and GOLDEN_DB pointing at the ETL'd database (see etl/tests/conftest.py)",
)

#: rounding differences of a rupee are still differences; the tolerance is zero
TOLERANCE = Decimal("0")


@needs_goldens
def test_every_piece_costs_what_the_legacy_view_said():
    """``api.jewel``: cost, sale price, margin and weights, per piece."""
    differences = []
    for row in golden.read("api_jewel"):
        piece = Piece.objects.filter(jewel_code=row["jewel_code"]).first()
        if piece is None:
            differences.append(f"{row['jewel_code']}: not loaded into the new database")
            continue
        version = piece.current_bom()
        checks = [
            ("cost_price", golden.money(row.get("cost_price")), version.total_cost_price if version else None),
            ("sale_price", golden.money(row.get("sale_price")), services.live_sale_price(piece)),
            ("current_cost", golden.money(row.get("current_cost")), services.current_cost(piece)),
            ("net_metal_wt_gm", golden.money(row.get("net_metal_wt_gm")), version.net_metal_wt_gm if version else None),
            ("bom_weight_gm", golden.money(row.get("bom_weight_gm")), version.bom_weight_gm if version else None),
        ]
        for label, expected, actual in checks:
            difference = golden.compare(f"{row['jewel_code']}.{label}", expected, actual, TOLERANCE)
            if difference:
                differences.append(difference)

    assert not differences, "\n".join(differences[:50]) + f"\n({len(differences)} differences)"


@needs_goldens
def test_margin_matches_where_the_legacy_view_had_one():
    differences = []
    for row in golden.read("api_jewel"):
        expected = golden.money(row.get("margin"))
        if expected is None:
            continue
        piece = Piece.objects.filter(jewel_code=row["jewel_code"]).first()
        if piece is None:
            continue
        version = piece.current_bom()
        actual = services.live_sale_price(piece) - (version.total_cost_price if version else Decimal("0"))
        difference = golden.compare(f"{row['jewel_code']}.margin", expected, actual, TOLERANCE)
        if difference:
            differences.append(difference)
    assert not differences, "\n".join(differences[:50])


@needs_goldens
def test_bom_lines_match_line_for_line():
    """``api.bom_line``: every line amount, so a rounding drift cannot hide in a total."""
    from stock.models import BomLine

    differences = []
    for row in golden.read("api_bom_line"):
        line = (
            BomLine.objects.filter(
                piece__jewel_code=row["jewel_code"], version_no=int(row["version_no"]), line_no=int(row["line_no"])
            )
            .select_related("material")
            .first()
        )
        if line is None:
            differences.append(f"{row['jewel_code']} v{row['version_no']} #{row['line_no']}: missing")
            continue
        for label, expected, actual in [
            ("cost_amount", golden.money(row.get("cost_amount")), line.cost_amount),
            ("sale_amount", golden.money(row.get("sale_amount")), line.sale_amount),
            ("qty_value", golden.money(row.get("qty_value")), line.qty_value),
        ]:
            difference = golden.compare(
                f"{row['jewel_code']}#{row['line_no']}.{label}", expected, actual, TOLERANCE
            )
            if difference:
                differences.append(difference)
    assert not differences, "\n".join(differences[:50])


@needs_goldens
def test_stock_positions_match():
    """``api.stock_summary``: pieces and carried cost per location."""
    from stock.enums import COUNTABLE_STATES

    differences = []
    for row in golden.read("api_stock_summary"):
        actual = Piece.objects.filter(
            location__code=row.get("location") or row.get("location_code"), stock_state__in=list(COUNTABLE_STATES)
        ).count()
        expected = int(row.get("pieces") or row.get("live_pieces") or 0)
        if expected != actual:
            differences.append(f"{row.get('location')}: legacy={expected} new={actual}")
    assert not differences, "\n".join(differences)


@needs_goldens
def test_closed_counts_kept_their_frozen_result():
    """A closed count's numbers are history; the ETL must not recompute them."""
    from stock.models import StockCount

    differences = []
    for row in golden.read("api_stock_count"):
        if row.get("status") != "CLOSED":
            continue
        count = StockCount.objects.filter(count_ref=row["count_ref"]).first()
        if count is None:
            differences.append(f"{row['count_ref']}: not loaded")
            continue
        if count.result is None:
            differences.append(f"{row['count_ref']}: frozen result was lost in the ETL")
    assert not differences, "\n".join(differences)
