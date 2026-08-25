"""One revenue ledger — the problem this rewrite exists to fix."""
from decimal import Decimal

import pytest
from django.utils import timezone

from crm import services
from crm.models import Customer
from stock.models import Sale

pytestmark = pytest.mark.django_db


def test_revenue_counts_both_sources_and_margin_counts_only_stock(received_piece, admin_user_):
    from stock import services as stock_services

    customer = Customer.objects.create(customer_code="C1", name="Anita")
    stock_services.sell_piece(admin_user_, received_piece, sold_price=Decimal("300000"), customer=customer)
    Sale.objects.create(
        customer=customer,
        sold_on=timezone.localdate(),
        sold_price=Decimal("50000"),
        source=Sale.CRM,
        cost_at_sale=None,
        product_category="cat2",
    )

    today = timezone.localdate()
    start = today.replace(day=1)
    assert services.revenue_between(start, today) == Decimal("350000")
    assert services.revenue_between(start, today, Sale.STOCK) == Decimal("300000")
    assert services.revenue_between(start, today, Sale.CRM) == Decimal("50000")

    margin = services.margin_between(start, today)
    # the CRM sale has no cost, so it contributes to revenue and not to margin
    assert margin["revenue"] == Decimal("300000")
    assert margin["margin"] == Decimal("300000") - received_piece.current_bom().total_cost_price


def test_a_crm_sale_has_no_margin_rather_than_a_fictional_one():
    customer = Customer.objects.create(customer_code="C1", name="Anita")
    sale = Sale.objects.create(
        customer=customer, sold_on=timezone.localdate(), sold_price=Decimal("50000"), source=Sale.CRM, cost_at_sale=None
    )
    sale.refresh_from_db()
    assert sale.margin_amt is None


def test_lifetime_value_reads_the_ledger():
    customer = Customer.objects.create(customer_code="C1", name="Anita")
    for amount in (10000, 20000):
        Sale.objects.create(
            customer=customer, sold_on=timezone.localdate(), sold_price=Decimal(amount), source=Sale.CRM
        )
    assert services.customer_lifetime_value(customer) == Decimal("30000")
