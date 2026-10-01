"""Job work and memos: goods out to a karigar or a client on a numbered document,
settled pouch by pouch until nothing is outstanding.

Out takes the goods off the pouch — they are not in the box — and the document
holds what is owed. Coming back is an in; consumed, lost or sold is a settle,
which clears what is owed without touching the pouch again.
"""
from django.db import transaction
from django.utils import timezone

from accounts.capabilities import INV_JOB, INV_MOVE
from crm.models import Customer
from stock.masking import allowed, mask
from stock.models import Vendor
from stock.services import ServiceError, require

from . import ledger
from .models import Movement, StockDocument

Kind, Status, Reason = StockDocument.Kind, StockDocument.Status, Movement.Reason

#: how goods on a challan or a memo are settled: (reason, direction)
JOB_SETTLE = {"in": (Reason.JOB_WORK_IN, Movement.IN), "consumed": (Reason.CONSUMED, Movement.SETTLE),
              "loss": (Reason.WASTAGE, Movement.SETTLE)}
MEMO_SETTLE = {"in": (Reason.MEMO_IN, Movement.IN), "sold": (Reason.SALE, Movement.SETTLE)}


def _goods_out(user, kind, reason, number, pouch, pcs, ct, occurred_on, expected_back, note, party):
    occurred_on = occurred_on or timezone.localdate()
    if expected_back and expected_back < occurred_on:
        raise ServiceError("Expected back cannot be before the date.")
    number = (number or "").strip()
    document = (StockDocument.objects.select_for_update()
                .filter(kind=kind, number=number, status=Status.OPEN).first()) if number else None
    if document is None:
        document = ledger.open_document(user, kind, number, occurred_on=occurred_on,
                                        expected_back=expected_back, note=note, **party)
    elif any(getattr(document, f"{field}_id") != value.pk for field, value in party.items()):
        raise ServiceError(f"{document} is open with someone else; give these goods a new number.")
    ledger.post(user, document, [ledger.Line(pouch, reason, Movement.OUT, pcs, ct, note=note)], occurred_on)
    return document


@transaction.atomic
def job_work_out(user, pouch, karigar, challan_no, pcs, ct, occurred_on=None, expected_back=None, note=""):
    """Goods out to a karigar on a delivery challan; the same open challan may take more pouches.

    ``karigar`` must be one of ``karigar_choices(user)``: the masked choice list is the only
    rule, enforced here rather than trusted to the form, so a hand-built post cannot name a
    vendor the Karigar desk has never been shown — and so, later, see it as a karigar.
    """
    require(user, INV_JOB, "Only a role that posts job cards can send goods out on job work.")
    if karigar is None or karigar.pk not in {choice["pk"] for choice in karigar_choices(user)}:
        raise ServiceError("Choose the karigar.")
    return _goods_out(user, Kind.JOB_WORK, Reason.JOB_WORK_OUT, challan_no, pouch, pcs, ct,
                      occurred_on, expected_back, note, {"vendor": karigar})


@transaction.atomic
def memo_out(user, pouch, customer, memo_no, pcs, ct, occurred_on=None, expected_back=None, note=""):
    """Goods out to a client on approval; the same open memo may take more pouches."""
    require(user, INV_MOVE, "Only a role that records stock movements can send goods out on memo.")
    if customer is None:
        raise ServiceError("Choose the customer.")
    return _goods_out(user, Kind.MEMO, Reason.MEMO_OUT, memo_no, pouch, pcs, ct,
                      occurred_on, expected_back, note, {"customer": customer})


def _settle(user, document, kind, table, pouch, how, pcs, ct, occurred_on, note):
    if document.kind != kind:
        raise ServiceError(f"{document} is not a {Kind(kind).label.lower()}.")
    if how not in table:
        raise ServiceError(f"Unknown way to settle a {Kind(kind).label.lower()}: {how}.")
    reason, direction = table[how]
    line = ledger.Line(pouch, reason, direction, pcs, ct, note=note)
    return ledger.post(user, document, [line], occurred_on)[0]


def settle_job_work(user, document, pouch, how, pcs, ct, occurred_on=None, note=""):
    """``how``: ``in`` (back into the pouch), ``consumed`` or ``loss`` (settled, never returned)."""
    require(user, INV_JOB, "Only a role that posts job cards can settle a challan.")
    return _settle(user, document, Kind.JOB_WORK, JOB_SETTLE, pouch, how, pcs, ct, occurred_on, note)


def settle_memo(user, document, pouch, how, pcs, ct, occurred_on=None, note=""):
    """``how``: ``in`` (returned to the pouch) or ``sold`` (settled against the memo)."""
    require(user, INV_MOVE, "Only a role that records stock movements can settle a memo.")
    return _settle(user, document, Kind.MEMO, MEMO_SETTLE, pouch, how, pcs, ct, occurred_on, note)


def karigar_choices(user):
    """Who goods may go to on job work, as this login may see them.

    Karigars and suppliers share one list. A login without sight of suppliers
    (the Karigar desk) is offered only those already named on a challan, so the
    list never shows it a supplier.
    """
    vendors = Vendor.objects.filter(is_active=True)
    if not allowed(user, "vendor_name"):
        vendors = vendors.filter(pk__in=StockDocument.objects.filter(kind=Kind.JOB_WORK).values("vendor"))
    return [mask(user, {"pk": v.pk, "karigar_name": v.name}) for v in vendors.order_by("name")]


def customer_choices(user):
    """CRM customers by code, named only for a login that may see sales.

    ponytail: the whole CRM in one datalist; a search endpoint if it passes ~10,000.
    """
    return [mask(user, {"code": c.customer_code, "customer_name": c.name})
            for c in Customer.objects.order_by("name").only("customer_code", "name")]
