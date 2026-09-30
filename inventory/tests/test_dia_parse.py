from decimal import Decimal

from inventory.importers import diamonds
from inventory.tests.fixtures_diamonds import build_workbook


def test_the_pivot_unrolls_into_lines():
    rows = diamonds.parse(build_workbook())
    assert [r.src for r in rows] == ["Sheet!2", "Sheet!3", "Sheet!4", "Sheet!5", "Sheet!7", "Sheet!8"]
    first, second, carried, recoded, polki, trillion = rows
    assert (first.category, first.batch_no, first.item_code, first.size_text, first.ct) == (
        "Natural Diamond", "", "DRFGH VS-SI", "0000-000", Decimal("20.13"))
    assert (carried.batch_no, carried.item_code, carried.size_text) == ("B-771", "DRFGH VS-SI", "+2")
    assert (recoded.batch_no, recoded.item_code) == ("B-771", "DPCEF VVS-VS")
    assert (polki.category, trillion.category, trillion.batch_no) == ("Foil Polki", "Foil Polki", "BW-1")


def test_totals_never_become_stock():
    assert sum(r.ct for r in diamonds.parse(build_workbook())) == Decimal("69.67")


def test_a_workbook_that_is_not_the_register_is_refused():
    from io import BytesIO
    from openpyxl import Workbook

    book = Workbook()
    book.active.append(["Jewel Code", "Gross Wt"])
    buffer = BytesIO()
    book.save(buffer)
    buffer.seek(0)
    assert diamonds.header_problems(buffer)
    assert diamonds.header_problems(build_workbook()) == []
