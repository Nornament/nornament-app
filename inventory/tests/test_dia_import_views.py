import pytest
from django.urls import reverse

from django.core.files.uploadedfile import SimpleUploadedFile

from inventory import dia_seed
from inventory.importers import dia_plan, diamonds
from inventory.models import DiamondLine, DiamondTerm
from inventory.tests.fixtures_diamonds import PLAN_ROWS, build_workbook, fancy_workbook
from stock.models import ImportBatch

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
    assert "DMLC SI-I" in body                                    # a new code waiting for review
    batch_id = int(review["Location"].rstrip("/").split("/")[-1])
    client.post(reverse("inventory:dia_import_commit", args=[batch_id]))
    assert DiamondLine.objects.count() == 10                       # the fixture's one 0 ct row opens nothing
    again = client.post(reverse("inventory:dia_import_commit", args=[batch_id]), follow=True)
    assert "already been committed" in again.content.decode()


def test_the_importer_is_closed_without_inv_masters(client, sales_user):
    client.force_login(sales_user)
    assert client.get(reverse("inventory:dia_import_home")).status_code == 403
    assert client.post(reverse("inventory:dia_import_commit", args=[1])).status_code == 403


def _upload(client, monkeypatch, book):
    from mediahub import storage

    data = book.getvalue()
    monkeypatch.setattr(storage, "put_bytes", lambda key, blob, mime: None)
    monkeypatch.setattr(storage, "get_bytes", lambda key: data)
    return client.post(reverse("inventory:dia_import_home"), {"workbook": SimpleUploadedFile("d.xlsx", data)})["Location"]


def test_an_unread_code_waits_on_the_review_page(client, admin_user_, monkeypatch):
    dia_seed.load(DiamondTerm)
    client.force_login(admin_user_)
    body = client.get(_upload(client, monkeypatch, fancy_workbook())).content.decode()
    assert "DTRQ VS-SI" in body and 'value="? Q"' in body


def test_a_blocked_row_stays_blocked_until_someone_chooses(client, admin_user_, monkeypatch):
    dia_seed.load(DiamondTerm)
    dup = ["B-771", "Round", "DRFGH VS-SI", "FGH", "VS SI", "+6-12", None, 3.40, None, None, None, "Diamond"]
    dia_plan.commit(dia_plan.analyse(diamonds.parse(fancy_workbook([dup, dup]))), admin_user_)
    b900 = ["B-900", "Princess", "DPCEF VVS-VS", "EF", "VVS VS", "+2", None, 0.85, None, None, None, "Diamond"]
    shifted = [PLAN_ROWS[0], b900, dup, dup]
    client.force_login(admin_user_)
    review = _upload(client, monkeypatch, fancy_workbook(shifted))
    body = client.get(review).content.decode()
    assert '<option value="" selected>choose…</option>' in body
    ref = DiamondLine.objects.order_by("pk").first().ref
    client.post(review, {"row:FANCY FINAL!4": "", "row:FANCY FINAL!4:line": ref,     # what the untouched form sends
                         "row:FANCY FINAL!5": "", "row:FANCY FINAL!5:line": ref,
                         "code:DPCEF VVS-VS:shape": "Princess", "code:DPCEF VVS-VS:colour": "E-F",
                         "code:DPCEF VVS-VS:clarity": "VVS-VS", "code:DPCEF VVS-VS:confirmed": "1"})
    batch = ImportBatch.objects.get(source="DIAMONDS")
    assert "code:DPCEF VVS-VS" in batch.decisions and "row:FANCY FINAL!4" not in batch.decisions
    assert dia_plan.analyse(diamonds.parse(fancy_workbook(shifted)), batch.decisions).counts()["blocked"] == 2


def test_a_row_only_skip_can_clear_offers_only_skip(client, admin_user_, monkeypatch):
    from mediahub import storage

    dia_seed.load(DiamondTerm)
    book = fancy_workbook([[None, "Marquise", "DMIJ VVS VS", "IJ", "VVS VS", "2.3*1.3", 6, 0.31, -32200, -9982]]).getvalue()
    monkeypatch.setattr(storage, "put_bytes", lambda key, data, mime: None)
    monkeypatch.setattr(storage, "get_bytes", lambda key: book)
    client.force_login(admin_user_)
    upload = SimpleUploadedFile("Dia_Stock.xlsx", book,
                                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    body = client.get(client.post(reverse("inventory:dia_import_home"), {"workbook": upload})["Location"]).content.decode()
    assert "Rate out of range" in body and 'value="skip"' in body and 'value="map"' not in body
