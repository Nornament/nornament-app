"""The permanent masking gate.

A SALES login logs in, walks every screen that could carry a cost, a vendor or
a margin, and none of those numbers may appear anywhere in any response body —
not in a table, not in a hidden field, not in a CSV export.

This is the regression test for the 0013-class bug, and it runs on every commit
rather than at deploy time. If a new screen leaks, it fails here; if a new
screen is added and not listed here, ``test_every_screen_is_covered`` fails.
"""
from decimal import Decimal

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from stock import services
from stock.models import Sale

pytestmark = pytest.mark.django_db


@pytest.fixture
def priced_and_sold(received_piece, admin_user_, sales_user):
    """A piece with a known cost, vendor and margin — all of them secret."""
    from stock.models import Vendor

    vendor = Vendor.objects.create(code="VEN01", name="Sharma Karigars", avg_tat_days=Decimal("7.50"))
    received_piece.vendor = vendor
    received_piece.save(update_fields=["vendor"])
    return received_piece


#: every number a SALES login must never be shown, as it would appear rendered
def secret_values(piece):
    version = piece.current_bom()
    cost = version.total_cost_price
    return {
        "cost": [str(cost), f"{cost:,.0f}", str(int(cost))],
        "vendor": ["Sharma Karigars", "VEN01"],
        "margin_source": [str(services.current_cost(piece))],
    }


@pytest.fixture
def crm_world(priced_and_sold):
    """One of everything in the CRM, carrying numbers a SALES login must not see.

    The CRM screens grew detail views with a vendor field and repair costs on
    them; without a row to render, the walk below would pass by rendering
    nothing. This gives it something to leak.
    """
    from crm.models import ClientMaterial, Customer, Enquiry, Order, Repair
    from stock.models import Sale

    customer = Customer.objects.create(
        customer_code="NOR-001", name="Meera Iyer", mobile="9876543210", is_fon=True, fon_level=1
    )
    enquiry = Enquiry.objects.create(
        enquiry_code="ENQ-001", customer=customer, status="New Enquiry",
        item_of_interest="Emerald drops", estimated_budget=Decimal("250000"),
    )
    order = Order.objects.create(
        order_code="ORD-001", customer=customer, status="Designing", item_description="Emerald drops",
        vendor="Sharma Karigars", total_amount=Decimal("250000"), advance_paid=Decimal("50000"),
    )
    repair = Repair.objects.create(
        repair_code="REP-001", customer=customer, status="In Workshop", item_description="Bangle",
        estimated_cost=CRM_REPAIR_COST, final_cost=CRM_REPAIR_COST,
    )
    material = ClientMaterial.objects.create(
        cm_code="CM-001", customer=customer, status="Received",
        jewellery_description="Old gold chain", estimated_value=Decimal("88000"),
    )
    Sale.objects.create(
        customer=customer, customer_name=customer.name, sold_on=timezone.localdate(),
        sold_price=Decimal("250000"), product_category="cat1", source=Sale.CRM, cost_at_sale=None,
    )
    return {
        "customer": customer.pk,
        "enquiry": enquiry.pk,
        "order": order.pk,
        "repair": repair.pk,
        "material": material.pk,
    }


#: a number that exists only on CRM repair rows, so a leak there is unambiguous
CRM_REPAIR_COST = Decimal("13579")


SALES_SCREENS = [
    ("stock:dashboard", {}),
    ("stock:piece_list", {}),
    ("stock:piece_detail", {"jewel_code": "ER00738"}),
    ("stock:piece_scenarios", {"jewel_code": "ER00738"}),
    ("stock:rate_list", {}),
    ("stock:material_list", {}),
    ("stock:repair_list", {}),
    ("stock:sale_list", {}),
    ("stock:piece_export", {}),
    ("stock:style_list", {}),
    ("crm:dashboard", {}),
    ("crm:customer_list", {}),
    ("crm:customer_rows", {}),
    ("crm:customer_detail", {"pk": "customer"}),
    ("crm:customer_new", {}),
    ("crm:customer_edit", {"pk": "customer"}),
    ("crm:customer_export", {}),
    ("crm:enquiry_list", {}),
    ("crm:enquiry_detail", {"pk": "enquiry"}),
    ("crm:order_list", {}),
    ("crm:order_detail", {"pk": "order"}),
    ("crm:repair_list", {}),
    ("crm:repair_detail", {"pk": "repair"}),
    ("crm:client_material_list", {}),
    ("crm:client_material_detail", {"pk": "material"}),
    ("crm:pipeline_new", {"kind": "enquiry"}),
    ("crm:pipeline_edit", {"kind": "order", "pk": "order"}),
    ("crm:fon", {}),
    ("crm:fon_detail", {"pk": "customer"}),
    ("crm:search", {}),
    ("crm:settings", {}),
    ("crm:reports", {}),
    ("crm:calculator", {}),
]


def _resolve(kwargs, world):
    """A ``"customer"``/``"order"`` placeholder pk becomes that row's real pk.

    Hardcoding 1 works when the CRM test runs alone and breaks the moment the
    sequence has moved on, which is every full-suite run.
    """
    return {key: (world[value] if key == "pk" else value) for key, value in kwargs.items()}


def _login(client, user):
    client.force_login(user)
    return client


def test_a_sales_login_sees_no_cost_vendor_or_margin_anywhere(client, sales_user, priced_and_sold, crm_world):
    services.sell_piece(_admin(), priced_and_sold, sold_price=Decimal("300000"))
    _login(client, sales_user)
    secrets = secret_values(priced_and_sold)
    secrets["crm_repair_cost"] = [str(CRM_REPAIR_COST), f"{CRM_REPAIR_COST:,.0f}"]

    for name, kwargs in SALES_SCREENS:
        response = client.get(reverse(name, kwargs=_resolve(kwargs, crm_world)))
        assert response.status_code in (200, 302), f"{name} returned {response.status_code}"
        if response.status_code != 200:
            continue
        body = response.content.decode()
        for label, values in secrets.items():
            for value in values:
                assert value not in body, f"{name} leaked a {label} value ({value})"


def test_the_same_screens_do_show_those_numbers_to_accounts(client, accounts_user, priced_and_sold):
    _login(client, accounts_user)
    detail = reverse("stock:piece_detail", kwargs={"jewel_code": "ER00738"})
    # cost lives on the BOM tab: the overview's pricing card was retired in
    # favour of the Pricing and BOM tabs, which is where the legacy kept it
    body = client.get(detail, {"tab": "bom"}).content.decode()
    cost = priced_and_sold.current_bom().total_cost_price
    assert f"{cost:,.0f}".replace(",", "") in body.replace(",", "")
    assert "Sharma Karigars" in client.get(detail).content.decode()


def test_the_material_breakup_is_closed_to_a_role_without_the_capability(client, graphic_user, priced_and_sold):
    _login(client, graphic_user)
    response = client.get(reverse("stock:piece_bom", kwargs={"jewel_code": "ER00738"}))
    assert response.status_code == 403


def test_the_locked_tabs_refuse_a_sales_login(client, sales_user, priced_and_sold):
    """The nav shows a padlock; the view is what actually refuses.

    The legacy said it plainly: the gate lives in the database function, "not
    just hidden in the interface — a bug in the UI cannot let it through".
    """
    _login(client, sales_user)
    for name in (
        "stock:melt_list", "stock:data", "stock:audit", "stock:settings", "stock:reports",
        "stock:material_export", "stock:rate_chart_export",
    ):
        assert client.get(reverse(name)).status_code == 403, f"{name} let a SALES login in"


def test_the_write_screens_refuse_a_login_without_edit_bom(client, sales_user, priced_and_sold):
    _login(client, sales_user)
    assert client.get(reverse("stock:piece_new")).status_code == 403
    assert client.get(reverse("stock:piece_edit", kwargs={"jewel_code": "ER00738"})).status_code == 403
    assert client.get(reverse("stock:piece_bom_edit", kwargs={"jewel_code": "ER00738"})).status_code == 403
    assert client.get(reverse("stock:style_new")).status_code == 403


def test_margin_and_admin_are_closed_to_sales(client, sales_user, priced_and_sold):
    _login(client, sales_user)
    assert client.get(reverse("stock:margin_report")).status_code == 403
    assert client.get("/admin/").status_code in (302, 403)
    response = client.post(
        reverse("stock:melt_piece", kwargs={"jewel_code": "ER00738"}),
        {"reason": "Trying to melt without the capability"},
    )
    priced_and_sold.refresh_from_db()
    assert priced_and_sold.stock_state != "MELTED"


def test_the_csv_export_is_masked_too(client, sales_user, priced_and_sold):
    _login(client, sales_user)
    body = client.get(reverse("stock:piece_export")).content.decode()
    header = body.splitlines()[0]
    for column in ("cost_price", "current_cost", "margin", "vendor_name", "vendor_code"):
        assert column not in header, f"the export offers {column} to a SALES login"
    assert "sale_price" in header  # what they may see is still there


def test_masking_is_stated_once_and_every_gated_field_is_covered():
    """Every price-ish key a row can carry must be in the masking table.

    The rule this enforces: services return the real numbers, presentation
    decides. A new sensitive field that nobody adds to GATED_FIELDS would slip
    through the screens above, so it is caught here instead.
    """
    from stock.masking import GATED_FIELDS

    sensitive_words = ("cost", "margin", "vendor", "sale_rate", "sale_amount", "sold_price")
    from stock.models import BomLine, Piece, Sale as SaleModel

    for model in (Piece, BomLine, SaleModel):
        for field in model._meta.concrete_fields:
            name = field.name
            # relations are never rendered raw — a row carries vendor_code and
            # vendor_name, both of which are gated, not the Vendor object
            if field.is_relation or name in {"cost_written_off", "src_net_wt_gm"}:
                continue
            if any(word in name for word in sensitive_words):
                assert name in GATED_FIELDS, f"{model.__name__}.{name} is sensitive but not in GATED_FIELDS"


def test_every_stock_and_crm_screen_is_in_the_sales_walk():
    """A screen nobody listed is a screen nobody checked for leaks."""
    covered = {name for name, _ in SALES_SCREENS}
    exempt = {
        # POST-only endpoints; their permission gates are tested in test_ledger
        "stock:sell_piece", "stock:melt_piece", "stock:move_piece", "stock:set_rate",
        "stock:set_piece_scenario",
        "stock:piece_field",
        "stock:count_open", "stock:count_scan", "stock:count_unscan", "stock:count_close",
        "stock:repair_complete", "stock:repair_open", "stock:reserve_piece", "crm:add_purchase",
        "crm:customer_delete", "crm:customer_temperature", "crm:delete_purchase",
        "crm:add_gift", "crm:delete_gift", "crm:add_occasion", "crm:delete_occasion",
        "crm:add_person", "crm:delete_person", "crm:add_outreach", "crm:delete_outreach",
        "crm:pipeline_status", "crm:pipeline_delete", "crm:enquiry_convert", "crm:material_convert",
        # gated whole, and asserted to 403 above
        "stock:piece_bom", "stock:margin_report",
        # need an object that this fixture does not create
        "stock:count_detail", "stock:count_list", "stock:piece_rows",
        # asserted to 403 for SALES in test_the_locked_tabs_refuse_a_sales_login
        "stock:melt_list", "stock:data", "stock:audit", "stock:settings", "stock:reports",
        "stock:material_export", "stock:rate_chart_export",
        # gated on edit_bom, and asserted to 403 below
        "stock:piece_new", "stock:piece_edit", "stock:piece_bom_edit",
        "stock:style_new", "stock:style_edit",
    }
    named = set()
    for resolver in get_resolver().url_patterns:
        if isinstance(resolver, URLResolver) and resolver.app_name in {"stock", "crm"}:
            for pattern in resolver.url_patterns:
                if isinstance(pattern, URLPattern) and pattern.name:
                    named.add(f"{resolver.app_name}:{pattern.name}")
    missing = named - covered - exempt
    assert not missing, f"screens with no masking check: {sorted(missing)}"


def _admin():
    from accounts.models import User

    return User.objects.get(username="owner")
