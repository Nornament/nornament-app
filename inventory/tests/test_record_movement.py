from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import ledger_jobs, services
from inventory.models import Movement, StockDocument
from inventory.tests.conftest import KARIGAR, SUPPLIER

pytestmark = pytest.mark.django_db
D = Decimal
ALL = ["Job Work Out", "Job Work In", "Sale", "Sales Return", "Memo Out", "Memo In", "Purchase",
       "Consumed in Production", "Wastage / Loss in Process", "Breakage", "Transfer to another batch",
       "Recount Adjustment", "Purchase Return", "Sample"]
JOB = ["Job Work Out", "Job Work In", "Consumed in Production", "Wastage / Loss in Process"]


def _body(client, user, pouch):
    client.force_login(user)
    return client.get(reverse("inventory:movements", args=[pouch.ref])).content.decode()


def _offered(body):
    return [reason for reason in ALL if f'value="{reason}" data-word' in body]


def _post(client, user, pouch, data, **extra):
    client.force_login(user)
    return client.post(reverse("inventory:movement_post", args=[pouch.ref]), data, **extra)


def test_the_form_offers_only_what_the_viewer_may_post(
    client, shelf, admin_user_, accounts_user, karigar_user, production_user, sales_user
):
    assert _offered(_body(client, admin_user_, shelf["onyx"])) == ALL
    assert _offered(_body(client, accounts_user, shelf["onyx"])) == ALL
    assert _offered(_body(client, karigar_user, shelf["onyx"])) == JOB
    assert _offered(_body(client, production_user, shelf["onyx"])) == JOB
    body = _body(client, sales_user, shelf["onyx"])
    assert _offered(body) == [] and "Post movement" not in body


def test_the_card_carries_the_prototypes_fields_and_checks(client, admin_user_, shelf):
    onyx = shelf["onyx"]
    body = _body(client, admin_user_, onyx)
    for text in ('Pieces <span class="qword">out</span>', "Karigar", "Delivery challan no.", "Expected back",
                 "Checks that will run", "<code>challan_no</code> present", "Out on Job Work",
                 "<code>20 − out pcs ≥ 0</code>", "Post movement", "⤴ Split", "⇄ Transfer to another batch"):
        assert text in body, text
    for url in (reverse("inventory:purchase"), reverse("inventory:split", args=[onyx.ref]),
                reverse("inventory:transfer", args=[onyx.ref])):
        assert url in body, url
    assert "🔒" not in body.split('id="record"')[1].split("</form>")[0]


def test_job_work_out_posts_and_the_ledger_links_its_challan(client, admin_user_, shelf, parties):
    onyx = shelf["onyx"]
    response = _post(client, admin_user_, onyx, {
        "reason": "Job Work Out", "pcs": "6", "ct": "4", "karigar": parties["karigar"].pk,
        "challan_no": "2026/0431", "occurred_on": "2026-10-01", "expected_back": "2026-10-08"})
    assert response.status_code == 302
    doc = StockDocument.objects.get(number="2026/0431")
    body = _body(client, admin_user_, onyx)
    assert KARIGAR in body and reverse("inventory:document", args=[doc.pk]) in body and "8.50 ct" in body


def test_a_refusal_comes_back_on_the_form_with_what_was_typed(client, admin_user_, shelf, parties):
    response = _post(client, admin_user_, shelf["onyx"], {
        "reason": "Job Work Out", "pcs": "6", "ct": "4.25", "karigar": parties["karigar"].pk, "challan_no": ""})
    body = response.content.decode()
    assert response.status_code == 200 and "challan no. is required" in body
    assert 'value="4.25"' in body and 'value="Job Work Out" data-word="out" selected' in body
    assert not Movement.objects.filter(reason="Job Work Out").exists()


def test_too_much_out_is_refused_in_plain_words(client, admin_user_, shelf, parties):
    response = _post(client, admin_user_, shelf["onyx"], {"reason": "Sale", "ct": "99", "customer": "C-881"})
    assert "Not enough in SL01G · 1" in response.content.decode()


def test_a_reason_the_viewer_may_not_post_is_a_403(client, karigar_user, shelf):
    assert _post(client, karigar_user, shelf["onyx"], {"reason": "Sale", "ct": "1"}).status_code == 403


def test_a_sale_against_a_memo_settles_it(client, accounts_user, shelf, parties):
    ruby = shelf["ruby"]
    memo = ledger_jobs.memo_out(accounts_user, ruby, parties["customer"], "MEMO-0088", None, D("5"))
    _post(client, accounts_user, ruby, {"reason": "Sale", "ct": "5", "memo": memo.pk})
    memo.refresh_from_db()
    assert memo.status == StockDocument.Status.CLOSED and services.stocked().get(pk=ruby.pk).on_ct == D("35")


def test_consumed_settles_a_challan_when_one_is_chosen_and_else_leaves_the_shelf(client, accounts_user, shelf, parties):
    onyx = shelf["onyx"]
    job = ledger_jobs.job_work_out(accounts_user, onyx, parties["karigar"], "2026/0431", 4, D("3"))
    _post(client, accounts_user, onyx, {"reason": "Consumed in Production", "pcs": "4", "ct": "3", "challan": job.pk})
    job.refresh_from_db()
    assert job.status == StockDocument.Status.CLOSED and services.stocked().get(pk=onyx.pk).on_ct == D("9.5")
    _post(client, accounts_user, onyx, {"reason": "Consumed in Production", "pcs": "1", "ct": "1", "challan": ""})
    assert services.stocked().get(pk=onyx.pk).on_ct == D("8.5")


def test_a_recount_from_the_form_posts_the_difference(client, accounts_user, shelf):
    onyx = shelf["onyx"]
    _post(client, accounts_user, onyx, {"reason": "Recount Adjustment", "pcs": "18", "ct": "12.5"})
    assert services.stocked().get(pk=onyx.pk).on_pcs == 18
    response = _post(client, accounts_user, onyx, {"reason": "Recount Adjustment", "pcs": "18", "ct": "12.5"}, follow=True)
    assert "nothing was posted" in response.content.decode()


def test_the_karigar_desk_is_offered_only_karigars_it_has_used(client, admin_user_, karigar_user, shelf, parties):
    body = _body(client, karigar_user, shelf["ruby"])
    assert SUPPLIER not in body and KARIGAR not in body
    ledger_jobs.job_work_out(admin_user_, shelf["onyx"], parties["karigar"], "2026/0431", 1, D("1"))
    body = _body(client, karigar_user, shelf["ruby"])
    assert KARIGAR in body and SUPPLIER not in body


def test_client_view_reaches_neither_the_page_nor_the_post(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    assert client.get(reverse("inventory:movements", args=[shelf["onyx"].ref])).status_code == 302
    assert client.post(reverse("inventory:movement_post", args=[shelf["onyx"].ref]), {"reason": "Sale"}).status_code == 302
    assert not Movement.objects.filter(reason="Sale").exists()
