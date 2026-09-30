"""The diamond register (``Dia_Stock_Nitesh.xlsx``): flat sheets, one row per line.

FANCY FINAL, Round_LB_LC and Round_RW are read; FANCY holds the same lines with
older rates and is not. The file's own Shape, Colour and Clarity columns are
mapped onto the master lists here, so a new item code arrives already read.
A header row can repeat mid-sheet; total rows have no weight and are skipped.
"""
import re
from dataclasses import dataclass
from decimal import Decimal

from openpyxl import load_workbook

SHEETS = ("FANCY FINAL", "Round_LB_LC", "Round_RW")

CATEGORY_NAMES = {"Diamond": "Natural Diamond", "HPHT Diamond": "HPHT Lab Grown", "Lab Grown": "Lab Grown (CVD?)",
                  "Solitare": "Solitaire", "Foil Polki": "Foil Polki"}

#: header text, lower-cased → field
HEADERS = {"code": "code", "shape": "shape", "gati code": "item_code", "colour": "colour", "clarity": "clarity",
           "seive/size": "size", "seive": "size", "pieces": "pcs", "weight": "ct", "rate": "rate",
           "amount": "amount", "price": "price", "category": "category"}
#: LB is M-N and LC is K-L — the owner, 2026-09-30
COLOURS = {"EF": "E-F", "GH": "G-H", "FGH": "F-G-H", "IJ": "I-J", "KL": "K-L", "MN": "M-N", "LB": "M-N", "LC": "K-L"}
SHAPES = {"ASSCHER": "Asscher", "TAPERS BUGGUTTE": "Tapered Baguette", "TRIANGLE": "Trillion",
          "PIECUT (EM)": "Pie Cut Emerald", "PIECUT (OV)": "Pie Cut Oval", "PIECUT (PEAR)": "Pie Cut Pear",
          "PIECUT (STAR)": "Pie Cut Star", "MIX SHAPES": "Mix"}
#: a Code like M0.10-0.15 is a carat band, written the way dia_rules.size_band reads one
BAND_CODE = re.compile(r"^([A-Z]{1,3})\s*(\d*\.\d+)-(\d*\.\d+)$")


@dataclass
class Row:
    src: str
    category: str
    batch_no: str
    item_code: str
    size_text: str
    ct: Decimal
    band_text: str = ""
    shape: str = ""
    colour: str = ""
    clarity: str = ""
    pcs: int = None
    rate: Decimal = None


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"\s+", " ", str(value)).strip()


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


def _size(value):
    """A bare number in the sieve column is a sieve: 10 is +10."""
    number = _number(value)
    if number is not None and number == number.to_integral_value():
        return f"+{int(number)}"
    return _text(value)


def _clarity(value):
    return "" if value.lower() == "fancy" else re.sub(r"[\s-]+", "-", value).upper()


def _colour(value, fancy):
    if fancy:
        return f"Fancy {value.title()}" if value else ""
    return COLOURS.get(value.upper(), value)


def _rate(money, ct):
    """Per carat. Round_LB_LC has its Amount and PRICE headers swapped, so the rate
    is whichever money value, times the weight, gives another; else the Rate column."""
    values = [v for v in money.values() if v is not None]
    if ct:
        for i, rate in enumerate(values):
            for j, total in enumerate(values):
                if i != j and abs(rate * ct - total) <= max(Decimal("1"), total / 200):
                    return rate
    return money.get("rate")


def _sheets(workbook):
    return [name for name in SHEETS if name in workbook.sheetnames]


def header_problems(fileobj):
    """Why this is not the diamond register, or ``[]``."""
    try:
        workbook = load_workbook(fileobj, read_only=True, data_only=True)
    except Exception as error:
        return [f"It does not open as a workbook ({error})."]
    names = _sheets(workbook)
    if not names:
        return [f"None of the diamond sheets ({', '.join(SHEETS)}) is in it."]
    problems = []
    for name in names:
        first = next(workbook[name].iter_rows(max_row=1, values_only=True), ())
        if "weight" not in [_text(v).lower() for v in first]:
            problems.append(f"Sheet {name} has no Weight column in row 1.")
    return problems


def parse(fileobj):
    workbook = load_workbook(fileobj, read_only=True, data_only=True)
    rows = []
    for name in _sheets(workbook):
        where = {}
        for number, values in enumerate(workbook[name].iter_rows(values_only=True), start=1):
            labels = [_text(v).lower() for v in values]
            if "weight" in labels:                      # the header, first or repeated
                where = {HEADERS[label]: i for i, label in enumerate(labels) if label in HEADERS}
                continue

            def cell(field):
                index = where.get(field)
                return values[index] if index is not None and index < len(values) else None

            ct = _number(cell("ct"))
            code = _text(cell("code"))
            if ct is None or code.lower().startswith("total"):
                continue                                # totals and blank rows
            band = BAND_CODE.match(code.upper())
            raw_colour, raw_clarity = _text(cell("colour")), _text(cell("clarity"))
            fancy = raw_clarity.lower() == "fancy"
            item_code = _text(cell("item_code"))
            if "item_code" not in where:                # Round_RW: RW1 EF VVS VS is DREF VVS VS
                item_code = f"DR{raw_colour.upper()} {raw_clarity}".strip()
            category = _text(cell("category"))
            money = {field: _number(cell(field)) for field in ("rate", "amount", "price") if field in where}
            rows.append(Row(
                src=f"{name}!{number}",
                category=CATEGORY_NAMES.get(category, category) or "Natural Diamond",
                batch_no="" if band else code,
                item_code=item_code,
                size_text=_size(cell("size")),
                ct=ct.quantize(Decimal("0.01")),
                band_text=f"{band.group(1)} {band.group(2)}-{band.group(3)}" if band else "",
                shape=SHAPES.get(_text(cell("shape")).upper(), _text(cell("shape"))),
                colour=_colour(raw_colour, fancy),
                clarity=_clarity(raw_clarity),
                pcs=None if _number(cell("pcs")) is None else int(_number(cell("pcs"))),
                rate=_rate(money, ct),
            ))
    return rows
