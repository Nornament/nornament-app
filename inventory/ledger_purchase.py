"""Record a purchase: the one clean way new stock enters.

Each line opens a new pouch (supplier and purchase date set), posts a Purchase
in movement on it, writes what was paid per carat in INR as a ``purchase``
price, and values it at landed cost — that price plus the purchase's freight,
duty and cutting spread by weight. The selling price is a separate decision.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction

from accounts.capabilities import INV_PURCHASE, VIEW_COST, VIEW_VENDOR
from stock.models import Vendor
from stock.services import ServiceError, require

from . import ledger, rules
from .importers import plan as importer_plan
from .models import Batch, Movement, PriceEntry, StockDocument

ZERO, PLACES = Decimal("0"), Decimal("0.0001")
#: what the purchase screen needs: the right, and sight of the cost and supplier it writes
PURCHASE_RIGHTS = (INV_PURCHASE, VIEW_COST, VIEW_VENDOR)


@dataclass
class PurchaseHeader:
    supplier: Vendor | None
    occurred_on: date
    invoice_no: str = ""
    currency: str = "INR"
    fx_rate: Decimal | None = None
    landed_extras: Decimal = ZERO
    note: str = ""


@dataclass
class PurchaseLine:
    batch: Batch | str          # a code: the purchase files into a new batch it creates
    pouch_no: str
    stone_name: str
    shape: str
    colour: str
    pcs: int | None
    ct: Decimal | None
    cost_per_ct: Decimal | None


def check_header(header, lines):
    """What every purchase's header needs, stones or diamonds: a supplier, a line, and INR or USD
    with its rate to INR."""
    if header.supplier is None:
        raise ServiceError("Choose the supplier.")
    if not lines:
        raise ServiceError("Add at least one line.")
    if header.currency not in ("INR", "USD"):
        raise ServiceError("A purchase is in INR or USD.")
    if header.currency == "USD" and header.fx_rate is None:
        raise ServiceError("A purchase in USD needs the rate to INR.")
    if header.fx_rate is not None and header.fx_rate <= 0:
        raise ServiceError("A rate must be positive.")
    if (header.landed_extras or ZERO) < 0:
        raise ServiceError("Landed extras cannot be negative.")


def _check(header, lines):
    check_header(header, lines)
    seen = set()
    for line in lines:
        number = (line.pouch_no or "").strip()
        if not number:
            raise ServiceError(f"Give every line in {line.batch} a pouch no.")
        if (line.batch.pk, number) in seen or not ledger.pouch_no_free(line.batch, number):
            raise ServiceError(f"{line.batch} · {number} already exists — give it a new number.")
        seen.add((line.batch.pk, number))
        if line.ct is None or line.ct <= 0:
            raise ServiceError("A weight must be positive.")
        if line.cost_per_ct is None or line.cost_per_ct <= 0:
            raise ServiceError("A rate must be positive.")


def _filed(batch):
    """A batch, or a code for one: an existing batch, else a new one when the code reads as a batch code
    (created the way the importer creates one; inside the purchase's transaction, so a refusal leaves none)."""
    if isinstance(batch, Batch):
        return batch
    code = (batch or "").strip().upper()
    found = Batch.objects.filter(code=code).first()
    if found:
        return found
    if not rules.parse_batch_code(code):
        raise ServiceError(f"{code or '(blank)'} does not read as family · class · number · box colour.")
    return importer_plan._batch(code, {})


@transaction.atomic
def post_purchase(user, header, lines):
    """New pouches only: a line on an existing batch + pouch no. is refused (known limit)."""
    require(user, INV_PURCHASE, "Only a role that records purchases can post one.")
    require(user, VIEW_COST, "A purchase writes a cost you may not see.")
    require(user, VIEW_VENDOR, "A purchase names a supplier you may not see.")
    for line in lines:
        line.batch = _filed(line.batch)
    _check(header, lines)
    usd = header.currency == "USD"
    fx = header.fx_rate if usd else Decimal("1")
    extras = header.landed_extras or ZERO
    per_ct = extras / sum(line.ct for line in lines)         # extras spread by weight
    document = ledger.open_document(
        user, StockDocument.Kind.PURCHASE, header.invoice_no, vendor=header.supplier,
        occurred_on=header.occurred_on, currency=header.currency, fx_rate=header.fx_rate if usd else None,
        landed_extras=extras, note=header.note,
    )
    by = user if getattr(user, "is_authenticated", False) else None
    moves, prices = [], []
    for line in lines:
        pouch = ledger.new_pouch(
            line.batch, pouch_no=line.pouch_no.strip(), stone_name=line.stone_name, shape=line.shape,
            colour=line.colour, countable=line.pcs is not None, supplier=header.supplier,
            purchase_date=header.occurred_on,
        )
        cost = (line.cost_per_ct * fx).quantize(PLACES)
        prices += [
            PriceEntry(pouch=pouch, kind=PriceEntry.PURCHASE, rate=cost, effective_from=header.occurred_on, set_by=by),
            PriceEntry(pouch=pouch, kind=PriceEntry.VALUATION, rate=(cost + per_ct).quantize(PLACES),
                       effective_from=header.occurred_on, set_by=by),
        ]
        moves.append(ledger.Line(pouch, Movement.Reason.PURCHASE, Movement.IN, line.pcs, line.ct))
    ledger.post(user, document, moves, header.occurred_on)
    PriceEntry.objects.bulk_create(prices)
    return document
