"""Reading the IVY export.

The rule most likely to break is that the five material bands run down a
block independently — a stone line on row 3 of a block is not related to the
diamond line on row 1. These tests exist mostly to keep that true.
"""
from decimal import Decimal

from stock.importers import ivy
from stock.tests.fixtures_ivy import build_workbook


def test_blocks_start_where_style_no_is_filled():
    pieces = ivy.parse(build_workbook())
    assert [p.jewel_code for p in pieces] == ["24P00088", "24P00111", "24P00095"]
    assert [p.row_no for p in pieces] == [4, 5, 8]


def test_header_fields_come_off_the_parent_row():
    first = ivy.parse(build_workbook())[0]
    assert first.style_code == "ER00502"
    assert first.category == "Earring"
    assert first.collection == "Norna"
    assert first.vendor == "Infinity Venture [IVY]"
    assert first.metal_purity == "18K"
    assert first.diamond_quality == "FGH VS-SI"
    # 'Finish Goods' is normalised to the value the model expects
    assert first.stock_type == "FINISH_GOODS"


def test_misc_remarks_is_read_as_the_fg_date():
    """Column Q is labelled 'Misc Remarks' but the export puts a date in it."""
    first = ivy.parse(build_workbook())[0]
    assert first.fg_date.year == 2025
    assert first.fg_date.month == 11
    assert first.fg_date.day == 7


def test_bands_are_read_independently_down_the_block():
    """The ragged product: 3 diamond, 1 metal, 2 stone lines."""
    ragged = ivy.parse(build_workbook())[1]
    by_band = {}
    for line in ragged.lines:
        by_band.setdefault(line.band, []).append(line)
    assert len(by_band["diamond"]) == 3
    assert len(by_band["metal"]) == 1
    assert len(by_band["stone"]) == 2
    # the stone on block-row 2 must not have been dropped when metal ran out
    assert [s.code for s in by_band["stone"]] == ["SP01C", "PS01W"]
    assert [d.code for d in by_band["diamond"]] == [
        "DRIJ SI-I", "FPL", "DRFGH SI-I",
    ]


def test_line_figures_keep_their_precision():
    ragged = ivy.parse(build_workbook())[1]
    metal = next(l for l in ragged.lines if l.band == "metal")
    assert metal.code == "G14K"
    assert metal.qty == Decimal("8.228")      # net weight, not gross
    assert metal.cost_rate == Decimal("4319")
    stone = next(l for l in ragged.lines if l.code == "PS01W")
    assert stone.pcs == 2
    assert stone.qty == Decimal("44.5")
    assert stone.sale_rate == Decimal("90")


def test_totals_and_source_figures_come_off_the_parent_row():
    ragged = ivy.parse(build_workbook())[1]
    assert ragged.src_cost_price == Decimal("84438")
    assert ragged.src_sale_price == Decimal("227427.18")
    assert ragged.src_net_wt_gm == Decimal("8.228")


def test_charge_lines_are_read_from_the_last_band():
    first = ivy.parse(build_workbook())[0]
    charge = next(l for l in first.lines if l.band == "charge")
    assert charge.code == "EC"
    assert charge.name == "Extra Charges"
    assert charge.sale_amount == Decimal("5400")


def test_a_workbook_with_the_wrong_headers_is_rejected():
    from openpyxl import load_workbook
    stream = build_workbook()
    book = load_workbook(stream)
    book["Sheet1"]["D3"] = "Some Other Column"
    import io
    broken = io.BytesIO()
    book.save(broken)
    broken.seek(0)
    problems = ivy.header_problems(broken)
    assert problems
    assert "JewelCode" in problems[0]


def test_a_correct_workbook_has_no_header_problems():
    assert ivy.header_problems(build_workbook()) == []


def test_the_footer_row_does_not_leak_into_the_last_block():
    """The last block runs to EOF, so the export footer sits inside its range."""
    last = ivy.parse(build_workbook())[-1]
    assert last.jewel_code == "24P00095"
    assert len(last.lines) == 2          # one diamond, one metal — and no footer
