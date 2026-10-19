"""The stock report's column picker and its photos, on screen and in the workbook."""
import io

import pytest
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook
from PIL import Image

from accounts.models import Role
from mediahub.models import MediaAsset

pytestmark = pytest.mark.django_db


def _sheet(client, **params):
    response = client.get(reverse("stock:reports_export"), params)
    assert response.status_code == 200
    return load_workbook(io.BytesIO(response.content))["Pieces"]


def _png():
    out = io.BytesIO()
    Image.new("RGB", (400, 300), "gold").save(out, "PNG")
    return out.getvalue()


def test_the_chosen_fields_are_exactly_the_sheet_columns(client, admin_user_, received_piece, chart):
    client.force_login(admin_user_)
    sheet = _sheet(client, f=["karat", "jewel_code", "cost_price"])
    # the report's own order, not the URL's
    assert [cell.value for cell in sheet[1]] == ["Jewel code", "Karat", "Cost (₹)"]
    assert sheet["A2"].value == "ER00738"

    page = client.get(reverse("stock:reports"), {"f": ["karat", "jewel_code"]}).content.decode()
    assert "<th>Jewel code</th><th>Karat</th></tr>" in page
    # the export link carries the same choice
    assert "f=jewel_code&amp;f=karat" in page


def test_a_login_without_cost_cannot_ask_for_a_cost_column(client, sales_user, received_piece, chart):
    role = Role.objects.get(group__name="SALES")
    role.screens = [*role.screens, "reports"]
    role.save()
    client.force_login(sales_user)
    sheet = _sheet(client, f=["jewel_code", "cost_price", "current_cost", "margin", "vendor_name", "sale_price"])
    assert [cell.value for cell in sheet[1]] == ["Jewel code", "Sale price (₹)"]
    page = client.get(reverse("stock:reports")).content.decode()
    assert 'value="cost_price"' not in page and 'value="sale_price"' in page


def test_the_photo_is_embedded_and_a_broken_one_does_not_fail_the_export(client, admin_user_, received_piece, chart):
    client.force_login(admin_user_)
    MediaAsset.objects.create(
        piece=received_piece, kind="PHOTO", mime_type="image/png", file_name="front.png",
        inline_data=_png(), confirmed_at=timezone.now(),
    )
    sheet = _sheet(client, f=["photo", "jewel_code"])
    assert [cell.value for cell in sheet[1]] == ["Photo", "Jewel code"]
    assert len(sheet._images) == 1

    # bytes that are not a picture, and a bucket key with no storage behind it
    MediaAsset.objects.filter(piece=received_piece).update(inline_data=b"not a png")
    assert len(_sheet(client, f=["photo", "jewel_code"])._images) == 0
    MediaAsset.objects.filter(piece=received_piece).update(inline_data=None, storage_key="pieces/gone.png")
    sheet = _sheet(client, f=["photo", "jewel_code"])
    assert len(sheet._images) == 0 and sheet["B2"].value == "ER00738"
