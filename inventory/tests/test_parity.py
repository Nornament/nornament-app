"""The port reproduces the prototype's own totals.

The prototype's data (all 2,916 pouches, as the owner has already seen them) is
rebuilt into a register, imported through the real importer, and the shelf's
totals must match. It reads the prototype from beside the repo and skips if it
is not there, so no stock figures are ever committed.
"""
import io
import json
from decimal import Decimal

import pytest
from django.conf import settings
from openpyxl import Workbook

from inventory import rows as rows_mod
from inventory import rules, seed, services
from inventory.importers import plan, stones
from inventory.models import BoxColour, CodePart

pytestmark = [pytest.mark.django_db, pytest.mark.golden]

PROTOTYPE = settings.BASE_DIR.parent / "Nornament_Inventory" / "01-prototype" / "nornament-ui-mockup.html"

FIELD = {"gati": "New Gati Code", "batch": "Batch No.", "carton": "Box No", "cat": "Category", "name": "Stone Name",
         "shape": "Shape", "size": "Size Length * Width", "colour": "Colour", "cut": "Cut", "q": "Quality",
         "pcs": "Pcs", "wt": "Weight in Cts / Qty", "rate": "Price Per Carat / Pc", "rem": "Remarks"}


def _prototype_pouches():
    if not PROTOTYPE.exists():
        pytest.skip(f"{PROTOTYPE} is not beside the repo")
    for line in PROTOTYPE.read_text().splitlines():
        if line.startswith("const D = "):
            data = json.loads(line[len("const D = "):].rstrip().rstrip(";"))
            break
    return [p for c in data["colours"] for ps in c["p"].values() for p in ps] + data["unparsed"]


def _register(pouches):
    headers = list(stones.COLUMNS.values())
    book = Workbook()
    book.remove(book.active)
    sheets = {}
    for pouch in pouches:
        name, row = pouch["src"].split("!")
        if name not in sheets:
            sheets[name] = book.create_sheet(name)
            sheets[name].append(headers)
        for column, header in enumerate(headers, start=1):
            key = next(k for k, v in FIELD.items() if v == header)
            value = pouch.get(key)
            sheets[name].cell(row=int(row), column=column, value=None if value in ("", None) else value)
    buffer = io.BytesIO()
    book.save(buffer)
    buffer.seek(0)
    return buffer


def test_the_shelf_matches_the_prototype(admin_user_):
    seed.load(BoxColour, CodePart)
    items = plan.analyse(stones.parse(_register(_prototype_pouches())))
    decisions = {}
    for item in items:
        if item.problem and not rules.parse_batch_code(item.batch):
            decisions[item.row.src] = {"batch": "", "pouch_no": item.pouch_no, "skip": True}
        elif item.problem:
            decisions[item.row.src] = {"batch": "", "pouch_no": f"{item.pouch_no}-{item.row.src}", "skip": False}
    items = plan.analyse(stones.parse(_register(_prototype_pouches())), decisions)
    plan.commit(items, admin_user_)

    totals = rows_mod.summarise(rows_mod.pouch_rows(admin_user_, services.stocked()))
    assert totals["pouches"] == 2915                     # 2,916 less the one "Broken" code
    assert totals["batches"] == 697
    assert totals["colours"] == 19
    assert totals["misfiled"] == 127
    assert abs(totals["ct"] - Decimal("1056315.1")) < Decimal("0.5")
    assert abs(totals["value"] - Decimal("17249719")) <= 10
    assert totals["unpriced"] == 48
