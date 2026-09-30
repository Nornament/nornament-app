from decimal import Decimal

from inventory.importers import stones
from inventory.tests.fixtures_stones import build_workbook


def test_reads_the_five_stone_sheets_and_skips_googri():
    rows = stones.parse(build_workbook())
    assert [r.src for r in rows] == ["SL!2", "SL!3", "SL!4", "SL!5", "SL!6", "SL!7"]


def test_typed_values():
    first, ruby, _, jade, *_ = stones.parse(build_workbook())
    assert (first.batch, first.pouch_no, first.carton) == ("SL01G", "1", "3")
    assert (first.pcs, first.ct, first.rate) == (20, Decimal("12.5"), Decimal("100"))
    assert ruby.pcs is None                       # blank Pcs: uncountable
    assert jade.pouch_no == ""


def test_a_workbook_without_the_stone_columns_is_refused():
    from io import BytesIO
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "SL"
    book.active.append(["Jewel Code", "Gross Wt"])
    buffer = BytesIO()
    book.save(buffer)
    buffer.seek(0)
    assert stones.header_problems(buffer)
    assert stones.header_problems(build_workbook()) == []
