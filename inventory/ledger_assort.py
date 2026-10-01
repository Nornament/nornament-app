"""Splitting a pouch, and re-filing one into another batch.

A split moves weight, it does not make or lose it: what comes out of the pouch
equals what goes into the new pouches plus any loss, in carats, and in pieces
when the pouch is counted (the diamond assortment's rule). A transfer changes
only where a pouch is filed; its quantity and its ``NRN-`` reference stay.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from accounts.capabilities import INV_ASSORT
from stock.services import ServiceError, require

from . import ledger, services
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
