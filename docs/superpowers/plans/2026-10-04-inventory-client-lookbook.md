# Inventory Client Lookbook (part 5e) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Staff build named lookbooks of stone pouches and share each by a private link that a client opens without a login, seeing only client-safe fields and photos, with Enquire by WhatsApp or email.

**Architecture:** Two models and a small service (`inventory/lookbooks.py`) for every write; staff screens in `inventory/views_lookbooks.py` under `/inventory/lookbooks/`; a public page and a token-scoped photo route in the same module, mounted at `/lookbook/` in `config/urls.py`, building rows with the client preview's own `rows.pouch_row(AnonymousUser(), pouch, client=True)`.

**Tech Stack:** Django 5.2, Postgres, pytest-django; server-rendered templates; `static/css/inventory.css` classes only (no new CSS).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-04-inventory-client-lookbook-design.md` — binding.
- Writes need `VIEW_SALE` (403); every internal role reads. Staff client view: every staff lookbook URL redirects to `inventory:shelf` first; the rail item stays padlocked there.
- Public URLs: `/lookbook/<token>/` (`lookbook_public`), `/lookbook/<token>/photo/<media_id>/` (`lookbook_photo`); no login; GET only; Off or unknown → the same 404 page "This lookbook is no longer shared."; `<meta name="robots" content="noindex">` and `X-Robots-Tag: noindex` on every public response.
- Public rows: `rows.pouch_row(AnonymousUser(), pouch, client=True)` on `services.stocked()` pouches — nothing in `rows.CLIENT_HIDDEN` or any gated key reaches the page. Shown: photo, stone name, colour, shape, cut, size, ct, pcs (or "uncountable"), "Ref NRN-…", Available / No longer available, Enquire.
- Enquire: WhatsApp `https://wa.me/<LOOKBOOK_WHATSAPP>?text=<urlencoded "Lookbook ‹title› — NRN-…">` when set, else `mailto:<LOOKBOOK_EMAIL>?subject=<same, urlencoded>`, else hidden.
- Token: `secrets.token_urlsafe(16)`, unique, set at creation.
- No stock or CRM coupling; no CSS; one migration (`0011_lookbook`).
- Tests: `POSTGRES_DB=<private> ../nornament-app/.venv/bin/pytest … -p no:warnings -q --junit-xml=<file>`; long suites in the background, polled until finished; never hand back mid-run. Known whole-suite failure: `stock/tests/test_import_commit.py::test_images_are_attached_in_chunks_and_are_resumable`.
- Commits end `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Models and the lookbook service

**Files:** Modify `inventory/models.py` (append); create `inventory/migrations/0011_lookbook.py` (generated), `inventory/lookbooks.py`, `inventory/tests/test_lookbooks.py`.

**Interfaces — Produces:**
- `Lookbook(title, note, token, shared, created_by, created_at, updated_at)`; `LookbookStone(lookbook, pouch, position)` with `related_name="stones"` on the lookbook FK, ordered by `position`.
- `lookbooks.create(user, title) -> Lookbook`
- `lookbooks.update(user, book, title, note, shared) -> Lookbook`
- `lookbooks.add_stones(user, book, text) -> (added: list[Pouch], unknown: list[str], skipped: list[Pouch])`
- `lookbooks.move(user, book, pouch_pk, step)` (`step` −1 up / +1 down; no-op at the ends)
- `lookbooks.remove(user, book, pouch_pk)`; `lookbooks.delete(user, book)`
- `lookbooks.resolve(token) -> Lookbook | None` (shared and matching, else None)
- `lookbooks.pouches(book) -> list[Pouch]` — stocked pouches in position order.

- [ ] **Step 1: Write the failing tests** — create `inventory/tests/test_lookbooks.py`:

```python
"""Part 5e: lookbooks — curated stones shared by a private link."""
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import lookbooks, services
from inventory.models import Lookbook, LookbookStone
from stock.services import ServiceError

pytestmark = pytest.mark.django_db


def _refs(book):
    return [s.pouch.ref for s in book.stones.select_related("pouch")]


def test_create_gives_a_long_random_token_and_shares_by_default(sales_user):
    book = lookbooks.create(sales_user, "Wedding greens")
    other = lookbooks.create(sales_user, "Reds")
    assert book.shared and len(book.token) >= 20 and book.token != other.token


def test_a_title_is_required(sales_user):
    with pytest.raises(ServiceError):
        lookbooks.create(sales_user, "  ")


def test_adding_by_ref_or_batch_and_pouch_no(sales_user, shelf):
    book = lookbooks.create(sales_user, "Greens")
    added, unknown, skipped = lookbooks.add_stones(
        sales_user, book, f"{shelf['onyx'].ref.lower()}, SL01G · 2\nNRN-999999\nSL01G · 77")
    assert [p.pk for p in added] == [shelf["onyx"].pk, shelf["ruby"].pk]
    assert unknown == ["NRN-999999", "SL01G · 77"] and skipped == []
    added, unknown, skipped = lookbooks.add_stones(sales_user, book, shelf["onyx"].ref)
    assert added == [] and [p.pk for p in skipped] == [shelf["onyx"].pk]
    assert _refs(book) == [shelf["onyx"].ref, shelf["ruby"].ref]


def test_moving_and_removing_keep_the_order_tidy(sales_user, shelf, admin_user_):
    jade = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "5", "stone_name": "Jade"}, pcs=1,
                               ct=Decimal("1"), rate=None)
    book = lookbooks.create(sales_user, "Greens")
    lookbooks.add_stones(sales_user, book, f"{shelf['onyx'].ref} {shelf['ruby'].ref} {jade.ref}")
    lookbooks.move(sales_user, book, jade.pk, -1)
    assert _refs(book) == [shelf["onyx"].ref, jade.ref, shelf["ruby"].ref]
    lookbooks.move(sales_user, book, shelf["onyx"].pk, -1)                   # already first: no-op
    lookbooks.remove(sales_user, book, jade.pk)
    assert _refs(book) == [shelf["onyx"].ref, shelf["ruby"].ref]
    assert [p.pk for p in lookbooks.pouches(book)] == [shelf["onyx"].pk, shelf["ruby"].pk]


def test_update_resolve_and_delete(sales_user, shelf):
    book = lookbooks.create(sales_user, "Greens")
    assert lookbooks.resolve(book.token) == book and lookbooks.resolve("nope") is None
    lookbooks.update(sales_user, book, "Greens for Mrs Rao", "Hand-picked", shared=False)
    book.refresh_from_db()
    assert (book.title, book.note, book.shared) == ("Greens for Mrs Rao", "Hand-picked", False)
    assert lookbooks.resolve(book.token) is None                             # off
    lookbooks.add_stones(sales_user, book, shelf["onyx"].ref)
    lookbooks.delete(sales_user, book)
    assert not Lookbook.objects.exists() and not LookbookStone.objects.exists()


def test_every_write_needs_the_sale_right(karigar_user, sales_user, shelf):
    book = lookbooks.create(sales_user, "Greens")
    for call in (lambda: lookbooks.create(karigar_user, "x"),
                 lambda: lookbooks.update(karigar_user, book, "x", "", True),
                 lambda: lookbooks.add_stones(karigar_user, book, shelf["onyx"].ref),
                 lambda: lookbooks.move(karigar_user, book, shelf["onyx"].pk, 1),
                 lambda: lookbooks.remove(karigar_user, book, shelf["onyx"].pk),
                 lambda: lookbooks.delete(karigar_user, book)):
        with pytest.raises(PermissionDenied):
            call()
```

- [ ] **Step 2: Run to verify failure** — `POSTGRES_DB=lb_t1 ../nornament-app/.venv/bin/pytest inventory/tests/test_lookbooks.py -p no:warnings -q` → ImportError.

- [ ] **Step 3: Models and migration** — append to `inventory/models.py`:

```python
class Lookbook(models.Model):
    """A curated set of pouches shared with a client by a private link (part 5e)."""

    title = models.CharField(max_length=120)
    note = models.TextField(blank=True, help_text="Shown to the client under the title.")
    token = models.CharField(max_length=32, unique=True, editable=False)
    shared = models.BooleanField(default=True, help_text="Off: the link answers as if it never existed.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inv_lookbook"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.title


class LookbookStone(models.Model):
    lookbook = models.ForeignKey(Lookbook, on_delete=models.CASCADE, related_name="stones")
    pouch = models.ForeignKey(Pouch, on_delete=models.PROTECT, related_name="+")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "inv_lookbook_stone"
        ordering = ["position", "pk"]
        constraints = [models.UniqueConstraint(fields=["lookbook", "pouch"], name="inv_lookbook_stone_once")]
```

Run `makemigrations inventory --name lookbook` (the number follows whatever 5d's last migration is; expect `0011_lookbook`).

- [ ] **Step 4: The service** — create `inventory/lookbooks.py`:

```python
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
```

The `add_stones` tokenizer: within a chunk without "·", whitespace also separates refs (so "NRN-1 NRN-2" works); a chunk with "·" is one batch · pouch no.

- [ ] **Step 5: Verify** — the test file passes; `makemigrations --check` clean; `inventory accounts` in the background, polled, 0 failures.

- [ ] **Step 6: Commit** — "Lookbooks: curated pouches with a private link, built by the showroom".

---

### Task 2: The staff screens

**Files:** Create `inventory/views_lookbooks.py` (staff views), `inventory/templates/inventory/lookbooks.html`, `inventory/templates/inventory/lookbook.html`, `inventory/templates/inventory/lookbook_add.html`; modify `inventory/urls.py`, `_rail.html` (Client lookbook line), `inventory/templates/inventory/pouch.html` (＋ Lookbook beside Split / Merge, inside the non-client branch, gated on `caps.view_sale`); create `inventory/tests/test_lookbook_views.py`; modify `inventory/tests/test_masking.py`; approved assertion rewrites: the two `'Client lookbook<span class="ct">🔒' in body` assertions in `test_finders_rail.py` (and any 5d test asserting it) now assert the rail links `inventory:lookbooks` in internal view — keep the client-view padlock assertion where one exists.

**Interfaces — Produces:** URL names `inventory:lookbooks` (`/inventory/lookbooks/`, GET list + POST create), `inventory:lookbook` (`/inventory/lookbooks/<pk>/`, GET + POST `action` ∈ save / add / up / down / remove / delete (+`confirm=delete`)), `inventory:lookbook_add` (`/inventory/pouches/<ref>/lookbook/`, GET form + POST `lookbook`).

- [ ] **Step 1: Failing tests** — `inventory/tests/test_lookbook_views.py`:

```python
"""Part 5e: the staff lookbook screens."""
import pytest
from django.urls import reverse

from inventory import lookbooks
from inventory.models import Lookbook

pytestmark = pytest.mark.django_db
LIST = reverse("inventory:lookbooks")


def _page(book):
    return reverse("inventory:lookbook", args=[book.pk])


def test_the_rail_opens_the_lookbooks(client, karigar_user, shelf):
    client.force_login(karigar_user)
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert f'href="{LIST}"' in body and 'Client lookbook<span class="ct">🔒' not in body
    assert client.get(LIST).status_code == 200 and "New lookbook" not in client.get(LIST).content.decode()


def test_create_add_reorder_remove_switch_and_delete(client, sales_user, shelf):
    client.force_login(sales_user)
    response = client.post(LIST, {"title": "Greens"})
    book = Lookbook.objects.get()
    assert response["Location"] == _page(book)
    client.post(_page(book), {"action": "add", "refs": f"{shelf['onyx'].ref}, {shelf['ruby'].ref}, NRN-999999"})
    body = client.get(_page(book)).content.decode()
    assert shelf["onyx"].ref in body and shelf["ruby"].ref in body and "NRN-999999" in body     # reported unknown
    assert book.token in body                                                                    # the link
    client.post(_page(book), {"action": "up", "pouch": shelf["ruby"].pk})
    assert [s.pouch_id for s in book.stones.all()] == [shelf["ruby"].pk, shelf["onyx"].pk]
    client.post(_page(book), {"action": "remove", "pouch": shelf["ruby"].pk})
    client.post(_page(book), {"action": "save", "title": "Greens", "note": "For you", "shared": ""})
    book.refresh_from_db()
    assert not book.shared and book.note == "For you" and book.stones.count() == 1
    first = client.post(_page(book), {"action": "delete"})
    assert first.status_code == 200 and Lookbook.objects.exists()                                # asks first
    client.post(_page(book), {"action": "delete", "confirm": "delete"})
    assert not Lookbook.objects.exists()


def test_adding_from_the_pouch_page(client, sales_user, shelf):
    book = lookbooks.create(sales_user, "Greens")
    client.force_login(sales_user)
    pouch_page = client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()
    url = reverse("inventory:lookbook_add", args=[shelf["onyx"].ref])
    assert f'href="{url}"' in pouch_page
    response = client.post(url, {"lookbook": book.pk})
    assert response["Location"] == _page(book) and book.stones.get().pouch_id == shelf["onyx"].pk


def test_rights_and_client_view(client, karigar_user, sales_user, admin_user_, shelf):
    book = lookbooks.create(sales_user, "Greens")
    client.force_login(karigar_user)
    assert client.post(LIST, {"title": "x"}).status_code == 403
    assert client.post(_page(book), {"action": "add", "refs": shelf["onyx"].ref}).status_code == 403
    assert f'href="{reverse("inventory:lookbook_add", args=[shelf["onyx"].ref])}"' not in \
        client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert 'Client lookbook<span class="ct">🔒' in body and LIST not in body
    for url in (LIST, _page(book), reverse("inventory:lookbook_add", args=[shelf["onyx"].ref])):
        response = client.get(url)
        assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf"), url
```

`test_masking.py`: add `LOOKBOOK_SCREENS = {"inventory:lookbooks", "inventory:lookbook", "inventory:lookbook_add"}` to `covered`, and a walk: for sales / karigar / production / graphic, every staff lookbook page with the onyx in a lookbook returns 200 (or 403 for `lookbook_add` POST-less GET by a login without the sale right — the GET form needs the right; assert 200 or 403) and never contains "7,919", the supplier name or `VALUE`.

- [ ] **Step 2: Verify failure** → `NoReverseMatch`.

- [ ] **Step 3: Implement** `inventory/views_lookbooks.py` (staff part):

```python
"""Lookbooks (part 5e): the staff screens, and the client's page a private link opens."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect

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
        book = get_object_or_404(Lookbook, pk=request.POST.get("lookbook") or 0)
        lookbooks.add_stones(request.user, book, pouch.ref)
        messages.success(request, f"{pouch.ref} is in {book.title}.")
        return redirect("inventory:lookbook", pk=book.pk)
    return _page(request, "inventory/lookbook_add.html", _everything(request), tab="lot", pouch_ref=pouch.ref,
                 pouch=pouch, books=Lookbook.objects.all())
```

(`from django.urls import reverse` with the other imports. A non-digit `lookbook` POST must 404, not 500 — guard with `.isdigit()` like `pouch_pk`.)

URLs in `inventory/urls.py`: `lookbooks/` → `lookbook_list` (`lookbooks`), `lookbooks/<int:pk>/` → `lookbook_detail` (`lookbook`), `pouches/<str:ref>/lookbook/` → `lookbook_add` (`lookbook_add`).

Rail (`_rail.html`, the Client lookbook line):
`{% if client_view %}<span class="locked"><span class="ic">◐</span>Client lookbook<span class="ct">🔒</span></span>{% else %}<a class="{% if tab == 'lookbooks' %}on{% endif %}" href="{% url 'inventory:lookbooks' %}"><span class="ic">◐</span>Client lookbook</a>{% endif %}`

Pouch page (inside the non-client `{% else %}` branch, after the Merge link):
`{% if caps.view_sale %}<a class="btn gho" href="{% url 'inventory:lookbook_add' row.ref %}">＋ Lookbook</a>{% endif %}`

Templates (stones shell; `.card`, `.led` table, `.btn`, `.chip`):
- `lookbooks.html`: shelfbar "Client lookbooks"; error banner; when `may`, a form (title + "＋ New lookbook"); a table — title (link), stones (`b.stones.count`), Link On/Off chip, last changed `b.updated_at|date:"d M Y"`; empty "No lookbooks yet.".
- `lookbook.html`: shelfbar title + On/Off chip; the link in a read-only `<input class="inp mono" id="lblink" value="{{ link }}" readonly>` and a `<button type="button" class="btn sm" onclick="navigator.clipboard.writeText(document.getElementById('lblink').value);this.textContent='Copied'">Copy link</button>`; when `may`: a save form (title, note textarea, "Link on" checkbox named `shared`, Save button value `save`), an add form (`refs` textarea, button value `add`, hint "NRN refs or batch · pouch no., separated by commas or new lines"); the stones table — position, ref, where (`batch · pouch no.`), stone, size, ct, Available chip (good) / No longer available chip (crit), and for `may` ↑ / ↓ / Remove buttons each in a tiny form posting `action` + `pouch`; a Delete button (`action=delete`), and when `confirming == "delete"` a banner "Delete this lookbook? Its link stops working." with a button `confirm=delete` + `action=delete`.
- `lookbook_add.html`: "Add {{ pouch.ref }} to a lookbook" — a select of lookbooks + Add; with none, "No lookbooks yet." and a link to the list.

- [ ] **Step 4: Verify** — the view tests, `test_masking.py`, `test_finders_rail.py` and any rewritten assertion pass; `inventory accounts` in the background, 0 failures.

- [ ] **Step 5: Commit** — "Lookbooks open from the rail: build one, add stones by reference or from a pouch, order them, share or stop sharing".

---

### Task 3: The client's page and its photos

**Files:** Modify `inventory/views_lookbooks.py` (public views), `config/urls.py` (mount), `config/settings.py` (two settings); create `inventory/templates/inventory/lookbook_public.html`, `inventory/templates/inventory/lookbook_gone.html`, `inventory/tests/test_lookbook_public.py`.

**Interfaces — Produces:** `lookbook_public` (`/lookbook/<str:token>/`), `lookbook_photo` (`/lookbook/<str:token>/photo/<int:media_id>/`), names in the root URLconf (no namespace).

- [ ] **Step 1: Failing tests** — `inventory/tests/test_lookbook_public.py`:

```python
"""Part 5e: what a client sees through a lookbook link — and everything they must not."""
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import lookbooks, services
from inventory.models import PriceEntry
from inventory.tests.conftest import SUPPLIER

pytestmark = pytest.mark.django_db


@pytest.fixture
def book(sales_user, admin_user_, shelf):
    services.add_price(admin_user_, shelf["onyx"], PriceEntry.LIST, Decimal("9500"), date(2026, 9, 1))
    b = lookbooks.create(sales_user, "Greens & golds")
    lookbooks.update(sales_user, b, "Greens & golds", "Picked for you", True)
    lookbooks.add_stones(sales_user, b, f"{shelf['onyx'].ref}, {shelf['ruby'].ref}")
    return b


def _get(client, book, **kw):
    return client.get(reverse("lookbook_public", args=[book.token]), **kw)


def test_no_login_and_only_client_safe_fields(client, book, shelf):
    response = _get(client, book)
    body = response.content.decode()
    assert response.status_code == 200 and response["X-Robots-Tag"] == "noindex" and 'content="noindex"' in body
    assert "Greens &amp; golds" in body and "Picked for you" in body
    assert shelf["onyx"].ref in body and "Green Onyx" in body and "12.50" in body and "Available" in body
    for secret in ("SL01G", "C-117", "keep away from light", "SL!2", "7,919", "9,500", SUPPLIER, "98,988"):
        assert secret not in body, secret


def test_an_empty_pouch_reads_no_longer_available(client, book, shelf, accounts_user, parties):
    from inventory import ledger_single
    from inventory.models import Movement

    ledger_single.post_single(accounts_user, shelf["ruby"], Movement.Reason.SALE, ct=Decimal("40"),
                              customer=parties["customer"])
    assert "No longer available" in _get(client, book).content.decode()


def test_off_and_unknown_links_answer_the_same(client, book, sales_user):
    unknown = client.get(reverse("lookbook_public", args=["not-a-token"]))
    lookbooks.update(sales_user, book, book.title, book.note, False)
    off = _get(client, book)
    assert unknown.status_code == off.status_code == 404
    assert "This lookbook is no longer shared." in off.content.decode()
    assert unknown.content == off.content


def test_enquire_by_whatsapp_else_email_else_hidden(client, book, shelf, settings):
    settings.LOOKBOOK_WHATSAPP, settings.LOOKBOOK_EMAIL = "919800000000", "hello@example.com"
    body = _get(client, book).content.decode()
    assert "https://wa.me/919800000000?text=Lookbook%20Greens%20%26%20golds%20%E2%80%94%20" + shelf["onyx"].ref in body
    settings.LOOKBOOK_WHATSAPP = ""
    assert "mailto:hello@example.com?subject=" in _get(client, book).content.decode()
    settings.LOOKBOOK_EMAIL = ""
    assert "Enquire" not in _get(client, book).content.decode()


def test_the_photo_route_serves_only_the_lookbooks_own_photos(client, book, shelf, sales_user):
    from mediahub.models import MediaAsset
    from stock.enums import MediaKind

    def photo(pouch, name):
        return MediaAsset.objects.create(media_ref=f"M-{name}", kind=MediaKind.PHOTO, storage_key=f"x/{name}.jpg",
                                         file_name=f"{name}.jpg", mime_type="image/jpeg", scope="pouch",
                                         scope_id=str(pouch.pk))

    mine = photo(shelf["onyx"], "a")
    url = reverse("lookbook_photo", args=[book.token, mine.pk])
    assert client.get(url).status_code in (302, 503)          # served (or storage not configured locally)
    body = _get(client, book).content.decode()
    assert url in body
    lookbooks.remove(sales_user, book, shelf["onyx"].pk)
    assert client.get(url).status_code == 404                  # no longer in the lookbook
    lookbooks.add_stones(sales_user, book, shelf["onyx"].ref)
    lookbooks.update(sales_user, book, book.title, book.note, False)
    assert client.get(url).status_code == 404                  # link off
```

- [ ] **Step 2: Verify failure** → `NoReverseMatch: 'lookbook_public'`.

- [ ] **Step 3: Implement** — in `config/settings.py` (beside the other `env(...)` reads): `LOOKBOOK_WHATSAPP = env("LOOKBOOK_WHATSAPP", "")`, `LOOKBOOK_EMAIL = env("LOOKBOOK_EMAIL", "")`.

In `config/urls.py`: `from inventory import views_lookbooks` and, before the catch-all `""` include,
`path("lookbook/<str:token>/", views_lookbooks.lookbook_public, name="lookbook_public"),`
`path("lookbook/<str:token>/photo/<int:media_id>/", views_lookbooks.lookbook_photo, name="lookbook_photo"),`

Append to `inventory/views_lookbooks.py`:

```python
import os
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.shortcuts import render
from django.views.decorators.http import require_GET

from mediahub import storage
from mediahub.models import MediaAsset
from stock.enums import MediaKind


def _noindex(response):
    response["X-Robots-Tag"] = "noindex"
    return response


def _gone(request):
    return _noindex(render(request, "inventory/lookbook_gone.html", status=404))


def _enquire(book, ref):
    text = quote(f"Lookbook {book.title} — {ref}")
    if settings.LOOKBOOK_WHATSAPP:
        return f"https://wa.me/{settings.LOOKBOOK_WHATSAPP}?text={text}"
    if settings.LOOKBOOK_EMAIL:
        return f"mailto:{settings.LOOKBOOK_EMAIL}?subject={text}"
    return ""


@require_GET
def lookbook_public(request, token):
    """What a client sees: the client preview's own row, for no one in particular, so nothing gated or
    filed survives (rows.CLIENT_HIDDEN, then every gated key masked away)."""
    book = lookbooks.resolve(token)
    if book is None:
        return _gone(request)
    pouches = lookbooks.pouches(book)
    found = rows.pouch_rows(AnonymousUser(), pouches, client=True)
    cards = [{**row, "available": bool(row.get("ct") or row.get("pcs")), "enquire": _enquire(book, row["ref"])}
             for row in found]
    return _noindex(render(request, "inventory/lookbook_public.html", {"book": book, "cards": cards}))


@require_GET
def lookbook_photo(request, token, media_id):
    book = lookbooks.resolve(token)
    asset = MediaAsset.objects.filter(pk=media_id, scope="pouch", kind=MediaKind.PHOTO, is_archived=False).first()
    if book is None or asset is None or not book.stones.filter(pouch_id=asset.scope_id).exists():
        return _gone(request)
    pouch = Pouch.objects.get(pk=asset.scope_id)
    extension = os.path.splitext(asset.file_name or "")[1].lower() or ".jpg"
    try:
        url = storage.presign_get(asset.storage_key, asset.mime_type, f"{pouch.ref}{extension}")
    except storage.StorageNotConfigured:
        return _noindex(render(request, "inventory/lookbook_gone.html", status=503))
    return _noindex(redirect(url))
```

`rows.pouch_rows` returns each row's `photo_id` (first photo) — confirm the key name in `rows.pouch_row` and that `photo_id` is not in `CLIENT_HIDDEN` (it is not: the client preview shows photos). Also confirm `ref` survives `client=True` (it does: the client sees the NRN ref).

Templates (standalone; `{% load static inventory_extras %}`; `<link rel="stylesheet" href="{% static 'css/inventory.css' %}">`; `<meta name="viewport" …>`; `<meta name="robots" content="noindex">`; `<title>{{ book.title }} · Nornament</title>`):
- `lookbook_public.html`: `<div class="wrap">`, a brand line "Nornament", `<h1>` title, note (`linebreaksbr`), then `<div class="colgrid">` of `<div class="colcard">`: a `.tile` with `<img class="photo" src="{% url 'lookbook_photo' book.token c.photo_id %}" alt="{{ c.stone_name }}" loading="lazy">` when `c.photo_id`, else `<span class="nophoto">no photo yet</span>`; stone name; colour · shape · cut; size (`c.size_display`); `{{ c.ct|ct }} ct`; `{% if c.countable %}{{ c.pcs|grouped }} pcs{% else %}uncountable{% endif %}`; "Ref {{ c.ref }}"; the Available / No longer available chip; `{% if c.enquire %}<a class="btn pri" href="{{ c.enquire }}" rel="noopener" target="_blank">Enquire</a>{% endif %}`. Empty: "Nothing here yet."
- `lookbook_gone.html`: the same head, "Nornament", and "This lookbook is no longer shared." — nothing else, identical for every 404.

- [ ] **Step 4: Verify** — `test_lookbook_public.py` passes; also `test_masking.py` (its walk enumerates only the `inventory` namespace, so the public routes don't need exemptions — confirm). Whole suite in the background, polled until finished: only the known S3 failure; `makemigrations --check` clean.

- [ ] **Step 5: Commit** — "A lookbook's private link shows a client its stones — client-safe fields, photos, Enquire — with no login".
