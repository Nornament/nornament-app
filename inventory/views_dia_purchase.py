"""Diamond purchases: the prototype's screen, posting through ``ledger_dia_purchase``.

Needs Record purchases with sight of cost and suppliers; any other role — or an
admin previewing one — sees "Not permitted". A refusal comes back on the form
with what was typed; a new supplier stands or falls with its purchase. Every
POST acts as the real login.
"""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.capabilities import ROLE_GROUPS
from stock.masking import mask
from stock.models import Vendor
from stock.services import ServiceError, require

from . import dia_services, inputs, ledger, ledger_dia_purchase
from .ledger_purchase import PURCHASE_RIGHTS, PurchaseHeader
from .models import DiamondLineCost, DiamondTerm, StockDocument
from .views_diamonds import dia_page, viewer

Kind, Status = StockDocument.Kind, StockDocument.Status
FIELDS = ("category", "shape", "colour", "clarity", "size_text", "batch_no", "pcs", "ct", "cost")
TONE = {Status.OPEN: "warn", Status.CLOSED: "good", Status.REVERSED: "crit"}
RECENT_CAP = 20


def _typed(post):
    """The lines as typed, a dict per row; a row left wholly blank is no line."""
    rows = [dict(zip(FIELDS, values)) for values in zip(*(post.getlist(name) for name in FIELDS))]
    return [row for row in rows if any((value or "").strip() for value in row.values())]


def _lines(rows):
    return [ledger_dia_purchase.DiaPurchaseLine(
        category=(row["category"] or "").strip(), shape=(row["shape"] or "").strip(),
        colour=(row["colour"] or "").strip(), clarity=(row["clarity"] or "").strip(),
        size_text=(row["size_text"] or "").strip(), pcs=inputs.whole(row["pcs"], "Pieces"),
        ct=inputs.decimal(row["ct"], "Carats"), cost_per_ct=inputs.decimal(row["cost"], "Cost / ct"),
        batch_no=(row["batch_no"] or "").strip(),
    ) for row in rows]


def _supplier(user, post):
    """The chosen supplier, or a new one saved by Settings' rule, inside the purchase's transaction."""
    raw = post.get("supplier") or ""
    if raw == "new":
        return dia_services.save_supplier(user, None, post.get("new_code"), post.get("new_name"), "", "")
    return Vendor.objects.filter(pk=raw, is_active=True).first() if raw.isdigit() else None


def _recent(user):
    """The latest diamond purchases: when, from whom, how many carats, at what landed cost.

    ponytail: the newest 20; page through when someone asks for more.
    """
    documents = list(StockDocument.objects.filter(kind=Kind.DIA_PURCHASE, reverses__isnull=True)
                     .select_related("vendor").prefetch_related("movements")
                     .order_by("-occurred_on", "-pk")[:RECENT_CAP])
    rates = {(c.document_id, c.line_id): c.cost_rate for c in DiamondLineCost.objects.filter(document__in=documents)}
    rows = []
    for d in documents:
        moves = list(d.movements.all())
        rows.append(mask(user, {
            "pk": d.pk, "number": d.number, "occurred_on": d.occurred_on, **ledger.party(d),
            "ct": sum((m.ct for m in moves), ledger.ZERO),
            "cost_amount": sum((m.ct * rates.get((d.pk, m.diamond_id), 0) for m in moves), ledger.ZERO),
            "status": d.get_status_display(), "tone": TONE[d.status], "reversed": d.status == Status.REVERSED,
        }))
    return rows


@login_required
def purchase(request):
    form, rows, error = {}, [dict.fromkeys(FIELDS, "")], None
    if request.method == "POST":
        for permission in PURCHASE_RIGHTS:
            require(request.user, permission,
                    "Recording a purchase needs the purchase right and sight of cost and suppliers.")
        form, rows = request.POST, _typed(request.POST) or rows
        try:
            with transaction.atomic():           # a new supplier stands or falls with its purchase
                currency = form.get("currency", "INR")
                header = PurchaseHeader(
                    supplier=_supplier(request.user, form),
                    occurred_on=inputs.day(form.get("occurred_on"), "Purchase date") or timezone.localdate(),
                    invoice_no=form.get("invoice_no", ""), currency=currency,
                    fx_rate=inputs.decimal(form.get("fx_rate"), "Rate to INR") if currency == "USD" else None,
                    landed_extras=inputs.decimal(form.get("landed_extras"), "Landed extras") or Decimal("0"),
                    note=form.get("note", ""),
                )
                document = ledger_dia_purchase.post_dia_purchase(request.user, header, _lines(_typed(form)))
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            messages.success(request, f"Purchase {document.number} posted.")
            return redirect("inventory:dia_purchase")
    user, role = viewer(request)
    role_label = ROLE_GROUPS[role]["name"]
    if not all(user.has_perm(permission) for permission in PURCHASE_RIGHTS):
        return dia_page(request, "inventory/diamonds/purchase.html", dtab="purchase", denied=True,
                        role_label=role_label)
    previewing = user is not request.user
    return dia_page(
        request, "inventory/diamonds/purchase.html", dtab="purchase", denied=False, role_label=role_label,
        can_post=not previewing, can_reverse=not previewing, form=form, lines=rows, error=error,
        suppliers=[mask(user, {"pk": v.pk, "vendor_name": v.name, "city": v.city})
                   for v in Vendor.objects.filter(is_active=True).order_by("name")],
        categories=dia_services.term_values(DiamondTerm.CATEGORY), shapes=dia_services.term_values(DiamondTerm.SHAPE),
        colours=dia_services.term_values(DiamondTerm.COLOUR), clarities=dia_services.term_values(DiamondTerm.CLARITY),
        recent=_recent(user), today=timezone.localdate().isoformat(),
    )


@login_required
@require_POST
def purchase_reverse(request, pk):
    for permission in PURCHASE_RIGHTS:
        require(request.user, permission, "Only a role that records purchases can reverse one.")
    doc = get_object_or_404(StockDocument, pk=pk, kind=Kind.DIA_PURCHASE, reverses__isnull=True)
    try:
        reversal = ledger.reverse_document(request.user, doc)
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
    else:
        messages.success(request, f"Reversed by {reversal.number}.")
    return redirect("inventory:dia_purchase")
