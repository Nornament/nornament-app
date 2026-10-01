"""Diamond Settings: one page of cards, each card's actions posting to a small view.

Every write goes through ``dia_services``; this module only reads the form,
calls the service, and sends the user back to the card they were on.
"""
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts.capabilities import INV_MASTERS, ROLE_GROUPS, VIEW_COST, VIEW_SALE
from stock.masking import mask
from stock.models import Vendor
from stock.services import ServiceError, require

from . import dia_rows, dia_seed, dia_services
from .models import DiamondCode, DiamondTerm, StockDocument
from .views_diamonds import dia_page, viewer

CARD_TITLES = [(DiamondTerm.CATEGORY, "Categories"), (DiamondTerm.SHAPE, "Shapes"),
               (DiamondTerm.COLOUR, "Colour grades"), (DiamondTerm.CLARITY, "Clarity grades"),
               (DiamondTerm.BAND, "Size bands")]


LADDERS = {DiamondTerm.COLOUR: dia_seed.COLOUR_LADDER, DiamondTerm.CLARITY: dia_seed.CLARITY_LADDER}


def _back(anchor):
    return redirect(reverse("inventory:dia_settings") + f"#{anchor}")


def _rights_matrix():
    groups = {g.name: set(g.permissions.values_list("codename", flat=True)) for g in Group.objects.all()}
    return [{"code": code, "name": ROLE_GROUPS[code]["name"], "locked": code == "ADMIN",
             "cells": [(codename, code == "ADMIN" or codename in groups.get(code, set()))
                       for codename, _ in dia_services.RIGHTS]}
            for code in dia_services.ROLE_ORDER]


@login_required
def settings_page(request):
    """Built for the viewer, so an admin's preview shows what the role would; every form still
    posts as the real login."""
    user, role = viewer(request)
    if not user.has_perm(INV_MASTERS):
        return dia_page(request, "inventory/diamonds/settings.html", dtab="settings", denied=True,
                        role_label=ROLE_GROUPS[role]["name"])
    lines = list(dia_services.stocked_lines())
    usage = dia_rows.term_usage(lines)
    by_kind = {kind: [] for kind, _ in CARD_TITLES}
    for t in DiamondTerm.objects.order_by("kind", "sort", "value"):
        n, ct = usage.get(t.pk, (0, 0))
        by_kind[t.kind].append({"term": t, "n": n, "ct": ct, "bad": t.value.startswith(("?", "("))})
    code_lines = {}
    for line in lines:
        code_lines[line.code_id] = code_lines.get(line.code_id, 0) + 1
    rates = [mask(user, {"code": code, "size_text": size_text, "cost_rate": rate["cost"], "sale_rate": rate["sale"]})
             for (code, size_text), rate in sorted(dia_services.rate_table().items())]
    # purchases per supplier: documents, stones and diamond, that stand (not a reversal, not reversed)
    purchases = Counter(StockDocument.objects.filter(
        kind__in=(StockDocument.Kind.PURCHASE, StockDocument.Kind.DIA_PURCHASE), reverses__isnull=True,
    ).exclude(status=StockDocument.Status.REVERSED).values_list("vendor_id", flat=True))
    return dia_page(
        request, "inventory/diamonds/settings.html", dtab="settings", denied=False,
        cards=[(kind, title, by_kind[kind]) for kind, title in CARD_TITLES],
        codes=[(c, code_lines.get(c.pk, 0)) for c in DiamondCode.objects.select_related("shape", "colour", "clarity")],
        terms_of={kind: [t["term"] for t in by_kind[kind]] for kind, _ in CARD_TITLES},
        rates=rates,
        can_rate=user.has_perm(VIEW_COST) and user.has_perm(VIEW_SALE),
        expansions=[t for t in DiamondTerm.objects.filter(kind__in=[DiamondTerm.COLOUR, DiamondTerm.CLARITY])
                    if t.value not in LADDERS[t.kind] and not t.value.startswith("Fancy")],
        supplier_card=mask(user, {"vendor_name": True}),
        suppliers=[mask(user, {"pk": v.pk, "vendor_code": v.code, "vendor_name": v.name, "city": v.city,
                                       "terms": v.terms, "purchases": purchases.get(v.pk, 0)})
                   for v in Vendor.objects.filter(is_active=True).order_by("name")],
        rights=dia_services.RIGHTS, matrix=_rights_matrix(), me=role,
        is_admin=user is request.user and request.user.is_admin(),
        today=date.today(),
    )


def _term_card(request, pk=None):
    if pk is None:
        return request.POST.get("kind", "")
    return DiamondTerm.objects.filter(pk=pk).values_list("kind", flat=True).first() or ""


def _guarded(anchor):
    """POST only, logged in, and the masters right — checked here and again in the service.
    A refusal goes back to the view's own card: ``anchor``, or a function of the request that finds it."""
    def decorate(view):
        @login_required
        @require_POST
        def wrapped(request, *args, **kwargs):
            require(request.user, INV_MASTERS, "Only a role that edits settings can change them.")
            try:
                return view(request, *args, **kwargs)
            except ServiceError as error:
                messages.error(request, error.messages[0])
                return _back(anchor(request, **kwargs) if callable(anchor) else anchor)
        return wrapped
    return decorate


@_guarded(_term_card)
def term_add(request):
    kind = request.POST.get("kind", "")
    dia_services.add_term(request.user, kind, request.POST.get("value"))
    return _back(kind)


@_guarded(_term_card)
def term_rename(request, pk):
    t = get_object_or_404(DiamondTerm, pk=pk)
    dia_services.rename_term(request.user, t, request.POST.get("value"))
    return _back(t.kind)


@_guarded(_term_card)
def term_delete(request, pk):
    t = get_object_or_404(DiamondTerm, pk=pk)
    kind = t.kind
    dia_services.delete_term(request.user, t)
    return _back(kind)


@_guarded("expansion")
def expansion(request, pk):
    t = get_object_or_404(DiamondTerm, pk=pk, kind__in=[DiamondTerm.COLOUR, DiamondTerm.CLARITY])
    dia_services.set_expansion(request.user, t, request.POST.get("grades"))
    return _back("expansion")


def _term_or_none(raw, kind):
    return DiamondTerm.objects.filter(pk=raw, kind=kind).first() if (raw or "").isdigit() else None


@_guarded("codes")
def code_save(request, code):
    item = get_object_or_404(DiamondCode, pk=code)
    dia_services.save_code(
        request.user, item, _term_or_none(request.POST.get("shape"), DiamondTerm.SHAPE),
        _term_or_none(request.POST.get("colour"), DiamondTerm.COLOUR),
        _term_or_none(request.POST.get("clarity"), DiamondTerm.CLARITY),
        bool(request.POST.get("confirmed")), request.POST.get("note"),
    )
    return _back("codes")


def _decimal(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ServiceError(f"{raw} is not a number.")


def _date(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        day = parse_date(raw)
    except ValueError:
        day = None
    if day is None:
        raise ServiceError(f"{raw} is not a date.")
    return day


@_guarded("rates")
def rate_save(request):
    code = get_object_or_404(DiamondCode, pk=request.POST.get("code", ""))
    dia_services.set_rate(request.user, code, request.POST.get("size_text"), _decimal(request.POST.get("cost_rate")),
                          _decimal(request.POST.get("sale_rate")), _date(request.POST.get("effective_from")))
    messages.success(request, "Rate saved.")
    return _back("rates")


@_guarded("rates")
def rates_ivy(request):
    upload = request.FILES.get("workbook")
    if upload is None:
        raise ServiceError("Choose the IVY export first.")
    result = dia_services.load_ivy_rates(request.user, upload)
    messages.success(request, f"{result['loaded']} sale rates loaded; {result['unknown']} codes in the export are not diamond lines here.")
    return _back("rates")


@_guarded("suppliers")
def supplier_save(request):
    raw = request.POST.get("pk", "")
    vendor = Vendor.objects.filter(pk=raw).first() if raw.isdigit() else None
    dia_services.save_supplier(request.user, vendor, request.POST.get("code"), request.POST.get("name"),
                               request.POST.get("city"), request.POST.get("terms"))
    return _back("suppliers")


@login_required
@require_POST
def right_toggle(request):
    try:
        dia_services.set_right(request.user, request.POST.get("role", ""), request.POST.get("right", ""),
                               request.POST.get("on") == "1")
    except ServiceError as error:
        messages.error(request, error.messages[0])
    return _back("rights")
