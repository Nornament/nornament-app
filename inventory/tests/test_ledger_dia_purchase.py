"""Diamond purchase, per rule: new lines; the code found or created; INR and USD cost with landed
extras; the rate card and sale untouched; the checks; reversal."""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied

from accounts.models import User
from inventory import dia_services, ledger
from inventory.ledger_dia_purchase import DiaPurchaseLine, post_dia_purchase
from inventory.ledger_purchase import PurchaseHeader
from inventory.models import DiamondCode, DiamondLine, DiamondRate, Movement, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
K, S, R = StockDocument.Kind, StockDocument.Status, Movement.Reason


def _line(pk):
    return dia_services.stocked_lines().get(pk=pk)


def _bought(doc):
    return [m.diamond for m in doc.movements.select_related(
        "diamond__category", "diamond__band", "diamond__code").order_by("pk")]


def _header(supplier, **changes):
    changes.setdefault("invoice_no", "2026/0442")
    return PurchaseHeader(supplier=supplier, occurred_on=date(2026, 8, 7), **changes)


def _lines():
    """The prototype's two lines: 14.20 ct round at ₹16,500 and 3.60 ct princess at ₹21,000."""
    return [DiaPurchaseLine("Natural Diamond", "Round", "F-G-H", "VS-SI", "+6-12", None, D("14.20"), D("16500"),
                            "B-901"),
            DiaPurchaseLine("Natural Diamond", "Princess", "E-F", "VVS-VS", "+2", 40, D("3.60"), D("21000"))]


def test_each_line_becomes_a_new_line_with_its_own_cost(accounts_user, diamonds):
    supplier = diamonds["supplier"]
    doc = post_dia_purchase(accounts_user, _header(supplier, landed_extras=D("1780")), _lines())
    assert (doc.kind, doc.number, doc.status, doc.vendor, doc.currency, doc.landed_extras) == (
        K.DIA_PURCHASE, "2026/0442", S.CLOSED, supplier, "INR", D("1780"))
    rnd, princess = _bought(doc)
    assert (rnd.ref, rnd.code_id, rnd.category.value, rnd.batch_no, rnd.size_text, rnd.band.value) == (
        "NRD-000004", "DRFGH VS-SI", "Natural Diamond", "B-901", "+6-12", "+6-11")
    assert (princess.ref, princess.code_id, princess.band.value, princess.batch_no) == (
        "NRD-000005", "DPCEF VVS-VS", "+2-6", "")
    assert list(doc.movements.order_by("pk").values_list("reason", "direction", "pcs", "ct")) == [
        (R.PURCHASE, "in", None, D("14.20")), (R.PURCHASE, "in", 40, D("3.60"))]
    rates = dia_services.rate_table()
    # ₹1,780 ÷ 17.80 ct = ₹100 a carat on top; the own cost wins over the rate card's ₹16,517
    assert dia_services.price(_line(rnd.pk), rates) == (D("16600"), D("21013"))
    assert dia_services.price(_line(princess.pk), rates) == (D("21100"), None)


def test_a_new_description_makes_a_confirmed_code(accounts_user, diamonds):
    line = DiaPurchaseLine("Natural Diamond", "Round", "G", "VS1", "+6", None, D("1"), D("30000"))
    (fresh,) = _bought(post_dia_purchase(accounts_user, _header(diamonds["supplier"]), [line]))
    assert (fresh.code_id, fresh.code.confirmed, fresh.band.value) == ("DRG VS1", True, "+6-11")


def test_a_usd_purchase_needs_its_rate_and_is_costed_in_inr(accounts_user, diamonds):
    line = [DiaPurchaseLine("Natural Diamond", "Round", "F-G-H", "VS-SI", "+6-12", None, D("2"), D("200"))]
    with pytest.raises(ServiceError, match="USD needs the rate"):
        post_dia_purchase(accounts_user, _header(diamonds["supplier"], currency="USD"), line)
    with pytest.raises(ServiceError, match="rate must be positive"):
        post_dia_purchase(accounts_user, _header(diamonds["supplier"], currency="USD", fx_rate=D("-1")), line)
    doc = post_dia_purchase(accounts_user, _header(diamonds["supplier"], currency="USD", fx_rate=D("83.5"),
                                                   landed_extras=D("100")), line)
    (fresh,) = _bought(doc)
    assert doc.fx_rate == D("83.5")
    assert dia_services.price(_line(fresh.pk), dia_services.rate_table())[0] == D("16750")   # 200 × 83.5 + 100 ÷ 2


def test_the_rate_card_and_sale_prices_are_untouched(accounts_user, diamonds):
    before = list(DiamondRate.objects.values_list("pk", "code", "size_text", "cost_rate", "sale_rate"))
    post_dia_purchase(accounts_user, _header(diamonds["supplier"]), _lines())
    assert list(DiamondRate.objects.values_list("pk", "code", "size_text", "cost_rate", "sale_rate")) == before
    assert dia_services.price(_line(diamonds["round"].pk), dia_services.rate_table()) == (D("16517"), D("21013"))


@pytest.mark.parametrize("field, value, words", [
    ("clarity", "", "needs category, shape, colour, clarity and size"),
    ("size_text", " ", "needs category, shape, colour, clarity and size"),
    ("category", "Moissanite", "Moissanite is not on the category list"),
    ("shape", "Cushion", "Cushion is not on the shape list"),
    ("ct", D("0"), "weight must be positive"),
    ("cost_per_ct", None, "cost per carat must be positive"),
])
def test_every_line_is_described_weighed_and_costed(accounts_user, diamonds, field, value, words):
    lines = _lines()
    setattr(lines[1], field, value)
    with pytest.raises(ServiceError, match=words):
        post_dia_purchase(accounts_user, _header(diamonds["supplier"]), lines)
    assert not StockDocument.objects.exists() and DiamondLine.objects.count() == 3


def test_a_supplier_and_a_line_are_required(accounts_user, diamonds):
    with pytest.raises(ServiceError, match="Choose the supplier"):
        post_dia_purchase(accounts_user, _header(None), _lines())
    with pytest.raises(ServiceError, match="at least one line"):
        post_dia_purchase(accounts_user, _header(diamonds["supplier"]), [])


def test_no_invoice_no_draws_an_automatic_number_and_a_typed_one_is_unique(accounts_user, diamonds):
    assert post_dia_purchase(accounts_user, _header(diamonds["supplier"], invoice_no=""), _lines()[:1]).number == "DP-000001"
    post_dia_purchase(accounts_user, _header(diamonds["supplier"]), _lines()[:1])
    with pytest.raises(ServiceError, match="already exists"):
        post_dia_purchase(accounts_user, _header(diamonds["supplier"]), _lines()[:1])


def test_a_size_that_reads_as_no_band_is_banded_per_stone(accounts_user, diamonds):
    line = DiaPurchaseLine("Natural Diamond", "Round", "F-G-H", "VS-SI", "mixed", 8, D("2"), D("16000"))
    (fresh,) = _bought(post_dia_purchase(accounts_user, _header(diamonds["supplier"]), [line]))
    assert (fresh.band.value, fresh.ct_lo, fresh.ct_hi) == ("carat band", D("0.250"), D("0.250"))


def test_a_fancy_colour_line_may_leave_clarity_blank(accounts_user, diamonds):
    """code_for's own ruling: clarity is optional only for a Fancy colour. A second line with the
    same shape and colour lands on the code the first line made, confirmed, with no clarity."""
    line = DiaPurchaseLine("Natural Diamond", "Round", "Fancy Yellow", "", "+6", None, D("1"), D("50000"))
    (fresh,) = _bought(post_dia_purchase(accounts_user, _header(diamonds["supplier"]), [line]))
    assert (fresh.code_id, fresh.code.confirmed, fresh.code.clarity, fresh.band.value) == (
        "D Round Fancy Yellow", True, None, "+6-11")
    line2 = DiaPurchaseLine("Natural Diamond", "Round", "Fancy Yellow", "", "+6", None, D("1"), D("51000"))
    (second,) = _bought(post_dia_purchase(accounts_user, _header(diamonds["supplier"], invoice_no="2026/0443"),
                                          [line2]))
    assert second.code_id == fresh.code_id
    assert DiamondCode.objects.filter(item_code="D Round Fancy Yellow").count() == 1


def test_a_non_fancy_colour_still_needs_a_clarity(accounts_user, diamonds):
    line = DiaPurchaseLine("Natural Diamond", "Round", "F-G-H", "", "+6", None, D("1"), D("50000"))
    with pytest.raises(ServiceError, match="needs category, shape, colour, clarity and size"):
        post_dia_purchase(accounts_user, _header(diamonds["supplier"]), [line])
    assert not StockDocument.objects.exists() and DiamondLine.objects.count() == 3


def test_a_purchase_needs_the_right_and_sight_of_cost_and_suppliers(production_user, accounts_user, diamonds):
    with pytest.raises(PermissionDenied):
        post_dia_purchase(production_user, _header(diamonds["supplier"]), _lines())
    Group.objects.get(name="ACCOUNTS").permissions.remove(
        Permission.objects.get(codename="view_vendor", content_type__app_label="accounts"))
    with pytest.raises(PermissionDenied):
        post_dia_purchase(User.objects.get(pk=accounts_user.pk), _header(diamonds["supplier"]), _lines())


def test_a_reversed_purchase_leaves_its_lines_at_zero(accounts_user, diamonds):
    doc = post_dia_purchase(accounts_user, _header(diamonds["supplier"]), _lines())
    ledger.reverse_document(accounts_user, doc)
    assert [_line(line.pk).on_ct for line in _bought(doc)] == [D("0"), D("0")]
