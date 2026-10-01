"""Single movements: a sale, a return, a loss, a sample or a recount — one pouch, one
``MOV-`` document, closed when posted."""
from django.db import transaction
from django.utils import timezone

from accounts.capabilities import INV_MOVE
from stock.services import ServiceError, require

from . import ledger, services
from .models import Movement, StockDocument

Reason = Movement.Reason

#: what may be posted from the shelf, and which way each moves
SINGLE = {
    Reason.SALE: Movement.OUT, Reason.SALES_RETURN: Movement.IN, Reason.PURCHASE_RETURN: Movement.OUT,
    Reason.BREAKAGE: Movement.OUT, Reason.WASTAGE: Movement.OUT, Reason.SAMPLE: Movement.OUT,
    Reason.CONSUMED: Movement.OUT,
}
NEEDS_CUSTOMER = (Reason.SALE, Reason.SALES_RETURN)
NEEDS_SUPPLIER = (Reason.PURCHASE_RETURN,)


@transaction.atomic
def post_single(user, pouch, reason, pcs, ct, occurred_on=None, customer=None, supplier=None, ref="", note=""):
    """One movement on its own document.

    ``ref`` (an invoice no., or the reference a return answers to) stays on the
    movement rather than numbering the document: one invoice may cover several
    pouches, and a document's number is unique per kind.
    """
    require(user, INV_MOVE, "Only a role that records stock movements can post this.")
    if reason not in SINGLE:
        raise ServiceError(f"{reason} is not posted from the shelf.")
    if reason in NEEDS_CUSTOMER and customer is None:
        raise ServiceError("Choose the customer.")
    if reason in NEEDS_SUPPLIER and supplier is None:
        raise ServiceError("Choose the supplier.")
    document = ledger.open_document(
        user, StockDocument.Kind.SINGLE, occurred_on=occurred_on or timezone.localdate(), note=note,
        customer=customer if reason in NEEDS_CUSTOMER else None,
        vendor=supplier if reason in NEEDS_SUPPLIER else None,
    )
    line = ledger.Line(pouch, reason, SINGLE[reason], pcs, ct, note=note, ref=(ref or "").strip())
    ledger.post(user, document, [line], occurred_on)
    return document


@transaction.atomic
def post_recount(user, pouch, pcs, ct, occurred_on=None, note=""):
    """Bring a pouch to the counted figures: the difference per quantity, on one document.

    ``None`` when the count matches the ledger, so nothing is posted.
    """
    require(user, INV_MOVE, "Only a role that records stock movements can post a recount.")
    if pcs is None and ct is None:
        raise ServiceError("Enter the counted pieces or weight.")
    deltas = services.recount_deltas(pouch, pcs, ct)
    if not deltas:
        return None
    document = ledger.open_document(user, StockDocument.Kind.SINGLE,
                                    occurred_on=occurred_on or timezone.localdate(), note=note)
    ledger.post(user, document, [
        ledger.Line(pouch, Reason.RECOUNT_ADJUSTMENT, direction, note=note, **{field: quantity})
        for field, direction, quantity in deltas
    ], occurred_on)
    return document
