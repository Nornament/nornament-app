from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied

from accounts.models import User
from inventory import ledger, services
from inventory.ledger_purchase import PurchaseHeader, PurchaseLine, post_purchase
from inventory.models import Movement, Pouch, PriceEntry, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal


def _held(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()


def _lines(batch):
    return [
        PurchaseLine(batch=batch, pouch_no="3", stone_name="Tanzanite", shape="Oval", colour="Blue",
                     pcs=12, ct=D("42.50"), cost_per_ct=D("1800")),
        PurchaseLine(batch=batch, pouch_no="4", stone_name="Tanzanite", shape="Round", colour="Blue",
                     pcs=None, ct=D("11.20"), cost_per_ct=D("2400")),
    ]


def _header(supplier, **changes):
    changes.setdefault("invoice_no", "2026/0442")
    return PurchaseHeader(supplier=supplier, occurred_on=date(2026, 8, 7), **changes)


def test_a_purchase_opens_new_pouches_with_cost_and_landed_valuation(accounts_user, shelf):
    supplier, batch = shelf["supplier"], shelf["batch"]
    doc = post_purchase(accounts_user, _header(supplier, landed_extras=D("5370")), _lines(batch))
    assert (doc.kind, doc.number, doc.status) == (StockDocument.Kind.PURCHASE, "2026/0442", StockDocument.Status.CLOSED)
    assert (doc.vendor, doc.currency, doc.landed_extras) == (supplier, "INR", D("5370"))
    three, four = Pouch.objects.get(batch=batch, pouch_no="3"), Pouch.objects.get(batch=batch, pouch_no="4")
    assert (three.supplier, three.purchase_date, three.stone_name, three.shape, three.countable) == (
        supplier, date(2026, 8, 7), "Tanzanite", "Oval", True)
    assert not four.countable
    assert three.movements.get().reason == Movement.Reason.PURCHASE
    held = _held(three)
    assert (held.on_pcs, held.on_ct, held.rate) == (12, D("42.5"), D("1900"))    # 1,800 + 5,370 ÷ 53.70 ct
    assert services.latest_price(three, PriceEntry.PURCHASE).rate == D("1800")
    assert _held(four).rate == D("2500")
    assert not PriceEntry.objects.filter(kind=PriceEntry.LIST).exists()           # selling price is not set here


def test_a_purchase_can_file_into_a_new_batch(accounts_user, shelf):
    from inventory.models import Batch

    line = PurchaseLine(batch="sp14b", pouch_no="1", stone_name="Tanzanite", shape="Oval", colour="Blue",
                        pcs=3, ct=D("4.20"), cost_per_ct=D("1800"))
    post_purchase(accounts_user, _header(shelf["supplier"]), [line])
    batch = Batch.objects.get(code="SP14B")
    assert (batch.family, batch.cls, batch.seq, batch.box_colour_id) == ("S", "P", "14", "B")
    assert Pouch.objects.filter(batch=batch, pouch_no="1").exists()
    bad = PurchaseLine(batch="TANZ-1", pouch_no="1", stone_name="", shape="", colour="", pcs=1, ct=D("1"),
                       cost_per_ct=D("1"))
    with pytest.raises(ServiceError, match="does not read as"):
        post_purchase(accounts_user, _header(shelf["supplier"], invoice_no="2026/0443"), [bad])
    assert not Batch.objects.filter(code="TANZ-1").exists()


def test_a_usd_purchase_needs_its_rate_and_is_costed_in_inr(accounts_user, shelf):
    lines = [PurchaseLine(batch=shelf["batch"], pouch_no="3", stone_name="Tanzanite", shape="Oval", colour="Blue",
                          pcs=2, ct=D("1"), cost_per_ct=D("20"))]
    with pytest.raises(ServiceError, match="USD needs the rate"):
        post_purchase(accounts_user, _header(shelf["supplier"], currency="USD"), lines)
    with pytest.raises(ServiceError, match="rate must be positive"):
        post_purchase(accounts_user, _header(shelf["supplier"], currency="USD", fx_rate=D("-1")), lines)
    doc = post_purchase(accounts_user, _header(shelf["supplier"], currency="USD", fx_rate=D("83.5")), lines)
    pouch = Pouch.objects.get(batch=shelf["batch"], pouch_no="3")
    assert doc.fx_rate == D("83.5") and services.latest_price(pouch, PriceEntry.PURCHASE).rate == D("1670")


def test_an_existing_pouch_number_is_refused_and_nothing_is_written(accounts_user, shelf):
    lines = _lines(shelf["batch"])
    lines[0].pouch_no = "1"
    with pytest.raises(ServiceError, match="SL01G · 1 already exists"):
        post_purchase(accounts_user, _header(shelf["supplier"]), lines)
    assert Pouch.objects.count() == 2 and not StockDocument.objects.exists()


def test_the_same_number_twice_in_one_purchase_is_refused(accounts_user, shelf):
    lines = _lines(shelf["batch"])
    lines[1].pouch_no = "3"
    with pytest.raises(ServiceError, match="already exists"):
        post_purchase(accounts_user, _header(shelf["supplier"]), lines)


@pytest.mark.parametrize("field, value, words", [
    ("ct", D("0"), "weight must be positive"), ("cost_per_ct", D("-1"), "rate must be positive"),
    ("cost_per_ct", None, "rate must be positive"), ("pouch_no", " ", "pouch no."),
])
def test_every_line_needs_a_number_a_weight_and_a_rate(accounts_user, shelf, field, value, words):
    lines = _lines(shelf["batch"])
    setattr(lines[0], field, value)
    with pytest.raises(ServiceError, match=words):
        post_purchase(accounts_user, _header(shelf["supplier"]), lines)


@pytest.mark.parametrize("field, value, words", [
    ("pouch_no", "9" * 17, "Pouch no is too long: at most 16"),
    ("stone_name", "T" * 121, "Stone name is too long: at most 120"),
    ("colour", "B" * 81, "Colour is too long: at most 80"),
])
def test_an_over_long_pouch_field_is_refused_and_nothing_is_written(accounts_user, shelf, field, value, words):
    lines = _lines(shelf["batch"])
    setattr(lines[1], field, value)
    with pytest.raises(ServiceError, match=words):
        post_purchase(accounts_user, _header(shelf["supplier"]), lines)
    assert not StockDocument.objects.exists() and Pouch.objects.count() == 2


def test_an_over_long_invoice_no_is_refused(accounts_user, shelf):
    with pytest.raises(ServiceError, match="at most 40 characters"):
        post_purchase(accounts_user, _header(shelf["supplier"], invoice_no="I" * 41), _lines(shelf["batch"]))


def test_a_supplier_and_a_line_are_required(accounts_user, shelf):
    with pytest.raises(ServiceError, match="Choose the supplier"):
        post_purchase(accounts_user, _header(None), _lines(shelf["batch"]))
    with pytest.raises(ServiceError, match="at least one line"):
        post_purchase(accounts_user, _header(shelf["supplier"]), [])


def test_no_invoice_no_draws_an_automatic_number(accounts_user, shelf):
    doc = post_purchase(accounts_user, _header(shelf["supplier"], invoice_no=""), _lines(shelf["batch"])[:1])
    assert doc.number == "PUR-000001"


def test_a_purchase_needs_the_right_and_sight_of_cost(production_user, accounts_user, shelf):
    with pytest.raises(PermissionDenied):
        post_purchase(production_user, _header(shelf["supplier"]), _lines(shelf["batch"]))
    Group.objects.get(name="ACCOUNTS").permissions.remove(Permission.objects.get(codename="view_cost"))
    blind = User.objects.get(pk=accounts_user.pk)                 # a fresh object: no cached permissions
    with pytest.raises(PermissionDenied):
        post_purchase(blind, _header(shelf["supplier"]), _lines(shelf["batch"]))


def test_a_purchase_needs_sight_of_suppliers(graphic_user, shelf):
    graphic_user.user_permissions.add(*Permission.objects.filter(codename__in=("inv_purchase", "view_cost")))
    buyer = User.objects.get(pk=graphic_user.pk)
    with pytest.raises(PermissionDenied):
        post_purchase(buyer, _header(shelf["supplier"]), _lines(shelf["batch"]))
    assert not StockDocument.objects.exists()


def test_a_reversed_purchase_leaves_its_pouches_at_zero(accounts_user, shelf):
    doc = post_purchase(accounts_user, _header(shelf["supplier"]), _lines(shelf["batch"]))
    ledger.reverse_document(accounts_user, doc)
    for number in ("3", "4"):
        assert _held(Pouch.objects.get(batch=shelf["batch"], pouch_no=number)).on_ct == D("0")
