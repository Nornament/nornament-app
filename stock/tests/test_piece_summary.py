"""The piece summary page: internal name, compliance lines, editable vendor
section, and sales typed in from the old books."""
from decimal import Decimal

import pytest
from django.urls import reverse

from stock.models import JobCard, PastSale, PieceCertificate, Vendor

pytestmark = pytest.mark.django_db


def _field(client, piece, field, value):
    return client.post(
        reverse("stock:piece_field", args=[piece.jewel_code]), {"field": field, field: value}
    )


def test_the_summary_reads_in_the_asked_order(client, admin_user_, received_piece):
    client.force_login(admin_user_)
    page = client.get(reverse("stock:piece_detail", args=[received_piece.jewel_code])).content.decode()
    assert page.index("<dt>Internal name</dt>") < page.index("<dt>Design name (marketing)</dt>")
    for gone in ("<dt>Quality</dt>", "<h3>Planning</h3>", "<h3>Availability</h3>", "<dt>Hallmarking centre</dt>"):
        assert gone not in page
    for there in ("<dt>Hallmark</dt>", "<dt>HUID No</dt>", "<dt>Certificate company</dt>", "<h3>Sales history</h3>"):
        assert there in page


def test_compliance_and_vendor_lines_save_in_place(client, admin_user_, received_piece):
    client.force_login(admin_user_)
    received_piece.vendor = Vendor.objects.create(code="KAR", name="Karigar One")
    received_piece.save()
    _field(client, received_piece, "hallmarked", "YES")
    _field(client, received_piece, "company", "IGI")
    _field(client, received_piece, "cert_number", "LG123")
    _field(client, received_piece, "job_no", "JC-77")
    _field(client, received_piece, "avg_tat_days", "12")
    client.post(
        reverse("stock:piece_marketing", args=[received_piece.jewel_code]),
        {"action": "field", "field": "internal_name", "internal_name": "Peacock studs"},
    )

    received_piece.refresh_from_db()
    assert received_piece.hallmarked == "YES"
    assert received_piece.style.internal_name == "Peacock studs"
    cert = PieceCertificate.objects.get(piece=received_piece)
    assert (cert.company, cert.cert_number) == ("IGI", "LG123")
    assert JobCard.objects.get(piece=received_piece).job_no == "JC-77"
    assert received_piece.vendor.avg_tat_days == Decimal("12")


def test_a_login_without_vendor_access_cannot_edit_the_vendor_section(client, sales_user, received_piece):
    from django.contrib.auth.models import Permission

    from accounts.capabilities import EDIT_BOM

    app, code = EDIT_BOM.split(".")
    sales_user.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=code))
    client.force_login(sales_user)
    assert _field(client, received_piece, "job_no", "JC-1").status_code == 403
    assert not JobCard.objects.exists()


def test_an_old_sale_is_added_shown_and_removed(client, admin_user_, received_piece):
    client.force_login(admin_user_)
    url = reverse("stock:piece_past_sale", args=[received_piece.jewel_code])
    client.post(url, {"sold_on": "2023-11-04", "customer_name": "Meera Shah", "sold_price": "185000", "remarks": "Diwali"})
    past = PastSale.objects.get(piece=received_piece)
    assert (past.customer_name, past.sold_price) == ("Meera Shah", Decimal("185000"))

    for tab in ("overview", "history"):
        page = client.get(reverse("stock:piece_detail", args=[received_piece.jewel_code]), {"tab": tab}).content.decode()
        assert "Meera Shah" in page and "Old books" in page

    client.post(url, {"delete": past.pk})
    assert not PastSale.objects.exists()



def test_a_login_without_edit_rights_cannot_add_an_old_sale(client, sales_user, received_piece):
    client.force_login(sales_user)
    response = client.post(
        reverse("stock:piece_past_sale", args=[received_piece.jewel_code]), {"customer_name": "Sneaky"}
    )
    assert response.status_code == 403 and not PastSale.objects.exists()
