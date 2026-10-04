"""Part 5c: merging whole pouches of one stone in one batch."""
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import ledger_assort, services
from inventory.models import Batch, Movement, Pouch, PriceEntry, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
R = Movement.Reason
ONYX = {"stone_name": "Green Onyx", "colour": "Green", "shape": "Oval", "quality": "B"}


def _held(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()


@pytest.fixture
def twin(admin_user_, shelf):
    """A second onyx pouch in the shelf's batch: 10 pcs, 7.5 ct at ₹9,000 (the onyx is 20 pcs, 12.5 ct at ₹7,919)."""
    return services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "5", "size_text": "12*10", **ONYX},
                               pcs=10, ct=D("7.5"), rate=D("9000"))


#: (12.5 × 7,919 + 7.5 × 9,000) / 20 = 8,324.375
WEIGHTED = D("8324.3750")


def test_candidates_are_the_same_stone_in_the_same_batch_with_stock(admin_user_, shelf, twin):
    empty = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "6", **ONYX}, pcs=0, ct=D("0"), rate=None)
    other = Batch.objects.create(code="SP14B", box_colour_id="B", family="S", cls="P", seq="14")
    services.open_pouch(admin_user_, other, {"pouch_no": "1", **ONYX}, pcs=1, ct=D("1"), rate=None)
    found = ledger_assort.candidates(twin)
    assert [p.pk for p in found] == [twin.pk, shelf["onyx"].pk]       # the opening pouch first
    assert empty.pk not in {p.pk for p in found}
    assert [p.pk for p in ledger_assort.candidates(shelf["ruby"])] == [shelf["ruby"].pk]   # no like pouch


def test_merging_into_an_existing_pouch(accounts_user, shelf, twin):
    onyx = shelf["onyx"]
    doc, rate = ledger_assort.merge_pouches(accounts_user, [onyx, twin], into=onyx, size_text="14*10 and 12*10")
    assert (doc.kind, doc.number, doc.status) == (StockDocument.Kind.MERGE, "MRG-000001", StockDocument.Status.CLOSED)
    assert rate == WEIGHTED
    held = _held(onyx)
    assert (held.on_pcs, held.on_ct, held.rate) == (30, D("20"), WEIGHTED)
    assert (_held(twin).on_pcs, _held(twin).on_ct) == (0, D("0"))
    assert Pouch.objects.get(pk=onyx.pk).size_text == "14*10 and 12*10"
    out = doc.movements.get(pouch=twin)
    assert (out.reason, out.direction, out.pcs, out.ct) == (R.MERGE, Movement.OUT, 10, D("7.5"))
    into = doc.movements.get(pouch=onyx)
    assert (into.reason, into.direction, into.pcs, into.ct) == (R.MERGE, Movement.IN, 10, D("7.5"))
    assert onyx.prices.filter(kind=PriceEntry.VALUATION).count() == 2       # the opening 7,919 is kept


def test_merging_into_a_new_pouch_copies_the_stone_and_takes_the_size(accounts_user, shelf, twin):
    onyx = shelf["onyx"]
    doc, rate = ledger_assort.merge_pouches(accounts_user, [twin, onyx], into=None, new_pouch_no="7", size_text="mixed")
    new = Pouch.objects.get(batch=shelf["batch"], pouch_no="7")
    assert new.ref.startswith("NRN-") and new.parent is None and new.size_text == "mixed"
    assert (new.stone_name, new.carton, new.supplier, new.countable) == ("Green Onyx", "C-117", shelf["supplier"], True)
    held = _held(new)
    assert (held.on_pcs, held.on_ct, held.rate) == (30, D("20"), WEIGHTED)
    assert (_held(onyx).on_ct, _held(twin).on_ct) == (D("0"), D("0"))
    assert doc.movements.filter(reason=R.MERGE, direction=Movement.OUT).count() == 2


def test_a_loss_is_wastage_on_the_target_and_the_rate_is_worked_before_it(accounts_user, shelf, twin):
    onyx = shelf["onyx"]
    doc, rate = ledger_assort.merge_pouches(accounts_user, [onyx, twin], into=onyx, loss_pcs=1, loss_ct=D("0.5"))
    assert rate == WEIGHTED
    loss = doc.movements.get(reason=R.WASTAGE)
    assert (loss.pouch_id, loss.direction, loss.pcs, loss.ct, loss.note) == (
        onyx.pk, Movement.OUT, 1, D("0.5"), "Loss in the merge")
    assert (_held(onyx).on_pcs, _held(onyx).on_ct) == (29, D("19.5"))


def test_no_valuation_is_written_when_one_pouch_has_none(accounts_user, admin_user_, shelf):
    bare = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "5", **ONYX}, pcs=2, ct=D("1"), rate=None)
    before = PriceEntry.objects.count()
    doc, rate = ledger_assort.merge_pouches(accounts_user, [shelf["onyx"], bare], into=shelf["onyx"])
    assert rate is None and PriceEntry.objects.count() == before


def _refused(user, pouches, match, **kwargs):
    before = (StockDocument.objects.count(), Movement.objects.count(), Pouch.objects.count(), PriceEntry.objects.count())
    with pytest.raises(ServiceError, match=match):
        ledger_assort.merge_pouches(user, pouches, **kwargs)
    assert (StockDocument.objects.count(), Movement.objects.count(), Pouch.objects.count(),
            PriceEntry.objects.count()) == before


def test_each_refusal_writes_nothing(accounts_user, admin_user_, shelf, twin, parties):
    from inventory import ledger_jobs

    onyx = shelf["onyx"]
    _refused(accounts_user, [onyx], "Tick at least two pouches to merge.", into=onyx)
    _refused(accounts_user, [onyx, shelf["ruby"]], "Only pouches of the same stone in the same batch merge.", into=onyx)
    other = Batch.objects.create(code="SP14B", box_colour_id="B", family="S", cls="P", seq="14")
    far = services.open_pouch(admin_user_, other, {"pouch_no": "1", **ONYX}, pcs=1, ct=D("1"), rate=None)
    _refused(accounts_user, [onyx, far], "Only pouches of the same stone in the same batch merge.", into=onyx)
    empty = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "6", **ONYX}, pcs=0, ct=D("0"), rate=None)
    _refused(accounts_user, [onyx, empty], f"{empty} is empty.", into=onyx)
    loose = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "8", **ONYX}, pcs=None, ct=D("3"), rate=None)
    _refused(accounts_user, [onyx, loose], f"Count {loose} first", into=onyx)
    _refused(accounts_user, [onyx, twin], "Merge into one of the ticked pouches, or a new pouch.", into=shelf["ruby"])
    _refused(accounts_user, [onyx, twin], "is taken", into=None, new_pouch_no="2")
    _refused(accounts_user, [onyx, twin], "A loss cannot be negative.", into=onyx, loss_ct=D("-1"))
    _refused(accounts_user, [onyx, twin], "The loss is more than the pouches hold.", into=onyx, loss_ct=D("25"))
    _refused(accounts_user, [onyx, twin], "The loss is more than the pouches hold.", into=onyx, loss_pcs=31)
    ledger_jobs.job_work_out(admin_user_, twin, parties["karigar"], "2026/0500", 2, D("1"))
    _refused(accounts_user, [onyx, twin], f"Settle 2026/0500 first: {twin} still has stone out on it.", into=onyx)


def test_merging_needs_the_assort_right(sales_user, production_user, shelf, twin):
    for user in (sales_user, production_user):
        with pytest.raises(PermissionDenied):
            ledger_assort.merge_pouches(user, [shelf["onyx"], twin], into=shelf["onyx"])
    assert not StockDocument.objects.exists()
