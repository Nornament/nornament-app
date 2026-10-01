"""Diamond job cards: the prototype's ledger, working.

Readable by every internal login, read-only without Job cards; a karigar's name
needs Job cards, as on stones. The page is built for the viewer, so an admin's
"Viewing as" preview shows what that role would see, with every form hidden;
every POST acts as the real login, needs Job cards, and comes back to the card
with what happened.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.capabilities import INV_JOB, ROLE_GROUPS
from stock.masking import mask
from stock.models import Vendor
from stock.services import ServiceError, require

from . import dia_services, inputs, ledger, ledger_dia_jobs, ledger_jobs
from .models import DiamondLine, Movement, StockDocument
from .views_diamonds import dia_page, viewer

Kind, Status = StockDocument.Kind, StockDocument.Status


def _card_row(user, card):
    """A card for the picker and the header, masked: a karigar the viewer may not see is simply
    absent, and never reads as In-house — ``in_house`` says that on its own."""
    return mask(user, {"pk": card.pk, "number": card.number, "in_house": card.vendor_id is None, **ledger.party(card),
                       "opened": card.occurred_on, "status": card.get_status_display().lower()})


def _ledger(card):
    """The card's entries, oldest first, as debits and credits with a running balance: out to the
    karigar is a debit; back, set or written off is a credit; an undone entry counts the other way."""
    rows, balance, debit, credit = [], ledger.ZERO, ledger.ZERO, ledger.ZERO
    moves = card.movements.select_related("diamond__band", "recorded_by").order_by("occurred_at", "pk")
    for m in moves:
        sign = 1 if m.direction == Movement.OUT else -1
        if m.reverses_id:
            sign = -sign
        ct = m.ct or ledger.ZERO
        balance += sign * ct
        debit, credit = (debit + ct, credit) if sign > 0 else (debit, credit + ct)
        label = ledger_dia_jobs.ENTRY_LABEL.get(m.reason, m.reason)
        rows.append({
            "when": m.occurred_at, "label": f"↺ {label}" if m.reverses_id else label,
            "tone": "" if m.reverses_id else ("warn" if m.direction == Movement.OUT else "good"),
            "line": dia_services.line_label(m.diamond), "ref": m.ref,
            "debit": ct if sign > 0 else None, "credit": None if sign > 0 else ct, "balance": balance,
            "by": (m.recorded_by.full_name or m.recorded_by.get_username()) if m.recorded_by_id else "system",
        })
    return rows, {"debit": debit, "credit": credit, "balance": debit - credit}


@login_required
def jobs(request):
    user, role = viewer(request)
    previewing = user is not request.user
    every = StockDocument.objects.filter(kind=Kind.DIA_JOB, reverses__isnull=True).select_related("vendor")
    raw = request.GET.get("card", "")
    card = every.filter(pk=raw).first() if raw.isdigit() else None
    closed = request.GET.get("closed") == "1" or (card is not None and card.status != Status.OPEN)
    listed = list((every if closed else every.filter(status=Status.OPEN)).order_by("-occurred_on", "-pk"))
    card = card or (listed[0] if listed else None)
    may = request.user.has_perm(INV_JOB) and not previewing
    context = {}
    if card is not None:
        rows, totals = _ledger(card)
        out = ledger_dia_jobs.owed(card)
        live = card.status == Status.OPEN
        undoable = card.movements.filter(reverses__isnull=True, reversal__isnull=True).exists()
        context = dict(
            card=_card_row(user, card), rows=rows, totals=totals, out_text=ledger._ct(out),
            can_post=may and live, can_close=may and live and out == 0,
            can_undo=may and card.status != Status.REVERSED and undoable,
            can_reverse=may and card.status != Status.REVERSED,
            issue=dia_services.line_choices() if may and live else [],
            credit=ledger_dia_jobs.credit_choices(card) if may and live else [],
        )
    return dia_page(
        request, "inventory/diamonds/jobs.html", dtab="jobs", role_label=ROLE_GROUPS[role]["name"],
        read_only=not user.has_perm(INV_JOB), may=may, closed=closed,
        cards=[_card_row(user, c) for c in listed], entries=ledger_dia_jobs.ENTRY_CHOICES,
        karigars=ledger_jobs.karigar_choices(request.user) if may else [],
        today=timezone.localdate().isoformat(), **context,
    )


def _card(pk):
    return get_object_or_404(StockDocument, pk=pk, kind=Kind.DIA_JOB, reverses__isnull=True)


def _back(pk):
    return redirect(f"{reverse('inventory:dia_jobs')}?card={pk}")


@login_required
@require_POST
def job_new(request):
    require(request.user, INV_JOB, "Only a role that posts job cards can open one.")
    raw = (request.POST.get("karigar") or "").strip()
    try:
        karigar = Vendor.objects.filter(pk=raw).first() if raw.isdigit() else None
        if raw and karigar is None:
            raise ServiceError("Choose the karigar, or In-house.")
        card = ledger_dia_jobs.open_card(request.user, karigar, inputs.day(request.POST.get("opened_on"), "Opened"),
                                         request.POST.get("note", ""))
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
        return redirect("inventory:dia_jobs")
    messages.success(request, f"Job card {card.number} opened.")
    return _back(card.pk)


@login_required
@require_POST
def job_post(request, pk):
    require(request.user, INV_JOB, "Only a role that posts job cards can post an entry.")
    card = _card(pk)
    raw = request.POST.get("line") or ""
    line = DiamondLine.objects.filter(pk=raw).first() if raw.isdigit() else None
    try:
        ledger_dia_jobs.post_entry(request.user, card, request.POST.get("entry", ""), line,
                                   inputs.decimal(request.POST.get("ct"), "Carats"),
                                   inputs.day(request.POST.get("occurred_on")), request.POST.get("ref", ""))
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
    else:
        messages.success(request, "Posted.")
    return _back(card.pk)


def _act(request, pk, act, done):
    """Close, undo or reverse a card as the real login, and come back to it with what happened."""
    require(request.user, INV_JOB, "Only a role that posts job cards may change one.")
    card = _card(pk)
    try:
        result = act(request.user, card)
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
    else:
        messages.success(request, done(result))
    return _back(card.pk)


@login_required
@require_POST
def job_close(request, pk):
    return _act(request, pk, ledger.close_document, lambda card: f"{card.number} closed.")


@login_required
@require_POST
def job_undo(request, pk):
    return _act(request, pk, ledger.undo_last,
                lambda move: f"Undone: {ledger_dia_jobs.ENTRY_LABEL.get(move.reason, move.reason)}.")


@login_required
@require_POST
def job_reverse(request, pk):
    return _act(request, pk, ledger.reverse_document, lambda reversal: f"Reversed by {reversal.number}.")
