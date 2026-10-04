"""The diamond Movements tab: recent diamond documents, and a ledger per line.

Read-only and readable by every internal login, as the document screens are.
Built for ``viewer(request)``, so an admin's "Viewing as" preview masks like the
role and every link carries it. Diamonds have no client view, so the stones'
Internal / Client flag is not read here.
"""
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.urls import reverse

from accounts.capabilities import INV_ASSORT, INV_JOB
from stock.masking import mask

from . import dia_rows, dia_services, ledger
from .ledger_purchase import PURCHASE_RIGHTS
from .models import DiamondLine, StockDocument
from .views_diamonds import dia_page, viewer

Kind, Status = StockDocument.Kind, StockDocument.Status
TONE = {Status.OPEN: "warn", Status.CLOSED: "good", Status.REVERSED: "crit"}
SYMBOL = {1: ("＋", "in"), -1: ("−", "out"), 0: ("·", "adj")}
WORD = {1: "In", -1: "Out", 0: "Settle"}
RECENT_CAP = 100
#: where each diamond document is read, and the query that picks it there
SCREEN = {Kind.DIA_JOB: ("inventory:dia_jobs", "card"), Kind.DIA_ASSORT: ("inventory:dia_assorts", "doc"),
          Kind.DIA_PURCHASE: ("inventory:dia_purchase", None)}
#: the right each screen needs — a stock take has none here: it is readable by every internal login
NEEDS = {Kind.DIA_JOB: (INV_JOB,), Kind.DIA_ASSORT: (INV_ASSORT,), Kind.DIA_PURCHASE: PURCHASE_RIGHTS}


def _may_open(user, kind):
    return all(user.has_perm(right) for right in NEEDS.get(kind, ()))


def opens(user, document, as_role=""):
    """The screen a diamond document is read on: its job card, its assortment, or Purchases (which
    lists them; a purchase has no page of its own). A reversal opens the document it reversed.

    ``""`` when the viewer holds none of the rights that screen needs — a stock take has no such
    right, so it always links. The caller then renders the document number as plain text."""
    document = document.reverses or document
    if document.kind == Kind.DIA_COUNT:
        url = reverse("inventory:dia_stock_take", args=[document.stock_take.pk])
        return url + (f"?{urlencode({'as': as_role})}" if as_role else "")
    if not _may_open(user, document.kind):
        return ""
    name, key = SCREEN[document.kind]
    params = {key: document.pk} if key else {}
    if as_role:
        params["as"] = as_role
    return reverse(name) + (f"?{urlencode(params)}" if params else "")


def _as_role(request, user, role):
    return role if user is not request.user else ""


@login_required
def movements(request):
    """Recent diamond documents, newest first. A reversal is not listed on its own: the document
    it undid reads Reversed.

    ponytail: the newest 100; page through when someone asks for more.
    """
    user, role = viewer(request)
    as_role = _as_role(request, user, role)
    kind = request.GET.get("kind", "")
    # reverses__isnull=True above means every listed document has no reverses of its own, so
    # opens()'s "document.reverses or document" always falls through to this row's own stock_take
    documents = (StockDocument.objects.filter(kind__in=ledger.DIAMOND_KINDS, reverses__isnull=True)
                 .select_related("vendor", "stock_take")
                 .annotate(lines=Count("movements__diamond", distinct=True)))
    if kind in ledger.DIAMOND_KINDS:
        documents = documents.filter(kind=kind)
    rows = [mask(user, {"pk": d.pk, "number": d.number, "kind": d.get_kind_display(), **ledger.party(d),
                        "in_house": d.kind == Kind.DIA_JOB and d.vendor_id is None, "occurred_on": d.occurred_on,
                        "status": d.get_status_display(), "tone": TONE[d.status], "lines": d.lines,
                        "href": opens(user, d, as_role)})
            for d in documents.order_by("-created_at", "-pk")[:RECENT_CAP]]
    return dia_page(request, "inventory/diamonds/movements.html", dtab="movements", rows=rows, kind=kind,
                    kinds=[(value, label) for value, label in Kind.choices if value in ledger.DIAMOND_KINDS])


def _ledger(user, line, as_role=""):
    """Every movement of the line, oldest first, with the balance after it by the shared rule
    (``Movement.effect``: in adds, out takes, a settle counts 0, a reversal the opposite sign). A
    movement on a document links to that document's screen; an import's opening names the register
    row it came from (its ref), and a recount says so in its note."""
    rows, balance = [], ledger.ZERO
    moves = line.movements.select_related("document__reverses", "recorded_by").order_by("occurred_at", "pk")
    for m in moves:
        balance += m.effect * (m.ct or ledger.ZERO)
        doc = m.document
        symbol, cls = SYMBOL[m.effect]
        rows.append(mask(user, {
            "when": m.occurred_at, "reason": m.reason, "note": m.note, "reversal": bool(m.reverses_id),
            "sym": symbol, "cls": cls, "direction": WORD[m.effect], "ct": m.ct, "balance": balance,
            "number": doc.number if doc else "", "href": opens(user, doc, as_role) if doc else "",
            "ref": m.ref if not doc or m.ref != doc.number else "",
            "by": (m.recorded_by.full_name or m.recorded_by.get_username()) if m.recorded_by_id else "system",
        }))
    return rows


@login_required
def line(request, ref):
    user, role = viewer(request)
    found = get_object_or_404(dia_services.stocked_lines(DiamondLine.objects.filter(ref=ref)))
    moves = _ledger(user, found, _as_role(request, user, role))
    return dia_page(request, "inventory/diamonds/line.html", dtab="movements",
                    row=dia_rows.line_row(user, found, dia_services.rate_table()), moves=list(reversed(moves)))
