"""CRM logic — above all, the FoN commission, computed off real sales.

The old app paid commission off ``customer.data.purchases[]``, a hand-typed
array that disagreed with the stock ledger. Here the same slabs read
``stock.Sale`` rows, so there is one revenue number and the payout is a
function of it.

Slabs, overrides and the roll-up shape are the CRM's, unchanged:

    level 1  own billing + everything under it, at the slab its total reaches
    level 2  a flat override on its own billing
    level 3  a smaller flat override

Only the input changed — from a typed array to the ledger.
"""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from stock.models import Sale
from .models import Customer

ZERO = Decimal("0")

CATEGORIES = ("cat1", "cat2", "cat3")
CATEGORY_LABELS = {
    "cat1": "Cat 1 – Diamond/Polki",
    "cat2": "Cat 2 – Lab/AD/Gold",
    "cat3": "Cat 3 – Solitaires/Silver/Strings",
}

#: level-1 slabs: the whole downline's billing decides which one applies
FON_SLABS = (
    {"max": Decimal("1000000"), "cat1": Decimal("5"), "cat2": Decimal("3"), "cat3": Decimal("0.5")},
    {"max": Decimal("5000000"), "cat1": Decimal("6"), "cat2": Decimal("4"), "cat3": Decimal("0.75")},
    {"max": None, "cat1": Decimal("7"), "cat2": Decimal("5"), "cat3": Decimal("1")},
)
FON_LEVEL_2 = {"cat1": Decimal("2"), "cat2": Decimal("1"), "cat3": Decimal("0.2")}
FON_LEVEL_3 = {"cat1": Decimal("1"), "cat2": Decimal("0.5"), "cat3": Decimal("0.1")}


def month_bounds(on=None):
    on = on or timezone.localdate()
    return date(on.year, on.month, 1), date(on.year, on.month, monthrange(on.year, on.month)[1])


def billing_for(customer, start, end):
    """One customer's billing in the window, split by commission category.

    Reads the sale ledger — every row, whether it came from the shop floor or
    from the CRM — so a piece sold through stock counts towards FoN exactly
    once and at the same figure the margin report uses.
    """
    totals = {key: ZERO for key in CATEGORIES}
    rows = (
        Sale.objects.filter(customer=customer, sold_on__gte=start, sold_on__lte=end)
        .values("product_category")
        .annotate(total=Sum("sold_price"))
    )
    for row in rows:
        key = row["product_category"] if row["product_category"] in CATEGORIES else "cat3"
        totals[key] += row["total"] or ZERO
    return totals


@dataclass
class FonPayout:
    customer: Customer
    level: int
    start: date
    end: date
    billing: dict = field(default_factory=dict)
    pct: dict = field(default_factory=dict)
    payout: dict = field(default_factory=dict)
    slab: dict | None = None

    @property
    def total(self):
        return sum(self.billing.values(), ZERO)

    @property
    def total_payout(self):
        return sum(self.payout.values(), ZERO)


def fon_payout(customer, on=None):
    """The month's payout for one FoN member. ``None`` if they are not one."""
    if not customer.is_fon:
        return None
    start, end = month_bounds(on)
    billing = billing_for(customer, start, end)

    slab = None
    if customer.fon_level == 1:
        # a level 1 earns on the whole tree beneath them
        for level_2 in Customer.objects.filter(is_fon=True, fon_level=2, fon_parent=customer):
            for key, value in billing_for(level_2, start, end).items():
                billing[key] += value
            for level_3 in Customer.objects.filter(is_fon=True, fon_level=3, fon_parent=level_2):
                for key, value in billing_for(level_3, start, end).items():
                    billing[key] += value
        total = sum(billing.values(), ZERO)
        slab = next((s for s in FON_SLABS if s["max"] is None or total <= s["max"]), FON_SLABS[-1])
        pct = {key: slab[key] for key in CATEGORIES}
    elif customer.fon_level == 2:
        pct = dict(FON_LEVEL_2)
    else:
        pct = dict(FON_LEVEL_3)

    payout = {key: billing[key] * pct[key] / Decimal(100) for key in CATEGORIES}
    return FonPayout(
        customer=customer,
        level=customer.fon_level or 3,
        start=start,
        end=end,
        billing=billing,
        pct=pct,
        payout=payout,
        slab=slab,
    )


def fon_register(on=None):
    """Every member's payout for the month, biggest first — the payout run."""
    payouts = [fon_payout(c, on) for c in Customer.objects.filter(is_fon=True).order_by("fon_level", "name")]
    return sorted((p for p in payouts if p), key=lambda p: p.total_payout, reverse=True)


# ── reporting ────────────────────────────────────────────────────────────
def revenue_between(start, end, source=None):
    """One revenue number. ``source=None`` means both ledgers, which is the point."""
    rows = Sale.objects.filter(sold_on__gte=start, sold_on__lte=end)
    if source:
        rows = rows.filter(source=source)
    return rows.aggregate(revenue=Sum("sold_price"))["revenue"] or ZERO


def margin_between(start, end):
    """Margin is only meaningful where a cost exists — stock-sourced sales."""
    return Sale.objects.filter(sold_on__gte=start, sold_on__lte=end, source=Sale.STOCK).aggregate(
        revenue=Sum("sold_price"), margin=Sum("margin_amt")
    )


def customer_lifetime_value(customer):
    return Sale.objects.filter(customer=customer).aggregate(total=Sum("sold_price"))["total"] or ZERO


def pipeline_counts():
    from .models import ClientMaterial, Enquiry, Order, Repair

    return {
        "enquiries": Enquiry.objects.exclude(status__in=["Lost", "Order Confirmed"]).count(),
        "orders": Order.objects.exclude(status__in=["Delivered", "Cancelled"]).count(),
        "repairs": Repair.objects.exclude(status="Delivered").count(),
        "client_materials": ClientMaterial.objects.exclude(status__in=["Returned", "Moved to Order"]).count(),
    }


def outstanding_orders():
    """Orders with money still to come in."""
    from .models import Order

    return (
        Order.objects.exclude(status="Cancelled")
        .filter(Q(billing_amount__isnull=False) | Q(total_amount__isnull=False))
        .select_related("customer")
    )
