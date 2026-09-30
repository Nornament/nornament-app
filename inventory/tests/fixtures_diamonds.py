"""A diamond register in memory, shaped the way build_dia.py documents DIAMOND 31.

Columns A category · B batch · C item code · D (unused) · E size · F weight.
The pivot leaves A–C and E blank when they repeat, puts "Total" rows under
groups, and ends with unlabelled grand-total rows — the ones that once produced
a phantom 1,350 ct. Every one of those shapes is here once.
"""
import io

from openpyxl import Workbook

HEADER = ["Raw Material", "Batch No", "Item Code", "", "Size", "Weight"]

ROWS_DEFAULT = [
    ["Diamond", "", "DRFGH VS-SI", "", "0000-000", 20.13],       # Sheet!2  no batch yet
    ["", "B-771", "DRFGH VS-SI", "", "+6-12", 3.40],              # Sheet!3
    ["", "", "", "", "+2", 1.15],                                 # Sheet!4  carries B-771, DRFGH VS-SI
    ["", "", "DPCEF VVS-VS", "", "+2", 0.85],                     # Sheet!5  carries B-771
    ["Diamond Total", "", "", "", "", 25.53],                     # Sheet!6  skipped
    ["Foil Polki", "BW-1", "FPL", "", "20+", 43.21],              # Sheet!7
    ["", "", "DTRLC VS-SI", "", "TR 0.20-0.24", 0.93],            # Sheet!8  carries Foil Polki / BW-1
    ["", "", "", "", "", 1350.00],                                # Sheet!9  grand total, skipped
]


def build_workbook(rows=None):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet"
    sheet.append(HEADER)
    for row in rows if rows is not None else ROWS_DEFAULT:
        sheet.append([None if cell == "" else cell for cell in row])
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
