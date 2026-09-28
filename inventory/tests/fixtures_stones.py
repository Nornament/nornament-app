"""A stones register in memory, shaped like the owner's.

One sheet per filing family, header in row 1. Every case the importer has to
decide about is here once: a duplicate key, a batch code that does not read, a
pouch with no number, an uncountable pouch, a pouch with no rate, and a Googri
sheet that must be ignored because Googri is not a stone.
"""
import io

from openpyxl import Workbook

from inventory.importers.stones import COLUMNS

HEADERS = list(COLUMNS.values())


def _row(batch, pouch_no, stone, colour, pcs, ct, rate, **extra):
    row = {
        "New Gati Code": batch, "Batch No.": pouch_no, "Box No": extra.get("box", 3),
        "Category": "Man Made", "Stone Name": stone, "Shape": extra.get("shape", "Oval"),
        "Size Length * Width": extra.get("size", "14*10"), "Colour": colour, "Cut": "Cabachon",
        "Quality": "B", "Pcs": pcs, "Weight in Cts / Qty": ct, "Price Per Carat / Pc": rate,
        "Remarks": extra.get("remarks"),
    }
    return [row[h] for h in HEADERS]


SHEETS_DEFAULT = {
    "SL": [
        _row("SL01G", 1, "Green Onyx", "Green", 20, 12.5, 100),         # SL!2
        _row("SL01G", 2, "Ruby Glass", "Red", None, 40, 50),             # SL!3  misfiled, uncountable
        _row("SL01G", 1, "Green Onyx", "Green", 5, 2, 100),              # SL!4  duplicate of SL!2
        _row("SL02G", None, "Jade", "Green", 3, 6, 200),                 # SL!5  no pouch no.
        _row("Broken", 1, "Unknown", "Green", 1, 1, 1),                  # SL!6  batch code does not read
        _row("SL03F", 1, "Pearl", "White", 10, 5, None),                 # SL!7  no rate; box F unconfirmed
    ],
    "Googri": [_row("GG01Y", 1, "Googri", "Yellow", 1, 1, 1)],
}


def build_workbook(sheets=None):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in (sheets or SHEETS_DEFAULT).items():
        sheet = workbook.create_sheet(name)
        sheet.append(HEADERS + ["New Code"])       # a dead column the reader must ignore
        for row in rows:
            sheet.append(row + ["X"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
