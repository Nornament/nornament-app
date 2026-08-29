"""Screens ported from ``legacy/Stock/app/nornament.html``.

Port-as-is: what the old screen did, this screen does. The visual refresh is
post-cutover work and doing it here would make every difference a question of
"did we mean to change that?".

HTMX carries the live bits — search, the scan flow, inline rate edits — by
returning the same partials the full page renders.
"""
import csv
import io
import re
from decimal import Decimal
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.forms import modelform_factory
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.capabilities import EDIT_BOM, ROLE_GROUPS, ROLE_TABS, VIEW_COST, VIEW_MARGIN, VIEW_SALE
from accounts.context_processors import _role_code
from crm import services as crm_services
from crm.models import Customer
from mediahub import services as media_services
from mediahub.models import MediaAsset

from . import services
from .enums import BomChangeReason, COUNTABLE_STATES, MovementType, StockState, TERMINAL_STATES, Uom
from .forms import (
    BomLineFormSet,
    CategoryForm,
    LocationForm,
    MaterialForm,
    MeltForm,
    MoveForm,
    PieceForm,
    RateChartLineForm,
    RepairForm,
    SaleForm,
    ScenarioForm,
    StyleForm,
)
from .masking import allowed, piece_row
from .models import (
    ActivityLog,
    Category,
    BomLine,
    BomVersion,
    JobCard,
    Location,
    Material,
    MaterialCategory,
    MeltRecord,
    Metal,
    MetalPurity,
    Piece,
    PieceCertificate,
    RateChart,
    RateChartLine,
    RepairJob,
    Sale,
    Scenario,
    StockCount,
    StockMovement,
    Style,
)

PAGE_SIZE = 50


def _visible_pieces(request):
    return Piece.objects.visible_to(request.user).select_related(
        "style", "style__category", "style__collection", "location", "vendor"
    )


@login_required
def dashboard(request):
    pieces = _visible_pieces(request)
    live = pieces.filter(stock_state__in=list(COUNTABLE_STATES))
    by_location = (
        live.values("location__code", "location__name").annotate(pieces=Count("pk")).order_by("location__code")
    )
    by_state = pieces.values("stock_state").annotate(pieces=Count("pk")).order_by("stock_state")
    # legacy "live": anything received and not yet terminal — repairs included
    alive = pieces.exclude(stock_state__in=list(TERMINAL_STATES)).exclude(stock_state=StockState.NOT_RECEIVED)
    priced = Q(bom_versions__is_current=True, bom_versions__total_cost_price__gt=0)
    context = {
        "live_count": live.count(),
        "in_stock_count": pieces.filter(stock_state=StockState.IN_STOCK).count(),
        "on_approval_count": pieces.filter(stock_state=StockState.ON_APPROVAL).count(),
        "in_repair_count": pieces.filter(stock_state=StockState.IN_REPAIR).count(),
        "unpriced_count": alive.count() - alive.filter(priced).count(),
        "by_location": by_location,
        "by_state": by_state,
        "open_counts": StockCount.objects.filter(status=StockCount.OPEN).select_related("location"),
        "open_repairs": RepairJob.objects.exclude(status__in=[RepairJob.DONE, RepairJob.CANCELLED]).select_related(
            "piece"
        )[:10],
        "metals": Metal.objects.filter(is_active=True),
        "should_make": services.should_make(request.user)[:10],
        "recent_moves": StockMovement.objects.filter(piece__in=pieces).select_related(
            "piece", "from_location", "to_location", "user"
        )[:10],
    }
    if allowed(request.user, "cost_price"):
        context["stock_value"] = (
            BomVersion.objects.filter(piece__in=alive, is_current=True).aggregate(value=Sum("total_cost_price"))["value"]
            or Decimal("0")
        )
    if allowed(request.user, "sold_price"):
        month_start = timezone.localdate().replace(day=1)
        context["month_sales"] = Sale.objects.filter(sold_on__gte=month_start).aggregate(
            revenue=Sum("sold_price"), pieces=Count("pk")
        )
    return render(request, "stock/dashboard.html", context)


#: The four status chips the legacy stock screen offered. The other states are
#: reachable — they are just not questions anyone asked from this screen.
LIST_STATES = [StockState.IN_STOCK, StockState.ON_APPROVAL, StockState.SOLD, StockState.IN_REPAIR]

#: ``PRICE_BANDS`` from the legacy, unchanged. ``None`` is "and up".
PRICE_BANDS = [
    ("0 – 1 lakh", 0, 100_000),
    ("1 – 2 lakh", 100_000, 200_000),
    ("2 – 5 lakh", 200_000, 500_000),
    ("5 lakh +", 500_000, None),
]

#: The dimensions the filter bar carries, in the legacy's own order.
FILTER_KEYS = ("category", "location", "state", "price")


def _filtered(request):
    """The list filter, shared by the page, the HTMX rows and the export.

    Every key repeats (``?state=IN_STOCK&state=SOLD``) — the legacy multi-select
    chips, where two chips in one row are an *or* and two rows are an *and*. A
    single value still works: ``getlist`` reads both shapes.
    """
    pieces = _visible_pieces(request)
    query = (request.GET.get("q") or "").strip()
    if query:
        pieces = pieces.filter(
            Q(jewel_code__icontains=query)
            | Q(style__style_code__icontains=query)
            | Q(style__name__icontains=query)
            | Q(huid__icontains=query)
            | Q(src_ref__icontains=query)
        )
    picked = {key: [value for value in request.GET.getlist(key) if value] for key in FILTER_KEYS}
    if picked["category"]:
        pieces = pieces.filter(style__category__code__in=picked["category"])
    if picked["location"]:
        pieces = pieces.filter(location__code__in=picked["location"])
    if picked["state"]:
        pieces = pieces.filter(stock_state__in=picked["state"])
    if request.GET.get("unpriced"):
        pieces = pieces.exclude(bom_versions__is_current=True, bom_versions__total_cost_price__gt=0)
    if picked["price"] and allowed(request.user, "sale_price"):
        pieces = _in_price_bands(pieces, picked["price"])
    elif picked["price"]:
        picked["price"] = []  # a role that cannot see prices is not offered them
    return pieces, query, picked


def _in_price_bands(pieces, chosen):
    """Keep the pieces whose asking price falls in one of the chosen bands.

    ponytail: a sale price is computed, not stored — metal moves daily — so this
    cannot be SQL and costs one BOM read per piece. It only runs when a price
    chip is on, over a catalogue of a few hundred; make it a materialised column
    if that stops being true.
    """
    bands = [PRICE_BANDS[int(index)] for index in chosen if index.isdigit() and int(index) < len(PRICE_BANDS)]
    if not bands:
        return pieces
    return [
        piece
        for piece in pieces
        if any(low <= (price := services.live_sale_price(piece)) and (high is None or price < high)
               for _, low, high in bands)
    ]


def _filter_qs(query, picked):
    params = [("q", query)] if query else []
    for key in FILTER_KEYS:
        params += [(key, value) for value in picked[key]]
    return urlencode(params)


def _filter_chips(options, key, picked, query):
    """One legacy ``.fchip`` per option: its toggled-URL querystring, precomputed."""
    selected = picked[key]
    chips = []
    for value, label in options:
        value = str(value)
        toggled = [v for v in selected if v != value] if value in selected else selected + [value]
        chips.append({"label": label, "active": value in selected, "qs": _filter_qs(query, picked | {key: toggled})})
    return chips


def _pin_thumbs(page):
    """First confirmed photo per piece on this page, presigned — or nothing at
    all when media storage is not configured (``urls_for`` swallows
    ``StorageNotConfigured``), so the screen falls back to the table."""
    return _piece_thumbs([p.pk for p in page])


def _piece_thumbs(piece_ids):
    """``{piece_id: url}`` for the first confirmed photo of each piece."""
    firsts = [assets[0] for assets in media_services.for_pieces(list(piece_ids), limit_each=1).values() if assets]
    urls = media_services.urls_for(firsts)
    return {asset.piece_id: urls[asset.pk] for asset in firsts if urls.get(asset.pk)}


@login_required
def piece_list(request):
    pieces, query, picked = _filtered(request)
    page = Paginator(pieces, PAGE_SIZE).get_page(request.GET.get("page"))
    rows = [piece_row(request.user, piece) for piece in page]
    thumbs = _pin_thumbs(page)
    return render(
        request,
        "stock/piece_list.html",
        {
            "page": page,
            "rows": rows,
            "pins": [
                {"row": row, "thumb": thumbs[row["jewel_code_id"]]} for row in rows if row["jewel_code_id"] in thumbs
            ],
            "q": query,
            # the legacy's own order: category, location, status, price
            "category_chips": _filter_chips(
                Category.objects.values_list("code", "name"), "category", picked, query
            ),
            "location_chips": _filter_chips(
                # the workshop is where a piece goes to be repaired, not a place
                # anyone browses stock in — the legacy left WS1 out of this row
                Location.objects.filter(is_active=True).exclude(kind="WORKSHOP").values_list("code", "name"),
                "location",
                picked,
                query,
            ),
            "state_chips": _filter_chips(
                [(state.value, state.label) for state in LIST_STATES], "state", picked, query
            ),
            "price_chips": _filter_chips(
                [(index, band[0]) for index, band in enumerate(PRICE_BANDS)], "price", picked, query
            ),
            "picked": picked,
        },
    )


@login_required
def piece_rows(request):
    """The HTMX half of the list: the same rows, no chrome."""
    pieces, _, _ = _filtered(request)
    page = Paginator(pieces, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "stock/_piece_rows.html",
        {"page": page, "rows": [piece_row(request.user, piece) for piece in page], "total": pieces.count()},
    )


#: the legacy detail tab bar, in its order
PIECE_TABS = [
    ("overview", "Overview", None),
    ("bom", "Sale BOM & Breakup", None),
    ("pricing", "Pricing", VIEW_SALE),
    ("media", "Media", None),
    ("similar", "Similar", None),
    ("marketing", "Marketing", None),
    ("history", "History", None),
]


def _similar_pieces(request, piece, limit=6):
    """The legacy's "Suggested automatically": category, then price, then metal.

    Guesses, and labelled as such on the screen. The legacy also had a
    "Linked by your team" list, but the real Supabase schema has no table
    behind it — it was demo data in the mock — so there is nothing to port.
    """
    mine = piece_row(request.user, piece).get("sale_price") or Decimal("0")
    candidates = (
        _visible_pieces(request)
        .exclude(pk=piece.pk)
        .exclude(stock_state__in=TERMINAL_STATES)
        .filter(style__category_id=piece.style.category_id)[:60]
    )
    scored = []
    for other in candidates:
        row = piece_row(request.user, other)
        price = row.get("sale_price") or Decimal("0")
        score = abs(price - mine) / max(mine, Decimal("1")) * 10
        if other.metal_purity != piece.metal_purity:
            score += 1
        scored.append((score, other, row))
    scored.sort(key=lambda entry: entry[0])
    chosen = scored[:limit]
    thumbs = _piece_thumbs(other.pk for _, other, _ in chosen)
    return [{"piece": other, "row": row, "thumb": thumbs.get(other.pk)} for _, other, row in chosen]


def _margin_panel(row):
    """The legacy margin row: amount, share of sale, and how far metal has moved.

    Derived from the already-masked row, so a role without ``view_margin`` has
    no ``margin`` key and gets nothing here either — the gate is not repeated.
    """
    sale, cost, current = row.get("sale_price"), row.get("cost_price"), row.get("current_cost")
    margin, current_margin = row.get("margin"), row.get("current_margin")
    if None in (sale, cost, current, margin, current_margin) or not sale:
        return None
    return {
        "margin_pct": Decimal(100) * margin / sale,
        "current_margin_pct": Decimal(100) * current_margin / sale,
        # legacy: at or below zero is bad, under a quarter of the sale is thin
        "tone": "bad" if current_margin <= 0 else "warn" if current_margin / sale < Decimal("0.25") else "good",
        "metal_moved": (current - cost) if current > cost else None,
    }


@login_required
def piece_detail(request, jewel_code):
    piece = get_object_or_404(_visible_pieces(request), jewel_code__iexact=jewel_code)
    row = piece_row(request.user, piece)
    live_of_design = Piece.objects.filter(style=piece.style, stock_state=StockState.IN_STOCK).count()
    detail_tabs = [(id, label) for id, label, perm in PIECE_TABS if perm is None or request.user.has_perm(perm)]
    tab = request.GET.get("tab") or "overview"
    if tab not in dict(detail_tabs):
        tab = "overview"
    context = {
        "nav": "stock",
        "piece": piece,
        "row": row,
        "tab": tab,
        "detail_tabs": detail_tabs,
        "repair_form": RepairForm(),
        "melt_form": MeltForm(piece),
        "open_repair": RepairJob.objects.filter(piece=piece).exclude(status="DONE").first(),
        "gaps": services.piece_gaps(piece),
        "reconciliation": services.weight_reconciliation(piece),
        "movements": piece.movements.select_related("from_location", "to_location", "user")[:20],
        "media": piece.media.filter(is_archived=False).order_by("rank_order"),
        "locations": Location.objects.filter(is_active=True),
        "sale": Sale.objects.filter(piece=piece).first() if allowed(request.user, "sold_price") else None,
        "certificate": PieceCertificate.objects.filter(piece=piece).first(),
        "planning": {
            "floor": piece.style.nos_min_qty,
            "live": live_of_design,
            "short": max(0, piece.style.nos_min_qty - live_of_design),
        },
    }
    if tab == "media":
        assets = list(piece.media.filter(is_archived=False).order_by("rank_order"))
        context["media_urls"] = media_services.urls_for(assets)
        context["media"] = assets
    if tab == "similar":
        context["similar"] = _similar_pieces(request, piece)
    if tab == "pricing":
        context |= _scenario_prices(request, piece)
    if tab == "bom" and request.user.has_perm("accounts.manage_materials"):
        context |= _bom_context(request, piece)
    if tab == "overview" and request.user.has_perm(EDIT_BOM):
        context["inline"] = _inline_form(piece)
        context["customers"] = Customer.objects.order_by("name")
    if tab == "history":
        context["bom_versions"] = piece.bom_versions.order_by("-version_no")
        context["repairs"] = RepairJob.objects.filter(piece=piece).select_related("vendor").order_by("-opened_on")
        context["sales"] = (
            Sale.objects.filter(piece=piece).order_by("-sold_on") if allowed(request.user, "sold_price") else []
        )
    if allowed(request.user, "gold_rate_used"):
        purity = MetalPurity.objects.select_related("metal").filter(pk=piece.metal_purity or "").first()
        if purity:
            context["rate_derivation"] = {
                "metal": purity.metal.name,
                "pure_rate": purity.metal.pure_rate,
                "sale_pct": purity.sale_factor * 100,
                "as_on": purity.metal.rate_as_on,
            }
    if allowed(request.user, "vendor_name"):
        context["job_card"] = JobCard.objects.filter(piece=piece).order_by("-issued_on").first()
    context["pricing"] = _margin_panel(row)
    return render(request, "stock/piece_detail.html", context)


def _bom_context(request, piece):
    """The material breakup, for the detail tab and the standalone BOM page.

    The sale side is priced under whatever the Pricing tab says is in use: the
    piece's scenario if it is on one, else the rates on its own lines.
    """
    version = piece.current_bom()
    lines = (
        BomLine.objects.filter(piece=piece, version_no=piece.current_bom_version)
        .select_related("material", "material__category")
        .order_by("material__category__sort_order", "line_no")
    )
    show_cost = allowed(request.user, "cost_amount")
    show_sale = allowed(request.user, "sale_amount")
    ldp = services.line_dp()
    metal_rate_today = services.alloy_cost_rate(piece.metal_purity)
    scenario = piece.scenario
    priced = {row["line"].line_no: row for row in services.sale_lines(piece, scenario=scenario)}
    sale_total = sum((row["sale_amount"] for row in priced.values()), Decimal("0")) or None

    groups, breakup = [], []
    for line in lines:
        is_metal = line.material.is_metal
        sale = priced.get(line.line_no, {})
        sale_amount = sale.get("sale_amount")
        share = (Decimal(100) * (sale_amount or 0) / sale_total) if sale_total else None
        row = {
            "line_no": line.line_no,
            "material": line.material.item_code,
            "material_name": line.material.item_name,
            "category": line.material.category_id,
            "size_band": line.size_band,
            "pcs": line.pcs,
            "qty_value": line.qty_value,
            "qty_uom": line.qty_uom,
            "basis": line.basis,
            "off_chart": line.off_chart,
            "cost_rate": line.cost_rate,
            "cost_amount": line.cost_amount,
            # today = the frozen line, except metal, which reprices live (app.current_cost)
            "cost_rate_today": metal_rate_today if is_metal else line.cost_rate,
            "cost_amount_today": (
                services.round_to(metal_rate_today * (line.qty_value or 0), ldp) if is_metal else line.cost_amount
            ),
            "sale_rate": sale.get("sale_rate"),
            "sale_amount": sale_amount,
            "share_pct": services.round_to(share, 1) if share is not None else None,
            "share_w": max(2, int(share * Decimal("0.38"))) if share is not None else 2,
            "chart_cost": services.chart_rate(line.material.item_code, line.size_band, "COST"),
            "chart_sale": services.chart_rate(line.material.item_code, line.size_band, "SALE"),
        }
        label = line.material.category.name
        if not groups or groups[-1]["label"] != label:
            groups.append({"label": label, "rows": []})
            breakup.append({"label": label, "pcs": 0, "qty": Decimal("0"), "uom": line.qty_uom, "amount": Decimal("0")})
        groups[-1]["rows"].append({key: value for key, value in row.items() if allowed(request.user, key)})
        breakup[-1]["pcs"] += line.pcs or 0
        breakup[-1]["qty"] += line.qty_value or 0

    # the customer-facing breakup carries one money column: sale if you may see
    # it, else cost — same rule as the legacy screen
    money = "sale" if show_sale else ("cost" if show_cost else None)
    if money:
        by_label = {group["label"]: group for group in breakup}
        for line in lines:
            amount = priced.get(line.line_no, {}).get("sale_amount") if money == "sale" else line.cost_amount
            by_label[line.material.category.name]["amount"] += amount or 0
    context = {
        "piece": piece,
        "row": piece_row(request.user, piece),
        "version": version,
        "groups": groups,
        "grp_span": 5 + (5 if show_cost else 0) + (3 if show_sale else 0),
        "breakup": breakup if money else None,
        "money": money,
        "breakup_total": (sale_total if money == "sale" else version.total_cost_price)
        if version and money
        else None,
        "sale_total": sale_total,
        "cost_today_total": services.current_cost(piece) if show_cost else None,
        "active_scenario": scenario,
    }
    if money == "sale":
        purity = MetalPurity.objects.select_related("metal").filter(pk=piece.metal_purity or "").first()
        if purity:
            context["derivation"] = {
                "metal": purity.metal.name,
                "pure_rate": purity.metal.pure_rate,
                "sale_pct": purity.sale_factor * 100,
                "alloy_rate": services.alloy_sale_rate(piece.metal_purity),
            }
    return context


@login_required
@permission_required("accounts.manage_materials", raise_exception=True)
def piece_bom(request, jewel_code):
    """The material breakup. Gated whole — this is the ``materials`` capability."""
    piece = get_object_or_404(_visible_pieces(request), jewel_code__iexact=jewel_code)
    return render(request, "stock/piece_bom.html", _bom_context(request, piece))


def _scenario_prices(request, piece):
    """``app.piece_scenarios`` — every scenario priced against one piece.

    Feeds both the Pricing tab and the standalone ``/scenarios/`` deep link.
    The legacy returned ``cost_today`` to anyone who could see prices at all;
    here the margin column is gated on ``view_margin``, which is the leak this
    rewrite exists to close.
    """
    show_margin = allowed(request.user, "margin")
    cost_today = services.current_cost(piece)

    def margin_of(price):
        """The legacy chip: share of the asking price left over cost today."""
        if not (show_margin and price and cost_today is not None):
            return {}
        margin = price - cost_today
        share = margin / price
        return {
            "margin": margin,
            "margin_pct": Decimal(100) * share,
            "tone": "c-crit" if margin <= 0 else "c-ser" if share < Decimal("0.25") else "c-good",
        }

    prices = []
    for scenario in Scenario.objects.filter(is_active=True).order_by("-is_default", "code"):
        if scenario.roles.exists() and not scenario.roles.filter(
            group__in=request.user.groups.all(), may_see=True
        ).exists():
            continue
        try:
            price = services.scenario_price(piece, scenario)
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
            continue
        prices.append(
            price.__dict__
            | margin_of(price.price)
            | {
                "scenario_id": scenario.pk,
                "target_pct": scenario.target_pct,
                "in_use": scenario.pk == piece.scenario_id,
                "is_default": scenario.is_default,
                "may_switch": services.may_switch_to(request.user, scenario),
            }
        )
    stored = services.live_sale_price(piece)
    return {
        "prices": prices,
        "show_margin": show_margin,
        # the legacy's last row: until a piece is put on a scenario it is quoted
        # at the rates written on its own lines, and that is what is in use
        "stored": {"price": stored} | margin_of(stored),
        "on_scenario": piece.scenario_id is not None,
        "may_clear": request.user.is_admin(),
    }


@login_required
def piece_scenarios(request, jewel_code):
    piece = get_object_or_404(_visible_pieces(request), jewel_code__iexact=jewel_code)
    if not (request.user.has_perm(VIEW_SALE) or request.user.has_perm(VIEW_COST)):
        raise PermissionDenied("You cannot see pricing.")
    return render(request, "stock/piece_scenarios.html", {"piece": piece, **_scenario_prices(request, piece)})


#: The piece's own fields that the detail screen edits in place. Jewel code is
#: absent by design — it is the identity of a physical object. So are design
#: name, category and collection: those belong to the *style*, and editing one
#: here would silently retag every other piece of that design.
INLINE_FIELDS = (
    "style",
    "sub_category",
    "metal_purity",
    "metal_colour",
    "size_label",
    "diamond_quality",
    "received_on",
    "measured_gross_wt_gm",
    "length_mm",
    "breadth_mm",
    "height_mm",
    "huid",
    "hallmarked_on",
    "hallmark_centre",
)


def _inline_form(piece):
    """``PieceForm`` again, one field per editor on the detail screen.

    Each value reads as text until its pencil is clicked; the widget rendered
    here is what appears then. Validation is the edit screen's own rather than
    a second copy of it.
    """
    form = PieceForm(instance=piece)
    for name in INLINE_FIELDS:
        widget = form.fields[name].widget
        widget.attrs["class"] = f"inplace {widget.attrs.get('class', '')}".strip()
    return form


@login_required
@require_POST
def piece_field(request, jewel_code):
    """Save one field edited in place on the detail screen."""
    piece = get_object_or_404(_visible_pieces(request), jewel_code__iexact=jewel_code)
    if not request.user.has_perm(EDIT_BOM):
        raise PermissionDenied("You are not authorised to edit this piece.")
    field = request.POST.get("field")
    if field not in INLINE_FIELDS:
        raise PermissionDenied(f"{field!r} is not editable here.")
    form = modelform_factory(Piece, form=PieceForm, fields=[field])(request.POST, instance=piece)
    if form.is_valid():
        form.save()
        services.log(request.user, "UPDATE", "jewel_code", piece.pk, f"{field} edited on the detail screen")
    else:
        messages.error(request, "; ".join(f"{field}: {e}" for errors in form.errors.values() for e in errors))
    return _redirect_back(request, reverse("stock:piece_detail", args=[piece.jewel_code]))


#: ``Meera — NOR-041 — 98…`` comes back from the datalist; the code is the part
#: that identifies anybody.
CUSTOMER_CODE = re.compile(r"\b([A-Z]{2,5}-\d+)\b")


def _sale_customer(request, new_name):
    """Who the sale is against: a new record, one picked from the CRM, or nobody.

    An unrecognised name is refused rather than dropped. Selling to "Meara" when
    Meera exists is a customer record that never gets the sale attached to it,
    and nothing on the screen would have said so.
    """
    if new_name:
        return crm_services.quick_customer(new_name, request.POST.get("new_customer_phone"))
    if request.POST.get("customer"):
        return Customer.objects.filter(pk=request.POST["customer"]).first()
    picked = (request.POST.get("customer_pick") or "").strip()
    if not picked:
        return None  # a walk-in, as the placeholder says
    code = CUSTOMER_CODE.search(picked)
    customer = (
        Customer.objects.filter(customer_code=code.group(1)).first()
        if code
        else Customer.objects.filter(name__iexact=picked).first()
    )
    if customer is None:
        raise ValidationError(
            f"No customer matches “{picked}”. Pick one from the list, or use ＋ New customer."
        )
    return customer


@login_required
@require_POST
def sell_piece_view(request, jewel_code):
    piece = get_object_or_404(_visible_pieces(request), jewel_code__iexact=jewel_code)
    new_name = (request.POST.get("new_customer_name") or "").strip()
    try:
        customer = _sale_customer(request, new_name)
    except ValidationError as error:
        messages.error(request, _message(error))
        return redirect("stock:piece_detail", jewel_code=piece.jewel_code)
    try:
        sale = services.sell_piece(
            request.user,
            piece,
            sold_price=request.POST["sold_price"],
            discount_amt=request.POST.get("discount_amt") or 0,
            customer=customer,
            customer_name=customer.name if customer else request.POST.get("customer_name"),
            customer_phone=customer.mobile if customer else request.POST.get("customer_phone"),
        )
    except (ValidationError, PermissionDenied) as error:
        messages.error(request, _message(error))
    except KeyError:
        messages.error(request, "A sold price is required.")
    else:
        who = f" to {customer.name} ({customer.customer_code})" if customer else ""
        messages.success(request, f"{piece.jewel_code} sold for {sale.sold_price}{who}.")
    return redirect("stock:piece_detail", jewel_code=piece.jewel_code)


@login_required
@require_POST
def melt_piece_view(request, jewel_code):
    piece = get_object_or_404(_visible_pieces(request), jewel_code__iexact=jewel_code)
    try:
        services.melt_piece(request.user, piece, request.POST.get("reason", ""))
    except (ValidationError, PermissionDenied) as error:
        messages.error(request, _message(error))
    else:
        messages.success(request, f"{piece.jewel_code} melted.")
    return redirect("stock:piece_detail", jewel_code=piece.jewel_code)


@login_required
@require_POST
def set_piece_scenario_view(request, jewel_code):
    """The Pricing tab's radio: put this piece on a scenario, or back on its own lines."""
    piece = get_object_or_404(_visible_pieces(request), jewel_code__iexact=jewel_code)
    try:
        scenario = services.set_piece_scenario(request.user, piece, request.POST.get("scenario") or None)
    except (ValidationError, PermissionDenied) as error:
        messages.error(request, _message(error))
    else:
        price = services.scenario_price(piece, scenario) if scenario else None
        messages.success(
            request,
            f"{piece.jewel_code} now priced on {scenario.name} — {price.price:.0f}."
            if scenario
            else f"{piece.jewel_code} is back on the rates on its own lines.",
        )
    return _redirect_back(request, reverse("stock:piece_detail", args=[piece.jewel_code]) + "?tab=pricing")


@login_required
@require_POST
def move_piece_view(request, jewel_code):
    piece = get_object_or_404(_visible_pieces(request), jewel_code__iexact=jewel_code)
    action = request.POST.get("action")
    try:
        if action == "receive":
            services.receive_piece(request.user, piece, request.POST["location"])
        elif action == "transfer":
            services.transfer_piece(request.user, piece, request.POST["location"])
        elif action == "reserve":
            services.reserve_piece(request.user, piece, request.POST.get("party_name"))
        elif action == "unreserve":
            services.unreserve_piece(request.user, piece)
        else:
            messages.error(request, f"Unknown action {action!r}.")
    except (ValidationError, PermissionDenied) as error:
        messages.error(request, _message(error))
    else:
        messages.success(request, f"{piece.jewel_code}: {action}.")
    return redirect("stock:piece_detail", jewel_code=piece.jewel_code)


def _redirect_back(request, fallback):
    """Honour ``?next=`` when it points at us, and ignore it when it does not.

    ``startswith("/")`` is not enough: ``//evil.com`` and its backslash twin both
    start with a slash and both send the browser off-site.
    """
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(target)
    return redirect(fallback)


def _message(error):
    if isinstance(error, ValidationError):
        return "; ".join(error.messages)
    return str(error)


@login_required
@permission_required("accounts.manage_materials", raise_exception=True)
def material_list(request):
    query = (request.GET.get("q") or "").strip()
    selected_cat = (request.GET.get("cat") or "").strip()
    materials = Material.objects.select_related("category", "metal").order_by("category__sort_order", "item_code")
    if query:
        materials = materials.filter(Q(item_code__icontains=query) | Q(item_name__icontains=query))
    if selected_cat:
        materials = materials.filter(category_id=selected_cat)
    materials = materials.annotate(used_on_lines=Count("bom_lines"))
    template = "stock/_material_rows.html" if request.headers.get("HX-Request") else "stock/material_list.html"
    return render(
        request,
        template,
        {
            "materials": materials,
            "q": query,
            "categories": MaterialCategory.objects.all(),
            "selected_cat": selected_cat,
        },
    )


@login_required
def rate_list(request):
    if not (request.user.has_perm(VIEW_SALE) or request.user.has_perm(VIEW_COST)):
        raise PermissionDenied("You cannot see rates.")
    chart = RateChart.objects.filter(is_default=True).first()
    lines = (
        RateChartLine.objects.filter(chart=chart).select_related("material", "material__category")
        if chart
        else RateChartLine.objects.none()
    )
    show_multiple = allowed(request.user, "cost_rate") and allowed(request.user, "sale_rate")
    rows = []
    for line in lines:
        row = {
            "material": line.material.item_code,
            "material_name": line.material.item_name,
            "category": line.material.category_id,
            "size_band": line.size_band,
            "cost_rate": line.cost_rate,
            "sale_rate": line.sale_rate,
            "uom": line.rate_uom or line.material.default_uom,
        }
        row = {key: value for key, value in row.items() if allowed(request.user, key)}
        if show_multiple and line.cost_rate and line.sale_rate:
            row["multiple"] = services.round_to(line.sale_rate / line.cost_rate, 2)
        rows.append(row)
    purity_rates = []
    for purity in MetalPurity.objects.select_related("metal"):
        entry = {
            "karat": purity.karat,
            "metal": purity.metal.name,
            "sale_pct": purity.sale_factor * 100,
            "sale_rate": services.metal_rate(purity.karat, "SALE"),
        }
        if allowed(request.user, "cost_rate"):
            # true fineness is the cost basis; the spread over it is the margin
            entry |= {
                "cost_rate": services.metal_rate(purity.karat, "COST"),
                "fineness_pct": purity.true_fineness * 100,
                "spread_pt": (purity.sale_factor - purity.true_fineness) * 100,
            }
        purity_rates.append(entry)
    return render(
        request,
        "stock/rate_list.html",
        {
            "chart": chart,
            "rows": rows,
            "show_multiple": show_multiple,
            "metals": Metal.objects.filter(is_active=True),
            "purity_rates": purity_rates,
        },
    )


@login_required
@require_POST
def set_rate_view(request):
    try:
        metal = services.set_metal_rate(request.user, request.POST["code"], request.POST["pure_rate"])
    except (ValidationError, PermissionDenied) as error:
        messages.error(request, _message(error))
    else:
        # the legacy toast named every karat the change moved, because "gold is
        # now 15600" does not tell a showroom what an 18K piece now sells for
        derived = " · ".join(
            f"{purity.karat} {services.alloy_sale_rate(purity.karat):,.0f}"
            for purity in MetalPurity.objects.filter(metal=metal).order_by("-sale_factor")
        )
        messages.success(
            request,
            f"{metal.name} is now {metal.pure_rate:,.0f} per gram. {derived}. Frozen costs did not move.",
        )
    return _redirect_back(request, "stock:rate_list")


# ── stock count ──────────────────────────────────────────────────────────
@login_required
def count_list(request):
    counts = StockCount.objects.select_related("location", "counted_by").filter(
        location_id__in=request.user.visible_location_ids()
    )
    on_books = dict(
        _visible_pieces(request)
        .filter(stock_state__in=list(COUNTABLE_STATES))
        .values_list("location_id")
        .annotate(pieces=Count("pk"))
        .values_list("location_id", "pieces")
    )
    locations = list(Location.objects.filter(is_active=True))
    for location in locations:
        location.live_pieces = on_books.get(location.pk, 0)
    return render(request, "stock/count_list.html", {"counts": counts, "locations": locations})


@login_required
@require_POST
def count_open(request):
    try:
        count = services.open_count(request.user, request.POST["location"])
    except (ValidationError, PermissionDenied) as error:
        messages.error(request, _message(error))
        return redirect("stock:count_list")
    return redirect("stock:count_detail", count_id=count.pk)


@login_required
def count_detail(request, count_id):
    count = get_object_or_404(StockCount, pk=count_id)
    state = services.count_state(request.user, count)
    return render(request, "stock/count_detail.html", {"count": count, "state": state})


@login_required
@require_POST
def count_scan(request, count_id):
    """The scan flow: one POST, one row partial back. No page reload, ever."""
    count = get_object_or_404(StockCount, pk=count_id)
    try:
        result = services.scan_piece(request.user, count, request.POST.get("code", ""))
    except (ValidationError, PermissionDenied) as error:
        result = {"verdict": "ERROR", "code": request.POST.get("code", ""), "note": _message(error)}
    state = services.count_state(request.user, count)
    return render(request, "stock/_count_scan_result.html", {"count": count, "result": result, "state": state})


@login_required
@require_POST
def count_unscan(request, count_id):
    count = get_object_or_404(StockCount, pk=count_id)
    try:
        state = services.unscan_piece(request.user, count, request.POST.get("code", ""))
    except (ValidationError, PermissionDenied) as error:
        messages.error(request, _message(error))
        state = services.count_state(request.user, count)
    return render(request, "stock/_count_scan_result.html", {"count": count, "result": None, "state": state})


@login_required
@require_POST
def count_close(request, count_id):
    count = get_object_or_404(StockCount, pk=count_id)
    try:
        services.close_count(
            request.user, count, cancel=bool(request.POST.get("cancel")), notes=request.POST.get("notes")
        )
    except (ValidationError, PermissionDenied) as error:
        messages.error(request, _message(error))
    return redirect("stock:count_detail", count_id=count.pk)


# ── repairs, sales, reports ──────────────────────────────────────────────
@login_required
def repair_list(request):
    jobs = RepairJob.objects.select_related("piece", "vendor").all()
    return render(request, "stock/repair_list.html", {"jobs": jobs})


@login_required
@require_POST
def repair_complete(request, job_id):
    job = get_object_or_404(RepairJob, pk=job_id)
    try:
        version = services.complete_repair(request.user, job)
    except (ValidationError, PermissionDenied) as error:
        messages.error(request, _message(error))
    else:
        messages.success(request, f"{job.job_no} closed at BOM v{version}.")
    return redirect("stock:repair_list")


@login_required
@permission_required("accounts.view_sale", raise_exception=True)
def sale_list(request):
    sales = Sale.objects.select_related("piece", "location", "customer").all()[:200]
    rows = []
    for sale in sales:
        row = {
            "sale_id": sale.sale_id,
            "sold_on": sale.sold_on,
            "jewel_code": sale.piece.jewel_code if sale.piece_id else None,
            "customer": sale.customer.name if sale.customer_id else sale.customer_name,
            "customer_id": sale.customer_id,
            "customer_code": sale.customer.customer_code if sale.customer_id else None,
            "location": sale.location.name if sale.location_id else None,
            "source": sale.source,
            "sold_price": sale.sold_price,
            "cost_at_sale": sale.cost_at_sale,
            "margin_amt": sale.margin_amt,
        }
        rows.append({key: value for key, value in row.items() if allowed(request.user, key)})
    return render(request, "stock/sale_list.html", {"rows": rows})


@login_required
@permission_required("accounts.view_margin", raise_exception=True)
def margin_report(request):
    """Margin is only meaningful where a cost exists — stock-sourced sales."""
    sales = Sale.objects.filter(source=Sale.STOCK)
    totals = sales.aggregate(revenue=Sum("sold_price"), cost=Sum("cost_at_sale"), margin=Sum("margin_amt"))
    crm_revenue = Sale.objects.filter(source=Sale.CRM).aggregate(revenue=Sum("sold_price"))["revenue"] or Decimal("0")

    # stock by location: pieces, carried cost and the unpriced few (pgReports)
    show_value = allowed(request.user, "cost_price")
    priced = Q(bom_versions__is_current=True, bom_versions__total_cost_price__gt=0)
    annotations = {
        "pieces": Count("pk", distinct=True),
        "priced_pieces": Count("pk", filter=priced, distinct=True),
    }
    if show_value:
        annotations["value"] = Sum("bom_versions__total_cost_price", filter=Q(bom_versions__is_current=True))
    by_location = list(
        _visible_pieces(request)
        .filter(stock_state__in=list(COUNTABLE_STATES))
        .values("location__code", "location__name")
        .annotate(**annotations)
        .order_by("location__code")
    )
    for entry in by_location:
        entry["unpriced"] = entry["pieces"] - entry["priced_pieces"]
    return render(
        request,
        "stock/margin_report.html",
        {
            "totals": totals,
            "crm_revenue": crm_revenue,
            "sales": sales.select_related("piece")[:200],
            "by_location": by_location,
            "show_value": show_value,
        },
    )


@login_required
def piece_export(request):
    """CSV of what this user may see — the same gate as the screen.

    An export is where masking is most often forgotten, so it goes through
    ``piece_row`` like everything else and is logged as an EXPORT.
    """
    pieces, _, _ = _filtered(request)
    rows = [piece_row(request.user, piece) for piece in pieces[:5000]]
    fields = list(rows[0].keys()) if rows else ["jewel_code"]
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="pieces.csv"'
    writer = csv.DictWriter(response, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    services.log(request.user, "EXPORT", "jewel_code", "piece_export", f"{len(rows)} rows", row_count=len(rows))
    return response


# ── the tabs the legacy nav carried that had no screen here ──────────────
def tab_required(tab):
    """Enforce the legacy ``ROLES[role].tabs`` list on the server.

    The old nav rendered a padlock, but the gate that mattered lived in the
    database function — "a bug in the UI cannot let it through". The nav still
    renders the padlock; this is the half that actually refuses.
    """

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            code = _role_code(request.user)
            if tab not in ROLE_TABS[code]:
                raise PermissionDenied(f"{ROLE_GROUPS[code]['name']} cannot open this screen.")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


@login_required
@tab_required("styles")
def style_list(request):
    """The Design Library. A style is the design; many jewel codes hang off one.

    ``nos_min_qty`` is the floor for the *design*, so the shortfall is counted
    per style and never per jewel code — a jewel code is one physical piece and
    can never be restocked.
    """
    query = (request.GET.get("q") or "").strip()
    styles = Style.objects.select_related("category", "collection").annotate(
        piece_count=Count("pieces", distinct=True),
        live_pieces=Count("pieces", filter=Q(pieces__stock_state=StockState.IN_STOCK), distinct=True),
    )
    if query:
        styles = styles.filter(Q(style_code__icontains=query) | Q(name__icontains=query))
    styles = list(styles.order_by("style_code"))
    # one example piece per style, for the thumbnail the legacy card carried
    examples = {}
    for piece in Piece.objects.filter(style__in=[s.pk for s in styles]).order_by("style_id", "jewel_code"):
        examples.setdefault(piece.style_id, piece)
    thumbs = _piece_thumbs(piece.pk for piece in examples.values())
    for style in styles:
        example = examples.get(style.pk)
        style.example = example
        style.thumb = thumbs.get(example.pk) if example else None
        style.shortfall = max((style.nos_min_qty or 0) - style.live_pieces, 0)
    return render(
        request,
        "stock/style_list.html",
        {"nav": "styles", "styles": styles, "q": query},
    )


@login_required
@tab_required("melt")
def melt_list(request):
    """The melt register. Melting is terminal, so this is the whole record."""
    melts = MeltRecord.objects.select_related("piece", "authorised_by", "location").order_by("-melted_on", "-melt_id")
    return render(
        request,
        "stock/melt_list.html",
        {"nav": "melt", "melts": melts, "thumbs": _piece_thumbs(row.piece_id for row in melts)},
    )


@login_required
@tab_required("reports")
def reports(request):
    """Stock by location, with the unpriced column the legacy insisted on.

    Without that column a partly-imported catalogue looks healthy while being
    badly understated.
    """
    live = Piece.objects.visible_to(request.user).exclude(stock_state__in=TERMINAL_STATES)
    rows = {}
    for piece in live.select_related("location"):
        key = piece.location.name if piece.location_id else "—"
        row = rows.setdefault(key, {"location": key, "pieces": 0, "value": Decimal("0"), "unpriced": 0})
        row["pieces"] += 1
        version = piece.current_bom()
        cost = version.total_cost_price if version else None
        if cost:
            row["value"] += cost
        else:
            row["unpriced"] += 1
    context = {"nav": "reports", "rows": sorted(rows.values(), key=lambda row: row["location"])}
    if not allowed(request.user, "cost_price"):
        for row in context["rows"]:
            row.pop("value", None)
    return render(request, "stock/reports.html", context)


@login_required
@tab_required("audit")
def audit(request):
    """The activity log, append only.

    "Who downloaded" on its own is close to useless — an export row records the
    row count and whether cost and margin columns were in the file, which is
    the difference between knowing someone exported and knowing what they took.
    """
    entries = ActivityLog.objects.select_related("user").order_by("-changed_at")
    action = (request.GET.get("action") or "").strip()
    if action:
        entries = entries.filter(action=action)
    actions = ActivityLog.objects.values_list("action", flat=True).distinct().order_by("action")
    page = Paginator(entries, 100).get_page(request.GET.get("page"))
    return render(
        request,
        "stock/audit.html",
        {"nav": "audit", "page": page, "actions": actions, "action": action},
    )


@login_required
@tab_required("data")
def data(request):
    """Import / Export. The counts are what each export would contain."""
    return render(
        request,
        "stock/data.html",
        {
            "nav": "data",
            "counts": {
                "pieces": Piece.objects.count(),
                "bom_lines": BomLine.objects.count(),
                "media": MediaAsset.objects.filter(is_archived=False).count(),
                "movements": StockMovement.objects.count(),
                "sales": Sale.objects.count(),
                "styles": Style.objects.count(),
                "materials": Material.objects.count(),
            },
        },
    )


#: the legacy Settings tab bar, in its order
SETTINGS_TABS = [
    ("cats", "Categories"),
    ("locs", "Locations"),
    ("mats", "Materials"),
    ("charts", "Rate charts"),
    ("scen", "Scenarios"),
    ("users", "Users"),
    ("perms", "Permissions"),
    ("rates", "Rates"),
]

#: the permission matrix the legacy Settings screen printed, verbatim
CAPABILITY_MATRIX = [
    ("manage_materials", "See material breakup", "Which stones and metal are in the piece"),
    ("view_sale", "See sale price", "Rates and amounts on the sale side"),
    ("view_cost", "See cost price", "Cost rates, cost amounts — the sensitive one"),
    ("view_margin", "See margin", "Sale minus cost"),
    ("view_vendor", "See vendor", "Who made it and their turnaround"),
    ("adjust_stock", "Backfill & reverse sales", "Record old sales and reverse entries"),
    ("edit_bom", "Edit the BOM", "Fork a correction version"),
    ("melt", "Melt", "Destroy a piece. Irreversible."),
]


@login_required
@tab_required("admin")
def settings_view(request):
    """Users & Settings — the legacy's tabbed admin screen.

    Categories, locations and materials are editable here because they were in
    the old app. Users are not: Django's own admin owns password hashes, group
    membership and the must-change flag, and a second half-implementation of
    that is how a role quietly gains a capability.
    """
    tab = request.GET.get("tab") or "cats"
    if tab not in dict(SETTINGS_TABS):
        tab = "cats"
    context = {"nav": "admin", "tab": tab, "setting_tabs": SETTINGS_TABS}

    if request.method == "POST":
        return _settings_post(request, tab)

    if tab == "cats":
        context["categories"] = Category.objects.annotate(
            designs=Count("styles", distinct=True), pieces=Count("styles__pieces", distinct=True)
        ).order_by("sort_order", "name")
        context["form"] = CategoryForm()
    elif tab == "locs":
        context["locations"] = Location.objects.annotate(
            live=Count("pieces", filter=~Q(pieces__stock_state__in=TERMINAL_STATES), distinct=True)
        ).order_by("code")
        context["form"] = LocationForm()
    elif tab == "mats":
        query = (request.GET.get("q") or "").strip()
        picked = request.GET.get("cat") or ""
        materials = Material.objects.select_related("category", "metal").annotate(
            used_on_lines=Count("bom_lines")
        )
        # counted off a plain queryset: the used_on_lines join would multiply a
        # material by its BOM lines and the pills would read as nonsense
        matching = Material.objects.all()
        if query:
            search = Q(item_code__icontains=query) | Q(item_name__icontains=query)
            materials, matching = materials.filter(search), matching.filter(search)
        # the pills count what the search holds, not what the table shows, so
        # picking one never changes the other numbers under it
        counts = {row["category_id"]: row["n"] for row in matching.values("category_id").annotate(n=Count("pk"))}
        categories = list(MaterialCategory.objects.all())
        for category in categories:
            category.n, category.selected = counts.get(category.pk, 0), category.pk == picked
        if picked:
            materials = materials.filter(category_id=picked)
        context |= {
            "materials": materials.order_by("category__sort_order", "item_code")[:400],
            "material_categories": categories,
            "material_total": sum(counts.values()),
            "cat": picked,
            "q": query,
            "form": MaterialForm(),
        }
    elif tab == "charts":
        chart_id = request.GET.get("chart")
        charts = list(RateChart.objects.order_by("-is_default", "code", "-version_no"))
        chart = next((c for c in charts if str(c.pk) == chart_id), None) or next(iter(charts), None)
        lines = (
            list(
                RateChartLine.objects.filter(chart=chart)
                .select_related("material")
                .order_by("material__item_code", "size_band")
            )
            if chart
            else []
        )
        # the edit history each row shows is the audit log, read back by pk —
        # a second history table would be a second thing to keep honest
        history = {}
        for entry in ActivityLog.objects.filter(
            table_name="rate_chart_line", record_pk__in=[str(line.pk) for line in lines]
        ).select_related("user"):
            history.setdefault(entry.record_pk, []).append(entry)
        hidden = {
            field
            for capability, field in ((VIEW_COST, "cost_rate"), (VIEW_SALE, "sale_rate"))
            if not request.user.has_perm(capability)
        }
        for line in lines:
            line.history = history.get(str(line.pk), [])
            for entry in line.history:
                # the log keeps everything; the row shows only what this reader may see
                entry.shown = _rate_diff(
                    {k: v for k, v in (entry.old_values or {}).items() if k not in hidden},
                    {k: v for k, v in (entry.new_values or {}).items() if k not in hidden},
                )
        context |= {
            "charts": charts,
            "chart": chart,
            "lines": lines,
            "line_form": RateChartLineForm(initial={"chart": chart}) if chart else None,
            "chart_in_use": chart.lines.filter(material__bom_lines__isnull=False).exists() if chart else False,
        }
    elif tab == "scen":
        context |= _scenario_tab(request)
    elif tab == "users":
        from accounts.models import User

        context["users"] = User.objects.prefetch_related("groups").order_by("username")
    elif tab == "perms":
        from accounts.models import User

        context |= {
            "matrix": CAPABILITY_MATRIX,
            "roles": [
                (code, spec["name"], {cap.split(".", 1)[1] for cap in spec["caps"]})
                for code, spec in ROLE_GROUPS.items()
            ],
            "role_tabs": ROLE_TABS,
        }
    elif tab == "rates":
        context |= {
            "metals": Metal.objects.order_by("code"),
            "purities": MetalPurity.objects.select_related("metal").order_by("metal__code", "-sale_factor"),
        }
    return render(request, "stock/settings.html", context)


def _scenario_role_rows(scenario):
    """Every role, with what this scenario grants it.

    A role that cannot see a sale price cannot be granted a scenario at all —
    the checkbox is shown disabled rather than hidden so the screen says why.
    """
    from django.contrib.auth.models import Group

    granted = {r.group_id: r for r in scenario.roles.all()} if scenario and scenario.pk else {}
    rows = []
    for group in Group.objects.prefetch_related("permissions").order_by("name"):
        may_price = any(p.codename == "view_sale" for p in group.permissions.all())
        role = granted.get(group.pk)
        rows.append(
            {
                "group": group,
                "label": ROLE_GROUPS.get(group.name, {}).get("name", group.name),
                "may_price": may_price,
                "may_see": bool(role and role.may_see) and may_price,
                "may_switch": bool(role and role.may_switch) and may_price,
            }
        )
    return rows


def _scenario_tab(request):
    """The Scenarios tab: the list, and one scenario open under it."""
    scenarios = list(Scenario.objects.prefetch_related("roles__group").order_by("-is_default", "code"))
    picked = request.GET.get("scenario")
    editing = Scenario() if picked == "new" else next((s for s in scenarios if str(s.pk) == picked), None)
    return {
        "scenarios": scenarios,
        "editing": editing,
        "form": ScenarioForm(instance=editing) if editing is not None else None,
        "role_rows": _scenario_role_rows(editing),
    }


@transaction.atomic
def _scenario_post(request):
    """Create or edit a scenario, and the roles it is granted to."""
    from .models import ScenarioRole

    back = f"{reverse('stock:settings')}?tab=scen"
    pk = request.POST.get("pk") or None
    instance = get_object_or_404(Scenario, pk=pk) if pk else None

    if request.POST.get("delete"):
        if instance is None:
            raise Http404("No such scenario.")
        if instance.pieces.exists():
            messages.error(request, f"{instance.name} is pricing live pieces. Retire it instead.")
        else:
            services.log(request.user, "REFERENCE_DELETED", "scenario", str(instance.pk), instance.name)
            instance.delete()
            messages.success(request, f"{instance.name} is gone.")
        return redirect(back)

    # one default, enforced by a partial unique index. The old one has to stand
    # down *before* the form validates, because ModelForm checks the table's own
    # constraints — and if the form then turns out invalid the whole thing is
    # rolled back, so a refused save cannot leave the catalogue with no default.
    if request.POST.get("is_default"):
        Scenario.objects.exclude(pk=pk or 0).filter(is_default=True).update(is_default=False)

    form = ScenarioForm(request.POST, instance=instance)
    if not form.is_valid():
        transaction.set_rollback(True)
        messages.error(
            request,
            "; ".join(f"{field}: {error[0]}" for field, error in form.errors.items()),
        )
        return redirect(f"{back}&scenario={pk or 'new'}")
    scenario = form.save()

    see = set(request.POST.getlist("may_see"))
    switch = set(request.POST.getlist("may_switch"))
    for row in _scenario_role_rows(scenario):
        group, key = row["group"], str(row["group"].pk)
        # switching is a price decision, so it implies being able to see the
        # scenario at all; a role with no sale price gets neither
        wants_switch = row["may_price"] and key in switch
        wants_see = row["may_price"] and (key in see or wants_switch)
        if wants_see:
            ScenarioRole.objects.update_or_create(
                scenario=scenario, group=group, defaults={"may_see": True, "may_switch": wants_switch}
            )
        else:
            ScenarioRole.objects.filter(scenario=scenario, group=group).delete()

    services.log(request.user, "REFERENCE_SAVED", "scenario", str(scenario.pk), scenario.name)
    messages.success(request, f"{scenario.name} saved.")
    return redirect(back)


def _settings_post(request, tab):
    """Category, location and material writes. Everything else is read-only here."""
    services.require(request.user, EDIT_BOM, "You cannot change reference data.")
    if tab == "charts":
        return _chart_line_post(request)
    if tab == "mats" and request.FILES.get("csv"):
        return _material_import(request)
    if tab == "scen":
        return _scenario_post(request)
    forms = {"cats": (CategoryForm, Category), "locs": (LocationForm, Location), "mats": (MaterialForm, Material)}
    if tab not in forms:
        raise PermissionDenied("That tab has nothing to save.")
    form_class, model = forms[tab]
    back = f"{reverse('stock:settings')}?tab={tab}"

    retire = request.POST.get("retire")
    if retire:
        row = get_object_or_404(model, pk=retire)
        # A location is retired, never deleted: movements and old pieces still
        # point at it. One holding live stock cannot be retired at all.
        if model is Location and row.pieces.exclude(stock_state__in=TERMINAL_STATES).exists():
            messages.error(request, f"{row.name} still holds live stock. Move it first.")
        else:
            row.is_active = not row.is_active
            row.save(update_fields=["is_active"])
            services.log(request.user, "REFERENCE_TOGGLE", model._meta.db_table, str(row.pk))
            messages.success(request, f"{row} is now {'active' if row.is_active else 'retired'}.")
        return redirect(back)

    edit = request.POST.get("pk")
    instance = get_object_or_404(model, pk=edit) if edit else None
    form = form_class(request.POST, instance=instance)
    if form.is_valid():
        row = form.save()
        services.log(request.user, "REFERENCE_SAVED", model._meta.db_table, str(row.pk))
        messages.success(request, f"{row} saved.")
    else:
        messages.error(request, "; ".join(f"{field}: {error[0]}" for field, error in form.errors.items()))
    return redirect(back)


#: the bulk sheet's columns, in order. ``item_code`` is what an upload matches
#: on, so the file that comes out is the file that goes back in.
MATERIAL_COLUMNS = ["item_code", "item_name", "size", "category", "default_uom", "metal", "is_active"]


@login_required
@tab_required("admin")
def material_export(request):
    """The material register as CSV, and the template an upload comes back on.

    ``?sample=1`` writes the header and five rows instead of the register — the
    same columns either way, because a template that does not match the export
    is a template nobody can round-trip.
    """
    materials = Material.objects.select_related("category", "metal").order_by("category__sort_order", "item_code")
    query = (request.GET.get("q") or "").strip()
    if query:
        materials = materials.filter(Q(item_code__icontains=query) | Q(item_name__icontains=query))
    if request.GET.get("cat"):
        materials = materials.filter(category_id=request.GET["cat"])
    sample = bool(request.GET.get("sample"))
    if sample:
        materials = materials[:5]

    name = "materials-sample" if sample else "materials"
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{name}-{timezone.localdate():%Y-%m-%d}.csv"'
    writer = csv.writer(response)
    writer.writerow(MATERIAL_COLUMNS)
    rows = 0
    for material in materials:
        writer.writerow(
            [
                material.item_code,
                material.item_name,
                material.size or "",
                material.category_id,
                material.default_uom,
                material.metal_id or "",
                material.is_active,
            ]
        )
        rows += 1
    if sample and not rows:
        # an empty register still has to hand back something fillable
        writer.writerow(["DRKL", "Diamond RKL", "1.0mm", "DIAMOND", "CT", "", "True"])
    services.log(request.user, "EXPORT", "material", name, f"{rows} rows", row_count=rows)
    return response


def _material_import(request):
    """Upsert the material register from a CSV, keyed on ``item_code``.

    Every row goes through ``MaterialForm``, so an upload cannot write a row the
    Add material modal would have refused. One bad row rolls the whole file back:
    a half-applied sheet is the state nobody can describe afterwards.
    """
    try:
        rows = list(csv.DictReader(io.TextIOWrapper(request.FILES["csv"], encoding="utf-8-sig")))
    except (UnicodeDecodeError, csv.Error):
        messages.error(request, "That file is not readable as CSV. Export the sheet again and edit that.")
        return redirect(f"{reverse('stock:settings')}?tab=mats")

    created = updated = 0
    errors = []
    with transaction.atomic():
        for number, row in enumerate(rows, start=2):  # row 1 is the header
            code = (row.get("item_code") or "").strip()
            if not code:
                errors.append(f"row {number}: no item_code")
                continue
            existing = Material.objects.filter(item_code=code).first()
            data = {column: (row.get(column) or "").strip() for column in MATERIAL_COLUMNS}
            if not data["is_active"]:
                # a blank column keeps what the row already said rather than
                # silently retiring every material in the sheet
                data["is_active"] = str(existing.is_active if existing else True)
            form = MaterialForm(data, instance=existing)
            if form.is_valid():
                form.save()
                updated += bool(existing)
                created += not existing
            else:
                errors.append(f"row {number} ({code}): " + "; ".join(f"{f}: {e[0]}" for f, e in form.errors.items()))
        if errors:
            transaction.set_rollback(True)

    if errors:
        messages.error(request, f"Nothing was saved — {len(errors)} row(s) were refused. " + " · ".join(errors[:5]))
    else:
        services.log(
            request.user, "IMPORT", "material", "material_import", f"{created} new, {updated} updated", row_count=len(rows)
        )
        messages.success(request, f"{created} material(s) added, {updated} updated.")
    return redirect(f"{reverse('stock:settings')}?tab=mats")


#: what a rate history entry records — the four values that can move
RATE_FIELDS = ["size_band", "cost_rate", "sale_rate", "rate_uom"]


def _rate_snapshot(line):
    return {field: (str(getattr(line, field)) if getattr(line, field) not in (None, "") else None) for field in RATE_FIELDS}


def _rate_diff(before, after):
    """`cost_rate 100 → 120 · sale_rate 200 → 240`, or the whole row when it is new."""
    if not before:
        return " · ".join(f"{k} {v}" for k, v in after.items() if v is not None) or "added"
    moved = [f"{k} {before.get(k) or '—'} → {after[k] or '—'}" for k in after if before.get(k) != after[k]]
    return " · ".join(moved) or "no change"


def _chart_line_post(request):
    """Add or edit one rate. The old values go to the audit log, never over the wire back.

    A locked chart refuses the write: a quote priced in March has to still
    reconcile in September, so the fix for a wrong rate is a fork, not an edit.
    """
    line = get_object_or_404(RateChartLine, pk=request.POST["pk"]) if request.POST.get("pk") else None
    # snapshot first: validating binds the posted values onto the instance
    before = _rate_snapshot(line) if line else {}
    # a rate this user is not allowed to see is never posted, so it is carried
    # over rather than saved as the blank the form would otherwise receive
    posted = request.POST.copy()
    for capability, field in ((VIEW_COST, "cost_rate"), (VIEW_SALE, "sale_rate")):
        if not request.user.has_perm(capability):
            posted[field] = before.get(field) or ""
    form = RateChartLineForm(posted, instance=line)
    back = f"{reverse('stock:settings')}?tab=charts&chart={request.POST.get('chart') or ''}"
    if not form.is_valid():
        messages.error(request, "; ".join(f"{field}: {error[0]}" for field, error in form.errors.items()))
        return redirect(back)
    if form.cleaned_data["chart"].is_locked:
        messages.error(request, f"{form.cleaned_data['chart']} is locked. Fork it to change a rate.")
        return redirect(back)

    row = form.save()
    after = _rate_snapshot(row)
    services.log(
        request.user,
        "UPDATE" if before else "INSERT",
        "rate_chart_line",
        row.pk,
        detail=_rate_diff(before, after),
        old_values=before or None,
        new_values=after,
    )
    messages.success(request, f"{row.material.item_code} saved.")
    return redirect(back)


# ── writes the legacy had and this app did not expose ────────────────────
@login_required
@permission_required("accounts.edit_bom", raise_exception=True)
def piece_form(request, jewel_code=None):
    """New piece / Edit details.

    A new piece is *received* through the service, so it lands with a movement
    row rather than appearing in a location with no history of getting there.
    """
    piece = get_object_or_404(Piece, jewel_code=jewel_code) if jewel_code else None
    if request.method == "POST":
        form = PieceForm(request.POST, instance=piece)
        if form.is_valid():
            saved = form.save(commit=False)
            saved.updated_at = timezone.now()
            if piece is None:
                saved.created_by = request.user
                saved.stock_state = StockState.NOT_RECEIVED
                location = form.cleaned_data["location"]
                saved.location = None
                saved.save()
                BomVersion.objects.create(piece=saved, version_no=1, is_current=True, reason="INITIAL")
                services.receive_piece(request.user, saved, location, moved_at=saved.received_on)
                messages.success(request, f"{saved.jewel_code} received into {location.name}.")
            else:
                saved.save()
                services.log(request.user, "PIECE_EDITED", "jewel_code", str(saved.pk))
                messages.success(request, f"{saved.jewel_code} saved.")
            return redirect("stock:piece_detail", jewel_code=saved.jewel_code)
    else:
        form = PieceForm(instance=piece)
    return render(
        request,
        "stock/piece_form.html",
        {"nav": "stock", "form": form, "piece": piece},
    )


@login_required
@permission_required("accounts.edit_bom", raise_exception=True)
def piece_bom_edit(request, jewel_code):
    """Edit the bill of materials.

    ``set_bom`` forks a new version — the old one is superseded, never
    overwritten, which is what makes a correction auditable in the export.
    """
    piece = get_object_or_404(Piece, jewel_code=jewel_code)
    version = piece.current_bom()
    existing = (
        [
            {
                "material": line.material.item_code,
                "size_band": line.size_band or "",
                "qty_value": line.qty_value,
                "qty_uom": line.qty_uom,
                "pcs": line.pcs,
                "basis": line.basis,
                "cost_rate": line.cost_rate,
                "sale_rate": line.sale_rate,
                "is_labour": line.material.is_labour,
            }
            for line in BomLine.objects.filter(piece=piece, version_no=version.version_no)
            .select_related("material")
            .order_by("line_no")
        ]
        if version
        else []
    )

    if request.method == "POST":
        formset = BomLineFormSet(request.POST, prefix="line")
        if formset.is_valid():
            # a rate column the reader may not see is not on the form, so it
            # is carried forward off the row it came from rather than saved as
            # blank — the editor must not be able to wipe what it cannot show
            masked = [
                field
                for capability, field in ((VIEW_COST, "cost_rate"), (VIEW_SALE, "sale_rate"))
                if not request.user.has_perm(capability)
            ]
            lines = []
            for index, entry in enumerate(formset.cleaned_data):
                if not entry or entry.get("DELETE"):
                    continue
                was = existing[index] if index < len(existing) else {}
                line = {
                    key: entry.get(key)
                    for key in ("material", "qty_value", "qty_uom", "pcs", "basis", "cost_rate", "sale_rate")
                } | {"size_band": entry.get("size_band") or ""}
                if was.get("material") == line["material"]:
                    for field in masked:
                        line[field] = was.get(field)
                lines.append(line)
            note = request.POST.get("note") or None
            try:
                # fork first, then write the lines onto the fork: ``set_bom``
                # replaces the lines of whichever version is current, so
                # without the fork the old one would be overwritten and the
                # correction would not be auditable
                services.new_bom_version(request.user, piece, BomChangeReason.CORRECTION, note=note)
                new_version = services.set_bom(request.user, piece, lines, note=note)
            except (ValidationError, PermissionDenied) as error:
                messages.error(request, _message(error))
            else:
                messages.success(request, f"{piece.jewel_code} is now on BOM v{new_version.version_no}.")
                return redirect("stock:piece_bom", jewel_code=piece.jewel_code)
    else:
        formset = BomLineFormSet(initial=existing, prefix="line")
    return render(
        request,
        "stock/piece_bom_edit.html",
        {
            "nav": "stock",
            "piece": piece,
            "version": version,
            "formset": formset,
            "materials": Material.objects.filter(is_active=True).order_by("item_code")[:800],
            "labour_codes": list(
                Material.objects.filter(is_active=True, category_id="LABOUR").values_list("item_code", flat=True)
            ),
            "uoms": Uom.choices,
        },
    )


@login_required
@require_POST
@permission_required("accounts.edit_bom", raise_exception=True)
def repair_open(request, jewel_code):
    piece = get_object_or_404(Piece, jewel_code=jewel_code)
    form = RepairForm(request.POST)
    if not form.is_valid():
        messages.error(request, "; ".join(f"{f}: {e[0]}" for f, e in form.errors.items()))
    else:
        try:
            job = services.open_repair(
                request.user,
                piece,
                form.cleaned_data["fault_description"],
                vendor=form.cleaned_data.get("vendor"),
                return_location=form.cleaned_data.get("return_location"),
            )
        except (ValidationError, PermissionDenied) as error:
            messages.error(request, _message(error))
        else:
            messages.success(request, f"{job.job_no} opened on {piece.jewel_code}.")
    return redirect("stock:piece_detail", jewel_code=jewel_code)


@login_required
@require_POST
def reserve_piece_view(request, jewel_code):
    """On approval, and back again. Both are movements, not a flag."""
    piece = get_object_or_404(Piece, jewel_code=jewel_code)
    release = request.POST.get("release")
    try:
        if release:
            services.unreserve_piece(request.user, piece)
            messages.success(request, f"{piece.jewel_code} is back in stock.")
        else:
            services.reserve_piece(request.user, piece, party_name=request.POST.get("party_name") or None)
            messages.success(request, f"{piece.jewel_code} is out on approval.")
    except (ValidationError, PermissionDenied) as error:
        messages.error(request, _message(error))
    return redirect("stock:piece_detail", jewel_code=jewel_code)


@login_required
@tab_required("styles")
def style_form(request, style_code=None):
    style = get_object_or_404(Style, style_code=style_code) if style_code else None
    if not request.user.has_perm(EDIT_BOM):
        raise PermissionDenied("You cannot change the design library.")
    if request.method == "POST":
        form = StyleForm(request.POST, instance=style)
        if form.is_valid():
            saved = form.save(commit=False)
            if style is None:
                saved.created_by = request.user
            saved.save()
            services.log(request.user, "STYLE_SAVED", "style", str(saved.pk))
            messages.success(request, f"{saved.style_code} saved.")
            return redirect("stock:style_list")
    else:
        form = StyleForm(instance=style)
    return render(request, "stock/style_form.html", {"nav": "styles", "form": form, "style": style})
