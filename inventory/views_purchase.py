"""Record a purchase: the prototype's screen, posting through ``ledger_purchase``."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone

from stock.masking import mask
from stock.models import Vendor
from stock.services import ServiceError, require

from . import dia_services, inputs, ledger, ledger_purchase
from .models import Batch
from .views import _client, _everything, _page

FIELDS = ("batch", "pouch_no", "stone_name", "shape", "colour", "pcs", "ct", "cost")
#: the prototype's Stock control card: everything that moves stock
STOCK_CONTROL = ["Purchase", "Purchase Return", "Sale", "Sales Return", "Memo Out", "Memo In", "Job Work Out",
                 "Job Work In", "Consumed in Production", "Wastage / Loss in Process", "Breakage", "Split", "Merge",
                 "Transfer", "Sample", "Recount Adjustment"]
#: the prototype's Price list card
PRICE_LIST = [("Cost per carat", "from the purchase"), ("Landed cost", "+ freight, duty, cutting"),
              ("Current valuation", "set on revaluation"), ("Selling / list price", "set separately"),
              ("Realised price", "from each sale")]


def _typed(post):
    """The lines as typed, a dict per row; a row left wholly blank is no line."""
    rows = [dict(zip(FIELDS, values)) for values in zip(*(post.getlist(name) for name in FIELDS))]
    return [row for row in rows if any((value or "").strip() for value in row.values())]


def _lines(rows):
    codes = {(row["batch"] or "").strip().upper() for row in rows}
    batches = {batch.code: batch for batch in Batch.objects.filter(code__in=codes)}
    lines = []
    for row in rows:
        code = (row["batch"] or "").strip().upper()
        lines.append(ledger_purchase.PurchaseLine(
            batch=batches.get(code, code),           # a new code: the purchase creates the batch
            pouch_no=row["pouch_no"] or "", stone_name=(row["stone_name"] or "").strip(),
            shape=(row["shape"] or "").strip(), colour=(row["colour"] or "").strip(),
            pcs=inputs.whole(row["pcs"], "Pieces"), ct=inputs.decimal(row["ct"], "Weight"),
            cost_per_ct=inputs.decimal(row["cost"], "Cost / ct"),
        ))
    return lines


def _supplier(user, post):
    raw = post.get("supplier") or ""
    if raw == "new":
        return dia_services.save_supplier(user, None, post.get("new_code"), post.get("new_name"), "", "")
    return Vendor.objects.filter(pk=raw, is_active=True).first() if raw.isdigit() else None


@login_required
def purchase(request):
    if _client(request):
        return redirect("inventory:shelf")
    for permission in ledger_purchase.PURCHASE_RIGHTS:
        require(request.user, permission, "Recording a purchase needs the purchase right and sight of cost and suppliers.")
    form, rows, error = {}, [dict.fromkeys(FIELDS, "")], None
    if request.method == "POST":
        form, rows = request.POST, _typed(request.POST) or rows
        try:
            with transaction.atomic():           # a new supplier stands or falls with its purchase
                currency = form.get("currency", "INR")
                header = ledger_purchase.PurchaseHeader(
                    supplier=_supplier(request.user, form),
                    occurred_on=inputs.day(form.get("occurred_on"), "Purchase date") or timezone.localdate(),
                    invoice_no=form.get("invoice_no", ""), currency=currency,
                    fx_rate=inputs.decimal(form.get("fx_rate"), "Rate to INR") if currency == "USD" else None,
                    landed_extras=inputs.decimal(form.get("landed_extras"), "Landed extras") or Decimal("0"),
                    note=form.get("note", ""),
                )
                document = ledger_purchase.post_purchase(request.user, header, _lines(_typed(form)))
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            messages.success(request, f"Purchase {document.number} posted.")
            return redirect("inventory:document", pk=document.pk)
    return _page(
        request, "inventory/purchase.html", _everything(request), tab="purchase", form=form, lines=rows, error=error,
        suppliers=[mask(request.user, {"pk": v.pk, "vendor_name": v.name})
                   for v in Vendor.objects.filter(is_active=True).order_by("name")],
        next_numbers=ledger.next_pouch_numbers(), today=timezone.localdate().isoformat(),
        stock_control=STOCK_CONTROL, price_list=PRICE_LIST,
    )
