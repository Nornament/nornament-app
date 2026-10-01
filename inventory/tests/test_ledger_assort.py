from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import ledger, ledger_assort, services
from inventory.ledger_assort import SplitPart
from inventory.models import Batch, Movement, Pouch, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
R = Movement.Reason


def _held(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()


def _other():
    return Batch.objects.create(code="SP14B", box_colour_id="B", family="S", cls="P", seq="14")


def _split(user, shelf, **changes):
    args = {"source": shelf["onyx"], "out_pcs": 10, "out_ct": D("6"), "loss_pcs": 1, "loss_ct": D("0.5"),
            "parts": [SplitPart("3", 6, D("3.5"), size_text="10*8", remarks="the larger ones"), SplitPart("4", 3, D("2"))]}
    return ledger_assort.split_pouch(user, **(args | changes))


def test_a_split_balances_and_carries_the_parent_across(accounts_user, shelf):
    onyx, batch = shelf["onyx"], shelf["batch"]
    doc = _split(accounts_user, shelf)
    assert (doc.kind, doc.number, doc.status) == (StockDocument.Kind.SPLIT, "SPL-000001", StockDocument.Status.CLOSED)
    three = Pouch.objects.get(batch=batch, pouch_no="3")
    assert three.parent == onyx and (three.size_text, three.remarks) == ("10*8", "the larger ones")
    assert (three.stone_name, three.shape, three.carton, three.supplier, three.countable) == (
        "Green Onyx", "Oval", "C-117", shelf["supplier"], True)
    held = _held(three)
    assert (held.on_pcs, held.on_ct, held.rate) == (6, D("3.5"), D("7919"))       # the parent's valuation rate
    assert (_held(onyx).on_pcs, _held(onyx).on_ct) == (10, D("6.5"))
    out = doc.movements.get(pouch=onyx, reason=R.SPLIT)
    assert (out.direction, out.pcs, out.ct) == (Movement.OUT, 9, D("5.5"))
    loss = doc.movements.get(pouch=onyx, reason=R.WASTAGE)
    assert (loss.direction, loss.pcs, loss.ct) == (Movement.OUT, 1, D("0.5"))
    assert doc.movements.filter(reason=R.SPLIT, direction=Movement.IN).count() == 2


def test_an_unbalanced_split_is_refused(accounts_user, shelf):
    with pytest.raises(ServiceError, match="0.5 ct unaccounted"):
        _split(accounts_user, shelf, loss_ct=None)
    with pytest.raises(ServiceError, match="1 pcs unaccounted"):
        _split(accounts_user, shelf, loss_pcs=None)
    assert not StockDocument.objects.exists()


def test_a_real_shortfall_is_never_rounded_to_zero(accounts_user, shelf):
    with pytest.raises(ServiceError, match="0.0001 ct unaccounted"):
        _split(accounts_user, shelf, loss_ct=D("0.4999"))


def test_a_split_cannot_take_more_than_the_pouch_holds(accounts_user, shelf):
    with pytest.raises(ServiceError, match="below zero"):
        _split(accounts_user, shelf, out_pcs=6, out_ct=D("13"), loss_pcs=None, loss_ct=None,
               parts=[SplitPart("3", 6, D("13"))])


def test_new_pouch_numbers_must_be_free(accounts_user, shelf):
    with pytest.raises(ServiceError, match="taken"):
        _split(accounts_user, shelf, parts=[SplitPart("2", 6, D("3.5")), SplitPart("4", 3, D("2"))])
    with pytest.raises(ServiceError, match="taken"):
        _split(accounts_user, shelf, parts=[SplitPart("3", 6, D("3.5")), SplitPart("3", 3, D("2"))])


def test_an_uncountable_pouch_splits_by_weight(accounts_user, shelf):
    ruby = shelf["ruby"]
    ledger_assort.split_pouch(accounts_user, ruby, None, D("40"), [SplitPart("3", None, D("25")), SplitPart("4", None, D("15"))])
    assert _held(ruby).on_ct == D("0") and not Pouch.objects.get(batch=shelf["batch"], pouch_no="3").countable
    with pytest.raises(ServiceError, match="Enter the weight"):
        ledger_assort.split_pouch(accounts_user, ruby, None, None, [SplitPart("5", None, D("1"))])


def test_reversing_a_split_restores_the_parent_and_leaves_the_new_pouches_at_zero(accounts_user, shelf):
    doc = _split(accounts_user, shelf)
    ledger.reverse_document(accounts_user, doc)
    assert (_held(shelf["onyx"]).on_pcs, _held(shelf["onyx"]).on_ct) == (20, D("12.5"))
    assert _held(Pouch.objects.get(batch=shelf["batch"], pouch_no="3")).on_ct == D("0")


def test_a_split_whose_new_pouch_has_moved_is_not_reversed(accounts_user, shelf):
    doc = _split(accounts_user, shelf)
    three = Pouch.objects.get(batch=shelf["batch"], pouch_no="3")
    sale = ledger.open_document(accounts_user, StockDocument.Kind.SINGLE)
    ledger.post(accounts_user, sale, [ledger.Line(three, R.SALE, Movement.OUT, 1, D("0.5"))])
    with pytest.raises(ServiceError, match="moved since"):
        ledger.reverse_document(accounts_user, doc)


def test_a_transfer_re_files_the_whole_pouch(accounts_user, shelf):
    onyx, other = shelf["onyx"], _other()
    doc = ledger_assort.transfer_pouch(accounts_user, onyx, other, "1", note="re-sorted")
    onyx.refresh_from_db()
    assert (onyx.batch, onyx.pouch_no, onyx.ref) == (other, "1", "NRN-000001")
    assert (doc.kind, doc.number, doc.from_batch, doc.from_pouch_no, doc.to_batch, doc.to_pouch_no) == (
        StockDocument.Kind.TRANSFER, "TRF-000001", shelf["batch"], "1", other, "1")
    move = doc.movements.get()
    assert (move.reason, move.direction, move.pcs, move.ct) == (R.TRANSFER, Movement.SETTLE, 20, D("12.5"))
    assert (_held(onyx).on_pcs, _held(onyx).on_ct) == (20, D("12.5"))


def test_a_transfer_needs_another_existing_batch_and_a_free_number(accounts_user, shelf):
    other = _other()
    with pytest.raises(ServiceError, match="Choose the batch"):
        ledger_assort.transfer_pouch(accounts_user, shelf["onyx"], None, "1")
    with pytest.raises(ServiceError, match="choose another"):
        ledger_assort.transfer_pouch(accounts_user, shelf["onyx"], shelf["batch"], "9")
    ledger_assort.transfer_pouch(accounts_user, shelf["onyx"], other, "1")
    with pytest.raises(ServiceError, match="taken"):
        ledger_assort.transfer_pouch(accounts_user, shelf["ruby"], other, "1")


def test_an_over_long_pouch_no_is_refused_on_a_split_and_a_transfer(accounts_user, shelf):
    with pytest.raises(ServiceError, match="at most 16 characters"):
        _split(accounts_user, shelf, parts=[SplitPart("3" * 17, 6, D("3.5")), SplitPart("4", 3, D("2"))])
    with pytest.raises(ServiceError, match="at most 16 characters"):
        ledger_assort.transfer_pouch(accounts_user, shelf["onyx"], _other(), "1" * 17)
    assert not StockDocument.objects.exists()


def test_an_empty_pouch_is_not_transferred(accounts_user, shelf):
    sale = ledger.open_document(accounts_user, StockDocument.Kind.SINGLE)
    ledger.post(accounts_user, sale, [ledger.Line(shelf["ruby"], R.SALE, Movement.OUT, None, D("40"))])
    with pytest.raises(ServiceError, match="There is nothing in this pouch to transfer."):
        ledger_assort.transfer_pouch(accounts_user, shelf["ruby"], _other(), "1")


def test_a_reversed_transfer_files_the_pouch_back(accounts_user, shelf):
    onyx = shelf["onyx"]
    doc = ledger_assort.transfer_pouch(accounts_user, onyx, _other(), "1")
    ledger.reverse_document(accounts_user, doc)
    onyx.refresh_from_db()
    assert (onyx.batch, onyx.pouch_no) == (shelf["batch"], "1")


def test_a_reversed_transfer_is_refused_once_the_pouch_has_moved_again(accounts_user, shelf):
    onyx = shelf["onyx"]
    doc = ledger_assort.transfer_pouch(accounts_user, onyx, _other(), "1")
    third = Batch.objects.create(code="SP15B", box_colour_id="B", family="S", cls="P", seq="15")
    ledger_assort.transfer_pouch(accounts_user, onyx, third, "1")
    with pytest.raises(ServiceError, match="re-filed since"):
        ledger.reverse_document(accounts_user, doc)


def test_a_reversed_transfer_is_refused_once_its_old_slot_is_taken(accounts_user, shelf):
    onyx, batch = shelf["onyx"], shelf["batch"]
    doc = ledger_assort.transfer_pouch(accounts_user, onyx, _other(), "1")
    services.open_pouch(accounts_user, batch, {"pouch_no": "1"}, pcs=1, ct=D("1"), rate=None)
    with pytest.raises(ServiceError, match="taken since"):
        ledger.reverse_document(accounts_user, doc)


def test_split_and_transfer_need_the_assort_right(production_user, shelf):
    with pytest.raises(PermissionDenied):
        _split(production_user, shelf)
    with pytest.raises(PermissionDenied):
        ledger_assort.transfer_pouch(production_user, shelf["onyx"], _other(), "1")
