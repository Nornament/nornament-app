"""The two price lists: every pouch's cost or selling price, filtered, and one price set for a whole group.

The prototype only explains them (cost and selling are different numbers with different owners, kept
as dated rows); the rows are ``PriceEntry``, the same ones each pouch's price card shows. Stones only:
diamonds price by the rate card in diamond Settings.
"""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import OuterRef, Q, Subquery
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import urlencode

from accounts.capabilities import INV_MASTERS, VIEW_COST, VIEW_SALE
from stock.masking import allowed, mask
from stock.services import ServiceError, require

from . import services
from .models import BoxColour, Pouch, PriceEntry
from .views import _client, _everything, _page

PAGE = 200
#: mode -> (the right to open it, the kind of price it sets, its title)
MODES = {
    "cost": (VIEW_COST, PriceEntry.VALUATION, "Price list — cost"),
    "selling": (VIEW_SALE, PriceEntry.LIST, "Price list — selling"),
}
#: the exact-match selects, as (field, label)
CHOICES = (("colour", "Colour"), ("shape", "Shape"), ("quality", "Quality"), ("size_text", "Size"))
FIELDS = ("stone", *(key for key, _ in CHOICES), "batch", "box")


def _filters(data):
    """The filters a GET or a POST carries. ``f`` marks a submitted form, so an unticked
    "in stock only" stays unticked; with no form yet it is on."""
    f = {key: (data.get(key) or "").strip() for key in FIELDS}
    f["stock"] = "1" if data.get("stock") or not data.get("f") else ""
    return f


def _query(f):
    return urlencode({"f": "1", **{key: value for key, value in f.items() if value}})


def _latest(kind, field="rate"):
    return Subquery(PriceEntry.objects.filter(pouch=OuterRef("pk"), kind=kind)
                    .order_by("-effective_from", "-pk").values(field)[:1])


def _pouches(f):
    pouches = services.stocked().annotate(
        valuation_from=_latest(PriceEntry.VALUATION, "effective_from"),
        purchase_rate=_latest(PriceEntry.PURCHASE),
        list_rate=_latest(PriceEntry.LIST), list_from=_latest(PriceEntry.LIST, "effective_from"),
    )
    if f["stone"]:
        pouches = pouches.filter(stone_name__icontains=f["stone"])
    for key, _ in CHOICES:
        if f[key]:
            pouches = pouches.filter(**{key: f[key]})
    if f["batch"]:
        pouches = pouches.filter(batch__code__istartswith=f["batch"])
    if f["box"]:
        pouches = pouches.filter(batch__box_colour_id=f["box"])
    if f["stock"]:
        pouches = pouches.filter(Q(on_ct__gt=0) | Q(on_pcs__gt=0))
    return pouches


def _margin(listed, valuation):
    if listed is None or not valuation:
        return None
    return (listed - valuation) / valuation * 100


def _row(user, pouch):
    row = mask(user, {
        "ref": pouch.ref, "batch_code": pouch.batch.code, "pouch_no": pouch.pouch_no or "",
        "stone_name": pouch.stone_name, "size_text": pouch.size_text, "ct": pouch.on_ct,
        "purchase_rate": pouch.purchase_rate, "valuation_rate": pouch.rate, "valuation_from": pouch.valuation_from,
        "pouch_value": services.value_of(pouch), "list_rate": pouch.list_rate, "list_from": pouch.list_from,
        # a margin reads the valuation, so it is never worked out for a login that may not see one
        "margin": _margin(pouch.list_rate, pouch.rate) if allowed(user, "valuation_rate") else None,
    })
    if "list_rate" in row:
        row["list_value"] = None if row["list_rate"] is None or row["ct"] is None else row["ct"] * row["list_rate"]
    return row


def _choices(f):
    """Each select's values: the distinct non-blank ones across every pouch, and the box colours."""
    out = []
    for key, label in CHOICES:
        values = Pouch.objects.exclude(**{key: ""}).order_by(key).values_list(key, flat=True).distinct()
        out.append((key, label, [(value, value, value == f[key]) for value in values]))
    out.append(("box", "Box colour", [(b.code, f"{b.code} · {b.label}", b.code == f["box"])
                                      for b in BoxColour.objects.all()]))
    return out


def _set(request, mode, kind, f):
    """One price for every pouch the posted filters match, on every page. The count the form showed
    must still hold, so stock that moved since the page loaded is never priced blind."""
    right = MODES[mode][0]
    require(request.user, INV_MASTERS, "Only a role that edits inventory records can set a price.")
    require(request.user, right, "A price you may not see is not yours to set.")
    back = f"{reverse(f'inventory:prices_{mode}')}?{_query(f)}"
    group = list(_pouches(f))
    if str(len(group)) != (request.POST.get("count") or "").strip():
        messages.error(request, "The group changed since the page loaded — check the count and set again.")
        return redirect(back)
    try:
        rate = Decimal(request.POST.get("rate") or "")
    except InvalidOperation:
        rate = None
    try:
        when = parse_date(request.POST.get("effective_from") or "") or timezone.localdate()
    except ValueError:
        messages.error(request, "That date does not exist.")
        return redirect(back)
    described = ", ".join(f"{key}={value}" for key, value in f.items() if value)
    try:
        n = services.set_group_price(request.user, group, kind, rate, when, described=described)
    except ServiceError as error:
        messages.error(request, error.messages[0])
        return redirect(back)
    what = "Valuation" if kind == PriceEntry.VALUATION else "List price"
    messages.success(request, f"{what} set on {n} pouch{'es' if n != 1 else ''}.")
    return redirect(back)


@login_required
def prices(request, mode):
    if _client(request):
        return redirect("inventory:shelf")
    right, kind, title = MODES[mode]
    require(request.user, right, "This price list needs the right to see its prices.")
    if request.method == "POST":
        return _set(request, mode, kind, _filters(request.POST))
    f = _filters(request.GET)
    rows = [_row(request.user, pouch) for pouch in _pouches(f)]
    money = "pouch_value" if mode == "cost" else "list_value"
    values = [r[money] for r in rows if r.get(money) is not None]
    total = sum(values) if values else None
    query = _query(f)
    return _page(
        request, "inventory/prices.html", _everything(request), tab=f"prices_{mode}", mode=mode, title=title,
        page=Paginator(rows, PAGE).get_page(request.GET.get("page")), count=len(rows), total=total,
        filters=f, choices=_choices(f), query=query, posted=[(k, v) for k, v in [("f", "1"), *f.items()] if v],
        margin=mode == "selling" and allowed(request.user, "margin"),
        can_set=request.user.has_perm(INV_MASTERS) and request.user.has_perm(right),
        set_label="valuation" if kind == PriceEntry.VALUATION else "list price", today=timezone.localdate(),
    )
