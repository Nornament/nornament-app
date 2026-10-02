"""The top bar's search: pouches and diamond lines by the names people use for them.

Internal only — in client view it redirects, as the ledger screens do — and no
money on the page: a result says where to go, not what it is worth.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect

from stock.masking import mask

from . import dia_rules, dia_services, services
from .models import DiamondLine, Pouch
from .views import _client, _everything, _page

CAP = 50
MIN = 2


def _pouches(q):
    """A pouch ref or a batch code exactly, "batch · pouch no." (or "batch pouch no."), or a stone
    name containing it; case never matters."""
    match = Q(ref__iexact=q) | Q(batch__code__iexact=q) | Q(stone_name__icontains=q)
    parts = q.replace("·", " ").split()
    if len(parts) == 2:
        match |= Q(batch__code__iexact=parts[0], pouch_no__iexact=parts[1])
    return services.stocked(Pouch.objects.filter(match))


def _lines(q):
    """A line ref or a batch no. exactly, or an item code containing it, read as the register
    writes codes ("drfgh vs si" finds DRFGH VS-SI)."""
    match = (Q(ref__iexact=q) | Q(batch_no__iexact=q)
             | Q(code__item_code__icontains=dia_rules.canonical_code(q.upper())))
    return dia_services.stocked_lines(DiamondLine.objects.filter(match))


def _pouch_row(user, p):
    return mask(user, {"ref": p.ref, "pouch": str(p), "stone_name": p.stone_name, "colour": p.colour,
                       "shape": p.shape, "countable": p.countable, "pcs": p.on_pcs if p.countable else None,
                       "ct": p.on_ct})


def _line_row(user, line):
    shape, colour, clarity = line.shape, line.colour, line.code.clarity
    return mask(user, {"ref": line.ref, "item_code": line.code_id, "category": line.category.value,
                       "shape": shape.value if shape else "", "colour": colour.value if colour else "",
                       "clarity": clarity.value if clarity else "", "size": line.size_text or line.band.value,
                       "batch": line.batch_no, "ct": line.on_ct})


@login_required
def search(request):
    if _client(request):
        return redirect("inventory:shelf")
    q = (request.GET.get("q") or "").strip()
    pouches, lines, found = [], [], {"pouches": 0, "lines": 0}
    if len(q) >= MIN:
        hits, matched = _pouches(q), _lines(q)
        found = {"pouches": hits.count(), "lines": matched.count()}
        pouches = [_pouch_row(request.user, p) for p in hits[:CAP]]
        lines = [_line_row(request.user, line) for line in matched[:CAP]]
    return _page(request, "inventory/search.html", _everything(request), tab="search", q=q, short=len(q) < MIN,
                 pouches=pouches, lines=lines, found=found)
