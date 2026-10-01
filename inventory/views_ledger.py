"""A pouch's Movements page, and its Record movement form.

The form is the prototype's card made to work: the reasons this login may post,
the fields each reason needs, and the checks the server will run. Every post
goes through the ledger services; a refusal comes back on the form with what
was typed still in it.
"""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.capabilities import INV_ASSORT, INV_JOB, INV_MOVE
from crm.models import Customer
from stock.masking import mask
from stock.models import Vendor
from stock.services import ServiceError

from . import dia_services, inputs, ledger, ledger_jobs, ledger_single, services
from .ledger_purchase import PURCHASE_RIGHTS
from .models import Movement, Pouch, StockDocument
from .views import _client, _everything, _page

Reason, Kind, Status = Movement.Reason, StockDocument.Kind, StockDocument.Status

#: the prototype's chip colours per reason
REASON_TONE = {Reason.MEMO_IN: "good", Reason.JOB_WORK_IN: "good", Reason.MEMO_OUT: "info",
               Reason.JOB_WORK_OUT: "warn", Reason.RECOUNT_ADJUSTMENT: "info"}
PERIODS = [("", "All time"), ("12", "Last 12 months"), ("3", "Last 3 months")]
TRANSFER = "Transfer to another batch"
#: the card's reasons — the prototype's twelve in its order, then the two it left out — each
#: with the rights that may post it (any one). Purchase needs all of PURCHASE_RIGHTS; it and
#: Transfer open their own screens.
REASONS = [
    (Reason.JOB_WORK_OUT, (INV_JOB,)), (Reason.JOB_WORK_IN, (INV_JOB,)), (Reason.SALE, (INV_MOVE,)),
    (Reason.SALES_RETURN, (INV_MOVE,)), (Reason.MEMO_OUT, (INV_MOVE,)), (Reason.MEMO_IN, (INV_MOVE,)),
    (Reason.PURCHASE, None), (Reason.CONSUMED, (INV_JOB, INV_MOVE)), (Reason.WASTAGE, (INV_JOB, INV_MOVE)),
    (Reason.BREAKAGE, (INV_MOVE,)), (TRANSFER, (INV_ASSORT,)), (Reason.RECOUNT_ADJUSTMENT, (INV_MOVE,)),
    (Reason.PURCHASE_RETURN, (INV_MOVE,)), (Reason.SAMPLE, (INV_MOVE,)),
]
#: the word the quantity labels take: "Pieces out", "Weight in", "Pieces counted"
WORD = {Reason.JOB_WORK_IN: "in", Reason.MEMO_IN: "in", Reason.SALES_RETURN: "in",
        Reason.RECOUNT_ADJUSTMENT: "counted"}
SYMBOL = {1: ("＋", "in"), -1: ("−", "out"), 0: ("·", "adj")}


def offered(user):
    """``[(reason, word)]`` — only the reasons this login may post."""
    out = []
    for reason, rights in REASONS:
        may = all(map(user.has_perm, PURCHASE_RIGHTS)) if rights is None else any(map(user.has_perm, rights))
        if may:
            out.append((str(reason), WORD.get(reason, "out")))
    return out


def _ledger(user, pouch):
    """The pouch's movements, oldest first, each with the balance after it and its
    counterparty under the key that masks it."""
    rows, pcs, ct = [], 0, 0
    moves = pouch.movements.select_related("counterparty", "recorded_by", "document__vendor", "document__customer")
    for move in moves.order_by("occurred_at", "pk"):
        pcs += move.effect * (move.pcs or 0)
        ct += move.effect * (move.ct or 0)
        if move.document_id:
            party, number = ledger.party(move.document), move.document.number
            ref = move.ref if move.ref != number else ""
        else:
            party, number = ({"vendor_name": move.counterparty.name} if move.counterparty_id else {}), ""
            ref = move.challan_no or move.ref
        symbol, cls = SYMBOL[move.effect]
        rows.append(mask(user, {
            "when": move.occurred_at, "reason": move.reason, "tone": REASON_TONE.get(move.reason, ""),
            "note": move.note, "sym": symbol, "cls": cls, "reversal": bool(move.reverses_id),
            "pcs": move.pcs, "ct": move.ct, "doc_pk": move.document_id, "number": number, "ref": ref,
            "bal_pcs": pcs, "bal_ct": ct, **party,
            "by": (move.recorded_by.full_name or move.recorded_by.get_username()) if move.recorded_by_id else "system",
        }))
    return rows


def _open_on(user, pouch, kind):
    """Open challans or memos holding some of this pouch, with how much each still has of it."""
    documents = list(StockDocument.objects.filter(kind=kind, status=Status.OPEN, movements__pouch=pouch)
                     .distinct().select_related("vendor", "customer"))
    owed = ledger.owed_by_document(documents)
    return [mask(user, {"pk": d.pk, "number": d.number, **ledger.party(d),
                        "ct": sum((ct for p, _, ct in owed.get(d.pk, []) if p.pk == pouch.pk), ledger.ZERO)})
            for d in documents]


def _movements_page(request, obj, form=None, error=None):
    user = request.user
    everything = _everything(request)
    row = next(r for r in everything if r["pk"] == obj.pk)
    rows = _ledger(user, obj)
    total = len(rows)
    reason, months = request.GET.get("reason", ""), request.GET.get("months", "")
    if reason:
        rows = [m for m in rows if m["reason"] == reason]
    if months.isdigit():
        since = timezone.now() - timedelta(days=31 * int(months))
        rows = [m for m in rows if m["when"] >= since]
    held = services.stocked(Pouch.objects.filter(pk=obj.pk)).get()
    record = offered(user)
    names = {name for name, _ in record}
    form = form or {}
    return _page(
        request, "inventory/movements.html", everything, tab="tx", pouch_ref=obj.ref, row=row,
        ledger=list(reversed(rows)), ledger_total=total, reason=reason, months=months,
        reasons=Movement.Reason.choices, periods=PERIODS,
        in_stock=bool((held.on_ct or 0) > 0 or (held.on_pcs or 0) > 0),
        record=record, form=form, error=error, today=timezone.localdate().isoformat(),
        chosen=form.get("reason") or request.GET.get("record") or (record[0][0] if record else ""),
        qty_reasons="|".join(name for name, _ in record if name not in (Reason.PURCHASE, TRANSFER)),
        karigars=ledger_jobs.karigar_choices(user) if Reason.JOB_WORK_OUT in names else [],
        challans=_open_on(user, obj, Kind.JOB_WORK) if names & {Reason.JOB_WORK_IN, Reason.CONSUMED, Reason.WASTAGE} else [],
        memos=_open_on(user, obj, Kind.MEMO) if names & {Reason.MEMO_IN, Reason.SALE} else [],
        customers=ledger_jobs.customer_choices(user) if names & {Reason.MEMO_OUT, Reason.SALE, Reason.SALES_RETURN} else [],
        suppliers=[mask(user, {"pk": v.pk, "vendor_name": v.name})
                   for v in Vendor.objects.filter(is_active=True).order_by("name")]
        if Reason.PURCHASE_RETURN in names else [],
    )


@login_required
def movements(request, ref):
    if _client(request):
        return redirect("inventory:pouch", ref=ref)
    return _movements_page(request, get_object_or_404(Pouch, ref=ref))


def _vendor(raw):
    raw = raw or ""
    return Vendor.objects.filter(pk=raw, is_active=True).first() if raw.isdigit() else None


def _customer(raw):
    raw = (raw or "").strip()
    return Customer.objects.filter(customer_code=raw).first() if raw else None


def _open(raw, kind):
    raw = raw or ""
    document = StockDocument.objects.filter(pk=raw, kind=kind).first() if raw.isdigit() else None
    if document is None:
        raise ServiceError(f"Choose the open {'challan' if kind == Kind.JOB_WORK else 'memo'} to settle against.")
    return document


def _record(user, pouch, reason, post):
    """Post one Record movement form: the document it landed on, or ``None`` for a matching count."""
    pcs, ct = inputs.whole(post.get("pcs"), "Pieces"), inputs.decimal(post.get("ct"), "Weight")
    when = inputs.day(post.get("occurred_on")) or timezone.localdate()
    back, note = inputs.day(post.get("expected_back"), "Expected back"), (post.get("note") or "").strip()
    if reason == Reason.JOB_WORK_OUT:
        with transaction.atomic():           # a new karigar stands or falls with its challan
            karigar = (dia_services.save_supplier(user, None, post.get("new_code"), post.get("new_name"), "", "")
                       if post.get("karigar") == "new" else _vendor(post.get("karigar")))
            return ledger_jobs.job_work_out(user, pouch, karigar, post.get("challan_no"), pcs, ct, when, back, note)
    if reason == Reason.MEMO_OUT:
        return ledger_jobs.memo_out(user, pouch, _customer(post.get("customer")), post.get("memo_no"),
                                    pcs, ct, when, back, note)
    if reason in (Reason.CONSUMED, Reason.WASTAGE):
        # two paths share one right each: settled against a challan needs inv_job, straight off
        # the shelf needs inv_move. A login with only one never sees the other's option in the
        # card, but a hand-built post is refused here — on the form, not a bare 403 that would
        # lose what was typed.
        settling = bool(post.get("challan")) or not user.has_perm(INV_MOVE)
        if settling:
            if not user.has_perm(INV_JOB):
                raise ServiceError("Only a role that posts job cards can settle a challan.")
            how = {Reason.CONSUMED: "consumed", Reason.WASTAGE: "loss"}[reason]
            return ledger_jobs.settle_job_work(user, _open(post.get("challan"), Kind.JOB_WORK), pouch, how,
                                               pcs, ct, when, note).document
        return ledger_single.post_single(user, pouch, reason, pcs, ct, when, note=note)
    if reason == Reason.JOB_WORK_IN:
        return ledger_jobs.settle_job_work(user, _open(post.get("challan"), Kind.JOB_WORK), pouch, "in",
                                           pcs, ct, when, note).document
    if reason == Reason.MEMO_IN or (reason == Reason.SALE and post.get("memo")):
        how = "in" if reason == Reason.MEMO_IN else "sold"
        return ledger_jobs.settle_memo(user, _open(post.get("memo"), Kind.MEMO), pouch, how,
                                       pcs, ct, when, note).document
    if reason == Reason.RECOUNT_ADJUSTMENT:
        return ledger_single.post_recount(user, pouch, pcs, ct, when, note)
    return ledger_single.post_single(user, pouch, reason, pcs, ct, when, customer=_customer(post.get("customer")),
                                     supplier=_vendor(post.get("supplier")), ref=post.get("ref"), note=note)


@login_required
@require_POST
def movement_post(request, ref):
    if _client(request):
        return redirect("inventory:pouch", ref=ref)
    obj = get_object_or_404(Pouch.objects.select_related("batch"), ref=ref)
    reason = request.POST.get("reason", "")
    if reason not in {name for name, _ in offered(request.user)}:
        raise PermissionDenied("That movement is not yours to post.")
    try:
        document = _record(request.user, obj, reason, request.POST)
    except ServiceError as refused:
        return _movements_page(request, obj, form=request.POST, error=refused.messages[0])
    if document is None:
        messages.info(request, "The count matches the ledger; nothing was posted.")
    else:
        messages.success(request, f"Posted on {document.number}.")
    return redirect("inventory:movements", ref=ref)
