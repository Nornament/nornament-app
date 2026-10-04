"""Splitting a pouch, and re-filing one into another batch.

A split moves weight, it does not make or lose it: what comes out of the pouch
equals what goes into the new pouches plus any loss, in carats, and in pieces
when the pouch is counted (the diamond assortment's rule). A transfer changes
only where a pouch is filed; its quantity and its ``NRN-`` reference stay.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from accounts.capabilities import INV_ASSORT
from stock.services import ServiceError, log, require

from . import inputs, ledger, services
from .models import Movement, Pouch, PriceEntry, StockDocument

Reason = Movement.Reason
#: what a new pouch takes from the pouch it was split from
COPIED = ("category", "stone_name", "colour", "shape", "cut", "quality", "carton", "supplier",
          "treatment", "origin", "purchase_date", "countable")


@dataclass
class SplitPart:
    pouch_no: str
    pcs: int | None
    ct: Decimal | None
    size_text: str = ""
    remarks: str = ""


def _by(user):
    return user if getattr(user, "is_authenticated", False) else None


def _free_numbers(batch, parts):
    numbers = [(part.pouch_no or "").strip() for part in parts]
    for number in numbers:
        if not number or numbers.count(number) > 1 or not ledger.pouch_no_free(batch, number):
            raise ServiceError(f"{batch} · {number or '(blank)'} is taken — a new pouch number must be free in its batch.")
    return numbers


@transaction.atomic
def split_pouch(user, source, out_pcs, out_ct, parts, loss_pcs=None, loss_ct=None, note=""):
    """Take ``out_pcs`` / ``out_ct`` from ``source`` into new pouches in its batch, less an
    optional loss. The new pouches carry the source's current valuation rate."""
    require(user, INV_ASSORT, "Only a role that assorts can split a pouch.")
    if out_ct is None or out_ct <= 0:
        raise ServiceError("Enter the weight that comes out of the pouch.")
    if not parts:
        raise ServiceError("Add at least one new pouch.")
    numbers = _free_numbers(source.batch, parts)
    unaccounted = out_ct - sum((part.ct or 0 for part in parts), loss_ct or 0)
    if unaccounted:
        raise ServiceError(f"{ledger._ct(unaccounted)} ct unaccounted — a split must balance.")
    if source.countable:
        short = (out_pcs or 0) - sum((part.pcs or 0 for part in parts), loss_pcs or 0)
        if short:
            raise ServiceError(f"{short} pcs unaccounted — a split must balance.")
    rate = services.stocked(Pouch.objects.filter(pk=source.pk)).get().rate
    document = ledger.open_document(user, StockDocument.Kind.SPLIT, note=note)
    moved_pcs = None if out_pcs is None else out_pcs - (loss_pcs or 0)
    lines = [ledger.Line(source, Reason.SPLIT, Movement.OUT, moved_pcs, out_ct - (loss_ct or 0), note=note)]
    if loss_pcs or loss_ct:
        lines.append(ledger.Line(source, Reason.WASTAGE, Movement.OUT, loss_pcs, loss_ct, note="Loss in the split"))
    children = []
    for part, number in zip(parts, numbers):
        child = ledger.new_pouch(source.batch, pouch_no=number, parent=source, size_text=part.size_text,
                                 remarks=part.remarks, **{field: getattr(source, field) for field in COPIED})
        children.append(child)
        lines.append(ledger.Line(child, Reason.SPLIT, Movement.IN, part.pcs, part.ct, note=note))
    ledger.post(user, document, lines)
    if rate is not None:
        PriceEntry.objects.bulk_create([PriceEntry(pouch=child, kind=PriceEntry.VALUATION, rate=rate, set_by=_by(user))
                                        for child in children])
    return document


@transaction.atomic
def transfer_pouch(user, pouch, to_batch, to_pouch_no, note=""):
    """Re-file the whole pouch into an existing batch under a pouch no. free there.

    One Transfer movement records it (direction settle, the balance moved, for
    the record); the document holds the from and the to, so it can be reversed.
    """
    require(user, INV_ASSORT, "Only a role that assorts can re-file a pouch.")
    to_pouch_no = (to_pouch_no or "").strip()
    if to_batch is None:
        raise ServiceError("Choose the batch to re-file into; it must already exist.")
    if to_batch.pk == pouch.batch_id:
        raise ServiceError(f"{pouch} is already in {to_batch}; choose another batch.")
    if not to_pouch_no or not ledger.pouch_no_free(to_batch, to_pouch_no):
        raise ServiceError(f"{to_batch} · {to_pouch_no or '(blank)'} is taken — a new pouch number must be free in its batch.")
    held = services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()
    if not (held.on_ct or held.on_pcs):
        raise ServiceError("There is nothing in this pouch to transfer.")
    document = ledger.open_document(
        user, StockDocument.Kind.TRANSFER, note=note, from_batch=pouch.batch, from_pouch_no=pouch.pouch_no or "",
        to_batch=to_batch, to_pouch_no=to_pouch_no,
    )
    trail = f"{pouch.batch.code} · {pouch.pouch_no or '?'} → {to_batch.code} · {to_pouch_no}"
    ledger.post(user, document, [ledger.Line(pouch, Reason.TRANSFER, Movement.SETTLE,
                                             held.on_pcs if pouch.countable else None, held.on_ct, note=trail)])
    pouch.batch, pouch.pouch_no = to_batch, to_pouch_no
    pouch.save(update_fields=["batch", "pouch_no"])
    return document


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
    open_docs = StockDocument.objects.filter(
        kind__in=ledger.OPENABLE, status=StockDocument.Status.OPEN, movements__pouch__in=ids).distinct()
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
    inputs.fits(Pouch, size_text=size_text)
    ids = {p.pk for p in pouches}
    list(Pouch.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    held = list(services.stocked(Pouch.objects.filter(pk__in=ids)))
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
        old_size = target.size_text
        target.size_text = size_text
        target.save(update_fields=["size_text"])
        log(user, "UPDATE", "inv_pouch", target.pk, str(target),
            old_values={"size_text": old_size}, new_values={"size_text": size_text})
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
        PriceEntry.objects.create(pouch=target, kind=PriceEntry.VALUATION, rate=rate, set_by=_by(user),
                                  created_at=document.created_at)
    return document, rate
