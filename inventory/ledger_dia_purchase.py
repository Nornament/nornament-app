"""Diamond purchase: the one way new diamond stock enters with a cost.

Each line is described — category, shape, colour, clarity, size — not coded.
Its item code is found, or created confirmed, from shape + colour + clarity;
its band comes from the size (part 3's rules). It becomes a new line with an in
movement (Purchase) and its own cost per carat in INR: what was paid × the
rate, plus the landed extras spread by weight. A purchase never sets a sale
price and never writes the rate card.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from stock.services import ServiceError, require

from . import dia_services, ledger
from .ledger_purchase import PURCHASE_RIGHTS, check_header
from .models import DiamondLineCost, DiamondTerm, Movement, StockDocument

ZERO, PLACES = Decimal("0"), Decimal("0.0001")


@dataclass
class DiaPurchaseLine:
    category: str
    shape: str
    colour: str
    clarity: str
    size_text: str
    pcs: int | None
    ct: Decimal | None
    cost_per_ct: Decimal | None
    batch_no: str = ""


def _check(lines):
    for line in lines:
        described = (line.category, line.shape, line.colour, line.clarity, line.size_text)
        if not all((value or "").strip() for value in described):
            raise ServiceError("A purchase line needs category, shape, colour, clarity and size.")
        if line.ct is None or line.ct <= 0:
            raise ServiceError("A weight must be positive.")
        if line.cost_per_ct is None or line.cost_per_ct <= 0:
            raise ServiceError("A cost per carat must be positive.")


@transaction.atomic
def post_dia_purchase(user, header, lines):
    """New lines only, each with its own landed cost. ``header`` is part 2's ``PurchaseHeader``."""
    for permission in PURCHASE_RIGHTS:
        require(user, permission, "Recording a purchase needs the purchase right and sight of cost and suppliers.")
    check_header(header, lines)
    _check(lines)
    usd = header.currency == "USD"
    fx = header.fx_rate if usd else Decimal("1")
    extras = header.landed_extras or ZERO
    per_ct = extras / sum(line.ct for line in lines)             # extras spread by weight
    document = ledger.open_document(
        user, StockDocument.Kind.DIA_PURCHASE, header.invoice_no, vendor=header.supplier,
        occurred_on=header.occurred_on, currency=header.currency, fx_rate=header.fx_rate if usd else None,
        landed_extras=extras, note=header.note,
    )
    by = user if getattr(user, "is_authenticated", False) else None
    moves, costs = [], []
    for line in lines:
        size = line.size_text.strip()
        sized = dia_services.sized(size, line.pcs, line.ct)
        fresh = dia_services.new_line(
            category=dia_services.listed(DiamondTerm.CATEGORY, line.category),
            code=dia_services.code_for(user, line.shape, line.colour, line.clarity),
            batch_no=(line.batch_no or "").strip(), size_text=size,
            band=dia_services.term(DiamondTerm.BAND, sized.band), ct_lo=sized.ct_lo, ct_hi=sized.ct_hi,
        )
        moves.append(ledger.Line(fresh, Movement.Reason.PURCHASE, Movement.IN, line.pcs, line.ct))
        costs.append(DiamondLineCost(line=fresh, cost_rate=(line.cost_per_ct * fx + per_ct).quantize(PLACES),
                                     effective_from=header.occurred_on, set_by=by, document=document))
    ledger.post(user, document, moves, header.occurred_on)
    DiamondLineCost.objects.bulk_create(costs)
    return document
