"""CRM screens, ported from ``legacy/CRM/nornament-crm.html``.

Same port-as-is rule as the stock side. The two differences from the original
are deliberate and both were the point of the rewrite: purchases are read from
the sale ledger rather than a typed array, and the quote calculator reads live
rates from the database instead of a hardcoded purity table.
"""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from stock.masking import allowed
from stock.models import Sale
from . import quote, services
from .models import ClientMaterial, Customer, Enquiry, Order, Repair, StatusEvent

PAGE_SIZE = 50


@login_required
def dashboard(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    context = {
        "pipeline": services.pipeline_counts(),
        "customers": Customer.objects.count(),
        "fon_members": Customer.objects.filter(is_fon=True).count(),
        "follow_ups": Enquiry.objects.filter(follow_up_date__lte=today)
        .exclude(status__in=["Lost", "Order Confirmed"])
        .select_related("customer")[:10],
        "due_orders": Order.objects.filter(expected_delivery__lte=today)
        .exclude(status__in=["Delivered", "Cancelled"])
        .select_related("customer")[:10],
    }
    if allowed(request.user, "sold_price"):
        context["month_revenue"] = services.revenue_between(month_start, today)
        context["recent_sales"] = Sale.objects.select_related("customer", "piece")[:10]
    return render(request, "crm/dashboard.html", context)


def _customers(request):
    customers = Customer.objects.all()
    query = (request.GET.get("q") or "").strip()
    if query:
        customers = customers.filter(
            Q(name__icontains=query)
            | Q(customer_code__icontains=query)
            | Q(mobile__icontains=query)
            | Q(email__icontains=query)
        )
    if request.GET.get("fon"):
        customers = customers.filter(is_fon=True)
    return customers, query


@login_required
def customer_list(request):
    customers, query = _customers(request)
    page = Paginator(customers, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request, "crm/customer_list.html", {"page": page, "q": query, "total": customers.count()}
    )


@login_required
def customer_rows(request):
    customers, _ = _customers(request)
    page = Paginator(customers, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "crm/_customer_rows.html", {"page": page, "total": customers.count()})


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    sales = Sale.objects.filter(customer=customer).select_related("piece").order_by("-sold_on")
    context = {
        "customer": customer,
        "enquiries": customer.enquirys.all(),
        "orders": customer.orders.all(),
        "repairs": customer.repairs.all(),
        "client_materials": customer.clientmaterials.all(),
        "occasions": customer.occasions.all(),
        "related_people": customer.related_people.all(),
        "gifts": customer.gifts.all(),
        "payout": services.fon_payout(customer),
        "media": customer.__class__.objects.none(),
    }
    if allowed(request.user, "sold_price"):
        context["sales"] = sales
        context["lifetime_value"] = services.customer_lifetime_value(customer)
    return render(request, "crm/customer_detail.html", context)


@login_required
@require_POST
def add_purchase(request, pk):
    """A purchase is a sale. It lands in the one ledger, tagged ``source='CRM'``.

    A CRM-sourced sale carries no cost, so its margin is null and the margin
    report filters it out explicitly rather than reporting a fictional number.
    """
    customer = get_object_or_404(Customer, pk=pk)
    if not request.user.has_perm("accounts.adjust_stock"):
        messages.error(request, "You do not have permission to record a sale.")
        return redirect("crm:customer_detail", pk=pk)
    try:
        sale = Sale.objects.create(
            customer=customer,
            customer_name=customer.name,
            customer_phone=customer.phone,
            sold_on=request.POST.get("date") or timezone.localdate(),
            sold_price=Decimal(request.POST["amount"]),
            product_category=request.POST.get("category", "cat1"),
            invoice_no=request.POST.get("invoice_no") or None,
            description=request.POST.get("description") or None,
            source=Sale.CRM,
            cost_at_sale=None,
        )
    except (KeyError, ValueError) as error:
        messages.error(request, f"Could not record that purchase: {error}")
    else:
        messages.success(request, f"Purchase of {sale.sold_price} recorded.")
    return redirect("crm:customer_detail", pk=pk)


def _pipeline_view(request, model, template, extra=None):
    rows = model.objects.select_related("customer").all()
    status = request.GET.get("status")
    if status:
        rows = rows.filter(status=status)
    query = (request.GET.get("q") or "").strip()
    if query:
        rows = rows.filter(Q(customer__name__icontains=query) | Q(notes__icontains=query))
    context = {"rows": rows[:300], "statuses": model.STATUSES, "selected_status": status or "", "q": query}
    context.update(extra or {})
    return render(request, template, context)


@login_required
def enquiry_list(request):
    return _pipeline_view(request, Enquiry, "crm/enquiry_list.html")


@login_required
def order_list(request):
    orders = Order.objects.exclude(status="Cancelled")
    return _pipeline_view(
        request,
        Order,
        "crm/order_list.html",
        {
            "totals": orders.aggregate(billed=Sum("billing_amount"), advance=Sum("advance_paid"))
            if allowed(request.user, "sold_price")
            else None
        },
    )


@login_required
@require_POST
def order_status(request, pk):
    order = get_object_or_404(Order, pk=pk)
    status = request.POST.get("status")
    if status not in Order.STATUSES:
        messages.error(request, f"{status!r} is not an order status.")
        return redirect("crm:order_list")
    order.status = status
    order.updated_at = timezone.now()
    order.save(update_fields=["status", "updated_at"])
    StatusEvent.objects.create(
        entity_type="order",
        entity_id=order.pk,
        date=timezone.localdate(),
        status=status,
        note=request.POST.get("note", ""),
        by=str(request.user),
    )
    messages.success(request, f"{order.order_code} is now {status}.")
    return redirect("crm:order_list")


@login_required
def repair_list(request):
    return _pipeline_view(request, Repair, "crm/repair_list.html")


@login_required
def client_material_list(request):
    return _pipeline_view(request, ClientMaterial, "crm/client_material_list.html")


@login_required
def fon_register_view(request):
    """The payout run — every member, computed off the sale ledger."""
    payouts = services.fon_register()
    return render(
        request,
        "crm/fon.html",
        {
            "payouts": payouts,
            "total": sum((payout.total_payout for payout in payouts), Decimal("0")),
            "categories": services.CATEGORY_LABELS,
        },
    )


@login_required
def fon_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    return render(
        request,
        "crm/fon_detail.html",
        {
            "customer": customer,
            "payout": services.fon_payout(customer),
            "categories": services.CATEGORY_LABELS,
            "downline": Customer.objects.filter(fon_parent=customer).annotate(children=Count("fon_children")),
        },
    )


@login_required
def reports(request):
    today = timezone.localdate()
    year_start = today.replace(month=4, day=1) if today.month >= 4 else today.replace(year=today.year - 1, month=4, day=1)
    context = {
        "financial_year_start": year_start,
        "pipeline": services.pipeline_counts(),
        "by_status": Order.objects.values("status").annotate(orders=Count("pk")).order_by("status"),
    }
    if allowed(request.user, "sold_price"):
        context["revenue"] = {
            "all": services.revenue_between(year_start, today),
            "stock": services.revenue_between(year_start, today, Sale.STOCK),
            "crm": services.revenue_between(year_start, today, Sale.CRM),
        }
    if allowed(request.user, "margin_amt"):
        context["margin"] = services.margin_between(year_start, today)
    return render(request, "crm/reports.html", context)


@login_required
def calculator(request):
    """The quote calculator, reading live rates rather than a hardcoded table."""
    items = []
    if request.method == "POST":
        karat = request.POST.get("karat") or "18K"
        grams = Decimal(request.POST.get("grams") or "0")
        making_rate = Decimal(request.POST.get("making_rate") or "0")
        item = quote.QuoteItem(
            name=request.POST.get("name") or "Item",
            code=request.POST.get("code", ""),
            making_rate=making_rate,
            components=[quote.metal_component(f"Metal ({karat})", karat, grams)],
        )
        for index in range(1, 6):
            carats = request.POST.get(f"stone_ct_{index}")
            material = request.POST.get(f"stone_material_{index}")
            if carats and material:
                item.components.append(
                    quote.stone_component(material, material, Decimal(carats), request.POST.get(f"stone_band_{index}", ""))
                )
        if request.POST.get("target_total"):
            quote.distribute_to_total(item, request.POST["target_total"])
        items.append(item)
    return render(
        request,
        "crm/calculator.html",
        {"items": items, "purities": quote.purity_rates(), "total": quote.quote_total(items)},
    )
