"""Screens ported from ``legacy/Stock/app/nornament.html``.

Port-as-is: what the old screen did, this screen does. The visual refresh is
post-cutover work and doing it here would make every difference a question of
"did we mean to change that?".

HTMX carries the live bits — search, the scan flow, inline rate edits — by
returning the same partials the full page renders.
"""
import csv
import datetime
import io
import re
from decimal import Decimal, InvalidOperation
from functools import wraps
from types import SimpleNamespace
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, ProtectedError, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.forms import modelform_factory
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_POST
from openpyxl import Workbook

from accounts.capabilities import ADJUST_STOCK, EDIT_BOM, ROLE_GROUPS, ROLE_TABS, VIEW_COST, VIEW_MARGIN, VIEW_SALE
from accounts.context_processors import _role_code
from crm import services as crm_services
from crm.models import Customer
from mediahub import services as media_services
from mediahub.models import MediaAsset

from . import services
from .enums import BomChangeReason, COUNTABLE_STATES, MediaKind, MovementType, StockState, TERMINAL_STATES, Uom
from .forms import (
    BomLineFormSet,
    RateChartForm,
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
from .importers import analyse as analyse_import
from .importers import commit as commit_import
from .importers import guess
from .importers import ivy
from .masking import allowed, mask, piece_row
from .models import (
    ActivityLog,
    Category,
    BomLine,
    BomVersion,
    Collection,
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
    ImportBatch,
    StockCount,
    StockMovement,
    Style,
    Vendor,
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

#: The dimensions the filter bar carries: the legacy's four first, then the
#: four the reports screen adds. One filter function serves every screen, so a
#: key added here works on the list, the CSV and the report at once.
FILTER_KEYS = ("category", "location", "state", "price", "collection", "karat", "vendor", "material")


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
    if picked["collection"]:
        pieces = pieces.filter(style__collection__code__in=picked["collection"])
    if picked["karat"]:
        pieces = pieces.filter(metal_purity__in=picked["karat"])
    if picked["vendor"]:
        pieces = pieces.filter(vendor__code__in=picked["vendor"])
    if picked["material"]:
        # the current BOM only: a material that was on version 1 and taken off
        # version 2 is not in the piece any more
        pieces = pieces.filter(
            bom_lines__version_no=F("current_bom_version"),
            bom_lines__material__category__code__in=picked["material"],
        ).distinct()
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


def _safe_next(request):
    """The posted ``next`` if it points at us, else "".

    ``startswith("/")`` is not enough: ``//evil.com`` and its backslash twin both
    start with a slash and both send the browser off-site, and a ``javascript:``
    value is a live script the moment it reaches an ``href``. Templates render
    this, never the raw parameter — a redirect the view refuses is a link the
    page must not offer either.
    """
    target = request.POST.get("next") or request.GET.get("next") or ""
    return (
        target
        if target
        and url_has_allowed_host_and_scheme(
            target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        )
        else ""
    )


def _redirect_back(request, fallback):
    """Honour ``?next=`` when it points at us, and ignore it when it does not."""
    target = _safe_next(request)
    return redirect(target) if target else redirect(fallback)


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
@permission_required("accounts.manage_materials", raise_exception=True)
def material_edit(request, item_code):
    """Change one material. The form already refuses metal without a metal."""
    material = get_object_or_404(Material, item_code=item_code)
    if request.method == "POST":
        form = MaterialForm(request.POST, instance=material)
        if form.is_valid():
            form.save()
            services.log(request.user, "UPDATE", "material", material.item_code, "edited")
            messages.success(request, f"{material.item_code} saved.")
            # reached from the Settings materials tab as well as the register,
            # and landing somewhere the user did not come from is its own bug
            return _redirect_back(request, "stock:material_list")
    else:
        form = MaterialForm(instance=material)
    return render(request, "stock/material_form.html", {
        "nav": "settings",
        "material": material,
        "next": _safe_next(request),
        "form": form,
        "usage": services.material_usage(material),
    })


@login_required
@permission_required("accounts.manage_materials", raise_exception=True)
def material_delete(request, item_code):
    """The checkpoint: what points at this material, and what to do about it.

    A material in use cannot simply go — every relation is PROTECT, because a
    BOM line pointing at nothing is a piece nobody can price. So the screen
    shows the count, and the only ways past it are to move those references to
    another material or to leave it alone.
    """
    material = get_object_or_404(Material, item_code=item_code)
    usage = services.material_usage(material)

    # the screen's own error round-trips have to carry the return path too, or
    # a refused delete quietly forgets where the user came from
    here = reverse("stock:material_delete", kwargs={"item_code": item_code})
    back_to = _safe_next(request)
    if back_to:
        here = f"{here}?{urlencode({'next': back_to})}"

    if request.method == "POST":
        target = None
        wanted = (request.POST.get("reassign_to") or "").strip()
        if wanted:
            target = Material.objects.filter(item_code=wanted).first()
            if target is None:
                messages.error(request, f"No material with the code {wanted!r}.")
                return redirect(here)
        try:
            moved = services.delete_material(request.user, material, reassign_to=target)
        except services.ServiceError as error:
            messages.error(request, str(error))
            return redirect(here)
        if target:
            messages.success(
                request,
                f"{item_code} deleted; {sum(moved.values())} reference(s) moved to {target.item_code}.",
            )
        else:
            messages.success(request, f"{item_code} deleted.")
        return _redirect_back(request, "stock:material_list")

    return render(request, "stock/material_delete.html", {
        "nav": "settings",
        "material": material,
        "next": back_to,
        "usage": usage,
        "uses": [(label, usage[key]) for key, label, _ in services.MATERIAL_USES],
        "candidates": Material.objects.filter(category=material.category)
                                      .exclude(pk=material.pk).order_by("item_code"),
        "all_materials": Material.objects.exclude(pk=material.pk).order_by("item_code"),
    })


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


#: what the summary can be grouped by → its heading and the ``piece_row`` key
#: it reads. A key the role may not see (vendor) drops out of the offer.
REPORT_GROUPS = {
    "location": ("Location", "location"),
    "category": ("Category", "category"),
    "collection": ("Collection", "collection"),
    "karat": ("Karat", "karat"),
    "state": ("Status", "stock_state_display"),
    "vendor": ("Vendor", "vendor_name"),
}

#: a report is read on a screen, not streamed — past this it is an export job
REPORT_LIMIT = 5000


def _report(request):
    """Everything the report screen and its workbook show, built once.

    One builder for both is the only thing that keeps a downloaded file honest
    about the screen it was downloaded from. Every number goes through
    ``piece_row``, so a role without ``view_cost`` has no cost column here,
    on the screen, or in the file.
    """
    pieces, query, picked = _filtered(request)
    if not picked["state"]:
        # the legacy report's "live": a sold or melted piece is not stock. A
        # state chip is an explicit ask for those, so it wins.
        pieces = [piece for piece in pieces if piece.stock_state not in TERMINAL_STATES]
    pieces = list(pieces)[:REPORT_LIMIT]
    rows = [piece_row(request.user, piece) for piece in pieces]
    # "unpriced" is a count, not a value, so it is read off the BOM rather than
    # off the masked row — otherwise a SALES login would see everything as
    # unpriced. One query for the page instead of one per piece.
    costed = {
        piece_id
        for piece_id, cost in BomVersion.objects.filter(
            piece__in=pieces, is_current=True
        ).values_list("piece_id", "total_cost_price")
        if cost
    }

    by = request.GET.get("by") or "location"
    if by not in REPORT_GROUPS or (rows and REPORT_GROUPS[by][1] not in rows[0]):
        by = "location"
    group_label, group_key = REPORT_GROUPS[by]

    columns = [("pieces", "Pieces"), ("gross_wt", "Gross wt (g)"), ("net_wt", "Net metal (g)")]
    if allowed(request.user, "cost_price"):
        columns.append(("cost", "Value at cost (₹)"))
    if allowed(request.user, "sale_price"):
        columns.append(("sale", "Sale value (₹)"))
    columns.append(("unpriced", "Unpriced"))

    groups = {}
    for piece, row in zip(pieces, rows):
        entry = groups.setdefault(row.get(group_key) or "—", dict.fromkeys([key for key, _ in columns], Decimal("0")))
        entry["pieces"] += 1
        entry["gross_wt"] += row.get("measured_gross_wt_gm") or 0
        entry["net_wt"] += row.get("net_metal_wt_gm") or 0
        if "cost" in entry:
            entry["cost"] += row.get("cost_price") or 0
        if "sale" in entry:
            entry["sale"] += row.get("sale_price") or 0
        entry["unpriced"] += 0 if piece.pk in costed else 1
    summary = [
        {"name": name, "cells": [entry[key] for key, _ in columns]}
        for name, entry in sorted(groups.items(), key=lambda item: str(item[0]))
    ]
    totals = [sum((entry[key] for entry in groups.values()), Decimal("0")) for key, _ in columns]

    return {
        "nav": "reports",
        "q": query,
        "picked": picked,
        "filter_qs": _filter_qs(query, picked),
        "by": by,
        "group_label": group_label,
        "group_chips": [
            {"key": key, "label": label, "active": key == by}
            for key, (label, row_key) in REPORT_GROUPS.items()
            if not rows or row_key in rows[0]
        ],
        "columns": [{"key": key, "label": label} for key, label in columns],
        "summary": summary,
        "totals": totals,
        "rows": rows,
        "materials": _material_mix(request.user, pieces),
        "capped": len(pieces) == REPORT_LIMIT,
    }


def _material_mix(user, pieces):
    """What the filtered pieces are made of, by material category.

    A piece is counted once per category it uses, so the piece counts add up to
    more than the stock — the money columns are what tie out.
    """
    if not allowed(user, "material_breakup"):
        return []
    lines = (
        BomLine.objects.filter(piece__in=pieces, version_no=F("piece__current_bom_version"))
        .values("material__category__name")
        .annotate(
            pieces=Count("piece", distinct=True),
            lines=Count("line_id"),
            cost_amount=Sum("cost_amount"),
            sale_amount=Sum("sale_amount"),
        )
        .order_by("material__category__name")
    )
    return [mask(user, {"category": line.pop("material__category__name") or "—", **line}) for line in lines]


@login_required
@tab_required("reports")
def reports(request):
    """Stock sliced every way the filter bar allows, with the unpriced column
    the legacy insisted on.

    Without that column a partly-imported catalogue looks healthy while being
    badly understated.
    """
    context = _report(request)
    page = Paginator(context["rows"], PAGE_SIZE).get_page(request.GET.get("page"))
    picked, query = context["picked"], context["q"]

    def chips(label, options, key, gate=True):
        return {"label": label, "chips": _filter_chips(options, key, picked, query) if gate else []}

    return render(
        request,
        "stock/reports.html",
        context
        | {
            "page": page,
            "rows": list(page),
            "total": len(context["rows"]),
            # the legacy's own order first, then the dimensions this screen adds
            "chip_rows": [
                chips("Category", Category.objects.values_list("code", "name"), "category"),
                chips("Location", Location.objects.filter(is_active=True).values_list("code", "name"), "location"),
                chips("Status", StockState.choices, "state"),
                chips(
                    "Price", [(index, band[0]) for index, band in enumerate(PRICE_BANDS)], "price",
                    allowed(request.user, "sale_price"),
                ),
                chips("Collection", Collection.objects.exclude(code=None).values_list("code", "name"), "collection"),
                chips("Karat", MetalPurity.objects.order_by("sort_order").values_list("karat", "karat"), "karat"),
                chips(
                    "Vendor", Vendor.objects.filter(is_active=True).values_list("code", "name"), "vendor",
                    allowed(request.user, "vendor_name"),
                ),
                chips(
                    "Material", MaterialCategory.objects.order_by("sort_order").values_list("code", "name"), "material",
                    allowed(request.user, "material_breakup"),
                ),
            ],
        },
    )


@login_required
@tab_required("reports")
def reports_export(request):
    """The report as a workbook: summary, material mix, and every piece behind them.

    Excel because that is what a stock take is reconciled in. The rows are the
    same masked rows the screen renders, and the download is logged like any
    other export — what was taken, not just that someone took something.
    """
    report = _report(request)
    book = Workbook()
    sheet = book.active
    sheet.title = "Summary"
    sheet.append([report["group_label"]] + [column["label"] for column in report["columns"]])
    for entry in report["summary"]:
        sheet.append([entry["name"]] + entry["cells"])
    sheet.append(["Total"] + report["totals"])

    if report["materials"]:
        materials = book.create_sheet("Materials")
        headers = list(report["materials"][0].keys())
        materials.append(headers)
        for line in report["materials"]:
            materials.append([line.get(key) for key in headers])

    detail = book.create_sheet("Pieces")
    fields = list(report["rows"][0].keys()) if report["rows"] else ["jewel_code"]
    detail.append(fields)
    for row in report["rows"]:
        detail.append([_cell(row.get(field)) for field in fields])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="stock-report.xlsx"'
    book.save(response)
    services.log(
        request.user, "EXPORT", "jewel_code", "reports_export",
        f"{len(report['rows'])} rows by {report['by']}", row_count=len(report["rows"]),
    )
    return response


def _cell(value):
    """openpyxl writes numbers, dates and strings; anything else goes as text."""
    if isinstance(value, (int, float, Decimal, bool)) or value is None:
        return value
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.replace(tzinfo=None) if isinstance(value, datetime.datetime) else value
    return str(value)


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
            "wipe": services.stock_wipe_preview() if request.user.is_superuser else None,
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


@login_required
@tab_required("data")
@require_POST
def stock_wipe(request):
    """Empty the stock side of the app, on a typed confirmation.

    The rules live in ``services.truncate_stock``; this only takes the answer.
    The phrase has to be typed rather than a checkbox clicked because the whole
    point of the step is to be slow enough to read what is about to go.
    """
    back = reverse("stock:data")
    if (request.POST.get("confirm") or "").strip().upper() != "DELETE STOCK":
        messages.error(request, "Nothing was deleted — type DELETE STOCK to confirm.")
        return redirect(back)
    try:
        result = services.truncate_stock(
            request.user,
            groups=request.POST.getlist("groups"),
            delete_media_files=bool(request.POST.get("delete_media_files")),
        )
    except (services.ServiceError, ValidationError) as error:
        messages.error(request, "; ".join(error.messages) if hasattr(error, "messages") else str(error))
        return redirect(back)

    titles = ", ".join(services.WIPE_GROUP_TITLES[key][0].lower() for key in result["groups"])
    note = f"Wiped {titles} — {result['total']} row(s) removed. The CRM was not touched."
    if result["media_keys"]:
        note += f" {result['media_keys']} image(s) deleted from the bucket."
        if result["media_failed"]:
            note += f" {len(result['media_failed'])} could not be removed and are still there."
    messages.success(request, note)
    return redirect(back)


# ── importing a workbook ─────────────────────────────────────────────────
def _batch_workbook(batch):
    """The stored workbook as a file object, straight from the bucket."""
    from mediahub import storage

    return io.BytesIO(storage.get_bytes(batch.media.storage_key))


def _store_workbook(upload, user):
    """Put the uploaded workbook in the bucket, and row it in the media table.

    Deliberately not ``attach_uploads``: that enforces ``SERVEABLE_TYPES``,
    the allowlist of things safe to hand back from our own origin, and a
    spreadsheet is rightly not on it. Widening that list to admit xlsx would
    weaken an XSS control for every asset the app serves, to solve a problem
    this upload does not have — nothing ever serves this file, the importer
    only reads it back to re-parse it.
    """
    from mediahub import storage

    data = upload.read()
    mime = upload.content_type or storage.guess_mime(upload.name)
    key = storage.build_key("import", "workbook", upload.name)
    storage.put_bytes(key, data, mime)
    return MediaAsset.objects.create(
        media_ref=media_services.next_media_ref(),
        kind=MediaKind.DOCUMENT,
        storage_key=key,
        file_name=upload.name,
        mime_type=mime,
        bytes=len(data),
        file_size_kb=int(len(data) / 1024) or None,
        sha256=storage.sha256_of(data),
        confirmed_at=timezone.now(),
        uploaded_by=user,
        scope="import",
        scope_id="workbook",
    )


#: the review, one set at a time. A set with nothing in it is skipped.
IMPORT_STEPS = [
    ("materials", "Materials", "Every stone, metal and charge the sheet names. "
     "Anything the importer could not place is listed first and must be answered."),
    ("categories", "Categories", "What the sheet calls a thing, against what this catalogue calls it."),
    ("collections", "Collections", "Same again, for collections."),
    ("vendors", "Vendors", "Who made the pieces."),
    ("pieces", "Pieces", "New jewel codes come in. A code already here is left alone "
     "unless you tick it — ticking writes a new BOM version and keeps the old one."),
    ("confirm", "Confirm", "What is about to happen, and where the pieces land."),
]


def _steps_for(plan):
    """The steps worth showing: every set with rows in it, plus Confirm."""
    return [
        (name, title, blurb) for name, title, blurb in IMPORT_STEPS
        if name == "confirm" or plan.sections.get(name)
    ]


def _merge_step(post, decisions, section):
    """Fold one step's answers into the decisions already gathered.

    Each step only ever writes its own section, so moving back and forth
    cannot quietly undo an answer given on another screen.
    """
    for key, choice in (decisions.get(section) or {}).items():
        field = f"{section}:{key}"
        if section == "materials":
            picked = (post.get(f"{field}:category") or "").strip()
            if picked:
                fields = choice.setdefault("fields", {})
                fields["category_id"] = picked
                # the unit is not a free choice: services._check_line_uom
                # refuses metal that is not GM and diamond that is not CT/PCS
                fields["default_uom"] = guess.uom_for_category(picked, fields.get("default_uom"))
        target = (post.get(f"{field}:map_to") or "").strip()
        if target:
            choice["map_to"] = target
            choice["action"] = "map"
            continue
        choice.pop("map_to", None)
        if section == "pieces":
            if choice.get("action") in ("skip", "update"):
                choice["action"] = "update" if post.get(f"update:{key}") else "skip"
        elif field in post:
            choice["action"] = post.get(field)
    return decisions


@login_required
@tab_required("data")
@require_POST
def import_upload(request):
    """Take the workbook, check it is the right one, and open a batch."""
    upload = request.FILES.get("workbook")
    if upload is None:
        messages.error(request, "Choose a workbook first.")
        return redirect("stock:data")

    problems = ivy.header_problems(upload)
    if problems:
        messages.error(request, f"That is not an IVY stock export. {problems[0]}")
        return redirect("stock:data")

    upload.seek(0)
    try:
        asset = _store_workbook(upload, request.user)
    except Exception as error:
        messages.error(request, f"Could not store the file. {error}")
        return redirect("stock:data")

    batch = ImportBatch.objects.create(media=asset, created_by=request.user)
    return redirect("stock:import_review", batch_id=batch.batch_id)


@login_required
@tab_required("data")
def import_review(request, batch_id):
    """Seed the decisions once, then hand over to the first step."""
    batch = get_object_or_404(ImportBatch, pk=batch_id)
    if not batch.decisions:
        plan = analyse_import.analyse(ivy.parse(_batch_workbook(batch)))
        batch.decisions = analyse_import.default_decisions(plan)
        batch.status = ImportBatch.Status.REVIEWING
        batch.save(update_fields=["decisions", "status"])
    return redirect("stock:import_step", batch_id=batch.batch_id, step="materials")


@login_required
@tab_required("data")
def import_step(request, batch_id, step):
    """One set of the review. GET shows it, POST files the answers and moves on."""
    batch = get_object_or_404(ImportBatch, pk=batch_id)
    pieces = ivy.parse(_batch_workbook(batch))
    plan = analyse_import.analyse(pieces)
    if not batch.decisions:
        batch.decisions = analyse_import.default_decisions(plan)

    steps = _steps_for(plan)
    names = [name for name, _, _ in steps]
    if step not in names:
        step = names[0]
    index = names.index(step)

    if request.method == "POST":
        if step != "confirm":
            batch.decisions = _merge_step(request.POST, batch.decisions, step)
        batch.save(update_fields=["decisions"])
        wanted = request.POST.get("go_to")
        if wanted in names:
            return redirect("stock:import_step", batch_id=batch.batch_id, step=wanted)
        step_to = names[max(index - 1, 0)] if request.POST.get("back") else names[min(index + 1, len(names) - 1)]
        return redirect("stock:import_step", batch_id=batch.batch_id, step=step_to)

    outstanding = analyse_import.unresolved(plan, batch.decisions)
    rows = plan.sections.get(step) or []
    # replay what was already answered onto the rows, so a step you come back
    # to shows your answer rather than the importer's first guess
    saved = batch.decisions.get(step) or {}
    for row in rows:
        choice = saved.get(row.key) or {}
        row.action = choice.get("action", row.action)
        row.map_to = choice.get("map_to", "")
        row.category = (choice.get("fields") or {}).get("category_id", "")

    summary = [
        (label, plan.counts[name]) for name, label, _ in steps
        if name != "confirm" and name in plan.counts
    ]
    # a handover file lists the same piece twice; say so rather than let the
    # row count quietly disagree with the spreadsheet
    superseded = sum(p.superseded for p in pieces)
    return render(request, "stock/import_step.html", {
        "nav": "data",
        "batch": batch,
        "plan": plan,
        "steps": steps,
        "step": step,
        "title": steps[index][1],
        "blurb": steps[index][2],
        "index": index,
        "is_first": index == 0,
        "is_last": step == "confirm",
        "prev_step": names[index - 1] if index else None,
        "next_step": names[index + 1] if index + 1 < len(names) else None,
        "rows": rows,
        "decisions": batch.decisions.get(step) or {},
        "counts": plan.counts,
        "outstanding": outstanding,
        "summary": summary,
        "superseded": superseded,
        "materials": Material.objects.order_by("item_code"),
        "material_categories": MaterialCategory.objects.order_by("sort_order"),
        "locations": Location.objects.filter(is_active=True),
    })


@login_required
@tab_required("data")
@require_POST
def import_commit(request, batch_id):
    """Apply what the reviewer decided across the steps, then do the images."""
    batch = get_object_or_404(ImportBatch, pk=batch_id)
    pieces = ivy.parse(_batch_workbook(batch))
    plan = analyse_import.analyse(pieces)
    decisions = batch.decisions or analyse_import.default_decisions(plan)

    still = analyse_import.unresolved(plan, decisions)
    if still:
        messages.error(
            request,
            f"{len(still)} decisions still need answering — they are marked on the Materials step.",
        )
        return redirect("stock:import_step", batch_id=batch.batch_id, step="materials")

    location = Location.objects.filter(pk=request.POST.get("location") or 0).first()
    batch.status = ImportBatch.Status.COMMITTING
    batch.save(update_fields=["status"])
    try:
        result = commit_import.commit(pieces, decisions, request.user, location=location)
    except Exception as error:  # the transaction has already rolled back
        batch.status = ImportBatch.Status.FAILED
        batch.result = {"error": str(error)}
        batch.save(update_fields=["status", "result"])
        messages.error(request, f"Import failed, nothing was written. {error}")
        return redirect("stock:import_step", batch_id=batch.batch_id, step="confirm")

    batch.result = result
    batch.images_total = sum(1 for p in pieces if p.image)
    batch.status = ImportBatch.Status.IMAGES if batch.images_total else ImportBatch.Status.DONE
    batch.finished_at = None if batch.images_total else timezone.now()
    batch.save(update_fields=["result", "images_total", "status", "finished_at"])
    return render(request, "stock/_import_progress.html", {"batch": batch})


@login_required
@tab_required("data")
@require_POST
def import_images(request, batch_id):
    """One chunk of image uploads, then the bar that asks for the next."""
    batch = get_object_or_404(ImportBatch, pk=batch_id)
    if batch.images_done < batch.images_total:
        commit_import.attach_images(batch, ivy.parse(_batch_workbook(batch)), limit=10)
        batch.refresh_from_db()
    if batch.images_done >= batch.images_total and batch.status != ImportBatch.Status.DONE:
        batch.status = ImportBatch.Status.DONE
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "finished_at"])
    return render(request, "stock/_import_progress.html", {"batch": batch})


def _chart_log_entries(user, chart, lines):
    """Every audit row for one rate chart — its lines and the chart itself.

    Read once and handed to both the inline per-row history and the History
    panel, so the two can never disagree about what a rate did. Cost and sale
    are dropped from the diff before it is formatted, not after: a reader
    without ``view_cost`` is shown the sale half of a change and nothing else.
    """
    hidden = {
        field for capability, field in ((VIEW_COST, "cost_rate"), (VIEW_SALE, "sale_rate")) if not user.has_perm(capability)
    }
    by_pk = {str(line.pk): line for line in lines}
    entries = list(
        ActivityLog.objects.filter(
            Q(table_name="rate_chart_line", record_pk__in=list(by_pk)) | Q(table_name="rate_chart", record_pk=str(chart.pk))
        )
        .select_related("user")
        .order_by("-changed_at")
    )
    for entry in entries:
        entry.line = by_pk.get(entry.record_pk) if entry.table_name == "rate_chart_line" else None
        # a chart-level act (a bulk upload) has no before/after row to diff;
        # what it wrote at the time is the honest summary
        entry.shown = (
            entry.detail
            if entry.line is None
            else _rate_diff(
                {k: v for k, v in (entry.old_values or {}).items() if k not in hidden},
                {k: v for k, v in (entry.new_values or {}).items() if k not in hidden},
            )
        )
    return entries


def _chart_rail(charts):
    """The chart cards down the left: what each one holds, and whether it moved.

    ``sides`` is what a reader of the rail actually wants to know — a chart with
    no cost rates anywhere prices a quote but not a margin, and that is worth
    seeing before opening it.
    """
    counts = {
        row["chart"]: row
        for row in RateChartLine.objects.values("chart").annotate(
            materials=Count("material", distinct=True),
            costed=Count("pk", filter=Q(cost_rate__isnull=False)),
            sold=Count("pk", filter=Q(sale_rate__isnull=False)),
        )
    }
    for chart in charts:
        row = counts.get(chart.pk, {})
        chart.materials = row.get("materials", 0)
        chart.sides = (
            "cost + sale" if row.get("costed") and row.get("sold") else "sale only" if row.get("sold") else
            "cost only" if row.get("costed") else "no rates yet"
        )
        # only asked of a locked chart: it is a query per chart, and an open
        # chart's card does not show the number anyway
        chart.live_pieces = services.chart_is_in_use(chart) if chart.is_locked else 0
    return charts


def _metal_courtesy_rows(user, chart, priced, query="", picked=""):
    """Metal materials the chart says nothing about, shown so the group reads whole.

    These are not chart rows — costing derives a metal rate from the *piece's*
    purity — so the cell carries that metal's live per-gram figure and typing
    one turns it into an override for that material alone.
    """
    if picked and picked != "METAL":
        return []
    if not (user.has_perm(VIEW_COST) or user.has_perm(VIEW_SALE)):
        return []
    materials = Material.objects.filter(category="METAL", is_active=True).select_related("metal")
    if query:
        materials = materials.filter(Q(item_code__icontains=query) | Q(item_name__icontains=query))
    return [
        SimpleNamespace(
            pk=None, material=material, size_band="", cost_rate=None, sale_rate=None,
            rate_uom="GM", multiple=None, needs_sale=False, history=[],
            live_rate=material.metal.pure_rate if material.metal else None,
        )
        for material in materials
        if (material.pk, "") not in priced
    ]


def _chart_groups(user, chart, lines, query="", picked=""):
    """The chart's rates, grouped by material category the way the sheet reads.

    The Metal group is the exception. A metal material with no line on the chart
    has no single rate to show: costing derives it from the *piece's* purity, so
    the honest cell is the metal's live per-gram rate and a note that the purity
    factor applies. A line, where one exists, overrides that.
    """
    by_category = {}
    for line in lines:
        line.multiple = (
            services.round_to(line.sale_rate / line.cost_rate, 2) if line.cost_rate and line.sale_rate else None
        )
        line.needs_sale = line.sale_rate is None
        by_category.setdefault(line.material.category_id, []).append(line)

    priced = {(line.material_id, line.size_band) for line in lines}
    for row in _metal_courtesy_rows(user, chart, priced, query, picked):
        by_category.setdefault("METAL", []).append(row)

    order = {category.pk: (category.sort_order, category.name) for category in MaterialCategory.objects.all()}
    return [
        (order.get(code, (99, code))[1], code, sorted(rows, key=lambda r: (r.material.item_code, r.size_band)))
        for code, rows in sorted(by_category.items(), key=lambda kv: order.get(kv[0], (99, kv[0]))[0])
    ]


def _chart_tab(request):
    """Users & Settings -> Rate charts. The rail, the open chart, its history."""
    charts = _chart_rail(list(RateChart.objects.order_by("-is_default", "is_locked", "name", "-version_no")))
    chart_id = request.GET.get("chart")
    chart = next((c for c in charts if str(c.pk) == chart_id), None) or next(iter(charts), None)
    query = (request.GET.get("q") or "").strip()
    picked = request.GET.get("cat") or ""
    rows = (
        RateChartLine.objects.filter(chart=chart).select_related("material", "material__metal") if chart
        else RateChartLine.objects.none()
    )
    # the pills count the chart, not the filtered view, so picking one never
    # changes the other numbers under it — the materials tab reads the same way
    counts = {
        row["material__category"]: row["n"]
        for row in rows.values("material__category").annotate(n=Count("pk"))
    }
    if query:
        rows = rows.filter(Q(material__item_code__icontains=query) | Q(material__item_name__icontains=query))
    if picked:
        rows = rows.filter(material__category=picked)
    lines = list(rows.order_by("material__item_code", "size_band"))
    # the edit history is the audit log, read back — a second history table
    # would be a second thing to keep honest. It is read once and shared:
    # the per-row history and the panel below cannot disagree about a rate.
    entries = _chart_log_entries(request.user, chart, lines) if chart else []
    for line in lines:
        line.history = [entry for entry in entries if entry.line is line]
    if chart:
        # the metal rows are not chart lines, so the pill counts them separately
        # or Metal never appears even though the table is full of it
        priced = set(RateChartLine.objects.filter(chart=chart).values_list("material_id", "size_band"))
        counts["METAL"] = counts.get("METAL", 0) + len(_metal_courtesy_rows(request.user, chart, priced))
    categories = [c for c in MaterialCategory.objects.all() if counts.get(c.pk)]
    for category in categories:
        category.n, category.selected = counts.get(category.pk, 0), category.pk == picked
    return {
        "charts": charts,
        "chart": chart,
        "q": query,
        "cat": picked,
        "line_categories": categories,
        "line_total": sum(counts.values()),
        "groups": _chart_groups(request.user, chart, lines, query, picked) if chart else [],
        "chart_log": Paginator(entries, 30).get_page(request.GET.get("page")),
        "chart_form": RateChartForm(),
        "line_form": RateChartLineForm(initial={"chart": chart}) if chart else None,
        "chart_live_pieces": services.chart_is_in_use(chart) if chart else 0,
    }


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
        # read only: a category is created and renamed in the Django admin, so
        # this tab carries no form and _settings_post refuses a "cats" write
        context["categories"] = Category.objects.annotate(
            designs=Count("styles", distinct=True), pieces=Count("styles__pieces", distinct=True)
        ).order_by("sort_order", "name")
    elif tab == "locs":
        context["locations"] = Location.objects.annotate(
            live=Count("pieces", filter=~Q(pieces__stock_state__in=TERMINAL_STATES), distinct=True)
        ).order_by("code")
        context["form"] = LocationForm()
        if request.GET.get("delete"):
            context |= _location_delete_step(request.GET["delete"])
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
        context |= _chart_tab(request)
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


#: everything that PROTECTs a location. A delete has to name what held it,
#: not just fail — "cannot delete" with no reason is a ticket, not an answer.
LOCATION_REFERENCES = [
    ("live pieces", lambda loc: loc.pieces.exclude(stock_state__in=TERMINAL_STATES).count()),
    ("pieces", lambda loc: loc.pieces.count()),
    ("movements out", lambda loc: loc.movements_out.count()),
    ("movements in", lambda loc: loc.movements_in.count()),
    ("sales", lambda loc: loc.sales.count()),
    ("melts", lambda loc: loc.melts.count()),
    ("stock counts", lambda loc: loc.counts.count()),
    ("material inventory", lambda loc: loc.inventory.count()),
    ("repair returns", lambda loc: RepairJob.objects.filter(return_location=loc).count()),
]


def _location_blockers(location, skip=("live pieces",)):
    """What still points at this location, counted, for a refusal that explains itself."""
    return [(label, count) for label, count in ((l, f(location)) for l, f in LOCATION_REFERENCES if l not in skip) if count]


def _location_live_pieces(location):
    return (
        Piece.objects.filter(location=location)
        .exclude(stock_state__in=TERMINAL_STATES)
        .select_related("style")
        .order_by("jewel_code")
    )


def _location_delete_step(pk):
    """The confirm step behind Delete: what sits here, and where each piece can go."""
    location = get_object_or_404(Location, pk=pk)
    return {
        "delete_location": location,
        "delete_pieces": list(_location_live_pieces(location)),
        "delete_targets": Location.objects.filter(is_active=True).exclude(pk=location.pk).order_by("code"),
        "delete_blockers": _location_blockers(location),
    }


def _location_delete(request):
    """Divert what sits here line by line, then remove the location.

    The two halves are deliberately not one transaction. The diverts are real
    stock movements and stand on their own; the delete is the part history can
    refuse. A location a movement row still points at is *retired* instead —
    PROTECT on every one of those FKs exists so old reports keep resolving, and
    the honest outcome is an empty retired location, not a cascade.
    """
    location = get_object_or_404(Location, pk=request.POST["delete"])
    back = f"{reverse('stock:settings')}?tab=locs"
    pieces = list(_location_live_pieces(location))
    if pieces and not request.user.has_perm(ADJUST_STOCK):
        messages.error(request, f"{location.name} holds {len(pieces)} live piece(s), and moving stock is not yours to do.")
        return redirect(back)

    try:
        with transaction.atomic():
            for piece in pieces:
                target = (request.POST.get(f"to_{piece.pk}") or request.POST.get("to_all") or "").strip()
                if not target:
                    raise services.ServiceError(f"{piece.jewel_code} has nowhere to go — pick a destination for every line.")
                if str(target) == str(location.pk):
                    raise services.ServiceError(f"{piece.jewel_code} cannot be diverted to the location being deleted.")
                services.transfer_piece(request.user, piece, int(target), reference_no=f"Closing {location.code}")
    except (services.ServiceError, ValidationError) as error:
        detail = "; ".join(error.messages) if hasattr(error, "messages") else str(error)
        messages.error(request, f"Nothing was moved — {detail}")
        return redirect(back)

    if pieces:
        services.log(request.user, "UPDATE", "location", str(location.pk), f"{len(pieces)} piece(s) diverted out")

    name, moved = str(location), (f" {len(pieces)} piece(s) moved out first." if pieces else "")
    try:
        with transaction.atomic():
            location.delete()
    except ProtectedError:
        location.is_active = False
        location.save(update_fields=["is_active"])
        held = ", ".join(f"{count} {label}" for label, count in _location_blockers(location))
        services.log(request.user, "UPDATE", "location", str(location.pk), "retired — delete refused by history")
        messages.warning(
            request,
            f"{name} is empty and now retired.{moved} It was not deleted: {held} still point at it, "
            "and history that resolves to nowhere is worse than a retired location.",
        )
    else:
        services.log(request.user, "DELETE", "location", str(location.pk), name)
        messages.success(request, f"{name} deleted.{moved}")
    return redirect(back)


def _settings_post(request, tab):
    """Category, location and material writes. Everything else is read-only here."""
    services.require(request.user, EDIT_BOM, "You cannot change reference data.")
    if tab == "charts":
        if request.FILES.get("csv"):
            return _rate_chart_import(request)
        if request.POST.get("chart_action"):
            return _chart_action(request)
        if request.POST.get("save_rates"):
            return _chart_rates_post(request)
        return _chart_line_post(request)
    if tab == "mats" and request.FILES.get("csv"):
        return _material_import(request)
    if tab == "scen":
        return _scenario_post(request)
    if tab == "locs" and request.POST.get("delete"):
        return _location_delete(request)
    forms = {"locs": (LocationForm, Location), "mats": (MaterialForm, Material)}
    if tab not in forms:
        raise PermissionDenied("That tab has nothing to save.")
    form_class, model = forms[tab]
    # the filter the user was looking at is part of where they were: dropping
    # q and cat on save lands them on a list they did not ask for
    kept = {key: request.GET[key] for key in ("q", "cat") if request.GET.get(key)}
    back = f"{reverse('stock:settings')}?{urlencode({'tab': tab} | kept)}"

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


#: the rate sheet's columns, in order. ``item_code`` + ``size_band`` are the
#: key an upload matches on, so the file that comes out is the file that goes back in.
RATE_CHART_COLUMNS = ["item_code", "size_band", "cost_rate", "sale_rate", "rate_uom"]


def _rate_columns(user):
    """The sheet minus the rates this reader may not see.

    The column is left out rather than blanked: a blank cell means "no rate" and
    would wipe one on the way back in, where an absent column can only be kept.
    """
    hidden = {
        field for capability, field in ((VIEW_COST, "cost_rate"), (VIEW_SALE, "sale_rate")) if not user.has_perm(capability)
    }
    return [column for column in RATE_CHART_COLUMNS if column not in hidden]


@login_required
@tab_required("admin")
def rate_chart_export(request):
    """One chart's rates as CSV, and the template an upload comes back on.

    ``?sample=1`` writes five rows instead of the whole chart — the same columns
    either way, because a template that does not match the export is a template
    nobody can round-trip.
    """
    picked = request.GET.get("chart") or ""
    chart = RateChart.objects.filter(pk=picked).first() if picked.isdigit() else RateChart.objects.first()
    columns = _rate_columns(request.user)
    sample = bool(request.GET.get("sample"))
    lines = (
        RateChartLine.objects.filter(chart=chart).select_related("material").order_by("material__item_code", "size_band")
        if chart
        else RateChartLine.objects.none()
    )
    if sample:
        lines = lines[:5]

    name = "rate-chart-sample" if sample else f"rate-chart-{chart.code}-v{chart.version_no}" if chart else "rate-chart"
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{name}-{timezone.localdate():%Y-%m-%d}.csv"'
    writer = csv.writer(response)
    writer.writerow(columns)
    rows = 0
    for line in lines:
        values = {
            "item_code": line.material.item_code,
            "size_band": line.size_band,
            "cost_rate": line.cost_rate if line.cost_rate is not None else "",
            "sale_rate": line.sale_rate if line.sale_rate is not None else "",
            "rate_uom": line.rate_uom or "",
        }
        writer.writerow([values[column] for column in columns])
        rows += 1
    if sample and not rows:
        # an empty chart still has to hand back something fillable
        filler = {"item_code": "DRKL", "size_band": "1.0mm", "cost_rate": "4500", "sale_rate": "6200", "rate_uom": "CT"}
        writer.writerow([filler[column] for column in columns])
    services.log(request.user, "EXPORT", "rate_chart_line", name, f"{rows} rows", row_count=rows)
    return response


def _rate_chart_import(request):
    """Upsert one chart's rates from a CSV, keyed on ``item_code`` + ``size_band``.

    Every row goes through ``RateChartLineForm``, so an upload cannot write a
    rate the Add rate modal would have refused — including a metal, which prices
    from its live rate and is not a chart's to override. One bad row rolls the
    whole file back: a half-priced chart is the state nobody can describe after.
    """
    chart = get_object_or_404(RateChart, pk=request.POST.get("chart"))
    back = f"{reverse('stock:settings')}?tab=charts&chart={chart.pk}"
    if chart.is_locked:
        messages.error(request, f"{chart} is locked. Fork it to change a rate.")
        return redirect(back)
    try:
        rows = list(csv.DictReader(io.TextIOWrapper(request.FILES["csv"], encoding="utf-8-sig")))
    except (UnicodeDecodeError, csv.Error):
        messages.error(request, "That file is not readable as CSV. Export the sheet again and edit that.")
        return redirect(back)

    columns = _rate_columns(request.user)
    created = updated = 0
    errors = []
    with transaction.atomic():
        for number, row in enumerate(rows, start=2):  # row 1 is the header
            code = (row.get("item_code") or "").strip()
            band = (row.get("size_band") or "").strip()
            if not code:
                errors.append(f"row {number}: no item_code")
                continue
            material = Material.objects.filter(item_code=code).first()
            if material is None:
                errors.append(f"row {number} ({code}): not a material — add it on the Materials tab first")
                continue
            existing = RateChartLine.objects.filter(chart=chart, material=material, size_band=band).first()
            # snapshot first: validating binds the posted values onto the instance
            before = _rate_snapshot(existing) if existing else {}
            data = {"chart": chart.pk, "material": material.pk, "size_band": band}
            for column in ("cost_rate", "sale_rate", "rate_uom"):
                # a column this reader could not export is not theirs to
                # overwrite either: the row keeps what it already said
                data[column] = (row.get(column) or "").strip() if column in columns else (before.get(column) or "")
            form = RateChartLineForm(data, instance=existing)
            if not form.is_valid():
                errors.append(f"row {number} ({code}): " + "; ".join(f"{f}: {e[0]}" for f, e in form.errors.items()))
                continue
            line = form.save()
            after = _rate_snapshot(line)
            services.log(
                request.user,
                "UPDATE" if before else "INSERT",
                "rate_chart_line",
                line.pk,
                detail=_rate_diff(before, after),
                old_values=before or None,
                new_values=after,
            )
            updated += bool(existing)
            created += not existing
        if errors:
            transaction.set_rollback(True)

    if errors:
        messages.error(request, f"Nothing was saved — {len(errors)} row(s) were refused. " + " · ".join(errors[:5]))
    else:
        services.log(
            request.user, "IMPORT", "rate_chart", str(chart.pk), f"CSV upload — {created} new, {updated} updated", row_count=len(rows)
        )
        messages.success(request, f"{created} rate(s) added, {updated} updated.")
    return redirect(back)


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


def _chart_back(chart=None, page=None):
    query = {"tab": "charts"}
    if chart is not None:
        query["chart"] = chart.pk if hasattr(chart, "pk") else chart
    return f"{reverse('stock:settings')}?{urlencode(query)}"


def _chart_action(request):
    """New, rename, duplicate, set default, fork, delete. One rule each, in services."""
    action = request.POST["chart_action"]
    chart = get_object_or_404(RateChart, pk=request.POST["chart"]) if request.POST.get("chart") else None
    try:
        if action == "new":
            form = RateChartForm(request.POST)
            if not form.is_valid():
                messages.error(request, "; ".join(f"{f}: {e[0]}" for f, e in form.errors.items()))
                return redirect(_chart_back(chart))
            chart = services.create_chart(
                request.user,
                form.cleaned_data["name"],
                form.cleaned_data.get("note"),
                copy_from=form.cleaned_data.get("copy_from"),
            )
            messages.success(request, f"{chart.name} created.")
        elif action == "rename":
            services.rename_chart(request.user, chart, request.POST.get("name"), request.POST.get("note"))
            messages.success(request, f"{chart.name} saved.")
        elif action == "duplicate":
            copy = services.create_chart(request.user, request.POST.get("name") or f"{chart.name} copy", chart.note, copy_from=chart)
            messages.success(request, f"{copy.name} created from {chart.name}.")
            chart = copy
        elif action == "default":
            services.set_default_chart(request.user, chart)
            messages.success(request, f"{chart.name} is now the default.")
        elif action == "fork":
            fork = services.fork_chart(request.user, chart)
            messages.success(request, f"{fork.name} v{fork.version_no} created. v{chart.version_no} is locked.")
            chart = fork
        elif action == "delete":
            name = services.delete_chart(request.user, chart)
            messages.success(request, f"{name} deleted.")
            chart = None
        else:
            raise Http404
    except (services.ServiceError, ValidationError) as error:
        messages.error(request, "; ".join(error.messages) if hasattr(error, "messages") else str(error))
    return redirect(_chart_back(chart))


def _chart_rates_post(request):
    """Save the rates typed straight into the table.

    A locked chart is not edited — the edit forks it and lands on the new
    version, which is the whole point of locking: a quote priced in March has
    to still reconcile in September. The user is told which version they are
    now on rather than silently redirected.
    """
    chart = get_object_or_404(RateChart, pk=request.POST["chart"])
    forked = None
    if chart.is_locked:
        try:
            chart, forked = services.fork_chart(request.user, chart), chart
        except (services.ServiceError, ValidationError) as error:
            messages.error(request, "; ".join(error.messages) if hasattr(error, "messages") else str(error))
            return redirect(_chart_back(chart))

    # a rate this reader cannot see is not rendered, so it is never posted —
    # carried over from the row rather than saved as the blank that came back
    hidden = {field for capability, field in ((VIEW_COST, "cost_rate"), (VIEW_SALE, "sale_rate")) if not request.user.has_perm(capability)}
    lines = {str(line.pk): line for line in RateChartLine.objects.filter(chart=chart).select_related("material")}
    saved = 0
    try:
        with transaction.atomic():
            for key in (k for k in request.POST if k.startswith("cost_") or k.startswith("sale_")):
                side, _, ref = key.partition("_")
                field = f"{side}_rate"
                if field in hidden:
                    continue
                value = (request.POST.get(key) or "").strip()
                line = lines.get(ref)
                if line is None:
                    if not value:
                        continue
                    material = get_object_or_404(Material, pk=ref.split(":")[0])
                    line = RateChartLine.objects.filter(chart=chart, material=material, size_band="").first() or RateChartLine(
                        chart=chart, material=material, size_band=""
                    )
                    lines[ref] = line
                before = _rate_snapshot(line) if line.pk else {}
                new = Decimal(value) if value else None
                if getattr(line, field) == new:
                    continue
                setattr(line, field, new)
                line.save()
                services.log(
                    request.user, "UPDATE" if before else "INSERT", "rate_chart_line", line.pk,
                    detail=_rate_diff(before, _rate_snapshot(line)),
                    old_values=before or None, new_values=_rate_snapshot(line),
                )
                saved += 1
    except (InvalidOperation, ValidationError) as error:
        messages.error(request, f"Nothing was saved — {error}")
        return redirect(_chart_back(chart))

    if forked:
        messages.success(request, f"{forked.name} v{forked.version_no} was locked, so this landed on v{chart.version_no}. {saved} rate(s) saved.")
    else:
        messages.success(request, f"{saved} rate(s) saved." if saved else "No rate changed.")
    return redirect(_chart_back(chart))


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
