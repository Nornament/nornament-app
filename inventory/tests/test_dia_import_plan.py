from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import dia_seed, dia_services
from inventory.importers import dia_plan, diamonds
from inventory.models import DiamondCode, DiamondLine, DiamondTerm
from inventory.tests.fixtures_diamonds import ROWS_DEFAULT, build_workbook
from stock.services import ServiceError

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _terms():
    dia_seed.load(DiamondTerm)


def _plan(rows=None, decisions=None):
    return dia_plan.analyse(diamonds.parse(build_workbook(rows)), decisions)


def test_a_first_import_opens_every_line_and_proposes_every_code(admin_user_):
    plan = _plan()
    counts = plan.counts()
    assert (counts["new"], counts["codes"], counts["blocked"]) == (6, 4, 0)
    proposed = {c.item_code: c for c in plan.codes}
    assert proposed["DPCEF VVS-VS"].shape == "Princess"
    assert proposed["DTRLC VS-SI"].colour == "? LC" and not proposed["DTRLC VS-SI"].confirmed
    result = dia_plan.commit(plan, admin_user_)
    assert (result["created"], result["codes"]) == (6, 4)
    trillion = DiamondLine.objects.get(src="Sheet!8")
    assert (trillion.band.value, trillion.ct_lo, trillion.category.value) == ("carat band", Decimal("0.200"), "Foil Polki")
    assert DiamondCode.objects.get(pk="FPL").shape.value == "Polki"


def test_a_reviewed_code_is_created_as_decided(admin_user_):
    plan = _plan()
    post = {"code:DTRLC VS-SI:shape": "Trillion", "code:DTRLC VS-SI:colour": "L", "code:DTRLC VS-SI:clarity": "VS-SI",
            "code:DTRLC VS-SI:confirmed": "1"}
    decisions = dia_plan.read_decisions(post, plan, {})
    dia_plan.commit(_plan(decisions=decisions), admin_user_)
    code = DiamondCode.objects.get(pk="DTRLC VS-SI")
    assert (code.colour.value, code.confirmed) == ("L", True)


def test_reimport_matches_recounts_and_lists_missing_lines(admin_user_):
    dia_plan.commit(_plan(), admin_user_)
    changed = [list(r) for r in ROWS_DEFAULT]
    changed[1][5] = 3.10                                     # B-771 DRFGH +6-12 lost 0.30 ct
    del changed[6]                                           # the trillion line is gone from the file
    plan = _plan(changed)
    counts = plan.counts()
    assert (counts["new"], counts["update"], counts["recount"], counts["missing"]) == (0, 5, 1, 1)
    decisions = dia_plan.read_decisions({f"missing:{plan.missing[0][0].ref}": "zero"}, plan, {})
    result = dia_plan.commit(_plan(changed, decisions), admin_user_)
    assert (result["recounted"], result["zeroed"]) == (1, 1)
    line = dia_services.stocked_lines().get(src="Sheet!3")
    assert line.on_ct == Decimal("3.10")


DUP = ["Diamond", "B-771", "DRFGH VS-SI", "", "+6-12", 3.40]


def test_an_ambiguous_row_blocks_until_decided(admin_user_):
    dia_plan.commit(_plan([list(DUP), list(DUP)]), admin_user_)       # two lines share one key, Sheet!2 and Sheet!3
    shifted = [list(ROWS_DEFAULT[0]), ["Diamond", "B-900", "DPCEF VVS-VS", "", "+2", 0.85], list(DUP), list(DUP)]
    plan = _plan(shifted)                                             # the pair moved to Sheet!4 and Sheet!5
    assert plan.counts()["blocked"] == 2
    with pytest.raises(ServiceError):
        dia_plan.commit(plan, admin_user_)
    refs = list(DiamondLine.objects.order_by("pk").values_list("ref", flat=True))
    post = {"row:Sheet!4": "map", "row:Sheet!4:line": refs[0], "row:Sheet!5": "map", "row:Sheet!5:line": refs[1]}
    decided = dia_plan.read_decisions(post, plan, {})
    assert _plan(shifted, decided).counts()["blocked"] == 0


def test_sales_cannot_import(sales_user):
    with pytest.raises(PermissionDenied):
        dia_plan.commit(_plan(), sales_user)
