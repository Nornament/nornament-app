"""Diamond Settings: one page of cards, each card's actions posting to a small view.

Every write goes through ``dia_services``; this module only reads the form,
calls the service, and sends the user back to the card they were on.
"""
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

from . import dia_rows, dia_services
from .models import DiamondCode, DiamondRate, DiamondTerm, Movement
from .views_diamonds import dia_page

CARD_TITLES = [(DiamondTerm.CATEGORY, "Categories"), (DiamondTerm.SHAPE, "Shapes"),
               (DiamondTerm.COLOUR, "Colour grades"), (DiamondTerm.CLARITY, "Clarity grades"),
               (DiamondTerm.BAND, "Size bands")]


def _back(anchor):
    return redirect(reverse("inventory:dia_settings") + f"#{anchor}")


def _rights_matrix(user):
    groups = {g.name: set(g.permissions.values_list("codename", flat=True)) for g in Group.objects.all()}
    return [{"code": code, "name": ROLE_GROUPS[code]["name"], "locked": code == "ADMIN",
             "cells": [(codename, code == "ADMIN" or codename in groups.get(code, set()))
                       for codename, _ in dia_services.RIGHTS]}
            for code in dia_services.ROLE_ORDER]


@login_required
def settings_page(request):
    if not request.user.has_perm(INV_MASTERS):
        return dia_page(request, "inventory/diamonds/settings.html", dtab="settings", denied=True)
    lines = list(dia_services.stocked_lines())
    usage = dia_rows.term_usage(lines)
    by_kind = {kind: [] for kind, _ in CARD_TITLES}
    for t in DiamondTerm.objects.order_by("kind", "sort", "value"):
        n, ct = usage.get(t.pk, (0, 0))
        by_kind[t.kind].append({"term": t, "n": n, "ct": ct, "bad": t.value.startswith(("?", "("))})
    code_lines = {}
    for line in lines:
        code_lines[line.code_id] = code_lines.get(line.code_id, 0) + 1
    rates = [mask(request.user, {"code": r.code_id, "size_text": r.size_text, "cost_rate": r.cost_rate,
                                 "sale_rate": r.sale_rate, "effective_from": r.effective_from})
             for r in DiamondRate.objects.all()]
    purchases = {}
    for vendor_id in Movement.objects.filter(reason=Movement.Reason.PURCHASE).values_list("counterparty_id", flat=True):
        purchases[vendor_id] = purchases.get(vendor_id, 0) + 1
    return dia_page(
        request, "inventory/diamonds/settings.html", dtab="settings", denied=False,
        cards=[(kind, title, by_kind[kind]) for kind, title in CARD_TITLES],
        codes=[(c, code_lines.get(c.pk, 0)) for c in DiamondCode.objects.select_related("shape", "colour", "clarity")],
        terms_of={kind: [t["term"] for t in by_kind[kind]] for kind, _ in CARD_TITLES},
        rates=sorted(rates, key=lambda r: (r["code"], r["size_text"])),
        can_rate=request.user.has_perm(VIEW_COST) and request.user.has_perm(VIEW_SALE),
        expansions=[t for t in DiamondTerm.objects.filter(kind__in=[DiamondTerm.COLOUR, DiamondTerm.CLARITY])
                    if t.expands_to or t.value.startswith("?")],
        suppliers=[(v, purchases.get(v.pk, 0)) for v in Vendor.objects.filter(is_active=True).order_by("name")],
        rights=dia_services.RIGHTS, matrix=_rights_matrix(request.user), is_admin=request.user.is_admin(),
        today=date.today(),
    )


def _guarded(view):
    """POST only, logged in, and the masters right — checked here and again in the service."""
    @login_required
    @require_POST
    def wrapped(request, *args, **kwargs):
        require(request.user, INV_MASTERS, "Only a role that edits settings can change them.")
        try:
            return view(request, *args, **kwargs)
        except ServiceError as error:
            messages.error(request, error.messages[0])
            return _back(kwargs.get("anchor") or request.POST.get("anchor", ""))
    return wrapped


@_guarded
def term_add(request):
    kind = request.POST.get("kind", "")
    dia_services.add_term(request.user, kind, request.POST.get("value"))
    return _back(kind)


@_guarded
def term_rename(request, pk):
    t = get_object_or_404(DiamondTerm, pk=pk)
    dia_services.rename_term(request.user, t, request.POST.get("value"))
    return _back(t.kind)


@_guarded
def term_delete(request, pk):
    t = get_object_or_404(DiamondTerm, pk=pk)
    kind = t.kind
    dia_services.delete_term(request.user, t)
    return _back(kind)


@_guarded
def expansion(request, pk):
    t = get_object_or_404(DiamondTerm, pk=pk, kind__in=[DiamondTerm.COLOUR, DiamondTerm.CLARITY])
    dia_services.set_expansion(request.user, t, request.POST.get("grades"))
    return _back("expansion")


def _term_or_none(raw, kind):
    return DiamondTerm.objects.filter(pk=raw, kind=kind).first() if (raw or "").isdigit() else None


@_guarded
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


@_guarded
def rate_save(request):
    code = get_object_or_404(DiamondCode, pk=request.POST.get("code", ""))
    dia_services.set_rate(request.user, code, request.POST.get("size_text"), _decimal(request.POST.get("cost_rate")),
                          _decimal(request.POST.get("sale_rate")), parse_date(request.POST.get("effective_from") or ""))
    messages.success(request, "Rate saved.")
    return _back("rates")


@_guarded
def rates_ivy(request):
    upload = request.FILES.get("workbook")
    if upload is None:
        raise ServiceError("Choose the IVY export first.")
    result = dia_services.load_ivy_rates(request.user, upload)
    messages.success(request, f"{result['loaded']} rates loaded; {result['unknown']} codes in the export are not diamond lines here.")
    return _back("rates")


@_guarded
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
