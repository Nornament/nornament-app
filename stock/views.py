"""Screens ported from ``legacy/Stock/app/nornament.html``.

Port-as-is: what the old screen did, this screen does. The visual refresh is
post-cutover work and doing it here would make every difference a question of
"did we mean to change that?".

HTMX carries the live bits — search, the scan flow, inline rate edits — by
returning the same partials the full page renders.
"""
import csv
from decimal import Decimal
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.capabilities import EDIT_BOM, ROLE_GROUPS, ROLE_TABS, VIEW_COST, VIEW_MARGIN, VIEW_SALE
from accounts.context_processors import _role_code
from mediahub import services as media_services
from mediahub.models import MediaAsset

from . import services
from .enums import BomChangeReason, COUNTABLE_STATES, MaterialClass, MovementType, StockState, TERMINAL_STATES, Uom
from .forms import (
    BomLineFormSet,
    CategoryForm,
    LocationForm,
    MaterialForm,
    MeltForm,
    MoveForm,
    PieceForm,
    RepairForm,
    SaleForm,
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


def _filtered(request):
    """The list filter, shared by the page, the HTMX rows and the export.

    ``state`` and ``location`` repeat (``?state=IN_STOCK&state=RESERVED``) —
    the legacy multi-select chips. A single value still works: ``getlist``
    reads both shapes.
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
    states = [value for value in request.GET.getlist("state") if value]
    if states:
        pieces = pieces.filter(stock_state__in=states)
    locations = [value for value in request.GET.getlist("location") if value]
    if locations:
        pieces = pieces.filter(location__code__in=locations)
    if request.GET.get("unpriced"):
        pieces = pieces.exclude(bom_versions__is_current=True, bom_versions__total_cost_price__gt=0)
    return pieces, query, states, locations


def _filter_qs(query, states, locations):
    params = ([("q", query)] if query else []) + [("state", s) for s in states] + [("location", c) for c in locations]
    return urlencode(params)


def _filter_chips(options, selected, other_qs_parts):
    """One legacy ``.fchip`` per option: its toggled-URL querystring, precomputed."""
    chips = []
    for value, label in options:
        toggled = [v for v in selected if v != value] if value in selected else selected + [value]
        chips.append({"label": label, "active": value in selected, "qs": other_qs_parts(toggled)})
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
    pieces, query, states, locations = _filtered(request)
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
            "state_chips": _filter_chips(
                StockState.choices, states, lambda toggled: _filter_qs(query, toggled, locations)
            ),
            "location_chips": _filter_chips(
                [(l.code, l.name) for l in Location.objects.filter(is_active=True)],
                locations,
                lambda toggled: _filter_qs(query, states, toggled),
            ),
            "selected_states": states,
            "selected_locations": locations,
            "filter_qs": _filter_qs(query, states, locations),
            "total": pieces.count(),
        },
    )


@login_required
def piece_rows(request):
    """The HTMX half of the list: the same rows, no chrome."""
    pieces, _, _, _ = _filtered(request)
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
    return render(request, "stock/piece_detail.html", context)


@login_required
@permission_required("accounts.manage_materials", raise_exception=True)
def piece_bom(request, jewel_code):
    """The material breakup. Gated whole — this is the ``materials`` capability."""
    piece = get_object_or_404(_visible_pieces(request), jewel_code__iexact=jewel_code)
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
    sale_total = (version.total_sale_price if version else None) or None

    groups, breakup = [], []
    for line in lines:
        is_metal = line.material.mat_class == MaterialClass.METAL
        share = (Decimal(100) * (line.sale_amount or 0) / sale_total) if sale_total else None
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
            "sale_rate": line.sale_rate,
            "sale_amount": line.sale_amount,
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
            amount = line.sale_amount if money == "sale" else line.cost_amount
            by_label[line.material.category.name]["amount"] += amount or 0
    context = {
        "piece": piece,
        "row": piece_row(request.user, piece),
        "version": version,
        "groups": groups,
        "grp_span": 5 + (5 if show_cost else 0) + (3 if show_sale else 0),
        "breakup": breakup if money else None,
        "money": money,
        "breakup_total": (version.total_sale_price if money == "sale" else version.total_cost_price)
        if version and money
        else None,
        "cost_today_total": services.current_cost(piece) if show_cost else None,
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
    return render(request, "stock/piece_bom.html", context)


@login_required
def piece_scenarios(request, jewel_code):
    """``api.piece_scenarios`` — what each scenario would ask for this piece."""
    piece = get_object_or_404(_visible_pieces(request), jewel_code__iexact=jewel_code)
    if not (request.user.has_perm(VIEW_SALE) or request.user.has_perm(VIEW_COST)):
        raise PermissionDenied("You cannot see pricing.")
    show_cost = allowed(request.user, "cost_price")
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
        row = price.__dict__.copy()
        if show_cost:
            # margin against cost today, never the frozen figure (legacy pricing tab)
            row["margin"] = price.price - price.cost_today
        prices.append(row)
    return render(
        request,
        "stock/piece_scenarios.html",
        {"piece": piece, "prices": prices, "show_cost": show_cost},
    )


@login_required
@require_POST
def sell_piece_view(request, jewel_code):
    piece = get_object_or_404(_visible_pieces(request), jewel_code__iexact=jewel_code)
    try:
        sale = services.sell_piece(
            request.user,
            piece,
            sold_price=request.POST["sold_price"],
            discount_amt=request.POST.get("discount_amt") or 0,
            customer_name=request.POST.get("customer_name"),
            customer_phone=request.POST.get("customer_phone"),
        )
    except (ValidationError, PermissionDenied) as error:
        messages.error(request, _message(error))
    else:
        messages.success(request, f"{piece.jewel_code} sold for {sale.sold_price}.")
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
    pieces, _, _, _ = _filtered(request)
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
        materials = Material.objects.select_related("category", "metal").annotate(
            used_on_lines=Count("bom_lines")
        )
        query = (request.GET.get("q") or "").strip()
        if query:
            materials = materials.filter(Q(item_code__icontains=query) | Q(item_name__icontains=query))
        context |= {
            "materials": materials.order_by("category__sort_order", "item_code")[:400],
            "material_categories": MaterialCategory.objects.all(),
            "q": query,
            "form": MaterialForm(),
        }
    elif tab == "charts":
        chart_id = request.GET.get("chart")
        charts = list(RateChart.objects.order_by("-is_default", "code", "-version_no"))
        chart = next((c for c in charts if str(c.pk) == chart_id), None) or next(iter(charts), None)
        context |= {
            "charts": charts,
            "chart": chart,
            "lines": RateChartLine.objects.filter(chart=chart).select_related("material").order_by(
                "material__item_code", "size_band"
            )
            if chart
            else [],
            "chart_in_use": chart.lines.filter(material__bom_lines__isnull=False).exists() if chart else False,
        }
    elif tab == "scen":
        context["scenarios"] = Scenario.objects.prefetch_related("roles__group").order_by("code")
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


def _settings_post(request, tab):
    """Category, location and material writes. Everything else is read-only here."""
    services.require(request.user, EDIT_BOM, "You cannot change reference data.")
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
            lines = [
                {
                    "material": entry["material"],
                    "size_band": entry.get("size_band") or "",
                    "qty_value": entry["qty_value"],
                    "qty_uom": entry["qty_uom"],
                }
                for entry in formset.cleaned_data
                if entry and not entry.get("DELETE")
            ]
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
