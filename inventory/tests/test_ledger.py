"""The ledger core: numbers, the one post and its checks, outstanding, reversal, undo — and the invariant."""
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from inventory import ledger, services
from inventory.ledger import Line
from inventory.models import Batch, Movement, Pouch, StockDocument
from inventory.tests.conftest import CUSTOMER, KARIGAR
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
K, S, R = StockDocument.Kind, StockDocument.Status, Movement.Reason
IN, OUT, SETTLE = Movement.IN, Movement.OUT, Movement.SETTLE


def _held(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()


def _job(user, parties, number="2026/0431"):
    return ledger.open_document(user, K.JOB_WORK, number, vendor=parties["karigar"])


def _memo(user, parties, number="MEMO-0088"):
    return ledger.open_document(user, K.MEMO, number, customer=parties["customer"])


def _single(user, pouch, reason, direction, ct, pcs=None):
    doc = ledger.open_document(user, K.SINGLE)
    ledger.post(user, doc, [Line(pouch, reason, direction, pcs, D(ct))])
    return doc


def test_automatic_numbers_count_up_per_prefix(admin_user_):
    kinds = (K.SPLIT, K.SPLIT, K.TRANSFER, K.SINGLE, K.PURCHASE)
    assert [ledger.open_document(admin_user_, kind).number for kind in kinds] == [
        "SPL-000001", "SPL-000002", "TRF-000001", "MOV-000001", "PUR-000001"]


def test_a_typed_number_is_free_per_kind_until_reversed(admin_user_, parties):
    first = _job(admin_user_, parties)
    with pytest.raises(ServiceError, match="already exists"):
        _job(admin_user_, parties)
    _memo(admin_user_, parties, "2026/0431")            # another kind may share it
    first.status = S.REVERSED
    first.save()
    assert _job(admin_user_, parties).number == "2026/0431"


@pytest.mark.parametrize("kind, words", [
    (K.JOB_WORK, "delivery challan no. is required"), (K.MEMO, "memo no. is required")])
def test_goods_leaving_without_a_sale_need_a_number(admin_user_, kind, words):
    with pytest.raises(ServiceError, match=words):
        ledger.open_document(admin_user_, kind, "  ")


def test_a_post_writes_every_movement_or_none(admin_user_, shelf):
    onyx = shelf["onyx"]
    doc = ledger.open_document(admin_user_, K.SINGLE)
    with pytest.raises(ServiceError, match="below zero"):
        ledger.post(admin_user_, doc, [Line(onyx, R.SALE, OUT, 2, D("1")), Line(onyx, R.BREAKAGE, OUT, 1, D("20"))])
    assert not doc.movements.exists() and _held(onyx).on_ct == D("12.5")


def test_an_empty_post_is_refused_so_it_cannot_silently_close_a_document(admin_user_):
    doc = ledger.open_document(admin_user_, K.SINGLE)
    with pytest.raises(ServiceError, match="Nothing to post"):
        ledger.post(admin_user_, doc, [])


def test_pieces_cannot_go_below_zero_either(admin_user_, shelf):
    with pytest.raises(ServiceError, match="below zero"):
        _single(admin_user_, shelf["onyx"], R.SALE, OUT, "1", pcs=21)


def test_an_uncountable_pouch_moves_by_weight_only(admin_user_, shelf):
    with pytest.raises(ServiceError, match="uncountable"):
        _single(admin_user_, shelf["ruby"], R.SALE, OUT, "1", pcs=1)
    _single(admin_user_, shelf["ruby"], R.SALE, OUT, "1")
    assert _held(shelf["ruby"]).on_ct == D("39")


@pytest.mark.parametrize("pcs, ct, words", [(None, "0", "above zero"), (None, "-1", "negative"), (-2, "1", "negative")])
def test_a_quantity_must_be_above_zero(admin_user_, shelf, pcs, ct, words):
    with pytest.raises(ServiceError, match=words):
        _single(admin_user_, shelf["onyx"], R.BREAKAGE, OUT, ct, pcs=pcs)


def test_a_single_closes_when_posted_and_takes_no_more(admin_user_, shelf):
    doc = _single(admin_user_, shelf["onyx"], R.SAMPLE, OUT, "1", pcs=1)
    assert doc.status == S.CLOSED
    with pytest.raises(ServiceError, match="takes no more entries"):
        ledger.post(admin_user_, doc, [Line(shelf["onyx"], R.SAMPLE, OUT, 1, D("1"))])


def test_job_work_stays_open_until_settled_then_closes_itself(admin_user_, shelf, parties):
    onyx = shelf["onyx"]
    doc = _job(admin_user_, parties)
    ledger.post(admin_user_, doc, [Line(onyx, R.JOB_WORK_OUT, OUT, 5, D("3"))])
    assert doc.status == S.OPEN and ledger.outstanding(doc) == {onyx.pk: (5, D("3"))}
    ledger.post(admin_user_, doc, [Line(onyx, R.JOB_WORK_IN, IN, 2, D("1"))])
    assert doc.status == S.OPEN
    ledger.post(admin_user_, doc, [Line(onyx, R.CONSUMED, SETTLE, 3, D("2"))])
    assert doc.status == S.CLOSED and ledger.outstanding(doc) == {onyx.pk: (0, D("0"))}
    held = _held(onyx)
    assert (held.on_pcs, held.on_ct) == (17, D("10.5"))       # the settle took nothing more off the shelf


def test_settling_cannot_exceed_what_is_outstanding(admin_user_, shelf, parties):
    doc = _job(admin_user_, parties)
    ledger.post(admin_user_, doc, [Line(shelf["onyx"], R.JOB_WORK_OUT, OUT, 2, D("3"))])
    with pytest.raises(ServiceError, match="cannot exceed what is outstanding"):
        ledger.post(admin_user_, doc, [Line(shelf["onyx"], R.JOB_WORK_IN, IN, 1, D("3.5"))])
    with pytest.raises(ServiceError, match="cannot exceed"):
        ledger.post(admin_user_, doc, [Line(shelf["ruby"], R.WASTAGE, SETTLE, None, D("1"))])    # never sent out


def test_reversing_puts_everything_back_on_a_new_document(admin_user_, shelf):
    onyx = shelf["onyx"]
    doc = _single(admin_user_, onyx, R.SALE, OUT, "2", pcs=4)
    reversal = ledger.reverse_document(admin_user_, doc)
    doc.refresh_from_db()
    assert doc.status == S.REVERSED and reversal.reverses == doc and reversal.status == S.CLOSED
    assert (reversal.number, reversal.kind) == ("REV-000001", K.SINGLE)
    assert (_held(onyx).on_pcs, _held(onyx).on_ct) == (20, D("12.5"))
    with pytest.raises(ServiceError, match="already reversed"):
        ledger.reverse_document(admin_user_, doc)
    with pytest.raises(ServiceError, match="itself a reversal"):
        ledger.reverse_document(admin_user_, reversal)


def test_a_reversal_that_would_go_below_zero_is_refused(admin_user_, shelf):
    onyx = shelf["onyx"]
    back = _single(admin_user_, onyx, R.SALES_RETURN, IN, "5")
    _single(admin_user_, onyx, R.SALE, OUT, "17")
    with pytest.raises(ServiceError, match="below zero"):
        ledger.reverse_document(admin_user_, back)
    back.refresh_from_db()
    assert back.status == S.CLOSED and not StockDocument.objects.filter(reverses=back).exists()


def test_reversing_needs_the_right_for_its_kind(admin_user_, karigar_user, shelf):
    doc = _single(admin_user_, shelf["onyx"], R.BREAKAGE, OUT, "1")
    with pytest.raises(PermissionDenied):
        ledger.reverse_document(karigar_user, doc)


def test_a_created_pouch_that_moved_since_blocks_the_reversal(admin_user_, shelf):
    doc = ledger.open_document(admin_user_, K.PURCHASE, "B-1")
    fresh = ledger.new_pouch(shelf["batch"], pouch_no="9", stone_name="Tanzanite")
    ledger.post(admin_user_, doc, [Line(fresh, R.PURCHASE, IN, 6, D("10"))])
    _single(admin_user_, fresh, R.SALE, OUT, "1", pcs=1)
    with pytest.raises(ServiceError, match="has moved since"):
        ledger.reverse_document(admin_user_, doc)


def test_reversing_the_later_movement_first_unblocks_the_creating_documents_reversal(admin_user_, shelf):
    doc = ledger.open_document(admin_user_, K.PURCHASE, "B-9")
    fresh = ledger.new_pouch(shelf["batch"], pouch_no="9", stone_name="Tanzanite")
    ledger.post(admin_user_, doc, [Line(fresh, R.PURCHASE, IN, 6, D("10"))])
    sale = _single(admin_user_, fresh, R.SALE, OUT, "1", pcs=1)
    ledger.reverse_document(admin_user_, sale)
    reversal = ledger.reverse_document(admin_user_, doc)
    held = _held(fresh)
    assert reversal.reverses == doc and (held.on_pcs, held.on_ct) == (0, D("0"))


def test_a_reversed_purchase_leaves_its_pouch_at_zero(admin_user_, shelf):
    doc = ledger.open_document(admin_user_, K.PURCHASE, "B-2")
    fresh = ledger.new_pouch(shelf["batch"], pouch_no="9")
    ledger.post(admin_user_, doc, [Line(fresh, R.PURCHASE, IN, 6, D("10"))])
    ledger.reverse_document(admin_user_, doc)
    held = _held(fresh)
    assert Pouch.objects.filter(pk=fresh.pk).exists() and (held.on_pcs, held.on_ct) == (0, D("0"))


def test_undo_reverses_only_the_latest_entry(admin_user_, shelf, parties):
    onyx = shelf["onyx"]
    doc = _job(admin_user_, parties)
    ledger.post(admin_user_, doc, [Line(onyx, R.JOB_WORK_OUT, OUT, 4, D("3"))])
    ledger.post(admin_user_, doc, [Line(onyx, R.JOB_WORK_IN, IN, 1, D("1"))])
    undone = ledger.undo_last(admin_user_, doc)
    assert undone.reverses.reason == R.JOB_WORK_IN and undone.document == doc
    assert ledger.outstanding(doc)[onyx.pk] == (4, D("3")) and _held(onyx).on_ct == D("9.5")
    doc.refresh_from_db()
    assert doc.status == S.OPEN


def test_undo_is_only_for_an_open_or_closed_job_work_or_memo(admin_user_, shelf):
    doc = _single(admin_user_, shelf["onyx"], R.BREAKAGE, OUT, "1")
    with pytest.raises(ServiceError, match="Only an open or closed job work or memo"):
        ledger.undo_last(admin_user_, doc)


def test_undo_reopens_a_document_its_own_settlement_had_closed(admin_user_, shelf, parties):
    """Owner, 2026-10-01: undo works on a challan or memo its settlements closed, not only an open one."""
    onyx = shelf["onyx"]
    doc = _job(admin_user_, parties)
    ledger.post(admin_user_, doc, [Line(onyx, R.JOB_WORK_OUT, OUT, 5, D("3"))])
    ledger.post(admin_user_, doc, [Line(onyx, R.CONSUMED, SETTLE, 5, D("3"))])
    assert doc.status == S.CLOSED and ledger.outstanding(doc)[onyx.pk] == (0, D("0"))
    undone = ledger.undo_last(admin_user_, doc)
    assert undone.reverses.reason == R.CONSUMED
    doc.refresh_from_db()
    assert doc.status == S.OPEN and ledger.outstanding(doc)[onyx.pk] == (5, D("3"))


def test_undo_refuses_a_reversed_document(admin_user_, shelf, parties):
    onyx = shelf["onyx"]
    doc = _job(admin_user_, parties)
    ledger.post(admin_user_, doc, [Line(onyx, R.JOB_WORK_OUT, OUT, 5, D("3"))])
    ledger.post(admin_user_, doc, [Line(onyx, R.CONSUMED, SETTLE, 5, D("3"))])
    ledger.reverse_document(admin_user_, doc)
    doc.refresh_from_db()
    assert doc.status == S.REVERSED
    with pytest.raises(ServiceError, match="Only an open or closed job work or memo"):
        ledger.undo_last(admin_user_, doc)


def test_reversing_a_transfer_files_the_pouch_back(admin_user_, shelf):
    onyx, home = shelf["onyx"], shelf["batch"]
    other = Batch.objects.create(code="SP14B", box_colour_id="B", family="S", cls="P", seq="14")
    doc = ledger.open_document(admin_user_, K.TRANSFER, from_batch=home, from_pouch_no="1",
                               to_batch=other, to_pouch_no="3")
    ledger.post(admin_user_, doc, [Line(onyx, R.TRANSFER, SETTLE, 20, D("12.5"))])
    onyx.batch, onyx.pouch_no = other, "3"
    onyx.save()
    assert _held(onyx).on_ct == D("12.5")
    ledger.reverse_document(admin_user_, doc)
    onyx.refresh_from_db()
    assert (onyx.batch_id, onyx.pouch_no) == (home.pk, "1") and _held(onyx).on_ct == D("12.5")


def test_pouch_numbers_and_references(shelf):
    batch = shelf["batch"]
    assert ledger.next_pouch_no(batch) == "3" and ledger.next_pouch_numbers()["SL01G"] == 3
    assert not ledger.pouch_no_free(batch, "2") and ledger.pouch_no_free(batch, "3")
    assert ledger.new_pouch(batch, pouch_no="3").ref == "NRN-000003"


def test_the_counterparty_comes_under_the_key_that_masks_it(admin_user_, shelf, parties):
    assert ledger.party(_job(admin_user_, parties)) == {"karigar_name": KARIGAR}
    assert ledger.party(_memo(admin_user_, parties)) == {"customer_name": CUSTOMER}
    bought = ledger.open_document(admin_user_, K.PURCHASE, vendor=shelf["supplier"])
    assert ledger.party(bought) == {"vendor_name": shelf["supplier"].name}
    assert ledger.party(None) == {}


def test_what_is_out_is_valued_at_each_pouchs_rate(admin_user_, shelf, parties):
    job = _job(admin_user_, parties)
    ledger.post(admin_user_, job, [Line(shelf["onyx"], R.JOB_WORK_OUT, OUT, 2, D("2"))])
    memo = _memo(admin_user_, parties)
    ledger.post(admin_user_, memo, [Line(shelf["ruby"], R.MEMO_OUT, OUT, None, D("4"))])
    assert ledger.out_summary() == {"ct": D("6"), "value": D("16038"), "documents": 2}     # 2 × 7,919 + 4 × 50


def test_on_shelf_plus_out_is_what_came_in_less_what_left_for_good(admin_user_, shelf, parties):
    """The ledger invariant, through every kind of post, an undo and a reversal."""
    onyx, ruby = shelf["onyx"], shelf["ruby"]

    def owned():
        return sum(p.on_ct or 0 for p in services.stocked()) + ledger.out_summary()["ct"]

    opening = D("52.5")
    assert owned() == opening
    job = _job(admin_user_, parties)
    ledger.post(admin_user_, job, [Line(onyx, R.JOB_WORK_OUT, OUT, 6, D("4"))])
    ledger.post(admin_user_, job, [Line(onyx, R.JOB_WORK_IN, IN, 1, D("1"))])
    ledger.post(admin_user_, job, [Line(onyx, R.CONSUMED, SETTLE, 2, D("1"))])            # left for good: 1
    memo = _memo(admin_user_, parties)
    ledger.post(admin_user_, memo, [Line(ruby, R.MEMO_OUT, OUT, None, D("10"))])
    ledger.post(admin_user_, memo, [Line(ruby, R.MEMO_IN, IN, None, D("3"))])
    ledger.post(admin_user_, memo, [Line(ruby, R.SALE, SETTLE, None, D("2"))])              # sold …
    ledger.undo_last(admin_user_, memo)                                                       # … then undone
    _single(admin_user_, onyx, R.SALE, OUT, "1", pcs=1)                                       # left for good: 1
    _single(admin_user_, onyx, R.SALES_RETURN, IN, "0.5")                                     # came back: 0.5
    bought = ledger.open_document(admin_user_, K.PURCHASE, "B-3")
    fresh = ledger.new_pouch(shelf["batch"], pouch_no="9")
    ledger.post(admin_user_, bought, [Line(fresh, R.PURCHASE, IN, 6, D("10"))])            # came in: 10
    broken = _single(admin_user_, ruby, R.BREAKAGE, OUT, "1")
    ledger.reverse_document(admin_user_, broken)                                              # nets to nothing
    assert owned() == opening + D("10") + D("0.5") - D("1") - D("1")
    assert ledger.out_summary()["ct"] == D("2") + D("7")


def test_the_ledger_screens_have_their_names():
    for name, args in [("inventory:purchase", []), ("inventory:job_work_list", []), ("inventory:memo_list", []),
                       ("inventory:recent", []), ("inventory:document", [1]), ("inventory:document_settle", [1]),
                       ("inventory:document_undo", [1]), ("inventory:document_reverse", [1]),
                       ("inventory:split", ["NRN-000001"]), ("inventory:transfer", ["NRN-000001"]),
                       ("inventory:movement_post", ["NRN-000001"]), ("inventory:movements", ["NRN-000001"])]:
        assert reverse(name, args=args)
