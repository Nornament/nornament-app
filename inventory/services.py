"""Every write to the inventory, and the one query that reads a pouch's stock.

Quantities are sums of movements and value is carats × the latest valuation, so
``stocked`` is how every screen reads a pouch: one query, with pieces, carats and
rate annotated.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from accounts.capabilities import INV_MASTERS, VIEW_COST, VIEW_SALE
from stock.services import ServiceError, log, require

from .models import Movement, Pouch, PriceEntry, balance

DETAIL_FIELDS = ("treatment", "origin", "purchase_date", "supplier")


def _by(user):
    return user if getattr(user, "is_authenticated", False) else None


def stocked(queryset=None):
    """Pouches with ``on_pcs``, ``on_ct`` and ``rate`` (the latest valuation)."""
    latest = (
        PriceEntry.objects.filter(pouch=OuterRef("pk"), kind=PriceEntry.VALUATION)
        .order_by("-effective_from", "-pk")
        .values("rate")[:1]
    )
    queryset = Pouch.objects.all() if queryset is None else queryset
    # ordered here, not by Meta: the aggregate drops Meta.ordering, and every
    # screen groups in arrival order, so batches by code and pouches as imported
    return queryset.select_related("batch__box_colour", "supplier").annotate(
        on_pcs=balance("pcs"), on_ct=balance("ct"), rate=Subquery(latest)
    ).order_by("batch__code", "pk")


def value_of(pouch):
    """Carats on hand × rate. ``None`` when either is missing — never zero."""
    if pouch.on_ct is None or pouch.rate is None:
        return None
    return pouch.on_ct * pouch.rate


def latest_price(pouch, kind):
    return pouch.prices.filter(kind=kind).order_by("-effective_from", "-pk").first()


def _check_quantities(pcs, ct, rate=None):
    if (pcs is not None and pcs < 0) or (ct is not None and ct < 0):
        raise ServiceError("A quantity cannot be negative; the direction says which way it moves.")
    if rate is not None and rate < 0:
        raise ServiceError("A rate cannot be negative.")


def _last_ref_number():
    # ponytail: read-the-max under the caller's transaction; the unique index
    # catches a race. Move to a DB sequence if two people ever create at once.
    last = Pouch.objects.order_by("-ref").values_list("ref", flat=True).first()
    return int(last[4:]) if last else 0


@transaction.atomic
def open_pouches(user, specs, import_batch=None):
    """Create pouches with an Opening Balance and, where there is one, a valuation.

    ``specs`` is a list of ``(batch, fields, pcs, ct, rate)``. Bulk, because an
    import opens three thousand of these and one request has to finish.
    """
    require(user, INV_MASTERS, "Only a role that edits inventory records can add stock.")
    number, now, today, by = _last_ref_number(), timezone.now(), timezone.localdate(), _by(user)
    pouches = []
    for batch, fields, pcs, ct, rate in specs:
        _check_quantities(pcs, ct, rate)
        number += 1
        pouches.append(Pouch(
            ref=f"NRN-{number:06d}", batch=batch, import_batch=import_batch,
            **{"countable": pcs is not None, **fields},
        ))
    Pouch.objects.bulk_create(pouches)
    Movement.objects.bulk_create([
        Movement(pouch=pouch, reason=Movement.Reason.OPENING_BALANCE, direction=Movement.IN,
                 pcs=pcs, ct=ct, occurred_at=now, recorded_by=by, ref=pouch.src)
        for pouch, (_, _, pcs, ct, _) in zip(pouches, specs)
    ])
    PriceEntry.objects.bulk_create([
        PriceEntry(pouch=pouch, kind=PriceEntry.VALUATION, rate=rate, effective_from=today, set_by=by)
        for pouch, (_, _, _, _, rate) in zip(pouches, specs) if rate is not None
    ])
    if pouches:
        log(user, "INSERT", "inv_pouch", f"{pouches[0].ref}..{pouches[-1].ref}", f"{len(pouches)} pouches opened")
    return pouches


def open_pouch(user, batch, fields, pcs, ct, rate, import_batch=None):
    return open_pouches(user, [(batch, fields, pcs, ct, rate)], import_batch)[0]


def save_details(user, pouch, **changes):
    """Treatment, origin, purchase date and supplier — the four fields the record adds."""
    require(user, INV_MASTERS, "Only a role that edits inventory records can save a pouch.")
    unknown = set(changes) - set(DETAIL_FIELDS)
    if unknown:
        raise ServiceError(f"{', '.join(sorted(unknown))} cannot be edited here.")
    old = {name: str(getattr(pouch, name) or "") for name in changes}
    for name, value in changes.items():
        setattr(pouch, name, value)
    try:
        pouch.full_clean(exclude=["batch", "import_batch"], validate_unique=False, validate_constraints=False)
    except ValidationError as error:
        raise ServiceError(error.messages[0]) from error
    pouch.save(update_fields=list(changes))
    log(user, "UPDATE", "inv_pouch", pouch.pk, str(pouch),
        old_values=old, new_values={name: str(getattr(pouch, name) or "") for name in changes})


def add_price(user, pouch, kind, rate, effective_from):
    require(user, INV_MASTERS, "Only a role that edits inventory records can set a price.")
    require(user, VIEW_SALE if kind == PriceEntry.LIST else VIEW_COST, "A price you may not see is not yours to set.")
    if kind not in dict(PriceEntry.KINDS):
        raise ServiceError(f"{kind} is not a kind of price.")
    _check_quantities(None, None, rate)
    entry = PriceEntry.objects.create(pouch=pouch, kind=kind, rate=rate, effective_from=effective_from, set_by=_by(user))
    log(user, "INSERT", "inv_price", entry.pk, f"{kind} {rate}/ct on {pouch}")
    return entry


#: what a group set may write: purchase prices come only from purchases
GROUP_KINDS = (PriceEntry.VALUATION, PriceEntry.LIST)


@transaction.atomic
def set_group_price(user, pouches, kind, rate, effective_from, described=""):
    """One dated price per pouch in a filtered group. Nothing is overwritten: each pouch gets its own row."""
    if kind not in GROUP_KINDS:
        raise ServiceError("A group sets a valuation or a list price; purchase prices come from purchases.")
    require(user, INV_MASTERS, "Only a role that edits inventory records can set a price.")
    require(user, VIEW_SALE if kind == PriceEntry.LIST else VIEW_COST, "A price you may not see is not yours to set.")
    # zero is refused here, unlike one pouch: a whole group at zero is a slip
    if rate is None or not rate.is_finite() or rate <= 0 or rate >= 10 ** 10:
        raise ServiceError("The rate has to be a number above zero, at most ten digits before the point.")
    if effective_from > timezone.localdate():
        raise ServiceError("A price cannot take effect in the future: the newest one is the current one.")
    pouches = list(pouches)
    if not pouches:
        raise ServiceError("No pouch matches these filters.")
    by = _by(user)
    entries = PriceEntry.objects.bulk_create([
        PriceEntry(pouch=pouch, kind=kind, rate=rate, effective_from=effective_from, set_by=by) for pouch in pouches
    ])
    detail = f"{kind} {rate}/ct on {len(pouches)} pouch{'es' if len(pouches) != 1 else ''}"
    log(user, "INSERT", "inv_price", entries[0].pk, f"{detail} ({described})" if described else detail)
    return len(pouches)


def recount_deltas(pouch, pcs, ct):
    """``(field, direction, quantity)`` for each counted figure that differs from the ledger.

    A figure of ``None`` means "not counted", never "zero". Pieces and carats
    can move in opposite directions (a recount finds more pieces but less
    weight), so each is its own adjustment.
    """
    _check_quantities(pcs, ct)
    held = stocked(Pouch.objects.filter(pk=pouch.pk)).get()
    deltas = []
    for field, counted, current in (("pcs", pcs, held.on_pcs), ("ct", ct, held.on_ct)):
        if counted is None or counted == (current or 0):
            continue
        delta = counted - (current or 0)
        deltas.append((field, Movement.IN if delta > 0 else Movement.OUT, abs(delta)))
    return deltas


@transaction.atomic
def recount(user, pouch, pcs, ct, note=""):
    """The importer's recount: bring the ledger to a counted figure, under the masters right.

    The Record movement form's Recount Adjustment posts the same differences on
    a document, through ``ledger_single.post_recount``.
    """
    require(user, INV_MASTERS, "Only a role that edits inventory records can recount.")
    moves = [
        Movement.objects.create(
            pouch=pouch, reason=Movement.Reason.RECOUNT_ADJUSTMENT, direction=direction, note=note,
            recorded_by=_by(user), **{"pcs": None, "ct": None, field: quantity},
        )
        for field, direction, quantity in recount_deltas(pouch, pcs, ct)
    ]
    if moves:
        log(user, "INSERT", "inv_movement", pouch.pk, f"recount of {pouch}: {len(moves)} adjustment(s)")
    return moves
