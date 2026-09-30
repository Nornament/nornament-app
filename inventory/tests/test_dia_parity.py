"""The diamond port reproduces the prototype's own diamond figures.

The prototype's embedded data (``const DD``: 348 lines as the owner has seen
them) is rebuilt into a register in file order, imported through the real
importer, and must land on the prototype's counts and carats. Read from beside
the repo; skipped when absent, so no stock figures are committed.
"""
import io
import json
from collections import defaultdict
from decimal import Decimal

import pytest
from django.conf import settings
from openpyxl import Workbook

from inventory import dia_seed, dia_services
from inventory.importers import dia_plan, diamonds
from inventory.models import DiamondCode, DiamondTerm

pytestmark = [pytest.mark.django_db, pytest.mark.golden]

PROTOTYPE = settings.BASE_DIR.parent / "Nornament_Inventory" / "01-prototype" / "nornament-ui-mockup.html"
RAW_CATEGORY = {name: raw for raw, name in diamonds.CATEGORY_NAMES.items()}


def _prototype_rows():
    if not PROTOTYPE.exists():
        pytest.skip(f"{PROTOTYPE} is not beside the repo")
    for line in PROTOTYPE.read_text().splitlines():
        if line.startswith("const DD = "):
            return json.loads(line[len("const DD = "):].rstrip().rstrip(";"))["rows"]
    pytest.fail("no const DD in the prototype")


def _register(rows):
    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet"
    sheet.append(["Raw Material", "Batch No", "Item Code", "", "Size", "Weight"])
    for r in rows:
        sheet.append([RAW_CATEGORY[r["cat"]], r["batch"] or None, r["item"], None, r["size"], r["wt"]])
    buffer = io.BytesIO()
    book.save(buffer)
    buffer.seek(0)
    return buffer


def test_the_diamonds_match_the_prototype(admin_user_):
    dia_seed.load(DiamondTerm)
    plan = dia_plan.analyse(diamonds.parse(_register(_prototype_rows())))
    assert plan.counts()["blocked"] == 0
    dia_plan.commit(plan, admin_user_)

    lines = list(dia_services.stocked_lines())
    assert len(lines) == 348
    assert sum(line.on_ct for line in lines) == Decimal("673.90")
    assert len({line.batch_no for line in lines if line.batch_no}) == 270
    assert DiamondCode.objects.count() == 84

    by_cat, by_band = defaultdict(lambda: [0, Decimal("0")]), defaultdict(lambda: [0, Decimal("0")])
    for line in lines:
        by_cat[line.category.value][0] += 1
        by_cat[line.category.value][1] += line.on_ct
        by_band[line.band.value][0] += 1
        by_band[line.band.value][1] += line.on_ct
    assert {k: (n, ct) for k, (n, ct) in by_cat.items()} == {
        "Natural Diamond": (329, Decimal("563.20")), "Foil Polki": (10, Decimal("105.58")),
        "HPHT Lab Grown": (5, Decimal("2.81")), "Solitaire": (3, Decimal("2.26")),
        "Lab Grown (CVD?)": (1, Decimal("0.05")),
    }
    assert {k: (n, ct) for k, (n, ct) in by_band.items()} == {
        "-2": (118, Decimal("445.69")), "+2-6": (46, Decimal("21.11")), "+6-11": (73, Decimal("71.22")),
        "11-20": (31, Decimal("17.63")), "20+": (9, Decimal("67.85")), "carat band": (71, Decimal("50.40")),
    }
