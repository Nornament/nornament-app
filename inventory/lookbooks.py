"""Lookbooks (part 5e): curated pouches a client sees by a private link, without a login.

Every write needs the sale right — the showroom builds them. Nothing here touches stock."""
import re
import secrets

from django.db import transaction
from django.db.models import Max

from accounts.capabilities import VIEW_SALE
from stock.services import ServiceError, log, require

from . import inputs, services
from .models import Lookbook, LookbookStone, Pouch

RIGHT = "Only a role that sees sale prices builds lookbooks."
#: NRN refs, or "batch · pouch no." — the separators people type between several
_SPLIT = re.compile(r"[,\n;]+")


def _by(user):
    return user if getattr(user, "is_authenticated", False) else None


def create(user, title):
    require(user, VIEW_SALE, RIGHT)
    title = (title or "").strip()
    if not title:
        raise ServiceError("Give the lookbook a title.")
    inputs.fits(Lookbook, title=title)
    book = Lookbook.objects.create(title=title, token=secrets.token_urlsafe(16), created_by=_by(user))
    log(user, "INSERT", "inv_lookbook", book.pk, title)
    return book


def update(user, book, title, note, shared):
    require(user, VIEW_SALE, RIGHT)
    title = (title or "").strip()
    if not title:
        raise ServiceError("Give the lookbook a title.")
    inputs.fits(Lookbook, title=title)
    book.title, book.note, book.shared = title, (note or "").strip(), bool(shared)
    book.save(update_fields=["title", "note", "shared", "updated_at"])
    return book


def _find(token):
    token = token.strip()
    if token.upper().startswith("NRN-"):
        return Pouch.objects.filter(ref__iexact=token).first()
    if "·" in token:
        batch, _, number = (part.strip() for part in token.partition("·"))
        return Pouch.objects.filter(batch__code__iexact=batch, pouch_no=number).first()
    return None


@transaction.atomic
def add_stones(user, book, text):
    """Each NRN ref or "batch · pouch no." in ``text`` joins the end, in the order typed.
    Returns (added, unknown, skipped): unknown as typed, skipped already in the lookbook."""
    require(user, VIEW_SALE, RIGHT)
    tokens = [t.strip() for chunk in _SPLIT.split(text or "") for t in
              (chunk.split() if "·" not in chunk else [chunk]) if t.strip()]
    have = set(book.stones.values_list("pouch_id", flat=True))
    position = (book.stones.aggregate(m=Max("position"))["m"] or 0)
    added, unknown, skipped = [], [], []
    for token in tokens:
        pouch = _find(token)
        if pouch is None:
            unknown.append(token)
        elif pouch.pk in have:
            skipped.append(pouch)
        else:
            position += 1
            LookbookStone.objects.create(lookbook=book, pouch=pouch, position=position)
            have.add(pouch.pk)
            added.append(pouch)
    book.save(update_fields=["updated_at"])
    return added, unknown, skipped


def _renumber(book):
    for i, stone in enumerate(book.stones.order_by("position", "pk"), start=1):
        if stone.position != i:
            stone.position = i
            stone.save(update_fields=["position"])


@transaction.atomic
def move(user, book, pouch_pk, step):
    require(user, VIEW_SALE, RIGHT)
    _renumber(book)
    stones = list(book.stones.order_by("position"))
    index = next((i for i, s in enumerate(stones) if s.pouch_id == pouch_pk), None)
    other = None if index is None else index + step
    if index is None or other is None or not 0 <= other < len(stones):
        return
    a, b = stones[index], stones[other]
    a.position, b.position = b.position, a.position
    a.save(update_fields=["position"])
    b.save(update_fields=["position"])
    book.save(update_fields=["updated_at"])


@transaction.atomic
def remove(user, book, pouch_pk):
    require(user, VIEW_SALE, RIGHT)
    book.stones.filter(pouch_id=pouch_pk).delete()
    _renumber(book)
    book.save(update_fields=["updated_at"])


def delete(user, book):
    require(user, VIEW_SALE, RIGHT)
    log(user, "DELETE", "inv_lookbook", book.pk, book.title)
    book.delete()


def resolve(token):
    return Lookbook.objects.filter(token=token, shared=True).first() if token else None


def pouches(book):
    """The lookbook's pouches, stocked (on_pcs, on_ct, rate, batch), in its order."""
    order = list(book.stones.order_by("position", "pk").values_list("pouch_id", flat=True))
    held = {p.pk: p for p in services.stocked(Pouch.objects.filter(pk__in=order))}
    return [held[pk] for pk in order if pk in held]
