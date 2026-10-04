"""Lookbooks (part 5e): the staff screens, and the client's page a private link opens."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from accounts.capabilities import VIEW_SALE
from stock.masking import mask
from stock.services import ServiceError, require

from . import lookbooks, rows
from .models import Lookbook, Pouch
from .views import _client, _everything, _page


def _staff_rows(user, book):
    return [mask(user, {"pk": p.pk, "ref": p.ref, "where": str(p), "stone_name": p.stone_name,
                        "size": p.size_text, "ct": p.on_ct, "available": bool(p.on_ct or p.on_pcs)})
            for p in lookbooks.pouches(book)]


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
    books = Lookbook.objects.all()
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
        pouch_pk = int(p["pouch"]) if (p.get("pouch") or "").isdigit() else None
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
        if not lookbook_pk.isdigit():
            raise Http404
        book = get_object_or_404(Lookbook, pk=lookbook_pk)
        lookbooks.add_stones(request.user, book, pouch.ref)
        messages.success(request, f"{pouch.ref} is in {book.title}.")
        return redirect("inventory:lookbook", pk=book.pk)
    return _page(request, "inventory/lookbook_add.html", _everything(request), tab="lot", pouch_ref=pouch.ref,
                 pouch=pouch, books=Lookbook.objects.all())


# ── the client's page (part 5e, task 3): placeholder so `lookbook_detail`'s link field has a URL name to
# reverse right now. Task 3 replaces this with the real public page, its photo route, and the url mount
# in config/urls.py below.
def lookbook_public(request, token):
    raise Http404


def lookbook_photo(request, token, media_id):
    raise Http404
