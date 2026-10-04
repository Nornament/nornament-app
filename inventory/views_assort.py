"""Split pouch, Transfer to another batch, and Merge pouches — the assort screens.

Both need the assort right, neither is reachable in client view, and a refusal
comes back on the form with what was typed.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect

from accounts.capabilities import INV_ASSORT
from stock.services import ServiceError, require

from . import inputs, ledger, ledger_assort
from .models import Batch, Pouch
from .views import _client, _everything, _page

PART_FIELDS = ("pouch_no", "pcs", "ct", "size_text", "remarks")


def _typed_parts(post):
    """The destination rows as typed; a row left wholly blank is no pouch."""
    rows = [dict(zip(PART_FIELDS, values)) for values in zip(*(post.getlist(name) for name in PART_FIELDS))]
    return [row for row in rows if any((value or "").strip() for value in row.values())]


def _parts(rows):
    return [ledger_assort.SplitPart(pouch_no=row["pouch_no"] or "", pcs=inputs.whole(row["pcs"], "Pieces"),
                                    ct=inputs.decimal(row["ct"], "Carats"), size_text=(row["size_text"] or "").strip(),
                                    remarks=(row["remarks"] or "").strip())
            for row in rows]


def _assort(request, ref, message):
    """The pouch and its row, after the right and the client-view checks."""
    require(request.user, INV_ASSORT, message)
    obj = get_object_or_404(Pouch.objects.select_related("batch"), ref=ref)
    everything = _everything(request)
    return obj, everything, next(r for r in everything if r["pk"] == obj.pk)


@login_required
def split(request, ref):
    if _client(request):
        return redirect("inventory:shelf")
    source, everything, row = _assort(request, ref, "Only a role that assorts can split a pouch.")
    blank = {"pouch_no": ledger.next_pouch_no(source.batch), "pcs": "", "ct": "", "size_text": source.size_text,
             "remarks": ""}
    form = {"out_pcs": row["pcs"] if row["pcs"] is not None else "",
            "out_ct": ledger._ct(row["ct"]) if row["ct"] is not None else ""}
    parts, error = [blank], None
    if request.method == "POST":
        form, parts = request.POST, _typed_parts(request.POST) or [blank]
        try:
            document = ledger_assort.split_pouch(
                request.user, source, inputs.whole(form.get("out_pcs"), "Pieces out"),
                inputs.decimal(form.get("out_ct"), "Weight out"), _parts(_typed_parts(form)),
                inputs.whole(form.get("loss_pcs"), "Loss pieces"), inputs.decimal(form.get("loss_ct"), "Loss weight"),
                (form.get("note") or "").strip(),
            )
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            messages.success(request, f"Split posted as {document.number}.")
            return redirect("inventory:document", pk=document.pk)
    return _page(request, "inventory/split.html", everything, tab="tx", pouch_ref=source.ref, row=row,
                 form=form, parts=parts, error=error)


@login_required
def transfer(request, ref):
    if _client(request):
        return redirect("inventory:shelf")
    obj, everything, row = _assort(request, ref, "Only a role that assorts can re-file a pouch.")
    form, error = {}, None
    if request.method == "POST":
        form = request.POST
        code = (form.get("batch") or "").strip().upper()
        try:
            document = ledger_assort.transfer_pouch(request.user, obj, Batch.objects.filter(code=code).first(),
                                                    form.get("pouch_no"), (form.get("note") or "").strip())
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            messages.success(request, f"Re-filed as {obj} on {document.number}.")
            return redirect("inventory:pouch", ref=obj.ref)
    numbers = ledger.next_pouch_numbers()
    numbers.pop(obj.batch.code, None)
    return _page(request, "inventory/transfer.html", everything, tab="tx", pouch_ref=obj.ref, row=row,
                 form=form, error=error, next_numbers=numbers)


@login_required
def merge(request, ref):
    if _client(request):
        return redirect("inventory:shelf")
    opening, everything, row = _assort(request, ref, "Only a role that assorts can merge pouches.")
    found = ledger_assort.candidates(opening)
    by_pk = {r["pk"]: r for r in everything}
    ticked, into, error = {opening.pk}, str(opening.pk), None
    form = {"new_pouch_no": ledger.next_pouch_no(opening.batch), "size_text": opening.size_text}
    if request.method == "POST":
        form = request.POST
        ticked = {int(pk) for pk in form.getlist("pouch") if pk.isdigit()}
        into = form.get("into") or ""
        try:
            target = None if into == "new" else next((p for p in found if str(p.pk) == into), None)
            if into != "new" and target is None:
                raise ServiceError("Merge into one of the ticked pouches, or a new pouch.")
            document, rate = ledger_assort.merge_pouches(
                request.user, [p for p in found if p.pk in ticked], target, (form.get("new_pouch_no") or "").strip(),
                (form.get("size_text") or "").strip(), inputs.whole(form.get("loss_pcs"), "Loss pieces"),
                inputs.decimal(form.get("loss_ct"), "Loss weight"), (form.get("note") or "").strip(),
            )
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            unvalued = "" if rate is not None else " — no valuation set: one of the pouches had none."
            messages.success(request, f"Merge posted as {document.number}.{unvalued}")
            return redirect("inventory:document", pk=document.pk)
    return _page(request, "inventory/merge.html", everything, tab="tx", pouch_ref=opening.ref, row=row,
                 candidates=[by_pk[p.pk] for p in found] if len(found) > 1 else [], ticked=ticked, into=into,
                 form=form, error=error)
