import pytest
from django.urls import reverse

from inventory import seed
from inventory.models import BoxColour, CodePart, Pouch
from inventory.tests.fixtures_stones import build_workbook

pytestmark = pytest.mark.django_db


@pytest.fixture
def bucket(monkeypatch):
    from mediahub import storage

    book = build_workbook().getvalue()
    monkeypatch.setattr(storage, "put_bytes", lambda key, data, mime: None)
    monkeypatch.setattr(storage, "get_bytes", lambda key: book)
    return book


def test_upload_review_decide_commit(client, admin_user_, bucket):
    from django.core.files.uploadedfile import SimpleUploadedFile

    seed.load(BoxColour, CodePart)
    client.force_login(admin_user_)
    upload = SimpleUploadedFile("stones.xlsx", bucket,
                                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    review = client.post(reverse("inventory:import_home"), {"workbook": upload})
    assert review.status_code == 302
    url = review["Location"]
    body = client.get(url).content.decode()
    assert "SL!4" in body and "is also SL!2" in body

    batch_id = int(url.rstrip("/").split("/")[-1])
    blocked = client.post(reverse("inventory:import_commit", args=[batch_id]))
    assert blocked.status_code == 302 and not Pouch.objects.exists()

    form = {"pouch_no:SL!4": "9", "batch:SL!4": "", "pouch_no:SL!6": "", "batch:SL!6": "", "skip:SL!6": "1",
            "pouch_no:SL!5": "", "batch:SL!5": ""}
    client.post(url, form)
    client.post(reverse("inventory:import_commit", args=[batch_id]))
    assert Pouch.objects.count() == 5


def test_the_importer_is_closed_without_inv_masters(client, sales_user):
    client.force_login(sales_user)
    assert client.get(reverse("inventory:import_home")).status_code == 403
    assert client.post(reverse("inventory:import_commit", args=[1])).status_code == 403
