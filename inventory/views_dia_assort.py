"""Diamond assortments: the prototype's must-balance ledger, working.

Seen and posted with the Assort right; any other role — or an admin previewing
one — sees "Not permitted". The form posts only when it balances, and a refusal
comes back on the form with what was typed. Every POST acts as the real login.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.capabilities import INV_ASSORT, ROLE_GROUPS
from stock.masking import mask
from stock.services import ServiceError, require

from . import dia_services, inputs, ledger, ledger_dia_assort
from .models import DiamondLine, DiamondTerm, Movement, StockDocument
from .views_diamonds import dia_page, viewer

Kind, Status, Reason = StockDocument.Kind, StockDocument.Status, Movement.Reason
DEST_FIELDS = ("shape", "colour", "clarity", "size_text", "ct", "cost")


def _typed(post):
    """The destination rows as typed; a row with nothing in it is no destination. A login without
    sight of cost has no cost column, so its rows are padded with blanks."""
    n = len(post.getlist("ct"))
    columns = [post.getlist(name) or [""] * n for name in DEST_FIELDS]
    rows = [dict(zip(DEST_FIELDS, values)) for values in zip(*columns)]
    return [row for row in rows if any((value or "").strip() for value in row.values())]


def _destinations(rows):
    return [ledger_dia_assort.Destination(
        shape=(row["shape"] or "").strip(), colour=(row["colour"] or "").strip(),
        clarity=(row["clarity"] or "").strip(), size_text=(row["size_text"] or "").strip(),
        ct=inputs.decimal(row["ct"], "Carats"), cost_per_ct=inputs.decimal(row["cost"], "Cost / ct"),
    ) for row in rows]


def _code(line):
    return f"{line.code_id} · {line.band.value}"


def _ledger(doc):
    """The prototype's ledger: the source debited with everything taken out of it, each destination
    credited, and the sorting loss a credit that settles the difference — so it runs to zero."""
    moves = list(doc.movements.filter(reverses__isnull=True).select_related("diamond__band").order_by("pk"))
    out = [m for m in moves if m.reason == Reason.ASSORT_OUT]
    loss = sum((m.ct for m in moves if m.reason == Reason.WASTAGE), ledger.ZERO)
    taken = sum((m.ct for m in out), loss)
    rows, running = [], taken
    if out:
        rows.append({"code": _code(out[0].diamond), "movement": "Assort out", "tone": "warn",
                     "note": f"source parcel · {out[0].diamond.ref}", "debit": taken, "running": running})
    for m in moves:
        if m.reason == Reason.ASSORT_IN:
            running -= m.ct
            rows.append({"code": _code(m.diamond), "movement": "Assort in", "tone": "good", "note": m.diamond.ref,
                         "credit": m.ct, "running": running})
    if loss:
        running -= loss
        rows.append({"code": "Sorting loss", "movement": "Sorting loss", "tone": "good", "note": "written off",
                     "credit": loss, "running": running})
    return rows, {"debit": taken, "credit": taken - running, "diff": running}


@login_required
def assorts(request):
    form, rows, error = {}, [], None
    if request.method == "POST":
        require(request.user, INV_ASSORT, "Only a role that assorts can post an assortment.")
        form, rows = request.POST, _typed(request.POST)
        raw = form.get("source") or ""
        source = DiamondLine.objects.filter(pk=raw).first() if raw.isdigit() else None
        try:
            doc = ledger_dia_assort.post_assortment(
                request.user, source, inputs.decimal(form.get("take_out"), "Take out"), _destinations(rows),
                inputs.decimal(form.get("loss"), "Sorting loss"), inputs.day(form.get("occurred_on")),
                form.get("note", ""),
            )
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            messages.success(request, f"Assortment {doc.number} posted.")
            return redirect(f"{reverse('inventory:dia_assorts')}?doc={doc.pk}")
    user, role = viewer(request)
    role_label = ROLE_GROUPS[role]["name"]
    if not user.has_perm(INV_ASSORT):
        return dia_page(request, "inventory/diamonds/assort.html", dtab="assort", denied=True, role_label=role_label)
    posted = list(StockDocument.objects.filter(kind=Kind.DIA_ASSORT, reverses__isnull=True)
                  .select_related("created_by").order_by("-occurred_on", "-pk"))
    raw = request.GET.get("doc", "")
    doc = next((d for d in posted if str(d.pk) == raw), posted[0] if posted else None)
    context = {}
    if doc is not None:
        lines, totals = _ledger(doc)
        by = (doc.created_by.full_name or doc.created_by.get_username()) if doc.created_by_id else "system"
        context = {"doc": doc, "ledger": lines, "totals": totals, "by": by}
    previewing = user is not request.user
    return dia_page(
        request, "inventory/diamonds/assort.html", dtab="assort", denied=False, role_label=role_label,
        posted=posted, can_post=not previewing,
        can_reverse=not previewing and doc is not None and doc.status != Status.REVERSED,
        form=form, dests=rows or [dict.fromkeys(DEST_FIELDS, "")], error=error,
        money=mask(user, {"cost_rate": None}), sources=dia_services.line_choices(),
        shapes=dia_services.term_values(DiamondTerm.SHAPE), colours=dia_services.term_values(DiamondTerm.COLOUR),
        clarities=dia_services.term_values(DiamondTerm.CLARITY), today=timezone.localdate().isoformat(), **context,
    )


@login_required
@require_POST
def assort_reverse(request, pk):
    require(request.user, INV_ASSORT, "Only a role that assorts can reverse an assortment.")
    doc = get_object_or_404(StockDocument, pk=pk, kind=Kind.DIA_ASSORT, reverses__isnull=True)
    try:
        reversal = ledger.reverse_document(request.user, doc)
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
    else:
        messages.success(request, f"Reversed by {reversal.number}.")
    return redirect(f"{reverse('inventory:dia_assorts')}?doc={doc.pk}")
