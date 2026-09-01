"""Delivering an order, and stages the app does not recognise.

Both are things the client found missing between the legacy CRM and this one:

* the legacy ``updateOrder`` wrote a ``purchases[]`` entry the moment an order
  reached ``Delivered``, so the customer's value moved with the delivery. This
  app moved the status and stopped there, so a delivered order showed nothing
  against the customer.
* a record whose status is not one of this app's stages matched no kanban
  column and no stage on the rail, so it disappeared from the board entirely
  rather than saying it was somewhere unexpected.
"""
from decimal import Decimal

import pytest
from django.urls import reverse

from crm import services
from crm.models import Customer, Order
from stock.models import Sale

pytestmark = pytest.mark.django_db


@pytest.fixture
def customer():
    return Customer.objects.create(customer_code="NOR-001", name="Meera Iyer", mobile="9876543210")


@pytest.fixture
def order(customer):
    return Order.objects.create(
        order_code="ORD-001",
        customer=customer,
        status="Ready",
        item_description="Polki choker",
        metal_type="Gold 22k",
        total_amount=Decimal("450000"),
    )


# ── delivery becomes a purchase ──────────────────────────────────────────
def test_delivering_an_order_puts_the_bill_in_the_customers_purchase_history(order, customer):
    sale = services.record_order_delivery(order, amount=Decimal("475000"))
    assert sale.customer == customer
    assert sale.source == Sale.CRM
    assert sale.sold_price == Decimal("475000")
    assert sale.crm_order == order
    assert services.customer_lifetime_value(customer) == Decimal("475000")


def test_the_bill_typed_at_delivery_is_written_back_onto_the_order(order):
    services.record_order_delivery(order, amount=Decimal("475000"))
    order.refresh_from_db()
    assert order.billing_amount == Decimal("475000")
    assert order.billing_date is not None


def test_a_delivery_with_no_typed_bill_falls_back_to_the_orders_own_figure(order):
    sale = services.record_order_delivery(order)
    assert sale.sold_price == Decimal("450000")


def test_billing_amount_beats_total_amount_because_it_is_what_the_invoice_said(order):
    order.billing_amount = Decimal("460000")
    order.save(update_fields=["billing_amount"])
    assert services.record_order_delivery(order).sold_price == Decimal("460000")


def test_an_order_with_no_amount_anywhere_records_nothing_rather_than_zero(customer):
    order = Order.objects.create(order_code="ORD-002", customer=customer, status="Ready")
    assert services.record_order_delivery(order) is None
    assert Sale.objects.filter(customer=customer).count() == 0


def test_delivering_twice_moves_the_one_purchase_instead_of_adding_a_second(order, customer):
    """The legacy ``sourceOrderId`` guard, kept: one order, one purchase."""
    services.record_order_delivery(order, amount=Decimal("475000"))
    services.record_order_delivery(order, amount=Decimal("480000"))
    sales = Sale.objects.filter(customer=customer)
    assert sales.count() == 1
    assert sales.first().sold_price == Decimal("480000")


def test_the_commission_band_follows_the_metal_as_the_legacy_rule_did(customer):
    gold = Order.objects.create(order_code="ORD-003", customer=customer, metal_type="Gold 22k", status="Ready")
    polki = Order.objects.create(order_code="ORD-004", customer=customer, metal_type="Polki", status="Ready")
    blank = Order.objects.create(order_code="ORD-005", customer=customer, status="Ready")
    assert services.delivery_category(gold) == "cat2"
    assert services.delivery_category(polki) == "cat1"
    assert services.delivery_category(blank) == "cat2"


def test_an_order_with_no_customer_bills_nobody(order):
    order.customer = None
    order.save(update_fields=["customer"])
    assert services.record_order_delivery(order, amount=Decimal("1")) is None


# ── through the screen ───────────────────────────────────────────────────
def test_moving_an_order_to_delivered_through_the_form_records_the_purchase(
    client, admin_user_, order, customer
):
    client.force_login(admin_user_)
    response = client.post(
        reverse("crm:pipeline_status", args=["order", order.pk]),
        {"status": "Delivered", "billing_amount": "475000", "by": "Priya", "note": "Handed over"},
        follow=True,
    )
    assert response.status_code == 200
    order.refresh_from_db()
    assert order.status == "Delivered"
    sale = Sale.objects.get(crm_order=order)
    assert sale.sold_price == Decimal("475000")
    assert sale.customer == customer


def test_delivering_without_an_amount_says_so_rather_than_failing_quietly(client, admin_user_, customer):
    order = Order.objects.create(order_code="ORD-006", customer=customer, status="Ready")
    client.force_login(admin_user_)
    response = client.post(
        reverse("crm:pipeline_status", args=["order", order.pk]), {"status": "Delivered"}, follow=True
    )
    assert Sale.objects.filter(customer=customer).count() == 0
    assert any("no bill amount" in str(m) for m in response.context["messages"])


def test_typing_the_amount_afterwards_records_the_purchase_it_could_not_before(
    client, admin_user_, customer
):
    order = Order.objects.create(order_code="ORD-007", customer=customer, status="Delivered")
    client.force_login(admin_user_)
    client.post(
        reverse("crm:pipeline_edit", args=["order", order.pk]),
        {
            "order_code": "ORD-007",
            "customer": customer.pk,
            "status": "Delivered",
            "billing_amount": "300000",
        },
        follow=True,
    )
    order.refresh_from_db()
    assert Sale.objects.get(crm_order=order).sold_price == Decimal("300000")


def test_moving_a_non_order_pipeline_bills_nothing(client, admin_user_, customer):
    """Only orders carry money; a repair reaching Delivered is not a sale."""
    from crm.models import Repair

    repair = Repair.objects.create(repair_code="REP-001", customer=customer, status="Ready", final_cost=Decimal("500"))
    client.force_login(admin_user_)
    client.post(reverse("crm:pipeline_status", args=["repair", repair.pk]), {"status": "Delivered"}, follow=True)
    assert Sale.objects.filter(customer=customer).count() == 0


# ── a stage the app does not know ────────────────────────────────────────
def test_a_record_at_an_unknown_stage_still_appears_on_the_board(client, admin_user_, customer):
    """It came across from the legacy CRM with a status this app has no column
    for. Hiding it is how a record 'loses its stage'."""
    Order.objects.create(order_code="ORD-008", customer=customer, status="Sent to Karigar")
    client.force_login(admin_user_)
    response = client.get(reverse("crm:order_list"), {"view": "kanban"})
    body = response.content.decode()
    assert "ORD-008" in body
    assert "Unmapped stage" in body
    assert response.context["unmapped_statuses"] == ["Sent to Karigar"]


def test_a_known_stage_adds_no_unmapped_column(client, admin_user_, customer, order):
    client.force_login(admin_user_)
    response = client.get(reverse("crm:order_list"), {"view": "kanban"})
    assert response.context["unmapped_statuses"] == []
    assert "Unmapped stage" not in response.content.decode()


def test_the_detail_screen_names_the_stage_it_does_not_recognise(client, admin_user_, customer):
    order = Order.objects.create(order_code="ORD-009", customer=customer, status="Sent to Karigar")
    client.force_login(admin_user_)
    response = client.get(reverse("crm:order_detail", args=[order.pk]))
    body = response.content.decode()
    assert response.context["unknown_status"] is True
    assert "Sent to Karigar" in body
    assert "not one of the orders stages" in body


def test_a_terminal_status_is_not_reported_as_unknown(client, admin_user_, customer):
    order = Order.objects.create(order_code="ORD-010", customer=customer, status="Cancelled")
    client.force_login(admin_user_)
    response = client.get(reverse("crm:order_detail", args=[order.pk]))
    assert response.context["unknown_status"] is False
    assert response.context["lost"] is True


# ── the backfill ─────────────────────────────────────────────────────────
def test_the_backfill_reports_before_it_writes(customer):
    """It creates revenue rows, so it never does so without being asked."""
    from django.core.management import call_command
    from io import StringIO

    Order.objects.create(
        order_code="ORD-011", customer=customer, status="Delivered", total_amount=Decimal("120000")
    )
    out = StringIO()
    call_command("backfill_delivered_purchases", stdout=out)
    assert "ORD-011" in out.getvalue()
    assert Sale.objects.count() == 0

    call_command("backfill_delivered_purchases", "--commit", stdout=StringIO())
    assert Sale.objects.get(crm_order__order_code="ORD-011").sold_price == Decimal("120000")


def test_the_backfill_leaves_an_order_that_already_has_its_purchase_alone(order, customer):
    from django.core.management import call_command
    from io import StringIO

    order.status = "Delivered"
    order.save(update_fields=["status"])
    services.record_order_delivery(order, amount=Decimal("450000"))
    call_command("backfill_delivered_purchases", "--commit", stdout=StringIO())
    assert Sale.objects.filter(crm_order=order).count() == 1


def test_the_backfill_names_an_order_it_cannot_bill_rather_than_inventing_zero(customer):
    from django.core.management import call_command
    from io import StringIO

    Order.objects.create(order_code="ORD-012", customer=customer, status="Delivered")
    out = StringIO()
    call_command("backfill_delivered_purchases", "--commit", stdout=out)
    assert "no bill amount" in out.getvalue()
    assert Sale.objects.count() == 0


def test_a_login_that_may_not_see_sale_prices_is_not_offered_the_bill(client, graphic_user, order):
    """The bill is a sale figure. A role without ``view_sale`` may still move
    the order to Delivered; it just does not get to read or type the amount."""
    client.force_login(graphic_user)
    response = client.get(reverse("crm:order_detail", args=[order.pk]))
    assert "billing_amount" not in response.content.decode()
    assert response.context["delivery_sale"] is None
