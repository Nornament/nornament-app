"""Lookbooks (part 5e): the staff screens, and the client's page a private link opens."""
import os
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AnonymousUser
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from accounts.capabilities import VIEW_SALE
from mediahub import storage
from mediahub.models import MediaAsset
from stock.enums import MediaKind
from stock.masking import mask
from stock.services import ServiceError, require

from . import lookbooks, rows
from .models import Lookbook, Pouch
from .views import _client, _everything, _page


def _staff_rows(user, book):
    pouches = lookbooks.pouches(book)
    photos = rows._photos([p.pk for p in pouches])
    return [mask(user, {"pk": p.pk, "ref": p.ref, "where": str(p), "stone_name": p.stone_name,
                        "size": p.size_text, "ct": p.on_ct, "available": bool(p.on_ct or p.on_pcs),
                        "photo_id": photos.get(p.pk)})
            for p in pouches]


@login_required
def lookbook_list(request):
    if _client(request):
        return redirect("inventory:shelf")
    error = None
    if request.method == "POST":
        try:
            book = lookbooks.create(request.user, request.POST.get("title"))
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            return redirect("inventory:lookbook", pk=book.pk)
    books = Lookbook.objects.annotate(n=Count("stones"))
    return _page(request, "inventory/lookbooks.html", _everything(request), tab="lookbooks", books=books,
                 error=error, may=request.user.has_perm(VIEW_SALE))


@login_required
def lookbook_detail(request, pk):
    if _client(request):
        return redirect("inventory:shelf")
    book = get_object_or_404(Lookbook, pk=pk)
    error = confirming = None
    if request.method == "POST":
        require(request.user, VIEW_SALE, lookbooks.RIGHT)
        action, p = request.POST.get("action"), request.POST
        pouch_pk = int(p["pouch"]) if (p.get("pouch") or "").isdecimal() else None
        try:
            if action == "add":
                added, unknown, skipped = lookbooks.add_stones(request.user, book, p.get("refs"))
                bits = [f"{len(added)} added"] + ([f"not found: {', '.join(unknown)}"] if unknown else []) \
                    + ([f"{len(skipped)} already here"] if skipped else [])
                (messages.warning if unknown else messages.success)(request, "; ".join(bits) + ".")
            elif action in ("up", "down") and pouch_pk:
                lookbooks.move(request.user, book, pouch_pk, -1 if action == "up" else 1)
            elif action == "remove" and pouch_pk:
                lookbooks.remove(request.user, book, pouch_pk)
            elif action == "save":
                lookbooks.update(request.user, book, p.get("title"), p.get("note"), bool(p.get("shared")))
                messages.success(request, "Saved.")
            elif action == "delete":
                if p.get("confirm") != "delete":
                    confirming = "delete"
                else:
                    lookbooks.delete(request.user, book)
                    messages.success(request, f"{book.title} deleted.")
                    return redirect("inventory:lookbooks")
        except ServiceError as refused:
            error = refused.messages[0]
        if not error and not confirming:
            return redirect("inventory:lookbook", pk=book.pk)
    link = request.build_absolute_uri(reverse("lookbook_public", args=[book.token]))
    return _page(request, "inventory/lookbook.html", _everything(request), tab="lookbooks", book=book,
                 stones=_staff_rows(request.user, book), link=link, error=error, confirming=confirming,
                 may=request.user.has_perm(VIEW_SALE))


@login_required
def lookbook_add(request, ref):
    if _client(request):
        return redirect("inventory:shelf")
    require(request.user, VIEW_SALE, lookbooks.RIGHT)
    pouch = get_object_or_404(Pouch, ref=ref)
    if request.method == "POST":
        lookbook_pk = request.POST.get("lookbook") or ""
        if not lookbook_pk.isdecimal():
            raise Http404
        book = get_object_or_404(Lookbook, pk=lookbook_pk)
        lookbooks.add_stones(request.user, book, pouch.ref)
        messages.success(request, f"{pouch.ref} is in {book.title}.")
        return redirect("inventory:lookbook", pk=book.pk)
    return _page(request, "inventory/lookbook_add.html", _everything(request), tab="lot", pouch_ref=pouch.ref,
                 pouch=pouch, books=Lookbook.objects.all())


# ── the client's page: no login, nothing gated or filed, the same 404 for off and unknown.
def _noindex(response):
    response["X-Robots-Tag"] = "noindex"
    return response


def _gone(request, status=404, message=None):
    return _noindex(render(request, "inventory/lookbook_gone.html", {"message": message}, status=status))


def _enquire(book, ref):
    text = quote(f"Lookbook {book.title} — {ref}")
    if settings.LOOKBOOK_WHATSAPP:
        return f"https://wa.me/{settings.LOOKBOOK_WHATSAPP}?text={text}"
    if settings.LOOKBOOK_EMAIL:
        return f"mailto:{settings.LOOKBOOK_EMAIL}?subject={text}"
    return ""


#: what a public card may carry, plus "available" and "enquire" computed below — nothing else rides along
_CARD_KEYS = ("ref", "stone_name", "colour", "shape", "cut", "size_display", "ct", "pcs", "countable", "photo_id")


@never_cache
@require_safe
def lookbook_public(request, token):
    """What a client sees: the client preview's own row, for no one in particular, so nothing gated or
    filed survives (rows.CLIENT_HIDDEN, every gated key masked away, then only the allow-listed keys kept)."""
    book = lookbooks.resolve(token)
    if book is None:
        return _gone(request)
    pouches = lookbooks.pouches(book)
    found = rows.pouch_rows(AnonymousUser(), pouches, client=True)
    cards = [{**{key: row[key] for key in _CARD_KEYS}, "available": bool(row.get("ct") or row.get("pcs")),
              "enquire": _enquire(book, row["ref"])} for row in found]
    return _noindex(render(request, "inventory/lookbook_public.html", {"book": book, "cards": cards}))


@never_cache
@require_safe
def lookbook_photo(request, token, media_id):
    """Only the photo the page shows for a pouch in this lookbook — its first by rank, via rows._photos,
    not any photo stepped to by id."""
    book = lookbooks.resolve(token)
    if book is None:
        return _gone(request)
    asset = MediaAsset.objects.filter(pk=media_id, scope="pouch", kind=MediaKind.PHOTO, is_archived=False).first()
    if asset is None:
        return _gone(request)
    pouch_pk = int(asset.scope_id)
    if not book.stones.filter(pouch_id=pouch_pk).exists() or rows._photos([pouch_pk]).get(pouch_pk) != asset.pk:
        return _gone(request)
    pouch = Pouch.objects.get(pk=pouch_pk)
    extension = os.path.splitext(asset.file_name or "")[1].lower() or ".jpg"
    try:
        url = storage.presign_get(asset.storage_key, asset.mime_type, f"{pouch.ref}{extension}")
    except storage.StorageNotConfigured:
        return _gone(request, status=503, message="Photos are unavailable right now.")
    return _noindex(redirect(url))
