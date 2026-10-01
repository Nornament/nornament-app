from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import ledger_jobs, services
from inventory.models import Movement, StockDocument
from inventory.tests.conftest import KARIGAR, SUPPLIER
from stock.models import Vendor

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


@pytest.mark.parametrize("data", [
    {"reason": "Job Work Out", "challan_no": "C" * 41, "karigar": "{karigar}"},
    {"reason": "Memo Out", "memo_no": "M" * 41, "customer": "C-881"},
    {"reason": "Sale", "ref": "I" * 41, "customer": "C-881"},
])
def test_an_over_long_number_is_refused_on_the_form(client, admin_user_, shelf, parties, data):
    data = {**data, "pcs": "1", "ct": "1"}
    if data.get("karigar"):
        data["karigar"] = parties["karigar"].pk
    response = _post(client, admin_user_, shelf["onyx"], data)
    assert response.status_code == 200 and "at most 40 characters" in response.content.decode()
    assert not Movement.objects.filter(document__isnull=False).exists()


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


def _new_karigar(**changes):
    return {"reason": "Job Work Out", "karigar": "new", "new_code": "rmk", "new_name": "Ramesh Karigar",
            "challan_no": "2026/0500", "pcs": "1", "ct": "1", **changes}


def test_settings_and_supplier_sight_may_add_a_karigar_with_the_challan(client, admin_user_, shelf):
    assert "＋ New karigar…" in _body(client, admin_user_, shelf["onyx"])
    response = _post(client, admin_user_, shelf["onyx"], _new_karigar())
    assert response.status_code == 302
    assert StockDocument.objects.get(number="2026/0500").vendor == Vendor.objects.get(code="RMK", name="Ramesh Karigar")


def test_a_refused_challan_creates_no_karigar(client, admin_user_, shelf):
    response = _post(client, admin_user_, shelf["onyx"], _new_karigar(ct="99"))
    assert response.status_code == 200 and "Not enough in" in response.content.decode()
    assert not Vendor.objects.filter(code="RMK").exists()


def test_only_settings_and_supplier_sight_are_offered_a_new_karigar(client, karigar_user, production_user, shelf):
    assert "＋ New karigar" not in _body(client, karigar_user, shelf["onyx"])
    assert "＋ New karigar" not in _body(client, production_user, shelf["onyx"])        # suppliers, but no settings


def test_client_view_reaches_neither_the_page_nor_the_post(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    assert client.get(reverse("inventory:movements", args=[shelf["onyx"].ref])).status_code == 302
    assert client.post(reverse("inventory:movement_post", args=[shelf["onyx"].ref]), {"reason": "Sale"}).status_code == 302
    assert not Movement.objects.filter(reason="Sale").exists()


def test_the_shelf_default_is_hidden_from_a_login_without_inv_move(client, karigar_user, shelf):
    """The Karigar desk (inv_job only) may only settle Consumed/Wastage against a challan; it
    must never be offered the direct-from-the-shelf option it is not allowed to post."""
    assert "— from the shelf —" not in _body(client, karigar_user, shelf["onyx"])


def test_job_work_in_is_never_offered_the_shelf(client, admin_user_, shelf):
    import re

    body = _body(client, admin_user_, shelf["onyx"])
    blocks = dict(re.findall(r'data-for="([^"]*)"><label>Open challan</label>(.*?)</select>', body, re.S))
    assert "— from the shelf —" not in blocks["Job Work In"]
    assert "— from the shelf —" in blocks["Consumed in Production|Wastage / Loss in Process"]


def test_consumed_without_a_challan_is_refused_on_the_form_not_a_403(client, karigar_user, shelf):
    """The Karigar desk has inv_job but not inv_move: posting Consumed with no challan chosen
    used to fall through to the inv_move-gated shelf path and come back as a bare 403, losing
    what was typed. It must be a plain refusal on the form instead."""
    response = _post(client, karigar_user, shelf["onyx"], {"reason": "Consumed in Production", "pcs": "1", "ct": "1"})
    assert response.status_code == 200
    assert "Choose the open challan to settle against." in response.content.decode()
    assert not Movement.objects.filter(reason="Consumed in Production").exists()


def test_the_karigar_desk_settles_consumed_against_its_own_challan(client, admin_user_, karigar_user, shelf, parties):
    onyx = shelf["onyx"]
    job = ledger_jobs.job_work_out(admin_user_, onyx, parties["karigar"], "2026/0431", 4, D("3"))
    response = _post(client, karigar_user, onyx,
                     {"reason": "Consumed in Production", "pcs": "4", "ct": "3", "challan": job.pk})
    assert response.status_code == 302
    job.refresh_from_db()
    assert job.status == StockDocument.Status.CLOSED
    assert services.stocked().get(pk=onyx.pk).on_ct == D("9.5")


def test_reasons_off_the_card_are_a_403_and_nothing_is_written(client, admin_user_, shelf):
    before = Movement.objects.count()
    for reason in ("Opening Balance", "Split", "Merge"):
        assert _post(client, admin_user_, shelf["onyx"], {"reason": reason, "ct": "1"}).status_code == 403
    assert Movement.objects.count() == before


def test_a_hand_built_purchase_or_transfer_post_is_refused_with_nothing_written(client, admin_user_, shelf):
    before = Movement.objects.count()
    for reason in ("Purchase", "Transfer to another batch"):
        response = _post(client, admin_user_, shelf["onyx"], {"reason": reason, "ct": "1"})
        assert response.status_code == 200
        assert "not posted from the shelf" in response.content.decode()
    assert Movement.objects.count() == before
