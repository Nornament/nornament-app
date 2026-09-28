"""Every write to the inventory, and the one query that reads a pouch's stock.

Quantities are sums of movements and value is carats × the latest valuation, so
``stocked`` is how every screen reads a pouch: one query, with pieces, carats and
rate annotated.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, F, OuterRef, Subquery, Sum, When
from django.utils import timezone

from accounts.capabilities import INV_MASTERS, VIEW_COST, VIEW_SALE
from stock.services import ServiceError, log, require

from .models import Movement, Pouch, PriceEntry

DETAIL_FIELDS = ("treatment", "origin", "purchase_date", "supplier")


def _by(user):
    return user if getattr(user, "is_authenticated", False) else None


def _signed(field):
    # ponytail: Django 5.2 won't infer a mixed IntegerField/PositiveIntegerField
    # Case output; the model's own field type settles it.
    output_field = Movement._meta.get_field(field)
    return Case(
        When(movements__direction=Movement.OUT, then=-F(f"movements__{field}")),
        default=F(f"movements__{field}"),
        output_field=output_field,
    )


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
        on_pcs=Sum(_signed("pcs")), on_ct=Sum(_signed("ct")), rate=Subquery(latest)
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


@transaction.atomic
def recount(user, pouch, pcs, ct, note=""):
    """Bring the ledger to a counted figure: one adjustment per quantity that differs.

    Pieces and carats can move in opposite directions (a recount finds more
    pieces but less weight), so each gets its own movement. A figure of ``None``
    means "not counted", never "zero".
    """
    require(user, INV_MASTERS, "Only a role that edits inventory records can recount.")
    _check_quantities(pcs, ct)
    held = stocked(Pouch.objects.filter(pk=pouch.pk)).get()
    moves = []
    for field, counted, current in (("pcs", pcs, held.on_pcs), ("ct", ct, held.on_ct)):
        if counted is None or counted == (current or 0):
            continue
        delta = counted - (current or 0)
        quantities = {"pcs": None, "ct": None, field: abs(delta)}
        moves.append(Movement.objects.create(
            pouch=pouch, reason=Movement.Reason.RECOUNT_ADJUSTMENT,
            direction=Movement.IN if delta > 0 else Movement.OUT, note=note, recorded_by=_by(user), **quantities,
        ))
    if moves:
        log(user, "INSERT", "inv_movement", pouch.pk, f"recount of {pouch}: {len(moves)} adjustment(s)")
    return moves
