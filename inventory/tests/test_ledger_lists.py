from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import ledger, ledger_jobs, ledger_single
from inventory.models import Movement, StockDocument
from inventory.tests.conftest import CUSTOMER, KARIGAR

pytestmark = pytest.mark.django_db
D = Decimal


def _get(client, user, name, query=""):
    client.force_login(user)
    return client.get(reverse(name) + query)


def test_job_work_out_lists_open_challans_with_an_overdue_chip(client, accounts_user, shelf, parties):
    today = date.today()
    ledger_jobs.job_work_out(accounts_user, shelf["onyx"], parties["karigar"], "2026/0417", 6, D("4"),
                             occurred_on=today - timedelta(days=10), expected_back=today - timedelta(days=3))
    done = ledger_jobs.job_work_out(accounts_user, shelf["ruby"], parties["karigar"], "2026/0418", None, D("5"))
    ledger_jobs.settle_job_work(accounts_user, done, shelf["ruby"], "in", None, D("5"))
    body = _get(client, accounts_user, "inventory:job_work_list").content.decode()
    assert "Job work out" in body and "Challan no." in body and "2026/0417" in body and KARIGAR in body
    assert "overdue" in body and "₹31,676" in body and "2026/0418" not in body       # 4 ct × ₹7,919 still out
    closed = _get(client, accounts_user, "inventory:job_work_list", "?closed=1").content.decode()
    assert "2026/0418" in closed and "Closed" in closed


def test_the_job_work_list_is_for_those_who_post_job_work(client, sales_user, production_user, shelf):
    assert _get(client, sales_user, "inventory:job_work_list").status_code == 403
    assert _get(client, production_user, "inventory:job_work_list").status_code == 200


def test_production_sees_karigars_but_no_value(client, admin_user_, production_user, shelf, parties):
    ledger_jobs.job_work_out(admin_user_, shelf["onyx"], parties["karigar"], "2026/0417", 6, D("4"))
    body = _get(client, production_user, "inventory:job_work_list").content.decode()
    assert KARIGAR in body and "31,676" not in body and "Value</th>" not in body


def test_memo_out_is_for_those_who_record_movements(client, accounts_user, karigar_user, shelf, parties):
    ledger_jobs.memo_out(accounts_user, shelf["ruby"], parties["customer"], "MEMO-0088", None, D("5"))
    body = _get(client, accounts_user, "inventory:memo_list").content.decode()
    assert "Memo out" in body and "Memo no." in body and "MEMO-0088" in body and CUSTOMER in body
    assert _get(client, karigar_user, "inventory:memo_list").status_code == 403


def test_recent_lists_documents_newest_first_and_filters_by_kind(client, accounts_user, shelf, parties):
    ledger_jobs.job_work_out(accounts_user, shelf["onyx"], parties["karigar"], "2026/0431", 1, D("1"))
    ledger_single.post_single(accounts_user, shelf["ruby"], Movement.Reason.BREAKAGE, None, D("1"))
    body = _get(client, accounts_user, "inventory:recent").content.decode()
    assert body.index("MOV-000001") < body.index("2026/0431")
    only = _get(client, accounts_user, "inventory:recent", "?kind=job_work").content.decode()
    assert "2026/0431" in only and "MOV-000001" not in only


def test_the_shelf_shows_what_is_out(client, accounts_user, sales_user, shelf, parties):
    ledger_jobs.job_work_out(accounts_user, shelf["onyx"], parties["karigar"], "2026/0431", 6, D("4"))
    body = _get(client, accounts_user, "inventory:shelf").content.decode()
    assert "Out on job work / memo" in body and "₹31,676" in body and "4.00 ct on 1 open document" in body
    body = _get(client, sales_user, "inventory:shelf").content.decode()
    assert "Out on job work / memo" in body and "4.00 ct on 1 open document" in body and "31,676" not in body


def test_the_rail_opens_the_ledger_screens_by_right(client, accounts_user, karigar_user, shelf):
    urls = {name: reverse(f"inventory:{name}") for name in ("purchase", "recent", "job_work_list", "memo_list")}
    body = _get(client, accounts_user, "inventory:shelf").content.decode()
    assert all(f'href="{url}"' in body for url in urls.values())
    assert 'Stock takes<span class="ct">🔒' in body and 'Transfers<span class="ct">🔒' in body
    body = _get(client, karigar_user, "inventory:shelf").content.decode()
    assert f'href="{urls["job_work_list"]}"' in body and f'href="{urls["recent"]}"' in body
    assert f'href="{urls["memo_list"]}"' not in body and f'href="{urls["purchase"]}"' not in body


def test_client_view_reaches_no_list(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    for name in ("inventory:job_work_list", "inventory:memo_list", "inventory:recent"):
        assert client.get(reverse(name)).status_code == 302, name


# --- deviation coverage: the brief's queries already exclude a reversal document from
# these lists (``reverses__isnull=True``) and a Reversed original is never shown as open,
# but nothing in the brief's own suite exercised that. Added per the orchestrator's note
# that earlier tasks' reversal semantics (a reversal is its own document, same kind,
# status Closed) must not leak a REV- document into Job work out / Memo out, and a
# Reversed original must not appear open.

def test_a_reversed_challan_never_shows_open_and_its_reversal_is_never_listed(client, accounts_user, shelf, parties):
    document = ledger_jobs.job_work_out(accounts_user, shelf["onyx"], parties["karigar"], "2026/0501", 6, D("4"))
    ledger.reverse_document(accounts_user, document)

    open_body = _get(client, accounts_user, "inventory:job_work_list").content.decode()
    assert "2026/0501" not in open_body

    closed_body = _get(client, accounts_user, "inventory:job_work_list", "?closed=1").content.decode()
    assert "2026/0501" in closed_body and "Reversed" in closed_body
    reversal_number = StockDocument.objects.get(reverses=document).number
    assert reversal_number.startswith("REV-")
    assert reversal_number not in closed_body
