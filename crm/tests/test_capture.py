"""The capture-time affordances the port had dropped.

Photographing a record while creating it, editing a purchase, filtering the
purchase list by financial year, naming a walk-in without leaving the enquiry
form, and putting a quote on the enquiry it belongs to. Each of these existed
in ``legacy/CRM/nornament-crm.html``; each is a write path, so each gets a
test that it writes the right thing and refuses the wrong login.
"""
import json
from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from crm.models import Customer, Enquiry, RelatedPerson, StatusEvent
from mediahub.models import MediaAsset
from stock.models import Sale


@pytest.fixture
def customer(db):
    return Customer.objects.create(customer_code="NOR-001", name="Meera Raghavan", mobile="9820011223")


@pytest.fixture
def purchases(customer):
    return [
        Sale.objects.create(
            customer=customer, customer_name=customer.name, source=Sale.CRM, cost_at_sale=None,
            sold_on=when, sold_price=amount, product_category="cat1",
            # a description with no piece is the ordinary CRM row, and the shape
            # that broke the card when the template reached for piece.jewel_code
            description=f"Purchase of {amount}", invoice_no="INV-1", remarks="noted",
        )
        for when, amount in [(date(2025, 5, 2), 40000), (date(2026, 2, 9), 60000), (date(2026, 6, 1), 25000)]
    ]


def test_the_purchases_tab_renders_a_crm_sale_that_has_no_stock_piece(client, admin_user_, customer, purchases):
    """Every CRM purchase has description but no piece — the ordinary case."""
    client.force_login(admin_user_)
    response = client.get(reverse("crm:customer_detail", args=[customer.pk]), {"tab": "Purchases"})
    assert response.status_code == 200
    body = response.content.decode()
    assert "Purchase of 40000" in body
    assert "📝 noted" in body


def _png():
    """The smallest thing that is really a PNG, so the mime gate sees a photo."""
    raw = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000a49444154789c6300010000050001"
        "0d0a2db40000000049454e44ae426082"
    )
    return SimpleUploadedFile("shot.png", raw, content_type="image/png")


# ── T4: the financial-year filter ────────────────────────────────────────
def test_the_purchases_tab_offers_a_year_per_financial_year_bought_in(client, admin_user_, customer, purchases):
    client.force_login(admin_user_)
    response = client.get(reverse("crm:customer_detail", args=[customer.pk]), {"tab": "Purchases"})
    assert [year for year, _ in response.context["financial_years"]] == [2026, 2025]
    assert response.context["shown_count"] == 3
    assert response.context["shown_value"] == Decimal("125000")


def test_choosing_a_year_narrows_the_list_to_april_to_march(client, admin_user_, customer, purchases):
    """FY 2025 runs 1 Apr 2025 to 31 Mar 2026, so Feb 2026 is inside it."""
    client.force_login(admin_user_)
    response = client.get(reverse("crm:customer_detail", args=[customer.pk]), {"tab": "Purchases", "fy": "2025"})
    assert response.context["shown_count"] == 2
    assert response.context["shown_value"] == Decimal("100000")
    assert response.context["lifetime_value"] == Decimal("125000"), "lifetime must not follow the filter"


def test_a_nonsense_year_is_ignored_rather_than_erroring(client, admin_user_, customer, purchases):
    client.force_login(admin_user_)
    response = client.get(reverse("crm:customer_detail", args=[customer.pk]), {"tab": "Purchases", "fy": "drop"})
    assert response.status_code == 200
    assert response.context["shown_count"] == 3


# ── T3: editing a purchase ───────────────────────────────────────────────
def test_editing_a_purchase_moves_the_ledger_row_it_names(client, admin_user_, customer, purchases):
    client.force_login(admin_user_)
    sale = purchases[0]
    response = client.post(
        reverse("crm:edit_purchase", args=[customer.pk, sale.pk]),
        {"sold_price": "45000", "sold_on": "2025-05-02", "category": "cat3", "remarks": "renegotiated"},
    )
    assert response.status_code == 302
    sale.refresh_from_db()
    assert sale.sold_price == Decimal("45000")
    assert sale.product_category == "cat3"
    assert sale.remarks == "renegotiated"


def test_a_stock_sale_cannot_be_edited_through_the_crm(client, admin_user_, customer):
    """A stock sale carries a cost and a margin. Editing it here would move a
    number the margin report is read off, from a screen that cannot see it."""
    sale = Sale.objects.create(
        customer=customer, source=Sale.STOCK, sold_on=date(2026, 1, 1),
        sold_price=Decimal("10000"), cost_at_sale=Decimal("6000"),
    )
    client.force_login(admin_user_)
    assert client.get(reverse("crm:edit_purchase", args=[customer.pk, sale.pk])).status_code == 404


# ── T2: photographs taken while the record is being created ──────────────
@pytest.fixture
def bucket(monkeypatch, settings):
    """Catch the bytes instead of sending them. No test touches the network."""
    settings.MEDIA_WEBP_ON_UPLOAD = False
    put = {}
    monkeypatch.setattr("mediahub.storage.put_bytes", lambda key, data, ct: put.update(key=key, data=data, ct=ct))
    return put


def test_a_new_enquiry_carries_the_photo_it_was_created_with(client, admin_user_, customer, bucket):
    client.force_login(admin_user_)
    response = client.post(
        reverse("crm:pipeline_new", args=["enquiry"]),
        {
            "enquiry_code": "ENQ-900", "customer": customer.pk, "item_of_interest": "Polki set",
            "status": "New Enquiry", "temperature": "Warm", "photos": _png(),
        },
    )
    assert response.status_code == 302
    enquiry = Enquiry.objects.get(enquiry_code="ENQ-900")
    asset = MediaAsset.objects.get(scope="enquiry", scope_id=str(enquiry.pk))
    assert asset.confirmed_at is not None, "an attachment nobody confirmed never renders"
    assert asset.kind == "PHOTO"
    assert bucket["key"].startswith(f"crm/enquiry/{enquiry.pk}/")


def test_a_new_customer_carries_the_photo_it_was_created_with(client, admin_user_, bucket):
    client.force_login(admin_user_)
    response = client.post(
        reverse("crm:customer_new"),
        {
            "customer_code": "NOR-778", "name": "Photo Person", "reference_type": "Walk-in",
            "customer_type": "Regular", "temperature": "Warm", "photos": _png(),
        },
    )
    assert response.status_code == 302
    customer = Customer.objects.get(customer_code="NOR-778")
    assert MediaAsset.objects.filter(scope="customer", scope_id=str(customer.pk)).exists()


def test_a_file_the_bucket_would_not_serve_is_refused_not_stored(client, admin_user_, customer, bucket):
    """The browser names its own content type. An object we would refuse to
    serve has no business being in the bucket under that name either."""
    client.force_login(admin_user_)
    response = client.post(
        reverse("crm:pipeline_new", args=["enquiry"]),
        {
            "enquiry_code": "ENQ-901", "customer": customer.pk, "item_of_interest": "Polki set",
            "status": "New Enquiry", "temperature": "Warm",
            "photos": SimpleUploadedFile("payload.svg", b"<svg onload=alert(1)>", content_type="image/svg+xml"),
        },
    )
    assert response.status_code == 302
    enquiry = Enquiry.objects.get(enquiry_code="ENQ-901")
    assert not MediaAsset.objects.filter(scope="enquiry", scope_id=str(enquiry.pk)).exists()
    assert not bucket, "the refused file still reached the bucket"


def test_a_purchase_photo_belongs_to_the_purchase_not_the_customer(client, admin_user_, customer, bucket):
    """The legacy card showed the photo of *that* purchase. Hanging it on the
    customer instead puts every bill in one pile and none on its own row."""
    client.force_login(admin_user_)
    response = client.post(
        reverse("crm:add_purchase", args=[customer.pk]),
        {"sold_price": "1000", "sold_on": "2026-08-14", "category": "cat1", "photos": _png()},
    )
    assert response.status_code == 302
    sale = Sale.objects.get(customer=customer)
    assert MediaAsset.objects.filter(scope="sale", scope_id=str(sale.pk)).exists()
    assert not MediaAsset.objects.filter(scope="customer").exists()
    assert bucket["key"].startswith(f"crm/sale/{sale.pk}/")


# ── T17: related people named on the create form ─────────────────────────
def test_people_typed_on_the_customer_form_are_saved_with_the_customer(client, admin_user_):
    client.force_login(admin_user_)
    response = client.post(
        reverse("crm:customer_new"),
        {
            "customer_code": "NOR-777", "name": "Asha Nair", "reference_type": "Walk-in",
            "customer_type": "Regular", "temperature": "Warm",
            "person_name": ["Ravi Nair", "", "Kiran Nair"],
            "person_relation": ["Husband", "", "Son"],
            "person_phone": ["9820000001", "", ""],
        },
    )
    assert response.status_code == 302
    people = RelatedPerson.objects.filter(customer__customer_code="NOR-777")
    assert {p.name for p in people} == {"Ravi Nair", "Kiran Nair"}, "a blank row must not become a person"
    assert people.get(name="Ravi Nair").relation == "Husband"


# ── T18: naming a walk-in without leaving the form ───────────────────────
def test_quick_add_returns_to_the_form_with_the_new_customer_selected(client, admin_user_):
    client.force_login(admin_user_)
    back = reverse("crm:pipeline_new", args=["enquiry"])
    response = client.post(reverse("crm:quick_customer"), {"name": "Walk In", "phone": "9820055667", "next": back})
    customer = Customer.objects.get(name="Walk In")
    assert response.status_code == 302
    assert response["Location"] == f"{back}?customer={customer.pk}"


def test_quick_add_refuses_an_off_site_next(client, admin_user_):
    client.force_login(admin_user_)
    response = client.post(
        reverse("crm:quick_customer"), {"name": "Walk In", "next": "//evil.example.com/steal"}
    )
    assert "evil.example.com" not in response["Location"]


def test_quick_add_needs_a_name(client, admin_user_):
    client.force_login(admin_user_)
    client.post(reverse("crm:quick_customer"), {"name": "   "})
    assert not Customer.objects.exists()


# ── T9: the quote, attached to the enquiry it belongs to ─────────────────
def test_attaching_a_quote_puts_it_on_the_enquiry_timeline(client, admin_user_, customer):
    enquiry = Enquiry.objects.create(enquiry_code="ENQ-500", customer=customer, status="New Enquiry")
    client.force_login(admin_user_)
    payload = {
        "items": [{"name": "Polki necklace", "total": 185000,
                   "components": [{"kind": "metal", "weight": 22, "rate": 6000}], "makingRate": 1500}],
        "total": 185000,
    }
    response = client.post(
        reverse("crm:quote_attach"), {"enquiry": enquiry.pk, "quote": json.dumps(payload)}
    )
    assert response.status_code == 302
    enquiry.refresh_from_db()
    assert enquiry.status == "Quote Sent"
    event = StatusEvent.objects.filter(entity_type="enquiry", entity_id=enquiry.pk).latest("id")
    assert "Polki necklace" in event.note and "1,85,000" in event.note.replace("185,000", "1,85,000")


def test_an_empty_quote_is_refused_rather_than_logged_as_a_blank_update(client, admin_user_, customer):
    enquiry = Enquiry.objects.create(enquiry_code="ENQ-501", customer=customer, status="New Enquiry")
    client.force_login(admin_user_)
    client.post(reverse("crm:quote_attach"), {"enquiry": enquiry.pk, "quote": "{}"})
    enquiry.refresh_from_db()
    assert enquiry.status == "New Enquiry"


def test_a_mangled_quote_payload_does_not_500(client, admin_user_, customer):
    enquiry = Enquiry.objects.create(enquiry_code="ENQ-502", customer=customer, status="New Enquiry")
    client.force_login(admin_user_)
    response = client.post(reverse("crm:quote_attach"), {"enquiry": enquiry.pk, "quote": "{not json"})
    assert response.status_code == 302


# ── T11: the share target's landing page ─────────────────────────────────
def test_the_share_page_lists_customers_to_attach_to(client, admin_user_, customer):
    client.force_login(admin_user_)
    body = client.get(reverse("crm:share")).content.decode()
    assert "Meera Raghavan" in body
    assert 'data-customer="%d"' % customer.pk in body


def test_the_manifest_declares_a_share_target(client, admin_user_):
    client.force_login(admin_user_)
    manifest = client.get(reverse("crm:manifest")).json()
    assert manifest["share_target"]["method"] == "POST"
    assert manifest["share_target"]["action"].endswith("share-target")
    assert manifest["start_url"] == reverse("crm:dashboard")
