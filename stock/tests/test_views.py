"""Screen smoke tests: every page renders, and the HTMX partials match them."""
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
    assert "FOUND" in body and "ER00738" in body
    assert "<html" not in body


def test_an_unknown_scan_says_so_without_failing(client, admin_user_, received_piece):
    client.force_login(admin_user_)
    count = services.open_count(admin_user_, "MUM")
    response = client.post(reverse("stock:count_scan", kwargs={"count_id": count.pk}), {"code": "GHOST"})
    assert "UNKNOWN" in response.content.decode()


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
