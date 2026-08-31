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
from decimal import Decimal, InvalidOperation

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
def default_making_rate():
    """What a new quote line starts at, per gram of metal.

    Kept in ``CrmSetting`` so it moves without a deploy — the legacy
    calculator hardcoded it, and a hardcoded rate is a rate nobody updates.
    """
    from .models import CrmSetting

    row = CrmSetting.objects.filter(pk="default_making_rate").first()
    try:
        return Decimal(str((row.value or {}).get("per_gram", 1500))) if row else Decimal("1500")
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("1500")


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


# ── writes ───────────────────────────────────────────────────────────────
# Everything below is a legacy CRM action. The rule from the stock side holds:
# a screen never writes a ledger or a status log itself, it calls one of these.

CODE_PREFIXES = {
    "customer": ("customer_code", "NOR"),
    "enquiry": ("enquiry_code", "ENQ"),
    "order": ("order_code", "ORD"),
    "repair": ("repair_code", "REP"),
    "clientmaterial": ("cm_code", "CM"),
}


def quick_customer(name, phone=""):
    """A walk-in, created from the sale modal with the two things the counter has.

    Everything else on a customer is optional, so the record is real and the
    CRM's own screen fills in the rest later. Recording the sale against a
    customer row is the point — a typed-in name on a sale is not a customer.
    """
    from .models import Customer

    return Customer.objects.create(
        customer_code=next_code(Customer, "customer"),
        name=(name or "").strip(),
        mobile=(phone or "").strip(),
    )


def next_code(model, kind):
    """``NOR-001``, ``ENQ-014`` … — the legacy ``gc``/``gEnq`` generators.

    The legacy app counted rows, which reissues a code after a delete. This
    reads the highest number actually in use instead, so a code is never
    handed out twice.
    """
    field, prefix = CODE_PREFIXES[kind]
    highest = 0
    for code in model.objects.values_list(field, flat=True):
        tail = str(code or "").rsplit("-", 1)[-1]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{prefix}-{highest + 1:03d}"


def log_status(entity, kind, status, note="", by=""):
    """Move an entity and write the ``statusLog`` entry that goes with it."""
    entity.status = status
    entity.updated_at = timezone.now()
    entity.save(update_fields=["status", "updated_at"])
    from .models import StatusEvent

    return StatusEvent.objects.create(
        entity_type=kind,
        entity_id=entity.pk,
        date=timezone.localdate(),
        status=status,
        note=note,
        by=by,
    )


def status_log(kind, entity_id):
    from .models import StatusEvent

    return StatusEvent.objects.filter(entity_type=kind, entity_id=entity_id)


def convert_enquiry_to_order(enquiry, by=""):
    """The legacy ``onConvertToOrder`` — a confirmed enquiry becomes an order.

    Idempotent: an enquiry that already produced an order returns that order
    rather than opening a second one, which the legacy app did not guard.
    """
    from .models import Order

    existing = enquiry.orders.first()
    if existing:
        return existing
    order = Order.objects.create(
        order_code=next_code(Order, "order"),
        customer=enquiry.customer,
        enquiry=enquiry,
        status="Order Confirmed",
        order_date=timezone.localdate(),
        item_description=enquiry.item_of_interest,
        metal_type=enquiry.metal_type,
        stone_details=enquiry.stone_details,
        design_brief=enquiry.design_brief,
        total_amount=enquiry.estimated_budget,
        salesperson=enquiry.salesperson,
        notes=enquiry.notes,
    )
    log_status(order, "order", "Order Confirmed", note=f"Converted from {enquiry.enquiry_code}", by=by)
    if enquiry.status != "Order Confirmed":
        log_status(enquiry, "enquiry", "Order Confirmed", note=f"Converted to {order.order_code}", by=by)
    return order


def client_material_to_order(material, by=""):
    """``Moved to Order`` — the held material becomes an order, and says so."""
    from .models import Order

    order = Order.objects.create(
        order_code=next_code(Order, "order"),
        customer=material.customer,
        status="Order Confirmed",
        order_date=timezone.localdate(),
        item_description=material.jewellery_description,
        metal_type=material.metal_type,
        weight_grams=material.weight_grams,
        design_brief=material.design_notes,
        salesperson=material.salesperson,
        notes=f"From client material {material.cm_code}",
    )
    log_status(order, "order", "Order Confirmed", note=f"From {material.cm_code}", by=by)
    log_status(material, "clientmaterial", "Moved to Order", note=f"Became {order.order_code}", by=by)
    return order


def client_material_to_repair(material, by=""):
    from .models import Repair

    repair = Repair.objects.create(
        repair_code=next_code(Repair, "repair"),
        customer=material.customer,
        status="Received",
        received_date=material.received_date or timezone.localdate(),
        jewellery_received=material.jewellery_description,
        item_description=material.jewellery_description,
        issue=material.issue,
        salesperson=material.salesperson,
        notes=f"From client material {material.cm_code}",
    )
    log_status(repair, "repair", "Received", note=f"From {material.cm_code}", by=by)
    log_status(material, "clientmaterial", "Moved to Repair", note=f"Became {repair.repair_code}", by=by)
    return repair


def record_purchase(customer, **fields):
    """A CRM purchase is a row in the one sale ledger, tagged ``source='CRM'``.

    It carries no cost, so its margin is null and the margin report filters it
    out rather than inventing a number it does not have.
    """
    return Sale.objects.create(
        customer=customer,
        customer_name=customer.name,
        customer_phone=customer.phone,
        source=Sale.CRM,
        cost_at_sale=None,
        **fields,
    )


# ── the lead engine, ported from the legacy CRM ──────────────────────────
def _days_since(when):
    if not when:
        return None
    if hasattr(when, "date"):
        when = when.date()
    return (timezone.localdate() - when).days


def _days_until(when):
    """Days to the next occurrence of a recurring date — ``daysUntil``."""
    if not when:
        return None
    today = timezone.localdate()
    for year in (today.year, today.year + 1):
        try:
            candidate = when.replace(year=year)
        except ValueError:
            candidate = when.replace(year=year, day=28)
        if candidate >= today:
            return (candidate - today).days
    return None


def last_activity(customer, enquiries=None):
    """``lastActivity`` — the most recent date on anything touching them."""
    from .models import StatusEvent

    dates = [customer.created_at.date() if customer.created_at else None]
    dates += [entry.date for entry in customer.outreach_log.all()]
    dates += list(Sale.objects.filter(customer=customer).values_list("sold_on", flat=True))
    rows = customer.enquirys.all() if enquiries is None else [e for e in enquiries if e.customer_id == customer.pk]
    for enquiry in rows:
        dates.append(enquiry.enquiry_date)
        dates += list(
            StatusEvent.objects.filter(entity_type="enquiry", entity_id=enquiry.pk).values_list("date", flat=True)
        )
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def next_occasion(customer):
    candidates = [
        ("birthday", _days_until(customer.birth_date)),
        ("anniversary", _days_until(customer.anniversary_date)),
        ("engagement", _days_until(customer.engagement_date)),
        ("wedding", _days_until(customer.wedding_date)),
    ]
    candidates += [(o.occasion_type or "occasion", _days_until(o.date)) for o in customer.occasions.all()]
    live = [(kind, days) for kind, days in candidates if days is not None]
    return min(live, key=lambda pair: pair[1]) if live else None


def computed_temp(customer, enquiries=None):
    """``computedTemp`` — what the activity says the temperature should be.

    Returns ``(temperature, why)``. Advisory only: the screen offers it as a
    chip to apply, exactly as the legacy app did. Nothing writes it silently.
    """
    rows = customer.enquirys.all() if enquiries is None else [e for e in enquiries if e.customer_id == customer.pk]
    open_enquiries = [e for e in rows if e.status not in ("Order Confirmed", "Lost")]
    since = _days_since(last_activity(customer, enquiries))
    today = timezone.localdate()

    for enquiry in open_enquiries:
        if not enquiry.follow_up_date:
            continue
        days = (enquiry.follow_up_date - today).days
        if days <= 7:
            if days < 0:
                return "Hot", f"Follow-up overdue {-days}d ({enquiry.enquiry_code})"
            when = "today" if days == 0 else f"in {days}d"
            return "Hot", f"Follow-up {when} ({enquiry.enquiry_code})"

    if open_enquiries and since is not None and since <= 14:
        return "Hot", f"Active enquiry · last touch {since}d ago"

    last_purchase = Sale.objects.filter(customer=customer).order_by("-sold_on").values_list("sold_on", flat=True).first()
    bought = _days_since(last_purchase)
    if bought is not None and bought <= 30:
        return "Hot", f"Purchased {bought}d ago"

    if open_enquiries:
        return "Warm", f"Open enquiry, quiet for {'?' if since is None else since}d"
    if since is not None and since <= 45:
        return "Warm", f"Last activity {since}d ago"

    occasion = next_occasion(customer)
    if occasion and occasion[1] <= 30:
        return "Warm", f"{occasion[0]} in {occasion[1]}d"

    return "Cold", "No activity logged yet" if since is None else f"No activity for {since}d"


#: gap kind -> (label, background, foreground) — the legacy ``KIND`` map
GAP_KINDS = {
    "overdue": ("Overdue", "#FDEBEC", "#9F2F2D"),
    "nofollow": ("No follow-up", "#FBF3DB", "#956400"),
    "stuck": ("Stuck", "#F0ECF8", "#5a3d8a"),
    "stale": ("Going cold", "#E1F3FE", "#1F6C9F"),
}
_GAP_PRIORITY = {"overdue": 0, "nofollow": 1, "stuck": 2, "stale": 3}


def lead_gaps(limit=30):
    """``leadGaps`` — open leads with no next step, worst first."""
    from .models import Enquiry, StatusEvent

    today = timezone.localdate()
    gaps = []
    enquiries = list(
        Enquiry.objects.exclude(status__in=["Order Confirmed", "Lost"]).select_related("customer")
    )
    latest_event = {}
    for entity_id, when in StatusEvent.objects.filter(
        entity_type="enquiry", entity_id__in=[e.pk for e in enquiries], date__isnull=False
    ).values_list("entity_id", "date"):
        if entity_id not in latest_event or when > latest_event[entity_id]:
            latest_event[entity_id] = when

    for enquiry in enquiries:
        if enquiry.follow_up_date:
            days = (enquiry.follow_up_date - today).days
            if days < 0:
                gaps.append(
                    {
                        "kind": "overdue",
                        "customer": enquiry.customer,
                        "enquiry": enquiry,
                        "days": -days,
                        "label": f"Follow-up overdue by {-days}d · {enquiry.item_of_interest or enquiry.status}",
                    }
                )
        else:
            gaps.append(
                {
                    "kind": "nofollow",
                    "customer": enquiry.customer,
                    "enquiry": enquiry,
                    "days": 0,
                    "label": "Open enquiry with no follow-up date set",
                }
            )
        stuck = _days_since(latest_event.get(enquiry.pk))
        if stuck is not None and stuck > 21:
            gaps.append(
                {
                    "kind": "stuck",
                    "customer": enquiry.customer,
                    "enquiry": enquiry,
                    "days": stuck,
                    "label": f"Sitting in “{enquiry.status}” for {stuck}d",
                }
            )

    all_enquiries = list(Enquiry.objects.all())
    for customer in Customer.objects.exclude(temperature="Cold").prefetch_related("outreach_log"):
        since = _days_since(last_activity(customer, all_enquiries))
        if since is not None and since > 45:
            gaps.append(
                {
                    "kind": "stale",
                    "customer": customer,
                    "enquiry": None,
                    "days": since,
                    "label": f"{customer.temperature or 'Warm'} customer with no touch for {since}d",
                }
            )

    gaps.sort(key=lambda gap: (_GAP_PRIORITY[gap["kind"]], -gap["days"]))
    for gap in gaps:
        gap["badge"] = GAP_KINDS[gap["kind"]]
    return gaps[:limit]


def temperature_spread():
    """What the engine thinks the book looks like, for the gaps panel header."""
    from .models import Enquiry

    enquiries = list(Enquiry.objects.all())
    spread = {"Hot": 0, "Warm": 0, "Cold": 0}
    for customer in Customer.objects.prefetch_related("outreach_log", "occasions"):
        spread[computed_temp(customer, enquiries)[0]] += 1
    return spread


def search(query, limit=8):
    """The ⌘K overlay: customers, enquiries, orders, repairs, materials."""
    from .models import ClientMaterial, Enquiry, Order, Repair

    query = (query or "").strip()
    if not query:
        return []
    sections = [
        (
            "Customers",
            Customer.objects.filter(
                Q(name__icontains=query) | Q(customer_code__icontains=query) | Q(mobile__icontains=query)
            )[:limit],
            lambda row: (row.name, row.customer_code, "crm:customer_detail", row.pk),
        ),
        (
            "Enquiries",
            Enquiry.objects.filter(
                Q(enquiry_code__icontains=query) | Q(item_of_interest__icontains=query)
            ).select_related("customer")[:limit],
            lambda row: (row.enquiry_code, row.item_of_interest, "crm:enquiry_detail", row.pk),
        ),
        (
            "Orders",
            Order.objects.filter(
                Q(order_code__icontains=query) | Q(item_description__icontains=query)
            ).select_related("customer")[:limit],
            lambda row: (row.order_code, row.item_description, "crm:order_detail", row.pk),
        ),
        (
            "Repairs",
            Repair.objects.filter(
                Q(repair_code__icontains=query) | Q(item_description__icontains=query)
            ).select_related("customer")[:limit],
            lambda row: (row.repair_code, row.item_description, "crm:repair_detail", row.pk),
        ),
        (
            "Client materials",
            ClientMaterial.objects.filter(
                Q(cm_code__icontains=query) | Q(jewellery_description__icontains=query)
            ).select_related("customer")[:limit],
            lambda row: (row.cm_code, row.jewellery_description, "crm:client_material_detail", row.pk),
        ),
    ]
    results = []
    for title, rows, shape in sections:
        hits = [dict(zip(("title", "sub", "url_name", "pk"), shape(row))) for row in rows]
        if hits:
            results.append({"section": title, "rows": hits})
    return results
