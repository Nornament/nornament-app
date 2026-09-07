"""CRM screens, ported from ``legacy/CRM/nornament-crm.html``.

Screen for screen and action for action with the old React app: the same
dashboard, the same customer profile and its twelve tabs, the same four
pipeline modules with a list view, a kanban and a detail screen, the same FoN
tree, reports, quote calculator and settings.

Two differences from the original are deliberate and both were the point of the
rewrite: purchases are read from and written to the sale ledger rather than a
typed array, and the quote calculator reads live rates from the database
instead of a hardcoded purity table.
"""
import csv
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.contrib.staticfiles import finders
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from mediahub import services as media_services
from mediahub.models import MediaAsset
from stock.masking import allowed
from stock.models import Sale
from . import forms as crm_forms, imports, quote, services
from .models import (
    ClientMaterial,
    Customer,
    Enquiry,
    Gift,
    Location,
    Occasion,
    Order,
    OutreachEntry,
    RelatedPerson,
    Repair,
    Salesperson,
    StatusEvent,
)

PAGE_SIZE = 50

#: what the board calls the column for statuses it does not recognise. A record
#: with one is not lost, it is just not on a stage — and it has to be visible
#: for anybody to fix it.
UNMAPPED_COLUMN = "⚠ Unmapped stage"

#: everything the four pipeline modules differ by, in one place. The legacy app
#: had four near-identical modules; this is that duplication collapsed.
PIPELINES = {
    "enquiry": {
        "model": Enquiry,
        "form": crm_forms.EnquiryForm,
        "code": "enquiry_code",
        "media_scope": "enquiry",
        "title": "Enquiries",
        "singular": "Enquiry",
        "list_url": "crm:enquiry_list",
        "detail_url": "crm:enquiry_detail",
        "icon": "🔍",
        "stages": [
            ("New Enquiry", "💬"),
            ("Pics Shared", "📸"),
            ("Quote Sent", "📝"),
            ("Design Brief", "✏️"),
            ("Design Approved", "✅"),
            ("Order Confirmed", "🎯"),
        ],
        "terminal": ["Lost"],
    },
    "order": {
        "model": Order,
        "form": crm_forms.OrderForm,
        "code": "order_code",
        "media_scope": "order",
        "title": "Orders",
        "singular": "Order",
        "list_url": "crm:order_list",
        "detail_url": "crm:order_detail",
        "icon": "📦",
        "stages": [
            ("Order Confirmed", "🎯"),
            ("Materials Ordered", "📥"),
            ("Designing", "✏️"),
            ("Stone Setting", "💠"),
            ("Polishing", "✨"),
            ("Quality Check", "🔎"),
            ("Billing", "🧾"),
            ("Ready", "✅"),
            ("Delivered", "🚚"),
        ],
        "terminal": ["Cancelled"],
    },
    "repair": {
        "model": Repair,
        "form": crm_forms.RepairForm,
        "code": "repair_code",
        "media_scope": "repair",
        "title": "Repairs",
        "singular": "Repair",
        "list_url": "crm:repair_list",
        "detail_url": "crm:repair_detail",
        "icon": "🔧",
        "stages": [
            ("Received", "📥"),
            ("Diagnosed", "🔎"),
            ("In Workshop", "🔧"),
            ("Ready", "✅"),
            ("Customer Approved", "👍"),
            ("Delivered", "🚚"),
        ],
        "terminal": [],
    },
    "clientmaterial": {
        "model": ClientMaterial,
        "form": crm_forms.ClientMaterialForm,
        "code": "cm_code",
        "media_scope": "client_material",
        "title": "Client Materials",
        "singular": "Client Material",
        "list_url": "crm:client_material_list",
        "detail_url": "crm:client_material_detail",
        "icon": "📋",
        "stages": [
            ("Received", "📥"),
            ("Design Pending", "✏️"),
            ("Design Approved", "✅"),
            ("Moved to Order", "📦"),
        ],
        "terminal": ["Moved to Repair", "Returned"],
    },
}


# ── shared helpers ───────────────────────────────────────────────────────
def _attach_posted_files(request, scope, entity_id, field="photos"):
    """The legacy forms photographed a record while creating it; this does too.

    The JS uploader needs an entity that already exists, so a brand-new enquiry
    could not carry a photo. A multipart form can: the row is saved, then its
    files go to the bucket in the same request.
    """
    files = request.FILES.getlist(field)
    if not files:
        return
    saved, refused = media_services.attach_uploads(files, scope, entity_id, request.user)
    if saved:
        messages.success(request, f"{len(saved)} file{'s' if len(saved) != 1 else ''} attached.")
    for name in refused:
        messages.error(request, f"Could not attach {name}.")


def _crm_media(scope, ids):
    """Confirmed, live media for CRM rows -> {scope_id: [(asset, url|None), ...]}.

    ``urls_for`` already swallows StorageNotConfigured, so a box with no media
    credentials renders the screen with placeholder tiles rather than a 500.
    """
    assets = list(
        MediaAsset.objects.filter(
            scope=scope, scope_id__in=[str(pk) for pk in ids], is_archived=False, confirmed_at__isnull=False
        )
    )
    urls = media_services.urls_for(assets)
    grouped = defaultdict(list)
    for asset in assets:
        grouped[asset.scope_id].append((asset, urls[asset.pk]))
    return grouped


def _thumbs(scope, rows):
    """First photo per row, for the 36px column the legacy tables carried."""
    media = _crm_media(scope, [row.pk for row in rows])
    return {int(scope_id): items[0][1] for scope_id, items in media.items() if items}


def _sale_thumbs(sales):
    """A purchase shows its own photo, or the one from the order it was billed from.

    The legacy CRM had nothing to photograph a purchase against — a purchase
    was an entry in the customer's ``purchases[]`` array, not an entity — so
    every migrated purchase has no media of its own and asking for ``sale``
    scope alone returns nothing at all. The photos of the piece are on the
    order that produced it, which ``crm_order`` now names.
    """
    thumbs = _thumbs("sale", sales)
    pending = {sale.crm_order_id: sale.pk for sale in sales if sale.pk not in thumbs and sale.crm_order_id}
    if not pending:
        return thumbs
    media = _crm_media("order", list(pending))
    for order_id, sale_pk in pending.items():
        items = media.get(str(order_id))
        if items:
            thumbs[sale_pk] = items[0][1]
    return thumbs


def _status_counts(model):
    counts = dict(model.objects.values_list("status").annotate(n=Count("pk")))
    return [(status, counts.get(status, 0)) for status in model.STATUSES]


def _next_occurrence(when, today):
    """The next birthday/anniversary for a stored date, 29 Feb folding to 28."""
    for year in (today.year, today.year + 1):
        try:
            candidate = when.replace(year=year)
        except ValueError:
            candidate = when.replace(year=year, day=28)
        if candidate >= today:
            return candidate
    return when


def _financial_year_bounds(start_year):
    """1 April to 31 March — the year the reports screen already works in."""
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def _financial_years(sales):
    """Every FY this customer bought in, newest first, as (value, label)."""
    years = set()
    for sold_on in sales.values_list("sold_on", flat=True):
        if sold_on:
            years.add(sold_on.year if sold_on.month >= 4 else sold_on.year - 1)
    return [(year, f"FY {year}-{str(year + 1)[2:]}") for year in sorted(years, reverse=True)]


def _reminders(today, horizon=30):
    """Birthdays, anniversaries, engagements, weddings and logged occasions.

    The legacy dashboard used a different horizon per kind — 30 days for
    birthdays and anniversaries, 60 for engagements, 90 for weddings — and this
    keeps that.
    """
    reminders = []
    kinds = (
        ("birthday", "birth_date", 30, "🎂", "al-b"),
        ("anniversary", "anniversary_date", 30, "💍", "al-a"),
        ("engagement", "engagement_date", 60, "💎", "al-e"),
        ("wedding", "wedding_date", 90, "👰", "al-e"),
    )
    rows = Customer.objects.filter(
        Q(birth_date__isnull=False)
        | Q(anniversary_date__isnull=False)
        | Q(engagement_date__isnull=False)
        | Q(wedding_date__isnull=False)
    ).values("pk", "name", "customer_code", "mobile", "birth_date", "anniversary_date", "engagement_date", "wedding_date")
    for row in rows:
        for kind, key, window, icon, css in kinds:
            if not row[key]:
                continue
            days = (_next_occurrence(row[key], today) - today).days
            if days <= window:
                reminders.append(
                    {
                        "kind": kind,
                        "days": days,
                        "pk": row["pk"],
                        "name": row["name"],
                        "code": row["customer_code"],
                        "mobile": row["mobile"],
                        "icon": icon,
                        "css": css,
                    }
                )
    for occasion in Occasion.objects.filter(date__isnull=False).select_related("customer"):
        days = (_next_occurrence(occasion.date, today) - today).days
        if days <= horizon:
            reminders.append(
                {
                    "kind": occasion.occasion_type or "occasion",
                    "days": days,
                    "pk": occasion.customer_id,
                    "name": occasion.customer.name,
                    "code": occasion.customer.customer_code,
                    "mobile": occasion.customer.mobile,
                    "icon": "🗓",
                    "css": "al-w",
                }
            )
    return sorted(reminders, key=lambda reminder: reminder["days"])


def _pipeline(kind):
    spec = PIPELINES.get(kind)
    if spec is None:
        raise Http404(f"no pipeline named {kind!r}")
    return spec


def _redirect_back(request, fallback):
    """Honour ``?next=`` so a status move from a list returns to that list.

    Only when it points at us. ``startswith("/")`` is not enough: ``//evil.com``
    and ``/\\evil.com`` both start with a slash and both send the browser
    off-site.
    """
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(target)
    return redirect(fallback)


# ── dashboard ────────────────────────────────────────────────────────────
@login_required
def dashboard(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    open_enquiries = list(
        Enquiry.objects.exclude(status__in=["Order Confirmed", "Lost"]).select_related("customer")[:6]
    )
    open_orders = list(Order.objects.exclude(status__in=["Delivered", "Cancelled"]).select_related("customer")[:6])
    open_materials = list(
        ClientMaterial.objects.exclude(status__in=["Moved to Order", "Moved to Repair", "Returned"]).select_related(
            "customer"
        )[:6]
    )
    open_repairs = list(Repair.objects.exclude(status="Delivered").select_related("customer")[:6])

    context = {
        "nav": "dashboard",
        "pipeline": services.pipeline_counts(),
        "customers": Customer.objects.count(),
        "fon_members": Customer.objects.filter(is_fon=True).count(),
        "temps": Customer.objects.aggregate(
            hot=Count("pk", filter=Q(temperature="Hot")),
            warm=Count("pk", filter=Q(temperature="Warm")),
            cold=Count("pk", filter=Q(temperature="Cold")),
            vip=Count("pk", filter=Q(customer_type=Customer.VIP)),
        ),
        "boards": [
            ("Enquiries", "enquiry", "crm:enquiry_list", _status_counts(Enquiry)),
            ("Orders", "order", "crm:order_list", _status_counts(Order)),
            ("Repairs", "repair", "crm:repair_list", _status_counts(Repair)),
            ("Client materials", "clientmaterial", "crm:client_material_list", _status_counts(ClientMaterial)),
        ],
        "gaps": services.lead_gaps(),
        "temp_spread": services.temperature_spread(),
        "reminders": _reminders(today)[:10],
        "cards": [
            (
                "🔍 Active Enquiries",
                PIPELINES["enquiry"],
                "crm:enquiry_list",
                open_enquiries,
                _thumbs("enquiry", open_enquiries),
            ),
            ("📦 Active Orders", PIPELINES["order"], "crm:order_list", open_orders, _thumbs("order", open_orders)),
            (
                "📋 Client Materials",
                PIPELINES["clientmaterial"],
                "crm:client_material_list",
                open_materials,
                _thumbs("client_material", open_materials),
            ),
            (
                "🔧 Active Repairs",
                PIPELINES["repair"],
                "crm:repair_list",
                open_repairs,
                _thumbs("repair", open_repairs),
            ),
        ],
        "follow_ups": Enquiry.objects.filter(follow_up_date__lte=today)
        .exclude(status__in=["Lost", "Order Confirmed"])
        .select_related("customer")[:10],
        "due_orders": Order.objects.filter(expected_delivery__lte=today)
        .exclude(status__in=["Delivered", "Cancelled"])
        .select_related("customer")[:10],
    }
    if allowed(request.user, "sold_price"):
        context["month_revenue"] = services.revenue_between(month_start, today)
        context["year_revenue"] = services.revenue_between(date(today.year, 1, 1), today)
        context["customer_value"] = Sale.objects.aggregate(total=Sum("sold_price"))["total"] or Decimal("0")
        context["recent_sales"] = Sale.objects.select_related("customer", "piece")[:10]
    return render(request, "crm/dashboard.html", context)


# ── customers ────────────────────────────────────────────────────────────
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
    if request.GET.get("temp"):
        customers = customers.filter(temperature=request.GET["temp"])
    if request.GET.get("type"):
        customers = customers.filter(customer_type=request.GET["type"])
    if request.GET.get("loc"):
        customers = customers.filter(location=request.GET["loc"])
    return customers, query


def _customer_page(request):
    """Shared by the full screen and the HTMX fragment: same filters, same shape."""
    customers, query = _customers(request)
    total = customers.count()
    if allowed(request.user, "sold_price"):
        # explicit order_by: a GROUP BY query no longer applies Meta.ordering
        customers = customers.annotate(value=Sum("sales__sold_price")).order_by("name")
    page = Paginator(customers, PAGE_SIZE).get_page(request.GET.get("page"))
    return {"page": page, "q": query, "total": total, "grand_total": Customer.objects.count()}


@login_required
def customer_list(request):
    context = _customer_page(request)
    context |= {
        "nav": "customers",
        "temp": request.GET.get("temp") or "",
        "ctype": request.GET.get("type") or "",
        "loc": request.GET.get("loc") or "",
        "temperatures": [name for name, _ in Customer.TEMPERATURES],
        "types": [Customer.VIP, Customer.REGULAR, Customer.WHOLESALE],
        "locations": Customer.objects.exclude(location="")
        .values_list("location", flat=True)
        .distinct()
        .order_by("location"),
    }
    return render(request, "crm/customer_list.html", context)


@login_required
def customer_rows(request):
    return render(request, "crm/_customer_rows.html", _customer_page(request))


#: the twelve tabs of the legacy customer profile, in order
PROFILE_TABS = [
    "Overview",
    "Timeline",
    "Purchases",
    "Outreach",
    "Orders",
    "Enquiries",
    "Client Mat.",
    "Repairs",
    "Gifting",
    "Occasions",
    "FoN",
    "Docs",
]


def _timeline(customer):
    """``ActivityTimeline`` — every dated thing about a customer, newest first."""
    from .templatetags.crm_extras import inr

    events = []
    for sale in Sale.objects.filter(customer=customer).select_related("piece"):
        events.append(
            {
                "date": sale.sold_on,
                "kind": "purchase",
                "title": f"Purchase — {inr(sale.sold_price)}",
                "sub": sale.description or (sale.piece.jewel_code if sale.piece_id else ""),
            }
        )
    for entry in customer.outreach_log.all():
        title = entry.get_type_display()
        if entry.outcome:
            title = f"{title} — {entry.outcome}"
        events.append({"date": entry.date, "kind": "outreach", "title": title, "sub": entry.notes})

    for kind, noun, rows, code_field, label_field in (
        ("enquiry", "Enquiry", customer.enquirys.all(), "enquiry_code", "item_of_interest"),
        ("order", "Order", customer.orders.all(), "order_code", "item_description"),
        ("repair", "Repair", customer.repairs.all(), "repair_code", "item_description"),
        ("clientmaterial", "Client material", customer.clientmaterials.all(), "cm_code", "jewellery_description"),
    ):
        rows = list(rows)
        log = defaultdict(list)
        for event in StatusEvent.objects.filter(entity_type=kind, entity_id__in=[r.pk for r in rows]).order_by(
            "date", "id"
        ):
            log[event.entity_id].append(event)
        for row in rows:
            code = getattr(row, code_field)
            started = getattr(row, "enquiry_date", None) or getattr(row, "order_date", None)
            started = started or getattr(row, "received_date", None) or row.created_at.date()
            label = getattr(row, label_field, "") or ""
            events.append(
                {
                    "date": started,
                    "kind": kind,
                    "title": f"{noun} {code}" + (f" — {label}" if label else ""),
                    "sub": "",
                }
            )
            for event in log[row.pk][1:]:
                events.append(
                    {"date": event.date, "kind": kind, "title": f"{code} → {event.status}", "sub": event.note}
                )
    return sorted((e for e in events if e["date"]), key=lambda e: e["date"], reverse=True)[:100]


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    tab = request.GET.get("tab") or "Overview"
    if tab not in PROFILE_TABS:
        tab = "Overview"
    suggested, why = services.computed_temp(customer)
    context = {
        "nav": "customers",
        "customer": customer,
        "tab": tab,
        "profile_tabs": PROFILE_TABS,
        "enquiries": customer.enquirys.all(),
        "orders": customer.orders.all(),
        "repairs": customer.repairs.all(),
        "client_materials": customer.clientmaterials.all(),
        "occasions": customer.occasions.all(),
        "related_people": customer.related_people.all(),
        "gifts": customer.gifts.all(),
        "outreach": customer.outreach_log.all(),
        "referrals": customer.referred_customers.all(),
        "payout": services.fon_payout(customer),
        "categories": services.CATEGORY_LABELS,
        "media": _crm_media("customer", [customer.pk]).get(str(customer.pk), []),
        "suggested_temp": None if suggested == customer.temperature else suggested,
        "suggested_why": why,
        "purchase_form": crm_forms.PurchaseForm(),
        "gift_form": crm_forms.GiftForm(),
        "occasion_form": crm_forms.OccasionForm(),
        "person_form": crm_forms.RelatedPersonForm(),
        "outreach_form": crm_forms.OutreachForm(),
    }
    if tab == "Timeline":
        context["timeline"] = _timeline(customer)
    if allowed(request.user, "sold_price"):
        sales = Sale.objects.filter(customer=customer).select_related("piece").order_by("-sold_on")
        context["financial_years"] = _financial_years(sales)
        chosen = request.GET.get("fy") or ""
        if chosen.isdigit():
            start, end = _financial_year_bounds(int(chosen))
            sales = sales.filter(sold_on__gte=start, sold_on__lte=end)
        context["fy"] = chosen
        context["sales"] = sales
        context["sale_thumbs"] = _sale_thumbs(sales)
        context["shown_value"] = sales.aggregate(total=Sum("sold_price"))["total"] or Decimal("0")
        context["shown_count"] = sales.count()
        context["lifetime_value"] = services.customer_lifetime_value(customer)
        context["year_value"] = Sale.objects.filter(
            customer=customer, sold_on__year=timezone.localdate().year
        ).aggregate(total=Sum("sold_price"))["total"] or Decimal("0")
        context["purchase_count"] = Sale.objects.filter(customer=customer).count()
    return render(request, "crm/customer_detail.html", context)


def _save_inline_people(request, customer):
    """The legacy form's Relationships tab, which edited ``relatedPeople[]``
    inside the create modal rather than making you save first."""
    names = request.POST.getlist("person_name")
    relations = request.POST.getlist("person_relation")
    phones = request.POST.getlist("person_phone")
    for index, name in enumerate(names):
        name = (name or "").strip()
        if not name:
            continue
        RelatedPerson.objects.create(
            customer=customer,
            name=name,
            relation=(relations[index] if index < len(relations) else "").strip(),
            phone=(phones[index] if index < len(phones) else "").strip(),
        )


@login_required
def customer_form(request, pk=None):
    customer = get_object_or_404(Customer, pk=pk) if pk else None
    if request.method == "POST":
        form = crm_forms.CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            saved = form.save(commit=False)
            saved.updated_at = timezone.now()
            saved.save()
            form.save_m2m()
            _attach_posted_files(request, "customer", saved.pk)
            _save_inline_people(request, saved)
            messages.success(request, f"{saved.name} saved.")
            return redirect("crm:customer_detail", pk=saved.pk)
    else:
        initial = {} if customer else {"customer_code": services.next_code(Customer, "customer")}
        form = crm_forms.CustomerForm(instance=customer, initial=initial)
    return render(
        request,
        "crm/customer_form.html",
        {
            "nav": "customers",
            "form": form,
            "customer": customer,
            "customer_media": _crm_media("customer", [customer.pk]).get(str(customer.pk), []) if customer else [],
        },
    )


@login_required
@require_POST
def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    name = customer.name
    customer.delete()
    messages.success(request, f"{name} deleted.")
    return redirect("crm:customer_list")


@login_required
@require_POST
def customer_apply_temperature(request, pk):
    """The legacy ``SuggestTemp`` chip: the engine proposes, a human applies."""
    customer = get_object_or_404(Customer, pk=pk)
    suggested, why = services.computed_temp(customer)
    customer.temperature = suggested
    customer.updated_at = timezone.now()
    customer.save(update_fields=["temperature", "updated_at"])
    messages.success(request, f"{customer.name} is now {suggested} — {why}.")
    return redirect("crm:customer_detail", pk=pk)


@login_required
def customer_export(request):
    """``doMasterExport`` — every customer, every column the legacy sheet had.

    CSV rather than the legacy XLSX: the columns are what the sheet is for, and
    a CSV needs no dependency to write and opens in Excel the same way.

    Money columns only for a login allowed to see sale prices; the masking rule
    does not stop at the screen.
    """
    show_money = allowed(request.user, "sold_price")
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="nornament-customers-{timezone.localdate():%Y-%m-%d}.csv"'
    )
    writer = csv.writer(response)
    header = [
        "Customer Code", "Name", "Mobile", "Landline", "Email", "Address", "Location",
        "Birthday", "Anniversary", "Engagement Date", "Wedding Date",
        "Customer Type", "Temperature", "Tier",
        "Metal Preference", "Salesperson", "Payment Preference",
        "Reference Type", "Referrer Code",
        "Is FoN", "FoN Level",
        "Total Orders", "Total Repairs", "Total Enquiries",
        "Personal Observation", "Client Info", "Created", "Last Updated",
    ]
    if show_money:
        header += ["Credit Limit", "Outstanding Balance", "Total Purchases (INR)"]
    writer.writerow(header)

    rows = (
        Customer.objects.select_related("referrer")
        .annotate(
            n_orders=Count("orders", distinct=True),
            n_repairs=Count("repairs", distinct=True),
            n_enquiries=Count("enquirys", distinct=True),
        )
        .order_by("name")
    )
    if show_money:
        rows = rows.annotate(value=Sum("sales__sold_price"))
    for customer in rows:
        # the legacy carried these two on the blob and this model has no column
        # for them; the ETL parked them in `extra`, so that is where they come
        # from rather than being quietly reported as zero
        extra = customer.extra or {}
        line = [
            customer.customer_code, customer.name, customer.mobile, customer.landline, customer.email,
            customer.address, customer.location,
            customer.birth_date or "", customer.anniversary_date or "",
            customer.engagement_date or "", customer.wedding_date or "",
            customer.customer_type, customer.temperature, extra.get("tier", ""),
            ", ".join(customer.metal_preference or []),
            customer.salesperson_preference, customer.payment_preference,
            customer.reference_type,
            customer.referrer.customer_code if customer.referrer else "",
            "Yes" if customer.is_fon else "No", customer.fon_level or "",
            customer.n_orders, customer.n_repairs, customer.n_enquiries,
            customer.personal_observation, customer.client_personal_info,
            customer.created_at.date() if customer.created_at else "",
            customer.updated_at.date() if customer.updated_at else "",
        ]
        if show_money:
            line += [extra.get("creditLimit", ""), extra.get("outstandingBalance", ""), customer.value or 0]
        writer.writerow(line)
    return response


# ── bulk import: the legacy MassUploadModal and PurchaseBulkUpload ───────
IMPORTS = {
    "customers": {
        "title": "Mass upload customers",
        "template": imports.CUSTOMER_TEMPLATE,
        "file_name": "nornament_customer_template.csv",
        "preview": imports.preview_customers,
        "commit": imports.import_customers,
        "done": "crm:customer_list",
        "columns": ["Name", "Mobile", "Code", "Email", "Location", "Birth date", "Type", "Temp"],
    },
    "purchases": {
        "title": "Bulk upload purchases",
        "template": imports.PURCHASE_TEMPLATE,
        "file_name": "nornament_purchase_template.csv",
        "preview": imports.preview_purchases,
        "commit": imports.import_purchases,
        "done": "crm:customer_list",
        "columns": ["Customer", "Date", "Amount", "Category", "Description", "Invoice"],
    },
}


def _import_spec(kind):
    spec = IMPORTS.get(kind)
    if spec is None:
        raise Http404(f"no importer named {kind!r}")
    return spec


@login_required
def import_template(request, kind):
    """The template download both legacy modals offered before anything else."""
    spec = _import_spec(kind)
    response = HttpResponse(imports.template_csv(spec["template"]), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{spec["file_name"]}"'
    return response


@login_required
def bulk_import(request, kind):
    """Drop a CSV, see what it understood, then commit.

    The preview is not decoration. Confirming posts back the same CSV text it
    was shown, so what gets written is exactly what was on screen — and a row
    the preview objected to is never written at all.
    """
    spec = _import_spec(kind)
    if kind == "purchases" and not request.user.has_perm("accounts.adjust_stock"):
        messages.error(request, "You do not have permission to record sales.")
        return redirect("crm:customer_list")

    context = {
        "nav": "customers",
        "kind": kind,
        "spec": spec,
        "form": crm_forms.CsvUploadForm(),
        "categories": services.CATEGORY_LABELS,
    }
    if request.method != "POST":
        return render(request, "crm/import.html", context)

    raw = request.POST.get("csv_text")
    if raw is None:
        form = crm_forms.CsvUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            context["form"] = form
            return render(request, "crm/import.html", context)
        raw = imports.text_of(form.cleaned_data["csv_file"])

    headers, rows = imports.read_csv(raw)
    if not rows:
        messages.error(request, "That file has headers but no data rows.")
        return render(request, "crm/import.html", context)

    preview = spec["preview"](rows)
    if request.POST.get("commit"):
        created, skipped = spec["commit"](preview)
        messages.success(request, f"Imported {created} row{'s' if created != 1 else ''}, skipped {skipped}.")
        return redirect(spec["done"])

    context |= {
        "headers": headers,
        "preview": preview,
        "csv_text": raw,
        "ok_count": sum(1 for row in preview if not row["problem"]),
        "bad_count": sum(1 for row in preview if row["problem"]),
    }
    return render(request, "crm/import.html", context)


# ── the customer's own sub-records ───────────────────────────────────────
def _child_add(request, pk, form_class, tab, assign=None):
    customer = get_object_or_404(Customer, pk=pk)
    form = form_class(request.POST)
    if form.is_valid():
        row = form.save(commit=False)
        row.customer = customer
        if assign:
            assign(row, form)
        row.save()
        messages.success(request, "Saved.")
    else:
        messages.error(request, "; ".join(f"{field}: {error[0]}" for field, error in form.errors.items()))
    return redirect(f"{reverse('crm:customer_detail', args=[pk])}?tab={tab}")


def _child_delete(request, model, pk, tab):
    row = get_object_or_404(model, pk=pk)
    customer_id = row.customer_id
    row.delete()
    messages.success(request, "Deleted.")
    return redirect(f"{reverse('crm:customer_detail', args=[customer_id])}?tab={tab}")


@login_required
@require_POST
def add_purchase(request, pk):
    """A purchase is a sale. It lands in the one ledger, tagged ``source='CRM'``.

    A CRM-sourced sale carries no cost, so its margin is null and the margin
    report filters it out explicitly rather than inventing a number.
    """
    customer = get_object_or_404(Customer, pk=pk)
    back = f"{reverse('crm:customer_detail', args=[pk])}?tab=Purchases"
    if not request.user.has_perm("accounts.adjust_stock"):
        messages.error(request, "You do not have permission to record a sale.")
        return redirect(back)
    form = crm_forms.PurchaseForm(request.POST)
    if not form.is_valid():
        messages.error(request, "; ".join(f"{field}: {error[0]}" for field, error in form.errors.items()))
        return redirect(back)
    sale = services.record_purchase(
        customer,
        sold_on=form.cleaned_data["sold_on"],
        sold_price=form.cleaned_data["sold_price"],
        product_category=form.cleaned_data["category"],
        invoice_no=form.cleaned_data.get("invoice_no") or None,
        description=form.cleaned_data.get("description") or None,
        remarks=form.cleaned_data.get("remarks") or None,
    )
    _attach_posted_files(request, "sale", sale.pk)
    messages.success(request, f"Purchase of {sale.sold_price} recorded.")
    return redirect(back)


@login_required
def edit_purchase(request, pk, sale_pk):
    """The legacy Edit Purchase modal. Only a CRM-sourced row: a stock sale is
    the stock app's to change, and editing it here would move a number the
    margin report depends on."""
    customer = get_object_or_404(Customer, pk=pk)
    sale = get_object_or_404(Sale, pk=sale_pk, customer=customer, source=Sale.CRM)
    back = f"{reverse('crm:customer_detail', args=[pk])}?tab=Purchases"
    if not request.user.has_perm("accounts.adjust_stock"):
        messages.error(request, "You do not have permission to change a sale.")
        return redirect(back)
    if request.method == "POST":
        form = crm_forms.PurchaseForm(request.POST, instance=sale)
        if form.is_valid():
            saved = form.save(commit=False)
            saved.product_category = form.cleaned_data["category"]
            saved.save()
            _attach_posted_files(request, "sale", sale.pk)
            messages.success(request, "Purchase updated.")
            return redirect(back)
    else:
        form = crm_forms.PurchaseForm(instance=sale)
    return render(
        request,
        "crm/purchase_form.html",
        {
            "nav": "customers",
            "customer": customer,
            "sale": sale,
            "form": form,
            "back": back,
            "media": _crm_media("sale", [sale.pk]).get(str(sale.pk), []),
        },
    )


@login_required
@require_POST
def delete_purchase(request, pk, sale_pk):
    if not request.user.has_perm("accounts.adjust_stock"):
        messages.error(request, "You do not have permission to remove a sale.")
    else:
        sale = get_object_or_404(Sale, pk=sale_pk, customer_id=pk, source=Sale.CRM)
        sale.delete()
        messages.success(request, "Purchase removed.")
    return redirect(f"{reverse('crm:customer_detail', args=[pk])}?tab=Purchases")


@login_required
@require_POST
def add_gift(request, pk):
    return _child_add(request, pk, crm_forms.GiftForm, "Gifting")


@login_required
@require_POST
def delete_gift(request, pk):
    return _child_delete(request, Gift, pk, "Gifting")


@login_required
@require_POST
def add_occasion(request, pk):
    return _child_add(request, pk, crm_forms.OccasionForm, "Occasions")


@login_required
@require_POST
def delete_occasion(request, pk):
    return _child_delete(request, Occasion, pk, "Occasions")


@login_required
@require_POST
def add_person(request, pk):
    return _child_add(request, pk, crm_forms.RelatedPersonForm, "Overview")


@login_required
@require_POST
def delete_person(request, pk):
    return _child_delete(request, RelatedPerson, pk, "Overview")


@login_required
@require_POST
def add_outreach(request, pk):
    """Logging outreach also stamps the customer's own outreach summary — the
    legacy app kept both and the dashboard reads the summary."""

    def stamp(row, form):
        customer = row.customer
        customer.outreach_done = True
        customer.outreach_last_date = form.cleaned_data["date"]
        customer.updated_at = timezone.now()
        customer.save(update_fields=["outreach_done", "outreach_last_date", "updated_at"])

    return _child_add(request, pk, crm_forms.OutreachForm, "Outreach", assign=stamp)


@login_required
@require_POST
def delete_outreach(request, pk):
    return _child_delete(request, OutreachEntry, pk, "Outreach")


# ── the four pipeline modules ────────────────────────────────────────────
def _pipeline_rows(request, spec):
    # ``.order('created_at')`` with no re-sort is how the legacy CRM loaded every
    # pipeline, so its list and board read oldest-first; the model's ordering
    # is for everywhere else.
    rows = spec["model"].objects.select_related("customer").order_by("created_at", "pk")
    status = request.GET.get("status")
    if status:
        rows = rows.filter(status=status)
    query = (request.GET.get("q") or "").strip()
    if query:
        rows = rows.filter(
            Q(customer__name__icontains=query) | Q(notes__icontains=query) | Q(**{f"{spec['code']}__icontains": query})
        )
    return list(rows), status or "", query


def _pipeline_list(request, kind, template, extra=None):
    spec = _pipeline(kind)
    rows, status, query = _pipeline_rows(request, spec)
    counts = dict(spec["model"].objects.values_list("status").annotate(n=Count("pk")))
    known = spec["model"].STATUSES
    # A status the app does not know is the one thing a board must not hide:
    # a card that matches no column silently vanishes, which is exactly how a
    # record "loses its stage". It gets a column of its own instead.
    unmapped = [row for row in rows if row.status not in known]
    columns = [(name, [row for row in rows if row.status == name]) for name in known]
    if unmapped:
        columns.append((UNMAPPED_COLUMN, unmapped))
    context = {
        "nav": kind,
        "kind": kind,
        "spec": spec,
        "rows": rows,
        "statuses": known,
        "status_counts": counts,
        "unmapped_statuses": sorted({row.status for row in unmapped}),
        "selected_status": status,
        "q": query,
        "view_mode": "kanban" if request.GET.get("view") == "kanban" else "list",
        "columns": columns,
        "thumbs": _thumbs(spec["media_scope"], rows),
    }
    context.update(extra or {})
    return render(request, template, context)


@login_required
def enquiry_list(request):
    kpis = Enquiry.objects.aggregate(
        total=Count("pk"),
        active=Count("pk", filter=~Q(status__in=["Lost", "Order Confirmed"])),
        converted=Count("pk", filter=Q(status="Order Confirmed")),
        lost=Count("pk", filter=Q(status="Lost")),
    )
    return _pipeline_list(request, "enquiry", "crm/enquiry_list.html", {"kpis": kpis})


@login_required
def order_list(request):
    extra = {
        "counts": Order.objects.aggregate(
            total=Count("pk"),
            open=Count("pk", filter=~Q(status__in=["Delivered", "Cancelled"])),
            delivered=Count("pk", filter=Q(status="Delivered")),
        )
    }
    if allowed(request.user, "sold_price"):
        extra["totals"] = Order.objects.exclude(status="Cancelled").aggregate(
            billed=Sum("billing_amount"),
            advance=Sum("advance_paid"),
            open_balance=Sum(
                Coalesce("billing_amount", "total_amount", Value(Decimal("0")))
                - Coalesce("advance_paid", Value(Decimal("0"))),
                filter=~Q(status="Delivered"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
    return _pipeline_list(request, "order", "crm/order_list.html", extra)


@login_required
def repair_list(request):
    kpis = Repair.objects.aggregate(
        total=Count("pk"),
        open=Count("pk", filter=~Q(status__in=["Ready", "Delivered"])),
        ready=Count("pk", filter=Q(status="Ready")),
        delivered=Count("pk", filter=Q(status="Delivered")),
    )
    return _pipeline_list(request, "repair", "crm/repair_list.html", {"kpis": kpis})


@login_required
def client_material_list(request):
    kpis = ClientMaterial.objects.aggregate(
        total=Count("pk"),
        active=Count("pk", filter=~Q(status__in=["Moved to Order", "Moved to Repair", "Returned"])),
        returned=Count("pk", filter=Q(status="Returned")),
    )
    return _pipeline_list(request, "clientmaterial", "crm/client_material_list.html", {"kpis": kpis})


def _pipeline_detail(request, kind, pk):
    spec = _pipeline(kind)
    row = get_object_or_404(spec["model"].objects.select_related("customer"), pk=pk)
    bills = kind == "order" and allowed(request.user, "sold_price")
    stages = [(name, icon) for name, icon in spec["stages"]]
    try:
        active = [name for name, _ in stages].index(row.status)
    except ValueError:
        active = -1
    return render(
        request,
        f"crm/{kind}_detail.html",
        {
            "nav": kind,
            "kind": kind,
            "spec": spec,
            "row": row,
            "code": getattr(row, spec["code"]),
            "stages": [
                {"name": name, "icon": icon, "state": "done" if i < active else "active" if i == active else ""}
                for i, (name, icon) in enumerate(stages)
            ],
            "lost": row.status in spec["terminal"],
            # neither a stage nor a terminal state: the rail would render blank
            # and both move buttons would be dead, with nothing saying why
            "unknown_status": active == -1 and row.status not in spec["terminal"],
            "log": services.status_log(kind, row.pk),
            "media": _crm_media(spec["media_scope"], [row.pk]).get(str(row.pk), []),
            # The bill is a sale figure, so it is offered on the same terms as
            # the rest of the money on this screen: a login that may not see
            # `sold_price` may still deliver the order, it just does not get to
            # type or read the amount here.
            "status_form": crm_forms.StatusUpdateForm(
                spec["model"].STATUSES,
                bills=kind == "order" and bills,
                initial={"status": row.status, "billing_amount": services.delivery_amount(row) if bills else None},
            ),
            "delivery_sale": services.purchase_for_order(row) if bills else None,
        },
    )


@login_required
def enquiry_detail(request, pk):
    return _pipeline_detail(request, "enquiry", pk)


@login_required
def order_detail(request, pk):
    return _pipeline_detail(request, "order", pk)


@login_required
def repair_detail(request, pk):
    return _pipeline_detail(request, "repair", pk)


@login_required
def client_material_detail(request, pk):
    return _pipeline_detail(request, "clientmaterial", pk)


@login_required
def pipeline_form(request, kind, pk=None):
    """One New/Edit screen for all four modules — they differ only by form."""
    spec = _pipeline(kind)
    row = get_object_or_404(spec["model"], pk=pk) if pk else None
    if request.method == "POST":
        form = spec["form"](request.POST, instance=row, user=request.user)
        if form.is_valid():
            created = row is None
            saved = form.save(commit=False)
            saved.updated_at = timezone.now()
            saved.save()
            _attach_posted_files(request, spec["media_scope"], saved.pk)
            if created:
                StatusEvent.objects.create(
                    entity_type=kind,
                    entity_id=saved.pk,
                    date=timezone.localdate(),
                    status=saved.status,
                    by=saved.salesperson,
                )
            messages.success(request, f"{getattr(saved, spec['code'])} saved.")
            if kind == "order" and saved.status == "Delivered":
                # the amount that was missing at delivery, typed in later: the
                # purchase is recorded now rather than waiting for a re-delivery
                sale = services.record_order_delivery(saved)
                if sale and allowed(request.user, "sold_price"):
                    messages.success(request, f"{sale.sold_price} recorded against {saved.customer.name}.")
                elif sale:
                    messages.success(request, f"The bill was recorded against {saved.customer.name}.")
            return redirect(spec["detail_url"], pk=saved.pk)
    else:
        initial = {}
        if row is None:
            initial[spec["code"]] = services.next_code(spec["model"], kind)
            initial["status"] = spec["model"].STATUSES[0]
            for field in ("enquiry_date", "order_date", "received_date"):
                if field in spec["form"].Meta.fields:
                    initial[field] = timezone.localdate()
            if request.GET.get("customer"):
                initial["customer"] = request.GET["customer"]
        form = spec["form"](instance=row, initial=initial, user=request.user)
    return render(
        request,
        "crm/pipeline_form.html",
        {
            "nav": kind,
            "kind": kind,
            "spec": spec,
            "form": form,
            "row": row,
            "media": _crm_media(spec["media_scope"], [row.pk]).get(str(row.pk), []) if row else [],
        },
    )


@login_required
@require_POST
def pipeline_status(request, kind, pk):
    spec = _pipeline(kind)
    row = get_object_or_404(spec["model"], pk=pk)
    status = request.POST.get("status")
    if status not in spec["model"].STATUSES:
        messages.error(request, f"{status!r} is not a {kind} status.")
        return _redirect_back(request, reverse(spec["detail_url"], args=[pk]))

    services.log_status(row, kind, status, note=request.POST.get("note", ""), by=request.POST.get("by", ""))
    messages.success(request, f"{getattr(row, spec['code'])} is now {status}.")
    if kind == "order" and status == "Delivered":
        _bill_the_delivery(request, row)
    return _redirect_back(request, reverse(spec["detail_url"], args=[pk]))


def _bill_the_delivery(request, order):
    """A delivered order becomes a line in the customer's purchase history.

    The bill typed into the status form wins; failing that the order's own
    billing or total amount stands in, which is what the legacy CRM used. When
    there is no figure anywhere the user is told, because a delivery that
    quietly adds nothing to the customer's value is the bug being fixed.
    """
    amount = _decimal_or_none(request.POST.get("billing_amount"))
    if order.customer_id is None:
        messages.warning(request, f"{order.order_code} has no customer, so nothing was added to a purchase history.")
        return
    sale = services.record_order_delivery(order, amount=amount, by=request.POST.get("by", ""))
    if sale is None:
        messages.warning(
            request,
            f"{order.order_code} is delivered but has no bill amount, so nothing was added to "
            f"{order.customer.name}'s purchase history. Add the amount and it will be recorded.",
        )
        return
    # The figure itself is a sale price: naming it in a flash message would put
    # it in front of a login that the screen behind carefully does not show it to.
    if allowed(request.user, "sold_price"):
        messages.success(request, f"{sale.sold_price} added to {order.customer.name}'s purchase history.")
    else:
        messages.success(request, f"The bill on {order.order_code} was added to {order.customer.name}'s purchase history.")


def _decimal_or_none(value):
    text = str(value or "").replace(",", "").replace("₹", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


@login_required
@require_POST
def pipeline_delete(request, kind, pk):
    spec = _pipeline(kind)
    row = get_object_or_404(spec["model"], pk=pk)
    code = getattr(row, spec["code"])
    StatusEvent.objects.filter(entity_type=kind, entity_id=row.pk).delete()
    row.delete()
    messages.success(request, f"{code} deleted.")
    return redirect(spec["list_url"])


@login_required
@require_POST
def enquiry_convert(request, pk):
    enquiry = get_object_or_404(Enquiry, pk=pk)
    order = services.convert_enquiry_to_order(enquiry, by=str(request.user))
    messages.success(request, f"{enquiry.enquiry_code} is now {order.order_code}.")
    return redirect("crm:order_detail", pk=order.pk)


@login_required
@require_POST
def material_convert(request, pk, target):
    material = get_object_or_404(ClientMaterial, pk=pk)
    if target == "order":
        row = services.client_material_to_order(material, by=str(request.user))
        messages.success(request, f"{material.cm_code} is now {row.order_code}.")
        return redirect("crm:order_detail", pk=row.pk)
    if target == "repair":
        row = services.client_material_to_repair(material, by=str(request.user))
        messages.success(request, f"{material.cm_code} is now {row.repair_code}.")
        return redirect("crm:repair_detail", pk=row.pk)
    raise Http404(target)


# ── network, reports, tools ──────────────────────────────────────────────
@login_required
def fon_register_view(request):
    """The payout run — every member, computed off the sale ledger.

    Rendered as the legacy tree: a card per level 1, their level 2s indented
    beneath, level 3s beneath those, and the payout breakdown at the foot.
    """
    payouts = services.fon_register()
    by_customer = {payout.customer.pk: payout for payout in payouts}
    members = Customer.objects.filter(is_fon=True).select_related("fon_parent")
    tree = []
    for level_1 in [m for m in members if m.fon_level == 1]:
        seconds = []
        for level_2 in [m for m in members if m.fon_level == 2 and m.fon_parent_id == level_1.pk]:
            thirds = [m for m in members if m.fon_level == 3 and m.fon_parent_id == level_2.pk]
            seconds.append({"member": level_2, "children": thirds})
        tree.append({"member": level_1, "payout": by_customer.get(level_1.pk), "children": seconds})
    return render(
        request,
        "crm/fon.html",
        {
            "nav": "fon",
            "tree": tree,
            "payouts": payouts,
            "levels": {
                level: members.filter(fon_level=level).count() for level in (1, 2, 3)
            },
            "total": sum((payout.total_payout for payout in payouts), Decimal("0")),
            "categories": services.CATEGORY_LABELS,
            "orphans": [m for m in members if m.fon_level != 1 and m.fon_parent_id is None],
        },
    )


@login_required
def fon_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    return render(
        request,
        "crm/fon_detail.html",
        {
            "nav": "fon",
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
        "nav": "reports",
        "financial_year_start": year_start,
        "year": today.year,
        "pipeline": services.pipeline_counts(),
        "by_status": Order.objects.values("status").annotate(orders=Count("pk")).order_by("status"),
        "by_source": Customer.objects.values("reference_type").annotate(n=Count("pk")).order_by("-n"),
        "fon_members": Customer.objects.filter(is_fon=True).count(),
    }
    context["source_peak"] = max((row["n"] for row in context["by_source"]), default=0) or 1
    if allowed(request.user, "sold_price"):
        context["revenue"] = {
            "all": services.revenue_between(year_start, today),
            "stock": services.revenue_between(year_start, today, Sale.STOCK),
            "crm": services.revenue_between(year_start, today, Sale.CRM),
        }
        context["total_revenue"] = Sale.objects.aggregate(total=Sum("sold_price"))["total"] or Decimal("0")
        context["purchase_count"] = Sale.objects.count()
        # the legacy chart is the calendar year, Jan-Dec, one bar a month
        by_month = dict(
            Sale.objects.filter(sold_on__year=today.year)
            .annotate(month=TruncMonth("sold_on"))
            .values_list("month")
            .annotate(revenue=Sum("sold_price"))
        )
        context["monthly"] = [
            {"month": date(today.year, month, 1), "revenue": by_month.get(date(today.year, month, 1)) or Decimal("0")}
            for month in range(1, 13)
        ]
        context["monthly_peak"] = max((row["revenue"] for row in context["monthly"]), default=Decimal("0")) or 1
        by_category = dict(
            Sale.objects.filter(sold_on__gte=year_start, sold_on__lte=today)
            .values_list("product_category")
            .annotate(revenue=Sum("sold_price"))
        )
        context["by_category"] = [
            (label, by_category.get(key) or Decimal("0")) for key, label in services.CATEGORY_LABELS.items()
        ]
        context["category_peak"] = max((amount for _, amount in context["by_category"]), default=Decimal("0")) or 1
    if allowed(request.user, "margin_amt"):
        context["margin"] = services.margin_between(year_start, today)
    return render(request, "crm/reports.html", context)


@login_required
def calculator(request):
    """The quote calculator.

    The arithmetic runs in the browser because a quote is a scratchpad — but
    every rate it starts from comes from here, off ``MetalPurity`` and the
    default ``RateChart``. The standalone HTML file carried its own ``PURITY``
    table, which is how 925 silver came to be priced off the gold rate.
    """
    purities = quote.purity_rates()
    stones = quote.stone_rates()
    return render(
        request,
        "crm/calculator.html",
        {
            "nav": "quote",
            "today": timezone.localdate(),
            "purities": purities,
            "stones": stones,
            "rates": {
                "metals": [
                    {"karat": row["karat"], "metal_name": row["metal_name"], "sale_rate": float(row["sale_rate"] or 0)}
                    for row in purities
                ],
                "stones": stones,
                "default_making": float(services.default_making_rate()),
            },
            "enquiries": Enquiry.objects.exclude(status__in=["Lost", "Order Confirmed"])
            .select_related("customer")
            .order_by("-enquiry_date")[:50],
        },
    )


@login_required
@require_POST
def quote_attach(request):
    """``shareToEnquiry`` — put the quote on the enquiry it belongs to.

    Written as a status update rather than into a field of its own: it is a
    thing that happened on a date, it belongs on the timeline, and the enquiry
    moves to "Quote Sent" the same way every other stage change does.
    """
    enquiry = get_object_or_404(Enquiry, pk=request.POST.get("enquiry"))
    try:
        payload = json.loads(request.POST.get("quote") or "{}")
    except json.JSONDecodeError:
        payload = {}
    items = payload.get("items") or []
    if not items:
        messages.error(request, "Add at least one item before attaching a quote.")
        return redirect("crm:calculator")

    lines = []
    for item in items:
        name = str(item.get("name") or "Item")[:80]
        total = Decimal(str(item.get("total") or 0)) if item.get("total") is not None else None
        if total is None:
            goods = sum(
                Decimal(str(c.get("weight") or 0)) * Decimal(str(c.get("rate") or 0))
                for c in item.get("components") or []
            )
            grams = sum(
                Decimal(str(c.get("weight") or 0))
                for c in item.get("components") or []
                if c.get("kind") == "metal"
            )
            total = goods + grams * Decimal(str(item.get("makingRate") or 0))
        lines.append(f"{name} — ₹{total:,.0f}")
    grand = Decimal(str(payload.get("total") or 0))
    note = "Quote: " + "; ".join(lines) + f". Total ₹{grand:,.0f}."

    services.log_status(enquiry, "enquiry", "Quote Sent", note=note[:2000], by=str(request.user))
    messages.success(request, f"Quote attached to {enquiry.enquiry_code}.")
    return redirect("crm:enquiry_detail", pk=enquiry.pk)


@login_required
def search(request):
    """The legacy search overlay. Returns a fragment for HTMX, a page without."""
    query = request.GET.get("q") or ""
    results = services.search(query)
    template = "crm/_search_results.html" if request.headers.get("HX-Request") else "crm/search.html"
    return render(request, template, {"nav": "search", "q": query, "results": results})


# ── PWA: installable, and a target for "share to Nornament" ──────────────
@login_required
def manifest(request):
    """The legacy manifest.json, pointed at Django's URLs.

    ``share_target`` posts to ``share-target``, which nothing serves: the
    service worker intercepts it. It has to — a share POST arrives from another
    app, so SameSite=Lax withholds the session cookie and the request would
    reach Django logged out.
    """
    return JsonResponse(
        {
            "name": "Nornament CRM",
            "short_name": "Nornament",
            "description": "Nornament Jewellery CRM — Customers, Orders, Repairs",
            "start_url": reverse("crm:dashboard"),
            "scope": reverse("crm:dashboard"),
            "display": "standalone",
            "background_color": "#F7F6F3",
            "theme_color": "#B08C3C",
            "icons": [
                {"src": static("img/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                {"src": static("img/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
            ],
            "share_target": {
                "action": reverse("crm:dashboard") + "share-target",
                "method": "POST",
                "enctype": "multipart/form-data",
                "params": {
                    "title": "title",
                    "text": "text",
                    "files": [{"name": "media", "accept": ["image/*", "video/*", "application/pdf"]}],
                },
            },
        },
        content_type="application/manifest+json",
    )


def service_worker(request):
    """Served from /crm/ so its scope is /crm/ — a worker's scope cannot be
    broader than the path it is served from, and /static/ would be too narrow."""
    path = finders.find("js/crm-sw.js")
    if not path:
        raise Http404("service worker not collected")
    with open(path, "rb") as handle:
        response = HttpResponse(handle.read(), content_type="text/javascript")
    response["Service-Worker-Allowed"] = reverse("crm:dashboard")
    return response


@login_required
def share_inbox(request):
    """``ShareAttachSheet`` — a photo shared into the app, waiting for a customer."""
    return render(request, "crm/share.html", {"nav": "customers", "customers": _share_customers(request)})


@login_required
def share_customers(request):
    """The picker's live rows, for HTMX."""
    return render(request, "crm/_share_rows.html", {"customers": _share_customers(request)})


def _share_customers(request):
    query = (request.GET.get("q") or "").strip()
    rows = Customer.objects.all()
    if query:
        rows = rows.filter(
            Q(name__icontains=query) | Q(customer_code__icontains=query) | Q(mobile__icontains=query)
        )
    return rows.order_by("name")[:8]


@login_required
@require_POST
def quick_customer(request):
    """The legacy forms let you name a walk-in without leaving the enquiry.

    Returns to wherever you were, with ``?customer=<pk>`` so the form you came
    from selects the person you just created.
    """
    name = (request.POST.get("name") or "").strip()
    if not name:
        messages.error(request, "A name is the one thing a customer needs.")
        return _redirect_back(request, reverse("crm:customer_list"))
    customer = services.quick_customer(name, request.POST.get("phone", ""))
    messages.success(request, f"{customer.name} added as {customer.customer_code}.")
    target = request.POST.get("next")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        joiner = "&" if "?" in target else "?"
        return redirect(f"{target}{joiner}customer={customer.pk}")
    return redirect("crm:customer_detail", pk=customer.pk)


@login_required
def settings_view(request):
    """The Settings modal: the salesperson and location lists it maintained."""
    if request.method == "POST":
        kind = request.POST.get("kind")
        if kind == "salesperson":
            form, model = crm_forms.SalespersonForm(request.POST), Salesperson
        elif kind == "location":
            form, model = crm_forms.LocationForm(request.POST), Location
        else:
            raise Http404(kind)
        if request.POST.get("delete"):
            model.objects.filter(pk=request.POST["delete"]).delete()
            messages.success(request, "Removed.")
        elif form.is_valid():
            form.save()
            messages.success(request, "Saved.")
        else:
            messages.error(request, "; ".join(f"{f}: {e[0]}" for f, e in form.errors.items()))
        return redirect("crm:settings")
    return render(
        request,
        "crm/settings.html",
        {
            "nav": "settings",
            "salespersons": Salesperson.objects.all(),
            "locations": Location.objects.all(),
            "salesperson_form": crm_forms.SalespersonForm(),
            "location_form": crm_forms.LocationForm(),
        },
    )
