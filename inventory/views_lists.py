"""The rail's ledger lists: what is out on job work and on memo, recent documents, splits and transfers."""
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import redirect
from django.utils import timezone

from accounts.capabilities import INV_JOB, INV_MOVE
from stock.masking import mask
from stock.services import require

from . import ledger
from .models import Movement, StockDocument
from .views import _client, _everything, _page

Kind, Status = StockDocument.Kind, StockDocument.Status
TONE = {Status.OPEN: "warn", Status.CLOSED: "good", Status.REVERSED: "crit"}
RECENT_CAP = 100


def _out_rows(user, documents):
    """One masked row per document: what went out, what is still out, and what that is worth."""
    documents = list(documents.select_related("vendor", "customer").prefetch_related("movements"))
    owed = ledger.owed_by_document(documents)
    today = timezone.localdate()
    rows = []
    for d in documents:
        sent_pcs, sent_ct = 0, ledger.ZERO
        for m in d.movements.all():
            if m.direction == Movement.OUT:
                sign = -1 if m.reverses_id else 1
                sent_pcs += sign * (m.pcs or 0)
                sent_ct += sign * (m.ct or 0)
        lines = owed.get(d.pk, []) if d.status == Status.OPEN else []
        rows.append(mask(user, {
            "pk": d.pk, "number": d.number, **ledger.party(d), "occurred_on": d.occurred_on,
            "expected_back": d.expected_back, "status": d.get_status_display(), "tone": TONE[d.status],
            "open": d.status == Status.OPEN,
            "overdue": d.status == Status.OPEN and d.expected_back is not None and d.expected_back < today,
            "sent_pcs": sent_pcs, "sent_ct": sent_ct,
            "owed_pcs": sum(pcs for _, pcs, _ in lines), "owed_ct": sum((ct for _, _, ct in lines), ledger.ZERO),
            "pouch_value": sum((ct * p.rate for p, _, ct in lines if p.rate is not None), ledger.ZERO),
        }))
    return rows


def _out_list(request, kind, right, title, party_label, number_label, tab):
    if _client(request):
        return redirect("inventory:shelf")
    require(request.user, right, f"The {title} list is not yours to see.")
    closed = request.GET.get("closed") == "1"
    documents = StockDocument.objects.filter(kind=kind, reverses__isnull=True).order_by("-occurred_on", "-pk")
    if not closed:
        documents = documents.filter(status=Status.OPEN)
    return _page(request, "inventory/out_list.html", _everything(request), tab=tab, title=title,
                 party_label=party_label, number_label=number_label, closed=closed,
                 rows=_out_rows(request.user, documents), money=mask(request.user, {"pouch_value": None}))


@login_required
def job_work_list(request):
    return _out_list(request, Kind.JOB_WORK, INV_JOB, "Job work out", "Karigar", "Challan no.", "job_work")


@login_required
def memo_list(request):
    return _out_list(request, Kind.MEMO, INV_MOVE, "Memo out", "Customer", "Memo no.", "memo")


@login_required
def recent(request):
    """Recent stones documents across every pouch, newest first. A diamond document is never
    listed here: the diamond ledgers have their own screens.

    ponytail: the newest 100; page through when someone asks for more.
    """
    if _client(request):
        return redirect("inventory:shelf")
    kind = request.GET.get("kind", "")
    documents = (StockDocument.objects.filter(kind__in=ledger.STONE_KINDS)
                 .select_related("vendor", "customer").annotate(lines=Count("movements")))
    if kind in ledger.STONE_KINDS:
        documents = documents.filter(kind=kind)
    rows = [mask(request.user, {"pk": d.pk, "number": d.number, "kind": d.get_kind_display(), **ledger.party(d),
                                "occurred_on": d.occurred_on, "status": d.get_status_display(),
                                "tone": TONE[d.status], "lines": d.lines})
            for d in documents.order_by("-created_at", "-pk")[:RECENT_CAP]]
    return _page(request, "inventory/recent.html", _everything(request), tab="recent", rows=rows, kind=kind,
                 kinds=[(value, label) for value, label in Kind.choices if value in ledger.STONE_KINDS])


def _name(user):
    return (user.full_name or user.get_username()) if user else "system"


@login_required
def splits(request):
    """Every split, newest first: the pouch it came out of, the pouches it made, and the carats taken
    out (any loss included). A reversal is not listed on its own: the split it undid reads Reversed.
    Merges join this list when they are built (5c).

    ponytail: every split on one page; page through when there are hundreds.
    """
    if _client(request):
        return redirect("inventory:shelf")
    documents = (StockDocument.objects.filter(kind=Kind.SPLIT, reverses__isnull=True)
                 .select_related("created_by").prefetch_related("movements__pouch__batch")
                 .order_by("-created_at", "-pk"))
    rows = []
    for d in documents:
        moves = sorted(d.movements.all(), key=lambda m: m.pk)
        out = [m for m in moves if m.direction == Movement.OUT]
        source = out[0].pouch if out else None
        rows.append(mask(request.user, {
            "pk": d.pk, "number": d.number, "occurred_on": d.occurred_on,
            "source": str(source) if source else "", "source_ref": source.ref if source else "",
            "made": [str(m.pouch) for m in moves if m.direction == Movement.IN],
            "ct": sum((m.ct or ledger.ZERO for m in out), ledger.ZERO),
            "reversed": d.status == Status.REVERSED, "by": _name(d.created_by),
        }))
    return _page(request, "inventory/splits.html", _everything(request), tab="splits", rows=rows)


@login_required
def transfers(request):
    """Every transfer, newest first: the pouch, where it was filed and where it went. A reversal is
    not listed on its own: the transfer it undid reads Reversed.

    ponytail: every transfer on one page; page through when there are hundreds.
    """
    if _client(request):
        return redirect("inventory:shelf")
    documents = (StockDocument.objects.filter(kind=Kind.TRANSFER, reverses__isnull=True)
                 .select_related("created_by", "from_batch", "to_batch").prefetch_related("movements__pouch")
                 .order_by("-created_at", "-pk"))
    rows = [mask(request.user, {
        "pk": d.pk, "number": d.number, "occurred_on": d.occurred_on,
        "ref": next(iter(d.movements.all())).pouch.ref,
        "moved_from": f"{d.from_batch.code} · {d.from_pouch_no or '?'}",
        "moved_to": f"{d.to_batch.code} · {d.to_pouch_no}",
        "reversed": d.status == Status.REVERSED, "by": _name(d.created_by),
    }) for d in documents]
    return _page(request, "inventory/transfers.html", _everything(request), tab="transfers", rows=rows)
