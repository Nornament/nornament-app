"""The stock-take screens (part 5d): the list with its start form, and the count sheet.

Stones render in the stones shell and are never reachable in client view; diamonds render through
``dia_page`` and honour the admin preview, which masks as the role and hides every form."""
import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect

from accounts.capabilities import INV_MOVE
from stock.masking import allowed, mask
from stock.services import ServiceError, require

from . import dia_services, inputs, ledger, stock_take
from .models import Batch, BoxColour, DiamondTerm, StockDocument, StockTake
from .views import _client, _everything, _page
from .views_diamonds import dia_page, viewer

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
            countable = False
        else:
            rate, stone, countable = owner.rate, owner.stone_name, owner.countable
        rows.append(mask(user, {
            "pk": owner.pk, "ref": owner.ref, "label": stock_take.label(take, owner), "stone": stone,
            "size": owner.size_text, "countable": countable,
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
        rows.append({**r, **dec, "stone": "", "size": "", "countable": r.get("countable", False)})
    return rows


def _totals(user, rows):
    out = {"counted": sum(1 for r in rows if r["counted_pcs"] is not None or r["counted_ct"] is not None),
           "total": len(rows), "var_ct": sum((r["var_ct"] for r in rows if r["var_ct"] is not None), ledger.ZERO)}
    if allowed(user, "cost_amount"):
        out["cost_amount"] = sum((r["cost_amount"] for r in rows if r.get("cost_amount") is not None), ledger.ZERO)
    return out


def _shown(rows):
    """What the page shows right now, per row: JSON of pk → [pcs, ct] as the box reads them, or null."""
    return json.dumps({str(r["pk"]): [
        None if r.get("counted_pcs") is None else str(r["counted_pcs"]),
        None if r.get("counted_ct") is None else str(r["counted_ct"]),
    ] for r in rows})


def _entries(post, rows):
    """(entries, errors). Only a row whose posted pcs/ct differ from the hidden ``shown`` field — what
    the page displayed when it was rendered — is sent on; an untouched row never reaches ``save_counts``,
    so a stale page cannot wipe someone else's later save. A bad value is kept out of ``entries`` and
    named in ``errors`` by the row's own label, so nothing is lost and nothing is saved on a bad row."""
    shown = json.loads(post.get("shown") or "{}")
    entries, errors = {}, []
    for r in rows:
        pk = r["pk"]
        if f"ct_{pk}" not in post and f"pcs_{pk}" not in post:
            continue
        pcs_raw = (post.get(f"pcs_{pk}") or "").strip()
        ct_raw = (post.get(f"ct_{pk}") or "").strip()
        shown_pcs, shown_ct = shown.get(str(pk), [None, None])
        if (pcs_raw or None) == shown_pcs and (ct_raw or None) == shown_ct:
            continue                                            # untouched since the page was shown
        try:
            entries[pk] = (inputs.whole(pcs_raw, "Pieces"), inputs.decimal(ct_raw, "Carats"))
        except ServiceError as bad:
            errors.append(f"{r['label']} — {bad.messages[0]}")
    return entries, errors


def _overlay_posted(rows, post):
    """``rows`` with each box's posted text in place of the saved value, so a bad row's own typing
    (and everyone else's unsaved typing) survives the re-render that follows a rejected save."""
    out = []
    for r in rows:
        pk, row = r["pk"], dict(r)
        if f"pcs_{pk}" in post:
            row["counted_pcs"] = post.get(f"pcs_{pk}") or None
        if f"ct_{pk}" in post:
            row["counted_ct"] = post.get(f"ct_{pk}") or None
        out.append(row)
    return out


def _act(request, take, rows):
    """Handle a POST on the sheet. Returns (redirect or None, error, confirming, rows to show instead
    of the saved ones — only set when a bad value means nothing was saved)."""
    require(request.user, INV_MOVE, stock_take.RIGHT)
    action = request.POST.get("action")
    entries, errors = _entries(request.POST, rows)
    if errors:
        return None, " · ".join(errors), None, _overlay_posted(rows, request.POST)
    try:
        if entries and take.status == StockTake.OPEN:
            stock_take.save_counts(request.user, take, entries)
        if action in CONFIRM and request.POST.get("confirm") != action:
            return None, None, action, None
        if action == "close":
            stock_take.close(request.user, take)
            messages.success(request, f"{take.number} closed.")
        elif action == "cancel":
            stock_take.cancel(request.user, take)
            messages.success(request, f"{take.number} cancelled.")
        elif action == "reverse":
            reversal = stock_take.reverse(request.user, take)
            messages.success(request, f"{take.number}'s recount reversed by {reversal.number}.")
        elif action == "save":
            messages.success(request, "Counts saved.")
    except ServiceError as refused:
        return None, refused.messages[0], None, None
    return redirect(request.path), None, None, None


def _context(user, take):
    rows = _sheet_rows(user, take) if take.status == StockTake.OPEN else _frozen_rows(user, take)
    reversed_ = bool(take.document_id and take.document.status == StockDocument.Status.REVERSED)
    return {"take": take, "scope": stock_take.scope_label(take), "rows": rows, "totals": _totals(user, rows),
            "reversed": reversed_, "shown": _shown(rows) if take.status == StockTake.OPEN else None}


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
    rows = [{"take": t, "scope": stock_take.scope_label(t), "counted": t.n,
             "reversed": bool(t.document_id and t.document.status == StockDocument.Status.REVERSED)}
            for t in takes.annotate(n=Count("counts"))]
    return sorted(rows, key=lambda r: (order.get(r["take"].status, 1), -r["take"].started_at.timestamp()))


def _rows_for_post(request, take):
    """Entries are only meaningful on an open take; a closed or cancelled one renders no input
    boxes, so there is nothing to build a sheet of rows for."""
    return _sheet_rows(request.user, take) if take.status == StockTake.OPEN else []


@login_required
def stock_take_sheet(request, pk):
    if _client(request):
        return redirect("inventory:shelf")
    take = get_object_or_404(StockTake.objects.select_related("box_colour", "batch", "document"), pk=pk,
                             side=StockTake.STONES)
    error = confirming = posted_rows = None
    if request.method == "POST":
        done, error, confirming, posted_rows = _act(request, take, _rows_for_post(request, take))
        if done:
            return done
        take.refresh_from_db()
    may = request.user.has_perm(INV_MOVE)
    context = _context(request.user, take)
    if posted_rows is not None:
        context["rows"] = posted_rows
    return _page(request, "inventory/stock_take.html", _everything(request), tab="stock_take",
                 error=error, confirming=confirming, confirm_message=CONFIRM.get(confirming), may=may,
                 previewing=False, editable=take.status == StockTake.OPEN and may, **context)


@login_required
def dia_stock_takes(request):
    user, _ = viewer(request)
    previewing = user is not request.user
    error = None
    if request.method == "POST":
        require(request.user, INV_MOVE, stock_take.RIGHT)
        try:
            category_pk = int(request.POST.get("category") or 0)
        except ValueError:
            category_pk = None
        try:
            take = stock_take.start(request.user, StockTake.DIAMONDS,
                                    category=DiamondTerm.objects.filter(kind="category", pk=category_pk).first()
                                    if category_pk else None)
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            return redirect("inventory:dia_stock_take", pk=take.pk)
    takes = StockTake.objects.filter(side=StockTake.DIAMONDS).select_related("category", "started_by", "closed_by",
                                                                               "document")
    return dia_page(request, "inventory/diamonds/stock_takes.html", dtab="stock_take", error=error,
                    takes=_listed(takes), categories=DiamondTerm.objects.filter(kind="category").order_by("sort", "value"),
                    may=request.user.has_perm(INV_MOVE) and not previewing)


@login_required
def dia_stock_take_sheet(request, pk):
    user, _ = viewer(request)
    previewing = user is not request.user
    take = get_object_or_404(StockTake.objects.select_related("category", "document"), pk=pk, side=StockTake.DIAMONDS)
    error = confirming = posted_rows = None
    if request.method == "POST":
        done, error, confirming, posted_rows = _act(request, take, _rows_for_post(request, take))
        if done:
            return done
        take.refresh_from_db()
    context = _context(user, take)
    if posted_rows is not None:
        context["rows"] = posted_rows
    may = request.user.has_perm(INV_MOVE) and not previewing
    return dia_page(request, "inventory/diamonds/stock_take.html", dtab="stock_take", error=error, confirming=confirming,
                    confirm_message=CONFIRM.get(confirming), may=may, previewing=previewing,
                    editable=take.status == StockTake.OPEN and may, **context)
