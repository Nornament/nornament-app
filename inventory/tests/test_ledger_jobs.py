from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import ledger, ledger_jobs, services
from inventory.models import Movement, Pouch, StockDocument
from inventory.tests.conftest import CUSTOMER, KARIGAR, SUPPLIER
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
S = StockDocument.Status


def _ct(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get().on_ct


def _out(user, shelf, parties, **changes):
    args = {"pouch": shelf["onyx"], "karigar": parties["karigar"], "challan_no": "2026/0431", "pcs": 6, "ct": D("4")}
    return ledger_jobs.job_work_out(user, **(args | changes))


def test_out_partly_back_consumed_and_lost_closes_at_zero(admin_user_, shelf, parties):
    onyx = shelf["onyx"]
    doc = _out(admin_user_, shelf, parties, occurred_on=date(2026, 10, 1), expected_back=date(2026, 10, 8))
    assert (doc.kind, doc.number, doc.status) == (StockDocument.Kind.JOB_WORK, "2026/0431", S.OPEN)
    assert doc.vendor == parties["karigar"] and doc.expected_back == date(2026, 10, 8)
    assert _ct(onyx) == D("8.5")
    ledger_jobs.settle_job_work(admin_user_, doc, onyx, "in", 2, D("1"))
    ledger_jobs.settle_job_work(admin_user_, doc, onyx, "consumed", 3, D("2.5"))
    doc.refresh_from_db()
    assert doc.status == S.OPEN                     # 1 pc and 0.5 ct still out: it cannot close early
    lost = ledger_jobs.settle_job_work(admin_user_, doc, onyx, "loss", 1, D("0.5"))
    doc.refresh_from_db()
    assert (lost.reason, lost.direction) == (Movement.Reason.WASTAGE, Movement.SETTLE)
    assert doc.status == S.CLOSED and _ct(onyx) == D("9.5")


def test_a_challan_can_take_more_pouches(admin_user_, shelf, parties):
    doc = _out(admin_user_, shelf, parties)
    again = _out(admin_user_, shelf, parties, pouch=shelf["ruby"], pcs=None, ct=D("5"))
    assert again == doc and set(ledger.outstanding(doc)) == {shelf["onyx"].pk, shelf["ruby"].pk}


def test_an_open_challan_belongs_to_one_karigar(admin_user_, shelf, parties):
    _out(admin_user_, shelf, parties)
    with pytest.raises(ServiceError, match="open with someone else"):
        _out(admin_user_, shelf, parties, karigar=shelf["supplier"])


def test_goods_out_need_a_challan_and_a_karigar(admin_user_, shelf, parties):
    with pytest.raises(ServiceError, match="challan no. is required"):
        _out(admin_user_, shelf, parties, challan_no=" ")
    with pytest.raises(ServiceError, match="Choose the karigar"):
        _out(admin_user_, shelf, parties, karigar=None)


def test_expected_back_cannot_come_before_the_date(admin_user_, shelf, parties):
    with pytest.raises(ServiceError, match="Expected back cannot be before"):
        _out(admin_user_, shelf, parties, occurred_on=date(2026, 10, 8), expected_back=date(2026, 10, 1))


def test_settling_is_capped_at_what_is_out(admin_user_, shelf, parties):
    doc = _out(admin_user_, shelf, parties)
    with pytest.raises(ServiceError, match="cannot exceed"):
        ledger_jobs.settle_job_work(admin_user_, doc, shelf["onyx"], "in", 7, D("1"))


def test_a_closed_challan_takes_nothing_more_and_keeps_its_number(admin_user_, shelf, parties):
    doc = _out(admin_user_, shelf, parties)
    ledger_jobs.settle_job_work(admin_user_, doc, shelf["onyx"], "in", 6, D("4"))
    doc.refresh_from_db()
    assert doc.status == S.CLOSED
    with pytest.raises(ServiceError, match="takes no more entries"):
        ledger_jobs.settle_job_work(admin_user_, doc, shelf["onyx"], "loss", None, D("0.1"))
    with pytest.raises(ServiceError, match="already exists"):
        _out(admin_user_, shelf, parties)


def test_memo_out_returned_then_sold(admin_user_, shelf, parties):
    ruby = shelf["ruby"]
    doc = ledger_jobs.memo_out(admin_user_, ruby, parties["customer"], "MEMO-0088", None, D("10"),
                               expected_back=date(2026, 12, 1))
    assert doc.customer == parties["customer"] and doc.kind == StockDocument.Kind.MEMO and _ct(ruby) == D("30")
    ledger_jobs.settle_memo(admin_user_, doc, ruby, "in", None, D("6"))
    sold = ledger_jobs.settle_memo(admin_user_, doc, ruby, "sold", None, D("4"))
    doc.refresh_from_db()
    assert (sold.reason, sold.direction) == (Movement.Reason.SALE, Movement.SETTLE)
    assert doc.status == S.CLOSED and _ct(ruby) == D("36")


def test_a_memo_needs_a_customer_and_a_number(admin_user_, shelf, parties):
    with pytest.raises(ServiceError, match="Choose the customer"):
        ledger_jobs.memo_out(admin_user_, shelf["ruby"], None, "MEMO-0088", None, D("1"))
    with pytest.raises(ServiceError, match="memo no. is required"):
        ledger_jobs.memo_out(admin_user_, shelf["ruby"], parties["customer"], "", None, D("1"))


def test_settling_the_wrong_way_or_the_wrong_kind_is_refused(admin_user_, shelf, parties):
    doc = _out(admin_user_, shelf, parties)
    with pytest.raises(ServiceError, match="Unknown way"):
        ledger_jobs.settle_job_work(admin_user_, doc, shelf["onyx"], "sold", 1, D("1"))
    with pytest.raises(ServiceError, match="not a memo"):
        ledger_jobs.settle_memo(admin_user_, doc, shelf["onyx"], "in", 1, D("1"))


def test_who_may_post_what(karigar_user, production_user, sales_user, shelf, parties):
    doc = _out(karigar_user, shelf, parties)                        # the Karigar desk posts job work
    ledger_jobs.settle_job_work(production_user, doc, shelf["onyx"], "in", 1, D("1"))
    with pytest.raises(PermissionDenied):
        ledger_jobs.memo_out(karigar_user, shelf["ruby"], parties["customer"], "MEMO-1", None, D("1"))
    with pytest.raises(PermissionDenied):
        _out(sales_user, shelf, parties, challan_no="2026/0500")


def test_karigar_choices_follow_what_the_login_may_see(admin_user_, karigar_user, production_user, shelf, parties):
    def names(user):
        return [choice.get("karigar_name") for choice in ledger_jobs.karigar_choices(user)]

    assert SUPPLIER in names(production_user) and KARIGAR in names(production_user)
    assert names(karigar_user) == []            # no challan yet, and suppliers are not theirs to see
    _out(admin_user_, shelf, parties)
    assert names(karigar_user) == [KARIGAR]


def test_customer_choices_are_named_only_for_those_who_see_sales(accounts_user, production_user, parties):
    assert ledger_jobs.customer_choices(accounts_user) == [{"code": "C-881", "customer_name": CUSTOMER}]
    assert ledger_jobs.customer_choices(production_user) == [{"code": "C-881"}]
