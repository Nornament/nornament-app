"""Diamond reads that every screen shares, and every diamond write.

Carats on hand are the sum of a line's movements (the stones' rule). Price is
the inventory's own rate card — the latest rate for the line's item code and
size, else for the code at any size — never the stock app's chart.
"""
from decimal import Decimal

from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Case, DecimalField, F, Sum, When
from django.utils import timezone
from openpyxl import load_workbook

from accounts.capabilities import INV_MASTERS, VIEW_COST, VIEW_SALE, VIEW_VENDOR
from stock.models import Vendor
from stock.services import ServiceError, log, require

from .dia_rules import canonical_code
from .models import DiamondCode, DiamondLine, DiamondRate, DiamondTerm, Movement

#: the prototype's seven rights, as the permissions they are
RIGHTS = [("view_cost", "See cost"), ("view_sale", "See sale"), ("view_margin", "See margin"),
          ("inv_purchase", "Post purchase"), ("inv_job", "Job cards"), ("inv_assort", "Assort"),
          ("inv_masters", "Edit settings")]
ROLE_ORDER = ["ADMIN", "ACCOUNTS", "SALES", "GRAPHIC", "PRODUCTION", "KARIGAR"]

#: IVY export: header on row 3, diamond band columns by position (the names repeat across bands)
IVY_HEADER_ROW, IVY_CODE, IVY_SIZE, IVY_COST, IVY_SALE = 3, 20, 26, 32, 33


def _by(user):
    return user if getattr(user, "is_authenticated", False) else None


def stocked_lines(queryset=None):
    signed = Case(
        When(movements__direction=Movement.OUT, then=-F("movements__ct")),
        default=F("movements__ct"),
        output_field=DecimalField(max_digits=14, decimal_places=4),
    )
    queryset = DiamondLine.objects.all() if queryset is None else queryset
    return queryset.select_related(
        "category", "band", "shape_override", "code__shape", "code__colour", "code__clarity"
    ).annotate(on_ct=Sum(signed)).order_by("pk")


def rate_table():
    """The current rate per (code, size), per field: later effective dates, then later rows,
    win, but only for the field a row actually sets — a cost-only row never hides an earlier
    sale rate."""
    table = {}
    for rate in DiamondRate.objects.order_by("effective_from", "pk"):
        entry = table.setdefault((rate.code_id, rate.size_text), {"cost": None, "sale": None})
        if rate.cost_rate is not None:
            entry["cost"] = rate.cost_rate
        if rate.sale_rate is not None:
            entry["sale"] = rate.sale_rate
    return table


def price(line, rates):
    exact = rates.get((line.code_id, line.size_text), {})
    any_size = rates.get((line.code_id, ""), {})
    cost = exact.get("cost") if exact.get("cost") is not None else any_size.get("cost")
    sale = exact.get("sale") if exact.get("sale") is not None else any_size.get("sale")
    return cost, sale


def term(kind, value):
    found, _ = DiamondTerm.objects.get_or_create(kind=kind, value=value)
    return found


def _last_ref_number():
    # ponytail: read-the-max under the caller's transaction, as for pouches
    last = DiamondLine.objects.order_by("-ref").values_list("ref", flat=True).first()
    return int(last[4:]) if last else 0


@transaction.atomic
def open_lines(user, specs, import_batch=None):
    """New lines, each with an Opening Balance of its carats."""
    require(user, INV_MASTERS, "Only a role that edits inventory records can add stock.")
    number, now, by = _last_ref_number(), timezone.now(), _by(user)
    lines, weights, pieces = [], [], []
    for spec in specs:
        spec = dict(spec)
        ct = spec.pop("ct")
        pcs = spec.pop("pcs", None)
        if ct is not None and ct < 0:
            raise ServiceError("A weight cannot be negative.")
        number += 1
        lines.append(DiamondLine(ref=f"NRD-{number:06d}", import_batch=import_batch, **spec))
        weights.append(ct)
        pieces.append(pcs)
    DiamondLine.objects.bulk_create(lines)
    Movement.objects.bulk_create([
        Movement(diamond=line, reason=Movement.Reason.OPENING_BALANCE, direction=Movement.IN,
                 pcs=pcs, ct=ct, occurred_at=now, recorded_by=by, ref=line.src)
        for line, ct, pcs in zip(lines, weights, pieces)
    ])
    if lines:
        log(user, "INSERT", "inv_dia_line", f"{lines[0].ref}..{lines[-1].ref}", f"{len(lines)} diamond lines opened")
    return lines


def recount_line(user, line, ct, note=""):
    require(user, INV_MASTERS, "Only a role that edits inventory records can recount.")
    if ct is None or ct < 0:
        raise ServiceError("A counted weight has to be zero or more.")
    held = stocked_lines(DiamondLine.objects.filter(pk=line.pk)).get().on_ct or Decimal("0")
    if ct == held:
        return None
    move = Movement.objects.create(
        diamond=line, reason=Movement.Reason.RECOUNT_ADJUSTMENT, direction=Movement.IN if ct > held else Movement.OUT,
        ct=abs(ct - held), note=note, recorded_by=_by(user),
    )
    log(user, "INSERT", "inv_movement", line.pk, f"recount of {line.ref}: {held} → {ct} ct")
    return move


def _in_use(t):
    if t.kind == DiamondTerm.CATEGORY:
        return DiamondLine.objects.filter(category=t).exists()
    if t.kind == DiamondTerm.BAND:
        return DiamondLine.objects.filter(band=t).exists()
    if t.kind == DiamondTerm.SHAPE:
        return DiamondCode.objects.filter(shape=t).exists() or DiamondLine.objects.filter(shape_override=t).exists()
    field = "colour" if t.kind == DiamondTerm.COLOUR else "clarity"
    return DiamondCode.objects.filter(**{field: t}).exists()


def add_term(user, kind, value):
    require(user, INV_MASTERS, "Only a role that edits settings can add a value.")
    value = (value or "").strip()
    if kind not in dict(DiamondTerm.KINDS) or not value:
        raise ServiceError("A value needs a list and a name.")
    if DiamondTerm.objects.filter(kind=kind, value=value).exists():
        raise ServiceError(f"{value} is already on the list.")
    created = DiamondTerm.objects.create(kind=kind, value=value)
    log(user, "INSERT", "inv_dia_term", created.pk, f"{kind}: {value}")
    return created


def rename_term(user, t, value):
    require(user, INV_MASTERS, "Only a role that edits settings can rename a value.")
    value = (value or "").strip()
    if not value:
        raise ServiceError("A value cannot be blank.")
    if DiamondTerm.objects.filter(kind=t.kind, value=value).exclude(pk=t.pk).exists():
        raise ServiceError(f"{value} is already on the list.")
    old, t.value = t.value, value
    t.save(update_fields=["value"])
    log(user, "UPDATE", "inv_dia_term", t.pk, f"{t.kind}: {old} → {value}")


def delete_term(user, t):
    require(user, INV_MASTERS, "Only a role that edits settings can delete a value.")
    if _in_use(t):
        raise ServiceError(f"{t.value} is in use and cannot be deleted.")
    log(user, "DELETE", "inv_dia_term", t.pk, f"{t.kind}: {t.value}")
    t.delete()


def set_expansion(user, t, grades_text):
    require(user, INV_MASTERS, "Only a role that edits settings can change an expansion.")
    grades = (grades_text or "").split()
    known = set(DiamondTerm.objects.filter(kind=t.kind, expands_to="").values_list("value", flat=True))
    unknown = [g for g in grades if g not in known]
    if unknown:
        raise ServiceError(f"Not a single {t.kind} grade: {', '.join(unknown)}.")
    t.expands_to = " ".join(grades)
    t.save(update_fields=["expands_to"])
    log(user, "UPDATE", "inv_dia_term", t.pk, f"{t.value} expands to {t.expands_to or 'nothing'}")


def save_code(user, code, shape, colour, clarity, confirmed, note):
    require(user, INV_MASTERS, "Only a role that edits settings can change an item code.")
    for value, kind in ((shape, DiamondTerm.SHAPE), (colour, DiamondTerm.COLOUR), (clarity, DiamondTerm.CLARITY)):
        if value is not None and value.kind != kind:
            raise ServiceError(f"{value} is not a {kind}.")
    code.shape, code.colour, code.clarity = shape, colour, clarity
    code.confirmed, code.note = bool(confirmed), (note or "").strip()[:120]
    code.save()
    log(user, "UPDATE", "inv_dia_code", code.pk, f"{code.pk}: {shape} / {colour} / {clarity}, confirmed={code.confirmed}")


def _rate(value):
    if value is None:
        return None
    value = Decimal(value)
    if not value.is_finite() or value < 0 or abs(value) >= 10 ** 10:
        raise ServiceError("A rate has to be a number from 0 up to ten digits.")
    return value


def set_rate(user, code, size_text, cost_rate, sale_rate, effective_from):
    """A new dated row; nothing overwritten. A row carries both rates, so both rights are needed."""
    require(user, INV_MASTERS, "Only a role that edits settings can set a rate.")
    require(user, VIEW_COST, "A cost you may not see is not yours to set.")
    require(user, VIEW_SALE, "A sale price you may not see is not yours to set.")
    rate = DiamondRate.objects.create(
        code=code, size_text=(size_text or "").strip(), cost_rate=_rate(cost_rate), sale_rate=_rate(sale_rate),
        effective_from=effective_from or timezone.localdate(), set_by=_by(user),
    )
    log(user, "INSERT", "inv_dia_rate", rate.pk, f"{code.pk} {rate.size_text or 'any size'}")
    return rate


def load_ivy_rates(user, fileobj):
    """Rates from the IVY export file (not the stock app): item code, size, cost and sale rate."""
    require(user, INV_MASTERS, "Only a role that edits settings can load rates.")
    require(user, VIEW_COST, "A cost you may not see is not yours to set.")
    require(user, VIEW_SALE, "A sale price you may not see is not yours to set.")
    sheet = load_workbook(fileobj, read_only=True, data_only=True).active
    codes = set(DiamondCode.objects.values_list("item_code", flat=True))
    found, unknown = {}, set()
    for values in sheet.iter_rows(min_row=IVY_HEADER_ROW + 1, values_only=True):
        values = list(values) + [None] * 40
        code = canonical_code(str(values[IVY_CODE] or ""))
        if not code or values[IVY_COST] is None and values[IVY_SALE] is None:
            continue
        if code not in codes:
            unknown.add(code)
            continue
        size = str(values[IVY_SIZE] or "").strip()
        found[(code, size)] = (values[IVY_COST], values[IVY_SALE])
    today = timezone.localdate()
    with transaction.atomic():
        for (code, size), (cost, sale) in found.items():
            DiamondRate.objects.create(code_id=code, size_text=size, effective_from=today, set_by=_by(user),
                                       cost_rate=_rate(None if cost is None else str(cost)),
                                       sale_rate=_rate(None if sale is None else str(sale)))
    log(user, "IMPORT", "inv_dia_rate", "-", f"{len(found)} rates from the IVY export, {len(unknown)} unknown codes")
    return {"loaded": len(found), "unknown": len(unknown)}


def save_supplier(user, vendor, code, name, city, terms):
    require(user, INV_MASTERS, "Only a role that edits settings can change suppliers.")
    require(user, VIEW_VENDOR, "A supplier you may not see is not yours to change.")
    code, name = (code or "").strip().upper(), (name or "").strip()
    if not code or not name:
        raise ServiceError("A supplier needs a code and a name.")
    clash = Vendor.objects.filter(code=code)
    if vendor is not None:
        clash = clash.exclude(pk=vendor.pk)
    if clash.exists():
        raise ServiceError(f"Supplier code {code} is already used.")
    vendor = vendor or Vendor()
    vendor.code, vendor.name, vendor.city, vendor.terms = code, name, (city or "").strip(), (terms or "").strip()
    vendor.save()
    log(user, "UPDATE", "vendor", vendor.pk, f"{vendor.code} {vendor.name}")
    return vendor


def set_right(user, role, codename, on):
    """Tick or untick one right for one role. Admins only; the Admin role is never edited."""
    if not (user and user.is_authenticated and user.is_admin()):
        raise PermissionDenied("Only an admin can change user rights.")
    if role == "ADMIN":
        raise ServiceError("The Admin role always holds every right.")
    if role not in ROLE_ORDER or codename not in dict(RIGHTS):
        raise ServiceError("Unknown role or right.")
    group = Group.objects.get(name=role)
    permission = Permission.objects.get(codename=codename, content_type__app_label="accounts")
    (group.permissions.add if on else group.permissions.remove)(permission)
    log(user, "UPDATE", "auth_group", group.pk, f"{role}: {codename} {'on' if on else 'off'}")
