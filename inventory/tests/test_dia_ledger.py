"""The ledger engine with a diamond line as the owner: carats are the quantity, a job card closes
by hand and only at zero, a created line blocks a reversal once it moves — and the invariant,
extended to diamond lines."""
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from inventory import dia_services, ledger, ledger_jobs
from inventory.ledger import Line
from inventory.models import Movement, StockDocument
from inventory.tests.conftest import DIA_SUPPLIER, KARIGAR
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
K, S, R = StockDocument.Kind, StockDocument.Status, Movement.Reason
IN, OUT, SETTLE = Movement.IN, Movement.OUT, Movement.SETTLE


def _ct(line):
    return dia_services.stocked_lines().get(pk=line.pk).on_ct


def _card(user, parties=None):
    return ledger.open_document(user, K.DIA_JOB, vendor=parties["karigar"] if parties else None)


def _bought(user, like, ct, number="INV-9"):
    """A purchase of one new line shaped like ``like``, straight through the engine."""
    doc = ledger.open_document(user, K.DIA_PURCHASE, number)
    fresh = dia_services.new_line(category=like.category, code=like.code, band=like.band, size_text=like.size_text)
    ledger.post(user, doc, [Line(fresh, R.PURCHASE, IN, None, D(ct))])
    return doc, fresh


def test_diamond_documents_number_themselves(admin_user_):
    kinds = (K.DIA_JOB, K.DIA_JOB, K.DIA_ASSORT, K.DIA_PURCHASE)
    assert [ledger.open_document(admin_user_, kind).number for kind in kinds] == [
        "JC-000001", "JC-000002", "AS-000001", "DP-000001"]
    assert ledger.open_document(admin_user_, K.DIA_PURCHASE, "2026/0442").number == "2026/0442"


def test_a_diamond_line_moves_by_carats(admin_user_, diamonds):
    rnd = diamonds["round"]
    doc = ledger.open_document(admin_user_, K.DIA_ASSORT)
    with pytest.raises(ServiceError, match="needs carats above zero"):
        ledger.post(admin_user_, doc, [Line(rnd, R.ASSORT_OUT, OUT, 3, None)])
    ledger.post(admin_user_, doc, [Line(rnd, R.ASSORT_OUT, OUT, 99, D("1.4"))])     # pieces ride along, unchecked
    assert _ct(rnd) == D("2.00") and doc.movements.get().diamond == rnd and doc.status == S.CLOSED


def test_no_diamond_line_goes_below_zero(admin_user_, diamonds):
    rnd, princess = diamonds["round"], diamonds["princess"]
    doc = ledger.open_document(admin_user_, K.DIA_ASSORT)
    with pytest.raises(ServiceError, match=r"Not enough in NRD-000002 .* below zero \(-0\.15 ct\)"):
        ledger.post(admin_user_, doc, [Line(rnd, R.ASSORT_OUT, OUT, None, D("1")),
                                       Line(princess, R.ASSORT_OUT, OUT, None, D("1"))])
    assert not doc.movements.exists() and _ct(rnd) == D("3.40")


def test_a_pouch_moves_only_on_a_stones_document_and_a_line_only_on_a_diamond_one(admin_user_, shelf, diamonds, parties):
    card = _card(admin_user_, parties)
    with pytest.raises(ServiceError, match="A pouch moves on a stones document, a diamond line on a diamond one"):
        ledger.post(admin_user_, card, [Line(shelf["onyx"], R.JOB_WORK_OUT, OUT, 1, D("1"))])
    job = ledger.open_document(admin_user_, K.JOB_WORK, "2026/0999", vendor=parties["karigar"])
    with pytest.raises(ServiceError, match="A pouch moves on a stones document, a diamond line on a diamond one"):
        ledger.post(admin_user_, job, [Line(diamonds["round"], R.JOB_WORK_OUT, OUT, None, D("1"))])
    assert not Movement.objects.filter(document__in=[card, job]).exists() and _ct(diamonds["round"]) == D("3.40")


def test_a_diamond_reversal_that_would_go_below_zero_is_refused(admin_user_, diamonds):
    rnd = diamonds["round"]
    back = ledger.open_document(admin_user_, K.DIA_PURCHASE)
    ledger.post(admin_user_, back, [Line(rnd, R.SALES_RETURN, IN, None, D("1"))])
    drain = ledger.open_document(admin_user_, K.DIA_ASSORT)
    ledger.post(admin_user_, drain, [Line(rnd, R.ASSORT_OUT, OUT, None, D("4.40"))])
    with pytest.raises(ServiceError, match=r"Not enough in NRD-000001 .* below zero \(-1 ct\)"):
        ledger.reverse_document(admin_user_, back)
    back.refresh_from_db()
    assert back.status == S.CLOSED and not StockDocument.objects.filter(reverses=back).exists()


def test_a_job_card_credit_cannot_exceed_what_that_line_has_out(admin_user_, diamonds, parties):
    rnd, princess = diamonds["round"], diamonds["princess"]
    card = _card(admin_user_, parties)
    ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_OUT, OUT, None, D("1")),
                                    Line(princess, R.JOB_WORK_OUT, OUT, None, D("0.5"))])
    assert ledger.outstanding(card) == {rnd.pk: (0, D("1")), princess.pk: (0, D("0.5"))}
    with pytest.raises(ServiceError, match="cannot exceed what is outstanding: JC-000001 has 0.5 ct of NRD-000002"):
        ledger.post(admin_user_, card, [Line(princess, R.CONSUMED, SETTLE, None, D("0.6"))])
    with pytest.raises(ServiceError, match="cannot exceed"):
        ledger.post(admin_user_, card, [Line(diamonds["polki"], R.JOB_WORK_IN, IN, None, D("0.1"))])  # never issued
    ledger.post(admin_user_, card, [Line(rnd, R.RETURNED_UNUSED, IN, None, D("0.4"))])
    assert ledger.outstanding(card)[rnd.pk] == (0, D("0.6")) and _ct(rnd) == D("2.80")


def test_a_job_card_never_closes_itself_and_closes_only_at_zero(admin_user_, diamonds, parties):
    rnd = diamonds["round"]
    card = _card(admin_user_, parties)
    ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_OUT, OUT, None, D("1"))])
    with pytest.raises(ServiceError, match="can close only at zero: 1 ct outstanding"):
        ledger.close_document(admin_user_, card)
    ledger.post(admin_user_, card, [Line(rnd, R.CONSUMED, SETTLE, None, D("1"))])
    card.refresh_from_db()
    assert card.status == S.OPEN                                  # balanced, still open: more may be issued
    ledger.close_document(admin_user_, card)
    card.refresh_from_db()
    assert card.status == S.CLOSED
    with pytest.raises(ServiceError, match="is closed; it takes no more entries"):
        ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_OUT, OUT, None, D("0.1"))])
    with pytest.raises(ServiceError, match="only an open card can close"):
        ledger.close_document(admin_user_, card)


def test_undo_reopens_a_closed_card(admin_user_, diamonds, parties):
    rnd = diamonds["round"]
    card = _card(admin_user_, parties)
    ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_OUT, OUT, None, D("1"))])
    ledger.post(admin_user_, card, [Line(rnd, R.WASTAGE, SETTLE, None, D("1"))])
    ledger.close_document(admin_user_, card)
    undone = ledger.undo_last(admin_user_, card)
    card.refresh_from_db()
    assert undone.reverses.reason == R.WASTAGE and undone.diamond == rnd
    assert card.status == S.OPEN and ledger.outstanding(card)[rnd.pk] == (0, D("1"))


def test_only_a_job_card_is_closed_by_hand(admin_user_, shelf, parties):
    job = ledger_jobs.job_work_out(admin_user_, shelf["onyx"], parties["karigar"], "2026/0431", 1, D("1"))
    with pytest.raises(ServiceError, match="closes itself"):
        ledger.close_document(admin_user_, job)


def test_closing_needs_the_job_cards_right(admin_user_, sales_user, diamonds):
    with pytest.raises(PermissionDenied):
        ledger.close_document(sales_user, _card(admin_user_))


def test_reversing_a_card_puts_every_line_back(admin_user_, diamonds, parties):
    rnd = diamonds["round"]
    card = _card(admin_user_, parties)
    ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_OUT, OUT, None, D("1"))])
    ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_IN, IN, None, D("0.25"))])
    reversal = ledger.reverse_document(admin_user_, card)
    card.refresh_from_db()
    assert card.status == S.REVERSED and (reversal.kind, reversal.status) == (K.DIA_JOB, S.CLOSED)
    assert _ct(rnd) == D("3.40")


def test_a_created_line_that_moved_since_blocks_the_reversal(admin_user_, diamonds, parties):
    bought, fresh = _bought(admin_user_, diamonds["round"], "2")
    card = _card(admin_user_, parties)
    ledger.post(admin_user_, card, [Line(fresh, R.JOB_WORK_OUT, OUT, None, D("0.5"))])
    with pytest.raises(ServiceError, match="NRD-000004 .* has moved since"):
        ledger.reverse_document(admin_user_, bought)
    ledger.reverse_document(admin_user_, card)                    # its later movement reversed …
    ledger.reverse_document(admin_user_, bought)                  # … the purchase reverses, the line stays at zero
    assert _ct(fresh) == D("0")


def test_an_assorted_line_counts_as_created(admin_user_, diamonds):
    princess = diamonds["princess"]
    doc = ledger.open_document(admin_user_, K.DIA_ASSORT)
    child = dia_services.new_line(category=princess.category, code=princess.code, band=princess.band, size_text="+2")
    ledger.post(admin_user_, doc, [Line(princess, R.ASSORT_OUT, OUT, None, D("0.5")),
                                   Line(child, R.ASSORT_IN, IN, None, D("0.5"))])
    again = ledger.open_document(admin_user_, K.DIA_ASSORT)
    ledger.post(admin_user_, again, [Line(child, R.ASSORT_OUT, OUT, None, D("0.1"))])
    with pytest.raises(ServiceError, match="has moved since"):
        ledger.reverse_document(admin_user_, doc)


def test_the_counterparty_of_a_card_is_a_karigar(admin_user_, diamonds, parties):
    assert ledger.party(_card(admin_user_, parties)) == {"karigar_name": KARIGAR}
    assert ledger.party(_card(admin_user_)) == {}                                       # In-house
    bought = ledger.open_document(admin_user_, K.DIA_PURCHASE, vendor=diamonds["supplier"])
    assert ledger.party(bought) == {"vendor_name": DIA_SUPPLIER}


def test_job_cards_never_count_as_stones_out(admin_user_, shelf, diamonds, parties):
    card = _card(admin_user_, parties)
    ledger.post(admin_user_, card, [Line(diamonds["round"], R.JOB_WORK_OUT, OUT, None, D("1"))])
    assert ledger.out_summary() == {"ct": D("0"), "value": D("0"), "documents": 0}


def test_on_hand_plus_out_on_cards_is_what_came_in_less_what_left_for_good(admin_user_, diamonds, parties):
    """The ledger invariant, for diamond lines: through every job-card entry, an undo, a purchase,
    an assortment with a sorting loss, and a reversal."""
    rnd, princess = diamonds["round"], diamonds["princess"]

    def owned():
        on_hand = sum((line.on_ct or 0 for line in dia_services.stocked_lines()), D("0"))
        cards = StockDocument.objects.filter(kind=K.DIA_JOB, reverses__isnull=True).exclude(status=S.REVERSED)
        return on_hand + sum((ct for card in cards for _, ct in ledger.outstanding(card).values()), D("0"))

    opening = D("47.46")                                                                # 3.40 + 0.85 + 43.21
    assert owned() == opening
    card = _card(admin_user_, parties)
    ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_OUT, OUT, None, D("2"))])
    ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_IN, IN, None, D("0.5"))])
    ledger.post(admin_user_, card, [Line(rnd, R.RETURNED_UNUSED, IN, None, D("0.25"))])
    ledger.post(admin_user_, card, [Line(rnd, R.CONSUMED, SETTLE, None, D("1"))])     # left for good: 1
    ledger.post(admin_user_, card, [Line(rnd, R.BREAKAGE, SETTLE, None, D("0.1"))])   # broken …
    ledger.undo_last(admin_user_, card)                                                 # … then undone
    _bought(admin_user_, rnd, "1.5")                                                    # came in: 1.5
    sort = ledger.open_document(admin_user_, K.DIA_ASSORT)
    child = dia_services.new_line(category=princess.category, code=princess.code, band=princess.band, size_text="+2")
    ledger.post(admin_user_, sort, [Line(princess, R.ASSORT_OUT, OUT, None, D("0.5")),
                                    Line(princess, R.WASTAGE, OUT, None, D("0.05")),    # left for good: 0.05
                                    Line(child, R.ASSORT_IN, IN, None, D("0.5"))])
    other = _card(admin_user_)
    ledger.post(admin_user_, other, [Line(diamonds["polki"], R.JOB_WORK_OUT, OUT, None, D("3"))])
    ledger.reverse_document(admin_user_, other)                                         # nets to nothing
    assert owned() == opening + D("1.5") - D("1") - D("0.05")
    assert ledger.outstanding(card) == {rnd.pk: (0, D("0.25"))}


def test_the_diamond_ledger_screens_have_their_names():
    for name, args in [("inventory:dia_jobs", []), ("inventory:dia_job_new", []), ("inventory:dia_job_post", [1]),
                       ("inventory:dia_job_close", [1]), ("inventory:dia_job_undo", [1]),
                       ("inventory:dia_job_reverse", [1]), ("inventory:dia_assorts", []),
                       ("inventory:dia_assort_reverse", [1]), ("inventory:dia_purchase", []),
                       ("inventory:dia_purchase_reverse", [1])]:
        assert reverse(name, args=args)


def test_a_diamond_document_cannot_be_dated_in_the_future(admin_user_, diamonds):
    from datetime import timedelta

    from django.utils import timezone

    from inventory import ledger_dia_assort, ledger_dia_jobs, ledger_dia_purchase
    from inventory.ledger_purchase import PurchaseHeader

    tomorrow = timezone.localdate() + timedelta(days=1)
    card = ledger_dia_jobs.open_card(admin_user_, None)
    attempts = [
        lambda: ledger_dia_jobs.open_card(admin_user_, None, opened_on=tomorrow),
        lambda: ledger_dia_jobs.post_entry(admin_user_, card, "issue", diamonds["round"], D("1"), occurred_on=tomorrow),
        lambda: ledger_dia_assort.post_assortment(
            admin_user_, diamonds["round"], D("1"),
            [ledger_dia_assort.Destination("Round", "E-F", "VVS-VS", "", D("1"))], occurred_on=tomorrow),
        lambda: ledger_dia_purchase.post_dia_purchase(
            admin_user_, PurchaseHeader(supplier=diamonds["supplier"], occurred_on=tomorrow, invoice_no="DIA-1"),
            [ledger_dia_purchase.DiaPurchaseLine("Natural Diamond", "Round", "F-G-H", "VS-SI", "+6-12", None,
                                                 D("1"), D("100"))]),
    ]
    for attempt in attempts:
        with pytest.raises(ServiceError, match="A date can't be in the future"):
            attempt()
    assert StockDocument.objects.count() == 1 and not Movement.objects.filter(document__isnull=False).exists()
