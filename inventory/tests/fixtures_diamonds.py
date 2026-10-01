"""A diamond register in memory, shaped like the owner's Dia_Stock_Nitesh.xlsx.

Three sheets are read (FANCY FINAL, Round_LB_LC and Round_RW) and FANCY is not.
Every awkward shape of the real file is here once: a blank Code that must not
carry down, a carat-band Code, Round_LB_LC's swapped Amount/PRICE headers and
its repeated header, bare sieve numbers, a Round_RW row with no item code at
zero carats, and the total rows.
"""
import io

from openpyxl import Workbook

from inventory import dia_services

FANCY_HEADER = ["Code", "Shape", "Gati Code", "Colour", "Clarity", "Seive/Size", "Pieces", "Weight", "Rate", "Amount",
                "REMARKS"]
FANCY_ROWS = [
    [None, "Emerald", "DEMREF VVS VS", "EF", "VVS VS", "2.7*2.1 - 2.9*1.8", 2, 0.14, 42000, 5880],             # !2
    ["M0.10-0.15", "Marquise", "DMIJ VVS VS ", "IJ", "VVS VS", "2.3*1.3 - 3.5*2.3", 6, 0.31, 32200, 9982],     # !3
    [None, "Marquise", "DMLC SI  I", "LC", "SI  I", "2.8*1.75 - 4.2*2.1", 3, 0.22, 35700, 7854],               # !4
    ["TB1.1", "Tapers Buggutte", "DTBEF VVS VS", "EF", "VVS VS", "-2BG", None, 14.86, 32000, 475520],          # !5
    ["FCD.20", "Mix Shapes", "DFY", "Yellow  ", "Fancy", None, None, 80.13, 25000, 2003250, "Average Price"],  # !6
    [None, None, None, None, None, None, None, None, None, 2502493],                                           # !7 total
]
LB_HEADER = ["Code", "Seive", "GATI CODE ", "COLOUR", "CLARITY", "WEIGHT", "Amount", "PRICE"]
LB_ROWS = [
    ["LB1.01", "0-1", "DRMN VVS VS", "MN", "VVS VS ", 0.67, 20000, 13400],     # !2  Amount is the rate here
    ["LB1.10", 10, "DRMN VVS VS", "MN", "VVS VS ", 0.22, 16000, 3520],         # !3  a bare sieve number
    ["Total=", None, None, None, None, None, None, 16920],                    # !4
    [],                                                                        # !5
    LB_HEADER,                                                                 # !6  the header again
    ["LC3.1 ", 1, "DRKL VS SI", "KL", "VS SI", 0.12, 15500, 1860],             # !7
]
RW_HEADER = ["Code", "Seive", "Colour", "Clarity", "Weight", "Rate", "Amount"]
RW_ROWS = [
    ["RW1", "+0000", "EF", "VVS VS", 0.29, 42000, 12180],                     # !2
    ["RW1", "+5", "EF", "VVS VS", 7.06, 35000, 247100],                       # !3
    ["RW2", "+3", "GH", "VVS VS", 0, 31500, 0],                               # !4  zero carats
    [None, None, None, None, None, None, 259280],                             # !5 total
]
#: FANCY holds the same lines as FANCY FINAL with older rates; it must never be read
IGNORED_ROWS = [[None, "Emerald", "DXX VVS VS", "EF", "VVS VS", None, 1, 99.99, 1, 99.99]]


def _save(workbook):
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def build_workbook():
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, header, rows in (("FANCY", FANCY_HEADER, IGNORED_ROWS), ("FANCY FINAL", FANCY_HEADER, FANCY_ROWS),
                                ("Round_LB_LC", LB_HEADER, LB_ROWS), ("Round_RW", RW_HEADER, RW_ROWS)):
        sheet = workbook.create_sheet(title)
        sheet.append(header)
        for row in rows:
            sheet.append(row)
    return _save(workbook)


#: for import-plan tests: FANCY FINAL rows with a Category column (index 11)
PLAN_ROWS = [
    [None, "Round", "DRFGH VS-SI", "FGH", "VS SI", "0000-000", None, 20.13, None, None, None, "Diamond"],       # !2
    ["B-771", "Round", "DRFGH VS-SI", "FGH", "VS SI", "+6-12", None, 3.40, None, None, None, "Diamond"],       # !3
    ["B-771", "Round", "DRFGH VS-SI", "FGH", "VS SI", "+2", None, 1.15, None, None, None, "Diamond"],         # !4
    ["B-771", "Princess", "DPCEF VVS-VS", "EF", "VVS VS", "+2", None, 0.85, None, None, None, "Diamond"],      # !5
    ["BW-1", None, "FPL", None, None, "20+", None, 43.21, None, None, None, "Foil Polki"],                    # !6
    ["BW-1", None, "DTRQ VS-SI", None, None, "TR 0.20-0.24", None, 0.93, None, None, None, "Foil Polki"],     # !7
]


def fancy_workbook(rows=None):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "FANCY FINAL"
    sheet.append(FANCY_HEADER + ["Category"])
    for row in PLAN_ROWS if rows is None else rows:
        sheet.append([None if cell == "" else cell for cell in row])
    return _save(workbook)


def ivy_workbook(rows):
    """The IVY export's shape: two title rows, the header on row 3, the diamond band's columns by position.
    ``rows`` are (item code, size, cost, sale)."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Karigar export"])
    sheet.append([])
    width = dia_services.IVY_SALE + 5
    header = [""] * width
    header[dia_services.IVY_CODE], header[dia_services.IVY_SIZE] = "Item Code", "Size"
    header[dia_services.IVY_COST], header[dia_services.IVY_SALE] = "Rate", "Rate"
    sheet.append(header)
    for code, size, cost, sale in rows:
        row = [None] * width
        row[dia_services.IVY_CODE], row[dia_services.IVY_SIZE] = code, size
        row[dia_services.IVY_COST], row[dia_services.IVY_SALE] = cost, sale
        sheet.append(row)
    return _save(workbook)
