"""FoN commission, computed off the sale ledger.

The slabs and overrides are the CRM's, unchanged. What changed is the input:
these tests write ``stock.Sale`` rows and assert the payout follows them, which
is the fix for the two disagreeing revenue numbers.
"""
from decimal import Decimal

import pytest
from django.utils import timezone

from crm import services
from crm.models import Customer
from stock.models import Sale

pytestmark = pytest.mark.django_db


def make_customer(name, code, level=None, parent=None):
    return Customer.objects.create(
        customer_code=code, name=name, is_fon=level is not None, fon_level=level, fon_parent=parent
    )


def bill(customer, amount, category="cat1", on=None):
    return Sale.objects.create(
        customer=customer,
        customer_name=customer.name,
        sold_on=on or timezone.localdate(),
        sold_price=Decimal(str(amount)),
        product_category=category,
        source=Sale.CRM,
        cost_at_sale=None,
    )


def test_a_customer_who_is_not_a_member_has_no_payout():
    assert services.fon_payout(make_customer("Walk in", "C1")) is None


def test_level_one_earns_the_first_slab_below_ten_lakh():
    member = make_customer("Anita", "C1", level=1)
    bill(member, 500000, "cat1")
    bill(member, 200000, "cat2")
    bill(member, 100000, "cat3")
    payout = services.fon_payout(member)
    assert payout.total == Decimal("800000")
    assert payout.pct == {"cat1": Decimal("5"), "cat2": Decimal("3"), "cat3": Decimal("0.5")}
    assert payout.payout["cat1"] == Decimal("25000")
    assert payout.payout["cat2"] == Decimal("6000")
    assert payout.payout["cat3"] == Decimal("500")
    assert payout.total_payout == Decimal("31500")


def test_the_slab_moves_with_the_total():
    member = make_customer("Anita", "C1", level=1)
    bill(member, 2000000, "cat1")
    assert services.fon_payout(member).pct["cat1"] == Decimal("6")
    bill(member, 4000000, "cat1")
    assert services.fon_payout(member).pct["cat1"] == Decimal("7")


def test_a_level_one_earns_on_the_whole_downline():
    top = make_customer("Anita", "C1", level=1)
    middle = make_customer("Bhavna", "C2", level=2, parent=top)
    bottom = make_customer("Chetan", "C3", level=3, parent=middle)
    bill(top, 100000)
    bill(middle, 200000)
    bill(bottom, 300000)

    payout = services.fon_payout(top)
    assert payout.billing["cat1"] == Decimal("600000")  # the whole tree
    assert payout.payout["cat1"] == Decimal("30000")

    # levels 2 and 3 earn a flat override on their own billing only
    middle_payout = services.fon_payout(middle)
    assert middle_payout.billing["cat1"] == Decimal("200000")
    assert middle_payout.pct == services.FON_LEVEL_2
    assert middle_payout.payout["cat1"] == Decimal("4000")

    bottom_payout = services.fon_payout(bottom)
    assert bottom_payout.pct == services.FON_LEVEL_3
    assert bottom_payout.payout["cat1"] == Decimal("3000")


def test_only_this_month_counts():
    member = make_customer("Anita", "C1", level=1)
    from datetime import timedelta

    today = timezone.localdate()
    last_month = today.replace(day=1) - timedelta(days=1)
    bill(member, 100000, on=today)
    bill(member, 900000, on=last_month)
    assert services.fon_payout(member).total == Decimal("100000")


def test_a_stock_sale_counts_towards_fon_exactly_like_a_crm_one(received_piece, admin_user_):
    """The point of one ledger: a piece sold on the shop floor pays commission."""
    from stock import services as stock_services

    member = make_customer("Anita", "C1", level=1)
    sale = stock_services.sell_piece(admin_user_, received_piece, sold_price=Decimal("300000"), customer=member)
    Sale.objects.filter(pk=sale.pk).update(product_category="cat1")

    payout = services.fon_payout(member)
    assert payout.billing["cat1"] == Decimal("300000")
    assert payout.payout["cat1"] == Decimal("15000")


def test_an_uncategorised_sale_falls_to_the_lowest_rate():
    """Never guess upward: an unlabelled sale pays the smallest commission."""
    member = make_customer("Anita", "C1", level=1)
    bill(member, 100000, category=None)
    payout = services.fon_payout(member)
    assert payout.billing["cat3"] == Decimal("100000")
    assert payout.billing["cat1"] == Decimal("0")


def test_the_register_lists_every_member_biggest_first():
    small = make_customer("Small", "C1", level=1)
    large = make_customer("Large", "C2", level=1)
    bill(small, 100000)
    bill(large, 900000)
    register = services.fon_register()
    assert [payout.customer.name for payout in register] == ["Large", "Small"]
