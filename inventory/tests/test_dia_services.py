from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import dia_rows, dia_services
from inventory.models import DiamondRate, DiamondTerm, Movement
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
    dia_services.set_rate(admin_user_, diamonds["round"].code, "+6-12", Decimal("1"), Decimal("2"), date(2030, 1, 1))
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
    import io
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(["Karigar export"])
    sheet.append([])
    header = [""] * 40
    header[20], header[26], header[32], header[33] = "Item Code", "Size", "Cost Rate", "Sale Rate"
    sheet.append(header)
    for code, size, cost, sale in (("DPCEF VVS-VS", "+2", 21000, 27500), ("DZZZ", "+2", 1, 1)):
        row = [None] * 40
        row[20], row[26], row[32], row[33] = code, size, cost, sale
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    buffer.seek(0)
    assert dia_services.load_ivy_rates(admin_user_, buffer) == {"loaded": 1, "unknown": 1}
    assert dia_services.price(_line(diamonds["princess"].pk), dia_services.rate_table()) == (Decimal("21000"), Decimal("27500"))


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
