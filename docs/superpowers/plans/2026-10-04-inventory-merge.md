# Inventory Merge (part 5c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge whole stone pouches of the same stone in one batch into one of them or into a new pouch, at a carat-weighted valuation, reversibly, listed beside splits.

**Architecture:** A new `StockDocument.Kind.MERGE` posted by `ledger_assort.merge_pouches` through the existing ledger engine (`ledger.post`); reversal reuses `ledger.reverse_document` with two merge-specific hooks (a "moved since" check on the target, and putting back the target's prior valuation). One form view mirrors the split's; the Splits & merges list learns the new kind.

**Tech Stack:** Django 5.2, Postgres, pytest-django; server-rendered templates in the stones shell; no new CSS.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-04-inventory-merge-design.md` — binding.
- Kind: `StockDocument.Kind.MERGE = "merge", "Merge"`; number prefix `MRG-`; right `INV_ASSORT`; in `ledger.STONE_KINDS` and `ledger.RIGHT_FOR_KIND`. One migration (`0009_merge_kind`) for the kind's choices.
- Eligible together: same batch, and equal `stone_name`, `colour`, `shape`, `quality` (as typed); each with something on hand. Size may differ.
- Whole pouches only. Sources (every ticked pouch but the target) post **Merge OUT** of their whole on-hand balance; the target posts **Merge IN** of their sum; a loss is **Wastage OUT** on the target, note "Loss in the merge".
- Valuation: new dated `PriceEntry` (valuation) on the target = Σ(ct × rate) / Σ ct over every ticked pouch's on-hand stock before the loss, quantized to `0.0001` half-up; none when any pouch with weight has no valuation. List prices are not carried.
- New target: `ledger.new_pouch` in the batch, `pouch_no` free there, `ledger_assort.COPIED` fields from the first pouch (lowest pk), entered size (else the first pouch's), `parent` empty. Existing target keeps its ref, photos, prices, history; its size becomes the entered size when one is given.
- Refusal messages (exact):
  - "Tick at least two pouches to merge."
  - "Only pouches of the same stone in the same batch merge."
  - "{pouch} is empty."
  - "Count {pouch} first: counted and uncounted pouches do not merge."
  - "Settle {number} first: {pouch} still has stone out on it."
  - "Merge into one of the ticked pouches, or a new pouch."
  - "{batch} · {no} is taken — a new pouch number must be free in its batch." (split's wording, via `_free_numbers`)
  - "A loss cannot be negative."
  - "The loss is more than the pouches hold."
- Success message: "Merge posted as {number}." plus " — no valuation set: one of the pouches had none." when no valuation was written.
- Rights: `require(INV_ASSORT)` → 403. Client view: the merge URL redirects to `inventory:shelf` before reading anything (GET and POST). The **⤵ Merge** button shows only to `inv_assort` holders and never in client view.
- Reversal: refused when the target has any movement after the merge's ("… has moved since; reverse its later movements first."). For a target that held stone before, when its current valuation is still the merge's row, the reversal writes a valuation row at its rate from before the merge.
- Splits & merges list: both kinds, a Kind column, "Out of" / "Into" columns; a reversal is not listed on its own.
- Masking: rows from `rows.pouch_rows` (already masked); templates test key presence (`'stone_rate' in p`).
- No CSS, no change under `stock/` or `crm/`, no new stock/CRM coupling.
- Tests: `POSTGRES_DB=<private name> ../nornament-app/.venv/bin/pytest inventory accounts -p no:warnings -q --junit-xml=<file>` (pytest -q prints no summary; read counts from the XML). Known unrelated failure in the whole suite: `stock/tests/test_import_commit.py::test_images_are_attached_in_chunks_and_are_resumable`. Run long suites in the background and poll the XML rather than blocking for many minutes.
- Commit messages: plain English, ending with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

---

## File structure

- Modify `inventory/models.py` — `Kind.MERGE`.
- Create `inventory/migrations/0009_merge_kind.py` — by `makemigrations`.
- Modify `inventory/ledger.py` — constants; reversal hooks (Task 2).
- Modify `inventory/ledger_assort.py` — `SAME`, `candidates`, `merge_pouches` and helpers.
- Create `inventory/tests/test_ledger_merge.py` — service tests (Task 1), reversal tests (Task 2).
- Modify `inventory/views_assort.py`, `inventory/urls.py`; create `inventory/templates/inventory/merge.html`; modify `pouch.html`, `movements.html` (buttons) — Task 3.
- Create `inventory/tests/test_merge_view.py`; modify `inventory/tests/test_masking.py` — Task 3.
- Modify `inventory/views_lists.py`, `inventory/templates/inventory/splits.html`, `inventory/tests/test_split_transfer_lists.py` — Task 4.

---

### Task 1: The Merge kind and `merge_pouches`

**Files:**
- Modify: `inventory/models.py` (`StockDocument.Kind`, after `TRANSFER`)
- Create: `inventory/migrations/0009_merge_kind.py` (generated)
- Modify: `inventory/ledger.py:31-49` (constants)
- Modify: `inventory/ledger_assort.py` (append)
- Test: `inventory/tests/test_ledger_merge.py` (create)

**Interfaces:**
- Consumes: `ledger.open_document`, `ledger.post`, `ledger.Line`, `ledger.new_pouch`, `ledger.owed_by_document`, `ledger.OPENABLE`, `ledger.ZERO`, `services.stocked`, `ledger_assort._free_numbers`, `ledger_assort.SplitPart`, `ledger_assort.COPIED`, `ledger_assort._by`.
- Produces:
  - `ledger_assort.SAME = ("stone_name", "colour", "shape", "quality")`
  - `ledger_assort.candidates(pouch) -> list[Pouch]` — stocked pouches (carrying `on_pcs`, `on_ct`, `rate`) of `pouch`'s batch and stone with something on hand; `pouch` first if it qualifies, the rest by pk.
  - `ledger_assort.merge_pouches(user, pouches, into=None, new_pouch_no="", size_text="", loss_pcs=None, loss_ct=None, note="") -> tuple[StockDocument, Decimal | None]` — the posted document and the valuation rate written (or `None`). `into` is a `Pouch` among `pouches`, or `None` for a new pouch.

- [ ] **Step 1: Write the failing tests**

Create `inventory/tests/test_ledger_merge.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=mg_t1 ../nornament-app/.venv/bin/pytest inventory/tests/test_ledger_merge.py -p no:warnings -q`
Expected: FAIL — `AttributeError: module 'inventory.ledger_assort' has no attribute 'candidates'`.

- [ ] **Step 3: Add the kind and its migration**

In `inventory/models.py`, inside `StockDocument.Kind`, after `TRANSFER = "transfer", "Transfer"`:

```python
        MERGE = "merge", "Merge"
```

Run: `../nornament-app/.venv/bin/python manage.py makemigrations inventory --name merge_kind`
Expected: `inventory/migrations/0009_merge_kind.py` with one `AlterField` on `stockdocument.kind`.

In `inventory/ledger.py`:
- `STONE_KINDS` gains `Kind.MERGE` (after `Kind.TRANSFER`).
- `RIGHT_FOR_KIND` gains `Kind.MERGE: INV_ASSORT`.
- `PREFIX` gains `Kind.MERGE: "MRG-"`.

- [ ] **Step 4: Implement the service**

Append to `inventory/ledger_assort.py` (add `from decimal import ROUND_HALF_UP, Decimal` — `Decimal` is already imported):

```python
#: what two pouches must share to merge (as typed); size may differ
SAME = ("stone_name", "colour", "shape", "quality")


def candidates(pouch):
    """The pouches that may merge with ``pouch``: its batch, its stone, something on hand. It comes first."""
    same = Pouch.objects.filter(batch_id=pouch.batch_id, **{field: getattr(pouch, field) for field in SAME})
    held = [p for p in services.stocked(same) if p.on_ct or p.on_pcs]
    return sorted(held, key=lambda p: (p.pk != pouch.pk, p.pk))


def _weighted(pouches):
    """Σ(ct × rate) / Σ ct to the column's 4 places; ``None`` when a pouch with weight has no valuation."""
    weighed = [p for p in pouches if p.on_ct]
    if not weighed or any(p.rate is None for p in weighed):
        return None
    total = sum(p.on_ct for p in weighed)
    return (sum(p.on_ct * p.rate for p in weighed) / total).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _settled(pouches):
    """Refuse a pouch with stone still out on an open job work or memo: what comes back would land in an emptied pouch."""
    ids = {p.pk for p in pouches}
    open_docs = StockDocument.objects.filter(kind__in=ledger.OPENABLE, status=StockDocument.Status.OPEN)
    for doc_pk, owed in ledger.owed_by_document(open_docs).items():
        for pouch, _, _ in owed:
            if pouch.pk in ids:
                number = StockDocument.objects.get(pk=doc_pk).number
                raise ServiceError(f"Settle {number} first: {pouch} still has stone out on it.")


@transaction.atomic
def merge_pouches(user, pouches, into=None, new_pouch_no="", size_text="", loss_pcs=None, loss_ct=None, note=""):
    """Empty every pouch into one of them (``into``) or into a new pouch in their batch, less an optional
    loss. The merged pouch is valued at the carat-weighted rate of everything in it, before the loss.
    Returns the document and the rate written (``None`` when one of the pouches had no valuation)."""
    require(user, INV_ASSORT, "Only a role that assorts can merge pouches.")
    held = list(services.stocked(Pouch.objects.filter(pk__in={p.pk for p in pouches})))
    if len(held) < 2:
        raise ServiceError("Tick at least two pouches to merge.")
    held.sort(key=lambda p: p.pk)
    first = held[0]
    if any(p.batch_id != first.batch_id or any(getattr(p, f) != getattr(first, f) for f in SAME) for p in held):
        raise ServiceError("Only pouches of the same stone in the same batch merge.")
    for p in held:
        if not (p.on_ct or p.on_pcs):
            raise ServiceError(f"{p} is empty.")
    if any(p.countable != first.countable for p in held):
        raise ServiceError(f"Count {next(p for p in held if not p.countable)} first: "
                           "counted and uncounted pouches do not merge.")
    _settled(held)
    target = None
    if into is not None:
        target = next((p for p in held if p.pk == into.pk), None)
        if target is None:
            raise ServiceError("Merge into one of the ticked pouches, or a new pouch.")
    else:
        number = _free_numbers(first.batch, [SplitPart(new_pouch_no or "", None, None)])[0]
    if (loss_ct or 0) < 0 or (loss_pcs or 0) < 0:
        raise ServiceError("A loss cannot be negative.")
    total_ct = sum((p.on_ct or ledger.ZERO for p in held), ledger.ZERO)
    total_pcs = sum(p.on_pcs or 0 for p in held)
    if (loss_ct or 0) > total_ct or (first.countable and (loss_pcs or 0) > total_pcs):
        raise ServiceError("The loss is more than the pouches hold.")
    rate = _weighted(held)
    sources = [p for p in held if target is None or p.pk != target.pk]
    if target is None:
        target = ledger.new_pouch(first.batch, pouch_no=number, size_text=size_text or first.size_text,
                                  **{field: getattr(first, field) for field in COPIED})
    elif size_text and size_text != target.size_text:
        target.size_text = size_text
        target.save(update_fields=["size_text"])
    document = ledger.open_document(user, StockDocument.Kind.MERGE, note=note)
    lines = [ledger.Line(p, Reason.MERGE, Movement.OUT, p.on_pcs if first.countable else None, p.on_ct, note=note)
             for p in sources]
    lines.append(ledger.Line(target, Reason.MERGE, Movement.IN,
                             sum(p.on_pcs or 0 for p in sources) if first.countable else None,
                             sum((p.on_ct or ledger.ZERO for p in sources), ledger.ZERO), note=note))
    if loss_pcs or loss_ct:
        lines.append(ledger.Line(target, Reason.WASTAGE, Movement.OUT, loss_pcs if first.countable else None, loss_ct,
                                 note="Loss in the merge"))
    ledger.post(user, document, lines)
    if rate is not None:
        PriceEntry.objects.create(pouch=target, kind=PriceEntry.VALUATION, rate=rate, set_by=_by(user))
    return document, rate
```

Note: `inputs.fits` inside `ledger.new_pouch` validates `size_text` length; a too-long size raises `ServiceError` before any movement (the transaction rolls back the new pouch).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=mg_t1 ../nornament-app/.venv/bin/pytest inventory/tests/test_ledger_merge.py -p no:warnings -q`
Expected: PASS. Then `../nornament-app/.venv/bin/python manage.py makemigrations --check --dry-run` → "No changes detected".

- [ ] **Step 6: Run inventory + accounts** (background, poll the XML)

Run: `POSTGRES_DB=mg_t1 ../nornament-app/.venv/bin/pytest inventory accounts -p no:warnings -q --junit-xml=/tmp/mg_t1.xml`
Expected: 0 failures, 0 errors.

- [ ] **Step 7: Commit**

```bash
git add inventory/models.py inventory/migrations/0009_merge_kind.py inventory/ledger.py inventory/ledger_assort.py \
        inventory/tests/test_ledger_merge.py
git commit -m "Whole pouches of one stone in one batch merge into one of them or a new pouch, at a carat-weighted valuation

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Reversing a merge

**Files:**
- Modify: `inventory/ledger.py` (`reverse_document`, a new `_unmerge_rate`; import `PriceEntry`)
- Test: `inventory/tests/test_ledger_merge.py` (append)

**Interfaces:**
- Consumes: Task 1's `merge_pouches`, `Kind.MERGE`.
- Produces: `ledger.reverse_document(user, document, note="")` handles a merge — no signature change.

- [ ] **Step 1: Write the failing tests**

Append to `inventory/tests/test_ledger_merge.py` (the `ledger` import goes to the top of the file):

```python
from inventory import ledger
from inventory.ledger_assort import SplitPart


def test_reversing_a_merge_into_a_pouch_gives_the_stock_back_and_puts_its_rate_back(accounts_user, shelf, twin):
    onyx = shelf["onyx"]
    doc, _ = ledger_assort.merge_pouches(accounts_user, [onyx, twin], into=onyx, loss_ct=D("0.5"))
    ledger.reverse_document(accounts_user, doc)
    assert (_held(onyx).on_pcs, _held(onyx).on_ct, _held(onyx).rate) == (20, D("12.5"), D("7919"))
    assert (_held(twin).on_pcs, _held(twin).on_ct, _held(twin).rate) == (10, D("7.5"), D("9000"))
    assert StockDocument.objects.get(pk=doc.pk).status == StockDocument.Status.REVERSED


def test_a_revaluation_after_the_merge_is_not_undone(accounts_user, admin_user_, shelf, twin):
    from django.utils import timezone

    onyx = shelf["onyx"]
    doc, _ = ledger_assort.merge_pouches(accounts_user, [onyx, twin], into=onyx)
    services.add_price(admin_user_, onyx, PriceEntry.VALUATION, D("9999"), timezone.localdate())
    ledger.reverse_document(accounts_user, doc)
    assert _held(onyx).rate == D("9999")


def test_reversing_a_merge_into_a_new_pouch_leaves_it_at_zero(accounts_user, shelf, twin):
    doc, _ = ledger_assort.merge_pouches(accounts_user, [shelf["onyx"], twin], into=None, new_pouch_no="7")
    ledger.reverse_document(accounts_user, doc)
    new = Pouch.objects.get(batch=shelf["batch"], pouch_no="7")
    assert (_held(new).on_pcs, _held(new).on_ct) == (0, D("0"))
    assert (_held(shelf["onyx"]).on_ct, _held(twin).on_ct) == (D("12.5"), D("7.5"))


@pytest.mark.parametrize("into_new", [False, True])
def test_a_merge_whose_target_has_moved_since_is_not_reversed(accounts_user, shelf, twin, into_new):
    doc, _ = ledger_assort.merge_pouches(accounts_user, [shelf["onyx"], twin],
                                         into=None if into_new else shelf["onyx"], new_pouch_no="7")
    target = Pouch.objects.get(batch=shelf["batch"], pouch_no="7") if into_new else shelf["onyx"]
    ledger_assort.split_pouch(accounts_user, target, 2, D("1"), [SplitPart("9", 2, D("1"))])
    with pytest.raises(ServiceError, match="has moved since"):
        ledger.reverse_document(accounts_user, doc)
    assert StockDocument.objects.get(pk=doc.pk).status != StockDocument.Status.REVERSED
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=mg_t2 ../nornament-app/.venv/bin/pytest inventory/tests/test_ledger_merge.py -p no:warnings -q`
Expected: FAIL — the rate is not put back (`8324.3750 != 7919`), and the moved-since merges reverse instead of refusing.

- [ ] **Step 3: Implement**

In `inventory/ledger.py`, add `PriceEntry` to the `from .models import (...)` line. In `reverse_document`, after the line that builds `later` and before `moved = (...)`:

```python
    target = None
    if document.kind == Kind.MERGE:
        # the target may have held stone before the merge, so "created" cannot find it: anything on it
        # after this merge's own movements means it has moved since
        target = next(m.pouch for m in moves if m.direction == Movement.IN and m.reason == Movement.Reason.MERGE)
        later |= Q(pouch=target, pk__gt=max(m.pk for m in moves))
```

After `document.save(update_fields=["status"])`:

```python
    if target is not None:
        _unmerge_rate(user, document, target)
```

And, beside `_unfile`:

```python
def _unmerge_rate(user, document, target):
    """A merge set its target the weighted rate; reversing it puts back the rate the target had before,
    unless someone has valued it since. A new pouch had none, so it keeps the merge's."""
    wrote = (target.prices.filter(kind=PriceEntry.VALUATION, created_at__gte=document.created_at)
             .order_by("pk").first())
    if wrote is None or services.latest_price(target, PriceEntry.VALUATION) != wrote:
        return
    before = (target.prices.filter(kind=PriceEntry.VALUATION, created_at__lt=document.created_at)
              .order_by("-effective_from", "-pk").first())
    if before is not None:
        PriceEntry.objects.create(pouch=target, kind=PriceEntry.VALUATION, rate=before.rate, set_by=_by(user))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=mg_t2 ../nornament-app/.venv/bin/pytest inventory/tests/test_ledger_merge.py inventory/tests/test_ledger_assort.py -p no:warnings -q`
Expected: PASS (the split reversal tests still pass).

- [ ] **Step 5: Run inventory + accounts** (background, poll the XML)

Run: `POSTGRES_DB=mg_t2 ../nornament-app/.venv/bin/pytest inventory accounts -p no:warnings -q --junit-xml=/tmp/mg_t2.xml`
Expected: 0 failures, 0 errors.

- [ ] **Step 6: Commit**

```bash
git add inventory/ledger.py inventory/tests/test_ledger_merge.py
git commit -m "A merge reverses: the sources get their stock back and an existing target its rate, unless it moved or was valued since

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The merge screen and its buttons

**Files:**
- Modify: `inventory/views_assort.py` (new `merge` view; module docstring "the two assort screens" → "the assort screens")
- Modify: `inventory/urls.py` (after the `transfer` path)
- Create: `inventory/templates/inventory/merge.html`
- Modify: `inventory/templates/inventory/pouch.html:27` and `inventory/templates/inventory/movements.html:13` (buttons)
- Test: `inventory/tests/test_merge_view.py` (create)
- Modify: `inventory/tests/test_masking.py` (`LEDGER_SCREENS`, `_ledger_urls`, the write-refusal and client-view tests)

**Interfaces:**
- Consumes: `ledger_assort.candidates(pouch)`, `ledger_assort.merge_pouches(...) -> (document, rate)`, `views_assort._assort(request, ref, message) -> (pouch, everything, row)`, `inputs.whole`, `inputs.decimal`, `ledger.next_pouch_no`.
- Produces: URL `inventory:merge` (`/inventory/pouches/<ref>/merge/`), GET and POST.

- [ ] **Step 1: Write the failing tests**

Create `inventory/tests/test_merge_view.py`:

```python
"""Part 5c: the merge screen."""
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import services
from inventory.models import Pouch, StockDocument

pytestmark = pytest.mark.django_db
D = Decimal
ONYX = {"stone_name": "Green Onyx", "colour": "Green", "shape": "Oval", "quality": "B"}


@pytest.fixture
def twin(admin_user_, shelf):
    return services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "5", "size_text": "12*10", **ONYX},
                               pcs=10, ct=D("7.5"), rate=D("9000"))


def _url(pouch):
    return reverse("inventory:merge", args=[pouch.ref])


def test_the_form_lists_the_same_stone_and_ticks_the_opening_pouch(client, accounts_user, shelf, twin):
    client.force_login(accounts_user)
    body = client.get(_url(shelf["onyx"])).content.decode()
    assert "Merge pouches" in body and "Post merge" in body
    assert f'name="pouch" value="{shelf["onyx"].pk}" checked' in body
    assert f'name="pouch" value="{twin.pk}"' in body and f'name="pouch" value="{twin.pk}" checked' not in body
    assert shelf["ruby"].ref not in body
    assert f'name="into" value="{shelf["onyx"].pk}" checked' in body and 'name="into" value="new"' in body
    assert 'name="new_pouch_no" value="6"' in body                   # the batch's next free number
    assert "₹7,919" in body and "₹9,000" in body                       # valuation, to the cost right
    assert f'class="on" href="{reverse("inventory:movements", args=[shelf["onyx"].ref])}"' in body


def test_a_pouch_with_no_like_pouch_says_so(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(_url(shelf["ruby"])).content.decode()
    assert "No other pouch in this batch holds the same stone." in body and "Post merge" not in body


def test_posting_a_merge_into_a_new_pouch_opens_its_document(client, accounts_user, shelf, twin):
    client.force_login(accounts_user)
    response = client.post(_url(shelf["onyx"]), {"pouch": [shelf["onyx"].pk, twin.pk], "into": "new",
                                                "new_pouch_no": "7", "size_text": "mixed", "loss_ct": "0.5", "note": "re-sieved"})
    doc = StockDocument.objects.get(kind=StockDocument.Kind.MERGE)
    assert response.status_code == 302 and response["Location"] == reverse("inventory:document", args=[doc.pk])
    page = client.get(response["Location"]).content.decode()
    assert "Merge posted as MRG-000001." in page
    assert Pouch.objects.filter(batch=shelf["batch"], pouch_no="7", size_text="mixed").exists()


def test_a_merge_without_a_valuation_says_so(client, accounts_user, admin_user_, shelf):
    bare = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "5", **ONYX}, pcs=2, ct=D("1"), rate=None)
    client.force_login(accounts_user)
    response = client.post(_url(shelf["onyx"]), {"pouch": [shelf["onyx"].pk, bare.pk], "into": str(shelf["onyx"].pk)})
    page = client.get(response["Location"]).content.decode()
    assert "Merge posted as MRG-000001. — no valuation set: one of the pouches had none." in page


def test_a_refusal_comes_back_on_the_form_with_the_ticks_kept(client, accounts_user, shelf, twin):
    client.force_login(accounts_user)
    response = client.post(_url(shelf["onyx"]), {"pouch": [twin.pk], "into": str(twin.pk)})
    body = response.content.decode()
    assert response.status_code == 200 and "Tick at least two pouches to merge." in body
    assert f'name="pouch" value="{twin.pk}" checked' in body
    assert f'name="pouch" value="{shelf["onyx"].pk}" checked' not in body
    assert not StockDocument.objects.exists()


def test_a_pouch_outside_the_candidates_is_ignored(client, accounts_user, shelf, twin):
    client.force_login(accounts_user)
    response = client.post(_url(shelf["onyx"]), {"pouch": [shelf["onyx"].pk, shelf["ruby"].pk],
                                                "into": str(shelf["onyx"].pk)})
    assert "Tick at least two pouches to merge." in response.content.decode()


def test_the_buttons_show_to_the_assort_right_only_and_never_in_client_view(client, accounts_user, sales_user,
                                                                            admin_user_, shelf):
    merge = f'href="{_url(shelf["onyx"])}"'
    for name in ("inventory:pouch", "inventory:movements"):
        client.force_login(accounts_user)
        assert merge in client.get(reverse(name, args=[shelf["onyx"].ref])).content.decode(), name
    client.force_login(sales_user)
    assert merge not in client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    assert merge not in client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()


def test_rights_and_client_view(client, sales_user, admin_user_, shelf, twin):
    client.force_login(sales_user)
    assert client.get(_url(shelf["onyx"])).status_code == 403
    assert client.post(_url(shelf["onyx"]), {"pouch": [shelf["onyx"].pk, twin.pk], "into": "new",
                                             "new_pouch_no": "7"}).status_code == 403
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    for response in (client.get(_url(shelf["onyx"])),
                     client.post(_url(shelf["onyx"]), {"pouch": [shelf["onyx"].pk, twin.pk], "into": "new",
                                                       "new_pouch_no": "7"})):
        assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf")
    assert not StockDocument.objects.exists()
```

In `inventory/tests/test_masking.py`:
- add `"inventory:merge"` to `LEDGER_SCREENS`;
- in `_ledger_urls(d)`, add `reverse("inventory:merge", args=[d["onyx"].ref])` after the `transfer` URL;
- in `test_client_view_reaches_no_ledger_screen_or_write`, add `reverse("inventory:merge", args=[d["onyx"].ref])` to the POST loop's URLs;
- in `test_the_ledger_writes_refuse_a_login_without_the_right`, add
  `(reverse("inventory:merge", args=[d["onyx"].ref]), {"pouch": [d["onyx"].pk, d["ruby"].pk], "into": "new", "new_pouch_no": "9"}),`.

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=mg_t3 ../nornament-app/.venv/bin/pytest inventory/tests/test_merge_view.py inventory/tests/test_masking.py -p no:warnings -q`
Expected: FAIL — `NoReverseMatch` for `inventory:merge`.

- [ ] **Step 3: Implement the view**

In `inventory/views_assort.py`, after `split`:

```python
@login_required
def merge(request, ref):
    if _client(request):
        return redirect("inventory:shelf")
    opening, everything, row = _assort(request, ref, "Only a role that assorts can merge pouches.")
    found = ledger_assort.candidates(opening)
    by_pk = {r["pk"]: r for r in everything}
    ticked, into, error = {opening.pk}, str(opening.pk), None
    form = {"new_pouch_no": ledger.next_pouch_no(opening.batch), "size_text": opening.size_text}
    if request.method == "POST":
        form = request.POST
        ticked = {int(pk) for pk in form.getlist("pouch") if pk.isdigit()}
        into = form.get("into") or ""
        try:
            target = None if into == "new" else next((p for p in found if str(p.pk) == into), None)
            if into != "new" and target is None:
                raise ServiceError("Merge into one of the ticked pouches, or a new pouch.")
            document, rate = ledger_assort.merge_pouches(
                request.user, [p for p in found if p.pk in ticked], target, (form.get("new_pouch_no") or "").strip(),
                (form.get("size_text") or "").strip(), inputs.whole(form.get("loss_pcs"), "Loss pieces"),
                inputs.decimal(form.get("loss_ct"), "Loss weight"), (form.get("note") or "").strip(),
            )
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            unvalued = "" if rate is not None else " — no valuation set: one of the pouches had none."
            messages.success(request, f"Merge posted as {document.number}.{unvalued}")
            return redirect("inventory:document", pk=document.pk)
    return _page(request, "inventory/merge.html", everything, tab="tx", pouch_ref=opening.ref, row=row,
                 candidates=[by_pk[p.pk] for p in found] if len(found) > 1 else [], ticked=ticked, into=into,
                 form=form, error=error)
```

In `inventory/urls.py`, after the `transfer` path:

```python
    path("pouches/<str:ref>/merge/", views_assort.merge, name="merge"),
```

- [ ] **Step 4: Implement the template and the buttons**

Create `inventory/templates/inventory/merge.html`:

```html
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Merge · {{ row.batch_code }} · {{ row.pouch_no|default:"?" }}{% endblock %}
{% block crumb %}Shelf &nbsp;›&nbsp; {{ row.box_label }} &nbsp;›&nbsp; <b class="mono">{{ row.batch_code }} · {{ row.pouch_no|default:"?" }}</b> &nbsp;›&nbsp; Merge{% endblock %}
{% block content %}
<div class="dbanner"><h2>Merge pouches</h2></div>
{% if error %}<div class="banner crit"><div class="banner-ic">!</div><div><h4>{{ error }}</h4></div></div>{% endif %}
{% if not candidates %}<div class="card"><div class="card-b"><span class="hint">No other pouch in this batch holds the same stone.</span></div></div>
{% else %}
<form method="post" id="merge">{% csrf_token %}
<div class="card" style="overflow:hidden">
  <div class="card-h"><span class="card-t">{{ row.stone_name|default:"Unidentified" }} in {{ row.batch_code }}</span>
    <span class="spacer"></span><span class="hint">Whole pouches only — split one first to take part of it.</span></div>
  <div style="overflow:auto"><table class="led">
    <thead><tr><th>Merge</th><th>Pouch</th><th class="r">Pieces</th><th class="r">Carats</th><th>Size</th>
      {% if 'stone_rate' in row %}<th class="r">Valuation /ct</th>{% endif %}<th>Into</th></tr></thead>
    <tbody>{% for p in candidates %}<tr>
      <td><input type="checkbox" name="pouch" value="{{ p.pk }}"{% if p.pk in ticked %} checked{% endif %} aria-label="Merge {{ p.batch_code }} · {{ p.pouch_no }}"></td>
      <td class="mono">{{ p.batch_code }} · {{ p.pouch_no|default:"?" }} <span class="hint">{{ p.ref }}</span></td>
      <td class="r">{% if p.countable %}{{ p.pcs|grouped }}{% else %}<span class="hint">uncountable</span>{% endif %}</td>
      <td class="r">{{ p.ct|ct }}</td><td class="mono">{{ p.size_display|default:"—" }}</td>
      {% if 'stone_rate' in p %}<td class="r">{{ p.stone_rate|rupees }}</td>{% endif %}
      <td><label class="hint"><input type="radio" name="into" value="{{ p.pk }}"{% if into == p.pk|stringformat:"s" %} checked{% endif %}> this pouch</label></td>
    </tr>{% endfor %}
    <tr><td></td><td colspan="{% if 'stone_rate' in row %}5{% else %}4{% endif %}"><b>A new pouch</b> in {{ row.batch_code }}, no.
      <input class="inp mono" name="new_pouch_no" maxlength="16" value="{{ form.new_pouch_no|default:'' }}" style="width:80px"></td>
      <td><label class="hint"><input type="radio" name="into" value="new"{% if into == "new" %} checked{% endif %}> a new pouch</label></td></tr>
    </tbody></table></div>
  <div class="card-b" style="border-top:1px solid var(--border)">
    <div class="filterbar">
      <div class="fsel"><label>Size of the merged pouch</label><input class="inp" name="size_text" maxlength="80" value="{{ form.size_text|default:'' }}"></div>
      <div class="fsel"><label>Loss — pieces</label><input class="inp tnum" name="loss_pcs" inputmode="numeric" value="{{ form.loss_pcs|default:'' }}"{% if not row.countable %} readonly placeholder="—"{% endif %}></div>
      <div class="fsel"><label>Loss — carats</label><div class="unit"><input class="inp tnum" name="loss_ct" inputmode="decimal" value="{{ form.loss_ct|default:'' }}"><span class="u">ct</span></div></div>
    </div>
    <div class="fld" style="margin-top:12px"><label>Note</label><input class="inp" name="note" value="{{ form.note|default:'' }}"></div>
    <p class="hint">The merged pouch is valued at the carat-weighted rate of everything in it. The emptied pouches stay on record at zero.</p>
    <button class="btn pri">Post merge</button>
  </div>
</div>
</form>{% endif %}
{% endblock %}
```

Note: `ticked` holds ints and `p.pk` is an int, so `p.pk in ticked` works; `into` is a string, compared with `p.pk|stringformat:"s"`.

In `inventory/templates/inventory/pouch.html` (line 27) and `inventory/templates/inventory/movements.html` (line 13), directly after the split link, inside the same `{% if caps.inv_assort %}` (pouch.html's block is already inside `{% else %}` of `{% if client_view %}`):

```html
      {% if caps.inv_assort %}<a class="btn gho" href="{% url 'inventory:merge' row.ref %}">⤵ Merge</a>{% endif %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=mg_t3 ../nornament-app/.venv/bin/pytest inventory/tests/test_merge_view.py inventory/tests/test_masking.py inventory/tests/test_assort_views.py -p no:warnings -q`
Expected: PASS.

- [ ] **Step 6: Run inventory + accounts** (background, poll the XML)

Run: `POSTGRES_DB=mg_t3 ../nornament-app/.venv/bin/pytest inventory accounts -p no:warnings -q --junit-xml=/tmp/mg_t3.xml`
Expected: 0 failures, 0 errors.

- [ ] **Step 7: Commit**

```bash
git add inventory/views_assort.py inventory/urls.py inventory/templates/inventory/merge.html \
        inventory/templates/inventory/pouch.html inventory/templates/inventory/movements.html \
        inventory/tests/test_merge_view.py inventory/tests/test_masking.py
git commit -m "Merge opens from a pouch: tick like pouches, choose one of them or a new pouch, post it

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Merges on the Splits & merges list

**Files:**
- Modify: `inventory/views_lists.py` (`splits`)
- Modify: `inventory/templates/inventory/splits.html`
- Test: `inventory/tests/test_split_transfer_lists.py` (append; one approved assertion change)

**Interfaces:**
- Consumes: Task 1's `merge_pouches`; Task 2's reversal.
- Produces: rows with `kind`, `source` (comma-joined sources), `source_ref` (comma-joined refs), `made`, `ct`.

- [ ] **Step 1: Write the failing tests**

In `inventory/tests/test_split_transfer_lists.py`, change `assert "No splits yet." in ...` to `assert "No splits or merges yet." in ...` (the one approved change to an existing assertion). Append:

```python
from inventory import ledger_assort, services

ONYX = {"stone_name": "Green Onyx", "colour": "Green", "shape": "Oval", "quality": "B"}


def test_merges_are_listed_beside_splits(client, accounts_user, admin_user_, sales_user, shelf):
    twin = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "5", **ONYX}, pcs=10, ct=D("7.5"), rate=None)
    split = split_pouch(accounts_user, shelf["ruby"], None, D("10"), [SplitPart("6", None, D("10"))])
    merge, _ = ledger_assort.merge_pouches(accounts_user, [shelf["onyx"], twin], into=shelf["onyx"], loss_ct=D("0.5"))
    body = _body(client, sales_user, "inventory:splits")
    assert body.index(merge.number) < body.index(split.number)
    row = _row(body, merge.number)
    assert "Merge" in row and "SL01G · 5" in row and twin.ref in row and "SL01G · 1" in row
    assert "7.50" in row                                              # what went in, not the loss
    assert "Split" in _row(body, split.number)
    assert "<th>Kind</th>" in body and "<th>Out of</th>" in body and "<th>Into</th>" in body


def test_a_reversed_merge_reads_reversed_and_its_reversal_is_not_listed(client, accounts_user, admin_user_, shelf):
    twin = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "5", **ONYX}, pcs=10, ct=D("7.5"), rate=None)
    merge, _ = ledger_assort.merge_pouches(accounts_user, [shelf["onyx"], twin], into=shelf["onyx"])
    reversal = ledger.reverse_document(accounts_user, merge)
    body = _body(client, accounts_user, "inventory:splits")
    assert "Reversed" in _row(body, merge.number) and reversal.number not in body


def test_the_recent_list_offers_merge(client, accounts_user, shelf):
    body = _body(client, accounts_user, "inventory:recent")
    assert '<option value="merge"' in body
```

(If `recent.html` renders its kind options differently, match its actual markup; the behaviour under test is that Merge is offered.)

(Move the new `import` line to the top of the file with the others.)

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=mg_t4 ../nornament-app/.venv/bin/pytest inventory/tests/test_split_transfer_lists.py -p no:warnings -q`
Expected: FAIL — merges are not listed; no Kind column; old empty text.

- [ ] **Step 3: Implement**

In `inventory/views_lists.py`, `splits` becomes:

```python
@login_required
def splits(request):
    """Every split and merge, newest first: the pouches emptied into the move, the pouches it filled,
    and the carats taken out (a split's loss included; a merge's loss is on its target, after).
    A reversal is not listed on its own: the document it undid reads Reversed.

    ponytail: every split and merge on one page; page through when there are hundreds.
    """
    if _client(request):
        return redirect("inventory:shelf")
    documents = (StockDocument.objects.filter(kind__in=(Kind.SPLIT, Kind.MERGE), reverses__isnull=True)
                 .select_related("created_by").prefetch_related("movements__pouch__batch")
                 .order_by("-created_at", "-pk"))
    rows = []
    for d in documents:
        moves = sorted(d.movements.all(), key=lambda m: m.pk)
        out = [m for m in moves if m.direction == Movement.OUT and (d.kind == Kind.SPLIT or m.reason == Movement.Reason.MERGE)]
        sources = list(dict.fromkeys(m.pouch for m in out))
        rows.append(mask(request.user, {
            "pk": d.pk, "number": d.number, "occurred_on": d.occurred_on, "kind": d.get_kind_display(),
            "source": ", ".join(str(p) for p in sources), "source_ref": ", ".join(p.ref for p in sources),
            "made": [str(m.pouch) for m in moves if m.direction == Movement.IN],
            "ct": sum((m.ct or ledger.ZERO for m in out), ledger.ZERO),
            "reversed": d.status == Status.REVERSED, "by": _name(d.created_by),
        }))
    return _page(request, "inventory/splits.html", _everything(request), tab="splits", rows=rows)
```

In `inventory/templates/inventory/splits.html`, the header row becomes
`<th>Document</th><th>Kind</th><th>Date</th><th>Out of</th><th>Into</th><th class="r">Carats out</th><th>By</th><th></th>`,
each row gains `<td>{{ d.kind }}</td>` after the document cell, the empty row becomes
`<tr><td colspan="8" class="hint">No splits or merges yet.</td></tr>`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=mg_t4 ../nornament-app/.venv/bin/pytest inventory/tests/test_split_transfer_lists.py -p no:warnings -q`
Expected: PASS.

- [ ] **Step 5: Run the whole suite** (background, poll the XML)

Run: `POSTGRES_DB=mg_t4 ../nornament-app/.venv/bin/pytest -p no:warnings -q --junit-xml=/tmp/mg_t4.xml` and `../nornament-app/.venv/bin/python manage.py makemigrations --check --dry-run`.
Expected: only the known S3 failure; "No changes detected".

- [ ] **Step 6: Commit**

```bash
git add inventory/views_lists.py inventory/templates/inventory/splits.html inventory/tests/test_split_transfer_lists.py
git commit -m "Merges join the Splits & merges list, with a Kind column; a reversed one reads Reversed

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
