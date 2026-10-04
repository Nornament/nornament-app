"""The top bar's search: pouches and diamond lines by the names people use for them.

No money on the page: a result says where to go, not what it is worth. In stones client
view a pouch is stock control, so it is never shown here — but the search box stays live
on a diamond page (which ignores that flag), so a client-view admin's diamond query still
works: it just finds diamond lines, never pouches.
"""
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.urls import reverse

from stock.masking import mask

from . import dia_rules, dia_services, services
from .models import DiamondLine, Pouch
from .views import _client, _everything, _page
from .views_diamonds import viewer

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


def _line_row(user, line, as_role=""):
    shape, colour, clarity = line.shape, line.colour, line.code.clarity
    href = reverse("inventory:dia_line", args=[line.ref]) + (f"?{urlencode({'as': as_role})}" if as_role else "")
    return mask(user, {"ref": line.ref, "item_code": line.code_id, "category": line.category.value,
                       "shape": shape.value if shape else "", "colour": colour.value if colour else "",
                       "clarity": clarity.value if clarity else "", "size": line.size_text or line.band.value,
                       "batch": line.batch_no, "ct": line.on_ct, "href": href})


@login_required
def search(request):
    """Internal only for pouches — a client never sees stock control — but diamonds have no client
    view, so a client-view admin on a diamond page still gets diamond results, never pouches."""
    client = _client(request)
    user, role = viewer(request)
    as_role = role if user is not request.user else ""
    q = (request.GET.get("q") or "").strip()
    pouches, lines, found = [], [], {"pouches": 0, "lines": 0}
    if len(q) >= MIN:
        matched = _lines(q)
        found["lines"] = matched.count()
        lines = [_line_row(user, line, as_role) for line in matched[:CAP]]
        if not client:
            hits = _pouches(q)
            found["pouches"] = hits.count()
            pouches = [_pouch_row(request.user, p) for p in hits[:CAP]]
    return _page(request, "inventory/search.html", _everything(request), tab="search", q=q, short=len(q) < MIN,
                 pouches=pouches, lines=lines, found=found)
