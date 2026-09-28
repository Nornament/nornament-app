"""The inventory screens. Thin: services write, rows mask, templates draw."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import rows, services
from .models import Batch, BoxColour, CodePart

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
