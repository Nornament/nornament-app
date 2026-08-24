"""Importing a device backup: the CRM photos that exist nowhere else."""
import base64
import json
from io import StringIO

import pytest
from django.core.management import call_command

from crm.models import Customer, Order
from mediahub.models import MediaAsset

pytestmark = pytest.mark.django_db

PIXEL = base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489")
).decode()


@pytest.fixture
def uploads(monkeypatch):
    """Storage is stubbed: this asserts what we would upload, and once."""
    written = {}

    def put_bytes(key, data, content_type):
        written[key] = (data, content_type)

    monkeypatch.setattr("mediahub.storage.put_bytes", put_bytes)
    return written


@pytest.fixture
def backup_file(tmp_path):
    def write(store):
        path = tmp_path / "device.json"
        path.write_text(json.dumps({"nornament_media_v4": store}))
        return str(path)

    return write


def test_a_photo_becomes_an_object_and_a_row(uploads, backup_file, capsys):
    customer = Customer.objects.create(customer_code="NC1", name="Anita", legacy_id="c_abc")
    path = backup_file(
        {"customer_c_abc": [{"id": "m1", "name": "ring.png", "data": f"data:image/png;base64,{PIXEL}"}]}
    )
    call_command("import_device_backup", path, stdout=StringIO())

    asset = MediaAsset.objects.get()
    assert asset.scope == "customer" and asset.scope_id == str(customer.pk)
    assert asset.mime_type == "image/png"
    assert asset.confirmed_at is not None
    assert asset.storage_key.startswith(f"crm/customer/{customer.pk}/")
    assert asset.storage_key in uploads


def test_importing_twice_imports_once(uploads, backup_file):
    Customer.objects.create(customer_code="NC1", name="Anita", legacy_id="c_abc")
    path = backup_file({"customer_c_abc": [{"data": f"data:image/png;base64,{PIXEL}"}]})
    call_command("import_device_backup", path, stdout=StringIO())
    call_command("import_device_backup", path, stdout=StringIO())
    assert MediaAsset.objects.count() == 1


def test_the_same_photo_from_two_devices_lands_once(uploads, backup_file, tmp_path):
    Customer.objects.create(customer_code="NC1", name="Anita", legacy_id="c_abc")
    first = backup_file({"customer_c_abc": [{"data": f"data:image/png;base64,{PIXEL}"}]})
    second = tmp_path / "device2.json"
    second.write_text(json.dumps({"nornament_media_v4": {"customer_c_abc": [{"data": f"data:image/png;base64,{PIXEL}"}]}}))
    call_command("import_device_backup", first, str(second), stdout=StringIO())
    assert MediaAsset.objects.count() == 1


def test_an_item_whose_entity_is_missing_is_reported_not_dropped_silently(uploads, backup_file):
    out = StringIO()
    path = backup_file({"customer_c_nobody": [{"data": f"data:image/png;base64,{PIXEL}"}]})
    call_command("import_device_backup", path, stdout=out)
    assert MediaAsset.objects.count() == 0
    assert "belong to entities this database does not have" in out.getvalue()


def test_dry_run_uploads_nothing(uploads, backup_file):
    Customer.objects.create(customer_code="NC1", name="Anita", legacy_id="c_abc")
    path = backup_file({"customer_c_abc": [{"data": f"data:image/png;base64,{PIXEL}"}]})
    call_command("import_device_backup", path, "--dry-run", stdout=StringIO())
    assert MediaAsset.objects.count() == 0
    assert uploads == {}


def test_orders_and_client_materials_are_scoped_too(uploads, backup_file):
    customer = Customer.objects.create(customer_code="NC1", name="Anita", legacy_id="c_abc")
    order = Order.objects.create(order_code="NO1", customer=customer, legacy_id="o_1", status="Designing")
    path = backup_file({"order_o_1": [{"data": f"data:image/png;base64,{PIXEL}"}]})
    call_command("import_device_backup", path, stdout=StringIO())
    asset = MediaAsset.objects.get()
    assert asset.scope == "order" and asset.scope_id == str(order.pk)


def test_a_corrupt_entry_is_counted_not_fatal(uploads, backup_file):
    Customer.objects.create(customer_code="NC1", name="Anita", legacy_id="c_abc")
    out = StringIO()
    path = backup_file({"customer_c_abc": [{"data": "not-a-data-url"}, {"data": f"data:image/png;base64,{PIXEL}"}]})
    call_command("import_device_backup", path, stdout=out)
    assert MediaAsset.objects.count() == 1
    assert "unreadable    " in out.getvalue()
