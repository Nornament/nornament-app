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
    ("crm:dashboard", {}),
    ("crm:customer_list", {}),
    ("crm:reports", {}),
    ("crm:calculator", {}),
]


def _login(client, user):
    client.force_login(user)
    return client


def test_a_sales_login_sees_no_cost_vendor_or_margin_anywhere(client, sales_user, priced_and_sold):
    services.sell_piece(_admin(), priced_and_sold, sold_price=Decimal("300000"))
    _login(client, sales_user)
    secrets = secret_values(priced_and_sold)

    for name, kwargs in SALES_SCREENS:
        response = client.get(reverse(name, kwargs=kwargs))
        assert response.status_code in (200, 302), f"{name} returned {response.status_code}"
        if response.status_code != 200:
            continue
        body = response.content.decode()
        for label, values in secrets.items():
            for value in values:
                assert value not in body, f"{name} leaked a {label} value ({value})"


def test_the_same_screens_do_show_those_numbers_to_accounts(client, accounts_user, priced_and_sold):
    _login(client, accounts_user)
    response = client.get(reverse("stock:piece_detail", kwargs={"jewel_code": "ER00738"}))
    body = response.content.decode()
    cost = priced_and_sold.current_bom().total_cost_price
    assert f"{cost:,.0f}".replace(",", "") in body.replace(",", "")
    assert "Sharma Karigars" in body


def test_the_material_breakup_is_closed_to_a_role_without_the_capability(client, graphic_user, priced_and_sold):
    _login(client, graphic_user)
    response = client.get(reverse("stock:piece_bom", kwargs={"jewel_code": "ER00738"}))
    assert response.status_code == 403


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
        "stock:count_open", "stock:count_scan", "stock:count_unscan", "stock:count_close",
        "stock:repair_complete", "crm:add_purchase", "crm:order_status",
        # gated whole, and asserted to 403 above
        "stock:piece_bom", "stock:margin_report",
        # need an object that this fixture does not create
        "stock:count_detail", "stock:count_list", "crm:customer_detail", "crm:fon", "crm:fon_detail",
        "crm:enquiry_list", "crm:order_list", "crm:repair_list", "crm:client_material_list",
        "stock:piece_rows", "crm:customer_rows",
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
