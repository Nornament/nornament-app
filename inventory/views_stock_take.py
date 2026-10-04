"""The stock-take screens (part 5d): the list with its start form, and the count sheet.

Stones render in the stones shell and are never reachable in client view; diamonds render through
``dia_page`` and honour the admin preview, which masks as the role and hides every form."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect

from accounts.capabilities import INV_MOVE
from stock.masking import mask
from stock.services import ServiceError, require

from . import dia_services, inputs, ledger, stock_take
from .models import Batch, BoxColour, StockDocument, StockTake
from .views import _client, _everything, _page

CONFIRM = {"close": "Close and post the counted differences?", "cancel": "Cancel this stock take? Nothing is posted.",
           "reverse": "Reverse the recount this stock take posted?"}


def _sheet_rows(user, take):
    """One masked row per owner on the sheet: book at count for a counted row, live book otherwise."""
    counts = {c.pouch_id or c.diamond_id: c for c in take.counts.all()}
    rates = dia_services.rate_table() if take.side == StockTake.DIAMONDS else None
    rows = []
    for owner in stock_take.owners(take):
        c = counts.get(owner.pk)
        var_pcs, var_ct = stock_take.variances(c) if c else (None, None)
        if rates is not None:
            rate = dia_services.price(owner, rates)[0]
            stone = " · ".join(v for v in (owner.shape and owner.shape.value, owner.colour and owner.colour.value,
                                           owner.code.clarity and owner.code.clarity.value) if v)
            countable, label = False, f"{owner.ref} · {owner.code.item_code}"
        else:
            rate, stone, countable, label = owner.rate, owner.stone_name, owner.countable, str(owner)
        rows.append(mask(user, {
            "pk": owner.pk, "ref": owner.ref, "label": label, "stone": stone, "size": owner.size_text,
            "countable": countable,
            "book_pcs": c.book_pcs if c and c.counted_pcs is not None else (owner.on_pcs if countable else None),
            "book_ct": c.book_ct if c else (owner.on_ct or ledger.ZERO),
            "counted_pcs": c.counted_pcs if c else None, "counted_ct": c.counted_ct if c else None,
            "var_pcs": var_pcs, "var_ct": var_ct,
            "cost_amount": var_ct * rate if var_ct is not None and rate is not None else None,
        }))
    return rows


def _frozen_rows(user, take):
    """A closed or cancelled stock take reads its frozen result: quantities only, never recomputed (no money:
    the value of a variance belongs to the day it was counted)."""
    rows = []
    for r in (take.result or {}).get("rows", []):
        dec = {k: (Decimal(r[k]) if r.get(k) is not None else None) for k in ("book_ct", "counted_ct", "var_ct")}
        rows.append({**r, **dec, "stone": "", "size": "", "countable": r.get("book_pcs") is not None})
    return rows


def _totals(rows):
    out = {"counted": sum(1 for r in rows if r["counted_pcs"] is not None or r["counted_ct"] is not None),
           "total": len(rows), "var_ct": sum((r["var_ct"] for r in rows if r["var_ct"] is not None), ledger.ZERO)}
    if rows and "cost_amount" in rows[0]:
        out["cost_amount"] = sum((r["cost_amount"] for r in rows if r.get("cost_amount") is not None), ledger.ZERO)
    return out


def _entries(post, rows):
    return {r["pk"]: (inputs.whole(post.get(f"pcs_{r['pk']}"), "Pieces"), inputs.decimal(post.get(f"ct_{r['pk']}"), "Carats"))
            for r in rows if f"ct_{r['pk']}" in post or f"pcs_{r['pk']}" in post}


def _act(request, take, rows):
    """Handle a POST on the sheet. Returns (redirect or None, error, confirming)."""
    require(request.user, INV_MOVE, stock_take.RIGHT)
    action = request.POST.get("action")
    try:
        entries = _entries(request.POST, rows)
        if entries and take.status == StockTake.OPEN:
            stock_take.save_counts(request.user, take, entries)
        if action in CONFIRM and request.POST.get("confirm") != "1":
            return None, None, action
        if action == "close":
            stock_take.close(request.user, take)
            messages.success(request, f"{take.number} closed.")
        elif action == "cancel":
            stock_take.cancel(request.user, take)
            messages.success(request, f"{take.number} cancelled.")
        elif action == "reverse":
            reversal = stock_take.reverse(request.user, take)
            messages.success(request, f"{take.number}'s recount reversed by {reversal.number}.")
        else:
            messages.success(request, "Counts saved.")
    except ServiceError as refused:
        return None, refused.messages[0], None
    return redirect(request.path), None, None


def _context(user, take):
    rows = _sheet_rows(user, take) if take.status == StockTake.OPEN else _frozen_rows(user, take)
    reversed_ = bool(take.document_id and take.document.status == StockDocument.Status.REVERSED)
    return {"take": take, "scope": stock_take.scope_label(take), "rows": rows, "totals": _totals(rows),
            "reversed": reversed_}


@login_required
def stock_takes(request):
    if _client(request):
        return redirect("inventory:shelf")
    error = None
    if request.method == "POST":
        require(request.user, INV_MOVE, stock_take.RIGHT)
        colour = request.POST.get("box_colour") or ""
        batch = request.POST.get("batch") or ""
        try:
            take = stock_take.start(request.user, StockTake.STONES,
                                    box_colour=BoxColour.objects.filter(pk=colour).first() if colour else None,
                                    batch=Batch.objects.filter(code=batch).first() if batch else None)
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            return redirect("inventory:stock_take", pk=take.pk)
    takes = StockTake.objects.filter(side=StockTake.STONES).select_related("box_colour", "batch", "started_by",
                                                                             "closed_by", "document")
    return _page(request, "inventory/stock_takes.html", _everything(request), tab="stock_take", error=error,
                 takes=_listed(takes), colours=BoxColour.objects.all(), batches=Batch.objects.order_by("code"),
                 may=request.user.has_perm(INV_MOVE))


def _listed(takes):
    order = {StockTake.OPEN: 0}
    rows = [{"take": t, "scope": stock_take.scope_label(t), "counted": t.n}
            for t in takes.annotate(n=Count("counts"))]
    return sorted(rows, key=lambda r: (order.get(r["take"].status, 1), -r["take"].started_at.timestamp()))


@login_required
def stock_take_sheet(request, pk):
    if _client(request):
        return redirect("inventory:shelf")
    take = get_object_or_404(StockTake.objects.select_related("box_colour", "batch", "document"), pk=pk,
                             side=StockTake.STONES)
    error = confirming = None
    if request.method == "POST":
        done, error, confirming = _act(request, take, _sheet_rows(request.user, take))
        if done:
            return done
        take.refresh_from_db()
    may = request.user.has_perm(INV_MOVE)
    return _page(request, "inventory/stock_take.html", _everything(request), tab="stock_take",
                 error=error, confirming=confirming, confirm_message=CONFIRM.get(confirming), may=may,
                 previewing=False, editable=take.status == StockTake.OPEN and may, **_context(request.user, take))
