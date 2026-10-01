"""Diamond assortment: re-grading part of a line's carats into new lines.

Sorting moves weight; it does not make or lose it. What is taken out of the
source line equals what goes into the destinations plus the sorting loss, to 4
places. Each destination becomes a new line with the source's category and
batch no.; weight that stays in grade simply stays on the source. The parcel's
cost is kept whole: the destinations' cost per carat absorbs the loss, so what
the carats cost does not shrink because some were lost in sorting.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from accounts.capabilities import INV_ASSORT, VIEW_COST
from stock.services import ServiceError, require

from . import dia_services, ledger
from .models import DiamondLine, DiamondLineCost, DiamondTerm, Movement, StockDocument

ZERO, PLACES = Decimal("0"), Decimal("0.0001")
Reason = Movement.Reason


@dataclass
class Destination:
    shape: str
    colour: str
    clarity: str
    size_text: str                          # blank: the source's size
    ct: Decimal | None
    cost_per_ct: Decimal | None = None      # an override; else carried from the source


def _by(user):
    return user if getattr(user, "is_authenticated", False) else None


def _check(source, take_out, destinations, loss):
    if source is None:
        raise ServiceError("Choose the source line.")
    if take_out is None or take_out <= 0:
        raise ServiceError("Enter the carats taken out of the source line.")
    if not destinations:
        raise ServiceError("Add at least one destination.")
    if any(d.ct is None or d.ct <= 0 for d in destinations):
        raise ServiceError("Every destination needs carats.")
    if any(d.cost_per_ct is not None and d.cost_per_ct <= 0 for d in destinations):
        raise ServiceError("A cost per carat must be positive.")
    if loss < 0:
        raise ServiceError("A sorting loss cannot be negative.")
    unaccounted = take_out - sum((d.ct for d in destinations), loss)
    if unaccounted:
        raise ServiceError(f"{ledger._ct(unaccounted)} ct unaccounted — an assortment must balance.")


@transaction.atomic
def post_assortment(user, source, take_out, destinations, loss=None, occurred_on=None, note=""):
    """Take ``take_out`` carats from ``source`` into new lines, less a sorting loss written off on
    the source. Posts only when it balances; the new lines, their codes and their costs are
    written in the same transaction, so a refusal leaves none of them."""
    require(user, INV_ASSORT, "Only a role that assorts can post an assortment.")
    if any(d.cost_per_ct is not None for d in destinations):
        require(user, VIEW_COST, "A cost you may not see is not yours to set.")
    loss = loss or ZERO
    _check(source, take_out, destinations, loss)
    held = dia_services.stocked_lines(DiamondLine.objects.filter(pk=source.pk)).get()
    cost = dia_services.price(held, dia_services.rate_table())[0]
    carried = (cost * take_out / (take_out - loss)).quantize(PLACES) if cost is not None else None
    document = ledger.open_document(user, StockDocument.Kind.DIA_ASSORT,
                                    occurred_on=occurred_on or timezone.localdate(), note=(note or "").strip())
    lines = [ledger.Line(source, Reason.ASSORT_OUT, Movement.OUT, None, take_out - loss, note="source parcel")]
    if loss:
        lines.append(ledger.Line(source, Reason.WASTAGE, Movement.OUT, None, loss, note="Sorting loss"))
    costs = []
    for d in destinations:
        size = (d.size_text or "").strip() or source.size_text
        sized = dia_services.sized(size)
        line = dia_services.new_line(
            category=source.category, code=dia_services.code_for(user, d.shape, d.colour, d.clarity),
            batch_no=source.batch_no, size_text=size, band=dia_services.term(DiamondTerm.BAND, sized.band),
            ct_lo=sized.ct_lo, ct_hi=sized.ct_hi,
        )
        lines.append(ledger.Line(line, Reason.ASSORT_IN, Movement.IN, None, d.ct, note=f"from {source.ref}"))
        rate = d.cost_per_ct if d.cost_per_ct is not None else carried
        if rate is not None:
            costs.append(DiamondLineCost(line=line, cost_rate=rate, effective_from=document.occurred_on,
                                         set_by=_by(user), document=document))
    ledger.post(user, document, lines, occurred_on)
    DiamondLineCost.objects.bulk_create(costs)
    return document
