# Inventory Price Lists (part 5b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unlock the stones rail's **Price list — cost** and **Price list — selling**: a filtered, paged pouch table per mode, and one per-carat price set for a whole filtered group.

**Architecture:** One service (`services.set_group_price`) writes one dated `PriceEntry` per pouch in a single transaction. One view module (`views_prices.py`) serves both modes from the same filters, rows and template; the POST reuses the GET's filters. No new tables, no migration, no change to `stock/`.

**Tech Stack:** Django 5.2, Postgres, pytest-django. Server-rendered templates in the stones shell (`templates/inventory_base.html`, `static/css/inventory.css` — no new CSS).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-02-inventory-price-lists-design.md` — binding.
- URLs: `/inventory/prices/cost/` named `inventory:prices_cost`; `/inventory/prices/selling/` named `inventory:prices_selling`.
- Open the cost list: `view_cost`. Open the selling list: `view_sale`. Set by group: `inv_masters` + that same right. Without the right to open: `require()` → 403.
- Client view: both URLs redirect to `inventory:shelf` before reading anything; the rail shows **Price list — selling** padlocked and **Price list — cost** not at all (as today).
- Masking: every row goes through `stock.masking.mask()`; templates test key presence. Keys: `purchase_rate`, `valuation_rate`, `pouch_value` (view_cost), `list_rate` (view_sale), `margin` (view_margin). `list_value` is computed after masking, only when `list_rate` survived. `stock/masking.py` is not touched.
- Margin = `(list − valuation) / valuation × 100`, shown with one decimal and `%`; blank when either rate is missing, valuation is zero, or the viewer lacks `view_cost`.
- 200 rows a page; the group set acts on every pouch the filters match, all pages.
- Group set refuses: kind other than valuation / list; rate not a finite number > 0 and < 10¹⁰; a future effective date; an empty group; a posted count that differs from the rebuilt count. Each refusal writes nothing.
- One activity-log entry per group set. Existing `add_price` and the pouch price card unchanged.
- Diamonds: each list's header links "Diamonds price by the rate card →" to `inventory:dia_settings` + `#rates`. Nothing on the diamond side changes.
- No new tables, no migrations, no CSS, no new stock/CRM coupling.
- Tests: `POSTGRES_DB=<private name> .venv/bin/pytest inventory accounts -p no:warnings -q` (from the repo root; the venv is `../nornament-app/.venv` in a worktree). `pytest -q` prints no summary — use `--junit-xml=<file>` for counts. Known unrelated failure: `stock/tests/test_import_commit.py::test_images_are_attached_in_chunks_and_are_resumable`.
- Commit messages: plain English, ending with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

---

## File structure

- Modify `inventory/services.py` — add `set_group_price` beside `add_price`.
- Create `inventory/views_prices.py` — filters, rows, totals, GET and POST for both modes.
- Create `inventory/templates/inventory/prices.html` — both modes.
- Modify `inventory/urls.py` — two paths.
- Modify `inventory/templates/inventory/_rail.html` — the two Commercial items go live by right.
- Create `inventory/tests/test_price_lists.py` — service, view and rail tests.
- Modify `inventory/tests/test_masking.py` — walk the two new URLs.

---

### Task 1: `set_group_price` service

**Files:**
- Modify: `inventory/services.py` (after `add_price`, ~line 126)
- Test: `inventory/tests/test_price_lists.py` (create)

**Interfaces:**
- Consumes: `PriceEntry`, `_by`, `log`, `require`, `ServiceError`, `INV_MASTERS`, `VIEW_COST`, `VIEW_SALE` — all already imported in `services.py`.
- Produces: `services.set_group_price(user, pouches, kind, rate, effective_from, described="") -> int` — the number of pouches priced. `pouches` is any iterable of `Pouch`; `kind` is `PriceEntry.VALUATION` or `PriceEntry.LIST`; `rate` a `Decimal` or `None`; `effective_from` a `date`. Raises `PermissionDenied` (from `require`) without the rights, `ServiceError` for every other refusal.

- [ ] **Step 1: Write the failing tests**

Create `inventory/tests/test_price_lists.py`:

```python
"""Part 5b: the two price lists and setting one price for a whole group."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from inventory import services
from inventory.models import Pouch, PriceEntry
from stock.models import ActivityLog
from stock.services import ServiceError

pytestmark = pytest.mark.django_db


def _group():
    return list(Pouch.objects.order_by("pk"))


def test_a_group_set_writes_one_dated_row_per_pouch_and_one_log(accounts_user, shelf):
    before = PriceEntry.objects.count()
    logs = ActivityLog.objects.count()
    when = timezone.localdate() - timedelta(days=1)
    n = services.set_group_price(accounts_user, _group(), PriceEntry.LIST, Decimal("1250"), when, described="stone=onyx")
    assert n == 2
    made = PriceEntry.objects.filter(kind=PriceEntry.LIST)
    assert PriceEntry.objects.count() == before + 2 and made.count() == 2
    assert {e.pouch_id for e in made} == {shelf["onyx"].pk, shelf["ruby"].pk}
    assert all(e.rate == Decimal("1250") and e.effective_from == when and e.set_by == accounts_user for e in made)
    assert ActivityLog.objects.count() == logs + 1
    assert ActivityLog.objects.latest("pk").detail == "list 1250/ct on 2 pouches (stone=onyx)"
    assert services.latest_price(shelf["onyx"], PriceEntry.LIST).rate == Decimal("1250")


def test_a_valuation_set_becomes_the_rate_on_file_and_nothing_is_overwritten(accounts_user, shelf):
    services.set_group_price(accounts_user, [shelf["onyx"]], PriceEntry.VALUATION, Decimal("8000"), timezone.localdate())
    onyx = services.stocked(Pouch.objects.filter(pk=shelf["onyx"].pk)).get()
    assert onyx.rate == Decimal("8000")
    assert shelf["onyx"].prices.filter(kind=PriceEntry.VALUATION).count() == 2      # the opening 7,919 is kept


@pytest.mark.parametrize("rate", [None, Decimal("0"), Decimal("-5"), Decimal("1e10"), Decimal("NaN"), Decimal("Infinity")])
def test_a_bad_rate_writes_nothing(accounts_user, shelf, rate):
    before = PriceEntry.objects.count()
    with pytest.raises(ServiceError):
        services.set_group_price(accounts_user, _group(), PriceEntry.LIST, rate, timezone.localdate())
    assert PriceEntry.objects.count() == before


def test_a_future_date_an_empty_group_and_a_purchase_kind_are_refused(accounts_user, shelf):
    before = PriceEntry.objects.count()
    tomorrow = timezone.localdate() + timedelta(days=1)
    with pytest.raises(ServiceError, match="future"):
        services.set_group_price(accounts_user, _group(), PriceEntry.LIST, Decimal("10"), tomorrow)
    with pytest.raises(ServiceError, match="No pouch matches these filters."):
        services.set_group_price(accounts_user, [], PriceEntry.LIST, Decimal("10"), timezone.localdate())
    with pytest.raises(ServiceError, match="purchase"):
        services.set_group_price(accounts_user, _group(), PriceEntry.PURCHASE, Decimal("10"), timezone.localdate())
    assert PriceEntry.objects.count() == before


def test_each_kind_needs_inv_masters_and_its_own_right(sales_user, production_user, shelf):
    before = PriceEntry.objects.count()
    today = timezone.localdate()
    with pytest.raises(PermissionDenied):          # Sales sees list prices but does not edit records
        services.set_group_price(sales_user, _group(), PriceEntry.LIST, Decimal("10"), today)
    with pytest.raises(PermissionDenied):
        services.set_group_price(production_user, _group(), PriceEntry.VALUATION, Decimal("10"), today)
    assert PriceEntry.objects.count() == before
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=pl_t1 ../nornament-app/.venv/bin/pytest inventory/tests/test_price_lists.py -p no:warnings -q`
Expected: FAIL — `AttributeError: module 'inventory.services' has no attribute 'set_group_price'`.

- [ ] **Step 3: Implement**

In `inventory/services.py`, directly after `add_price`:

```python
#: what a group set may write: purchase prices come only from purchases
GROUP_KINDS = (PriceEntry.VALUATION, PriceEntry.LIST)


@transaction.atomic
def set_group_price(user, pouches, kind, rate, effective_from, described=""):
    """One dated price per pouch in a filtered group. Nothing is overwritten: each pouch gets its own row."""
    if kind not in GROUP_KINDS:
        raise ServiceError("A group sets a valuation or a list price; purchase prices come from purchases.")
    require(user, INV_MASTERS, "Only a role that edits inventory records can set a price.")
    require(user, VIEW_SALE if kind == PriceEntry.LIST else VIEW_COST, "A price you may not see is not yours to set.")
    # zero is refused here, unlike one pouch: a whole group at zero is a slip
    if rate is None or not rate.is_finite() or rate <= 0 or rate >= 10 ** 10:
        raise ServiceError("The rate has to be a number above zero, at most ten digits before the point.")
    if effective_from > timezone.localdate():
        raise ServiceError("A price cannot take effect in the future: the newest one is the current one.")
    pouches = list(pouches)
    if not pouches:
        raise ServiceError("No pouch matches these filters.")
    by = _by(user)
    entries = PriceEntry.objects.bulk_create([
        PriceEntry(pouch=pouch, kind=kind, rate=rate, effective_from=effective_from, set_by=by) for pouch in pouches
    ])
    detail = f"{kind} {rate}/ct on {len(pouches)} pouch{'es' if len(pouches) != 1 else ''}"
    log(user, "INSERT", "inv_price", entries[0].pk, f"{detail} ({described})" if described else detail)
    return len(pouches)
```

- [ ] **Step 4: Run them to verify they pass**

Run: `POSTGRES_DB=pl_t1 ../nornament-app/.venv/bin/pytest inventory/tests/test_price_lists.py -p no:warnings -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add inventory/services.py inventory/tests/test_price_lists.py
git commit -m "A valuation or list price can be set for a whole group of pouches, one dated row each

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The two price lists (read side), rail and masking walk

**Files:**
- Create: `inventory/views_prices.py`
- Create: `inventory/templates/inventory/prices.html`
- Modify: `inventory/urls.py` (import list and two paths after `transfers`)
- Modify: `inventory/templates/inventory/_rail.html:30-31` (the two Commercial price items)
- Modify: `inventory/tests/test_masking.py` (`PRICE_SCREENS`, covered set, two tests)
- Test: `inventory/tests/test_price_lists.py` (append)

**Interfaces:**
- Consumes: `services.stocked()`, `services.value_of(pouch)`, `views._client`, `views._everything`, `views._page`, `stock.masking.mask/allowed`, `stock.services.require`.
- Produces (Task 3 uses these): in `views_prices.py` — `MODES` dict `mode -> (right, kind, title)`; `FIELDS` tuple of filter names; `_filters(data) -> dict`; `_query(f) -> str` (url-encoded, always with `f=1`); `_pouches(f) -> QuerySet` (filtered, annotated); `prices(request, mode)` view handling GET (POST added in Task 3). Template context `posted` (list of `(name, value)` filter pairs), `count`, `can_set`, `today`.

- [ ] **Step 1: Write the failing tests**

Append to `inventory/tests/test_price_lists.py` — the `import` lines go to the top of the file with the others, the rest at the end:

```python
from django.urls import reverse

from inventory import views_prices
from inventory.tests.conftest import VALUE

COST, SELLING = reverse("inventory:prices_cost"), reverse("inventory:prices_selling")


@pytest.fixture
def priced(admin_user_, shelf):
    """The shelf with a purchase price and a list price on the onyx, and an empty jade pouch."""
    services.add_price(admin_user_, shelf["onyx"], PriceEntry.PURCHASE, Decimal("6000"), date(2026, 8, 7))
    services.add_price(admin_user_, shelf["onyx"], PriceEntry.LIST, Decimal("9500"), date(2026, 9, 1))
    jade = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "9", "stone_name": "Jade", "colour": "Green"},
                               pcs=0, ct=Decimal("0"), rate=None)
    return {**shelf, "jade": jade}


def _get(client, user, url, **params):
    client.force_login(user)
    return client.get(url, params)


def test_the_cost_list_shows_purchase_valuation_and_value_with_a_total(client, accounts_user, priced):
    body = _get(client, accounts_user, COST).content.decode()
    assert priced["onyx"].ref in body and priced["ruby"].ref in body
    assert "₹6,000" in body and "₹7,919" in body and VALUE in body
    assert "1,00,988" in body                                          # 98,987.5 + 2,000
    assert f'href="{reverse("inventory:dia_settings")}#rates"' in body and "Diamonds price by the rate card →" in body
    assert 'class="on" href="' + COST + '"' in body


def test_the_selling_list_shows_list_price_value_and_margin(client, accounts_user, priced):
    body = _get(client, accounts_user, SELLING).content.decode()
    assert "₹9,500" in body and "₹1,18,750" in body                   # 12.5 ct × ₹9,500
    assert "20.0%" in body                                             # (9,500 − 7,919) / 7,919
    assert "<th class=\"r\">Margin</th>" in body


def test_sales_sees_list_prices_but_no_cost_or_margin_and_no_cost_list(client, sales_user, priced):
    body = _get(client, sales_user, SELLING).content.decode()
    assert "₹9,500" in body and "₹1,18,750" in body
    for secret in ("7,919", VALUE, "6,000", "20.0%", "Margin</th>"):
        assert secret not in body, secret
    assert _get(client, sales_user, COST).status_code == 403


@pytest.mark.parametrize("fixture", ["karigar_user", "graphic_user", "production_user"])
def test_a_login_without_the_right_is_refused_both(client, request, priced, fixture):
    user = request.getfixturevalue(fixture)
    assert _get(client, user, COST).status_code == 403
    assert _get(client, user, SELLING).status_code == 403


def test_the_filters_narrow_the_list(client, accounts_user, priced):
    def refs(**params):
        body = _get(client, accounts_user, COST, **params).content.decode()
        return {name for name in ("onyx", "ruby", "jade") if priced[name].ref in body}

    assert refs() == {"onyx", "ruby"}                                  # in stock only, by default
    assert refs(f="1") == {"onyx", "ruby", "jade"}                     # the box unticked: every pouch
    assert refs(stone="ONYX") == {"onyx"}
    assert refs(colour="Red") == {"ruby"}
    assert refs(shape="Oval") == {"onyx"} and refs(quality="A") == {"ruby"} and refs(size_text="14*10") == {"onyx"}
    assert refs(batch="sl0") == {"onyx", "ruby"} and refs(batch="XX") == set()
    assert refs(box="G") == {"onyx", "ruby"}


def test_paging_keeps_the_filters(client, accounts_user, priced, monkeypatch):
    monkeypatch.setattr(views_prices, "PAGE", 1)
    first = _get(client, accounts_user, COST, f="1", batch="SL").content.decode()
    assert "Page 1 of 3" in first and "?f=1&amp;batch=SL&amp;stock=1&amp;page=2" not in first
    assert "?f=1&amp;batch=SL&amp;page=2" in first                    # the box unticked stays unticked
    second = _get(client, accounts_user, COST, f="1", batch="SL", page="2").content.decode()
    assert "Page 2 of 3" in second


def test_the_rail_opens_each_list_by_right(client, accounts_user, sales_user, karigar_user, priced):
    body = _get(client, accounts_user, reverse("inventory:shelf")).content.decode()
    assert f'href="{COST}"' in body and f'href="{SELLING}"' in body
    body = _get(client, sales_user, reverse("inventory:shelf")).content.decode()
    assert f'href="{COST}"' not in body and "Price list — cost<span class=\"ct\">🔒" in body
    assert f'href="{SELLING}"' in body
    body = _get(client, karigar_user, reverse("inventory:shelf")).content.decode()
    assert "Price list — selling<span class=\"ct\">🔒" in body and f'href="{SELLING}"' not in body


def test_client_view_padlocks_both_and_redirects_both(client, admin_user_, priced):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert COST not in body and SELLING not in body and "Price list — cost" not in body
    assert "Price list — selling<span class=\"ct\">🔒" in body
    for url in (COST, SELLING):
        response = client.get(url)
        assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf"), url
```

In `inventory/tests/test_masking.py`, add after `FINDER_SCREENS` is defined (search the file for `FINDER_SCREENS =`):

```python
#: part 5b's price lists, walked by test_no_price_list_shows_a_login_what_it_may_not_see
PRICE_SCREENS = {"inventory:prices_cost", "inventory:prices_selling"}


@pytest.mark.parametrize("fixture, secrets", [
    ("sales_user", ("7,919", VALUE, TOTAL_VALUE, SUPPLIER)),
    ("karigar_user", ("7,919", VALUE, TOTAL_VALUE, SUPPLIER)),
    ("production_user", ("7,919", VALUE, TOTAL_VALUE)),
    ("graphic_user", ("7,919", VALUE, TOTAL_VALUE, SUPPLIER)),
])
def test_no_price_list_shows_a_login_what_it_may_not_see(client, shelf, request, fixture, secrets):
    client.force_login(request.getfixturevalue(fixture))
    for name in sorted(PRICE_SCREENS):
        for query in ("", "?f=1"):
            response = client.get(reverse(name) + query)
            assert response.status_code in (200, 403), f"{name} returned {response.status_code}"
            body = response.content.decode()
            for secret in secrets:
                assert secret not in body, f"{name}{query} leaked {secret!r} to {fixture}"


def test_the_cost_list_shows_cost_to_accounts(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:prices_cost")).content.decode()
    assert "7,919" in body and VALUE in body and TOTAL_VALUE in body
```

and in `test_every_inventory_screen_is_walked`, extend the `covered` union with `| PRICE_SCREENS` (the names are defined at module level, so the order of definitions in the file does not matter at call time).

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=pl_t2 ../nornament-app/.venv/bin/pytest inventory/tests/test_price_lists.py inventory/tests/test_masking.py -p no:warnings -q`
Expected: FAIL — `NoReverseMatch` for `inventory:prices_cost` (collection error in `test_price_lists.py`).

- [ ] **Step 3: Implement the view**

Create `inventory/views_prices.py`:

```python
"""The two price lists: every pouch's cost or selling price, filtered, and one price set for a whole group.

The prototype only explains them (cost and selling are different numbers with different owners, kept
as dated rows); the rows are ``PriceEntry``, the same ones each pouch's price card shows. Stones only:
diamonds price by the rate card in diamond Settings.
"""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import OuterRef, Q, Subquery
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.http import urlencode

from accounts.capabilities import INV_MASTERS, VIEW_COST, VIEW_SALE
from stock.masking import allowed, mask
from stock.services import require

from . import services
from .models import BoxColour, Pouch, PriceEntry
from .views import _client, _everything, _page

PAGE = 200
#: mode -> (the right to open it, the kind of price it sets, its title)
MODES = {
    "cost": (VIEW_COST, PriceEntry.VALUATION, "Price list — cost"),
    "selling": (VIEW_SALE, PriceEntry.LIST, "Price list — selling"),
}
#: the exact-match selects, as (field, label)
CHOICES = (("colour", "Colour"), ("shape", "Shape"), ("quality", "Quality"), ("size_text", "Size"))
FIELDS = ("stone", *(key for key, _ in CHOICES), "batch", "box")


def _filters(data):
    """The filters a GET or a POST carries. ``f`` marks a submitted form, so an unticked
    "in stock only" stays unticked; with no form yet it is on."""
    f = {key: (data.get(key) or "").strip() for key in FIELDS}
    f["stock"] = "1" if data.get("stock") or not data.get("f") else ""
    return f


def _query(f):
    return urlencode({"f": "1", **{key: value for key, value in f.items() if value}})


def _latest(kind, field="rate"):
    return Subquery(PriceEntry.objects.filter(pouch=OuterRef("pk"), kind=kind)
                    .order_by("-effective_from", "-pk").values(field)[:1])


def _pouches(f):
    pouches = services.stocked().annotate(
        valuation_from=_latest(PriceEntry.VALUATION, "effective_from"),
        purchase_rate=_latest(PriceEntry.PURCHASE),
        list_rate=_latest(PriceEntry.LIST), list_from=_latest(PriceEntry.LIST, "effective_from"),
    )
    if f["stone"]:
        pouches = pouches.filter(stone_name__icontains=f["stone"])
    for key, _ in CHOICES:
        if f[key]:
            pouches = pouches.filter(**{key: f[key]})
    if f["batch"]:
        pouches = pouches.filter(batch__code__istartswith=f["batch"])
    if f["box"]:
        pouches = pouches.filter(batch__box_colour_id=f["box"])
    if f["stock"]:
        pouches = pouches.filter(Q(on_ct__gt=0) | Q(on_pcs__gt=0))
    return pouches


def _margin(listed, valuation):
    if listed is None or not valuation:
        return None
    return (listed - valuation) / valuation * 100


def _row(user, pouch):
    row = mask(user, {
        "ref": pouch.ref, "batch_code": pouch.batch.code, "pouch_no": pouch.pouch_no or "",
        "stone_name": pouch.stone_name, "size_text": pouch.size_text, "ct": pouch.on_ct,
        "purchase_rate": pouch.purchase_rate, "valuation_rate": pouch.rate, "valuation_from": pouch.valuation_from,
        "pouch_value": services.value_of(pouch), "list_rate": pouch.list_rate, "list_from": pouch.list_from,
        # a margin reads the valuation, so it is never worked out for a login that may not see one
        "margin": _margin(pouch.list_rate, pouch.rate) if allowed(user, "valuation_rate") else None,
    })
    if "list_rate" in row:
        row["list_value"] = None if row["list_rate"] is None or row["ct"] is None else row["ct"] * row["list_rate"]
    return row


def _choices(f):
    """Each select's values: the distinct non-blank ones across every pouch, and the box colours."""
    out = []
    for key, label in CHOICES:
        values = Pouch.objects.exclude(**{key: ""}).order_by(key).values_list(key, flat=True).distinct()
        out.append((key, label, [(value, value, value == f[key]) for value in values]))
    out.append(("box", "Box colour", [(b.code, f"{b.code} · {b.label}", b.code == f["box"])
                                      for b in BoxColour.objects.all()]))
    return out


@login_required
def prices(request, mode):
    if _client(request):
        return redirect("inventory:shelf")
    right, kind, title = MODES[mode]
    require(request.user, right, "This price list needs the right to see its prices.")
    f = _filters(request.GET)
    rows = [_row(request.user, pouch) for pouch in _pouches(f)]
    money = "pouch_value" if mode == "cost" else "list_value"
    total = sum((r[money] for r in rows if r.get(money) is not None), start=0) if rows else None
    query = _query(f)
    return _page(
        request, "inventory/prices.html", _everything(request), tab=f"prices_{mode}", mode=mode, title=title,
        page=Paginator(rows, PAGE).get_page(request.GET.get("page")), count=len(rows), total=total,
        filters=f, choices=_choices(f), query=query, posted=[(k, v) for k, v in [("f", "1"), *f.items()] if v],
        margin=mode == "selling" and allowed(request.user, "margin"),
        can_set=request.user.has_perm(INV_MASTERS) and request.user.has_perm(right),
        set_label="valuation" if kind == PriceEntry.VALUATION else "list price", today=timezone.localdate(),
    )
```

- [ ] **Step 4: Implement the template**

Create `inventory/templates/inventory/prices.html`:

```html
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}{{ title }}{% endblock %}
{% block crumb %}Commercial &nbsp;›&nbsp; <b>{{ title }}</b>{% endblock %}
{% block content %}
<div class="shelfbar"><h1>{{ title }}</h1><span class="chip">{{ count|grouped }} pouch{{ count|pluralize:"es" }}</span>
  <span class="spacer"></span><a class="hint" href="{% url 'inventory:dia_settings' %}#rates">Diamonds price by the rate card →</a></div>

<form method="get" class="card" style="margin-bottom:14px"><div class="card-b ctrow">
  <input type="hidden" name="f" value="1">
  <input class="inp" name="stone" value="{{ filters.stone }}" placeholder="Stone" style="width:150px">
  {% for key, label, options in choices %}<select class="inp" name="{{ key }}" style="width:140px" aria-label="{{ label }}">
    <option value="">{{ label }}: any</option>{% for value, text, on in options %}<option value="{{ value }}"{% if on %} selected{% endif %}>{{ text }}</option>{% endfor %}</select>{% endfor %}
  <input class="inp mono" name="batch" value="{{ filters.batch }}" placeholder="Batch" style="width:100px">
  <label class="hint"><input type="checkbox" name="stock" value="1"{% if filters.stock %} checked{% endif %}> In stock only</label>
  <button class="btn">Filter</button> <a class="hint" href="?">Clear</a>
</div></form>

<div class="card" style="overflow:hidden"><div style="overflow:auto"><table class="pt">
  <thead><tr><th>Pouch</th><th>Stone</th><th>Size</th><th class="r">Ct on hand</th>
    {% if mode == 'cost' %}<th class="r">Purchase /ct</th><th class="r">Valuation /ct</th><th class="r">Value</th>
    {% else %}<th class="r">List /ct</th><th class="r">List value</th>{% if margin %}<th class="r">Margin</th>{% endif %}{% endif %}</tr></thead>
  <tbody>{% for p in page %}<tr>
    <td><a class="rowlink mono" href="{% url 'inventory:pouch' p.ref %}">{{ p.ref }}</a>
      <span class="hint mono">{{ p.batch_code }} · {{ p.pouch_no|default:"?" }}</span></td>
    <td>{{ p.stone_name }}</td><td class="mono">{{ p.size_text|default:"—" }}</td><td class="r">{{ p.ct|ct }}</td>
    {% if mode == 'cost' %}
      <td class="r">{% if 'purchase_rate' in p %}{{ p.purchase_rate|rupees }}{% endif %}</td>
      <td class="r">{% if 'valuation_rate' in p %}{{ p.valuation_rate|rupees }}{% if p.valuation_rate is not None and p.valuation_from %} <span class="hint">{{ p.valuation_from|date:"j M Y" }}</span>{% endif %}{% endif %}</td>
      <td class="r"><b>{% if 'pouch_value' in p %}{{ p.pouch_value|rupees }}{% endif %}</b></td>
    {% else %}
      <td class="r">{% if 'list_rate' in p %}{{ p.list_rate|rupees }}{% if p.list_from %} <span class="hint">{{ p.list_from|date:"j M Y" }}</span>{% endif %}{% endif %}</td>
      <td class="r"><b>{% if 'list_value' in p %}{{ p.list_value|rupees }}{% endif %}</b></td>
      {% if margin %}<td class="r">{% if p.margin is not None %}{{ p.margin|floatformat:1 }}%{% else %}—{% endif %}</td>{% endif %}
    {% endif %}
  </tr>{% empty %}<tr><td colspan="7" class="hint">No pouch matches these filters.</td></tr>{% endfor %}</tbody>
  {% if count %}<tfoot><tr><td colspan="4"><b>{{ count|grouped }}</b> pouch{{ count|pluralize:"es" }}</td>
    {% if mode == 'cost' %}<td></td><td></td>{% endif %}<td class="r"><b>{{ total|rupees }}</b></td>{% if margin %}<td></td>{% endif %}</tr></tfoot>{% endif %}
</table></div></div>

{% if page.has_other_pages %}<div class="ctrow" style="margin-top:10px">
  {% if page.has_previous %}<a class="btn sm" href="?{{ query }}&page={{ page.previous_page_number }}">‹ Previous</a>{% endif %}
  <span class="hint">Page {{ page.number }} of {{ page.paginator.num_pages }}</span>
  {% if page.has_next %}<a class="btn sm" href="?{{ query }}&page={{ page.next_page_number }}">Next ›</a>{% endif %}
</div>{% endif %}
{% endblock %}
```

- [ ] **Step 5: Wire the URLs and the rail**

In `inventory/urls.py`, add `views_prices` to the `from . import (...)` list (alphabetical, after `views_lists`) and, after the `transfers` path:

```python
    path("prices/cost/", views_prices.prices, {"mode": "cost"}, name="prices_cost"),
    path("prices/selling/", views_prices.prices, {"mode": "selling"}, name="prices_selling"),
```

In `inventory/templates/inventory/_rail.html`, replace the two lines

```html
  {% if not client_view %}<span class="locked"><span class="ic">₹</span>Price list — cost<span class="ct">🔒</span></span>{% endif %}
  <span class="locked"><span class="ic">₹</span>Price list — selling<span class="ct">🔒</span></span>
```

with

```html
  {% if not client_view %}{% if caps.view_cost %}<a class="{% if tab == 'prices_cost' %}on{% endif %}" href="{% url 'inventory:prices_cost' %}"><span class="ic">₹</span>Price list — cost</a>
  {% else %}<span class="locked"><span class="ic">₹</span>Price list — cost<span class="ct">🔒</span></span>{% endif %}{% endif %}
  {% if caps.view_sale and not client_view %}<a class="{% if tab == 'prices_selling' %}on{% endif %}" href="{% url 'inventory:prices_selling' %}"><span class="ic">₹</span>Price list — selling</a>
  {% else %}<span class="locked"><span class="ic">₹</span>Price list — selling<span class="ct">🔒</span></span>{% endif %}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `POSTGRES_DB=pl_t2 ../nornament-app/.venv/bin/pytest inventory/tests/test_price_lists.py inventory/tests/test_masking.py -p no:warnings -q`
Expected: PASS. If `test_paging_keeps_the_filters` fails on the exact query string, print the body's pager and adjust only the test's expected string to the `_query` output order (`f`, then `FIELDS` order, then `stock`) — the behaviour under test is that an unticked "in stock only" stays unticked across pages.

- [ ] **Step 7: Run inventory + accounts**

Run: `POSTGRES_DB=pl_t2 ../nornament-app/.venv/bin/pytest inventory accounts -p no:warnings -q --junit-xml=/tmp/pl_t2.xml`
Expected: no failures, no errors.

- [ ] **Step 8: Commit**

```bash
git add inventory/views_prices.py inventory/templates/inventory/prices.html inventory/urls.py \
        inventory/templates/inventory/_rail.html inventory/tests/test_price_lists.py inventory/tests/test_masking.py
git commit -m "The cost and selling price lists open from the rail by right: filtered, paged, totalled and masked

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Set a price for the filtered group

**Files:**
- Modify: `inventory/views_prices.py` (POST branch in `prices`, new `_set`)
- Modify: `inventory/templates/inventory/prices.html` (group form after the pager)
- Modify: `inventory/tests/test_masking.py` (a POST refusal test)
- Test: `inventory/tests/test_price_lists.py` (append)

**Interfaces:**
- Consumes: Task 1's `services.set_group_price(user, pouches, kind, rate, effective_from, described="") -> int`; Task 2's `MODES`, `_filters`, `_query`, `_pouches`, and context `posted`, `count`, `can_set`, `set_label`, `today`.
- Produces: POST to `inventory:prices_cost` / `inventory:prices_selling` with the filter fields, `count`, `rate`, `effective_from` → redirect to the same list with the same filters and a message.

- [ ] **Step 1: Write the failing tests**

Append to `inventory/tests/test_price_lists.py` — the `import` line goes to the top of the file, the rest at the end:

```python
from django.contrib.messages import get_messages


def _set(client, user, url, count, rate="1250", **filters):
    client.force_login(user)
    return client.post(url, {"f": "1", "stock": "1", **filters, "count": str(count), "rate": rate,
                             "effective_from": timezone.localdate().isoformat()})


def _said(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


def test_setting_a_list_price_prices_every_filtered_pouch_on_every_page(client, accounts_user, priced, monkeypatch):
    monkeypatch.setattr(views_prices, "PAGE", 1)
    response = _set(client, accounts_user, SELLING, 2, batch="SL")
    assert response.status_code == 302
    assert response["Location"] == f"{SELLING}?f=1&batch=SL&stock=1"
    assert _said(response) == ["List price set on 2 pouches."]
    assert services.latest_price(priced["ruby"], PriceEntry.LIST).rate == Decimal("1250")
    assert services.latest_price(priced["onyx"], PriceEntry.LIST).rate == Decimal("1250")
    assert not priced["jade"].prices.exists()                         # empty, so not in the in-stock group


def test_setting_a_valuation_from_the_cost_list_shows_on_the_pouch(client, accounts_user, priced):
    response = _set(client, accounts_user, COST, 1, rate="8000", stone="onyx")
    assert _said(response) == ["Valuation set on 1 pouch."]
    body = client.get(reverse("inventory:pouch", args=[priced["onyx"].ref])).content.decode()
    assert "₹8,000" in body


def test_a_changed_group_or_a_bad_rate_writes_nothing_and_says_why(client, accounts_user, priced):
    before = PriceEntry.objects.count()
    response = _set(client, accounts_user, SELLING, 5)
    assert _said(response) == ["The group changed since the page loaded — check the count and set again."]
    response = _set(client, accounts_user, SELLING, 2, rate="0")
    assert _said(response) == ["The rate has to be a number above zero, at most ten digits before the point."]
    response = _set(client, accounts_user, SELLING, 2, rate="abc")
    assert "The rate has to be a number" in _said(response)[0]
    response = _set(client, accounts_user, SELLING, 0, stone="nothing-like-this")
    assert _said(response) == ["No pouch matches these filters."]
    assert PriceEntry.objects.count() == before


def test_the_form_shows_only_to_who_may_set_and_states_the_count(client, accounts_user, sales_user, priced):
    body = _get(client, accounts_user, SELLING).content.decode()
    assert "Set for 2 pouches" in body and 'name="count" value="2"' in body and "Set list price" in body
    assert "Set valuation" in _get(client, accounts_user, COST).content.decode()
    assert "Set for" not in _get(client, sales_user, SELLING).content.decode()


def test_sales_cannot_set_a_list_price_even_by_posting(client, sales_user, priced):
    before = PriceEntry.objects.count()
    assert _set(client, sales_user, SELLING, 2).status_code == 403
    assert PriceEntry.objects.count() == before


def test_client_view_refuses_a_post(client, admin_user_, priced):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    before = PriceEntry.objects.count()
    response = _set(client, admin_user_, SELLING, 2)
    assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf")
    assert PriceEntry.objects.count() == before
```

In `inventory/tests/test_masking.py`, after `test_the_cost_list_shows_cost_to_accounts`:

```python
@pytest.mark.parametrize("fixture", ["sales_user", "karigar_user", "production_user", "graphic_user"])
def test_no_price_list_post_writes_for_a_login_without_the_right(client, shelf, request, fixture):
    from inventory.models import PriceEntry

    client.force_login(request.getfixturevalue(fixture))
    before = PriceEntry.objects.count()
    for name in sorted(PRICE_SCREENS):
        response = client.post(reverse(name), {"f": "1", "stock": "1", "count": "2", "rate": "1"})
        assert response.status_code == 403, f"{name} returned {response.status_code} to {fixture}"
    assert PriceEntry.objects.count() == before
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_DB=pl_t3 ../nornament-app/.venv/bin/pytest inventory/tests/test_price_lists.py inventory/tests/test_masking.py -p no:warnings -q`
Expected: FAIL — a POST renders the list (200) instead of redirecting; no "Set for" form.

- [ ] **Step 3: Implement the POST**

In `inventory/views_prices.py`, add imports:

```python
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.urls import reverse
from django.utils.dateparse import parse_date
from stock.services import ServiceError, require
```

(merge with the existing `from stock.services import require` line). Add `_set` above `prices`:

```python
def _set(request, mode, kind, f):
    """One price for every pouch the posted filters match, on every page. The count the form showed
    must still hold, so stock that moved since the page loaded is never priced blind."""
    right = MODES[mode][0]
    require(request.user, INV_MASTERS, "Only a role that edits inventory records can set a price.")
    require(request.user, right, "A price you may not see is not yours to set.")
    back = f"{reverse(f'inventory:prices_{mode}')}?{_query(f)}"
    group = list(_pouches(f))
    if str(len(group)) != (request.POST.get("count") or "").strip():
        messages.error(request, "The group changed since the page loaded — check the count and set again.")
        return redirect(back)
    try:
        rate = Decimal(request.POST.get("rate") or "")
    except InvalidOperation:
        rate = None
    when = parse_date(request.POST.get("effective_from") or "") or timezone.localdate()
    described = ", ".join(f"{key}={value}" for key, value in f.items() if value)
    try:
        n = services.set_group_price(request.user, group, kind, rate, when, described=described)
    except ServiceError as error:
        messages.error(request, error.messages[0])
        return redirect(back)
    what = "Valuation" if kind == PriceEntry.VALUATION else "List price"
    messages.success(request, f"{what} set on {n} pouch{'es' if n != 1 else ''}.")
    return redirect(back)
```

In `prices`, directly after the `require(request.user, right, ...)` line:

```python
    if request.method == "POST":
        return _set(request, mode, kind, _filters(request.POST))
```

Note the empty-group case: the posted count is `0`, the rebuilt group is empty, so the counts agree and `set_group_price` answers "No pouch matches these filters."

- [ ] **Step 4: Add the form to the template**

In `inventory/templates/inventory/prices.html`, after the pager block and before `{% endblock %}`:

```html
{% if can_set %}<form method="post" class="card" style="margin-top:14px"><div class="card-b ctrow">{% csrf_token %}
  {% for name, value in posted %}<input type="hidden" name="{{ name }}" value="{{ value }}">{% endfor %}
  <input type="hidden" name="count" value="{{ count }}">
  <b>Set {{ set_label }}</b> ₹/ct <input class="inp tnum" name="rate" required inputmode="decimal" style="width:120px">
  effective from <input class="inp" type="date" name="effective_from" value="{{ today|date:'Y-m-d' }}" max="{{ today|date:'Y-m-d' }}" style="width:150px">
  <button class="btn pri"{% if not count %} disabled{% endif %}>Set for {{ count|grouped }} pouch{{ count|pluralize:"es" }}</button>
  <span class="hint">Every pouch these filters match, on every page. Each gets its own dated row; nothing is overwritten.</span>
</div></form>{% endif %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=pl_t3 ../nornament-app/.venv/bin/pytest inventory/tests/test_price_lists.py inventory/tests/test_masking.py -p no:warnings -q`
Expected: PASS.

- [ ] **Step 6: Run the whole suite**

Run: `POSTGRES_DB=pl_t3 ../nornament-app/.venv/bin/pytest -p no:warnings -q --junit-xml=/tmp/pl_t3.xml` then read the counts from the XML. Also `../nornament-app/.venv/bin/python manage.py makemigrations --check --dry-run`.
Expected: only the known S3 failure; "No changes detected".

- [ ] **Step 7: Commit**

```bash
git add inventory/views_prices.py inventory/templates/inventory/prices.html \
        inventory/tests/test_price_lists.py inventory/tests/test_masking.py
git commit -m "Each price list sets one valuation or list price for every pouch its filters match, checked against the count shown

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
