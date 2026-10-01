"""Diamond job cards, per rule: the six entries, per-line outstanding, close only at zero, refused
after close, undo reopens, reverse."""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from inventory import dia_services, ledger, ledger_jobs
from inventory.ledger_dia_jobs import ENTRY_CHOICES, ENTRY_LABEL, credit_choices, open_card, owed, post_entry
from inventory.models import Movement, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
S, R = StockDocument.Status, Movement.Reason


def _ct(line):
    return dia_services.stocked_lines().get(pk=line.pk).on_ct


@pytest.fixture
def card(accounts_user, diamonds, parties):
    """The prototype's JC card: both lines issued on one challan."""
    card = open_card(accounts_user, parties["karigar"], date(2026, 5, 4))
    post_entry(accounts_user, card, "issue", diamonds["round"], D("3.40"), date(2026, 5, 4), "CH 2026/0417")
    post_entry(accounts_user, card, "issue", diamonds["princess"], D("0.85"), date(2026, 5, 4), "CH 2026/0417")
    return card


def test_a_card_opens_numbered_with_its_karigar_or_in_house(accounts_user, diamonds, parties):
    first = open_card(accounts_user, parties["karigar"], date(2026, 5, 4), "rings for the Diwali order")
    assert (first.number, first.kind, first.status) == ("JC-000001", StockDocument.Kind.DIA_JOB, S.OPEN)
    assert (first.vendor, first.occurred_on, first.note) == (parties["karigar"], date(2026, 5, 4),
                                                            "rings for the Diwali order")
    assert open_card(accounts_user, None).vendor is None


def test_an_issue_takes_the_carats_off_the_line(card, diamonds):
    assert (_ct(diamonds["round"]), _ct(diamonds["princess"])) == (D("0"), D("0"))
    first = card.movements.order_by("pk").first()
    assert (first.reason, first.direction, first.ref, first.counterparty) == (
        R.JOB_WORK_OUT, Movement.OUT, "CH 2026/0417", card.vendor)
    assert timezone.localtime(first.occurred_at).date() == date(2026, 5, 4)
    assert owed(card) == D("4.25")


def test_the_six_entries_and_how_each_moves(accounts_user, card, diamonds):
    rnd = diamonds["round"]
    post_entry(accounts_user, card, "loose", rnd, D("0.85"), ref="CH 2026/0417")   # back into the line
    post_entry(accounts_user, card, "unused", rnd, D("0.40"))                       # never worked: back too
    post_entry(accounts_user, card, "set", rnd, D("1.50"), ref="JOB")               # settled, not returned
    post_entry(accounts_user, card, "loss", rnd, D("0.05"))
    post_entry(accounts_user, card, "breakage", rnd, D("0.10"))
    assert _ct(rnd) == D("1.25")
    assert ledger.outstanding(card)[rnd.pk] == (0, D("0.50"))
    posted = list(card.movements.order_by("pk").values_list("reason", "direction"))[2:]
    assert posted == [(R.JOB_WORK_IN, "in"), (R.RETURNED_UNUSED, "in"), (R.CONSUMED, "settle"),
                      (R.WASTAGE, "settle"), (R.BREAKAGE, "settle")]
    assert [ENTRY_LABEL[reason] for reason, _ in posted] == [
        "Received loose", "Returned unused", "Consumed / set", "Loss in process", "Breakage"]


def test_the_stock_control_select_reads_as_the_prototype():
    assert ENTRY_CHOICES == [("issue", "Issue to job card — debit"), ("loose", "Received loose — credit"),
                             ("set", "Consumed / set — credit"), ("loss", "Loss in process — credit"),
                             ("unused", "Returned unused — credit"), ("breakage", "Breakage — credit")]


def test_a_credit_settles_only_its_own_line(accounts_user, card, diamonds):
    with pytest.raises(ServiceError, match="cannot exceed what is outstanding"):
        post_entry(accounts_user, card, "set", diamonds["princess"], D("1.00"))     # 0.85 out on that line
    with pytest.raises(ServiceError, match="cannot exceed"):
        post_entry(accounts_user, card, "loose", diamonds["polki"], D("0.10"))       # never issued here
    assert [(c["pk"], c["ct"]) for c in credit_choices(card)] == [
        (diamonds["round"].pk, D("3.40")), (diamonds["princess"].pk, D("0.85"))]
    assert credit_choices(card)[0]["label"] == "NRD-000001 · DRFGH VS-SI · +6-12 · B-771"


def test_a_card_closes_only_at_zero_and_then_takes_nothing(accounts_user, card, diamonds):
    with pytest.raises(ServiceError, match="can close only at zero: 4.25 ct outstanding"):
        ledger.close_document(accounts_user, card)
    post_entry(accounts_user, card, "set", diamonds["round"], D("3.40"))
    post_entry(accounts_user, card, "unused", diamonds["princess"], D("0.85"))
    card.refresh_from_db()
    assert card.status == S.OPEN                          # balanced, but only Close closes it
    ledger.close_document(accounts_user, card)
    card.refresh_from_db()
    assert card.status == S.CLOSED
    with pytest.raises(ServiceError, match="is closed; it takes no more entries"):
        post_entry(accounts_user, card, "issue", diamonds["polki"], D("1"))


def test_undo_reopens_a_closed_card(accounts_user, card, diamonds):
    post_entry(accounts_user, card, "set", diamonds["round"], D("3.40"))
    post_entry(accounts_user, card, "unused", diamonds["princess"], D("0.85"))
    ledger.close_document(accounts_user, card)
    ledger.undo_last(accounts_user, card)
    card.refresh_from_db()
    assert card.status == S.OPEN and owed(card) == D("0.85") and _ct(diamonds["princess"]) == D("0")


def test_reversing_a_card_puts_its_lines_back_and_it_takes_nothing_more(accounts_user, card, diamonds):
    post_entry(accounts_user, card, "loose", diamonds["round"], D("1"))
    ledger.reverse_document(accounts_user, card)
    card.refresh_from_db()
    assert card.status == S.REVERSED
    assert (_ct(diamonds["round"]), _ct(diamonds["princess"])) == (D("3.40"), D("0.85"))
    with pytest.raises(ServiceError, match="is reversed; it takes no more entries"):
        post_entry(accounts_user, card, "issue", diamonds["round"], D("1"))


def test_an_issue_cannot_take_more_than_the_line_holds(accounts_user, diamonds):
    card = open_card(accounts_user, None)
    with pytest.raises(ServiceError, match="below zero"):
        post_entry(accounts_user, card, "issue", diamonds["princess"], D("0.9"))


@pytest.mark.parametrize("entry, line, ct, words", [
    ("swap", "round", "1", "Choose the stock-control entry"),
    ("issue", None, "1", "Choose the line"),
    ("issue", "round", None, "needs carats above zero"),
    ("issue", "round", "0.00001", "more than 4 decimal places"),
])
def test_an_entry_needs_its_kind_its_line_and_its_carats(accounts_user, diamonds, entry, line, ct, words):
    from inventory import inputs

    card = open_card(accounts_user, None)
    with pytest.raises(ServiceError, match=words):
        post_entry(accounts_user, card, entry, diamonds[line] if line else None, inputs.decimal(ct, "Carats"))
    assert not card.movements.exists()


def test_a_job_card_needs_the_right(sales_user, accounts_user, diamonds):
    with pytest.raises(PermissionDenied):
        open_card(sales_user, None)
    card = open_card(accounts_user, None)
    with pytest.raises(PermissionDenied):
        post_entry(sales_user, card, "issue", diamonds["round"], D("1"))


def test_the_karigar_desk_names_only_karigars_already_on_a_challan_or_card(karigar_user, accounts_user, diamonds,
                                                                           parties):
    with pytest.raises(ServiceError, match="Choose the karigar"):
        open_card(karigar_user, parties["karigar"])                     # never named anywhere yet
    assert open_card(karigar_user, None).vendor is None                  # In-house is always there
    open_card(accounts_user, parties["karigar"])                         # named once, by a login that sees suppliers
    assert open_card(karigar_user, parties["karigar"]).vendor == parties["karigar"]
    assert diamonds["supplier"].pk not in {c["pk"] for c in ledger_jobs.karigar_choices(karigar_user)}
