from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import ledger_single, services
from inventory.models import Movement, Pouch, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
R, IN, OUT = Movement.Reason, Movement.IN, Movement.OUT


def _held(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()


@pytest.mark.parametrize("reason, direction, ct_after", [
    (R.SALE, OUT, "11.5"), (R.SALES_RETURN, IN, "13.5"), (R.PURCHASE_RETURN, OUT, "11.5"),
    (R.BREAKAGE, OUT, "11.5"), (R.WASTAGE, OUT, "11.5"), (R.SAMPLE, OUT, "11.5"), (R.CONSUMED, OUT, "11.5"),
])
def test_every_single_reason_posts_a_closed_document(accounts_user, shelf, parties, reason, direction, ct_after):
    doc = ledger_single.post_single(accounts_user, shelf["onyx"], reason, 1, D("1"), customer=parties["customer"],
                                    supplier=shelf["supplier"], ref="INV 2026/1188")
    move = doc.movements.get()
    assert (doc.kind, doc.status, doc.number) == (StockDocument.Kind.SINGLE, StockDocument.Status.CLOSED, "MOV-000001")
    assert (move.reason, move.direction, move.ref) == (reason, direction, "INV 2026/1188")
    assert _held(shelf["onyx"]).on_ct == D(ct_after)


def test_only_a_sale_or_return_names_a_customer_and_only_a_purchase_return_a_supplier(accounts_user, shelf, parties):
    both = {"customer": parties["customer"], "supplier": shelf["supplier"]}
    sale = ledger_single.post_single(accounts_user, shelf["onyx"], R.SALE, 1, D("1"), **both)
    assert sale.customer == parties["customer"] and sale.vendor is None
    back = ledger_single.post_single(accounts_user, shelf["onyx"], R.PURCHASE_RETURN, 1, D("1"), **both)
    assert back.vendor == shelf["supplier"] and back.customer is None
    broken = ledger_single.post_single(accounts_user, shelf["onyx"], R.BREAKAGE, 1, D("1"), **both)
    assert broken.vendor is None and broken.customer is None


def test_a_sale_needs_a_customer_and_a_purchase_return_a_supplier(accounts_user, shelf):
    with pytest.raises(ServiceError, match="Choose the customer"):
        ledger_single.post_single(accounts_user, shelf["onyx"], R.SALES_RETURN, None, D("1"))
    with pytest.raises(ServiceError, match="Choose the supplier"):
        ledger_single.post_single(accounts_user, shelf["onyx"], R.PURCHASE_RETURN, None, D("1"))


def test_job_work_is_not_posted_from_the_shelf(accounts_user, shelf):
    with pytest.raises(ServiceError, match="not posted from the shelf"):
        ledger_single.post_single(accounts_user, shelf["onyx"], R.JOB_WORK_OUT, 1, D("1"))


def test_a_recount_posts_the_differences_on_one_document(accounts_user, shelf):
    onyx = shelf["onyx"]
    doc = ledger_single.post_recount(accounts_user, onyx, 22, D("12"))
    pieces, weight = doc.movements.get(ct=None), doc.movements.get(pcs=None)
    assert (pieces.direction, pieces.pcs, weight.direction, weight.ct) == (IN, 2, OUT, D("0.5"))
    assert {pieces.reason, weight.reason} == {R.RECOUNT_ADJUSTMENT}
    assert (_held(onyx).on_pcs, _held(onyx).on_ct) == (22, D("12"))
    assert ledger_single.post_recount(accounts_user, onyx, 22, D("12")) is None


def test_an_uncountable_pouch_is_recounted_by_weight_only(accounts_user, shelf):
    with pytest.raises(ServiceError, match="uncountable"):
        ledger_single.post_recount(accounts_user, shelf["ruby"], 5, None)
    ledger_single.post_recount(accounts_user, shelf["ruby"], None, D("38"))
    assert _held(shelf["ruby"]).on_ct == D("38")


def test_a_count_must_be_given_and_not_negative(accounts_user, shelf):
    with pytest.raises(ServiceError, match="counted pieces or weight"):
        ledger_single.post_recount(accounts_user, shelf["onyx"], None, None)
    with pytest.raises(ServiceError, match="negative"):
        ledger_single.post_recount(accounts_user, shelf["onyx"], None, D("-1"))


def test_singles_need_the_movements_right(production_user, karigar_user, shelf, parties):
    for user in (production_user, karigar_user):
        with pytest.raises(PermissionDenied):
            ledger_single.post_single(user, shelf["onyx"], R.BREAKAGE, 1, D("1"))
        with pytest.raises(PermissionDenied):
            ledger_single.post_recount(user, shelf["onyx"], 19, None)


def test_the_importers_recount_is_unchanged(admin_user_, shelf):
    moves = services.recount(admin_user_, shelf["onyx"], 18, None)
    assert len(moves) == 1 and moves[0].document is None and moves[0].direction == OUT
