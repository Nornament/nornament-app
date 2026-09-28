"""The inventory screens. Thin: services write, rows mask, templates draw."""
import os
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.capabilities import INV_MASTERS
from mediahub.models import MediaAsset
from mediahub.services import attach_uploads
from stock.enums import MediaKind
from stock.masking import allowed, mask
from stock.models import Vendor
from stock.services import ServiceError, require

from . import rows, services
from .models import ORIGINS, TREATMENTS, Batch, BoxColour, CodePart, Pouch, PriceEntry

BATCH_CAP = 40


def _client(request):
    return bool(request.session.get("inv_client"))


def _everything(request):
    return rows.pouch_rows(request.user, services.stocked(), client=_client(request))


def _labels():
    return {(part.kind, part.code): part for part in CodePart.objects.all()}


def _page(request, template, everything, **context):
    """Every screen carries the rail's counts, which are counts of the whole shelf."""
    context.update(client_view=_client(request), rail=rows.summarise(everything))
    return render(request, template, context)


def _next(request, fallback="inventory:shelf"):
    target = request.POST.get("next") or ""
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return redirect(fallback).url


@login_required
@require_POST
def set_view(request):
    """Internal or client. A session flag, so it holds as staff click through the shelf."""
    request.session["inv_client"] = request.POST.get("view") == "client"
    return redirect(_next(request))


@login_required
def shelf(request):
    everything = _everything(request)
    return _page(request, "inventory/shelf.html", everything, tab="shelf",
                 totals=rows.summarise(everything), colours=rows.by_colour(everything))


@login_required
def colour(request, code):
    box = get_object_or_404(BoxColour, pk=code)
    everything = _everything(request)
    batches = rows.by_batch([r for r in everything if r["box_colour"] == box.code], _labels())
    shown = batches if request.GET.get("all") == "1" else batches[:BATCH_CAP]
    return _page(request, "inventory/colour.html", everything, tab="shelf", box=box,
                 batches=shown, batch_total=len(batches))


@login_required
def batch(request, pk):
    batch = get_object_or_404(Batch.objects.select_related("box_colour"), pk=pk)
    everything = _everything(request)
    mine = [r for r in everything if r["batch_pk"] == batch.pk]
    labels = _labels()
    table = request.GET.get("view") == "table" and not _client(request)
    return _page(request, "inventory/batch.html", everything, tab="shelf", batch=batch, box=batch.box_colour,
                 pouches=mine, view="table" if table else "grid", decoder=rows.decoder(batch, labels),
                 names=rows.by_batch(mine, labels)[0]["names"] if mine else "",
                 money=bool(mine) and "pouch_value" in mine[0])


#: which gated field a price of each kind is — so the history masks like everything else
PRICE_FIELD = {PriceEntry.VALUATION: "valuation_rate", PriceEntry.PURCHASE: "purchase_rate", PriceEntry.LIST: "list_rate"}


def _price_card(user, pouch):
    valuation, purchase, listed = (services.latest_price(pouch, kind) for kind in
                                   (PriceEntry.VALUATION, PriceEntry.PURCHASE, PriceEntry.LIST))
    card = mask(user, {
        "valuation_rate": valuation.rate if valuation else None,
        "purchase_rate": purchase.rate if purchase else None,
        "list_rate": listed.rate if listed else None,
    })
    if "valuation_rate" in card:
        card["valuation_date"] = valuation.effective_from if valuation else None
    return card


def _missing(row):
    parts = [name for name, key in (("weight", "ct"), ("rate", "stone_rate")) if row.get(key) is None]
    return " and no ".join(parts)


def _size_foot(kind):
    return {"lw": "length × width", "dia": "diameter", "multi": "several sizes in one pouch"}.get(kind, "free size — no millimetres")


@login_required
def pouch(request, ref):
    obj = get_object_or_404(Pouch.objects.select_related("batch__box_colour"), ref=ref)
    everything = _everything(request)
    row = next(r for r in everything if r["pk"] == obj.pk)
    labels = _labels()
    photos = list(MediaAsset.objects.filter(scope="pouch", scope_id=str(obj.pk), kind=MediaKind.PHOTO,
                                            is_archived=False).order_by("rank_order", "pk"))
    held = services.stocked(Pouch.objects.filter(pk=obj.pk)).get()
    prices = {} if _client(request) else _price_card(request.user, obj)
    history = [e for e in obj.prices.order_by("-effective_from", "-pk") if allowed(request.user, PRICE_FIELD[e.kind])]
    return _page(
        request, "inventory/pouch.html", everything, tab="lot", pouch_ref=obj.ref, row=row, box=obj.batch.box_colour,
        shares=rows.shares(row, everything) if row.get("pouch_value") is not None else None,
        missing=_missing(row), size_mm=row["size_display"].removesuffix(" mm"), size_foot=_size_foot(row["size_kind"]),
        avg=(held.on_ct / held.on_pcs) if (held.on_ct is not None and held.on_pcs) else None,
        in_stock=bool((held.on_ct or 0) > 0 or (held.on_pcs or 0) > 0),
        family_label=rows.label(labels, "family", obj.batch.family),
        class_label=rows.label(labels, "class", obj.batch.cls),
        photos=photos, prices=prices, history=history, movement_count=obj.movements.count(),
        price_kinds=[(k, label) for k, label in PriceEntry.KINDS if allowed(request.user, PRICE_FIELD[k])],
        treatments=TREATMENTS, origins=ORIGINS, vendors=Vendor.objects.filter(is_active=True).order_by("name"),
    )


@login_required
@require_POST
def pouch_save(request, ref):
    obj = get_object_or_404(Pouch, ref=ref)
    changes = {name: request.POST.get(name, "") for name in ("treatment", "origin") if name in request.POST}
    if "purchase_date" in request.POST:
        raw = request.POST.get("purchase_date") or ""
        changes["purchase_date"] = parse_date(raw) if raw else None
        if raw and changes["purchase_date"] is None:
            messages.error(request, "That purchase date does not read as a date.")
            return redirect("inventory:pouch", ref=ref)
    if "supplier" in request.POST:
        changes["supplier"] = Vendor.objects.filter(pk=request.POST.get("supplier") or 0).first()
    try:
        services.save_details(request.user, obj, **changes)
        messages.success(request, "Saved.")
    except ServiceError as error:
        messages.error(request, error.messages[0])
    return redirect("inventory:pouch", ref=ref)


@login_required
@require_POST
def pouch_price(request, ref):
    obj = get_object_or_404(Pouch, ref=ref)
    try:
        rate = Decimal(request.POST.get("rate") or "")
    except InvalidOperation:
        messages.error(request, "The rate has to be a number.")
        return redirect("inventory:pouch", ref=ref)
    when = parse_date(request.POST.get("effective_from") or "") or timezone.localdate()
    try:
        services.add_price(request.user, obj, request.POST.get("kind"), rate, when)
        messages.success(request, "Price added.")
    except ServiceError as error:
        messages.error(request, error.messages[0])
    return redirect("inventory:pouch", ref=ref)


@login_required
@require_POST
def pouch_photos(request, ref):
    """Photos filed as ``{batch}-{pouchNo|X}-NN.jpg``, the prototype's naming."""
    obj = get_object_or_404(Pouch.objects.select_related("batch"), ref=ref)
    require(request.user, INV_MASTERS, "Only a role that edits inventory records can add photos.")
    uploads = request.FILES.getlist("photos")
    start = MediaAsset.objects.filter(scope="pouch", scope_id=str(obj.pk)).count()
    for number, upload in enumerate(uploads, start=start + 1):
        extension = os.path.splitext(upload.name)[1].lower() or ".jpg"
        upload.name = f"{obj.batch.code}-{obj.pouch_no or 'X'}-{number:02d}{extension}"
    saved, refused = attach_uploads(uploads, "pouch", obj.pk, request.user, kind=MediaKind.PHOTO)
    if saved:
        messages.success(request, f"{len(saved)} photo{'s' if len(saved) != 1 else ''} added.")
    if refused:
        messages.error(request, f"Not added: {', '.join(refused)}")
    return redirect("inventory:pouch", ref=ref)
