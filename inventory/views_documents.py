"""A document's page: what it is, what moved on it, what is still out, and its actions.

Readable by every internal login, masked like every other screen; the actions
— settle, undo the last entry, reverse — need the right for the document's kind.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from stock.masking import mask
from stock.services import ServiceError

from . import inputs, ledger, ledger_jobs
from .models import Pouch, PriceEntry, StockDocument
from .views import _client, _everything, _page

Kind, Status = StockDocument.Kind, StockDocument.Status
#: how an open document's outstanding pouches are settled, in the prototype's words
SETTLE_CHOICES = {Kind.JOB_WORK: [("in", "Received back"), ("consumed", "Consumed"), ("loss", "Loss")],
                  Kind.MEMO: [("in", "Returned"), ("sold", "Sold")]}
TONE = {Status.OPEN: "warn", Status.CLOSED: "good", Status.REVERSED: "crit"}
SYMBOL = {1: ("＋", "in"), -1: ("−", "out"), 0: ("·", "adj")}


def _moves(user, doc):
    """The document's movements, oldest first; a purchase's carry the cost per carat it wrote."""
    bought = doc.kind == Kind.PURCHASE
    rates = dict(PriceEntry.objects.filter(kind=PriceEntry.PURCHASE, pouch__movements__document=doc)
                 .values_list("pouch", "rate")) if bought else {}
    rows = []
    for m in doc.movements.select_related("pouch__batch", "recorded_by").order_by("occurred_at", "pk"):
        symbol, cls = SYMBOL[m.effect]
        rows.append(mask(user, {
            "when": m.occurred_at, "ref": m.pouch.ref, "pouch": str(m.pouch), "reason": m.reason,
            "reversal": bool(m.reverses_id), "sym": symbol, "cls": cls, "pcs": m.pcs, "ct": m.ct, "note": m.note,
            "by": (m.recorded_by.full_name or m.recorded_by.get_username()) if m.recorded_by_id else "system",
            **({"purchase_rate": rates.get(m.pouch_id)} if bought else {}),
        }))
    return rows


@login_required
def document(request, pk):
    if _client(request):
        return redirect("inventory:shelf")
    doc = get_object_or_404(StockDocument.objects.select_related(
        "vendor", "customer", "reverses", "from_batch", "to_batch"), pk=pk)
    user = request.user
    owed = []
    if doc.kind in ledger.OPENABLE and doc.status == Status.OPEN:
        owed = ledger.owed_by_document([doc]).get(doc.pk, [])
    outstanding = [mask(user, {"pk": p.pk, "ref": p.ref, "pouch": str(p), "countable": p.countable,
                               "pcs": pcs if p.countable else None, "ct": ct,
                               "pouch_value": ct * p.rate if p.rate is not None else None})
                   for p, pcs, ct in owed]
    header = mask(user, {**ledger.party(doc), **({"cost_amount": doc.landed_extras} if doc.kind == Kind.PURCHASE else {})})
    may = user.has_perm(ledger.RIGHT_FOR_KIND[doc.kind])
    today = timezone.localdate()
    # Deviation from the brief (owner ruling, 2026-10-01): Undo works on an open OR
    # closed job work/memo, never only an open one, and never on a document that is
    # itself a reversal. The brief tied the Undo button to `can_settle` (which also
    # requires something outstanding) — that would hide Undo on a challan closed by
    # its own settlements. `can_undo` is its own flag, independent of what is left
    # outstanding.
    can_undo = (may and doc.kind in ledger.OPENABLE and doc.status in (Status.OPEN, Status.CLOSED)
                and not doc.reverses_id)
    return _page(
        request, "inventory/document.html", _everything(request), tab="recent", doc=doc, header=header,
        tone=TONE[doc.status], moves=_moves(user, doc), outstanding=outstanding,
        out_ct=sum((o["ct"] for o in outstanding), ledger.ZERO),
        overdue=doc.status == Status.OPEN and doc.expected_back is not None and doc.expected_back < today,
        can_settle=may and bool(outstanding), can_undo=can_undo, choices=SETTLE_CHOICES.get(doc.kind, []),
        can_reverse=may and doc.status != Status.REVERSED and not doc.reverses_id,
        reversed_by=StockDocument.objects.filter(reverses=doc).first(), today=today.isoformat(),
    )


def _back(pk):
    return redirect("inventory:document", pk=pk)


@login_required
@require_POST
def document_settle(request, pk):
    if _client(request):
        return redirect("inventory:shelf")
    doc = get_object_or_404(StockDocument, pk=pk)
    raw = request.POST.get("pouch") or ""
    pouch = Pouch.objects.filter(pk=raw).first() if raw.isdigit() else None
    settle = ledger_jobs.settle_job_work if doc.kind == Kind.JOB_WORK else ledger_jobs.settle_memo
    try:
        if pouch is None:
            raise ServiceError("Choose the pouch to settle.")
        settle(request.user, doc, pouch, request.POST.get("how", ""), inputs.whole(request.POST.get("pcs"), "Pieces"),
               inputs.decimal(request.POST.get("ct"), "Weight"), inputs.day(request.POST.get("occurred_on")),
               (request.POST.get("note") or "").strip())
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
    else:
        messages.success(request, "Posted.")
    return _back(pk)


@login_required
@require_POST
def document_undo(request, pk):
    if _client(request):
        return redirect("inventory:shelf")
    doc = get_object_or_404(StockDocument, pk=pk)
    try:
        move = ledger.undo_last(request.user, doc)
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
    else:
        messages.success(request, f"Undone: {move.reason}.")
    return _back(pk)


@login_required
@require_POST
def document_reverse(request, pk):
    if _client(request):
        return redirect("inventory:shelf")
    doc = get_object_or_404(StockDocument, pk=pk)
    try:
        reversal = ledger.reverse_document(request.user, doc, (request.POST.get("note") or "").strip())
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
    else:
        messages.success(request, f"Reversed by {reversal.number}.")
    return _back(pk)
