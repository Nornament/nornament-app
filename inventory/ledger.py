"""The stones ledger: documents, and the one way their movements are written.

Every action that moves stock — job work, a memo, a purchase, a split, a
transfer, a one-off sale or loss — opens a ``StockDocument`` and hands its
movements to ``post``, which writes them in one transaction and runs the checks
every post shares: quantities above zero, an uncountable pouch by weight only,
nothing settled beyond what is out, no pouch below zero. Nothing is edited
afterwards; a mistake is undone by posting the opposite movements.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal

from django.db import transaction
from django.db.models import Case, F, Sum, When
from django.utils import timezone

from accounts.capabilities import INV_ASSORT, INV_JOB, INV_MOVE, INV_PURCHASE
from stock.services import ServiceError, log, require

from . import inputs, services
from .models import Batch, Movement, Pouch, StockDocument

ZERO = Decimal("0")
Kind, Status = StockDocument.Kind, StockDocument.Status

#: the kinds that stay open while goods are out with someone
OPENABLE = (Kind.JOB_WORK, Kind.MEMO)
#: the right that posts each kind — and so may undo or reverse it
RIGHT_FOR_KIND = {
    Kind.PURCHASE: INV_PURCHASE, Kind.JOB_WORK: INV_JOB, Kind.MEMO: INV_MOVE,
    Kind.SPLIT: INV_ASSORT, Kind.TRANSFER: INV_ASSORT, Kind.SINGLE: INV_MOVE,
}
#: automatic numbers; job work and memos carry the challan or memo no. people type
PREFIX = {Kind.PURCHASE: "PUR-", Kind.SPLIT: "SPL-", Kind.TRANSFER: "TRF-", Kind.SINGLE: "MOV-"}
REVERSAL_PREFIX = "REV-"
#: the reasons that bring a pouch into being, so a reversal can find what it created
CREATING = (Movement.Reason.PURCHASE, Movement.Reason.SPLIT)


@dataclass
class Line:
    """One movement to post. ``ref`` defaults to the document's number."""

    pouch: Pouch
    reason: str
    direction: str
    pcs: int | None = None
    ct: Decimal | None = None
    note: str = ""
    ref: str = ""
    reverses: Movement | None = None


def _by(user):
    return user if getattr(user, "is_authenticated", False) else None


def _when(day):
    """A movement's time: now when it happens today, else noon of the day it happened."""
    if day is None or day == timezone.localdate():
        return timezone.now()
    return timezone.make_aware(datetime.combine(day, time(12)))


def next_number(prefix):
    """``SPL-000001``: one above the highest number with this prefix.

    ponytail: read-the-max under the caller's transaction; the unique number
    constraint catches a race. A sequence if two people ever post at once.
    """
    last = (StockDocument.objects.filter(number__regex=rf"^{prefix}[0-9]{{6}}$")
            .order_by("-number").values_list("number", flat=True).first())
    return f"{prefix}{(int(last[len(prefix):]) if last else 0) + 1:06d}"


def open_document(user, kind, number="", **fields):
    """A new, open document.

    A typed number must be free among this kind's open and closed documents (a
    reversed one's may be reused). A blank one is drawn automatically — except
    for job work and memos, where goods leave without a sale and need theirs.
    """
    number = (number or "").strip()
    inputs.fits(StockDocument, number=number, **fields)
    if not number:
        if kind not in PREFIX:
            what = "delivery challan no." if kind == Kind.JOB_WORK else "memo no."
            raise ServiceError(f"A {what} is required whenever goods leave without a sale.")
        number = next_number(PREFIX[kind])
    elif StockDocument.objects.filter(kind=kind, number=number).exclude(status=Status.REVERSED).exists():
        raise ServiceError(f"{Kind(kind).label} {number} already exists; give it another number.")
    return StockDocument.objects.create(kind=kind, number=number, created_by=_by(user), **fields)


def _owed(field):
    """Out adds to what a document is owed; in and settle take from it; a reversal flips its sign."""
    value = F(field)
    return Sum(Case(
        When(direction=Movement.OUT, reverses__isnull=True, then=value),
        When(direction=Movement.OUT, then=-value),
        When(reverses__isnull=True, then=-value),
        default=value,
        output_field=Movement._meta.get_field(field),
    ))


def outstanding(document):
    """``{pouch pk: (pcs, ct)}`` still out on a job work or memo document."""
    totals = document.movements.order_by().values("pouch").annotate(pcs=_owed("pcs"), ct=_owed("ct"))
    return {t["pouch"]: (t["pcs"] or 0, t["ct"] or ZERO) for t in totals}


def owed_by_document(documents):
    """``{document pk: [(pouch, pcs, ct)]}`` — what each of these job work or memo documents
    still has out, with the pouches read through ``services.stocked`` so each carries its
    current valuation ``rate``."""
    totals = [t for t in Movement.objects.filter(document__in=documents).order_by()
              .values("document", "pouch").annotate(pcs=_owed("pcs"), ct=_owed("ct"))
              if t["pcs"] or t["ct"]]
    pouches = {p.pk: p for p in services.stocked(Pouch.objects.filter(pk__in={t["pouch"] for t in totals}))}
    owed = defaultdict(list)
    for t in totals:
        owed[t["document"]].append((pouches[t["pouch"]], t["pcs"] or 0, t["ct"] or ZERO))
    return owed


def out_summary():
    """Carats out on open job work and memos, valued at each pouch's current rate.

    An unvalued pouch adds nothing to the value, as on the shelf's Stock value.
    """
    documents = StockDocument.objects.filter(kind__in=OPENABLE, status=Status.OPEN)
    ct, value = ZERO, ZERO
    for lines in owed_by_document(documents).values():
        for pouch, _, owed_ct in lines:
            ct += owed_ct
            value += owed_ct * pouch.rate if pouch.rate is not None else ZERO
    return {"ct": ct, "value": value, "documents": documents.count()}


def party(document):
    """The counterparty, under the key that masks it.

    ``karigar_name`` is seen by those who post job work, ``vendor_name`` by those
    who see suppliers, ``customer_name`` by those who see sales. Callers mask.
    """
    if document is None:
        return {}
    if document.customer_id:
        return {"customer_name": document.customer.name}
    if document.vendor_id:
        return {("karigar_name" if document.kind == Kind.JOB_WORK else "vendor_name"): document.vendor.name}
    return {}


def next_pouch_numbers(batches=None):
    """``{batch code: the next free pouch no.}`` — one above the highest numeric number in
    use (the importer's rule), so a suggestion never collides with a number."""
    batches = Batch.objects.all() if batches is None else batches
    top = dict.fromkeys(batches.values_list("code", flat=True), 0)
    numbered = Pouch.objects.filter(batch__in=batches).exclude(pouch_no=None)
    for code, number in numbered.values_list("batch__code", "pouch_no"):
        if number.isdigit():
            top[code] = max(top[code], int(number))
    return {code: n + 1 for code, n in top.items()}


def next_pouch_no(batch):
    return str(next_pouch_numbers(Batch.objects.filter(pk=batch.pk))[batch.code])


def pouch_no_free(batch, pouch_no):
    return not Pouch.objects.filter(batch=batch, pouch_no=pouch_no).exists()


def new_pouch(batch, **fields):
    """A pouch with the next ``NRN-`` reference and nothing in it: its stock arrives by the
    movement its caller posts."""
    inputs.fits(Pouch, **fields)
    return Pouch.objects.create(ref=f"NRN-{services._last_ref_number() + 1:06d}", batch=batch, **fields)


def _ct(value):
    """Up to 4 places (the column's own precision), trimming trailing zeros: a real
    shortfall like 0.0001 ct must never print as a misleadingly-rounded 0.00."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _check(document, pouch, line, owed):
    if line.reverses is not None:
        return                      # a reversal repeats a movement that passed these once
    inputs.fits(Movement, ref=line.ref)
    if any(value is not None and value < 0 for value in (line.pcs, line.ct)):
        raise ServiceError("A quantity cannot be negative; the reason says which way it moves.")
    if not (line.pcs or line.ct):
        raise ServiceError("A movement needs pieces or a weight above zero.")
    if not pouch.countable and line.pcs is not None:
        raise ServiceError(f"{pouch} is uncountable: it moves by weight only.")
    if document.kind in OPENABLE and line.direction != Movement.OUT:
        pcs, ct = owed.get(pouch.pk, (0, ZERO))
        if (line.pcs or 0) > pcs or (line.ct or 0) > ct:
            pieces = f" and {pcs} pcs" if pouch.countable else ""
            raise ServiceError(f"Settling cannot exceed what is outstanding: {document.number} has "
                               f"{_ct(ct)} ct{pieces} of {pouch} out.")
        owed[pouch.pk] = (pcs - (line.pcs or 0), ct - (line.ct or 0))


def _check_balances(pks):
    for pouch in services.stocked(Pouch.objects.filter(pk__in=pks)):
        if (pouch.on_ct or 0) < 0 or (pouch.countable and (pouch.on_pcs or 0) < 0):
            pieces = f" and {pouch.on_pcs or 0} pcs" if pouch.countable else ""
            raise ServiceError(f"Not enough in {pouch}: this would leave it below zero "
                               f"({_ct(pouch.on_ct or 0)} ct{pieces}).")


def _settle_status(document):
    """Job work and memos close themselves when nothing is outstanding; every other kind —
    and every reversal — closes when posted."""
    if document.kind in OPENABLE and document.reverses_id is None:
        settled = all(pcs == 0 and ct == 0 for pcs, ct in outstanding(document).values())
        status = Status.CLOSED if settled else Status.OPEN
    else:
        status = Status.CLOSED
    if document.status != status:
        document.status = status
        document.save(update_fields=["status"])


def _write(user, document, lines, occurred_on=None):
    """Write a document's movements — all of them, or none — check every pouch's balance, and
    settle the document's status. Shared by ``post`` (an open document only) and ``undo_last``
    (which may do this on a document its own settlements already closed)."""
    locked = Pouch.objects.select_for_update().filter(pk__in={line.pouch.pk for line in lines})
    pouches = {pouch.pk: pouch for pouch in locked}
    owed = outstanding(document) if document.kind in OPENABLE else {}
    for line in lines:
        _check(document, pouches[line.pouch.pk], line, owed)
    at, by = _when(occurred_on), _by(user)
    challan = document.number if document.kind in OPENABLE else ""
    moves = Movement.objects.bulk_create([
        Movement(pouch=line.pouch, document=document, reason=line.reason, direction=line.direction,
                 pcs=line.pcs, ct=line.ct, note=line.note, ref=line.ref or document.number,
                 reverses=line.reverses, counterparty=document.vendor, challan_no=challan,
                 occurred_at=at, recorded_by=by)
        for line in lines
    ])
    _check_balances(list(pouches))
    _settle_status(document)
    log(user, "INSERT", "inv_movement", document.pk, f"{document}: {len(moves)} movement(s)")
    return moves


@transaction.atomic
def post(user, document, lines, occurred_on=None):
    """Write a document's movements — all of them, or none — and settle its status.

    Internal: every caller has already checked the right for its action.
    ``occurred_on`` is the day it happened (``None`` is now). The document is locked and
    re-read first (document, then pouches, as ``undo_last``), so a caller's stale copy can
    never post onto a document reversed or closed a moment ago.
    """
    document.refresh_from_db(from_queryset=StockDocument.objects.select_for_update())
    if document.status != Status.OPEN:
        raise ServiceError(f"{document} is {document.get_status_display().lower()}; it takes no more entries.")
    if not lines and document.reverses_id is None:
        raise ServiceError("Nothing to post.")
    return _write(user, document, lines, occurred_on)


def _unfile(document):
    """Put a transferred pouch back where it was, if nothing has re-filed it since."""
    pouch = document.movements.select_related("pouch__batch").get(reverses__isnull=True).pouch
    if (pouch.batch_id, pouch.pouch_no or "") != (document.to_batch_id, document.to_pouch_no):
        raise ServiceError(f"{pouch} has been re-filed since; reverse that transfer first.")
    if document.from_pouch_no and not pouch_no_free(document.from_batch, document.from_pouch_no):
        raise ServiceError(f"{document.from_batch} · {document.from_pouch_no} has been taken since.")
    pouch.batch_id, pouch.pouch_no = document.from_batch_id, document.from_pouch_no or None
    pouch.save(update_fields=["batch", "pouch_no"])


@transaction.atomic
def reverse_document(user, document, note=""):
    """Post the opposite of every movement on it not already reversed, on a new document
    that points back at it, and mark it Reversed. A pouch it created stays, at zero."""
    require(user, RIGHT_FOR_KIND[document.kind], "Only a role that posts this kind of document may reverse it.")
    document = StockDocument.objects.select_for_update().get(pk=document.pk)
    if document.status == Status.REVERSED:
        raise ServiceError(f"{document} is already reversed.")
    if document.reverses_id:
        raise ServiceError(f"{document} is itself a reversal; it cannot be reversed.")
    moves = list(document.movements.filter(reverses__isnull=True, reversal__isnull=True).select_related("pouch"))
    created = [m.pouch_id for m in moves if m.direction == Movement.IN and m.reason in CREATING]
    moved = (Movement.objects.filter(pouch__in=created, reverses__isnull=True, reversal__isnull=True)
             .exclude(document=document).select_related("pouch__batch").first())
    if moved:
        raise ServiceError(f"{moved.pouch} has moved since; reverse its later movements first.")
    if document.kind == Kind.TRANSFER:
        _unfile(document)
    reversal = StockDocument.objects.create(
        kind=document.kind, number=next_number(REVERSAL_PREFIX), vendor=document.vendor,
        customer=document.customer, reverses=document, note=note, created_by=_by(user),
    )
    post(user, reversal, [Line(m.pouch, m.reason, m.direction, m.pcs, m.ct, note=f"Reverses {document.number}",
                               reverses=m) for m in moves])
    document.status = Status.REVERSED
    document.save(update_fields=["status"])
    log(user, "REVERSAL", "inv_document", document.pk, f"{document} reversed by {reversal.number}")
    return reversal


@transaction.atomic
def undo_last(user, document):
    """Reverse the latest entry on a job work or memo — open, or already closed by its own
    settlements — one wrong line, not the whole challan. Never a reversed document, nor any
    other kind. Undoing recomputes the status the same way posting does: something outstanding
    again reopens it; nothing outstanding leaves it closed (owner, 2026-10-01)."""
    require(user, RIGHT_FOR_KIND[document.kind], "Only a role that posts this kind of document may undo its entries.")
    document = StockDocument.objects.select_for_update().get(pk=document.pk)
    if document.kind not in OPENABLE or document.status not in (Status.OPEN, Status.CLOSED):
        raise ServiceError("Only an open or closed job work or memo has a last entry to undo.")
    last = (document.movements.filter(reverses__isnull=True, reversal__isnull=True)
            .select_related("pouch").order_by("-pk").first())
    if last is None:
        raise ServiceError(f"{document} has nothing left to undo.")
    return _write(user, document, [Line(last.pouch, last.reason, last.direction, last.pcs, last.ct,
                                        note=f"Undoes {last.reason}", reverses=last)])[0]
