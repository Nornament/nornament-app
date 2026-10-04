"""Part 5d: stock takes — counting a box colour, a batch or a diamond category, and posting the differences."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from inventory import dia_services, ledger, ledger_assort, ledger_single, services, stock_take
from inventory.models import Batch, BoxColour, DiamondTerm, Movement, Pouch, StockDocument, StockTake
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
R = Movement.Reason


def _held(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()


def _natural():
    return DiamondTerm.objects.get(kind="category", value="Natural Diamond")


def test_starting_numbers_and_scopes(accounts_user, shelf, diamonds):
    by_colour = stock_take.start(accounts_user, StockTake.STONES, box_colour=BoxColour.objects.get(pk="G"))
    assert (by_colour.number, by_colour.status) == ("ST-000001", StockTake.OPEN)
    assert stock_take.scope_label(by_colour).startswith("Box colour G")
    dia = stock_take.start(accounts_user, StockTake.DIAMONDS, category=_natural())
    assert dia.number == "ST-000002" and stock_take.scope_label(dia) == "Natural Diamond"


def test_a_stones_scope_needs_exactly_one_of_box_colour_or_batch(accounts_user, shelf):
    with pytest.raises(ServiceError):
        stock_take.start(accounts_user, StockTake.STONES)
    with pytest.raises(ServiceError):
        stock_take.start(accounts_user, StockTake.STONES, box_colour=BoxColour.objects.get(pk="G"), batch=shelf["batch"])
    assert not StockTake.objects.exists()


def test_overlapping_stock_takes_are_refused_both_ways(accounts_user, shelf, diamonds):
    colour = BoxColour.objects.get(pk="G")
    first = stock_take.start(accounts_user, StockTake.STONES, box_colour=colour)
    with pytest.raises(ServiceError, match=f"{first.number} is already counting"):
        stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])          # a batch in that colour
    stock_take.cancel(accounts_user, first)
    by_batch = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    with pytest.raises(ServiceError, match=f"{by_batch.number} is already counting"):
        stock_take.start(accounts_user, StockTake.STONES, box_colour=colour)
    other = Batch.objects.create(code="SP14B", box_colour_id="B", family="S", cls="P", seq="14")
    stock_take.start(accounts_user, StockTake.STONES, batch=other)                        # no overlap
    stock_take.start(accounts_user, StockTake.DIAMONDS, category=_natural())
    with pytest.raises(ServiceError, match="is already counting"):
        stock_take.start(accounts_user, StockTake.DIAMONDS, category=_natural())


def test_the_sheet_lists_the_scope_with_stock_plus_anything_counted(accounts_user, admin_user_, shelf, diamonds):
    empty = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "9", "stone_name": "Jade"}, pcs=0,
                                ct=D("0"), rate=None)
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    assert [p.pk for p in stock_take.owners(take)] == [shelf["onyx"].pk, shelf["ruby"].pk]
    dia = stock_take.start(accounts_user, StockTake.DIAMONDS, category=_natural())
    assert {line.pk for line in stock_take.owners(dia)} == {diamonds["round"].pk, diamonds["princess"].pk}
    assert empty.pk not in {p.pk for p in stock_take.owners(take)}


def test_saving_counts_blank_zero_and_emptied(accounts_user, shelf):
    onyx, ruby = shelf["onyx"], shelf["ruby"]
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    assert stock_take.save_counts(accounts_user, take, {onyx.pk: (19, D("12")), ruby.pk: (None, D("0"))}) == 2
    onyx_count = take.counts.get(pouch=onyx)
    assert (onyx_count.counted_pcs, onyx_count.counted_ct, onyx_count.book_pcs, onyx_count.book_ct) == (
        19, D("12"), 20, D("12.5"))
    ruby_count = take.counts.get(pouch=ruby)
    assert (ruby_count.counted_pcs, ruby_count.counted_ct, ruby_count.book_pcs) == (None, D("0"), None)
    stock_take.save_counts(accounts_user, take, {ruby.pk: (None, None)})               # the box emptied
    assert not take.counts.filter(pouch=ruby).exists()


def test_a_count_outside_the_scope_or_negative_is_refused(accounts_user, admin_user_, shelf):
    other = Batch.objects.create(code="SP14B", box_colour_id="B", family="S", cls="P", seq="14")
    far = services.open_pouch(admin_user_, other, {"pouch_no": "1"}, pcs=1, ct=D("1"), rate=None)
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    with pytest.raises(ServiceError):
        stock_take.save_counts(accounts_user, take, {far.pk: (1, D("1"))})
    with pytest.raises(ServiceError):
        stock_take.save_counts(accounts_user, take, {shelf["onyx"].pk: (None, D("-1"))})
    assert not take.counts.exists()


def test_an_unchanged_resave_keeps_the_book_it_was_counted_against(accounts_user, shelf, parties):
    onyx = shelf["onyx"]
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(accounts_user, take, {onyx.pk: (20, D("12"))})
    ledger_single.post_single(accounts_user, onyx, R.SALE, pcs=1, ct=D("1"), customer=parties["customer"])
    stock_take.save_counts(accounts_user, take, {onyx.pk: (20, D("12"))})              # the sheet saved again
    count = take.counts.get(pouch=onyx)
    assert (count.book_pcs, count.book_ct) == (20, D("12.5"))
    stock_take.save_counts(accounts_user, take, {onyx.pk: (19, D("11"))})              # a changed count
    count.refresh_from_db()
    assert (count.book_pcs, count.book_ct) == (19, D("11.5"))


def test_closing_posts_only_the_counted_differences_and_a_later_sale_stands(accounts_user, shelf, parties):
    onyx, ruby = shelf["onyx"], shelf["ruby"]
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(accounts_user, take, {onyx.pk: (21, D("12")), ruby.pk: (None, D("40"))})
    ledger_single.post_single(accounts_user, onyx, R.SALE, pcs=1, ct=D("1"), customer=parties["customer"])  # sold after counting
    stock_take.close(accounts_user, take)
    take.refresh_from_db()
    doc = take.document
    assert (take.status, doc.kind, doc.number) == (StockTake.CLOSED, StockDocument.Kind.STOCK_TAKE, "STK-000001")
    lines = sorted(((m.pcs, m.ct, m.direction) for m in doc.movements.all()), key=lambda t: t[2])
    assert lines == sorted([(1, None, Movement.IN), (None, D("0.5"), Movement.OUT)], key=lambda t: t[2])
    assert all(m.reason == R.RECOUNT_ADJUSTMENT and m.note == f"Stock take {take.number}" for m in doc.movements.all())
    assert (_held(onyx).on_pcs, _held(onyx).on_ct) == (20, D("11"))                    # 21 − 1 sold; 12 − 1 sold
    assert take.result["counted"] == 2 and take.result["total"] == 2


def test_a_close_with_no_difference_posts_nothing(accounts_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(accounts_user, take, {shelf["onyx"].pk: (20, D("12.5"))})
    before = StockDocument.objects.count()
    stock_take.close(accounts_user, take)
    take.refresh_from_db()
    assert take.status == StockTake.CLOSED and take.document is None and StockDocument.objects.count() == before
    assert take.result["counted"] == 1 and take.result["total"] == 2


def test_a_close_that_would_go_below_zero_is_refused_and_stays_open(accounts_user, shelf, parties):
    onyx = shelf["onyx"]
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(accounts_user, take, {onyx.pk: (None, D("1"))})              # book 12.5 → −11.5
    ledger_single.post_single(accounts_user, onyx, R.SALE, pcs=10, ct=D("12"), customer=parties["customer"])  # only 0.5 left
    with pytest.raises(ServiceError, match="Not enough in"):
        stock_take.close(accounts_user, take)
    take.refresh_from_db()
    assert take.status == StockTake.OPEN and take.document is None
    assert not StockDocument.objects.filter(kind=StockDocument.Kind.STOCK_TAKE).exists()


def test_a_diamond_close_posts_carats_on_a_diamond_document(accounts_user, diamonds):
    take = stock_take.start(accounts_user, StockTake.DIAMONDS, category=_natural())
    stock_take.save_counts(accounts_user, take, {diamonds["round"].pk: (5, D("3"))})   # pcs are ignored
    assert take.counts.get().counted_pcs is None
    stock_take.close(accounts_user, take)
    take.refresh_from_db()
    move = take.document.movements.get()
    assert (take.document.kind, take.document.number) == (StockDocument.Kind.DIA_COUNT, "DST-000001")
    assert (move.diamond_id, move.ct, move.direction, move.pcs) == (diamonds["round"].pk, D("0.4"), Movement.OUT, None)


def test_cancel_and_reverse(accounts_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(accounts_user, take, {shelf["onyx"].pk: (20, D("12"))})
    with pytest.raises(ServiceError):
        stock_take.reverse(accounts_user, take)                                         # still open
    stock_take.close(accounts_user, take)
    stock_take.reverse(accounts_user, take)
    take.refresh_from_db()
    assert take.document.status == StockDocument.Status.REVERSED
    assert _held(shelf["onyx"]).on_ct == D("12.5")
    with pytest.raises(ServiceError):
        stock_take.reverse(accounts_user, take)                                         # twice
    other = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    stock_take.cancel(accounts_user, other)
    other.refresh_from_db()
    assert other.status == StockTake.CANCELLED and other.document is None
    with pytest.raises(ServiceError):
        stock_take.save_counts(accounts_user, other, {shelf["onyx"].pk: (1, D("1"))})


def test_every_write_needs_the_movement_right(sales_user, accounts_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    for call in (lambda: stock_take.start(sales_user, StockTake.STONES, box_colour=BoxColour.objects.get(pk="B")),
                 lambda: stock_take.save_counts(sales_user, take, {shelf["onyx"].pk: (1, D("1"))}),
                 lambda: stock_take.close(sales_user, take), lambda: stock_take.cancel(sales_user, take),
                 lambda: stock_take.reverse(sales_user, take)):
        with pytest.raises(PermissionDenied):
            call()


# I2: a counted pouch (or diamond line) transferred or assorted out of scope must stay on the
# sheet and close normally — `owners()` always includes anything already counted.


def test_a_counted_pouch_transferred_out_of_scope_still_closes(accounts_user, admin_user_, shelf):
    other = Batch.objects.create(code="SL02R", box_colour_id="R", family="S", cls="L", seq="02")
    onyx = shelf["onyx"]
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(accounts_user, take, {onyx.pk: (20, D("12"))})           # 0.5 ct short
    ledger_assort.transfer_pouch(admin_user_, onyx, other, "9")
    assert onyx.pk in {p.pk for p in stock_take.owners(take)}                       # stays on the sheet
    stock_take.close(accounts_user, take)
    take.refresh_from_db()
    move = take.document.movements.get()
    assert (take.status, move.pcs, move.ct, move.direction) == (StockTake.CLOSED, None, D("0.5"), Movement.OUT)
    assert _held(onyx).batch_id == other.pk                                        # still re-filed, as transferred


# I3: owner's ruling — refuse the close while a counted owner has had a Recount Adjustment
# (any document, or none — a bare diamond recount) recorded after it was counted here.


def test_close_refuses_a_stale_count_recounted_since_and_a_resave_or_clear_lets_it_through(accounts_user, shelf):
    onyx = shelf["onyx"]
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(accounts_user, take, {onyx.pk: (20, D("12"))})           # 0.5 ct short
    ledger_single.post_recount(accounts_user, onyx, None, D("12"))                  # same shortfall, one pouch
    with pytest.raises(ServiceError, match="was recounted since it was counted here"):
        stock_take.close(accounts_user, take)
    take.refresh_from_db()
    assert take.status == StockTake.OPEN and take.document is None
    stock_take.save_counts(accounts_user, take, {onyx.pk: (None, None)})            # clearing it lets the close through
    stock_take.close(accounts_user, take)
    take.refresh_from_db()
    assert take.status == StockTake.CLOSED and take.document is None               # nothing left to post


def test_close_refuses_a_diamond_line_recounted_since_and_a_resave_lets_it_through(accounts_user, diamonds):
    round_ = diamonds["round"]
    take = stock_take.start(accounts_user, StockTake.DIAMONDS, category=_natural())
    stock_take.save_counts(accounts_user, take, {round_.pk: (None, D("3"))})        # 0.4 ct short
    dia_services.recount_line(accounts_user, round_, D("3"))                        # a bare recount, no document
    with pytest.raises(ServiceError, match="was recounted since it was counted here"):
        stock_take.close(accounts_user, take)
    take.refresh_from_db()
    assert take.status == StockTake.OPEN
    stock_take.save_counts(accounts_user, take, {round_.pk: (None, D("3.4"))})       # a changed re-save stamps a fresh counted_at
    stock_take.close(accounts_user, take)
    take.refresh_from_db()
    assert take.status == StockTake.CLOSED


def test_close_refuses_a_backdated_recount_since_even_though_it_occurred_before_the_count(accounts_user, shelf):
    onyx = shelf["onyx"]
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(accounts_user, take, {onyx.pk: (20, D("12"))})           # 0.5 ct short
    yesterday = timezone.localdate() - timedelta(days=1)
    ledger_single.post_recount(accounts_user, onyx, None, D("12"), occurred_on=yesterday)
    with pytest.raises(ServiceError, match="was recounted since it was counted here"):
        stock_take.close(accounts_user, take)
