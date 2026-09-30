import pytest
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

from inventory.models import DiamondRate, DiamondTerm
from inventory.tests.conftest import DIA_COST, DIA_SUPPLIER
from inventory.tests.fixtures_diamonds import ivy_workbook

pytestmark = pytest.mark.django_db


def test_settings_lists_everything_for_an_editor(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:dia_settings")).content.decode()
    for heading in ("User rights", "Suppliers", "Categories", "Shapes", "Colour grades", "Clarity grades",
                    "Size bands", "Item codes", "Rate card", "Range → grade expansion"):
        assert heading in body, heading
    assert DIA_SUPPLIER in body and "Advance" in body and DIA_COST in body
    assert 'id="shape"' in body                                # the rail's anchors land


def test_settings_is_refused_without_the_masters_right(client, sales_user, diamonds):
    client.force_login(sales_user)
    body = client.get(reverse("inventory:dia_settings")).content.decode()
    assert "Not permitted for Sales / Showroom" in body and "Rate card" not in body
    assert client.post(reverse("inventory:dia_term_add"), {"kind": "shape", "value": "Cushion"}).status_code == 403


def test_add_rename_delete_a_value(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    client.post(reverse("inventory:dia_term_add"), {"kind": "shape", "value": "Cushion"})
    cushion = DiamondTerm.objects.get(kind="shape", value="Cushion")
    client.post(reverse("inventory:dia_term_rename", args=[cushion.pk]), {"value": "Cushion Brilliant"})
    cushion.refresh_from_db()
    assert cushion.value == "Cushion Brilliant"
    client.post(reverse("inventory:dia_term_delete", args=[cushion.pk]))
    assert not DiamondTerm.objects.filter(pk=cushion.pk).exists()
    in_use = DiamondTerm.objects.get(kind="shape", value="Round")
    response = client.post(reverse("inventory:dia_term_delete", args=[in_use.pk]), follow=True)
    assert "in use" in response.content.decode()


def test_a_rate_can_be_set_and_codes_edited(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    client.post(reverse("inventory:dia_rate_save"), {"code": "DPCEF VVS-VS", "size_text": "", "cost_rate": "21000",
                                                     "sale_rate": "27000", "effective_from": "2026-09-30"})
    assert DiamondRate.objects.filter(code_id="DPCEF VVS-VS").exists()
    shape = DiamondTerm.objects.get(kind="shape", value="Round")
    client.post(reverse("inventory:dia_code_save", args=["FPL"]),
                {"shape": shape.pk, "colour": "", "clarity": "", "confirmed": "1", "note": ""})
    from inventory.models import DiamondCode
    assert DiamondCode.objects.get(pk="FPL").confirmed


def test_only_an_admin_toggles_rights(client, admin_user_, accounts_user, diamonds):
    client.force_login(accounts_user)
    assert client.post(reverse("inventory:dia_right_toggle"), {"role": "SALES", "right": "inv_job", "on": "1"}).status_code == 403
    client.force_login(admin_user_)
    client.post(reverse("inventory:dia_right_toggle"), {"role": "SALES", "right": "inv_job", "on": "1"})
    assert Group.objects.get(name="SALES").permissions.filter(codename="inv_job").exists()


def test_suppliers_can_be_added(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    client.post(reverse("inventory:dia_supplier_save"), {"code": "bha", "name": "Bhansali Diamonds", "city": "Surat", "terms": "30 days"})
    from stock.models import Vendor
    assert Vendor.objects.get(code="BHA").terms == "30 days"


def test_suppliers_stay_hidden_from_an_editor_without_view_vendor(client, sales_user, diamonds):
    sales_user.user_permissions.add(Permission.objects.get(codename="inv_masters"))
    client.force_login(sales_user)
    body = client.get(reverse("inventory:dia_settings")).content.decode()
    assert "Item codes" in body and DIA_SUPPLIER not in body and 'id="suppliers"' not in body
    response = client.post(reverse("inventory:dia_supplier_save"), {"code": "BHA", "name": "Bhansali Diamonds"})
    assert response.status_code == 403
    from stock.models import Vendor
    assert not Vendor.objects.filter(code="BHA").exists()


def test_rates_load_from_an_ivy_export_upload(client, accounts_user, diamonds):
    from django.core.files.uploadedfile import SimpleUploadedFile

    client.force_login(accounts_user)
    book = ivy_workbook([("DRFGH VS SI", "+2", 15000, 19000), ("DXYZ VVS VS", "+2", 1, 1)])
    response = client.post(reverse("inventory:dia_rates_ivy"),
                           {"workbook": SimpleUploadedFile("ivy.xlsx", book.getvalue())}, follow=True)
    assert "1 rates loaded; 1 codes in the export are not diamond lines here." in response.content.decode()
    assert DiamondRate.objects.filter(code_id="DRFGH VS-SI", size_text="+2", cost_rate=15000).exists()
