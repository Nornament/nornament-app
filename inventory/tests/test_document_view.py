from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import ledger_jobs, ledger_single, services
from inventory.ledger_purchase import PurchaseHeader, PurchaseLine, post_purchase
from inventory.models import Movement, StockDocument
from inventory.tests.conftest import CUSTOMER, KARIGAR, SUPPLIER

pytestmark = pytest.mark.django_db
D = Decimal


def _job(user, shelf, parties):
    return ledger_jobs.job_work_out(user, shelf["onyx"], parties["karigar"], "2026/0431", 6, D("4"),
                                    expected_back=date.today() + timedelta(days=7))


def _memo(user, shelf, parties):
    return ledger_jobs.memo_out(user, shelf["ruby"], parties["customer"], "MEMO-0088", None, D("5"))


def _body(client, user, doc):
    client.force_login(user)
    return client.get(reverse("inventory:document", args=[doc.pk])).content.decode()


def test_a_job_work_page_shows_what_is_out_and_how_to_settle_it(client, accounts_user, shelf, parties):
    body = _body(client, accounts_user, _job(accounts_user, shelf, parties))
    for text in ("Job work 2026/0431", KARIGAR, "Open", "4.00 ct outstanding", "Received back", "Consumed", "Loss",
                 "↺ Undo last entry", "Reverse document", "₹31,676"):         # 4 ct × ₹7,919
        assert text in body, text


def test_settling_from_the_page_closes_the_challan(client, accounts_user, shelf, parties):
    doc, onyx = _job(accounts_user, shelf, parties), shelf["onyx"]
    client.force_login(accounts_user)
    url = reverse("inventory:document_settle", args=[doc.pk])
    client.post(url, {"pouch": onyx.pk, "how": "in", "pcs": "2", "ct": "1", "occurred_on": ""})
    client.post(url, {"pouch": onyx.pk, "how": "consumed", "pcs": "4", "ct": "3", "occurred_on": ""})
    doc.refresh_from_db()
    assert doc.status == StockDocument.Status.CLOSED
    body = _body(client, accounts_user, doc)
    # Deviation from the brief: the owner's 2026-10-01 ruling says Undo works on an
    # OPEN or CLOSED job work/memo (reopening it if undoing makes something outstanding
    # again), not only an open one — so a challan closed by its own settlements still
    # offers Undo. Only the settle choices (nothing left outstanding) disappear.
    assert "Closed" in body and "Received back" not in body and "↺ Undo last entry" in body


def test_too_much_back_comes_back_as_a_message(client, accounts_user, shelf, parties):
    doc = _job(accounts_user, shelf, parties)
    client.force_login(accounts_user)
    response = client.post(reverse("inventory:document_settle", args=[doc.pk]),
                           {"pouch": shelf["onyx"].pk, "how": "in", "ct": "9"}, follow=True)
    assert "cannot exceed what is outstanding" in response.content.decode()


def test_undo_and_reverse_from_the_page(client, accounts_user, shelf, parties):
    doc, onyx = _job(accounts_user, shelf, parties), shelf["onyx"]
    ledger_jobs.settle_job_work(accounts_user, doc, onyx, "in", 1, D("1"))
    client.force_login(accounts_user)
    client.post(reverse("inventory:document_undo", args=[doc.pk]))
    assert services.stocked().get(pk=onyx.pk).on_ct == D("8.5")
    response = client.post(reverse("inventory:document_reverse", args=[doc.pk]), follow=True)
    doc.refresh_from_db()
    assert doc.status == StockDocument.Status.REVERSED and "Reversed by REV-000001" in response.content.decode()
    assert services.stocked().get(pk=onyx.pk).on_ct == D("12.5")


def test_a_refused_reversal_is_a_message(client, accounts_user, shelf, parties):
    back = ledger_single.post_single(accounts_user, shelf["onyx"], Movement.Reason.SALES_RETURN, None, D("5"),
                                     customer=parties["customer"])
    ledger_single.post_single(accounts_user, shelf["onyx"], Movement.Reason.SALE, None, D("17"),
                              customer=parties["customer"])
    client.force_login(accounts_user)
    response = client.post(reverse("inventory:document_reverse", args=[back.pk]), follow=True)
    assert "below zero" in response.content.decode()


def test_a_memo_offers_returned_and_sold(client, accounts_user, shelf, parties):
    body = _body(client, accounts_user, _memo(accounts_user, shelf, parties))
    assert "Memo MEMO-0088" in body and CUSTOMER in body and "Returned" in body and "Sold" in body


def test_who_sees_which_name_and_which_action(client, admin_user_, sales_user, karigar_user, production_user, shelf, parties):
    job, memo = _job(admin_user_, shelf, parties), _memo(admin_user_, shelf, parties)
    body = _body(client, sales_user, job)
    assert "2026/0431" in body and KARIGAR not in body and "Received back" not in body and "Reverse document" not in body
    assert CUSTOMER in _body(client, sales_user, memo)
    body = _body(client, karigar_user, job)
    assert KARIGAR in body and "Received back" in body and "31,676" not in body
    assert CUSTOMER not in _body(client, karigar_user, memo)
    assert CUSTOMER not in _body(client, production_user, memo)


def test_a_purchase_page_shows_its_cost_only_to_those_who_see_cost(client, accounts_user, production_user, shelf):
    doc = post_purchase(accounts_user, PurchaseHeader(supplier=shelf["supplier"], occurred_on=date(2026, 8, 7),
                                                      invoice_no="B-77", landed_extras=D("100")),
                        [PurchaseLine(batch=shelf["batch"], pouch_no="3", stone_name="Tanzanite", shape="Oval",
                                      colour="Blue", pcs=6, ct=D("2"), cost_per_ct=D("4321"))])
    body = _body(client, accounts_user, doc)
    assert "Purchase B-77" in body and "4,321" in body and SUPPLIER in body and "landed extras ₹100" in body
    body = _body(client, production_user, doc)
    assert "4,321" not in body and "landed extras" not in body


def test_writes_need_the_right(client, admin_user_, sales_user, shelf, parties):
    doc = _job(admin_user_, shelf, parties)
    client.force_login(sales_user)
    for name in ("inventory:document_settle", "inventory:document_undo", "inventory:document_reverse"):
        response = client.post(reverse(name, args=[doc.pk]), {"pouch": shelf["onyx"].pk, "how": "in", "ct": "1"})
        assert response.status_code == 403, name


def test_client_view_never_opens_a_document(client, admin_user_, shelf, parties):
    doc = _job(admin_user_, shelf, parties)
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    assert client.get(reverse("inventory:document", args=[doc.pk])).status_code == 302
    assert client.post(reverse("inventory:document_reverse", args=[doc.pk])).status_code == 302
    doc.refresh_from_db()
    assert doc.status == StockDocument.Status.OPEN
