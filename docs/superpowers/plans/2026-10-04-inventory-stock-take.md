# Inventory Stock Take (part 5d) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Count a box colour or a batch of stones, or a category of diamonds, over one or more sessions, and on close post every counted difference as Recount Adjustments on one document.

**Architecture:** Two new models (`StockTake`, `StockTakeCount`) and two new document kinds, driven by one service module `inventory/stock_take.py` (start / owners / save_counts / close / cancel / reverse) that posts through the existing ledger engine. One view module serves both sides (stones in the stones shell, diamonds through `dia_page` with the admin preview), sharing row building and actions.

**Tech Stack:** Django 5.2, Postgres, pytest-django; server-rendered templates; no new CSS.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-04-inventory-stock-take-design.md` — binding.
- Numbers: stock takes `ST-000001` (one sequence across both sides). Document kinds `STOCK_TAKE = "stock_take", "Stock take"` (stones, `STK-`, in `STONE_KINDS`) and `DIA_COUNT = "dia_count", "Diamond stock take"` (diamonds, `DST-`, in `DIAMOND_KINDS`); `RIGHT_FOR_KIND` = `INV_MOVE` for both.
- Scope: stones — exactly one of a box colour or a batch; diamonds — a category (`DiamondTerm` of kind `category`). Overlap refusal: "{number} is already counting {scope}; close or cancel it first." (box colour ↔ any batch in it; same box colour; same batch; same category).
- Sheet rows: everything in scope with something on hand, plus anything already counted in this stock take.
- Counts: blank = not counted; 0 is a count. A row saved with a changed count stores counted and book-at-count; unchanged keeps its book; emptied removes the count. Pieces are never stored for an uncountable pouch or a diamond line.
- Close: one document with a Recount Adjustment line per counted difference, pcs and ct as separate lines, direction by sign, quantity the absolute difference, note "Stock take ST-…"; no differences → closes with no document; the ledger's "Not enough in …" refusal refuses the close and leaves it open. Frozen `result` JSON on close and cancel.
- Reverse: only a closed stock take with a document not already reversed; through `ledger.reverse_document`.
- Rights: start, save, close, cancel, reverse need `INV_MOVE` → 403. Every internal role may read.
- Client view: every stones stock-take URL redirects to `inventory:shelf` first (GET and POST). Diamond pages honour `?as=` (admin preview): mask as the role and hide every form.
- Masking: rows through `stock.masking.mask()`; variance value under the gated key `cost_amount` (view_cost); templates test key presence.
- Padlocks off: stones rail **Stock takes**, stones tab **Stock take**, diamonds tab **Stock take**. Five existing assertions that pin these padlocks are rewritten (approved): `test_dia_purchase_view.py:105`, `test_dia_wiring.py:76`, `test_finders_rail.py:23` and `:36`, `test_ledger_lists.py:72`. Client lookbook stays padlocked.
- No CSS, no change under `stock/` or `crm/`, no stock/CRM coupling. One migration (`0010_stock_take`).
- Tests: `POSTGRES_DB=<private> ../nornament-app/.venv/bin/pytest … -p no:warnings -q --junit-xml=<file>`; run long suites in the background and poll the XML until finished; don't hand back mid-run. Known unrelated whole-suite failure: `stock/tests/test_import_commit.py::test_images_are_attached_in_chunks_and_are_resumable`.
- Commit messages: plain English, ending `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

---

## File structure

- Modify `inventory/models.py` — two kinds; `StockTake`, `StockTakeCount`.
- Create `inventory/migrations/0010_stock_take.py` (generated).
- Modify `inventory/ledger.py` — `STONE_KINDS`, `DIAMOND_KINDS`, `RIGHT_FOR_KIND`, `PREFIX`.
- Create `inventory/stock_take.py` — the service.
- Create `inventory/tests/test_stock_take.py` — service tests (Task 1).
- Create `inventory/views_stock_take.py`; templates `inventory/stock_takes.html`, `inventory/stock_take.html` (stones), `inventory/diamonds/stock_takes.html`, `inventory/diamonds/stock_take.html`; modify `inventory/urls.py`, `_rail.html`, `templates/inventory_base.html`, `inventory/views_dia_movements.py` (`opens`).
- Create `inventory/tests/test_stock_take_views.py`; modify `inventory/tests/test_masking.py` and the five padlock assertions.

---

### Task 1: Models, kinds and the stock-take service

**Files:**
- Modify: `inventory/models.py` (Kind: after `MERGE`, `STOCK_TAKE`; after `DIA_PURCHASE`, `DIA_COUNT`; new models at the end)
- Create: `inventory/migrations/0010_stock_take.py`
- Modify: `inventory/ledger.py:31-50`
- Create: `inventory/stock_take.py`
- Test: `inventory/tests/test_stock_take.py`

**Interfaces:**
- Produces (Tasks 2–3 rely on these):
  - `StockTake` with `STONES`, `DIAMONDS`, `OPEN`, `CLOSED`, `CANCELLED`; fields per the spec; `document` is a `OneToOneField(StockDocument, null=True, related_name="stock_take")`.
  - `StockTakeCount` with `stock_take` (`related_name="counts"`), `pouch`, `diamond`, `counted_pcs`, `counted_ct`, `book_pcs`, `book_ct`, `counted_by`, `counted_at`.
  - `stock_take.scope_label(take) -> str` — "Box colour G · Green", "Batch SL01G", "Natural Diamond".
  - `stock_take.start(user, side, box_colour=None, batch=None, category=None, note="") -> StockTake`
  - `stock_take.owners(take) -> list[Pouch | DiamondLine]` — stocked owners (pouches carry `on_pcs`, `on_ct`, `rate`; lines `on_ct`, `own_cost`), scope with stock plus counted, in `stocked` order.
  - `stock_take.save_counts(user, take, entries: dict[int, tuple[int | None, Decimal | None]]) -> int` — owner pk → (pcs, ct); returns the number of counts stored or removed.
  - `stock_take.close(user, take) -> StockTake`, `stock_take.cancel(user, take) -> StockTake`, `stock_take.reverse(user, take) -> StockDocument`.
  - `stock_take.variances(count) -> (var_pcs | None, var_ct | None)`.

- [ ] **Step 1: Write the failing tests**

Create `inventory/tests/test_stock_take.py`:

```python
"""Part 5d: stock takes — counting a box colour, a batch or a diamond category, and posting the differences."""
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import ledger, ledger_single, services, stock_take
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


def test_an_unchanged_resave_keeps_the_book_it_was_counted_against(accounts_user, shelf):
    onyx = shelf["onyx"]
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(accounts_user, take, {onyx.pk: (20, D("12"))})
    ledger_single.post_single(accounts_user, onyx, R.SALE, pcs=1, ct=D("1"))
    stock_take.save_counts(accounts_user, take, {onyx.pk: (20, D("12"))})              # the sheet saved again
    count = take.counts.get(pouch=onyx)
    assert (count.book_pcs, count.book_ct) == (20, D("12.5"))
    stock_take.save_counts(accounts_user, take, {onyx.pk: (19, D("11"))})              # a changed count
    count.refresh_from_db()
    assert (count.book_pcs, count.book_ct) == (19, D("11.5"))


def test_closing_posts_only_the_counted_differences_and_a_later_sale_stands(accounts_user, shelf):
    onyx, ruby = shelf["onyx"], shelf["ruby"]
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(accounts_user, take, {onyx.pk: (21, D("12")), ruby.pk: (None, D("40"))})
    ledger_single.post_single(accounts_user, onyx, R.SALE, pcs=1, ct=D("1"))           # sold after counting
    stock_take.close(accounts_user, take)
    take.refresh_from_db()
    doc = take.document
    assert (take.status, doc.kind, doc.number) == (StockTake.CLOSED, StockDocument.Kind.STOCK_TAKE, "STK-000001")
    lines = sorted((m.pcs, m.ct, m.direction) for m in doc.movements.all())
    assert lines == sorted([(1, None, Movement.IN), (None, D("0.5"), Movement.OUT)])   # ruby matched: no line
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


def test_a_close_that_would_go_below_zero_is_refused_and_stays_open(accounts_user, shelf):
    onyx = shelf["onyx"]
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(accounts_user, take, {onyx.pk: (None, D("1"))})              # book 12.5 → −11.5
    ledger_single.post_single(accounts_user, onyx, R.SALE, pcs=10, ct=D("12"))         # only 0.5 left
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
```

Before writing these, read `ledger_single.post_single`'s real signature and the diamond fixture's category terms in `inventory/tests/conftest.py`; adjust the calls (not the behaviour) to match, and note it in the report.

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=st_t1 ../nornament-app/.venv/bin/pytest inventory/tests/test_stock_take.py -p no:warnings -q`
Expected: FAIL — `ImportError: cannot import name 'stock_take'`.

- [ ] **Step 3: Models, kinds, migration**

In `inventory/models.py`, `StockDocument.Kind`: after `MERGE`, `STOCK_TAKE = "stock_take", "Stock take"`; after `DIA_PURCHASE`, `DIA_COUNT = "dia_count", "Diamond stock take"`. At the end of the file:

```python
class StockTake(models.Model):
    """A count of one box colour or batch of stones, or one category of diamonds (part 5d).

    Each count keeps the book figure it was taken against; closing posts counted − book as
    Recount Adjustments on one document and freezes ``result``. Never recomputed after."""

    STONES, DIAMONDS = "stones", "diamonds"
    SIDES = [(STONES, "Stones"), (DIAMONDS, "Diamonds")]
    OPEN, CLOSED, CANCELLED = "open", "closed", "cancelled"
    STATUSES = [(OPEN, "Open"), (CLOSED, "Closed"), (CANCELLED, "Cancelled")]

    number = models.CharField(max_length=12, unique=True)
    side = models.CharField(max_length=8, choices=SIDES)
    box_colour = models.ForeignKey(BoxColour, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    category = models.ForeignKey(DiamondTerm, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=STATUSES, default=OPEN)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    started_at = models.DateTimeField(default=timezone.now)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    document = models.OneToOneField(StockDocument, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="stock_take")
    result = models.JSONField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        db_table = "inv_stock_take"
        ordering = ["-started_at", "-pk"]

    def __str__(self):
        return self.number


class StockTakeCount(models.Model):
    stock_take = models.ForeignKey(StockTake, on_delete=models.CASCADE, related_name="counts")
    pouch = models.ForeignKey(Pouch, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    diamond = models.ForeignKey(DiamondLine, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    counted_pcs = models.PositiveIntegerField(null=True, blank=True)
    counted_ct = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    book_pcs = models.PositiveIntegerField(null=True, blank=True)
    book_ct = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    counted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    counted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_stock_take_count"
        constraints = [
            models.UniqueConstraint(fields=["stock_take", "pouch"], condition=Q(pouch__isnull=False),
                                    name="inv_stock_take_count_pouch"),
            models.UniqueConstraint(fields=["stock_take", "diamond"], condition=Q(diamond__isnull=False),
                                    name="inv_stock_take_count_diamond"),
            models.CheckConstraint(condition=Q(pouch__isnull=True) ^ Q(diamond__isnull=True),
                                   name="inv_stock_take_count_one_owner"),
        ]
```

(If this Django version spells it `check=` rather than `condition=` for `CheckConstraint`, use the spelling the other constraints in this file use.)

Run `../nornament-app/.venv/bin/python manage.py makemigrations inventory --name stock_take` → `0010_stock_take.py`.

In `inventory/ledger.py`: `STONE_KINDS` gains `Kind.STOCK_TAKE`; `DIAMOND_KINDS` gains `Kind.DIA_COUNT`; `RIGHT_FOR_KIND` gains both → `INV_MOVE`; `PREFIX` gains `Kind.STOCK_TAKE: "STK-"`, `Kind.DIA_COUNT: "DST-"`.

- [ ] **Step 4: The service**

Create `inventory/stock_take.py`:

```python
"""Stock takes (part 5d): count a box colour or a batch of stones, or a category of diamonds, and post the
differences as Recount Adjustments on one document when it closes.

A count keeps the book figure it was taken against, so stone sold after its pouch was counted is not undone
by the recount: what posts is counted − book-at-count (owner, 2026-10-04)."""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.capabilities import INV_MOVE
from stock.services import ServiceError, log, require

from . import dia_services, ledger, services
from .models import BoxColour, DiamondLine, DiamondTerm, Movement, Pouch, StockDocument, StockTake

Kind = StockDocument.Kind
RIGHT = "Only a role that records stock movements can take stock."


def _by(user):
    return user if getattr(user, "is_authenticated", False) else None


def scope_label(take):
    if take.side == StockTake.DIAMONDS:
        return take.category.value
    if take.box_colour_id:
        return f"Box colour {take.box_colour.code} · {take.box_colour.label}"
    return f"Batch {take.batch.code}"


def _next_number():
    # ponytail: read-the-max under the caller's transaction; the unique number catches a race
    last = (StockTake.objects.filter(number__regex=r"^ST-[0-9]{6}$").order_by("-number")
            .values_list("number", flat=True).first())
    return f"ST-{(int(last[3:]) if last else 0) + 1:06d}"


def _overlap(side, box_colour, batch, category):
    open_ = StockTake.objects.filter(side=side, status=StockTake.OPEN)
    if side == StockTake.DIAMONDS:
        return open_.filter(category=category).first()
    if box_colour is not None:
        return open_.filter(Q(box_colour=box_colour) | Q(batch__box_colour=box_colour)).first()
    return open_.filter(Q(batch=batch) | Q(box_colour_id=batch.box_colour_id)).first()


@transaction.atomic
def start(user, side, box_colour=None, batch=None, category=None, note=""):
    require(user, INV_MOVE, RIGHT)
    if side == StockTake.STONES:
        if (box_colour is None) == (batch is None):
            raise ServiceError("Choose a box colour or a batch to count — one of them.")
        # serialise starts on the same colour, so two overlapping counts cannot open at once
        BoxColour.objects.select_for_update().get(pk=box_colour.pk if box_colour else batch.box_colour_id)
    elif side == StockTake.DIAMONDS:
        if category is None:
            raise ServiceError("Choose the category to count.")
        DiamondTerm.objects.select_for_update().get(pk=category.pk)
    else:
        raise ServiceError(f"{side} is not a side of the inventory.")
    other = _overlap(side, box_colour, batch, category)
    if other:
        raise ServiceError(f"{other.number} is already counting {scope_label(other)}; close or cancel it first.")
    take = StockTake.objects.create(number=_next_number(), side=side, box_colour=box_colour, batch=batch,
                                    category=category, started_by=_by(user), note=note)
    log(user, "INSERT", "inv_stock_take", take.pk, f"{take.number} started: {scope_label(take)}")
    return take


def owners(take):
    """What the sheet lists: everything in scope with something on hand, plus anything already counted."""
    counted = {c.pouch_id or c.diamond_id for c in take.counts.all()}
    if take.side == StockTake.DIAMONDS:
        lines = dia_services.stocked_lines(DiamondLine.objects.filter(category=take.category))
        return [line for line in lines if line.on_ct or line.pk in counted]
    scope = Pouch.objects.filter(batch=take.batch) if take.batch_id else Pouch.objects.filter(batch__box_colour=take.box_colour)
    return [p for p in services.stocked(scope) if p.on_ct or p.on_pcs or p.pk in counted]


def _open(take):
    take = StockTake.objects.select_for_update().get(pk=take.pk)
    if take.status != StockTake.OPEN:
        raise ServiceError(f"{take.number} is {take.get_status_display().lower()}; it takes no more counts.")
    return take


def _field(take):
    return "diamond" if take.side == StockTake.DIAMONDS else "pouch"


@transaction.atomic
def save_counts(user, take, entries):
    """Store each counted (pcs, ct), owner pk → figures. (None, None) removes a count. A changed count
    stores the book of that moment; an unchanged one keeps the book it was counted against."""
    require(user, INV_MOVE, RIGHT)
    take = _open(take)
    held = {o.pk: o for o in owners(take)}
    field, done = _field(take), 0
    for pk, (pcs, ct) in entries.items():
        owner = held.get(pk)
        if owner is None:
            raise ServiceError("That is not in this stock take's scope.")
        if take.side == StockTake.DIAMONDS or not owner.countable:
            pcs = None
        if (pcs is not None and pcs < 0) or (ct is not None and ct < 0):
            raise ServiceError("A count cannot be negative.")
        existing = take.counts.filter(**{field: owner}).first()
        if pcs is None and ct is None:
            if existing:
                existing.delete()
                done += 1
            continue
        if existing and (existing.counted_pcs, existing.counted_ct) == (pcs, ct):
            continue
        book_pcs = None if pcs is None else (getattr(owner, "on_pcs", None) or 0)
        take.counts.update_or_create(**{field: owner}, defaults={
            "counted_pcs": pcs, "counted_ct": ct, "book_pcs": book_pcs, "book_ct": owner.on_ct or ledger.ZERO,
            "counted_by": _by(user), "counted_at": timezone.now()})
        done += 1
    return done


def variances(count):
    var_pcs = None if count.counted_pcs is None else count.counted_pcs - (count.book_pcs or 0)
    var_ct = None if count.counted_ct is None else count.counted_ct - (count.book_ct or ledger.ZERO)
    return var_pcs, var_ct


def _frozen(take):
    counts = {c.pouch_id or c.diamond_id: c for c in take.counts.all()}
    rows = []
    for owner in owners(take):
        c = counts.get(owner.pk)
        var_pcs, var_ct = variances(c) if c else (None, None)
        rows.append({"pk": owner.pk, "ref": owner.ref, "label": str(owner),
                     "book_pcs": c.book_pcs if c else getattr(owner, "on_pcs", None),
                     "book_ct": str(c.book_ct if c else (owner.on_ct or ledger.ZERO)),
                     "counted_pcs": c.counted_pcs if c else None,
                     "counted_ct": None if not c or c.counted_ct is None else str(c.counted_ct),
                     "var_pcs": var_pcs, "var_ct": None if var_ct is None else str(var_ct)})
    return {"rows": rows, "counted": len(counts), "total": len(rows)}


@transaction.atomic
def close(user, take):
    require(user, INV_MOVE, RIGHT)
    take = _open(take)
    by_pk = {o.pk: o for o in owners(take)}
    lines = []
    for count in take.counts.order_by("pk"):
        owner = by_pk[count.pouch_id or count.diamond_id]
        for field, delta in zip(("pcs", "ct"), variances(count)):
            if delta:
                lines.append(ledger.Line(owner, Movement.Reason.RECOUNT_ADJUSTMENT,
                                         Movement.IN if delta > 0 else Movement.OUT,
                                         note=f"Stock take {take.number}", **{field: abs(delta)}))
    if lines:
        kind = Kind.DIA_COUNT if take.side == StockTake.DIAMONDS else Kind.STOCK_TAKE
        take.document = ledger.open_document(user, kind, note=f"Stock take {take.number}")
        ledger.post(user, take.document, lines)
    take.result = _frozen(take)
    take.status, take.closed_by, take.closed_at = StockTake.CLOSED, _by(user), timezone.now()
    take.save(update_fields=["document", "result", "status", "closed_by", "closed_at"])
    log(user, "UPDATE", "inv_stock_take", take.pk, f"{take.number} closed: {len(lines)} adjustment(s)")
    return take


@transaction.atomic
def cancel(user, take):
    require(user, INV_MOVE, RIGHT)
    take = _open(take)
    take.result = _frozen(take)
    take.status, take.closed_by, take.closed_at = StockTake.CANCELLED, _by(user), timezone.now()
    take.save(update_fields=["result", "status", "closed_by", "closed_at"])
    log(user, "UPDATE", "inv_stock_take", take.pk, f"{take.number} cancelled")
    return take


@transaction.atomic
def reverse(user, take):
    require(user, INV_MOVE, RIGHT)
    take = StockTake.objects.select_for_update().get(pk=take.pk)
    if take.status != StockTake.CLOSED or take.document_id is None:
        raise ServiceError(f"{take.number} posted nothing, so there is nothing to reverse.")
    return ledger.reverse_document(user, take.document)
```

`str(owner)` gives "SL01G · 1" for a pouch and "{ref} {code}" for a diamond line. A pouch's `pk` and a line's `pk` never meet: a stock take holds one side only.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=st_t1 ../nornament-app/.venv/bin/pytest inventory/tests/test_stock_take.py -p no:warnings -q`
Expected: PASS. Then `../nornament-app/.venv/bin/python manage.py makemigrations --check --dry-run` → "No changes detected".

- [ ] **Step 6: Run inventory + accounts** (background, poll the XML until finished)

Run: `POSTGRES_DB=st_t1 ../nornament-app/.venv/bin/pytest inventory accounts -p no:warnings -q --junit-xml=/tmp/st_t1.xml`
Expected: 0 failures, 0 errors.

- [ ] **Step 7: Commit**

```bash
git add inventory/models.py inventory/migrations/0010_stock_take.py inventory/ledger.py inventory/stock_take.py \
        inventory/tests/test_stock_take.py
git commit -m "Stock takes count a box colour, a batch or a diamond category and post the counted differences on close

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The stones stock-take screens and the padlocks off

**Files:**
- Create: `inventory/views_stock_take.py` (shared helpers + stones views)
- Create: `inventory/templates/inventory/stock_takes.html`, `inventory/templates/inventory/stock_take.html`
- Create: `inventory/templates/inventory/_stock_sheet.html` (the count table both sides include)
- Modify: `inventory/urls.py`; `inventory/templates/inventory/_rail.html:22`; `templates/inventory_base.html:74` (stones tab)
- Modify (approved rewrites): `inventory/tests/test_finders_rail.py:23`, `inventory/tests/test_ledger_lists.py:72`
- Test: `inventory/tests/test_stock_take_views.py` (create); `inventory/tests/test_masking.py`

**Interfaces:**
- Consumes: Task 1's `stock_take.*`, `StockTake`.
- Produces (Task 3 reuses): in `views_stock_take.py` — `_sheet_rows(user, take) -> list[dict]` (masked; keys `pk`, `ref`, `label`, `stone`, `size`, `countable`, `book_pcs`, `book_ct`, `counted_pcs`, `counted_ct`, `var_pcs`, `var_ct`, `cost_amount`), `_totals(rows) -> dict` (`counted`, `total`, `var_ct`, `cost_amount` when present), `_act(request, take, entries) -> tuple[redirect | None, error, confirming]` handling `action` ∈ save / close / cancel / reverse with `confirm=1`, `_entries(post, rows)`. Template `inventory/_stock_sheet.html` taking `rows`, `totals`, `editable`, `diamonds`.

- [ ] **Step 1: Write the failing tests**

Create `inventory/tests/test_stock_take_views.py`:

```python
"""Part 5d: the stock-take screens."""
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import stock_take
from inventory.models import StockDocument, StockTake

pytestmark = pytest.mark.django_db
D = Decimal
LIST = reverse("inventory:stock_takes")


def _sheet(take):
    return reverse("inventory:stock_take", args=[take.pk])


def test_the_rail_and_the_tab_open_the_list(client, sales_user, shelf):
    client.force_login(sales_user)
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert f'href="{LIST}"' in body and 'Stock takes<span class="ct">🔒' not in body and "Stock take 🔒" not in body
    assert 'Client lookbook<span class="ct">🔒' in body


def test_starting_from_the_list_opens_the_sheet(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(LIST).content.decode()
    assert "Start a stock take" in body and 'name="box_colour"' in body and 'name="batch"' in body
    response = client.post(LIST, {"batch": shelf["batch"].code})
    take = StockTake.objects.get()
    assert response.status_code == 302 and response["Location"] == _sheet(take)
    body = client.get(LIST).content.decode()
    assert take.number in body and "Batch SL01G" in body and "Open" in body


def test_an_overlap_comes_back_on_the_list(client, accounts_user, shelf):
    client.force_login(accounts_user)
    client.post(LIST, {"box_colour": "G"})
    body = client.post(LIST, {"batch": shelf["batch"].code}).content.decode()
    assert "ST-000001 is already counting Box colour G" in body and StockTake.objects.count() == 1


def test_the_sheet_saves_counts_and_shows_the_variance_and_its_value(client, accounts_user, sales_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    client.force_login(accounts_user)
    onyx = shelf["onyx"]
    response = client.post(_sheet(take), {"action": "save", f"pcs_{onyx.pk}": "20", f"ct_{onyx.pk}": "10.5",
                                          f"pcs_{shelf['ruby'].pk}": "", f"ct_{shelf['ruby'].pk}": ""})
    assert response.status_code == 302
    body = client.get(_sheet(take)).content.decode()
    assert 'value="10.5' in body
    assert "−2.00" in body or "-2.00" in body                     # whichever sign the ct filter prints
    assert "15,838" in body                                       # 2 ct × ₹7,919, to the cost right
    assert "Counted 1 of 2" in body
    client.force_login(sales_user)
    body = client.get(_sheet(take)).content.decode()
    assert "15,838" not in body and "Save counts" not in body     # read-only, no money


def test_close_needs_a_second_press_then_posts(client, accounts_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    client.force_login(accounts_user)
    onyx = shelf["onyx"]
    first = client.post(_sheet(take), {"action": "close", f"pcs_{onyx.pk}": "20", f"ct_{onyx.pk}": "12"})
    assert first.status_code == 200 and "Yes, close and post" in first.content.decode()
    take.refresh_from_db()
    assert take.status == StockTake.OPEN and take.counts.count() == 1        # the counts were saved
    second = client.post(_sheet(take), {"action": "close", "confirm": "1", f"pcs_{onyx.pk}": "20", f"ct_{onyx.pk}": "12"})
    take.refresh_from_db()
    assert second.status_code == 302 and take.status == StockTake.CLOSED
    body = client.get(_sheet(take)).content.decode()
    assert "Closed" in body and take.document.number in body
    assert f'href="{reverse("inventory:document", args=[take.document.pk])}"' in body and "Save counts" not in body


def test_cancel_and_reverse_from_the_sheet(client, accounts_user, shelf):
    client.force_login(accounts_user)
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(accounts_user, take, {shelf["onyx"].pk: (20, D("12"))})
    stock_take.close(accounts_user, take)
    client.post(_sheet(take), {"action": "reverse", "confirm": "1"})
    take.refresh_from_db()
    assert take.document.status == StockDocument.Status.REVERSED
    assert "Reversed" in client.get(_sheet(take)).content.decode()
    other = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    client.post(_sheet(other), {"action": "cancel", "confirm": "1"})
    other.refresh_from_db()
    assert other.status == StockTake.CANCELLED


def test_rights_and_client_view(client, sales_user, admin_user_, accounts_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    client.force_login(sales_user)
    assert client.get(LIST).status_code == 200 and "Start a stock take" not in client.get(LIST).content.decode()
    assert client.post(LIST, {"box_colour": "B"}).status_code == 403
    assert client.post(_sheet(take), {"action": "save"}).status_code == 403
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    for response in (client.get(LIST), client.get(_sheet(take)), client.post(_sheet(take), {"action": "save"})):
        assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf")


def test_a_diamond_stock_take_is_not_a_stones_page(client, accounts_user, diamonds):
    from inventory.models import DiamondTerm

    take = stock_take.start(accounts_user, StockTake.DIAMONDS,
                            category=DiamondTerm.objects.get(kind="category", value="Natural Diamond"))
    client.force_login(accounts_user)
    assert client.get(_sheet(take)).status_code == 404
```

Approved padlock rewrites:
- `test_finders_rail.py:23`: `'Stock takes<span class="ct">🔒' in body` → `f'href="{reverse("inventory:stock_takes")}"' in body`.
- `test_ledger_lists.py:72`: the same replacement.

In `inventory/tests/test_masking.py` add:

```python
#: part 5d's stock-take screens, walked by test_no_stock_take_screen_shows_a_login_what_it_may_not_see
STOCK_TAKE_SCREENS = {"inventory:stock_takes", "inventory:stock_take"}


@pytest.fixture
def counted(admin_user_, shelf):
    from decimal import Decimal

    from inventory import stock_take
    from inventory.models import StockTake

    take = stock_take.start(admin_user_, StockTake.STONES, batch=shelf["batch"])
    stock_take.save_counts(admin_user_, take, {shelf["onyx"].pk: (20, Decimal("10.5"))})   # −2 ct × ₹7,919
    return take


@pytest.mark.parametrize("fixture", ["sales_user", "karigar_user", "production_user", "graphic_user"])
def test_no_stock_take_screen_shows_a_login_what_it_may_not_see(client, counted, request, fixture):
    client.force_login(request.getfixturevalue(fixture))
    for url in (reverse("inventory:stock_takes"), reverse("inventory:stock_take", args=[counted.pk])):
        response = client.get(url)
        assert response.status_code == 200, url
        assert "15,838" not in response.content.decode(), f"{url} leaked the variance value to {fixture}"


def test_accounts_sees_the_variance_value(client, accounts_user, counted):
    client.force_login(accounts_user)
    assert "15,838" in client.get(reverse("inventory:stock_take", args=[counted.pk])).content.decode()
```

and add `| STOCK_TAKE_SCREENS` to `covered` in `test_every_inventory_screen_is_walked`.

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=st_t2 ../nornament-app/.venv/bin/pytest inventory/tests/test_stock_take_views.py inventory/tests/test_masking.py -p no:warnings -q`
Expected: FAIL — `NoReverseMatch` for `inventory:stock_takes`.

- [ ] **Step 3: The views**

Create `inventory/views_stock_take.py`:

```python
"""The stock-take screens (part 5d): the list with its start form, and the count sheet.

Stones render in the stones shell and are never reachable in client view; diamonds render through
``dia_page`` and honour the admin preview, which masks as the role and hides every form."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect

from accounts.capabilities import INV_MOVE
from stock.masking import mask
from stock.services import ServiceError, require

from . import dia_services, inputs, ledger, stock_take
from .models import Batch, BoxColour, StockDocument, StockTake
from .views import _client, _everything, _page

CONFIRM = {"close": "Close and post the counted differences?", "cancel": "Cancel this stock take? Nothing is posted.",
           "reverse": "Reverse the recount this stock take posted?"}


def _sheet_rows(user, take):
    """One masked row per owner on the sheet: book at count for a counted row, live book otherwise."""
    counts = {c.pouch_id or c.diamond_id: c for c in take.counts.all()}
    rates = dia_services.rate_table() if take.side == StockTake.DIAMONDS else None
    rows = []
    for owner in stock_take.owners(take):
        c = counts.get(owner.pk)
        var_pcs, var_ct = stock_take.variances(c) if c else (None, None)
        if rates is not None:
            rate = dia_services.price(owner, rates)[0]
            stone = " · ".join(v for v in (owner.shape and owner.shape.value, owner.colour and owner.colour.value,
                                           owner.code.clarity and owner.code.clarity.value) if v)
            countable, label = False, f"{owner.ref} · {owner.code.item_code}"
        else:
            rate, stone, countable, label = owner.rate, owner.stone_name, owner.countable, str(owner)
        rows.append(mask(user, {
            "pk": owner.pk, "ref": owner.ref, "label": label, "stone": stone, "size": owner.size_text,
            "countable": countable,
            "book_pcs": c.book_pcs if c and c.counted_pcs is not None else (owner.on_pcs if countable else None),
            "book_ct": c.book_ct if c else (owner.on_ct or ledger.ZERO),
            "counted_pcs": c.counted_pcs if c else None, "counted_ct": c.counted_ct if c else None,
            "var_pcs": var_pcs, "var_ct": var_ct,
            "cost_amount": var_ct * rate if var_ct is not None and rate is not None else None,
        }))
    return rows


def _frozen_rows(user, take):
    """A closed or cancelled stock take reads its frozen result: quantities only, never recomputed (no money:
    the value of a variance belongs to the day it was counted)."""
    from decimal import Decimal

    rows = []
    for r in (take.result or {}).get("rows", []):
        dec = {k: (Decimal(r[k]) if r.get(k) is not None else None) for k in ("book_ct", "counted_ct", "var_ct")}
        rows.append({**r, **dec, "stone": "", "size": "", "countable": r.get("book_pcs") is not None})
    return rows


def _totals(rows):
    out = {"counted": sum(1 for r in rows if r["counted_pcs"] is not None or r["counted_ct"] is not None),
           "total": len(rows), "var_ct": sum((r["var_ct"] for r in rows if r["var_ct"] is not None), ledger.ZERO)}
    if rows and "cost_amount" in rows[0]:
        out["cost_amount"] = sum((r["cost_amount"] for r in rows if r.get("cost_amount") is not None), ledger.ZERO)
    return out


def _entries(post, rows):
    return {r["pk"]: (inputs.whole(post.get(f"pcs_{r['pk']}"), "Pieces"), inputs.decimal(post.get(f"ct_{r['pk']}"), "Carats"))
            for r in rows if f"ct_{r['pk']}" in post or f"pcs_{r['pk']}" in post}


def _act(request, take, rows):
    """Handle a POST on the sheet. Returns (redirect or None, error, confirming)."""
    require(request.user, INV_MOVE, stock_take.RIGHT)
    action = request.POST.get("action")
    try:
        entries = _entries(request.POST, rows)
        if entries and take.status == StockTake.OPEN:
            stock_take.save_counts(request.user, take, entries)
        if action in CONFIRM and request.POST.get("confirm") != "1":
            return None, None, action
        if action == "close":
            stock_take.close(request.user, take)
            messages.success(request, f"{take.number} closed.")
        elif action == "cancel":
            stock_take.cancel(request.user, take)
            messages.success(request, f"{take.number} cancelled.")
        elif action == "reverse":
            reversal = stock_take.reverse(request.user, take)
            messages.success(request, f"{take.number}'s recount reversed by {reversal.number}.")
        else:
            messages.success(request, "Counts saved.")
    except ServiceError as refused:
        return None, refused.messages[0], None
    return redirect(request.path), None, None


def _context(user, take):
    rows = _sheet_rows(user, take) if take.status == StockTake.OPEN else _frozen_rows(user, take)
    reversed_ = bool(take.document_id and take.document.status == StockDocument.Status.REVERSED)
    return {"take": take, "scope": stock_take.scope_label(take), "rows": rows, "totals": _totals(rows),
            "reversed": reversed_}


@login_required
def stock_takes(request):
    if _client(request):
        return redirect("inventory:shelf")
    error = None
    if request.method == "POST":
        require(request.user, INV_MOVE, stock_take.RIGHT)
        colour = request.POST.get("box_colour") or ""
        batch = request.POST.get("batch") or ""
        try:
            take = stock_take.start(request.user, StockTake.STONES,
                                    box_colour=BoxColour.objects.filter(pk=colour).first() if colour else None,
                                    batch=Batch.objects.filter(code=batch).first() if batch else None)
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            return redirect("inventory:stock_take", pk=take.pk)
    takes = StockTake.objects.filter(side=StockTake.STONES).select_related("box_colour", "batch", "started_by",
                                                                             "closed_by", "document")
    return _page(request, "inventory/stock_takes.html", _everything(request), tab="stock_take", error=error,
                 takes=_listed(takes), colours=BoxColour.objects.all(), batches=Batch.objects.order_by("code"),
                 may=request.user.has_perm(INV_MOVE))


def _listed(takes):
    from django.db.models import Count

    order = {StockTake.OPEN: 0}
    rows = [{"take": t, "scope": stock_take.scope_label(t), "counted": t.n}
            for t in takes.annotate(n=Count("counts"))]
    return sorted(rows, key=lambda r: (order.get(r["take"].status, 1), -r["take"].started_at.timestamp()))


@login_required
def stock_take_sheet(request, pk):
    if _client(request):
        return redirect("inventory:shelf")
    take = get_object_or_404(StockTake.objects.select_related("box_colour", "batch", "document"), pk=pk,
                             side=StockTake.STONES)
    error = confirming = None
    if request.method == "POST":
        done, error, confirming = _act(request, take, _sheet_rows(request.user, take))
        if done:
            return done
        take.refresh_from_db()
    may = request.user.has_perm(INV_MOVE)
    return _page(request, "inventory/stock_take.html", _everything(request), tab="stock_take",
                 error=error, confirming=confirming, confirm_message=CONFIRM.get(confirming), may=may,
                 previewing=False, editable=take.status == StockTake.OPEN and may, **_context(request.user, take))
```

In `inventory/urls.py`, import `views_stock_take` and add:

```python
    path("stock-takes/", views_stock_take.stock_takes, name="stock_takes"),
    path("stock-takes/<int:pk>/", views_stock_take.stock_take_sheet, name="stock_take"),
```

- [ ] **Step 4: Templates, rail and tab**

`inventory/templates/inventory/_stock_sheet.html` (the count table; `editable` = open and may and not previewing):

```html
{% load inventory_extras %}<div style="overflow:auto"><table class="led">
  <thead><tr><th>{% if diamonds %}Line{% else %}Pouch{% endif %}</th><th>{% if diamonds %}Diamond{% else %}Stone{% endif %}</th><th>Size</th>
    {% if not diamonds %}<th class="r">Book pcs</th><th class="r">Counted pcs</th>{% endif %}
    <th class="r">Book ct</th><th class="r">Counted ct</th>
    {% if not diamonds %}<th class="r">Variance pcs</th>{% endif %}<th class="r">Variance ct</th>
    {% if 'cost_amount' in totals %}<th class="r">Variance value</th>{% endif %}</tr></thead>
  <tbody>{% for r in rows %}<tr>
    <td class="mono">{{ r.label }} <span class="hint">{{ r.ref }}</span></td><td>{{ r.stone }}</td><td class="mono">{{ r.size|default:"—" }}</td>
    {% if not diamonds %}<td class="r">{% if r.countable %}{{ r.book_pcs|grouped }}{% else %}<span class="hint">uncountable</span>{% endif %}</td>
    <td class="r">{% if editable and r.countable %}<input class="inp tnum" name="pcs_{{ r.pk }}" inputmode="numeric" value="{{ r.counted_pcs|default_if_none:'' }}" style="width:70px" aria-label="Counted pieces, {{ r.label }}">{% else %}{{ r.counted_pcs|default_if_none:"—" }}{% endif %}</td>{% endif %}
    <td class="r">{{ r.book_ct|ct }}</td>
    <td class="r">{% if editable %}<input class="inp tnum" name="ct_{{ r.pk }}" inputmode="decimal" value="{{ r.counted_ct|default_if_none:'' }}" style="width:90px" aria-label="Counted carats, {{ r.label }}">{% else %}{{ r.counted_ct|ct }}{% endif %}</td>
    {% if not diamonds %}<td class="r">{{ r.var_pcs|default_if_none:"—" }}</td>{% endif %}
    <td class="r">{% if r.var_ct is not None %}{{ r.var_ct|ct }}{% else %}—{% endif %}</td>
    {% if 'cost_amount' in totals %}<td class="r">{{ r.cost_amount|rupees }}</td>{% endif %}
  </tr>{% empty %}<tr><td colspan="10" class="hint">Nothing in this scope has stock.</td></tr>{% endfor %}</tbody>
  <tfoot><tr><td colspan="{% if diamonds %}3{% else %}7{% endif %}"><b>Counted {{ totals.counted }} of {{ totals.total }}</b></td>
    <td class="r"><b>{{ totals.var_ct|ct }}</b></td>{% if 'cost_amount' in totals %}<td class="r"><b>{{ totals.cost_amount|rupees }}</b></td>{% endif %}</tr></tfoot>
</table></div>
```

(Check the foot's colspans against the header for each side and fix them so the totals sit under Variance ct and Variance value; add a test assertion on cell order like 5b's foot test.)

`inventory/templates/inventory/stock_take.html`:

```html
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}{{ take.number }} · Stock take{% endblock %}
{% block crumb %}Stock control &nbsp;›&nbsp; <a href="{% url 'inventory:stock_takes' %}">Stock takes</a> &nbsp;›&nbsp; <b class="mono">{{ take.number }}</b>{% endblock %}
{% block content %}
{% include "inventory/_stock_take_body.html" with list_url="inventory:stock_takes" diamonds=False %}
{% endblock %}
```

`inventory/templates/inventory/_stock_take_body.html` (shared by both sides' sheet pages):

```html
{% load inventory_extras %}
<div class="shelfbar"><h1>{{ take.number }} · {{ scope }}</h1>
  <span class="chip {% if reversed %}crit{% elif take.status == 'open' %}warn{% elif take.status == 'closed' %}good{% endif %}"><span class="dot"></span>{% if reversed %}Reversed{% else %}{{ take.get_status_display }}{% endif %}</span></div>
{% if error %}<div class="banner crit"><div class="banner-ic">!</div><div><h4>{{ error }}</h4></div></div>{% endif %}
<p class="hint">Started by {{ take.started_by.full_name|default:take.started_by.get_username|default:"system" }} on {{ take.started_at|date:"d M Y" }}{% if take.closed_at %} · {{ take.get_status_display|lower }} {{ take.closed_at|date:"d M Y" }}{% endif %}{% if take.document %} · posted as {% if diamonds %}<b class="mono">{{ take.document.number }}</b>{% else %}<a class="mono" href="{% url 'inventory:document' take.document.pk %}">{{ take.document.number }}</a>{% endif %}{% endif %}</p>
<form method="post">{% csrf_token %}
<div class="card" style="overflow:hidden">{% include "inventory/_stock_sheet.html" %}
  {% if may and not previewing %}<div class="card-b" style="border-top:1px solid var(--border)">
    {% if confirming %}<div class="banner warn" style="margin:0 0 10px"><div class="banner-ic">?</div><div><h4>{{ confirm_message }}</h4>
      <input type="hidden" name="confirm" value="1"><button class="btn pri" name="action" value="{{ confirming }}">Yes, {% if confirming == 'close' %}close and post{% elif confirming == 'cancel' %}cancel it{% else %}reverse it{% endif %}</button>
      <a class="btn" href="">No</a></div></div>{% endif %}
    {% if take.status == 'open' %}<button class="btn" name="action" value="save">Save counts</button>
      <button class="btn pri" name="action" value="close">Close and post</button>
      <button class="btn gho" name="action" value="cancel">Cancel stock take</button>
    {% elif take.status == 'closed' and take.document and not reversed %}<button class="btn gho" name="action" value="reverse">Reverse</button>{% endif %}
  </div>{% endif %}
</div></form>
```

`confirm_message`, `editable` (open, `may`, not previewing) and `previewing` come from the view.

`inventory/templates/inventory/stock_takes.html`:

```html
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Stock takes{% endblock %}
{% block crumb %}Stock control &nbsp;›&nbsp; <b>Stock takes</b>{% endblock %}
{% block content %}
<div class="shelfbar"><h1>Stock takes</h1></div>
{% if error %}<div class="banner crit"><div class="banner-ic">!</div><div><h4>{{ error }}</h4></div></div>{% endif %}
{% if may %}<form method="post" class="card" style="margin-bottom:14px"><div class="card-b ctrow">{% csrf_token %}
  <b>Start a stock take</b>
  <select class="inp" name="box_colour" aria-label="Box colour"><option value="">Box colour…</option>{% for c in colours %}<option value="{{ c.code }}">{{ c.code }} · {{ c.label }}</option>{% endfor %}</select>
  <span class="hint">or</span>
  <select class="inp mono" name="batch" aria-label="Batch"><option value="">Batch…</option>{% for b in batches %}<option>{{ b.code }}</option>{% endfor %}</select>
  <button class="btn pri">Start</button></div></form>{% endif %}
<div class="card" style="overflow:hidden"><div style="overflow:auto"><table class="led">
  <thead><tr><th>Stock take</th><th>Scope</th><th>Status</th><th>Started</th><th class="r">Counted</th><th>Closed</th></tr></thead>
  <tbody>{% for r in takes %}<tr>
    <td class="mono"><a href="{% url 'inventory:stock_take' r.take.pk %}"><b>{{ r.take.number }}</b></a></td>
    <td>{{ r.scope }}</td><td><span class="chip"><span class="dot"></span>{{ r.take.get_status_display }}</span></td>
    <td class="hint">{{ r.take.started_at|date:"d M Y" }} · {{ r.take.started_by.full_name|default:"system" }}</td>
    <td class="r">{{ r.counted }}</td><td class="hint">{{ r.take.closed_at|date:"d M Y"|default:"—" }}</td></tr>
  {% empty %}<tr><td colspan="6" class="hint">No stock takes yet.</td></tr>{% endfor %}</tbody></table></div></div>
{% endblock %}
```

Rail (`_rail.html:22`):
`<a class="{% if tab == 'stock_take' %}on{% endif %}" href="{% url 'inventory:stock_takes' %}"><span class="ic">⊙</span>Stock takes</a>`

Stones tab (`templates/inventory_base.html:74`): replace the disabled button with
`{% if not client_view %}<a class="{% if tab == 'stock_take' %}on{% endif %}" href="{% url 'inventory:stock_takes' %}">Stock take</a>{% endif %}`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=st_t2 ../nornament-app/.venv/bin/pytest inventory/tests/test_stock_take_views.py inventory/tests/test_masking.py inventory/tests/test_finders_rail.py inventory/tests/test_ledger_lists.py -p no:warnings -q`
Expected: PASS.

- [ ] **Step 6: Run inventory + accounts** (background, poll until finished)

Expected: 0 failures, 0 errors.

- [ ] **Step 7: Commit**

```bash
git add inventory/views_stock_take.py inventory/templates/inventory/stock_takes.html inventory/templates/inventory/stock_take.html \
        inventory/templates/inventory/_stock_sheet.html inventory/templates/inventory/_stock_take_body.html inventory/urls.py \
        inventory/templates/inventory/_rail.html templates/inventory_base.html inventory/tests/test_stock_take_views.py \
        inventory/tests/test_masking.py inventory/tests/test_finders_rail.py inventory/tests/test_ledger_lists.py
git commit -m "Stock takes open from the rail and the tab: start one for a box colour or batch, count, close, cancel, reverse

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The diamond stock-take screens

**Files:**
- Modify: `inventory/views_stock_take.py` (two diamond views)
- Create: `inventory/templates/inventory/diamonds/stock_takes.html`, `inventory/templates/inventory/diamonds/stock_take.html`
- Modify: `inventory/urls.py`; `templates/inventory_base.html:63` (diamond tab); `inventory/views_dia_movements.py` (`opens`)
- Modify (approved rewrites): `inventory/tests/test_dia_purchase_view.py:105`, `inventory/tests/test_dia_wiring.py:76`, `inventory/tests/test_finders_rail.py:36`
- Test: `inventory/tests/test_stock_take_views.py` (append); `inventory/tests/test_masking.py`

**Interfaces:**
- Consumes: Task 2's `_sheet_rows`, `_frozen_rows`, `_totals`, `_act`, `_context`, `_listed`, `_stock_take_body.html`, `_stock_sheet.html`; `views_diamonds.viewer`, `views_diamonds.dia_page`; `views_dia_movements._as_role`.
- Produces: URL names `inventory:dia_stock_takes` (`/inventory/diamonds/stock-takes/`), `inventory:dia_stock_take` (`/inventory/diamonds/stock-takes/<pk>/`); `views_dia_movements.opens` returns the stock take's page for a `DIA_COUNT` document.

- [ ] **Step 1: Write the failing tests**

Append to `inventory/tests/test_stock_take_views.py`:

```python
DIA_LIST = reverse("inventory:dia_stock_takes")


def _natural():
    from inventory.models import DiamondTerm

    return DiamondTerm.objects.get(kind="category", value="Natural Diamond")


def test_the_diamond_tab_opens_the_diamond_list_and_a_preview_carries(client, admin_user_, diamonds):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert f'href="{DIA_LIST}">Stock take</a>' in body and "Stock take 🔒" not in body
    previewed = client.get(reverse("inventory:diamonds"), {"as": "SALES"}).content.decode()
    assert f'href="{DIA_LIST}?as=SALES">Stock take</a>' in previewed


def test_a_diamond_stock_take_counts_carats_and_closes(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    response = client.post(DIA_LIST, {"category": _natural().pk})
    take = StockTake.objects.get()
    sheet = reverse("inventory:dia_stock_take", args=[take.pk])
    assert response["Location"] == sheet
    round_ = diamonds["round"]
    body = client.get(sheet).content.decode()
    assert round_.ref in body and f'name="pcs_{round_.pk}"' not in body
    client.post(sheet, {"action": "close", "confirm": "1", f"ct_{round_.pk}": "3"})
    take.refresh_from_db()
    assert take.status == StockTake.CLOSED and take.document.kind == StockDocument.Kind.DIA_COUNT
    movements = client.get(reverse("inventory:dia_movements")).content.decode()
    assert f'href="{sheet}"' in movements                       # the diamond Movements tab opens it


def test_a_preview_masks_and_hides_every_form(client, admin_user_, accounts_user, diamonds):
    take = stock_take.start(accounts_user, StockTake.DIAMONDS, category=_natural())
    stock_take.save_counts(accounts_user, take, {diamonds["round"].pk: (None, D("3"))})   # −0.4 ct × ₹16,517
    client.force_login(admin_user_)
    sheet = reverse("inventory:dia_stock_take", args=[take.pk])
    assert "6,607" in client.get(sheet).content.decode()
    previewed = client.get(sheet, {"as": "SALES"}).content.decode()
    assert "6,607" not in previewed and "Save counts" not in previewed and 'name="ct_' not in previewed
    assert "Start a stock take" not in client.get(DIA_LIST, {"as": "SALES"}).content.decode()


def test_a_stones_stock_take_is_not_a_diamond_page(client, accounts_user, shelf):
    take = stock_take.start(accounts_user, StockTake.STONES, batch=shelf["batch"])
    client.force_login(accounts_user)
    assert client.get(reverse("inventory:dia_stock_take", args=[take.pk])).status_code == 404
```

Approved padlock rewrites (each: the diamond tab now links to the list):
- `test_dia_purchase_view.py:105` and `test_finders_rail.py:36`: `"Stock take 🔒" in body` → `f'href="{reverse("inventory:dia_stock_takes")}">Stock take</a>' in body`.
- `test_dia_wiring.py:76`: `"Stock take 🔒" in body` → `"Stock take 🔒" not in body`.

In `test_masking.py`: add `"inventory:dia_stock_takes", "inventory:dia_stock_take"` to `STOCK_TAKE_SCREENS`, and a parametrized diamond walk mirroring the stones one (fixture: a diamond stock take with the round line counted at 3 ct; secret "6,607"; roles sales / karigar / production / graphic → 200 and absent; accounts → present).

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=st_t3 ../nornament-app/.venv/bin/pytest inventory/tests/test_stock_take_views.py inventory/tests/test_masking.py -p no:warnings -q`
Expected: FAIL — `NoReverseMatch` for `inventory:dia_stock_takes`.

- [ ] **Step 3: Implement**

In `inventory/views_stock_take.py` add (imports: `from .models import DiamondTerm`; `from .views_diamonds import dia_page, viewer`):

```python
@login_required
def dia_stock_takes(request):
    user, _ = viewer(request)
    previewing = user is not request.user
    error = None
    if request.method == "POST":
        require(request.user, INV_MOVE, stock_take.RIGHT)
        try:
            take = stock_take.start(request.user, StockTake.DIAMONDS,
                                    category=DiamondTerm.objects.filter(kind="category", pk=request.POST.get("category") or 0).first())
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            return redirect("inventory:dia_stock_take", pk=take.pk)
    takes = StockTake.objects.filter(side=StockTake.DIAMONDS).select_related("category", "started_by", "closed_by")
    return dia_page(request, "inventory/diamonds/stock_takes.html", dtab="stock_take", error=error,
                    takes=_listed(takes), categories=DiamondTerm.objects.filter(kind="category").order_by("sort", "value"),
                    may=request.user.has_perm(INV_MOVE) and not previewing)


@login_required
def dia_stock_take_sheet(request, pk):
    user, _ = viewer(request)
    previewing = user is not request.user
    take = get_object_or_404(StockTake.objects.select_related("category", "document"), pk=pk, side=StockTake.DIAMONDS)
    error = confirming = None
    if request.method == "POST":
        done, error, confirming = _act(request, take, _sheet_rows(request.user, take))
        if done:
            return done
        take.refresh_from_db()
    context = _context(user, take)
    may = request.user.has_perm(INV_MOVE) and not previewing
    return dia_page(request, "inventory/diamonds/stock_take.html", dtab="stock_take", error=error, confirming=confirming,
                    confirm_message=CONFIRM.get(confirming), may=may, previewing=previewing,
                    editable=take.status == StockTake.OPEN and may, **context)
```

Note `_context` is called with `user` (the previewed role) so the rows mask as the role; the POST always acts as `request.user`. (The stones `stock_take_sheet` already passes the same three.)

URLs:

```python
    path("diamonds/stock-takes/", views_stock_take.dia_stock_takes, name="dia_stock_takes"),
    path("diamonds/stock-takes/<int:pk>/", views_stock_take.dia_stock_take_sheet, name="dia_stock_take"),
```

Templates: `inventory/diamonds/stock_takes.html` extends the same base as `inventory/diamonds/movements.html` (copy its title / crumb pattern), with a start form (a `category` select) shown when `may`, and the same list table as the stones one but linking `inventory:dia_stock_take` and carrying `?as={{ as_role }}` when `as_role`. `inventory/diamonds/stock_take.html` extends that base and includes `inventory/_stock_take_body.html` with `diamonds=True`.

Diamond tab (`templates/inventory_base.html:63`): replace the disabled button with
`<a class="{% if dtab == 'stock_take' %}on{% endif %}" href="{% url 'inventory:dia_stock_takes' %}{% if as_role %}?as={{ as_role }}{% endif %}">Stock take</a>`.
Check the Diamond stock tab's own `on` condition (`dtab != 'purchase' and dtab != 'movements'`) and add `and dtab != 'stock_take'` so it is not highlighted on the stock-take pages.

`inventory/views_dia_movements.py` `opens`: before the `SCREEN` lookup,

```python
    if document.kind == Kind.DIA_COUNT:
        url = reverse("inventory:dia_stock_take", args=[document.stock_take.pk])
        return url + (f"?{urlencode({'as': as_role})}" if as_role else "")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=st_t3 ../nornament-app/.venv/bin/pytest inventory/tests/test_stock_take_views.py inventory/tests/test_masking.py inventory/tests/test_dia_wiring.py inventory/tests/test_dia_purchase_view.py inventory/tests/test_finders_rail.py inventory/tests/test_dia_movements.py -p no:warnings -q`
Expected: PASS.

- [ ] **Step 5: Run the whole suite** (background, poll until finished)

Run: `POSTGRES_DB=st_t3 ../nornament-app/.venv/bin/pytest -p no:warnings -q --junit-xml=/tmp/st_t3.xml` and `makemigrations --check --dry-run`.
Expected: only the known S3 failure; "No changes detected".

- [ ] **Step 6: Commit**

```bash
git add inventory/views_stock_take.py inventory/templates/inventory/diamonds/stock_takes.html \
        inventory/templates/inventory/diamonds/stock_take.html inventory/urls.py templates/inventory_base.html \
        inventory/views_dia_movements.py inventory/tests/
git commit -m "Diamond stock takes count a category in carats; the tab opens them and Movements links each one

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
