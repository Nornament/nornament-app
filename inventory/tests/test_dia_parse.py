from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook

from inventory.importers import diamonds
from inventory.tests.fixtures_diamonds import build_workbook


def _rows():
    return {r.src: r for r in diamonds.parse(build_workbook())}


def test_three_sheets_are_read_and_fancy_is_not():
    assert list(_rows()) == ["FANCY FINAL!2", "FANCY FINAL!3", "FANCY FINAL!4", "FANCY FINAL!5", "FANCY FINAL!6",
                             "Round_LB_LC!2", "Round_LB_LC!3", "Round_LB_LC!7",
                             "Round_RW!2", "Round_RW!3", "Round_RW!4"]


def test_totals_never_become_stock():
    assert sum(r.ct for r in diamonds.parse(build_workbook())) == Decimal("104.02")


def test_a_carat_band_code_is_a_band_and_a_blank_code_does_not_carry_down():
    rows = _rows()
    band, blank = rows["FANCY FINAL!3"], rows["FANCY FINAL!4"]
    assert (band.batch_no, band.band_text, band.size_text) == ("", "M 0.10-0.15", "2.3*1.3 - 3.5*2.3")
    assert (blank.batch_no, blank.band_text) == ("", "")
    assert rows["FANCY FINAL!5"].batch_no == "TB1.1"


def test_columns_are_mapped_onto_the_master_lists():
    rows = _rows()
    marquise = rows["FANCY FINAL!3"]
    assert (marquise.item_code, marquise.shape, marquise.colour, marquise.clarity, marquise.pcs, marquise.rate) == (
        "DMIJ VVS VS", "Marquise", "I-J", "VVS-VS", 6, Decimal("32200"))
    lc = rows["FANCY FINAL!4"]
    assert (lc.item_code, lc.colour, lc.clarity) == ("DMLC SI I", "K-L", "SI-I")
    taper = rows["FANCY FINAL!5"]
    assert (taper.shape, taper.size_text, taper.pcs) == ("Tapered Baguette", "-2BG", None)
    fancy = rows["FANCY FINAL!6"]
    assert (fancy.shape, fancy.colour, fancy.clarity) == ("Mix", "Fancy Yellow", "")
    assert {r.category for r in rows.values()} == {"Natural Diamond"}


def test_the_round_sheets():
    rows = _rows()
    lb, bare, lc = rows["Round_LB_LC!2"], rows["Round_LB_LC!3"], rows["Round_LB_LC!7"]
    assert (lb.batch_no, lb.item_code, lb.size_text, lb.colour, lb.rate) == (
        "LB1.01", "DRMN VVS VS", "0-1", "M-N", Decimal("20000"))        # the swapped headers do not fool it
    assert bare.size_text == "+10"
    assert (lc.batch_no, lc.size_text, lc.clarity, lc.colour) == ("LC3.1", "+1", "VS-SI", "K-L")
    rw, zero = rows["Round_RW!2"], rows["Round_RW!4"]
    assert (rw.item_code, rw.batch_no, rw.size_text, rw.colour, rw.rate) == (
        "DREF VVS VS", "RW1", "+0000", "E-F", Decimal("42000"))
    assert (zero.item_code, zero.ct, zero.rate) == ("DRGH VVS VS", Decimal("0.00"), Decimal("31500"))


def test_a_workbook_that_is_not_the_register_is_refused():
    book = Workbook()
    book.active.append(["Jewel Code", "Gross Wt"])
    buffer = BytesIO()
    book.save(buffer)
    buffer.seek(0)
    assert diamonds.header_problems(buffer)
    assert diamonds.header_problems(build_workbook()) == []
