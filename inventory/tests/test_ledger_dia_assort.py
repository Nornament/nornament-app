"""Assortment, per rule: balances to 4 places, new lines, weight that stays in grade, the loss,
cost carried with the loss absorbed, an override, a source with no cost, refusals, reversal."""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied

from accounts.models import User
from inventory import dia_services, ledger
from inventory.ledger_dia_assort import Destination, post_assortment
from inventory.models import DiamondLine, DiamondLineCost, Movement, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
K, S, R = StockDocument.Kind, StockDocument.Status, Movement.Reason
CARRIED = D("16940.5128")            # ₹16,517 × 2.00 ct ÷ (2.00 − 0.05) ct, to 4 places


def _line(pk):
    return dia_services.stocked_lines().get(pk=pk)


def _ct(line):
    return _line(line.pk).on_ct


def _cost(line):
    return dia_services.price(_line(line.pk), dia_services.rate_table())[0]


def _new(doc):
    return [m.diamond for m in doc.movements.filter(reason=R.ASSORT_IN)
            .select_related("diamond__code", "diamond__band", "diamond__category").order_by("pk")]


def _dests():
    return [Destination("Round", "E-F", "VVS-VS", "+6-12", D("1.20")),     # upgraded on a re-look
            Destination("Round", "I-J", "SI-I", "+2", D("0.75"))]          # downgraded, smaller sieve


def test_a_balanced_assortment_makes_new_lines_and_leaves_the_rest_in_grade(accounts_user, diamonds):
    rnd = diamonds["round"]
    doc = post_assortment(accounts_user, rnd, D("2.00"), _dests(), D("0.05"), date(2026, 8, 2),
                          "re-sieved after client return")
    assert (doc.kind, doc.number, doc.status, doc.note) == (K.DIA_ASSORT, "AS-000001", S.CLOSED,
                                                           "re-sieved after client return")
    assert _ct(rnd) == D("1.40")                                       # what stayed in grade stays on the source
    up, down = _new(doc)
    assert (up.code_id, up.category, up.batch_no, up.size_text, up.band.value) == (
        "DREF VVS-VS", rnd.category, "B-771", "+6-12", "+6-11")
    assert (down.code_id, down.band.value, down.code.confirmed) == ("DRIJ SI-I", "+2-6", True)
    assert (_ct(up), _ct(down)) == (D("1.20"), D("0.75"))
    assert list(doc.movements.order_by("pk").values_list("reason", "direction", "ct")) == [
        (R.ASSORT_OUT, "out", D("1.95")), (R.WASTAGE, "out", D("0.05")),
        (R.ASSORT_IN, "in", D("1.20")), (R.ASSORT_IN, "in", D("0.75"))]


def test_the_cost_is_carried_with_the_loss_absorbed(accounts_user, diamonds):
    doc = post_assortment(accounts_user, diamonds["round"], D("2.00"), _dests(), D("0.05"), date(2026, 8, 2))
    up, down = _new(doc)
    assert (_cost(up), _cost(down)) == (CARRIED, CARRIED)
    rows = DiamondLineCost.objects.filter(document=doc)
    assert rows.count() == 2 and {r.effective_from for r in rows} == {date(2026, 8, 2)}
    # the parcel's cost is kept whole: 1.95 ct at the carried rate is what 2.00 ct cost at the source's
    assert abs(D("1.95") * CARRIED - D("2.00") * D("16517")) < D("0.01")


def test_an_override_sets_that_destinations_cost(accounts_user, diamonds):
    dests = _dests()
    dests[0].cost_per_ct = D("20000")
    up, down = _new(post_assortment(accounts_user, diamonds["round"], D("2.00"), dests, D("0.05")))
    assert (_cost(up), _cost(down)) == (D("20000"), CARRIED)


def test_a_source_with_no_cost_gives_no_own_cost(accounts_user, diamonds):
    doc = post_assortment(accounts_user, diamonds["princess"], D("0.85"),
                          [Destination("Princess", "G", "VS1", "", D("0.85"))])
    (child,) = _new(doc)
    assert not DiamondLineCost.objects.filter(line=child).exists()
    assert child.size_text == "+2"                                     # a blank size keeps the source's
    assert dia_services.price(_line(child.pk), dia_services.rate_table()) == (None, None)


@pytest.mark.parametrize("take_out, loss, words", [
    (D("2.00"), None, "0.05 ct unaccounted"),
    (D("1.90"), D("0.05"), "-0.1 ct unaccounted"),
    (D("2.0001"), D("0.05"), "0.0001 ct unaccounted"),
    (None, None, "taken out"),
])
def test_an_assortment_must_balance_to_four_places(accounts_user, diamonds, take_out, loss, words):
    with pytest.raises(ServiceError, match=words):
        post_assortment(accounts_user, diamonds["round"], take_out, _dests(), loss)
    assert not StockDocument.objects.exists() and _ct(diamonds["round"]) == D("3.40")


def test_every_destination_needs_carats_and_a_listed_description(accounts_user, diamonds):
    with pytest.raises(ServiceError, match="Every destination needs carats"):
        post_assortment(accounts_user, diamonds["round"], D("1"), [Destination("Round", "G", "VS1", "", None)])
    with pytest.raises(ServiceError, match="Cushion is not on the shape list"):
        post_assortment(accounts_user, diamonds["round"], D("1"), [Destination("Cushion", "G", "VS1", "", D("1"))])
    with pytest.raises(ServiceError, match="Add at least one destination"):
        post_assortment(accounts_user, diamonds["round"], D("1"), [], D("1"))
    assert not StockDocument.objects.exists() and DiamondLine.objects.count() == 3


def test_taking_out_more_than_the_line_holds_is_refused(accounts_user, diamonds):
    with pytest.raises(ServiceError, match="below zero"):
        post_assortment(accounts_user, diamonds["princess"], D("1"), [Destination("Princess", "G", "VS1", "", D("1"))])
    assert DiamondLine.objects.count() == 3


def test_an_untouched_assortment_reverses_whole(accounts_user, diamonds):
    doc = post_assortment(accounts_user, diamonds["round"], D("2.00"), _dests(), D("0.05"))
    up, down = _new(doc)
    ledger.reverse_document(accounts_user, doc)
    assert (_ct(diamonds["round"]), _ct(up), _ct(down)) == (D("3.40"), D("0"), D("0"))


def test_reversal_is_refused_once_a_new_line_has_moved(accounts_user, diamonds):
    doc = post_assortment(accounts_user, diamonds["round"], D("2.00"), _dests(), D("0.05"))
    up, _ = _new(doc)
    card = ledger.open_document(accounts_user, K.DIA_JOB)
    ledger.post(accounts_user, card, [ledger.Line(up, R.JOB_WORK_OUT, Movement.OUT, None, D("0.5"))])
    with pytest.raises(ServiceError, match="has moved since"):
        ledger.reverse_document(accounts_user, doc)


def test_assorting_needs_the_right_and_an_override_needs_sight_of_cost(production_user, accounts_user, diamonds):
    with pytest.raises(PermissionDenied):
        post_assortment(production_user, diamonds["round"], D("2.00"), _dests(), D("0.05"))
    Group.objects.get(name="ACCOUNTS").permissions.remove(Permission.objects.get(codename="view_cost"))
    blind = User.objects.get(pk=accounts_user.pk)                     # a fresh object: no cached permissions
    dests = _dests()
    dests[0].cost_per_ct = D("20000")
    with pytest.raises(PermissionDenied):
        post_assortment(blind, diamonds["round"], D("2.00"), dests, D("0.05"))
    post_assortment(blind, diamonds["round"], D("2.00"), _dests(), D("0.05"))   # a carried cost needs no sight of it


def test_a_blank_destination_size_keeps_a_per_stone_band(accounts_user, diamonds):
    rnd = diamonds["round"]
    (mm,) = dia_services.open_lines(accounts_user, [
        {"category": rnd.category, "code": rnd.code, "batch_no": "B-772", "size_text": "2.7*2.1 - 2.9*1.8",
         "band": dia_services.term("band", "carat band"), "ct_lo": D("0.07"), "ct_hi": D("0.07"), "ct": D("0.14")}])
    for typed in ("", "2.7*2.1 - 2.9*1.8"):           # blank, or the source's own size typed out
        (child,) = _new(post_assortment(accounts_user, mm, D("0.07"), [Destination("Round", "E-F", "VVS-VS", typed, D("0.07"))]))
        assert (child.size_text, child.band.value, child.ct_lo, child.ct_hi) == (
            "2.7*2.1 - 2.9*1.8", "carat band", D("0.07"), D("0.07"))


def test_a_destination_in_the_source_grade_is_refused(accounts_user, diamonds):
    for size in ("", "+6-12"):
        with pytest.raises(ServiceError, match="stays on the source"):
            post_assortment(accounts_user, diamonds["round"], D("1"), [Destination("Round", "F-G-H", "VS-SI", size, D("1"))])
    assert not StockDocument.objects.exists() and DiamondLine.objects.count() == 3


def test_a_carried_cost_too_large_to_keep_is_refused(accounts_user, diamonds):
    rnd = diamonds["round"]
    dia_services.set_rate(accounts_user, rnd.code, "+6-12", D("9000000000"), None, date(2026, 9, 2))
    with pytest.raises(ServiceError, match="too large"):
        post_assortment(accounts_user, rnd, D("2"), [Destination("Round", "E-F", "VVS-VS", "", D("1"))], D("1"))
    assert not StockDocument.objects.exists() and DiamondLine.objects.count() == 3
