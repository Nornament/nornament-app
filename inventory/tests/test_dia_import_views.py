import pytest
from django.urls import reverse

from inventory import dia_seed
from inventory.models import DiamondLine, DiamondTerm
from inventory.tests.fixtures_diamonds import build_workbook

pytestmark = pytest.mark.django_db


@pytest.fixture
def bucket(monkeypatch):
    from mediahub import storage

    book = build_workbook().getvalue()
    monkeypatch.setattr(storage, "put_bytes", lambda key, data, mime: None)
    monkeypatch.setattr(storage, "get_bytes", lambda key: book)
    return book


def test_upload_review_commit(client, admin_user_, bucket):
    from django.core.files.uploadedfile import SimpleUploadedFile

    dia_seed.load(DiamondTerm)
    client.force_login(admin_user_)
    upload = SimpleUploadedFile("DIAMOND 31.xlsx", bucket,
                                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    review = client.post(reverse("inventory:dia_import_home"), {"workbook": upload})
    assert review.status_code == 302
    body = client.get(review["Location"]).content.decode()
    assert "DMLC SI I" in body                                    # a new code waiting for review
    batch_id = int(review["Location"].rstrip("/").split("/")[-1])
    client.post(reverse("inventory:dia_import_commit", args=[batch_id]))
    assert DiamondLine.objects.count() == 10                       # the fixture's one 0 ct row opens nothing
    again = client.post(reverse("inventory:dia_import_commit", args=[batch_id]), follow=True)
    assert "already been committed" in again.content.decode()


def test_the_importer_is_closed_without_inv_masters(client, sales_user):
    client.force_login(sales_user)
    assert client.get(reverse("inventory:dia_import_home")).status_code == 403
    assert client.post(reverse("inventory:dia_import_commit", args=[1])).status_code == 403
