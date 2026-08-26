"""The CRM's write paths, ported from the legacy React app.

The old app did all of this in the browser against Supabase: generate the next
code, move a status and push onto ``statusLog[]``, turn a confirmed enquiry
into an order, turn a held client material into an order or a repair. Each of
those is now a service, and each is checked here.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from crm import services
from crm.models import ClientMaterial, Customer, Enquiry, Order, OutreachEntry, Repair, StatusEvent
from crm.templatetags.crm_extras import initials, inr, status_class
from stock.models import Sale

pytestmark = pytest.mark.django_db


@pytest.fixture
def customer():
    return Customer.objects.create(customer_code="NOR-001", name="Meera Iyer", mobile="9876543210")


# ── codes ────────────────────────────────────────────────────────────────
def test_the_next_code_follows_the_highest_in_use_not_the_row_count(customer):
    """The legacy generator counted rows, so a delete reissued a live code."""
    Enquiry.objects.create(enquiry_code="ENQ-001", customer=customer, status="New Enquiry")
    Enquiry.objects.create(enquiry_code="ENQ-009", customer=customer, status="New Enquiry")
    assert services.next_code(Enquiry, "enquiry") == "ENQ-010"


def test_the_first_code_of_an_empty_table_is_001():
    assert services.next_code(Customer, "customer") == "NOR-001"


# ── status moves ─────────────────────────────────────────────────────────
def test_moving_a_status_writes_the_log_entry_that_goes_with_it(customer):
    order = Order.objects.create(order_code="ORD-001", customer=customer, status="Order Confirmed")
    services.log_status(order, "order", "Polishing", note="Sent to Rakesh", by="Priya")
    order.refresh_from_db()
    assert order.status == "Polishing"
    event = StatusEvent.objects.get(entity_type="order", entity_id=order.pk)
    assert (event.status, event.note, event.by) == ("Polishing", "Sent to Rakesh", "Priya")


# ── conversions ──────────────────────────────────────────────────────────
def test_a_confirmed_enquiry_becomes_an_order_carrying_its_detail(customer):
    enquiry = Enquiry.objects.create(
        enquiry_code="ENQ-001",
        customer=customer,
        status="Order Confirmed",
        item_of_interest="Emerald drops",
        metal_type="Gold 18k",
        estimated_budget=Decimal("250000"),
    )
    order = services.convert_enquiry_to_order(enquiry, by="Priya")
    assert order.order_code == "ORD-001"
    assert order.customer == customer
    assert order.item_description == "Emerald drops"
    assert order.total_amount == Decimal("250000")
    assert order.enquiry == enquiry


def test_converting_the_same_enquiry_twice_returns_the_first_order(customer):
    """The legacy button opened a second order on a double tap."""
    enquiry = Enquiry.objects.create(enquiry_code="ENQ-001", customer=customer, status="Order Confirmed")
    first = services.convert_enquiry_to_order(enquiry)
    assert services.convert_enquiry_to_order(enquiry) == first
    assert Order.objects.count() == 1


def test_a_client_material_can_become_an_order_or_a_repair(customer):
    material = ClientMaterial.objects.create(
        cm_code="CM-001", customer=customer, status="Received", jewellery_description="Old chain"
    )
    order = services.client_material_to_order(material)
    material.refresh_from_db()
    assert material.status == "Moved to Order"
    assert order.item_description == "Old chain"

    second = ClientMaterial.objects.create(
        cm_code="CM-002", customer=customer, status="Received", jewellery_description="Bent bangle"
    )
    repair = services.client_material_to_repair(second)
    second.refresh_from_db()
    assert second.status == "Moved to Repair"
    assert repair.jewellery_received == "Bent bangle"


def test_a_recorded_purchase_is_a_crm_sale_with_no_cost(customer):
    sale = services.record_purchase(
        customer, sold_on=timezone.localdate(), sold_price=Decimal("50000"), product_category="cat2"
    )
    assert sale.source == Sale.CRM
    assert sale.cost_at_sale is None
    assert services.customer_lifetime_value(customer) == Decimal("50000")


# ── the lead engine ──────────────────────────────────────────────────────
def test_an_overdue_follow_up_makes_a_customer_hot(customer):
    Enquiry.objects.create(
        enquiry_code="ENQ-001",
        customer=customer,
        status="Quote Sent",
        follow_up_date=timezone.localdate() - timedelta(days=3),
    )
    temperature, why = services.computed_temp(customer)
    assert temperature == "Hot"
    assert "overdue 3d" in why


def test_a_customer_with_nothing_logged_is_cold(customer):
    customer.created_at = timezone.now() - timedelta(days=400)
    customer.save(update_fields=["created_at"])
    assert services.computed_temp(customer)[0] == "Cold"


def test_a_recent_purchase_makes_a_customer_hot(customer):
    services.record_purchase(customer, sold_on=timezone.localdate(), sold_price=Decimal("1"), product_category="cat1")
    assert services.computed_temp(customer)[0] == "Hot"


def test_an_open_enquiry_with_no_follow_up_date_is_a_gap(customer):
    Enquiry.objects.create(enquiry_code="ENQ-001", customer=customer, status="Quote Sent")
    kinds = [gap["kind"] for gap in services.lead_gaps()]
    assert "nofollow" in kinds


def test_a_closed_enquiry_is_never_a_gap(customer):
    Enquiry.objects.create(enquiry_code="ENQ-001", customer=customer, status="Lost")
    assert not [gap for gap in services.lead_gaps() if gap["enquiry"]]


# ── search ───────────────────────────────────────────────────────────────
def test_search_spans_customers_and_every_pipeline(customer):
    Enquiry.objects.create(enquiry_code="ENQ-001", customer=customer, item_of_interest="Emerald", status="Quote Sent")
    Order.objects.create(order_code="ORD-001", customer=customer, item_description="Emerald", status="Designing")
    sections = {group["section"] for group in services.search("emerald")}
    assert sections == {"Enquiries", "Orders"}
    assert services.search("meera")[0]["section"] == "Customers"
    assert services.search("") == []


# ── template helpers ─────────────────────────────────────────────────────
def test_rupees_group_the_indian_way():
    assert inr(1234567) == "₹12,34,567"
    assert inr(999) == "₹999"
    assert inr(1000) == "₹1,000"
    assert inr(None) == "₹0"


def test_initials_and_status_classes_match_the_legacy_maps():
    assert initials("Meera Iyer") == "MI"
    assert initials("") == "?"
    assert status_class("In Workshop") == "s-karigar"
    assert status_class("Something new") == "br"


# ── the screens, end to end ──────────────────────────────────────────────
def test_the_full_crm_write_cycle_through_the_views(client, admin_user_):
    """Create a customer, an enquiry, log outreach, move it, convert it."""
    client.force_login(admin_user_)

    response = client.post(
        reverse("crm:customer_new"),
        {
            "customer_code": "NOR-001",
            "name": "Meera Iyer",
            "mobile": "9876543210",
            "preferred_phone": "mobile",
            "customer_type": "Regular",
            "temperature": "Warm",
            "reference_type": "Walk-in",
        },
    )
    assert response.status_code == 302
    customer = Customer.objects.get(customer_code="NOR-001")

    client.post(
        reverse("crm:pipeline_new", args=["enquiry"]),
        {
            "enquiry_code": "ENQ-001",
            "customer": customer.pk,
            "item_of_interest": "Emerald drops",
            "status": "New Enquiry",
            "temperature": "Warm",
        },
    )
    enquiry = Enquiry.objects.get(enquiry_code="ENQ-001")
    assert StatusEvent.objects.filter(entity_type="enquiry", entity_id=enquiry.pk).count() == 1

    client.post(
        reverse("crm:add_outreach", args=[customer.pk]),
        {"type": "phone", "date": timezone.localdate(), "outcome": "Interested", "notes": "Wants to see options"},
    )
    assert OutreachEntry.objects.filter(customer=customer).count() == 1
    customer.refresh_from_db()
    assert customer.outreach_done is True

    client.post(
        reverse("crm:pipeline_status", args=["enquiry", enquiry.pk]),
        {"status": "Order Confirmed", "note": "Confirmed on call", "by": "Priya"},
    )
    enquiry.refresh_from_db()
    assert enquiry.status == "Order Confirmed"

    client.post(reverse("crm:enquiry_convert", args=[enquiry.pk]))
    assert Order.objects.filter(enquiry=enquiry).count() == 1


def test_deleting_a_pipeline_row_takes_its_status_log_with_it(client, admin_user_, customer):
    client.force_login(admin_user_)
    repair = Repair.objects.create(repair_code="REP-001", customer=customer, status="Received")
    services.log_status(repair, "repair", "Diagnosed")
    client.post(reverse("crm:pipeline_delete", args=["repair", repair.pk]))
    assert not Repair.objects.filter(pk=repair.pk).exists()
    assert not StatusEvent.objects.filter(entity_type="repair", entity_id=repair.pk).exists()


def test_a_sales_login_cannot_edit_a_field_it_cannot_see(client, sales_user, customer):
    """The edit form must not carry a gated value, even as a hidden input.

    SALES holds ``view_sale``, so the order total is theirs to edit; the vendor
    and a repair cost are not, and neither may reach the HTML.
    """
    client.force_login(sales_user)
    order = Order.objects.create(
        order_code="ORD-001", customer=customer, status="Designing", vendor="Sharma Karigars",
        total_amount=Decimal("250000"),
    )
    body = client.get(reverse("crm:pipeline_edit", args=["order", order.pk])).content.decode()
    assert "Sharma Karigars" not in body
    assert "250000" in body  # a sale price is theirs to see

    repair = Repair.objects.create(
        repair_code="REP-001", customer=customer, status="In Workshop", estimated_cost=Decimal("13579")
    )
    body = client.get(reverse("crm:pipeline_edit", args=["repair", repair.pk])).content.decode()
    assert "13579" not in body


# ── the ?next= redirect ──────────────────────────────────────────────────
OFF_SITE = [
    "//evil.example",           # protocol-relative: a slash, and off-site
    "/\\evil.example",          # browsers read the backslash as a second slash
    "https://evil.example/x",
    "http:/evil.example",
]


@pytest.mark.parametrize("target", OFF_SITE)
def test_a_status_move_never_redirects_off_site(client, admin_user_, customer, target):
    """``?next=`` returns you to the list you came from — and nowhere else.

    ``startswith("/")`` used to be the whole check, which let a protocol-relative
    URL through.
    """
    client.force_login(admin_user_)
    enquiry = Enquiry.objects.create(enquiry_code="ENQ-001", customer=customer, status="New Enquiry")
    response = client.post(
        reverse("crm:pipeline_status", args=["enquiry", enquiry.pk]),
        {"status": "Quote Sent", "next": target},
    )
    assert response.status_code == 302
    assert "evil.example" not in response["Location"]


def test_a_status_move_does_honour_a_local_next(client, admin_user_, customer):
    client.force_login(admin_user_)
    enquiry = Enquiry.objects.create(enquiry_code="ENQ-001", customer=customer, status="New Enquiry")
    response = client.post(
        reverse("crm:pipeline_status", args=["enquiry", enquiry.pk]),
        {"status": "Quote Sent", "next": "/crm/enquiries/?status=Quote+Sent"},
    )
    assert response["Location"] == "/crm/enquiries/?status=Quote+Sent"
