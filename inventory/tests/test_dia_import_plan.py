from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied

from inventory import dia_seed, dia_services
from inventory.importers import dia_plan, diamonds
from inventory.models import DiamondCode, DiamondLine, DiamondRate, DiamondTerm, Movement
from inventory.tests.fixtures_diamonds import PLAN_ROWS, build_workbook, fancy_workbook
from stock.services import ServiceError

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _terms():
    dia_seed.load(DiamondTerm)


def _plan(rows=None, decisions=None):
    return dia_plan.analyse(diamonds.parse(fancy_workbook(rows)), decisions)


def test_a_first_import_opens_every_line_and_proposes_every_code(admin_user_):
    plan = _plan()
    counts = plan.counts()
    assert (counts["new"], counts["codes"], counts["blocked"]) == (6, 4, 0)
    proposed = {c.item_code: c for c in plan.codes}
    assert proposed["DPCEF VVS-VS"].shape == "Princess"
    assert proposed["DTRQ VS-SI"].colour == "? Q" and not proposed["DTRQ VS-SI"].confirmed
    result = dia_plan.commit(plan, admin_user_)
    assert (result["created"], result["codes"]) == (6, 4)
    trillion = DiamondLine.objects.get(src="FANCY FINAL!7")
    assert (trillion.band.value, trillion.ct_lo, trillion.category.value) == ("carat band", Decimal("0.200"), "Foil Polki")
    assert DiamondCode.objects.get(pk="FPL").shape.value == "Polki"


def test_a_reviewed_code_is_created_as_decided(admin_user_):
    plan = _plan()
    post = {"code:DTRQ VS-SI:shape": "Trillion", "code:DTRQ VS-SI:colour": "L", "code:DTRQ VS-SI:clarity": "VS-SI",
            "code:DTRQ VS-SI:confirmed": "1"}
    decisions = dia_plan.read_decisions(post, plan, {})
    dia_plan.commit(_plan(decisions=decisions), admin_user_)
    code = DiamondCode.objects.get(pk="DTRQ VS-SI")
    assert (code.colour.value, code.confirmed) == ("L", True)


def test_reimport_matches_recounts_and_lists_missing_lines(admin_user_):
    dia_plan.commit(_plan(), admin_user_)
    changed = [list(r) for r in PLAN_ROWS]
    changed[1][7] = 3.10                                     # B-771 DRFGH +6-12 lost 0.30 ct
    del changed[5]                                           # the trillion line is gone from the file
    plan = _plan(changed)
    counts = plan.counts()
    assert (counts["new"], counts["update"], counts["recount"], counts["missing"]) == (0, 5, 1, 1)
    decisions = dia_plan.read_decisions({f"missing:{plan.missing[0][0].ref}": "zero"}, plan, {})
    result = dia_plan.commit(_plan(changed, decisions), admin_user_)
    assert (result["recounted"], result["zeroed"]) == (1, 1)
    line = dia_services.stocked_lines().get(src="FANCY FINAL!3")
    assert line.on_ct == Decimal("3.10")


DUP = ["B-771", "Round", "DRFGH VS-SI", "FGH", "VS SI", "+6-12", None, 3.40, None, None, None, "Diamond"]


def test_an_ambiguous_row_blocks_until_decided(admin_user_):
    dia_plan.commit(_plan([list(DUP), list(DUP)]), admin_user_)   # two lines share one key, FANCY FINAL!2 and !3
    b900 = ["B-900", "Princess", "DPCEF VVS-VS", "EF", "VVS VS", "+2", None, 0.85, None, None, None, "Diamond"]
    shifted = [list(PLAN_ROWS[0]), b900, list(DUP), list(DUP)]    # the pair moved to FANCY FINAL!4 and !5
    plan = _plan(shifted)
    assert plan.counts()["blocked"] == 2
    with pytest.raises(ServiceError):
        dia_plan.commit(plan, admin_user_)
    refs = list(DiamondLine.objects.order_by("pk").values_list("ref", flat=True))
    post = {"row:FANCY FINAL!4": "map", "row:FANCY FINAL!4:line": refs[0],
            "row:FANCY FINAL!5": "map", "row:FANCY FINAL!5:line": refs[1]}
    decided = dia_plan.read_decisions(post, plan, {})
    assert _plan(shifted, decided).counts()["blocked"] == 0


def test_sales_cannot_import(sales_user):
    with pytest.raises(PermissionDenied):
        dia_plan.commit(_plan(), sales_user)


def _file_plan(decisions=None):
    return dia_plan.analyse(diamonds.parse(build_workbook()), decisions)


def test_a_code_takes_the_files_columns_and_is_confirmed_when_they_agree():
    codes = {c.item_code: c for c in _file_plan().codes}
    marquise = codes["DMIJ VVS-VS"]
    assert (marquise.shape, marquise.colour, marquise.clarity, marquise.confirmed) == ("Marquise", "I-J", "VVS-VS", True)
    fancy = codes["DFY"]
    assert (fancy.shape, fancy.colour, fancy.clarity, fancy.confirmed) == ("Mix", "Fancy Yellow", "", True)


def test_a_column_that_disagrees_with_the_code_leaves_it_unconfirmed():
    rows = [[None, "Marquise", "DMMN VVS VS", "MN", "VS-SI", "4.0*2.5", 4, 0.61, 26000, 15860]]
    code = dia_plan.analyse(diamonds.parse(fancy_workbook(rows))).codes[0]
    assert (code.clarity, code.confirmed) == ("VS-SI", False) and "clarity" in code.note


def test_two_rows_of_one_code_that_disagree_leave_it_unconfirmed():
    rows = [[None, "Pear", "DPRGH VVS VS", "GH", "VVS VS", "2.8*1.5", 10, 1.34, 37800, 50652],
            [None, "Oval", "DPRGH VVS VS", "GH", "VVS VS", "3.0*2.0", 1, 0.20, 37800, 7560]]
    code = dia_plan.analyse(diamonds.parse(fancy_workbook(rows))).codes[0]
    assert (code.shape, code.confirmed) == ("Pear", False) and "Oval" in code.note


def test_zero_rows_open_nothing_and_pieces_open_with_the_carats(admin_user_):
    plan = _file_plan()
    assert plan.counts()["empty"] == 1 and plan.counts()["blocked"] == 0
    result = dia_plan.commit(plan, admin_user_)
    assert result["created"] == 10
    assert not DiamondLine.objects.filter(src="Round_RW!4").exists()
    opening = Movement.objects.get(diamond__src="FANCY FINAL!3")
    assert (opening.pcs, opening.ct) == (6, Decimal("0.31"))
    marquise = DiamondLine.objects.get(src="FANCY FINAL!3")
    assert (marquise.band.value, marquise.ct_lo, marquise.ct_hi) == ("carat band", Decimal("0.100"), Decimal("0.150"))


def test_a_held_line_that_comes_back_at_zero_is_recounted_to_zero(admin_user_):
    dia_plan.commit(_plan(), admin_user_)
    changed = [list(r) for r in PLAN_ROWS]
    changed[1][7] = 0
    plan = _plan(changed)
    assert plan.counts()["recount"] == 1
    dia_plan.commit(plan, admin_user_)
    assert dia_services.stocked_lines().get(src="FANCY FINAL!3").on_ct == Decimal("0")


def test_commit_saves_each_lines_cost_to_the_rate_card_once(admin_user_):
    dia_plan.commit(_file_plan(), admin_user_)
    rates = dia_services.rate_table()
    assert rates[("DMIJ VVS-VS", "2.3*1.3 - 3.5*2.3")]["cost"] == Decimal("32200")
    assert rates[("DRMN VVS-VS", "0-1")]["cost"] == Decimal("20000")
    before = DiamondRate.objects.count()
    result = dia_plan.commit(_file_plan(), admin_user_)                # the same file again
    assert result["rates"] == 0 and DiamondRate.objects.count() == before


def test_a_login_that_cannot_see_cost_imports_stock_without_prices(production_user):
    production_user.user_permissions.add(Permission.objects.get(codename="inv_masters"))
    production_user = type(production_user).objects.get(pk=production_user.pk)       # fresh permission cache
    result = dia_plan.commit(_file_plan(), production_user)
    assert result["created"] == 10 and result["prices_skipped"] and not DiamondRate.objects.exists()


def test_a_reimport_keeps_what_settings_renamed(admin_user_):
    dia_plan.commit(_plan(), admin_user_)
    dia_services.rename_term(admin_user_, DiamondTerm.objects.get(kind="category", value="Natural Diamond"), "Natural")
    dia_services.rename_term(admin_user_, DiamondTerm.objects.get(kind="band", value="+6-11"), "6-11 sieve")
    result = dia_plan.commit(_plan(), admin_user_)
    assert result["updated"] == 6
    line = DiamondLine.objects.get(src="FANCY FINAL!3")
    assert (line.category.value, line.band.value) == ("Natural", "6-11 sieve")
    assert not DiamondTerm.objects.filter(kind="category", value="Natural Diamond").exists()
    assert not DiamondTerm.objects.filter(kind="band", value="+6-11").exists()


def test_a_size_that_reads_as_no_band_is_banded_by_weight_per_stone(admin_user_):
    dia_plan.commit(_file_plan(), admin_user_)
    emerald = DiamondLine.objects.get(src="FANCY FINAL!2")               # 0.14 ct in 2 pieces
    assert (emerald.band.value, emerald.ct_lo, emerald.ct_hi) == ("carat band", Decimal("0.070"), Decimal("0.070"))
    assert DiamondLine.objects.get(src="FANCY FINAL!6").band.value == "?"   # no pieces, nothing to divide by


@pytest.mark.parametrize("rate", [-32200, 10 ** 10])
def test_a_rate_out_of_range_blocks_the_row(rate):
    rows = [[None, "Marquise", "DMIJ VVS VS", "IJ", "VVS VS", "2.3*1.3", 6, 0.31, rate, 9982]]
    assert dia_plan.analyse(diamonds.parse(fancy_workbook(rows))).items[0].problem == "Rate out of range"


def test_a_file_of_other_sheets_lists_none_of_these_lines_as_missing(admin_user_):
    import io

    from openpyxl import Workbook

    from inventory.tests.fixtures_diamonds import RW_HEADER, RW_ROWS

    dia_plan.commit(_plan(), admin_user_)                                  # lines from FANCY FINAL
    book = Workbook()
    book.active.title = "Round_RW"
    book.active.append(RW_HEADER)
    book.active.append(RW_ROWS[1])
    buffer = io.BytesIO()
    book.save(buffer)
    buffer.seek(0)
    assert dia_plan.analyse(diamonds.parse(buffer)).missing == []


def test_a_later_row_that_differs_from_the_code_says_file_against_code():
    rows = [[None, None, "DPRGH VVS VS", "GH", "VVS VS", "2.8*1.5", 10, 1.34, 37800, 50652],
            [None, "Oval", "DPRGH VVS VS", "GH", "VVS VS", "3.0*2.0", 1, 0.20, 37800, 7560]]
    code = dia_plan.analyse(diamonds.parse(fancy_workbook(rows))).codes[0]
    assert "shape: file says Oval, code reads Pear" in code.note and "disagree" not in code.note
