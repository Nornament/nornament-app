# IVY Stock Importer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin upload the IVY Karigar stock workbook in the browser, review every ambiguous decision before anything is written, then commit pieces, BOMs and images with a live progress bar.

**Architecture:** A new `stock/importers/` package holds four pure-ish modules — `ivy.py` (parse), `guess.py` (fill in new materials), `analyse.py` (diff against the DB), `commit.py` (write). Views stay thin and live in `stock/views.py`. One `ImportBatch` row carries the uploaded file, the reviewer's decisions and the image progress counter. Image uploads run after the DB transaction, chunked by the browser via htmx.

**Tech Stack:** Django 5.2, pytest + pytest-django, htmx (already vendored), openpyxl (new), boto3 via the existing `mediahub` app.

**Spec:** `docs/superpowers/specs/2026-09-01-ivy-stock-importer-design.md`

## Global Constraints

- Python code follows the surrounding style: docstrings explain *why*, not *what*. The codebase uses no type annotations, so do not add them to functions — the one exception is dataclass field declarations in `ivy.py` and `analyse.py`, where annotations are what makes `@dataclass` work at all.
- Reuse `stock.services` rather than writing new BOM/ledger code. Specifically: `services.set_bom`, `services.new_bom_version`, `services.receive_piece`, `services.recost_piece`.
- Reuse `mediahub.services.attach_uploads` for images. Write no new S3 code.
- Never use `ChargeBasis.BY_NET_METAL_WT` for imported metal lines. `recost_piece` snaps every such line to the piece's *total* net metal weight, so a piece with two metal lines (e.g. `G14K` plus `GC14K`) would have both inflated to the total. Imported metal lines use `BY_QTY` with the sheet's own net weight.
- Charge lines (`EC`, `PC`, `RH100`) use `ChargeBasis.FLAT`, where `charge_base` returns 1 and the rate *is* the amount.
- `Material` has a check constraint `material_metal_required`: a material with `category="METAL"` must have a non-null `metal` FK. A metal the guesser cannot resolve is a hard blocker, never a `needs_review` pass-through.
- `services.set_bom` enforces UOM per category: metal must be `GM`; `DIAMOND`/`POLKI` must be `CT` or `PCS`.
- All new tests go under `stock/tests/`, run with `pytest`, and use `pytestmark = pytest.mark.django_db`.
- Run tests as: `source .venv/bin/activate && pytest <path> -v`

## File Structure

| File | Responsibility |
|---|---|
| `stock/importers/__init__.py` | package marker, re-exports `parse`, `analyse`, `commit` |
| `stock/importers/ivy.py` | the IVY sheet shape: band constants, `parse()`, header check |
| `stock/importers/guess.py` | new-material field guessing from band + code |
| `stock/importers/analyse.py` | diff a parse against the DB into a `Plan` |
| `stock/importers/commit.py` | write the plan, and attach images in chunks |
| `stock/models.py` (modify) | add `ImportBatch` |
| `stock/views.py` (modify) | four thin views |
| `stock/urls.py` (modify) | four routes |
| `stock/templates/stock/import_review.html` | the review screen |
| `stock/templates/stock/_import_progress.html` | the progress bar partial |
| `stock/templates/stock/data.html` (modify) | the upload form |
| `stock/tests/test_import_ivy.py` | parse + guess tests |
| `stock/tests/test_import_commit.py` | analyse + commit + images tests |
| `stock/tests/fixtures_ivy.py` | builds the fixture workbook in memory |

---

### Task 1: Dependency, package skeleton, and the fixture workbook

Nothing can be tested until there is a workbook to test against. This task
produces the fixture builder that every later task uses.

**Files:**
- Modify: `requirements.txt`
- Create: `stock/importers/__init__.py`
- Create: `stock/tests/fixtures_ivy.py`

**Interfaces:**
- Produces: `stock.tests.fixtures_ivy.build_workbook(products=None) -> io.BytesIO`, and the module-level `THREE_PRODUCTS` list used as its default.

- [ ] **Step 1: Add the dependency**

Add to `requirements.txt`, keeping the existing pinning style:

```
openpyxl==3.1.*
```

Then install it:

```bash
source .venv/bin/activate && pip install 'openpyxl==3.1.*'
```

- [ ] **Step 2: Create the package marker**

`stock/importers/__init__.py`:

```python
"""Reading the IVY Karigar stock export.

The workbook is not a table: products are blocks of rows, and five material
bands run down each block independently. Everything that knows that shape
lives here, so ``views.py`` never has to.
"""
from .analyse import analyse
from .commit import commit
from .ivy import parse

__all__ = ["parse", "analyse", "commit"]
```

This will not import until Tasks 2–5 exist. That is expected; nothing imports
it yet.

- [ ] **Step 3: Write the fixture builder**

`stock/tests/fixtures_ivy.py`. Three products chosen to cover the rules most
likely to break: a one-row product, a product whose bands are different
lengths, and a product that will collide with an existing jewel code.

```python
"""A miniature IVY workbook, built in memory.

Three products, because the fixture has to stay readable: one plain row, one
whose bands are deliberately ragged, and one that collides with a piece the
test has already created.
"""
import io
from datetime import datetime

from openpyxl import Workbook

#: header row 3, verbatim from the real export
HEADERS = [
    "Image", "Sr No", "Style No", "JewelCode", "Category", "Sub Category",
    "Location Name", "Inw Date", "Qty", "Item Pieces", "Manuf. Name",
    "Manufacturer No", "Collection", "Item Size", "Make Type", "Stock Type",
    "Misc Remarks", "Remarks", "Update By", "Update Date",
    "Item Code", "Item Name Diamond", "Shape", "ShapeName", "Quality", "GSize",
    "Size", "Size MM", "Setting", "Pcs", "Wt", "Batch No", "Cost Rate",
    "Sale Rate", "Cost", "Sale",
    "Item Code", "Item Name Gold", "Gross Wt", "Net Wt", "Loss Wt", "Pure Wt",
    "CPFRate", "Cost Rate", "Sale Rate", "Cost", "Sale",
    "Stone", "Stone (Name)", "Pcs", "Wt", "Batch No", "Cost Rate", "Rate",
    "Cost", "Amount",
    "Cost Price", "Sale Price", "Cost Making Amt", "Sale Making Amt",
    "G Qly", "Item Name", "Quality", "ToneCode", "Gross Wt", "Net Wt",
    "Cost Rate", "Cost Amt", "Sale Rate", "Sale Amt",
    "Item Code", "Item Name", "Pcs", "Wt", "Cost Rate", "Cost Amt", "Rate",
    "Amt",
]


def _header(sr, style, jewel, category, collection):
    """Columns B..T of a parent row, as a dict of column index -> value."""
    return {
        2: sr, 3: style, 4: jewel, 5: category, 6: "STUDS",
        8: datetime(2026, 7, 8), 9: 1, 10: 1, 11: "Infinity Venture [IVY]",
        13: collection, 15: "Casting", 16: "Finish Goods",
        17: "Nov  7 2025 12:00AM", 19: "Krisha Gada",
        20: datetime(2026, 7, 27, 10, 19, 44),
    }


#: (header cells, [extra cells per row of the block])
THREE_PRODUCTS = [
    # 1. one row: one diamond line, one metal line, and the totals
    (
        _header(1, "ER00502", "24P00088", "Earring", "Norna"),
        [{
            21: "DRFGH VS-SI", 22: "DiamondRFGH VS-SI", 23: "R", 24: "Round",
            25: "FGH VS-SI", 26: "+2-6.5", 27: "+3", 28: "1.40",
            30: 2, 31: 0.02, 33: 30000, 34: 250000, 35: 600, 36: 5000,
            37: "G18K", 38: "Gold18K", 39: 1.41, 40: 1.406, 42: 1.059,
            43: 2500, 44: 5460, 45: 11291.09, 46: 7677, 47: 15875,
            57: 9683, 58: 29514.56, 59: 1406, 60: 3515, 61: "18K",
            71: "EC", 72: "Extra Charges", 78: 5400,
        }],
    ),
    # 2. ragged bands: 3 diamond lines, 1 metal line, 2 stone lines.
    #    The stone band must keep reading after the metal band has run out.
    (
        _header(2, "ER00409", "24P00111", "Earring", "Lumina"),
        [
            {
                21: "DRIJ SI-I", 22: "DiamondRIJ SI-I", 23: "R", 24: "Round",
                25: "IJ SI-I", 27: "+1", 30: 10, 31: 0.07,
                33: 9500, 34: 35000, 35: 665, 36: 2450,
                37: "G14K", 38: "Gold14K", 39: 9.75, 40: 8.228, 42: 4.822,
                43: 1500, 44: 4319, 45: 8765.45, 46: 35537, 47: 72122,
                48: "SP01C", 49: "Stone Semi Precious01C", 50: 10, 51: 14,
                53: 100, 54: 300, 55: 1400, 56: 4200,
                57: 84438, 58: 227427.18, 59: 8558, 60: 12837, 61: "14K",
            },
            {
                21: "FPL", 22: "Foil Polki", 26: "+12-18", 27: "+12-18",
                30: 4, 31: 1.86, 33: 6000, 34: 21000, 35: 11160, 36: 39060,
                48: "PS01W", 49: "7 MM Moti", 50: 2, 51: 44.5,
                53: 20, 54: 90, 55: 890, 56: 4005,
            },
            {
                21: "DRFGH SI-I", 22: "DiamondRFGH SI-I", 23: "R",
                24: "Round", 25: "FGH SI-I", 27: "00-0",
                30: 81, 31: 0.39, 33: 10300, 34: 35000, 35: 4017, 36: 13650,
            },
        ],
    ),
    # 3. collides with a piece the test creates beforehand
    (
        _header(3, "RG00113", "24P00095", "Ring", "Brilliance"),
        [{
            21: "DRGH VVS-VS", 22: "DiamondRGH VVS-VS", 23: "R", 24: "Round",
            25: "GH VVS-VS", 30: 24, 31: 0.46,
            33: 20000, 34: 86700, 35: 9200, 36: 39882,
            37: "G14K", 38: "Gold14K", 39: 1.22, 40: 1.128, 42: 0.661,
            43: 1500, 44: 4689, 45: 8765.45, 46: 5289, 47: 9887,
            57: 15617, 58: 51407.77, 59: 1128, 60: 1692, 61: "14K",
        }],
    ),
]


def build_workbook(products=None):
    """The three-product workbook as a BytesIO, laid out like the real export."""
    products = THREE_PRODUCTS if products is None else products
    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet["A1"] = "IVY Karigar Private Limited"
    for index, name in enumerate(HEADERS, start=1):
        sheet.cell(row=3, column=index, value=name)

    row = 4
    for header, block in products:
        for offset, extras in enumerate(block):
            cells = dict(extras)
            if offset == 0:
                cells.update(header)
            for column, value in cells.items():
                sheet.cell(row=row, column=column, value=value)
            row += 1
    sheet.cell(row=row + 1, column=1, value="[admin] : 27:07:2026 11:18")

    stream = io.BytesIO()
    book.save(stream)
    stream.seek(0)
    return stream
```

- [ ] **Step 4: Verify the fixture builds and has the shape we expect**

```bash
source .venv/bin/activate && python -c "
from openpyxl import load_workbook
from stock.tests.fixtures_ivy import build_workbook
ws = load_workbook(build_workbook())['Sheet1']
assert ws['A1'].value == 'IVY Karigar Private Limited'
assert ws['C3'].value == 'Style No'
assert ws['C4'].value == 'ER00502'
assert ws['C5'].value == 'RG00113' or ws['C5'].value is None
print('parent rows:', [r for r in range(4, 12) if ws.cell(row=r, column=3).value])
print('ok')
"
```

Expected: `parent rows: [4, 5, 8]` and `ok`. Product 2 occupies rows 5–7, so
product 3 starts at row 8.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt stock/importers/__init__.py stock/tests/fixtures_ivy.py
git commit -m "Add openpyxl and a miniature IVY workbook to test against"
```

---

### Task 2: The parser

**Files:**
- Create: `stock/importers/ivy.py`
- Create: `stock/tests/test_import_ivy.py`

**Interfaces:**
- Consumes: `stock.tests.fixtures_ivy.build_workbook`
- Produces:
  - `ParsedLine` dataclass: `band, code, name, pcs, qty, cost_rate, sale_rate, cost_amount, sale_amount, size_band, shape, quality`
  - `ParsedPiece` dataclass: `row_no, sr_no, style_code, jewel_code, category, sub_category, collection, vendor, make_type, stock_type, inw_date, fg_date, metal_purity, diamond_quality, remarks, src_cost_price, src_sale_price, src_net_wt_gm, lines, image`
  - `parse(fileobj) -> list[ParsedPiece]`
  - `header_problems(fileobj) -> list[str]`

- [ ] **Step 1: Write the failing tests**

`stock/tests/test_import_ivy.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate && pytest stock/tests/test_import_ivy.py -v
```

Expected: collection error / `ModuleNotFoundError: No module named 'stock.importers.ivy'`.

- [ ] **Step 3: Write the parser**

`stock/importers/ivy.py`:

```python
"""The shape of the IVY Karigar stock export, in one place.

Products are blocks, not rows: a block opens wherever column C carries a style
number and runs to the next one. Five material bands then run down that block
*independently* — the stone on the third row of a block has nothing to do with
the diamond on the first. Reading them in lockstep would silently pair up
unrelated materials, which is why each band gets its own pass.
"""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string as col

SHEET = "Sheet1"
HEADER_ROW = 3
FIRST_DATA_ROW = 4
STYLE_COL = col("C")

#: Column letters we check in row 3 before trusting anything else in the file.
EXPECTED_HEADERS = {
    "C": "Style No",
    "D": "JewelCode",
    "E": "Category",
    "M": "Collection",
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
    lines: list = field(default_factory=list)
    image: bytes = None


def _text(sheet, row, letter):
    value = sheet.cell(row=row, column=col(letter)).value
    if value is None:
        return ""
    return str(value).strip()


def _num(sheet, row, letter):
    """A cell as Decimal, or None. Blank and unparseable both mean None."""
    value = sheet.cell(row=row, column=col(letter)).value
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _int(sheet, row, letter):
    value = _num(sheet, row, letter)
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


def header_problems(fileobj):
    """Every header in row 3 that is not what this importer expects.

    Checked before anything else, so the wrong workbook is refused with the
    offending column rather than imported as nonsense.
    """
    sheet = load_workbook(fileobj, data_only=True, read_only=True)[SHEET]
    problems = []
    for letter, expected in EXPECTED_HEADERS.items():
        found = _text(sheet, HEADER_ROW, letter)
        if found != expected:
            problems.append(f"Column {letter} should be {expected!r}, found {found!r}")
    return problems


def _line_at(sheet, row, band, spec):
    """One line of one band on one row, or None if this band is blank here."""
    code = _text(sheet, row, spec["key"])
    if not code:
        return None
    return ParsedLine(
        band=band,
        code=code,
        name=_text(sheet, row, spec.get("name", spec["key"])),
        pcs=_int(sheet, row, spec["pcs"]) if "pcs" in spec else None,
        qty=_num(sheet, row, spec["qty"]) if "qty" in spec else None,
        cost_rate=_num(sheet, row, spec["cost_rate"]),
        sale_rate=_num(sheet, row, spec["sale_rate"]),
        cost_amount=_num(sheet, row, spec["cost_amount"]),
        sale_amount=_num(sheet, row, spec["sale_amount"]),
        size_band=_text(sheet, row, spec["size_band"]) if "size_band" in spec else "",
        shape=_text(sheet, row, spec["shape"]) if "shape" in spec else "",
        quality=_text(sheet, row, spec["quality"]) if "quality" in spec else "",
    )


def _images_by_row(sheet):
    """Anchor row -> image bytes. Images sit in column A on parent rows."""
    found = {}
    for image in getattr(sheet, "_images", []):
        row = image.anchor._from.row + 1
        data = image._data() if callable(getattr(image, "_data", None)) else None
        if data:
            found[row] = data
    return found


def parse(fileobj):
    """Every product in the workbook, with its material lines and its photo."""
    book = load_workbook(fileobj, data_only=True)
    sheet = book[SHEET]
    images = _images_by_row(sheet)

    starts = [
        row for row in range(FIRST_DATA_ROW, sheet.max_row + 1)
        if _text(sheet, row, "C")
    ]
    pieces = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else sheet.max_row + 1
        piece = ParsedPiece(
            row_no=start,
            sr_no=_text(sheet, start, "B"),
            style_code=_text(sheet, start, "C"),
            jewel_code=_text(sheet, start, "D"),
            category=_text(sheet, start, "E"),
            sub_category=_text(sheet, start, "F"),
            collection=_text(sheet, start, "M"),
            vendor=_text(sheet, start, "K"),
            make_type=_text(sheet, start, "O"),
            stock_type=_text(sheet, start, "P").upper().replace(" ", "_"),
            inw_date=_date(sheet.cell(row=start, column=col("H")).value),
            fg_date=_date(sheet.cell(row=start, column=col("Q")).value),
            metal_purity=_text(sheet, start, "BI"),
            diamond_quality=_text(sheet, start, "Y"),
            remarks=_text(sheet, start, "R"),
            src_cost_price=_num(sheet, start, "BE"),
            src_sale_price=_num(sheet, start, "BF"),
            src_net_wt_gm=_num(sheet, start, "AN"),
            image=images.get(start),
        )
        # each band down the whole block, on its own — see the module docstring
        for band, spec in BANDS.items():
            for row in range(start, end):
                line = _line_at(sheet, row, band, spec)
                if line is not None:
                    piece.lines.append(line)
        pieces.append(piece)
    return pieces
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
source .venv/bin/activate && pytest stock/tests/test_import_ivy.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Sanity-check against the real workbook**

```bash
source .venv/bin/activate && python -c "
from stock.importers import ivy
pieces = ivy.parse('/Users/preet/Downloads/nornament stock.xlsx')
print('products:', len(pieces))
print('lines:', sum(len(p.lines) for p in pieces))
print('images:', sum(1 for p in pieces if p.image))
print('header problems:', ivy.header_problems('/Users/preet/Downloads/nornament stock.xlsx'))
"
```

Expected exactly: `products: 373`, `lines: 1845`, `images: 367`,
`header problems: []`. Any other number means a band is being read wrongly —
stop and fix before continuing.

- [ ] **Step 6: Commit**

```bash
git add stock/importers/ivy.py stock/tests/test_import_ivy.py
git commit -m "Parse the IVY export, reading each material band independently"
```

---

### Task 3: Guessing new materials

**Files:**
- Create: `stock/importers/guess.py`
- Modify: `stock/tests/test_import_ivy.py` (append)

**Interfaces:**
- Consumes: `ivy.ParsedLine`
- Produces: `guess.material_fields(line) -> (fields: dict, problem: str | None)`.
  `fields` is a kwargs dict for `Material.objects.create`. A non-None `problem`
  means the row blocks commit until a human resolves it.
  Also `guess.bom_basis_and_uom(line, material_category) -> (basis, uom)`.

- [ ] **Step 1: Write the failing tests**

Append to `stock/tests/test_import_ivy.py`:

```python
# ── guessing new materials ───────────────────────────────────────────────
import pytest

from stock.enums import ChargeBasis, Uom
from stock.importers import guess
from stock.importers.ivy import ParsedLine

pytestmark = pytest.mark.django_db


def _line(band, code, name=""):
    return ParsedLine(band=band, code=code, name=name or code)


def test_a_diamond_code_becomes_a_diamond_in_carats():
    fields, problem = guess.material_fields(_line("diamond", "DRFGH SI-I"))
    assert problem is None
    assert fields["category_id"] == "DIAMOND"
    assert fields["default_uom"] == Uom.CT


def test_a_foil_polki_code_becomes_polki_not_diamond():
    fields, problem = guess.material_fields(_line("diamond", "FPL", "Foil Polki"))
    assert problem is None
    assert fields["category_id"] == "POLKI"


def test_a_gold_code_resolves_its_metal_and_purity(rates):
    fields, problem = guess.material_fields(_line("metal", "G18K", "Gold18K"))
    assert problem is None
    assert fields["category_id"] == "METAL"
    assert fields["metal_id"] == "GOLD"
    assert fields["purity_factor"] == pytest.approx(0.75, abs=0.0001)
    assert fields["default_uom"] == Uom.GM


def test_a_silver_code_resolves_to_silver(rates):
    fields, problem = guess.material_fields(_line("metal", "S925", "Silver925"))
    assert problem is None
    assert fields["metal_id"] == "SILVER"


def test_a_purity_that_does_not_exist_is_a_blocker_not_a_guess(rates):
    """G12K: MetalPurity has no 12K row, and inventing one would be a lie."""
    fields, problem = guess.material_fields(_line("metal", "G12K", "Gold12K"))
    assert problem is not None
    assert "12K" in problem


def test_an_unreadable_metal_code_is_a_blocker(rates):
    """CJ 'Customer Jewelry999' has no G/S prefix to read a metal from."""
    _, problem = guess.material_fields(_line("metal", "CJ", "Customer Jewelry999"))
    assert problem is not None


def test_a_stone_becomes_a_setting_stone():
    fields, problem = guess.material_fields(_line("stone", "SP01C", "Semi Precious"))
    assert problem is None
    assert fields["category_id"] == "SETTING"


def test_an_other_band_line_mints_a_code_from_its_name():
    fields, problem = guess.material_fields(_line("other", "Lakh", "Lakh"))
    assert problem is None
    assert fields["item_code"] == "OTH-LAKH"
    assert fields["category_id"] == "OTHER"


def test_a_charge_becomes_labour():
    fields, problem = guess.material_fields(_line("charge", "EC", "Extra Charges"))
    assert problem is None
    assert fields["category_id"] == "LABOUR"


def test_metal_lines_are_by_qty_never_by_net_metal_weight():
    """BY_NET_METAL_WT would snap every metal line to the piece total."""
    basis, uom = guess.bom_basis_and_uom(_line("metal", "G18K"), "METAL")
    assert basis == ChargeBasis.BY_QTY
    assert uom == Uom.GM


def test_charge_lines_are_flat_so_the_rate_is_the_amount():
    basis, uom = guess.bom_basis_and_uom(_line("charge", "EC"), "LABOUR")
    assert basis == ChargeBasis.FLAT
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate && pytest stock/tests/test_import_ivy.py -k guess -v
```

Expected: `ModuleNotFoundError: No module named 'stock.importers.guess'`.

- [ ] **Step 3: Write the guesser**

`stock/importers/guess.py`:

```python
"""Filling in a material the sheet mentions but the register has never seen.

127 of the 224 codes in the first real file were new. Asking a human to type
category, unit and metal for each of those is how an import stops happening,
so the band a code appeared in does the work: it already says what kind of
thing the code is. What the band cannot answer — a metal purity that does not
exist in the table — is returned as a problem rather than a guess, because a
wrong purity silently misprices every piece that uses it.
"""
import re

from stock.enums import ChargeBasis, Uom

#: band -> the material category a code in that band belongs to
BAND_CATEGORY = {
    "diamond": "DIAMOND",
    "metal": "METAL",
    "stone": "SETTING",
    "other": "OTHER",
    "charge": "LABOUR",
}

#: band -> the unit its quantities are written in
BAND_UOM = {
    "diamond": Uom.CT,
    "metal": Uom.GM,
    "stone": Uom.CT,
    "other": Uom.GM,
    "charge": Uom.PCS,
}

#: codes in the diamond band that are polki, not diamond
POLKI_PREFIXES = ("FPL", "PL")

METAL_BY_PREFIX = {"G": "GOLD", "S": "SILVER"}


def _category_for(line):
    if line.band == "diamond" and line.code.upper().startswith(POLKI_PREFIXES):
        return "POLKI"
    return BAND_CATEGORY[line.band]


def _minted_code(line):
    """The BI–BR band carries a name and no code, so we mint a stable one."""
    slug = re.sub(r"[^A-Z0-9]+", "-", line.code.upper()).strip("-")
    return f"OTH-{slug}"


def _metal_fields(line):
    """Metal, purity and the karat it was read from — or a reason we cannot."""
    from stock.models import MetalPurity

    code = line.code.upper()
    metal_id = METAL_BY_PREFIX.get(code[0]) if code else None
    if metal_id is None:
        return None, None, (
            f"{line.code!r} does not start with G or S, so its metal cannot be read. "
            "Pick the metal and purity by hand."
        )
    karat = re.search(r"(\d+K|\d{3})", line.name.upper() or code)
    if karat is None:
        return None, None, f"No karat or fineness in {line.name or line.code!r}."
    karat = karat.group(1)
    purity = MetalPurity.objects.filter(pk=karat).first()
    if purity is None:
        return None, None, (
            f"Purity {karat!r} is not in the purity table. Create it, or point "
            f"{line.code!r} at an existing purity."
        )
    return metal_id, purity, None


def material_fields(line):
    """``(kwargs for Material, problem)``. A problem blocks the import."""
    category = _category_for(line)
    fields = {
        "item_code": _minted_code(line) if line.band == "other" else line.code.upper(),
        "item_name": line.name or line.code,
        "category_id": category,
        "default_uom": BAND_UOM[line.band],
    }
    if category == "METAL":
        metal_id, purity, problem = _metal_fields(line)
        if problem:
            return fields, problem
        fields["metal_id"] = metal_id
        fields["purity_factor"] = purity.true_fineness
    return fields, None


def bom_basis_and_uom(line, material_category):
    """How a BOM line off this sheet is charged.

    Metal is BY_QTY on the sheet's own net weight, never BY_NET_METAL_WT:
    recosting snaps every BY_NET_METAL_WT line to the piece's *total* metal
    weight, which would double-count a piece carrying two metal lines.
    Charges are FLAT, where the base is 1 and the rate is the amount.
    """
    if material_category == "LABOUR":
        return ChargeBasis.FLAT, Uom.PCS
    if material_category == "METAL":
        return ChargeBasis.BY_QTY, Uom.GM
    if material_category in ("DIAMOND", "POLKI"):
        return ChargeBasis.BY_QTY, Uom.CT
    return ChargeBasis.BY_QTY, BAND_UOM.get(line.band, Uom.CT)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
source .venv/bin/activate && pytest stock/tests/test_import_ivy.py -v
```

Expected: all pass (9 parse + 11 guess).

- [ ] **Step 5: Commit**

```bash
git add stock/importers/guess.py stock/tests/test_import_ivy.py
git commit -m "Guess a new material from the band its code appeared in"
```

---

### Task 4: The ImportBatch model

**Files:**
- Modify: `stock/models.py` (append after `ActivityLog`)
- Create: `stock/migrations/00NN_importbatch.py` (generated)

**Interfaces:**
- Produces: `stock.models.ImportBatch` with fields `batch_id, media, decisions, status, images_done, images_total, result, created_by, created_at, finished_at` and the class attribute `ImportBatch.Status`.

- [ ] **Step 1: Add the model**

Append to `stock/models.py`:

```python
class ImportBatch(AppModel):
    """One run of the spreadsheet importer, from upload to the last image.

    The workbook itself is kept rather than the parse: re-reading 992 rows
    costs about two seconds, and staging tables for data thrown away at commit
    would be three models nobody ever queries again. What is worth keeping is
    the decisions a human made, and how far the images got.
    """

    class Status(models.TextChoices):
        UPLOADED = "UPLOADED", "Uploaded"
        REVIEWING = "REVIEWING", "Reviewing"
        COMMITTING = "COMMITTING", "Committing"
        IMAGES = "IMAGES", "Attaching images"
        DONE = "DONE", "Done"
        FAILED = "FAILED", "Failed"

    batch_id = models.AutoField(primary_key=True)
    media = models.ForeignKey(
        "mediahub.MediaAsset", on_delete=models.PROTECT, db_column="media_id", related_name="import_batches"
    )
    source = models.CharField(max_length=32, default="IVY")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UPLOADED)
    decisions = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    images_done = models.IntegerField(default=0)
    images_total = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        db_column="created_by", related_name="+",
    )
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "import_batch"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.source} import #{self.batch_id}"

    @property
    def images_pct(self):
        if not self.images_total:
            return 0
        return int(self.images_done * 100 / self.images_total)
```

- [ ] **Step 2: Generate and inspect the migration**

```bash
source .venv/bin/activate && python manage.py makemigrations stock -n importbatch
```

Read the generated file. It must contain exactly one `CreateModel` for
`ImportBatch` and no changes to any other model. If it proposes anything else,
something is out of sync — stop and investigate rather than applying it.

- [ ] **Step 3: Apply it and check it round-trips**

```bash
source .venv/bin/activate && python manage.py migrate stock
source .venv/bin/activate && python manage.py shell -c "
from stock.models import ImportBatch
print(ImportBatch.Status.UPLOADED, ImportBatch.objects.count())
"
```

Expected: `UPLOADED 0`.

- [ ] **Step 4: Commit**

```bash
git add stock/models.py stock/migrations/
git commit -m "Record an import as one batch row: the file, the decisions, the progress"
```

---

### Task 5: Analyse — the diff against the database

**Files:**
- Create: `stock/importers/analyse.py`
- Create: `stock/tests/test_import_commit.py`

**Interfaces:**
- Consumes: `ivy.ParsedPiece`, `guess.material_fields`
- Produces:
  - `Resolution` dataclass: `key, label, action, target, fields, problem, detail`
  - `Plan` dataclass: `materials, categories, collections, vendors, styles, pieces` (each a `list[Resolution]`), plus properties `blockers` and `counts`
  - `analyse(pieces) -> Plan`
  - `default_decisions(plan) -> dict`

Actions are the strings `"map"`, `"create"`, `"skip"`, `"update"`.

- [ ] **Step 1: Write the failing tests**

`stock/tests/test_import_commit.py`:

```python
"""Deciding what an import will do, and then doing it."""
import pytest

from stock.importers import analyse as analyse_mod, ivy
from stock.importers.analyse import analyse, default_decisions
from stock.models import Material, Piece, Style
from stock.tests.fixtures_ivy import build_workbook

pytestmark = pytest.mark.django_db


@pytest.fixture
def parsed():
    return ivy.parse(build_workbook())


@pytest.fixture
def import_reference(db, rates, materials):
    """What the shared fixtures do not cover but this workbook needs.

    ``materials`` creates METAL/DIAMOND/SETTING/LABOUR only, and ``rates``
    creates 18K and 925 only. The sample workbook carries a Foil Polki line
    and 14K gold, so without these the guesser produces a category that does
    not exist and a purity it is right to refuse.
    """
    from stock.models import MaterialCategory, MetalPurity

    for order, code in enumerate(["POLKI", "OTHER"], start=5):
        MaterialCategory.objects.get_or_create(
            code=code, defaults={"name": code.title(), "sort_order": order}
        )
    MetalPurity.objects.get_or_create(
        karat="14K",
        defaults={
            "sale_factor": "0.6000", "true_fineness": "0.5833",
            "metal": rates["gold"], "sort_order": 4,
        },
    )


def test_a_material_already_in_the_register_is_mapped_not_created(parsed, materials):
    """``materials`` fixture creates DRFGH SI-I among others."""
    Material.objects.get_or_create(
        item_code="DRFGH SI-I",
        defaults={"item_name": "Diamond", "category_id": "DIAMOND", "default_uom": "CT"},
    )
    plan = analyse(parsed)
    row = next(r for r in plan.materials if r.key == "DRFGH SI-I")
    assert row.action == "map"


def test_an_unknown_material_is_proposed_as_a_creation(parsed, materials, import_reference):
    plan = analyse(parsed)
    row = next(r for r in plan.materials if r.key == "SP01C")
    assert row.action == "create"
    assert row.fields["category_id"] == "SETTING"


def test_a_material_the_guesser_cannot_place_becomes_a_blocker(materials):
    """A workbook whose only metal is G12K, a purity that does not exist."""
    from stock.tests.fixtures_ivy import THREE_PRODUCTS, build_workbook as build

    header, block = THREE_PRODUCTS[0]
    broken = [(dict(header), [{**block[0], 37: "G12K", 38: "Gold12K"}])]
    plan = analyse(ivy.parse(build(products=broken)))
    row = next(r for r in plan.materials if r.key == "G12K")
    assert row.problem is not None
    assert plan.blockers


def test_categories_match_existing_ones_by_fuzzy_name(parsed):
    from stock.models import Category

    Category.objects.get_or_create(code="EAR", defaults={"name": "Earrings"})
    plan = analyse(parsed)
    row = next(r for r in plan.categories if r.key == "Earring")
    assert row.action == "map"
    assert row.target.name == "Earrings"


def test_an_unmatched_category_is_proposed_as_a_creation(parsed):
    plan = analyse(parsed)
    row = next(r for r in plan.categories if r.key == "Ring")
    # nothing named like 'Ring' exists in a bare test database
    assert row.action == "create"


def test_a_piece_already_present_defaults_to_untouched(parsed, piece, materials):
    """An existing jewel code is offered for update, but not ticked."""
    existing = Piece.objects.first()
    existing.jewel_code = "24P00095"
    existing.save(update_fields=["jewel_code"])
    plan = analyse(parsed)
    row = next(r for r in plan.pieces if r.key == "24P00095")
    assert row.action == "skip"
    assert row.detail  # the diff that explains what an update would change


def test_a_new_piece_defaults_to_being_created(parsed, materials):
    plan = analyse(parsed)
    row = next(r for r in plan.pieces if r.key == "24P00088")
    assert row.action == "create"


def test_default_decisions_round_trip_the_plan(parsed, materials):
    plan = analyse(parsed)
    decisions = default_decisions(plan)
    assert decisions["materials"]["SP01C"]["action"] == "create"
    assert decisions["pieces"]["24P00088"]["action"] == "create"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate && pytest stock/tests/test_import_commit.py -v
```

Expected: `ModuleNotFoundError: No module named 'stock.importers.analyse'`.

- [ ] **Step 3: Write the analyser**

`stock/importers/analyse.py`:

```python
"""What an import would do, worked out before it does any of it.

Nothing here writes. The review screen renders a Plan, the reviewer edits the
decisions that come out of it, and only then does ``commit`` run. Keeping the
diff pure is what makes the review screen safe to reload.
"""
import re
from dataclasses import dataclass, field

from stock.importers import guess
from stock.models import Category, Collection, Material, Piece, Style, Vendor


@dataclass
class Resolution:
    """One decision: what the sheet said, and what we propose doing about it."""
    key: str
    label: str = ""
    action: str = "create"          # map | create | skip | update
    target: object = None           # the existing row, when action is map
    fields: dict = field(default_factory=dict)
    problem: str = None             # non-None blocks the commit
    detail: str = ""                # human-readable extra, e.g. a diff


@dataclass
class Plan:
    materials: list = field(default_factory=list)
    categories: list = field(default_factory=list)
    collections: list = field(default_factory=list)
    vendors: list = field(default_factory=list)
    styles: list = field(default_factory=list)
    pieces: list = field(default_factory=list)

    @property
    def sections(self):
        return {
            "materials": self.materials,
            "categories": self.categories,
            "collections": self.collections,
            "vendors": self.vendors,
            "styles": self.styles,
            "pieces": self.pieces,
        }

    @property
    def blockers(self):
        """Every unresolved row, across every section."""
        return [r for rows in self.sections.values() for r in rows if r.problem]

    @property
    def counts(self):
        out = {}
        for name, rows in self.sections.items():
            out[name] = {
                "total": len(rows),
                "map": sum(1 for r in rows if r.action == "map"),
                "create": sum(1 for r in rows if r.action == "create"),
                "skip": sum(1 for r in rows if r.action == "skip"),
                "blocked": sum(1 for r in rows if r.problem),
            }
        return out


def _norm(name):
    """Loose enough that 'Earring' finds 'Earrings' and 'Ring' finds 'Rings'."""
    return re.sub(r"[^a-z]", "", (name or "").lower())


def _fuzzy(name, existing):
    """An existing row whose name contains, or is contained by, this one."""
    target = _norm(name)
    if not target:
        return None
    for row in existing:
        candidate = _norm(row.name)
        if candidate == target or target in candidate or candidate in target:
            return row
    return None


def _material_rows(pieces):
    seen, rows = {}, []
    known = {m.item_code: m for m in Material.objects.all()}
    for piece in pieces:
        for line in piece.lines:
            fields, problem = guess.material_fields(line)
            code = fields["item_code"]
            if code in seen:
                continue
            seen[code] = True
            existing = known.get(code)
            rows.append(Resolution(
                key=line.code,
                label=line.name or line.code,
                action="map" if existing else "create",
                target=existing,
                fields=fields,
                problem=None if existing else problem,
                detail=line.band,
            ))
    return sorted(rows, key=lambda r: (r.problem is None, r.detail, r.key))


def _named_rows(values, model, create_code=True):
    existing = list(model.objects.all())
    rows = []
    for value in sorted({v for v in values if v}):
        match = _fuzzy(value, existing)
        rows.append(Resolution(
            key=value,
            label=value,
            action="map" if match else "create",
            target=match,
            fields={"name": value, "code": _norm(value).upper()[:32]} if create_code else {"name": value},
            detail=f"→ {match.name}" if match else "",
        ))
    return rows


def _style_rows(pieces):
    known = set(Style.objects.values_list("style_code", flat=True))
    rows, seen = [], set()
    for piece in pieces:
        if piece.style_code in seen:
            continue
        seen.add(piece.style_code)
        rows.append(Resolution(
            key=piece.style_code,
            label=piece.style_code,
            action="map" if piece.style_code in known else "create",
            detail=piece.category,
        ))
    return rows


def _piece_diff(existing, parsed):
    """The fields an update would change, as one readable line."""
    changes = []
    for label, was, now in (
        ("purity", existing.metal_purity, parsed.metal_purity),
        ("sub-category", existing.sub_category, parsed.sub_category),
        ("cost", existing.src_cost_price, parsed.src_cost_price),
        ("sale", existing.src_sale_price, parsed.src_sale_price),
    ):
        if now and str(was or "") != str(now):
            changes.append(f"{label} {was or '—'} → {now}")
    return "; ".join(changes)


def _piece_rows(pieces):
    known = {p.jewel_code: p for p in Piece.objects.all()}
    rows = []
    for piece in pieces:
        existing = known.get(piece.jewel_code)
        rows.append(Resolution(
            key=piece.jewel_code,
            label=f"{piece.jewel_code} · {piece.style_code}",
            # an existing piece is offered, never ticked: see the spec
            action="skip" if existing else "create",
            target=existing,
            detail=_piece_diff(existing, piece) if existing else piece.category,
        ))
    return rows


def analyse(pieces):
    """Everything the import would touch, decided but not done."""
    return Plan(
        materials=_material_rows(pieces),
        categories=_named_rows({p.category for p in pieces}, Category),
        collections=_named_rows({p.collection for p in pieces}, Collection),
        vendors=_named_rows({p.vendor for p in pieces}, Vendor),
        styles=_style_rows(pieces),
        pieces=_piece_rows(pieces),
    )


def default_decisions(plan):
    """The plan's own proposals, in the shape the review form posts back."""
    return {
        section: {
            row.key: {
                "action": row.action,
                "target": getattr(row.target, "pk", None),
                "fields": row.fields,
            }
            for row in rows
        }
        for section, rows in plan.sections.items()
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
source .venv/bin/activate && pytest stock/tests/test_import_commit.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add stock/importers/analyse.py stock/tests/test_import_commit.py
git commit -m "Work out what an import would do before it does any of it"
```

---

### Task 6: Commit — writing the plan

**Files:**
- Create: `stock/importers/commit.py`
- Modify: `stock/tests/test_import_commit.py` (append)

**Interfaces:**
- Consumes: `ivy.ParsedPiece`, `analyse.Plan`, `guess.bom_basis_and_uom`, `services.set_bom`, `services.new_bom_version`, `services.receive_piece`
- Produces:
  - `commit(pieces, decisions, user, location=None) -> dict` with keys
    `materials_created, styles_created, pieces_created, pieces_updated, pieces_skipped, lines_written, variances`
  - `attach_images(batch, pieces, limit=10) -> int` (returns how many were done this call)

- [ ] **Step 1: Write the failing tests**

Append to `stock/tests/test_import_commit.py`:

```python
# ── committing ───────────────────────────────────────────────────────────
from decimal import Decimal

from stock.importers.commit import attach_images, commit
from stock.models import BomLine, BomVersion, ImportBatch


def test_commit_creates_materials_styles_and_pieces(parsed, materials, import_reference, admin_user_):
    plan = analyse(parsed)
    result = commit(parsed, default_decisions(plan), admin_user_)
    assert result["pieces_created"] == 3
    assert Piece.objects.filter(jewel_code="24P00088").exists()
    assert Style.objects.filter(style_code="ER00502").exists()


def test_imported_pieces_carry_what_the_source_system_said(parsed, materials, import_reference, admin_user_):
    plan = analyse(parsed)
    commit(parsed, default_decisions(plan), admin_user_)
    piece = Piece.objects.get(jewel_code="24P00111")
    assert piece.src_system == "IVY"
    assert piece.src_cost_price == Decimal("84438.00")
    assert piece.src_net_wt_gm == Decimal("8.228")


def test_every_material_line_lands_on_the_bom(parsed, materials, import_reference, admin_user_):
    plan = analyse(parsed)
    commit(parsed, default_decisions(plan), admin_user_)
    piece = Piece.objects.get(jewel_code="24P00111")
    lines = BomLine.objects.filter(piece=piece, version_no=piece.current_bom_version)
    assert lines.count() == 6          # 3 diamond + 1 metal + 2 stone


def test_metal_lines_keep_their_own_weight(parsed, materials, import_reference, admin_user_):
    """BY_NET_METAL_WT would have snapped this to the piece total."""
    plan = analyse(parsed)
    commit(parsed, default_decisions(plan), admin_user_)
    piece = Piece.objects.get(jewel_code="24P00111")
    metal = BomLine.objects.get(
        piece=piece, version_no=piece.current_bom_version, material__category="METAL"
    )
    assert metal.qty_value == Decimal("8.2280")
    assert metal.basis == "BY_QTY"


def test_pieces_land_not_received_when_no_location_is_chosen(parsed, materials, import_reference, admin_user_):
    plan = analyse(parsed)
    commit(parsed, default_decisions(plan), admin_user_)
    piece = Piece.objects.get(jewel_code="24P00088")
    assert piece.stock_state == "NOT_RECEIVED"
    assert piece.location_id is None


def test_choosing_a_location_receives_the_piece(parsed, materials, import_reference, admin_user_, locations):
    from stock.models import Location

    plan = analyse(parsed)
    where = Location.objects.first()
    commit(parsed, default_decisions(plan), admin_user_, location=where)
    piece = Piece.objects.get(jewel_code="24P00088")
    assert piece.stock_state == "IN_STOCK"
    assert piece.location_id == where.pk


def test_an_existing_piece_is_left_alone_when_skipped(parsed, piece, materials, import_reference, admin_user_):
    existing = Piece.objects.first()
    existing.jewel_code = "24P00095"
    existing.sub_category = "UNTOUCHED"
    existing.save(update_fields=["jewel_code", "sub_category"])
    plan = analyse(parsed)
    result = commit(parsed, default_decisions(plan), admin_user_)
    existing.refresh_from_db()
    assert existing.sub_category == "UNTOUCHED"
    assert result["pieces_skipped"] == 1


def test_updating_an_existing_piece_adds_a_version_and_keeps_the_old_one(
    parsed, piece, materials, import_reference, admin_user_
):
    existing = Piece.objects.first()
    existing.jewel_code = "24P00095"
    existing.save(update_fields=["jewel_code"])
    was = existing.current_bom_version
    plan = analyse(parsed)
    decisions = default_decisions(plan)
    decisions["pieces"]["24P00095"]["action"] = "update"
    result = commit(parsed, decisions, admin_user_)

    existing.refresh_from_db()
    assert result["pieces_updated"] == 1
    assert existing.current_bom_version == was + 1
    # the old version survives, and is no longer current
    old = BomVersion.objects.get(piece=existing, version_no=was)
    assert old.is_current is False
    new = BomVersion.objects.get(piece=existing, version_no=was + 1)
    assert new.is_current is True
    assert new.reason == "CORRECTION"


def test_images_are_attached_in_chunks_and_are_resumable(
    parsed, materials, import_reference, admin_user_, settings, tmp_path
):
    """Each chunk does its share, and the counter is what makes it resumable."""
    from mediahub.models import MediaAsset

    plan = analyse(parsed)
    commit(parsed, default_decisions(plan), admin_user_)

    # the fixture workbook has no embedded images, so plant one
    parsed[0].image = b"\xff\xd8\xff\xe0fake-jpeg"
    batch = ImportBatch.objects.create(
        media=MediaAsset.objects.create(file_name="x.xlsx"),
        images_total=1,
        created_by=admin_user_,
    )
    done = attach_images(batch, parsed, limit=10)
    batch.refresh_from_db()
    assert done == 1
    assert batch.images_done == 1
    # running again does nothing, rather than attaching a second copy
    assert attach_images(batch, parsed, limit=10) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate && pytest stock/tests/test_import_commit.py -k "commit or images or metal or location or version" -v
```

Expected: `ImportError: cannot import name 'commit' from 'stock.importers.commit'`.

- [ ] **Step 3: Write the committer**

`stock/importers/commit.py`:

```python
"""Writing an approved plan.

Two phases, deliberately separated. The catalogue goes in inside one
transaction, so a failure leaves the database exactly as it was. The images do
not: S3 is not transactional, and one refused upload should not roll back 373
pieces. An orphaned object in the bucket is harmless; a half-imported
catalogue nobody can describe is not.
"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from stock import services
from stock.enums import BomChangeReason
from stock.importers import guess
from stock.models import Category, Collection, Material, Piece, Style, Vendor

#: how far our recost may drift from IVY's own total before we mention it
VARIANCE_TOLERANCE = 1


def _decision(decisions, section, key):
    return (decisions.get(section) or {}).get(key) or {}


def _resolve_named(decisions, section, model, cache):
    """Create-or-map every name in a section once, and remember the result."""
    for key, choice in (decisions.get(section) or {}).items():
        if key in cache:
            continue
        if choice.get("action") == "map" and choice.get("target"):
            cache[key] = model.objects.filter(pk=choice["target"]).first()
        elif choice.get("action") == "create":
            fields = dict(choice.get("fields") or {})
            name = fields.pop("name", key)
            code = fields.pop("code", None)
            lookup = {"code": code} if code else {"name": name}
            cache[key], _ = model.objects.get_or_create(**lookup, defaults={"name": name, **fields})
        else:
            cache[key] = None
    return cache


def _resolve_materials(decisions):
    """code as written in the sheet -> the Material it means."""
    resolved = {}
    for key, choice in (decisions.get("materials") or {}).items():
        fields = dict(choice.get("fields") or {})
        code = fields.get("item_code", key)
        if choice.get("action") == "map":
            resolved[key] = Material.objects.filter(item_code=code).first()
            continue
        existing = Material.objects.filter(item_code=code).first()
        if existing:
            resolved[key] = existing
            continue
        if fields.get("category_id") == "METAL" and not fields.get("metal_id"):
            # the view blocks this too; refusing here as well keeps a bad
            # decisions blob from reaching material_metal_required as an
            # IntegrityError halfway through the transaction
            raise ValueError(
                f"{code} is a metal with no metal resolved. Set its metal and purity first."
            )
        resolved[key] = Material.objects.create(**fields)
    return resolved


def _bom_lines(parsed, materials):
    """The sheet's lines in the shape ``services.set_bom`` wants."""
    lines = []
    for line in parsed.lines:
        material = materials.get(line.code)
        if material is None:
            continue
        basis, uom = guess.bom_basis_and_uom(line, material.category_id)
        qty = line.qty
        if basis == "FLAT":
            qty = None
        lines.append({
            "material": material,
            "size_band": line.size_band,
            "pcs": line.pcs,
            "qty_value": qty,
            "qty_uom": uom,
            "basis": basis,
            # FLAT means base 1, so the sheet's amount is the rate
            "cost_rate": line.cost_amount if basis == "FLAT" else line.cost_rate,
            "sale_rate": line.sale_amount if basis == "FLAT" else line.sale_rate,
            "off_chart": True,
        })
    return lines


def _apply_header(piece, parsed, style):
    piece.style = style
    piece.sub_category = parsed.sub_category or None
    piece.metal_purity = parsed.metal_purity or None
    piece.diamond_quality = parsed.diamond_quality or None
    piece.stock_type = parsed.stock_type or "FINISH_GOODS"
    piece.fg_date = parsed.fg_date
    piece.remarks = parsed.remarks or None
    piece.src_system = "IVY"
    piece.src_ref = parsed.sr_no or None
    piece.src_cost_price = parsed.src_cost_price
    piece.src_sale_price = parsed.src_sale_price
    piece.src_net_wt_gm = parsed.src_net_wt_gm
    piece.updated_at = timezone.now()


@transaction.atomic
def commit(pieces, decisions, user, location=None):
    """Write the approved plan. One transaction: it all lands, or none does."""
    materials = _resolve_materials(decisions)
    categories = _resolve_named(decisions, "categories", Category, {})
    collections = _resolve_named(decisions, "collections", Collection, {})
    vendors = _resolve_named(decisions, "vendors", Vendor, {})

    result = {
        "materials_created": sum(
            1 for c in (decisions.get("materials") or {}).values() if c.get("action") == "create"
        ),
        "styles_created": 0,
        "pieces_created": 0,
        "pieces_updated": 0,
        "pieces_skipped": 0,
        "lines_written": 0,
        "variances": [],
    }

    for parsed in pieces:
        choice = _decision(decisions, "pieces", parsed.jewel_code)
        action = choice.get("action", "create")
        existing = Piece.objects.filter(jewel_code=parsed.jewel_code).first()

        if existing and action != "update":
            result["pieces_skipped"] += 1
            continue

        style = Style.objects.filter(style_code=parsed.style_code).first()
        if style is None:
            category = categories.get(parsed.category)
            if category is None:
                # Style.category is NOT NULL PROTECT: a skipped category would
                # abort the whole transaction here rather than skip one row.
                raise ValueError(
                    f"{parsed.jewel_code} needs category {parsed.category!r}, which was "
                    "set to skip. Map it or create it."
                )
            style = Style.objects.create(
                style_code=parsed.style_code,
                category=category,
                collection=collections.get(parsed.collection),
                created_by=user,
            )
            result["styles_created"] += 1

        if existing:
            _apply_header(existing, parsed, style)
            existing.save()
            services.new_bom_version(
                user, existing, BomChangeReason.CORRECTION, note="IVY import"
            )
            piece = existing
            result["pieces_updated"] += 1
        else:
            piece = Piece(jewel_code=parsed.jewel_code, created_by=user)
            _apply_header(piece, parsed, style)
            piece.vendor = vendors.get(parsed.vendor)
            piece.save()
            result["pieces_created"] += 1

        lines = _bom_lines(parsed, materials)
        if lines:
            services.set_bom(user, piece, lines, reason=BomChangeReason.INITIAL, note="IVY import")
            result["lines_written"] += len(lines)

        if location is not None and piece.stock_state == "NOT_RECEIVED":
            services.receive_piece(user, piece, location, moved_at=parsed.inw_date)

        # our recost against IVY's own total — a big gap means a rule is wrong
        version = piece.current_bom()
        if version and parsed.src_cost_price is not None and version.total_cost_price is not None:
            drift = abs(version.total_cost_price - parsed.src_cost_price)
            if drift > VARIANCE_TOLERANCE:
                result["variances"].append(
                    {"jewel_code": piece.jewel_code, "ours": str(version.total_cost_price),
                     "theirs": str(parsed.src_cost_price), "drift": str(drift)}
                )
    return result


def attach_images(batch, pieces, limit=10):
    """Upload the next few images. Returns how many this call got through.

    Runs outside the commit transaction, and is driven a chunk at a time by the
    browser, so a closed tab resumes from ``batch.images_done`` rather than
    starting over or double-attaching.
    """
    from mediahub.models import MediaAsset
    from mediahub.services import attach_uploads

    with_images = [p for p in pieces if p.image]
    todo = with_images[batch.images_done:batch.images_done + limit]
    if not todo:
        return 0

    done, refused = 0, list((batch.result or {}).get("images_refused", []))
    for parsed in todo:
        piece = Piece.objects.filter(jewel_code=parsed.jewel_code).first()
        if piece is None:
            done += 1
            continue
        if MediaAsset.objects.filter(scope="piece", scope_id=str(piece.pk)).exists():
            done += 1
            continue
        upload = SimpleUploadedFile(
            f"{parsed.jewel_code}.jpg", parsed.image, content_type="image/jpeg"
        )
        saved, rejected = attach_uploads([upload], "piece", piece.pk, batch.created_by)
        refused.extend(rejected)
        done += 1

    batch.images_done += done
    batch.result = {**(batch.result or {}), "images_refused": refused}
    batch.save(update_fields=["images_done", "result"])
    return done
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
source .venv/bin/activate && pytest stock/tests/test_import_commit.py -v
```

Expected: all pass. If `test_images_are_attached_in_chunks_and_are_resumable`
fails on storage configuration, the bucket is not set in the test environment —
mock `mediahub.services.attach_uploads` in that one test with
`monkeypatch.setattr` returning `([], [])` rather than weakening the code.

- [ ] **Step 5: Commit**

```bash
git add stock/importers/commit.py stock/tests/test_import_commit.py
git commit -m "Write an approved import: catalogue in one transaction, images after"
```

---

### Task 7: Views, URLs and the review screen

**Files:**
- Modify: `stock/views.py` (append near the `data` view)
- Modify: `stock/urls.py`
- Modify: `stock/templates/stock/data.html`
- Create: `stock/templates/stock/import_review.html`
- Create: `stock/templates/stock/_import_progress.html`

**Interfaces:**
- Consumes: `importers.parse`, `importers.analyse`, `importers.commit`, `commit.attach_images`, `ImportBatch`
- Produces: named routes `stock:import_upload`, `stock:import_review`, `stock:import_commit`, `stock:import_images`

- [ ] **Step 1: Add the routes**

In `stock/urls.py`, after the `data` path:

```python
    path("data/import/", views.import_upload, name="import_upload"),
    path("data/import/<int:batch_id>/", views.import_review, name="import_review"),
    path("data/import/<int:batch_id>/commit/", views.import_commit, name="import_commit"),
    path("data/import/<int:batch_id>/images/", views.import_images, name="import_images"),
```

- [ ] **Step 2: Add the views**

In `stock/views.py`, after the `data` view. Add
`from stock.importers import analyse as analyse_import, commit as commit_import, ivy`
and `from stock.models import ImportBatch` to the imports at the top.

```python
def _batch_workbook(batch):
    """The stored workbook as a file object, straight from the bucket."""
    from mediahub import storage

    return io.BytesIO(storage.get_bytes(batch.media.storage_key))


@login_required
@tab_required("admin")
@require_POST
def import_upload(request):
    """Take the workbook, check it is the right one, and open a batch."""
    from mediahub.services import attach_uploads

    upload = request.FILES.get("workbook")
    if upload is None:
        messages.error(request, "Choose a workbook first.")
        return redirect("stock:data")

    problems = ivy.header_problems(upload)
    if problems:
        messages.error(request, f"That is not an IVY stock export. {problems[0]}")
        return redirect("stock:data")

    upload.seek(0)
    saved, refused = attach_uploads([upload], "import", "workbook", request.user)
    if not saved:
        messages.error(request, f"Could not store the file. {'; '.join(refused)}")
        return redirect("stock:data")

    batch = ImportBatch.objects.create(media=saved[0], created_by=request.user)
    return redirect("stock:import_review", batch_id=batch.batch_id)


@login_required
@tab_required("admin")
def import_review(request, batch_id):
    """Everything the import would do, with the guesses pre-filled."""
    batch = get_object_or_404(ImportBatch, pk=batch_id)
    pieces = ivy.parse(_batch_workbook(batch))
    plan = analyse_import.analyse(pieces)
    if not batch.decisions:
        batch.decisions = analyse_import.default_decisions(plan)
        batch.status = ImportBatch.Status.REVIEWING
        batch.save(update_fields=["decisions", "status"])
    return render(request, "stock/import_review.html", {
        "nav": "data",
        "batch": batch,
        "plan": plan,
        "counts": plan.counts,
        "blockers": plan.blockers,
        "locations": Location.objects.filter(is_active=True),
    })


@login_required
@tab_required("admin")
@require_POST
def import_commit(request, batch_id):
    """Apply the reviewed decisions, then hand over to the image loop."""
    batch = get_object_or_404(ImportBatch, pk=batch_id)
    pieces = ivy.parse(_batch_workbook(batch))
    plan = analyse_import.analyse(pieces)
    if plan.blockers:
        messages.error(request, f"{len(plan.blockers)} decisions still need resolving.")
        return redirect("stock:import_review", batch_id=batch.batch_id)

    decisions = _decisions_from_post(request.POST, plan)
    location = Location.objects.filter(pk=request.POST.get("location") or 0).first()

    batch.decisions = decisions
    batch.status = ImportBatch.Status.COMMITTING
    batch.save(update_fields=["decisions", "status"])
    try:
        result = commit_import.commit(pieces, decisions, request.user, location=location)
    except Exception as error:                      # the transaction already rolled back
        batch.status = ImportBatch.Status.FAILED
        batch.result = {"error": str(error)}
        batch.save(update_fields=["status", "result"])
        messages.error(request, f"Import failed, nothing was written. {error}")
        return redirect("stock:import_review", batch_id=batch.batch_id)

    batch.result = result
    batch.images_total = sum(1 for p in pieces if p.image)
    batch.status = ImportBatch.Status.IMAGES if batch.images_total else ImportBatch.Status.DONE
    batch.finished_at = None if batch.images_total else timezone.now()
    batch.save(update_fields=["result", "images_total", "status", "finished_at"])
    return render(request, "stock/_import_progress.html", {"batch": batch})


@login_required
@tab_required("admin")
@require_POST
def import_images(request, batch_id):
    """One chunk of image uploads, then the bar that asks for the next."""
    batch = get_object_or_404(ImportBatch, pk=batch_id)
    if batch.images_done < batch.images_total:
        pieces = ivy.parse(_batch_workbook(batch))
        commit_import.attach_images(batch, pieces, limit=10)
        batch.refresh_from_db()
    if batch.images_done >= batch.images_total and batch.status != ImportBatch.Status.DONE:
        batch.status = ImportBatch.Status.DONE
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "finished_at"])
    return render(request, "stock/_import_progress.html", {"batch": batch})


def _decisions_from_post(post, plan):
    """Turn the review form back into the decisions dict, plan as the default."""
    decisions = analyse_import.default_decisions(plan)
    for section, rows in decisions.items():
        for key, choice in rows.items():
            field = f"{section}:{key}"
            if field in post:
                choice["action"] = post.get(field)
            elif section == "pieces" and choice["action"] == "skip":
                choice["action"] = "update" if post.get(f"update:{key}") else "skip"
    return decisions
```

Check that `mediahub.storage` exposes a `get_bytes(key)`. If it does not, add
it beside `put_bytes` in `mediahub/storage.py`:

```python
def get_bytes(key):
    """One object's bytes, for re-reading something we stored ourselves."""
    return _client().get_object(Bucket=settings.MEDIA_BUCKET, Key=key)["Body"].read()
```

- [ ] **Step 3: Add the upload form to the Import/Export page**

In `stock/templates/stock/data.html`, replace the closing `</div>` of the
"Bringing a spreadsheet in" card with an upload form ahead of it:

```html
  <form method="post" action="{% url 'stock:import_upload' %}"
        enctype="multipart/form-data" class="row" style="margin-top:14px">
    {% csrf_token %}
    <input type="file" name="workbook" accept=".xlsx" required>
    <button class="btn primary" type="submit">Read the workbook</button>
  </form>
  <p class="hint">Nothing is written until you have seen what it would do.</p>
</div>
```

- [ ] **Step 4: Write the review template**

`stock/templates/stock/import_review.html`:

```html
{% extends "base.html" %}
{% block title %}Review import · Nornament{% endblock %}
{% block heading %}Review import #{{ batch.batch_id }}{% endblock %}
{% block content %}
{% if blockers %}
<div class="card" style="border-color:var(--bad)">
  <h3>{{ blockers|length }} decisions need you</h3>
  <p class="hint">The import cannot run until each of these is resolved.</p>
  <table><tbody>
    {% for row in blockers %}
    <tr><td><b>{{ row.key }}</b></td><td>{{ row.label }}</td><td class="dim">{{ row.problem }}</td></tr>
    {% endfor %}
  </tbody></table>
</div>
{% endif %}

<form method="post" action="{% url 'stock:import_commit' batch.batch_id %}">
  {% csrf_token %}
  {% for section, rows in plan.sections.items %}
  <details class="card" {% if section == 'pieces' %}open{% endif %}>
    <summary><b>{{ section|title }}</b> — {{ rows|length }} rows</summary>
    <table><thead><tr><th>From the sheet</th><th>What happens</th><th></th></tr></thead><tbody>
      {% for row in rows %}
      <tr{% if row.problem %} class="bad"{% endif %}>
        <td><b>{{ row.key }}</b><br><span class="dim">{{ row.label }}</span></td>
        <td>
          {% if section == 'pieces' and row.target %}
            <label><input type="checkbox" name="update:{{ row.key }}"> update</label>
          {% else %}
            <select name="{{ section }}:{{ row.key }}">
              <option value="create" {% if row.action == 'create' %}selected{% endif %}>create</option>
              <option value="map" {% if row.action == 'map' %}selected{% endif %}>map to existing</option>
              <option value="skip" {% if row.action == 'skip' %}selected{% endif %}>skip</option>
            </select>
          {% endif %}
        </td>
        <td class="dim">{{ row.problem|default:row.detail }}</td>
      </tr>
      {% endfor %}
    </tbody></table>
  </details>
  {% endfor %}

  <div class="card">
    <h3>Receive into</h3>
    <p class="hint">Leave blank and new pieces stay <b>Not received</b> with no location.</p>
    <select name="location">
      <option value="">— not received —</option>
      {% for location in locations %}
      <option value="{{ location.pk }}">{{ location.name }}</option>
      {% endfor %}
    </select>
    <div class="row" style="margin-top:14px">
      <button class="btn primary" type="submit" {% if blockers %}disabled{% endif %}>
        Import
      </button>
      <a class="btn" href="{% url 'stock:data' %}">Cancel</a>
    </div>
  </div>
</form>
{% endblock %}
```

- [ ] **Step 5: Write the progress partial**

`stock/templates/stock/_import_progress.html`. The partial re-requests itself
until the counter catches up, which is what makes the bar honest — every
increment is work that already committed.

```html
<div class="card" id="import-progress">
  {% if batch.status == 'DONE' %}
    <h3>Import finished</h3>
    <p>{{ batch.result.pieces_created }} pieces created,
       {{ batch.result.pieces_updated }} updated,
       {{ batch.result.pieces_skipped }} left alone,
       {{ batch.result.lines_written }} material lines,
       {{ batch.images_done }} images.</p>
    {% if batch.result.variances %}
    <div class="note"><b>{{ batch.result.variances|length }} pieces cost differently here
      than in IVY.</b> Their rates are on the BOM; the source figure is kept beside it.</div>
    {% endif %}
    {% if batch.result.images_refused %}
    <div class="note"><b>{{ batch.result.images_refused|length }} images were refused.</b>
      {{ batch.result.images_refused|join:", " }}</div>
    {% endif %}
    <a class="btn primary" href="{% url 'stock:piece_list' %}">See the pieces</a>
  {% else %}
    <h3>Attaching images</h3>
    <progress value="{{ batch.images_done }}" max="{{ batch.images_total }}"></progress>
    <p class="dim">{{ batch.images_done }} of {{ batch.images_total }} ({{ batch.images_pct }}%)</p>
    <div hx-post="{% url 'stock:import_images' batch.batch_id %}"
         hx-target="#import-progress"
         hx-swap="outerHTML"
         hx-trigger="load delay:100ms"></div>
  {% endif %}
</div>
```

- [ ] **Step 6: Check the whole flow by hand**

```bash
source .venv/bin/activate && python manage.py runserver
```

Open `/stock/data/`, upload `/Users/preet/Downloads/nornament stock.xlsx`.
Expected: the review screen lists 224 materials, 9 categories, 373 pieces, and
four blockers (`G12K`, `S995`, `G18%`, `CJ`) with the Import button disabled.

- [ ] **Step 7: Commit**

```bash
git add stock/views.py stock/urls.py stock/templates/stock/
git commit -m "Upload, review and commit an import from the browser"
```

---

### Task 8: View tests

**Files:**
- Modify: `stock/tests/test_import_commit.py` (append)

**Interfaces:**
- Consumes: the four routes from Task 7.

- [ ] **Step 1: Write the failing tests**

Append to `stock/tests/test_import_commit.py`:

```python
# ── the screens ──────────────────────────────────────────────────────────
from django.urls import reverse


def test_a_workbook_with_wrong_headers_is_refused_at_upload(client, admin_user_):
    import io
    from openpyxl import Workbook

    book = Workbook()
    book.active["A1"] = "not an IVY export"
    stream = io.BytesIO()
    book.save(stream)
    stream.seek(0)
    stream.name = "wrong.xlsx"

    client.force_login(admin_user_)
    response = client.post(reverse("stock:import_upload"), {"workbook": stream}, follow=True)
    assert ImportBatch.objects.count() == 0
    assert b"not an IVY stock export" in response.content


def test_a_non_admin_cannot_open_the_importer(client, sales_user):
    client.force_login(sales_user)
    response = client.post(reverse("stock:import_upload"), {})
    assert response.status_code == 403


def test_the_progress_partial_stops_asking_once_it_is_done(client, admin_user_):
    from mediahub.models import MediaAsset

    batch = ImportBatch.objects.create(
        media=MediaAsset.objects.create(file_name="x.xlsx"),
        status=ImportBatch.Status.DONE,
        images_done=3,
        images_total=3,
        result={"pieces_created": 3, "pieces_updated": 0, "pieces_skipped": 0, "lines_written": 9},
        created_by=admin_user_,
    )
    client.force_login(admin_user_)
    response = client.post(reverse("stock:import_images", args=[batch.batch_id]))
    assert b"hx-trigger" not in response.content
    assert b"Import finished" in response.content
```

- [ ] **Step 2: Run them to verify they fail**

```bash
source .venv/bin/activate && pytest stock/tests/test_import_commit.py -k "upload or admin or partial" -v
```

Expected: `NoReverseMatch` if Task 7's routes are missing, otherwise failures
describing the missing behaviour.

- [ ] **Step 3: Fix whatever the tests catch**

No new code is planned here — Task 7 should already satisfy these. If a test
fails, the bug is in Task 7's views and belongs fixed there.

- [ ] **Step 4: Run the whole suite**

```bash
source .venv/bin/activate && pytest -q
```

Expected: everything passes, including the pre-existing suite. A pre-existing
failure that this work did not cause should be reported, not silently fixed.

- [ ] **Step 5: Commit**

```bash
git add stock/tests/test_import_commit.py
git commit -m "Cover the import screens: bad workbook, permissions, progress"
```

---

## Not in this plan

- A generic column mapper. The spec rules it out: the band layout cannot be expressed as a flat column map.
- A task queue. Browser-driven chunking covers the one long phase with no new infrastructure.
- Undo. BOM versioning already makes piece changes reversible, and skipped pieces are untouched by construction.
