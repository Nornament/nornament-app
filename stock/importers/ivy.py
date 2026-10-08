"""The shape of the IVY Karigar stock export, in one place.

Products are blocks, not rows: a block opens wherever column C carries a style
number and runs to the next one. Five material bands then run down that block
*independently* — the stone on the third row of a block has nothing to do with
the diamond on the first. Reading them in lockstep would silently pair up
unrelated materials, which is why each band gets its own pass.
"""
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook
from openpyxl.drawing.spreadsheet_drawing import SpreadsheetDrawing
from openpyxl.packaging.relationship import get_dependents, get_rels_path
from openpyxl.utils import column_index_from_string as col
from openpyxl.xml.functions import fromstring

SHEET = "Sheet1"
HEADER_ROW = 3
FIRST_DATA_ROW = 4

#: The last column of the piece header. Everything from here on is material
#: bands, whose layout has been identical in every export seen so far.
HEADER_BLOCK_END = 20  # column T

#: What ``parse`` reads out of the piece header, by the text in row 3 rather
#: than by column letter. These columns move: a client handover file inserted
#: "Image Name" and dropped "Location Name", shifting Category and Sub Category
#: one to the right, which read the style code as the category and imported
#: every ring as its own category. Names inside the header block are unique in
#: every export seen, so matching on them is both safer and self-describing.
HEADER_FIELDS = {
    "sr_no": "Sr No",
    "style_code": "Style No",
    "jewel_code": "JewelCode",
    "category": "Category",
    "sub_category": "Sub Category",
    "vendor": "Manuf. Name",
    "collection": "Collection",
    "make_type": "Make Type",
    "stock_type": "Stock Type",
    "inw_date": "Inw Date",
    "fg_date": "Misc Remarks",
    "remarks": "Remarks",
}

#: Without these the file is not a stock export and nothing else is worth doing.
REQUIRED_HEADERS = ("style_code", "jewel_code", "category", "inw_date")

#: Band anchors, still checked by letter: the bands have never moved, and their
#: headers repeat ("Item Code" three times) so names cannot identify them.
EXPECTED_HEADERS = {
    "U": "Item Code",
    "AK": "Item Code",
    "AV": "Stone",
    "BE": "Cost Price",
    "BS": "Item Code",
}

#: band name -> the columns that make up one line of that band.
#: ``key`` is the column that decides whether the band has a line on this row.
BANDS = {
    "diamond": {
        "key": "U", "name": "V", "shape": "X", "quality": "Y",
        "size_band": "AA", "pcs": "AD", "qty": "AE",
        "cost_rate": "AG", "sale_rate": "AH",
        "cost_amount": "AI", "sale_amount": "AJ",
    },
    "metal": {
        "key": "AK", "name": "AL", "qty": "AN",
        "cost_rate": "AR", "sale_rate": "AS",
        "cost_amount": "AT", "sale_amount": "AU",
    },
    "stone": {
        "key": "AV", "name": "AW", "pcs": "AX", "qty": "AY",
        "cost_rate": "BA", "sale_rate": "BB",
        "cost_amount": "BC", "sale_amount": "BD",
    },
    # BI–BR carries a name but no item code, so the name is the key
    "other": {
        "key": "BJ", "name": "BJ", "qty": "BN",
        "cost_rate": "BO", "sale_rate": "BQ",
        "cost_amount": "BP", "sale_amount": "BR",
    },
    "charge": {
        "key": "BS", "name": "BT", "pcs": "BU", "qty": "BV",
        "cost_rate": "BW", "sale_rate": "BY",
        "cost_amount": "BX", "sale_amount": "BZ",
    },
}


@dataclass
class ParsedLine:
    band: str
    code: str
    name: str = ""
    pcs: int = None
    qty: Decimal = None
    cost_rate: Decimal = None
    sale_rate: Decimal = None
    cost_amount: Decimal = None
    sale_amount: Decimal = None
    size_band: str = ""
    shape: str = ""
    quality: str = ""


@dataclass
class ParsedPiece:
    row_no: int
    sr_no: str = ""
    style_code: str = ""
    jewel_code: str = ""
    category: str = ""
    sub_category: str = ""
    collection: str = ""
    vendor: str = ""
    make_type: str = ""
    stock_type: str = ""
    inw_date: object = None
    fg_date: object = None
    metal_purity: str = ""
    diamond_quality: str = ""
    remarks: str = ""
    src_cost_price: Decimal = None
    src_sale_price: Decimal = None
    src_net_wt_gm: Decimal = None
    making_cost: Decimal = None
    making_sale: Decimal = None
    superseded: int = 0             # earlier rows for this jewel code, folded away
    lines: list = field(default_factory=list)
    #: where this piece's photo sits inside the workbook, not the photo itself:
    #: the bytes are read one at a time by whoever attaches them (``read_photo``)
    photo: str = None


def _grid(sheet, max_row=None):
    """Every value on the sheet as rows of tuples, read once.

    The workbook is opened read-only, which never loads the embedded photos —
    in normal mode openpyxl reads every one of them into memory just to open
    the file, on every review page. Read-only cells are slow to reach one at a
    time, hence the single pass into plain tuples.
    """
    grid = [list(row) for row in sheet.iter_rows(max_row=max_row, values_only=True)]
    _blank_merged(grid, sheet)
    return grid


def _blank_merged(grid, sheet):
    """Keep only the top-left value of each merged range, as normal mode does.

    IVY writes a merged footer ("[admin] : 08:10:2026 03:08") with the text
    repeated in every cell; read-only mode knows nothing of merges, so without
    this the footer's column C reads as one more style number.
    """
    from xml.etree.ElementTree import iterparse

    from openpyxl.worksheet.cell_range import CellRange

    with sheet.parent._archive.open(sheet._worksheet_path) as source:
        for _, element in iterparse(source):
            if element.tag.endswith("}mergeCell"):
                merged = CellRange(element.get("ref"))
                for row, column in merged.cells:
                    if (row, column) != (merged.min_row, merged.min_col) and row <= len(grid):
                        values = grid[row - 1]
                        if column <= len(values):
                            values[column - 1] = None
            element.clear()


def _cell(grid, row, column):
    """One cell by column index, tolerating a column this export does not have."""
    if not column or row > len(grid):
        return None
    values = grid[row - 1]
    return values[column - 1] if column <= len(values) else None


def _cell_text(grid, row, column):
    value = _cell(grid, row, column)
    return "" if value is None else str(value).strip()


def _text(grid, row, letter):
    return _cell_text(grid, row, col(letter))


def _num(grid, row, letter):
    """A cell as Decimal, or None. Blank and unparseable both mean None."""
    value = _cell(grid, row, col(letter))
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _int(grid, row, letter):
    value = _num(grid, row, letter)
    return None if value is None else int(value)


def _date(value):
    """The export writes dates two ways: real datetimes, and 'Nov  7 2025 12:00AM'."""
    if isinstance(value, datetime):
        return value.date()
    if not value:
        return None
    text = " ".join(str(value).split())
    for pattern in ("%b %d %Y %I:%M%p", "%b %d %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def header_map(grid):
    """Field name -> column index, read off row 3 of the piece header.

    Only the header block is resolved this way. Its names are unique, and they
    are the columns that have actually moved between exports.
    """
    found = {}
    for column in range(1, HEADER_BLOCK_END + 1):
        label = _cell_text(grid, HEADER_ROW, column)
        for field, expected in HEADER_FIELDS.items():
            if label == expected and field not in found:
                found[field] = column
    return found


def header_problems(fileobj):
    """Why this workbook cannot be read, if it cannot.

    Checked before anything else, so the wrong workbook is refused with the
    offending column rather than imported as nonsense. Anything that is not a
    readable workbook, or is one without the export's sheet, is a problem too
    — this is the gate for files a person picked by mistake, so it has to
    answer rather than raise.
    """
    try:
        book = load_workbook(fileobj, data_only=True, read_only=True)
    except Exception as error:
        return [f"That file could not be read as a spreadsheet ({error})."]
    if SHEET not in book.sheetnames:
        return [f"No {SHEET!r} sheet — found {', '.join(book.sheetnames) or 'nothing'}."]
    grid = _grid(book[SHEET], max_row=HEADER_ROW)
    book.close()

    problems = []
    mapped = header_map(grid)
    for field in REQUIRED_HEADERS:
        if field not in mapped:
            problems.append(f"No {HEADER_FIELDS[field]!r} column in row {HEADER_ROW}.")
    for letter, expected in EXPECTED_HEADERS.items():
        found = _text(grid, HEADER_ROW, letter)
        if found != expected:
            problems.append(f"Column {letter} should be {expected!r}, found {found!r}")
    return problems


def _line_at(grid, row, band, spec):
    """One line of one band on one row, or None if this band is blank here."""
    code = _text(grid, row, spec["key"])
    if not code:
        return None
    return ParsedLine(
        band=band,
        code=code,
        name=_text(grid, row, spec.get("name", spec["key"])),
        pcs=_int(grid, row, spec["pcs"]) if "pcs" in spec else None,
        qty=_num(grid, row, spec["qty"]) if "qty" in spec else None,
        cost_rate=_num(grid, row, spec["cost_rate"]),
        sale_rate=_num(grid, row, spec["sale_rate"]),
        cost_amount=_num(grid, row, spec["cost_amount"]),
        sale_amount=_num(grid, row, spec["sale_amount"]),
        size_band=_text(grid, row, spec["size_band"]) if "size_band" in spec else "",
        shape=_text(grid, row, spec["shape"]) if "shape" in spec else "",
        quality=_text(grid, row, spec["quality"]) if "quality" in spec else "",
    )


def _photo_paths(book, sheet):
    """Anchor row -> where that row's photo lives inside the workbook.

    Read off the sheet's drawing XML, so no photo is loaded to find out where
    the photos are. Photos sit in column A on parent rows.
    """
    archive = book._archive
    rels_path = get_rels_path(sheet._worksheet_path)
    if rels_path not in archive.namelist():
        return {}
    found = {}
    for drawing_rel in get_dependents(archive, rels_path).find(SpreadsheetDrawing._rel_type):
        drawing = SpreadsheetDrawing.from_tree(fromstring(archive.read(drawing_rel.target)))
        deps = get_dependents(archive, get_rels_path(drawing_rel.target))
        for pic in drawing._blip_rels:
            dep = deps.get(pic.embed)
            if dep is not None and dep.Type.endswith("/image"):
                found[pic.anchor._from.row + 1] = dep.target
    return found


def read_photo(fileobj, path):
    """One photo's bytes out of the workbook, and only that one."""
    with zipfile.ZipFile(fileobj) as archive:
        return archive.read(path)


def latest_per_jewel_code(pieces):
    """One block per jewel code: the most recently inwarded one.

    A handover file lists the same piece more than once — the same jewel code
    at two dates, differing in its sale rates. Everything downstream keys on
    the jewel code, so two blocks for one piece is not something they can each
    do half of: analyse would collapse them into one decision and commit would
    silently take whichever it met first, which is the older one.

    Taking the newest inward date makes that choice explicit and picks the
    valuation the client most recently stood behind. What was dropped is
    counted on the survivor rather than thrown away quietly.
    """
    newest = {}
    for order, piece in enumerate(pieces):
        seen = newest.get(piece.jewel_code)
        if seen is None:
            newest[piece.jewel_code] = piece
            continue
        # a row with no date never beats one that has a date; otherwise the
        # later date wins, and equal dates fall to the later row in the file
        current = (piece.inw_date is not None, piece.inw_date or date.min, order)
        against = (seen.inw_date is not None, seen.inw_date or date.min, -1)
        keep, drop = (piece, seen) if current > against else (seen, piece)
        keep.superseded = seen.superseded + drop.superseded + 1
        newest[piece.jewel_code] = keep
    return list(newest.values())


def parse(fileobj):
    """Every product in the workbook, with its material lines and where its photo is."""
    book = load_workbook(fileobj, data_only=True, read_only=True)
    sheet = book[SHEET]
    grid = _grid(sheet)
    photos = _photo_paths(book, sheet)
    book.close()

    where = header_map(grid)
    at = lambda row, field: _cell_text(grid, row, where.get(field))
    start_col = where.get("style_code", col("C"))
    max_row = len(grid)

    starts = [
        row for row in range(FIRST_DATA_ROW, max_row + 1)
        if _cell_text(grid, row, start_col)
    ]
    pieces = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else max_row + 1
        piece = ParsedPiece(
            row_no=start,
            sr_no=at(start, "sr_no"),
            style_code=at(start, "style_code"),
            jewel_code=at(start, "jewel_code"),
            category=at(start, "category"),
            sub_category=at(start, "sub_category"),
            collection=at(start, "collection"),
            vendor=at(start, "vendor"),
            make_type=at(start, "make_type"),
            stock_type=at(start, "stock_type").upper().replace(" ", "_"),
            inw_date=_date(_cell(grid, start, where.get("inw_date"))),
            fg_date=_date(_cell(grid, start, where.get("fg_date"))),
            metal_purity=_text(grid, start, "BI"),
            diamond_quality=_text(grid, start, "Y"),
            remarks=at(start, "remarks"),
            src_cost_price=_num(grid, start, "BE"),
            src_sale_price=_num(grid, start, "BF"),
            src_net_wt_gm=_num(grid, start, "AN"),
            # BG/BH are the piece's making charge. They sit with the totals
            # rather than in a band, so they are read here and become a labour
            # line at commit — without them every piece imports under-costed.
            making_cost=_num(grid, start, "BG"),
            making_sale=_num(grid, start, "BH"),
            photo=photos.get(start),
        )
        # each band down the whole block, on its own — see the module docstring
        for band, spec in BANDS.items():
            for row in range(start, end):
                line = _line_at(grid, row, band, spec)
                if line is not None:
                    piece.lines.append(line)
        pieces.append(piece)
    return latest_per_jewel_code(pieces)
