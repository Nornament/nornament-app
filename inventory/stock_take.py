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
