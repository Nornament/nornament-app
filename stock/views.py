"""Screens ported from ``legacy/Stock/app/nornament.html``.

Port-as-is: what the old screen did, this screen does. The visual refresh is
post-cutover work and doing it here would make every difference a question of
"did we mean to change that?".

HTMX carries the live bits — search, the scan flow, inline rate edits — by
returning the same partials the full page renders.
"""
import csv
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.capabilities import EDIT_BOM, VIEW_COST, VIEW_MARGIN, VIEW_SALE
from mediahub import services as media_services

from . import services
from .enums import COUNTABLE_STATES, MaterialClass, MovementType, StockState, TERMINAL_STATES
from .masking import allowed, piece_row
from .models import (
    BomLine,
    BomVersion,
    JobCard,
    Location,
    Material,
    MaterialCategory,
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
    firsts = [assets[0] for assets in media_services.for_pieces([p.pk for p in page], limit_each=1).values() if assets]
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


@login_required
def piece_detail(request, jewel_code):
    piece = get_object_or_404(_visible_pieces(request), jewel_code__iexact=jewel_code)
    row = piece_row(request.user, piece)
    live_of_design = Piece.objects.filter(style=piece.style, stock_state=StockState.IN_STOCK).count()
    context = {
        "piece": piece,
        "row": row,
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
        messages.success(request, f"{metal.name} is now {metal.pure_rate} per gram.")
    return redirect("stock:rate_list")


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
