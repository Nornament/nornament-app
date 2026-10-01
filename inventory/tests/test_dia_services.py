from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import dia_rows, dia_seed, dia_services
from inventory.models import DiamondCode, DiamondRate, DiamondTerm, Movement
from inventory.tests.fixtures_diamonds import ivy_workbook
from stock.services import ServiceError

pytestmark = pytest.mark.django_db


def _line(pk):
    return dia_services.stocked_lines().get(pk=pk)


def test_opening_gives_a_ref_and_a_balance(diamonds):
    assert diamonds["round"].ref == "NRD-000001"
    assert _line(diamonds["round"].pk).on_ct == Decimal("3.40")


def test_price_by_exact_size_then_any_size_then_not_set(diamonds, admin_user_):
    rates = dia_services.rate_table()
    assert dia_services.price(_line(diamonds["round"].pk), rates) == (Decimal("16517"), Decimal("21013"))
    assert dia_services.price(_line(diamonds["princess"].pk), rates) == (None, None)
    dia_services.set_rate(admin_user_, diamonds["princess"].code, "", Decimal("21000"), Decimal("27000"), date(2026, 9, 1))
    assert dia_services.price(_line(diamonds["princess"].pk), dia_services.rate_table())[0] == Decimal("21000")


def test_the_latest_rate_wins(diamonds, admin_user_):
    from django.utils import timezone

    dia_services.set_rate(admin_user_, diamonds["round"].code, "+6-12", Decimal("1"), Decimal("2"), timezone.localdate())
    assert dia_services.price(_line(diamonds["round"].pk), dia_services.rate_table()) == (Decimal("1"), Decimal("2"))
    assert DiamondRate.objects.count() == 2


def test_rows_mask_money_by_role(diamonds, sales_user, accounts_user, karigar_user):
    def row(user):
        return next(r for r in dia_rows.line_rows(user) if r["ref"] == "NRD-000001")
    full = row(accounts_user)
    assert (full["cost_amount"], full["sale_amount"]) == (Decimal("56157.8000"), Decimal("71444.2000"))
    assert round(full["margin"], 1) == Decimal("27.2")
    assert "cost_rate" not in row(sales_user) and "sale_rate" in row(sales_user)
    assert "sale_rate" not in row(karigar_user)
    assert full["cols"] == ["F", "G", "H"] and full["shape"] == "Round"


def test_recount_posts_the_difference(diamonds, admin_user_):
    move = dia_services.recount_line(admin_user_, diamonds["round"], Decimal("3.10"))
    assert (move.direction, move.ct, move.reason) == (Movement.OUT, Decimal("0.30"), Movement.Reason.RECOUNT_ADJUSTMENT)
    assert dia_services.recount_line(admin_user_, diamonds["round"], Decimal("3.10")) is None


def test_terms_rename_and_refuse_deletes_in_use(diamonds, admin_user_):
    round_shape = DiamondTerm.objects.get(kind="shape", value="Round")
    with pytest.raises(ServiceError):
        dia_services.delete_term(admin_user_, round_shape)
    with pytest.raises(ServiceError):
        dia_services.rename_term(admin_user_, round_shape, "Princess")
    dia_services.rename_term(admin_user_, round_shape, "Round Brilliant")
    assert next(r for r in dia_rows.line_rows(admin_user_) if r["ref"] == "NRD-000001")["shape"] == "Round Brilliant"
    spare = dia_services.add_term(admin_user_, "shape", "Cushion")
    dia_services.delete_term(admin_user_, spare)


def test_expansion_only_names_grades_that_exist(diamonds, admin_user_):
    si_i = DiamondTerm.objects.get(kind="clarity", value="SI-I")
    dia_services.set_expansion(admin_user_, si_i, "SI1 SI2 SI3 I1 I2")
    assert si_i.grades()[-1] == "I2"
    with pytest.raises(ServiceError):
        dia_services.set_expansion(admin_user_, si_i, "SI1 Z9")


def test_a_rate_needs_both_money_rights(diamonds, sales_user):
    with pytest.raises(PermissionDenied):
        dia_services.set_rate(sales_user, diamonds["round"].code, "", Decimal("1"), Decimal("1"), date.today())


def test_rates_load_from_the_ivy_export(diamonds, admin_user_):
    book = ivy_workbook([("DPCEF  VVS VS", "+2", 21000, 27500), ("DZZZ", "+2", 1, 1)])   # the export's own spelling
    assert dia_services.load_ivy_rates(admin_user_, book) == {"loaded": 1, "unknown": 1}
    assert dia_services.price(_line(diamonds["princess"].pk), dia_services.rate_table()) == (None, Decimal("27500"))


def test_the_ivy_export_sets_sale_prices_and_never_the_files_cost(diamonds, admin_user_):
    round_line = _line(diamonds["round"].pk)
    cost_before = dia_services.price(round_line, dia_services.rate_table())[0]
    book = ivy_workbook([(round_line.code_id, round_line.size_text, 99999, 30000)])
    dia_services.load_ivy_rates(admin_user_, book)
    assert dia_services.price(round_line, dia_services.rate_table()) == (cost_before, Decimal("30000"))
    assert not DiamondRate.objects.filter(cost_rate=99999).exists()


def test_rights_are_set_by_an_admin_only_and_never_on_admin(diamonds, admin_user_, accounts_user):
    dia_services.set_right(admin_user_, "SALES", "inv_job", True)
    from django.contrib.auth.models import Group
    assert Group.objects.get(name="SALES").permissions.filter(codename="inv_job").exists()
    with pytest.raises(PermissionDenied):
        dia_services.set_right(accounts_user, "SALES", "inv_job", False)
    with pytest.raises(ServiceError):
        dia_services.set_right(admin_user_, "ADMIN", "view_cost", False)


def test_suppliers_have_unique_codes(diamonds, admin_user_):
    with pytest.raises(ServiceError):
        dia_services.save_supplier(admin_user_, None, "KOT", "Another", "Surat", "")
    created = dia_services.save_supplier(admin_user_, None, "BHA", "Bhansali Diamonds", "Surat", "30 days")
    assert created.terms == "30 days"


def test_rail_counts(diamonds):
    counts = dia_rows.rail_counts()
    assert counts["lines"] == 3 and counts["categories"] == 5 and counts["shapes"] >= 3


def test_a_cost_only_rate_does_not_hide_an_earlier_sale_rate(admin_user_):
    dia_seed.load(DiamondTerm)
    code = DiamondCode.objects.create(item_code="DREF VVS VS")
    dia_services.set_rate(admin_user_, code, "+5", None, "50000", None)
    DiamondRate.objects.create(code=code, size_text="+5", cost_rate=Decimal("35000"))
    rates = dia_services.rate_table()
    assert rates[("DREF VVS VS", "+5")] == {"cost": Decimal("35000"), "sale": Decimal("50000")}


def test_si_i1_covers_si1_si2_and_i1(diamonds):
    assert DiamondTerm.objects.get(kind="clarity", value="SI-I1").grades() == ["SI1", "SI2", "I1"]


def test_the_migration_fills_a_blank_si_i1():
    import importlib

    from django.apps import apps

    DiamondTerm.objects.update_or_create(kind="clarity", value="SI-I1", defaults={"expands_to": ""})
    importlib.import_module("inventory.migrations.0005_clarity_si_i1").add_si_i1(apps, None)
    assert DiamondTerm.objects.get(kind="clarity", value="SI-I1").expands_to == "SI1 SI2 I1"


def test_a_range_cannot_be_left_expanding_to_nothing(diamonds, admin_user_):
    with pytest.raises(ServiceError):
        dia_services.set_expansion(admin_user_, DiamondTerm.objects.get(kind="clarity", value="SI-I"), "  ")
    unresolved = DiamondTerm.objects.create(kind="colour", value="? Q")
    dia_services.set_expansion(admin_user_, unresolved, "")


def test_a_grade_named_in_a_range_is_in_use_and_renames_through_it(diamonds, admin_user_):
    si3 = DiamondTerm.objects.get(kind="clarity", value="SI3")          # on no code, but inside SI-I
    with pytest.raises(ServiceError):
        dia_services.delete_term(admin_user_, si3)
    dia_services.rename_term(admin_user_, DiamondTerm.objects.get(kind="clarity", value="I1"), "I-1")
    assert DiamondTerm.objects.get(kind="clarity", value="SI-I").expands_to == "SI1 SI2 SI3 I-1"
    assert DiamondTerm.objects.get(kind="clarity", value="I1-I2").expands_to == "I-1 I2"


def test_an_ivy_sale_rate_that_is_not_a_number_is_refused(diamonds, admin_user_):
    with pytest.raises(ServiceError):
        dia_services.load_ivy_rates(admin_user_, ivy_workbook([("DPCEF VVS VS", "+2", 21000, "on request")]))
    assert not DiamondRate.objects.filter(code_id="DPCEF VVS-VS").exists()


def test_a_rate_dated_in_the_future_waits_for_its_day(admin_user_):
    dia_seed.load(DiamondTerm)
    code = DiamondCode.objects.create(item_code="DREF VVS-VS")
    dia_services.set_rate(admin_user_, code, "+5", "35000", "50000", None)
    dia_services.set_rate(admin_user_, code, "+5", "99000", "99000", date(2999, 1, 1))
    assert dia_services.rate_table()[("DREF VVS-VS", "+5")] == {"cost": Decimal("35000"), "sale": Decimal("50000")}
