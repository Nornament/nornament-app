"""Screen smoke tests: every page renders, and the HTMX partials match them."""
from decimal import Decimal

import pytest
from django.urls import reverse

from stock import services

pytestmark = pytest.mark.django_db


def test_every_screen_renders_for_an_admin(client, admin_user_, received_piece, chart, scenarios):
    client.force_login(admin_user_)
    count = services.open_count(admin_user_, "MUM")
    pages = [
        reverse("stock:dashboard"),
        reverse("stock:piece_list"),
        reverse("stock:piece_detail", kwargs={"jewel_code": "ER00738"}),
        reverse("stock:piece_bom", kwargs={"jewel_code": "ER00738"}),
        reverse("stock:piece_scenarios", kwargs={"jewel_code": "ER00738"}),
        reverse("stock:material_list"),
        reverse("stock:rate_list"),
        reverse("stock:count_list"),
        reverse("stock:count_detail", kwargs={"count_id": count.pk}),
        reverse("stock:repair_list"),
        reverse("stock:sale_list"),
        reverse("stock:margin_report"),
        reverse("crm:dashboard"),
        reverse("crm:customer_list"),
        reverse("crm:enquiry_list"),
        reverse("crm:order_list"),
        reverse("crm:repair_list"),
        reverse("crm:client_material_list"),
        reverse("crm:fon"),
        reverse("crm:reports"),
        reverse("crm:calculator"),
    ]
    for page in pages:
        response = client.get(page)
        assert response.status_code == 200, f"{page} returned {response.status_code}"


def test_the_htmx_rows_partial_lists_the_same_pieces(client, admin_user_, received_piece):
    client.force_login(admin_user_)
    full = client.get(reverse("stock:piece_list")).content.decode()
    partial = client.get(reverse("stock:piece_rows"), headers={"HX-Request": "true"}).content.decode()
    assert "ER00738" in full and "ER00738" in partial
    assert "<nav" not in partial  # a partial is a partial


def test_search_filters_the_rows(client, admin_user_, received_piece):
    client.force_login(admin_user_)
    hit = client.get(reverse("stock:piece_rows"), {"q": "ER007"}).content.decode()
    miss = client.get(reverse("stock:piece_rows"), {"q": "NOTHINGLIKETHIS"}).content.decode()
    assert "ER00738" in hit
    assert "ER00738" not in miss and "No pieces match" in miss


def test_the_scan_flow_returns_a_row_partial_not_a_page(client, admin_user_, received_piece):
    client.force_login(admin_user_)
    count = services.open_count(admin_user_, "MUM")
    response = client.post(reverse("stock:count_scan", kwargs={"count_id": count.pk}), {"code": "ER00738"})
    body = response.content.decode()
    assert response.status_code == 200
    assert ">Found<" in body and "ER00738" in body
    assert "<html" not in body


def test_an_unknown_scan_says_so_without_failing(client, admin_user_, received_piece):
    client.force_login(admin_user_)
    count = services.open_count(admin_user_, "MUM")
    response = client.post(reverse("stock:count_scan", kwargs={"count_id": count.pk}), {"code": "GHOST"})
    assert "Unknown code" in response.content.decode()


def test_selling_from_the_screen_writes_one_sale(client, admin_user_, received_piece):
    from stock.models import Sale

    client.force_login(admin_user_)
    client.post(
        reverse("stock:sell_piece", kwargs={"jewel_code": "ER00738"}),
        {"sold_price": "300000", "discount_amt": "0", "customer_name": "Anita"},
    )
    assert Sale.objects.filter(piece=received_piece).count() == 1


def test_healthz_answers_without_a_login(client):
    assert client.get(reverse("healthz")).status_code == 200


def test_an_anonymous_visitor_is_sent_to_the_login(client):
    response = client.get(reverse("stock:piece_list"))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


def test_a_rate_edit_is_saved_and_shows_its_history_on_the_row(client, admin_user_, chart, materials):
    """The rate moves, and the row reads back what it was before."""
    client.force_login(admin_user_)
    line = chart.lines.get()
    url = reverse("stock:settings") + "?tab=charts&chart=" + str(chart.pk)
    response = client.post(
        url,
        {
            "pk": line.pk,
            "chart": chart.pk,
            "material": line.material_id,
            "size_band": "",
            "cost_rate": "160000",
            "sale_rate": "180000",
            "rate_uom": "CT",
        },
        follow=True,
    )
    line.refresh_from_db()
    assert line.cost_rate == Decimal("160000")
    page = response.content.decode()
    assert "cost_rate 150000.0000 → 160000" in page  # the history entry, on the row
    assert "1 edit" in page


def test_a_locked_chart_refuses_the_edit(client, admin_user_, chart):
    client.force_login(admin_user_)
    chart.is_locked = True
    chart.save(update_fields=["is_locked"])
    line = chart.lines.get()
    client.post(
        reverse("stock:settings") + "?tab=charts",
        {"pk": line.pk, "chart": chart.pk, "material": line.material_id, "size_band": "", "cost_rate": "1"},
    )
    line.refresh_from_db()
    assert line.cost_rate == Decimal("150000")


# ── the detail screen's inline editors ───────────────────────────────────
def _edit(client, field, value, code="ER00738"):
    return client.post(
        reverse("stock:piece_field", kwargs={"jewel_code": code}), {"field": field, field: value}
    )


def test_a_field_edited_in_place_is_saved(client, admin_user_, received_piece):
    client.force_login(admin_user_)
    response = _edit(client, "sub_category", "Jhumka")
    assert response.status_code == 302
    received_piece.refresh_from_db()
    assert received_piece.sub_category == "Jhumka"


def test_the_jewel_code_cannot_be_edited_in_place(client, admin_user_, received_piece):
    """It is the identity of a physical object; every ledger row points at it."""
    client.force_login(admin_user_)
    response = _edit(client, "jewel_code", "ER99999")
    assert response.status_code == 403
    received_piece.refresh_from_db()
    assert received_piece.jewel_code == "ER00738"


def test_a_field_that_is_not_offered_inline_is_refused(client, admin_user_, received_piece):
    """The whitelist is the gate: a hand-rolled POST cannot reach stock_state."""
    client.force_login(admin_user_)
    assert _edit(client, "stock_state", "SOLD").status_code == 403
    received_piece.refresh_from_db()
    assert received_piece.stock_state != "SOLD"


def test_a_role_without_edit_bom_cannot_edit_in_place(client, sales_user, received_piece):
    client.force_login(sales_user)
    assert _edit(client, "sub_category", "Jhumka").status_code == 403


def test_an_invalid_value_is_reported_and_nothing_is_saved(client, admin_user_, received_piece):
    client.force_login(admin_user_)
    response = _edit(client, "measured_gross_wt_gm", "not a weight")
    assert response.status_code == 302  # back to the screen, with the message
    received_piece.refresh_from_db()
    assert received_piece.measured_gross_wt_gm != "not a weight"


# ── selling against a customer ───────────────────────────────────────────
def test_a_sale_can_create_the_customer_it_is_recorded_against(client, admin_user_, received_piece):
    """The counter has a name and a phone; that is enough to be a real row."""
    from crm.models import Customer
    from stock.models import Sale

    client.force_login(admin_user_)
    client.post(
        reverse("stock:sell_piece", kwargs={"jewel_code": "ER00738"}),
        {"sold_price": "300000", "new_customer_name": "Anita Rao", "new_customer_phone": "9812345678"},
    )
    customer = Customer.objects.get(name="Anita Rao")
    assert customer.customer_code.startswith("NOR-")
    sale = Sale.objects.get(piece=received_piece)
    assert sale.customer == customer
    assert sale.customer_name == "Anita Rao" and sale.customer_phone == "9812345678"


def test_a_sale_can_be_recorded_against_an_existing_customer(client, admin_user_, received_piece):
    from crm.models import Customer
    from stock.models import Sale

    existing = Customer.objects.create(customer_code="NOR-900", name="Meera", mobile="9800000000")
    client.force_login(admin_user_)
    client.post(
        reverse("stock:sell_piece", kwargs={"jewel_code": "ER00738"}),
        {"sold_price": "300000", "customer": existing.pk},
    )
    assert Sale.objects.get(piece=received_piece).customer == existing
    assert Customer.objects.count() == 1  # nothing new was invented


def test_a_sale_can_be_recorded_against_a_customer_picked_from_the_list(client, admin_user_, received_piece):
    """The datalist hands back ``Name — CODE — phone``; the code is the identity."""
    from crm.models import Customer
    from stock.models import Sale

    existing = Customer.objects.create(customer_code="NOR-041", name="Meera", mobile="9800000000")
    client.force_login(admin_user_)
    client.post(
        reverse("stock:sell_piece", kwargs={"jewel_code": "ER00738"}),
        {"sold_price": "300000", "customer_pick": "Meera — NOR-041 — 9800000000"},
    )
    assert Sale.objects.get(piece=received_piece).customer == existing


def test_a_typed_customer_nobody_recognises_stops_the_sale(client, admin_user_, received_piece):
    """Selling to a near-miss name silently detaches the sale from the customer."""
    from crm.models import Customer
    from stock.models import Sale

    Customer.objects.create(customer_code="NOR-041", name="Meera")
    client.force_login(admin_user_)
    response = client.post(
        reverse("stock:sell_piece", kwargs={"jewel_code": "ER00738"}), {"sold_price": "300000", "customer_pick": "Meara"}
    )
    assert response.status_code == 302
    assert not Sale.objects.filter(piece=received_piece).exists()
    received_piece.refresh_from_db()
    assert received_piece.stock_state != "SOLD"


def test_the_category_pills_count_the_search_and_filter_the_table(client, admin_user_, materials):
    """A pill counts what the search matched; picking one narrows only the table."""
    client.force_login(admin_user_)
    url = reverse("stock:settings")
    page = client.get(url, {"tab": "mats"}).content.decode()
    assert "Diamond <b>1</b>" in page and "All <b>3</b>" in page
    assert 'id="matdlg"' in page and "+ Add material" in page  # the add form is a modal now

    filtered = client.get(url, {"tab": "mats", "cat": "DIAMOND"}).content.decode()
    assert "DRKL" in filtered and "MAKING" not in filtered
    assert "All <b>3</b>" in filtered  # the counts are of the search, not of the filtered table

    searched = client.get(url, {"tab": "mats", "q": "Gold"}).content.decode()
    assert "Metal <b>1</b>" in searched and "Diamond <b>0</b>" in searched
