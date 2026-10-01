# Inventory Part 5a (Lists and Finders) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove nine padlocks with read-only screens over data the app already has: the top search box, the four data-quality filters, the Splits & merges and Transfers lists, the diamond Movements tab with a ledger per line, and the stones Suppliers link.

**Architecture:** No new tables and no new services. Each screen is a thin view over existing reads: `services.stocked`, `dia_services.stocked_lines`, `rows.pouch_rows`/`summarise`, `dia_rows.line_row`, `ledger.party` and `Movement.effect` (the shared balance rule). Stones screens render through `views._page` (stones rail, client flag honoured: every new stones screen redirects in client view). Diamond screens render through `views_diamonds.dia_page` and are built for `views_diamonds.viewer(request)`, so an admin's "Viewing as" preview masks like the role. Rows end in `stock.masking.mask`. Task 1 routes every new URL up front (stubs raising `Http404`) and wires every rail item and tab, so wave 2 builds three screens in parallel without touching `urls.py`, `_rail.html` or `inventory_base.html`.

**Tech Stack:** Django 5.2, Postgres 17, pytest + pytest-django, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-02-inventory-lists-and-finders-design.md` (binding). Earlier parts: `2026-09-28-inventory-stones-design.md`, `2026-10-01-inventory-stones-ledger-design.md`, `2026-09-30-inventory-diamonds-design.md`, `2026-10-01-inventory-diamond-ledgers-design.md`, each with its "Changed while planning". Precedent plan: `docs/superpowers/plans/2026-10-01-inventory-diamond-ledgers.md`.

## Global Constraints

- **Standalone rule:** add no new dependency on stock or CRM data. Part 2's ties stay as they are: karigars and suppliers are `stock.Vendor`, and customers come from `crm.Customer`. This part adds no tie of any kind. Reuse, do not duplicate: `stock.masking.mask/allowed`, `views._client/_everything/_page`, `views_diamonds.viewer/dia_page`, `services.stocked`, `dia_services.stocked_lines/rate_table/line_label`, `dia_rows.line_row`, `ledger.party/STONE_KINDS/DIAMOND_KINDS/ZERO`, `Movement.effect`, `dia_rules.canonical_code`.
- **Masking:** rows are built once and end in `stock.masking.mask()`. Templates test **key presence** (`{% if 'karigar_name' in d %}`, `{% if 'cost_amount' in row %}`), never capabilities, for anything money- or name-shaped. The gated keys used here are `karigar_name` (inv_job), `vendor_name` (view_vendor), `stone_rate`/`pouch_value` and `cost_rate`/`cost_amount` (view_cost). A template never prints `doc.vendor` directly. A karigar the viewer may not see never reads as "In-house": `in_house` is its own key, true only for a job card with no vendor. Rail and tab links may test `caps.*` (part 1's precedent for actions and navigation).
- **Client view:** every new **stones** screen (search results, the four filters, Splits & merges, Transfers) redirects to the shelf in client view, before anything is read, as the ledger screens do. The top search box is padlocked in client view. **Diamonds have no client view:** the diamond Movements list and the line ledger ignore the stones' Internal / Client session flag, as diamond Search already does.
- **"Viewing as":** the diamond Movements list and the line ledger are built for `viewer(request)`. Their links carry `?as=` while previewing. They have no forms.
- **Rights:** every new screen is readable by every internal role, as the document pages are. The Suppliers link is live for `inv_masters` + `view_vendor` (Edit settings and supplier sight), padlocked otherwise and always in client view.
- **Views never write models.** Nothing in this part writes; tests write through the existing services.
- **Shell:** every screen extends `templates/inventory_base.html`: part 1's shell, CSS, dark mode and phone drawer. Use only the existing classes in `static/css/inventory.css`; add no CSS. Wide tables sit in `<div style="overflow:auto">`. Never put `hidden` on an element whose class sets `display`.
- **Prose stripped:** no explainer `<p>`. Headings, column labels, chips and one-line empty states only.
- **Numbers:** carats print with the `ct` filter (2 places, Indian grouping), money with `rupees`, counts with `grouped`.
- **Every existing test passes unchanged**, with exactly three exceptions, each an assertion that a padlock this part removes is still there. Task 1 rewrites them to assert the link instead: `test_ledger_lists.py::test_the_rail_opens_the_ledger_screens_by_right` (Transfers), `test_dia_purchase_view.py::test_the_diamond_purchase_tab` (diamond Movements) and `test_dia_wiring.py::test_the_diamond_movements_and_stock_take_tabs_stay_locked` (diamond Movements; renamed). `test_masking.py` only gains entries (and Task 1's `PENDING`, which Task 5 removes). No other test file is edited. A failure elsewhere is a bug in the change, never in the test.
- **Real-file and parity tests run and pass:** `test_dia_real_file.py` (281 lines, 546.96 ct, cost ₹1,47,98,794 ± ₹10), `test_dia_parity.py` and `test_parity.py` pass unchanged. `../Dia_Stock_Nitesh.xlsx` and `../Nornament_Inventory/` are beside this worktree, so they run rather than skip.
- **Still padlocked after 5a** (`🔒`, never a dead link): Stock takes (stones rail and both tab strips), Price list — cost / selling, Merge (5c), Client lookbook, and "＋ Add user".
- Follow the surrounding style: docstrings say *why*, and there are no type annotations except on dataclass fields.
- Only database tests carry `pytestmark = pytest.mark.django_db`. Tests use the real role fixtures in the root `conftest.py` (`admin_user_` "Owner", `accounts_user` "Accounts", `sales_user` "Showroom", `graphic_user`, `production_user`, `karigar_user`) and in `inventory/tests/conftest.py` (`shelf`, `diamonds`, `parties`, `ledger_docs`, `dia_docs`, and `finder_docs` from Task 5). The `shelf` fixture: batch `SL01G` in box colour G; onyx `SL01G · 1` (NRN-000001, Green Onyx, 20 pcs, 12.5 ct, rate ₹7,919, size `14*10`, supplier Bhansali Gems); ruby `SL01G · 2` (NRN-000002, Ruby Glass, Red in the Green box so misfiled, uncountable, 40 ct, ₹50, size `Free Far` so no size in mm). Neither has a photo. The `diamonds` fixture: NRD-000001 round `DRFGH VS-SI`, `+6-12`, batch `B-771`, 3.40 ct, source row `Sheet!3`, rate card cost ₹16,517; NRD-000002 princess `DPCEF VVS-VS`, batch `B-771`, 0.85 ct; NRD-000003 polki `FPL`, batch `BW-1`, 43.21 ct.
- Run tests from the worktree root with a **private database name** per task: `POSTGRES_DB=finders_tN ../nornament-app/.venv/bin/pytest <paths> -p no:warnings`. Ignore one known pre-existing environmental failure: `stock/tests/test_import_commit.py::test_images_are_attached_in_chunks_and_are_resumable` (live S3 401).
- Commit messages end with a blank line and `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|---|---|
| `inventory/urls.py` (modify, Task 1 only) | `search`, `quality`, `splits`, `transfers`, `dia_movements`, `dia_line` |
| `inventory/views_search.py` (new, Task 1) | the top search box's results: pouches and diamond lines |
| `inventory/views_quality.py` (stub in Task 1, built in Task 2) | the four data-quality filters, one view taking the check's name |
| `inventory/views_lists.py` (stubs in Task 1, built in Task 3) | `splits`, `transfers` beside the existing lists |
| `inventory/views_dia_movements.py` (stub in Task 1, built in Task 4) | the diamond Movements list, the line ledger, `opens()` |
| `inventory/rows.py` (modify, Task 2) | `CHECKS`: the four data-quality predicates, shared by `summarise` and the filters |
| `templates/inventory_base.html` (modify, Task 1 only) | the live search box; the diamond Movements tab |
| `inventory/templates/inventory/_rail.html` (modify, Task 1; Suppliers line in Task 5) | the four filters, Splits & merges, Transfers, Suppliers |
| `inventory/templates/inventory/search.html` (new, Task 1) | search results |
| `inventory/templates/inventory/_pouch_table.html` (new, Task 2) | the batch page's pouch table, with an optional Batch column |
| `inventory/templates/inventory/batch.html` (modify, Task 2) | includes `_pouch_table.html` |
| `inventory/templates/inventory/quality.html` (new, Task 2) | one filter's pouches |
| `inventory/templates/inventory/splits.html`, `transfers.html` (new, Task 3) | the two lists |
| `inventory/templates/inventory/diamonds/movements.html`, `line.html` (new, Task 4) | the diamond Movements list, the line ledger |
| `inventory/templates/inventory/diamonds/search.html` (modify, Task 4) | a Line column linking each ref to its ledger |
| `inventory/tests/test_search.py`, `test_finders_rail.py` (new, Task 1; Task 5 appends to the rail file) | search rules; rail and tab wiring |
| `inventory/tests/test_quality.py` (Task 2), `test_split_transfer_lists.py` (Task 3), `test_dia_movements.py` (Task 4) | per screen |
| `inventory/tests/test_ledger_lists.py`, `test_dia_purchase_view.py`, `test_dia_wiring.py` (Task 1) | the three padlock assertions, rewritten |
| `inventory/tests/test_masking.py` (Task 1 `PENDING`; Task 5 the walk), `inventory/tests/conftest.py` (Task 5 `finder_docs`) | masking walk and every-screen check |
| `docs/superpowers/specs/2026-10-02-inventory-lists-and-finders-design.md` (Task 5) | "Changed while planning" |

## Parallel waves

| Wave | Tasks | Files each task touches |
|---|---|---|
| 1 | **1** search, routes, rail and tabs | `inventory/urls.py`, `inventory/views_search.py`, stub `inventory/views_quality.py`, stub `inventory/views_dia_movements.py`, `inventory/views_lists.py` (two stubs), `templates/inventory_base.html`, `inventory/templates/inventory/_rail.html`, `inventory/templates/inventory/search.html`, `inventory/tests/test_search.py`, `inventory/tests/test_finders_rail.py`, `inventory/tests/test_masking.py` (`PENDING`), `inventory/tests/test_ledger_lists.py`, `inventory/tests/test_dia_purchase_view.py`, `inventory/tests/test_dia_wiring.py` (one assertion each) |
| 2 | **2, 3, 4** in parallel | 2: `inventory/rows.py`, `inventory/views_quality.py`, `_pouch_table.html`, `batch.html`, `quality.html`, `inventory/tests/test_quality.py` · 3: `inventory/views_lists.py`, `splits.html`, `transfers.html`, `inventory/tests/test_split_transfer_lists.py` · 4: `inventory/views_dia_movements.py`, `diamonds/movements.html`, `diamonds/line.html`, `diamonds/search.html`, `inventory/tests/test_dia_movements.py` |
| 3 | **5** Suppliers, masking walk, spec | `_rail.html` (the Suppliers line), `inventory/tests/test_finders_rail.py` (appends), `inventory/tests/test_masking.py`, `inventory/tests/conftest.py`, the spec |

**Why wave 2 does not fight over files.** Task 1 routes all six URLs (the five not built in Task 1 point at stubs raising `Http404`, in the three modules wave 2 fills) and lists them as `PENDING` in the every-screen check. It also wires every rail item and the diamond Movements tab to those URLs. So no wave-2 task edits `urls.py`, `_rail.html`, `inventory_base.html`, `conftest.py` or `test_masking.py`. Each wave-2 task owns its own view module, its own templates and its own test file. Task 3 is the only one touching `views_lists.py`, Task 2 the only one touching `rows.py` and `batch.html`, and Task 4 the only one touching `diamonds/search.html`. Task 4's search test reads only the new Line column; Task 2's tests read only the quality pages and the rail counts Task 1 already renders.

---

### Task 1: The search box, its results, every new route, and the rail and tabs wired

**Files:**
- Create: `inventory/views_search.py`, `inventory/views_quality.py` (stub), `inventory/views_dia_movements.py` (stub), `inventory/templates/inventory/search.html`, `inventory/tests/test_search.py`, `inventory/tests/test_finders_rail.py`
- Modify: `inventory/urls.py`, `inventory/views_lists.py` (two stubs), `templates/inventory_base.html`, `inventory/templates/inventory/_rail.html`, `inventory/tests/test_masking.py`, `inventory/tests/test_ledger_lists.py`, `inventory/tests/test_dia_purchase_view.py`, `inventory/tests/test_dia_wiring.py`

**Interfaces:**
- Consumes: `views._client/_everything/_page`; `services.stocked(queryset)`; `dia_services.stocked_lines(queryset)`; `dia_rules.canonical_code`; `stock.masking.mask`; `Pouch`, `DiamondLine`.
- Produces:
  - URL names: `inventory:search` (`search/`), `inventory:quality` (`quality/<str:check>/`), `inventory:splits` (`splits/`), `inventory:transfers` (`transfers/`), `inventory:dia_movements` (`diamonds/movements/`), `inventory:dia_line` (`diamonds/lines/<str:ref>/`).
  - `views_search.search(request)`; `views_search.CAP = 50`, `views_search.MIN = 2`.
  - Stubs, each raising `Http404("Not built yet.")`: `views_quality.quality(request, check)`, `views_lists.splits(request)`, `views_lists.transfers(request)`, `views_dia_movements.movements(request)`, `views_dia_movements.line(request, ref)`.
  - Rail: the four data-quality items link to `inventory:quality` with `misfiled`, `no_pouch_no`, `no_photo`, `no_size`, carry their live counts and no padlock, and are `on` when the page's `check` matches. Splits & merges and Transfers link to their lists and are `on` for `tab` `splits` / `transfers`.
  - Diamond tabs: Movements links to `inventory:dia_movements` (carrying `?as=`) and is `on` for `dtab == 'movements'`. Diamond stock is `on` for any other `dtab` except `purchase`.
  - `test_masking.PENDING` holds the six new names.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_search.py`:

```python
"""The top bar's search: what each kind of query finds, the cap, the minimum, and where it is
not offered."""
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import dia_services, services
from inventory.tests.conftest import DIA_COST, DIA_COST_VALUE, VALUE

pytestmark = pytest.mark.django_db
D = Decimal
ROW = '<a class="rowlink" href="'


def _found(client, user, q):
    client.force_login(user)
    return client.get(reverse("inventory:search"), {"q": q}).content.decode()


def _pouch(pouch):
    return f'{ROW}{reverse("inventory:pouch", args=[pouch.ref])}"'


def _line(line):
    return f'{ROW}{reverse("inventory:dia_line", args=[line.ref])}"'


def test_the_box_is_live_on_both_sides_and_padlocked_in_client_view(client, admin_user_, shelf, diamonds):
    box = f'action="{reverse("inventory:search")}"'
    client.force_login(admin_user_)
    assert box in client.get(reverse("inventory:shelf")).content.decode()
    assert box in client.get(reverse("inventory:diamonds")).content.decode()
    client.post(reverse("inventory:set_view"), {"view": "client"})
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert box not in body and "Search batch, pouch, stone… 🔒" in body
    response = client.get(reverse("inventory:search"), {"q": "onyx"})
    assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf")


def test_a_pouch_is_found_by_ref_batch_batch_and_pouch_no_or_stone_name(client, accounts_user, shelf):
    onyx, ruby = shelf["onyx"], shelf["ruby"]
    for q, hits in [(onyx.ref.lower(), {onyx}), ("sl01g", {onyx, ruby}), ("SL01G · 2", {ruby}),
                    ("SL01G 1", {onyx}), ("onyx", {onyx}), ("GLASS", {ruby}), ("SL01", set())]:
        body = _found(client, accounts_user, q)
        for pouch in (onyx, ruby):
            assert (_pouch(pouch) in body) == (pouch in hits), (q, pouch.ref)


def test_a_diamond_line_is_found_by_ref_item_code_or_batch_no(client, accounts_user, diamonds):
    lines = (diamonds["round"], diamonds["princess"], diamonds["polki"])
    rnd, princess, polki = lines
    for q, hits in [(rnd.ref.lower(), {rnd}), ("drfgh vs si", {rnd}), ("VVS", {princess}),
                    ("b-771", {rnd, princess}), ("bw-1", {polki}), ("FPL", {polki})]:
        body = _found(client, accounts_user, q)
        for line in lines:
            assert (_line(line) in body) == (line in hits), (q, line.ref)


def test_each_group_shows_at_most_fifty(client, admin_user_, shelf, diamonds):
    services.open_pouches(admin_user_, [(shelf["batch"], {"pouch_no": str(n), "stone_name": "Agate"}, 1, D("1"), None)
                                        for n in range(10, 65)])
    rnd = diamonds["round"]
    dia_services.open_lines(admin_user_, [
        {"category": rnd.category, "code": rnd.code, "batch_no": "AGATE", "size_text": "+2", "band": rnd.band,
         "src": f"Sheet!{n}", "ct": D("1")} for n in range(100, 155)])
    body = _found(client, admin_user_, "agate")
    pouches = reverse("inventory:pouch", args=["x"]).removesuffix("x/")
    lines = reverse("inventory:dia_line", args=["x"]).removesuffix("x/")
    assert body.count(f"{ROW}{pouches}") == 50 and body.count(f"{ROW}{lines}") == 50
    assert body.count("first 50 of 55") == 2


def test_a_query_under_two_characters_finds_nothing(client, accounts_user, shelf):
    for q in ("", "   ", "s"):
        body = _found(client, accounts_user, q)
        assert "Nothing found" in body and _pouch(shelf["onyx"]) not in body, q


def test_results_carry_no_money_and_every_internal_role_may_search(client, accounts_user, karigar_user, shelf,
                                                                   diamonds):
    body = _found(client, accounts_user, "SL01G")
    assert _pouch(shelf["onyx"]) in body and "7,919" not in body and VALUE not in body
    body = _found(client, accounts_user, "B-771")
    assert _line(diamonds["round"]) in body and DIA_COST not in body and DIA_COST_VALUE not in body
    assert _pouch(shelf["onyx"]) in _found(client, karigar_user, "onyx")
```

`inventory/tests/test_finders_rail.py`:

```python
"""Part 5a's rail and tabs: what was padlocked now links, and what stays padlocked still is."""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db
CHECKS = ("misfiled", "no_pouch_no", "no_photo", "no_size")


def _shelf(client, user):
    client.force_login(user)
    return client.get(reverse("inventory:shelf")).content.decode()


def test_the_stones_rail_links_the_lists_and_the_data_quality_filters(client, accounts_user, shelf):
    body = _shelf(client, accounts_user)
    urls = [reverse("inventory:splits"), reverse("inventory:transfers"),
            *(reverse("inventory:quality", args=[check]) for check in CHECKS)]
    for url in urls:
        assert f'href="{url}"' in body, url
    assert 'Misfiled colour<span class="ct">1</span>' in body and 'No pouch no.<span class="ct">0</span>' in body
    assert 'Missing photos<span class="ct">2</span>' in body and 'No size in mm<span class="ct">1</span>' in body
    assert "🔒" not in body.split('<div class="nav-h">Data quality</div>')[1].split("</nav>")[0]
    assert 'Stock takes<span class="ct">🔒' in body and 'Client lookbook<span class="ct">🔒' in body


def test_client_view_shows_neither_the_lists_nor_the_filters(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert reverse("inventory:splits") not in body and reverse("inventory:quality", args=["misfiled"]) not in body


def test_the_diamond_movements_tab_is_live_and_stock_take_stays_locked(client, admin_user_, diamonds):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert f'href="{reverse("inventory:dia_movements")}">Movements</a>' in body and "Stock take 🔒" in body
    previewed = client.get(reverse("inventory:diamonds"), {"as": "SALES"}).content.decode()       # only an admin previews
    assert f'href="{reverse("inventory:dia_movements")}?as=SALES">Movements</a>' in previewed
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=finders_t1 ../nornament-app/.venv/bin/pytest inventory/tests/test_search.py inventory/tests/test_finders_rail.py -p no:warnings`
Expected: FAIL with `NoReverseMatch: Reverse for 'search' not found`.

- [ ] **Step 3: The stubs and the routes**

`inventory/views_quality.py`:

```python
"""The data-quality filters — routed now so the rail can link to them; built by its own task."""
from django.http import Http404


def quality(request, check):
    raise Http404("Not built yet.")
```

`inventory/views_dia_movements.py`:

```python
"""The diamond Movements tab and the line ledger — routed now so the tabs and Search can link to
them; built by its own task."""
from django.http import Http404


def movements(request):
    raise Http404("Not built yet.")


def line(request, ref):
    raise Http404("Not built yet.")
```

In `inventory/views_lists.py`, add `from django.http import Http404` to the imports and append:

```python
def splits(request):
    raise Http404("Not built yet.")


def transfers(request):
    raise Http404("Not built yet.")
```

`inventory/urls.py`, the import becomes:

```python
from . import (
    views, views_assort, views_dia_assort, views_dia_import, views_dia_jobs, views_dia_movements, views_dia_purchase,
    views_dia_settings, views_diamonds, views_documents, views_ledger, views_lists, views_purchase, views_quality,
    views_search,
)
```

after `path("movements/", views_lists.recent, name="recent"),` add:

```python
    path("search/", views_search.search, name="search"),
    path("quality/<str:check>/", views_quality.quality, name="quality"),
    path("splits/", views_lists.splits, name="splits"),
    path("transfers/", views_lists.transfers, name="transfers"),
```

and after the `dia_purchase_reverse` route add:

```python
    path("diamonds/movements/", views_dia_movements.movements, name="dia_movements"),
    path("diamonds/lines/<str:ref>/", views_dia_movements.line, name="dia_line"),
```

In `inventory/tests/test_masking.py`, add after `EXEMPT`:

```python
#: part 5a's finders, routed before they are built so the rail and tabs can link to them;
#: the masking-walk task walks each of them and deletes this set
PENDING = {"inventory:search", "inventory:quality", "inventory:splits", "inventory:transfers",
           "inventory:dia_movements", "inventory:dia_line"}
```

and in `test_every_inventory_screen_is_walked`:

```python
    missing = named - covered - EXEMPT - PENDING
```

- [ ] **Step 4: The results view**

`inventory/views_search.py`:

```python
"""The top bar's search: pouches and diamond lines by the names people use for them.

Internal only — in client view it redirects, as the ledger screens do — and no
money on the page: a result says where to go, not what it is worth.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect

from stock.masking import mask

from . import dia_rules, dia_services, services
from .models import DiamondLine, Pouch
from .views import _client, _everything, _page

CAP = 50
MIN = 2


def _pouches(q):
    """A pouch ref or a batch code exactly, "batch · pouch no." (or "batch pouch no."), or a stone
    name containing it; case never matters."""
    match = Q(ref__iexact=q) | Q(batch__code__iexact=q) | Q(stone_name__icontains=q)
    parts = q.replace("·", " ").split()
    if len(parts) == 2:
        match |= Q(batch__code__iexact=parts[0], pouch_no__iexact=parts[1])
    return services.stocked(Pouch.objects.filter(match))


def _lines(q):
    """A line ref or a batch no. exactly, or an item code containing it, read as the register
    writes codes ("drfgh vs si" finds DRFGH VS-SI)."""
    match = (Q(ref__iexact=q) | Q(batch_no__iexact=q)
             | Q(code__item_code__icontains=dia_rules.canonical_code(q.upper())))
    return dia_services.stocked_lines(DiamondLine.objects.filter(match))


def _pouch_row(user, p):
    return mask(user, {"ref": p.ref, "pouch": str(p), "stone_name": p.stone_name, "colour": p.colour,
                       "shape": p.shape, "countable": p.countable, "pcs": p.on_pcs if p.countable else None,
                       "ct": p.on_ct})


def _line_row(user, line):
    shape, colour, clarity = line.shape, line.colour, line.code.clarity
    return mask(user, {"ref": line.ref, "item_code": line.code_id, "category": line.category.value,
                       "shape": shape.value if shape else "", "colour": colour.value if colour else "",
                       "clarity": clarity.value if clarity else "", "size": line.size_text or line.band.value,
                       "batch": line.batch_no, "ct": line.on_ct})


@login_required
def search(request):
    if _client(request):
        return redirect("inventory:shelf")
    q = (request.GET.get("q") or "").strip()
    pouches, lines, found = [], [], {"pouches": 0, "lines": 0}
    if len(q) >= MIN:
        hits, matched = _pouches(q), _lines(q)
        found = {"pouches": hits.count(), "lines": matched.count()}
        pouches = [_pouch_row(request.user, p) for p in hits[:CAP]]
        lines = [_line_row(request.user, line) for line in matched[:CAP]]
    return _page(request, "inventory/search.html", _everything(request), tab="search", q=q, short=len(q) < MIN,
                 pouches=pouches, lines=lines, found=found)
```

`inventory/templates/inventory/search.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Search{% endblock %}
{% block crumb %}<b>Search</b>{% if q %} &nbsp;›&nbsp; <span class="mono">{{ q }}</span>{% endif %}{% endblock %}
{% block content %}
<div class="shelfbar"><h1>Search</h1></div>
{% if not pouches and not lines %}
<div class="card"><div class="card-b"><span class="hint">Nothing found{% if short %} — type at least 2 characters{% endif %}.</span></div></div>
{% endif %}
{% if pouches %}
<div class="card" style="overflow:hidden;margin-bottom:14px">
  <div class="card-h"><span class="card-t">Pouches</span><span class="spacer"></span>
    <span class="hint">{% if found.pouches > pouches|length %}first {{ pouches|length }} of {{ found.pouches }}{% else %}{{ found.pouches }}{% endif %}</span></div>
  <div style="overflow:auto"><table class="pt">
    <thead><tr><th>Pouch</th><th>Ref</th><th>Stone</th><th>Colour</th><th>Shape</th><th class="r">Pcs</th><th class="r">Carats</th></tr></thead>
    <tbody>{% for p in pouches %}<tr onclick="location.href='{% url 'inventory:pouch' p.ref %}'">
      <td class="mono"><a class="rowlink" href="{% url 'inventory:pouch' p.ref %}"><b>{{ p.pouch }}</b></a></td>
      <td class="mono hint">{{ p.ref }}</td>
      <td>{{ p.stone_name|default:"—" }}</td><td>{{ p.colour|default:"—" }}</td><td>{{ p.shape|default:"—" }}</td>
      <td class="r">{% if p.countable %}{{ p.pcs|grouped }}{% else %}<span class="hint">uncountable</span>{% endif %}</td>
      <td class="r">{{ p.ct|ct }}</td></tr>{% endfor %}</tbody></table></div>
</div>
{% endif %}
{% if lines %}
<div class="card" style="overflow:hidden">
  <div class="card-h"><span class="card-t">Diamond lines</span><span class="spacer"></span>
    <span class="hint">{% if found.lines > lines|length %}first {{ lines|length }} of {{ found.lines }}{% else %}{{ found.lines }}{% endif %}</span></div>
  <div style="overflow:auto"><table class="pt">
    <thead><tr><th>Line</th><th>Item code</th><th>Category</th><th>Shape</th><th>Colour</th><th>Clarity</th><th>Size</th><th>Batch</th><th class="r">Carats</th></tr></thead>
    <tbody>{% for l in lines %}<tr onclick="location.href='{% url 'inventory:dia_line' l.ref %}'">
      <td class="mono"><a class="rowlink" href="{% url 'inventory:dia_line' l.ref %}"><b>{{ l.ref }}</b></a></td>
      <td class="mono" style="font-size:11px">{{ l.item_code }}</td><td>{{ l.category }}</td>
      <td>{{ l.shape|default:"—" }}</td><td>{{ l.colour|default:"—" }}</td><td>{{ l.clarity|default:"—" }}</td>
      <td class="mono">{{ l.size }}</td><td class="mono">{{ l.batch|default:"—" }}</td>
      <td class="r">{{ l.ct|ct }}</td></tr>{% endfor %}</tbody></table></div>
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: The box and the diamond Movements tab**

In `templates/inventory_base.html`, the line

```django
      <div class="search locked" title="Coming soon">Search batch, pouch, stone… 🔒</div>
```

becomes

```django
      {% if client_view %}<div class="search locked" title="Internal only">Search batch, pouch, stone… 🔒</div>
      {% else %}<form method="get" action="{% url 'inventory:search' %}" role="search">
        <input class="inp" type="search" name="q" value="{{ q|default:'' }}" maxlength="60" placeholder="Search batch, pouch, stone…"
          aria-label="Search pouches and diamond lines" style="min-width:190px;padding:6px 10px;font-size:12px"></form>{% endif %}
```

The live box is a `<form>` with an `.inp` input, not `.search`: the shell hides `.search` below 860px, and the box must work on a phone, where `.top` already wraps.

In the diamond tabs, the lines

```django
        <button disabled title="Coming soon">Movements 🔒</button>
```

and

```django
        <a class="{% if dtab != 'purchase' %}on{% endif %}" href="{% url 'inventory:diamonds' %}">Diamond stock</a>
```

become

```django
        <a class="{% if dtab == 'movements' %}on{% endif %}" href="{% url 'inventory:dia_movements' %}{% if as_role %}?as={{ as_role }}{% endif %}">Movements</a>
```

and

```django
        <a class="{% if dtab != 'purchase' and dtab != 'movements' %}on{% endif %}" href="{% url 'inventory:diamonds' %}">Diamond stock</a>
```

- [ ] **Step 6: The rail**

In `inventory/templates/inventory/_rail.html`, the three locked lines at the end of the Stock control `<nav>`

```django
  <span class="locked"><span class="ic">⊙</span>Stock takes<span class="ct">🔒</span></span>
  <span class="locked"><span class="ic">⤴</span>Splits &amp; merges<span class="ct">🔒</span></span>
  <span class="locked"><span class="ic">⇉</span>Transfers<span class="ct">🔒</span></span>
```

become

```django
  <span class="locked"><span class="ic">⊙</span>Stock takes<span class="ct">🔒</span></span>
  <a class="{% if tab == 'splits' %}on{% endif %}" href="{% url 'inventory:splits' %}"><span class="ic">⤴</span>Splits &amp; merges</a>
  <a class="{% if tab == 'transfers' %}on{% endif %}" href="{% url 'inventory:transfers' %}"><span class="ic">⇉</span>Transfers</a>
```

and the Data quality `<nav>` becomes

```django
<nav class="nav">
  {% if 'misfiled' in rail %}<a class="{% if check == 'misfiled' %}on{% endif %}" href="{% url 'inventory:quality' 'misfiled' %}"><span class="ic" style="color:var(--warning)">⚑</span>Misfiled colour<span class="ct">{{ rail.misfiled|grouped }}</span></a>{% endif %}
  {% if 'no_pouch_no' in rail %}<a class="{% if check == 'no_pouch_no' %}on{% endif %}" href="{% url 'inventory:quality' 'no_pouch_no' %}"><span class="ic" style="color:var(--critical)">!</span>No pouch no.<span class="ct">{{ rail.no_pouch_no|grouped }}</span></a>{% endif %}
  <a class="{% if check == 'no_photo' %}on{% endif %}" href="{% url 'inventory:quality' 'no_photo' %}"><span class="ic">◱</span>Missing photos<span class="ct">{{ rail.no_photo|grouped }}</span></a>
  <a class="{% if check == 'no_size' %}on{% endif %}" href="{% url 'inventory:quality' 'no_size' %}"><span class="ic">⤢</span>No size in mm<span class="ct">{{ rail.no_size|grouped }}</span></a>
</nav>
```

Both blocks stay inside their existing `{% if not client_view %}`.

- [ ] **Step 7: The three padlock assertions this part removes**

`inventory/tests/test_ledger_lists.py`, in `test_the_rail_opens_the_ledger_screens_by_right`, the line

```python
    assert 'Stock takes<span class="ct">🔒' in body and 'Transfers<span class="ct">🔒' in body
```

becomes

```python
    assert 'Stock takes<span class="ct">🔒' in body and f'href="{reverse("inventory:transfers")}"' in body
```

`inventory/tests/test_dia_purchase_view.py`, in `test_the_diamond_purchase_tab`, the line

```python
    assert "Movements 🔒" in body and "Stock take 🔒" in body
```

becomes

```python
    assert f'href="{reverse("inventory:dia_movements")}">Movements</a>' in body and "Stock take 🔒" in body
```

`inventory/tests/test_dia_wiring.py`, the last test becomes

```python
def test_the_diamond_stock_take_tab_stays_locked(client, accounts_user, diamonds):
    body = _search(client, accounts_user)
    assert "Movements 🔒" not in body and "Stock take 🔒" in body
```

- [ ] **Step 8: Run the tests**

Run: `POSTGRES_DB=finders_t1 ../nornament-app/.venv/bin/pytest inventory/tests/test_search.py inventory/tests/test_finders_rail.py inventory/tests/test_ledger_lists.py inventory/tests/test_dia_purchase_view.py inventory/tests/test_dia_wiring.py inventory/tests/test_masking.py inventory/tests/test_client_view.py -p no:warnings`
Expected: PASS.

Run: `POSTGRES_DB=finders_t1 ../nornament-app/.venv/bin/pytest inventory -p no:warnings`
Expected: PASS, the real-file and parity tests included, with `git diff --stat inventory/tests/` showing only the two new files, `test_masking.py` and the three one-assertion edits.

- [ ] **Step 9: Commit**

```bash
git add inventory/urls.py inventory/views_search.py inventory/views_quality.py inventory/views_dia_movements.py \
  inventory/views_lists.py templates/inventory_base.html inventory/templates/inventory/_rail.html \
  inventory/templates/inventory/search.html inventory/tests/test_search.py inventory/tests/test_finders_rail.py \
  inventory/tests/test_masking.py inventory/tests/test_ledger_lists.py inventory/tests/test_dia_purchase_view.py \
  inventory/tests/test_dia_wiring.py
git commit -m "$(cat <<'EOF'
The top search box finds pouches and diamond lines; part 5a's routes, rail items and diamond Movements tab wired

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The four data-quality filters, each listing exactly the rail's count

**Files:**
- Create: `inventory/templates/inventory/_pouch_table.html`, `inventory/templates/inventory/quality.html`, `inventory/tests/test_quality.py`
- Modify: `inventory/rows.py`, `inventory/views_quality.py` (replaces the stub), `inventory/templates/inventory/batch.html`

**Interfaces:**
- Consumes: `views._client/_everything/_page`; `rows.summarise/pouch_rows`; the rail items and `inventory:quality` route from Task 1.
- Produces:
  - `rows.CHECKS`: `{"misfiled", "no_pouch_no", "no_photo", "no_size"}` → a predicate on a pouch row. `rows.summarise` counts through it; its output is unchanged.
  - `views_quality.TITLES` (the rail's four labels) and `views_quality.quality(request, check)`: client view → redirect to the shelf; an unknown check → 404; else the matching rows of `_everything(request)` in the pouch table, `tab="quality"`, `check=check`.
  - `inventory/_pouch_table.html`: the batch page's pouch table (from `<div style="overflow:auto">` to its close), reading `pouches`, `money` and an optional `show_batch` (a leading Batch column).

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_quality.py`:

```python
"""The rail's four data-quality filters: each lists exactly the pouches the rail counts."""
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import rows, services
from inventory.views_quality import TITLES

pytestmark = pytest.mark.django_db
CHECKS = ("misfiled", "no_pouch_no", "no_photo", "no_size")
ROW = '<a class="rowlink" href="'


@pytest.fixture
def flawed(admin_user_, shelf):
    """The shelf (the ruby is misfiled with no size in mm; neither pouch has a photo), plus a jade
    with no pouch no. and no size, and a photo on the onyx."""
    from mediahub.models import MediaAsset
    from stock.enums import MediaKind

    jade = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": None, "stone_name": "Jade", "colour": "Green"},
                               pcs=3, ct=Decimal("6"), rate=None)
    MediaAsset.objects.create(media_ref="M-ONYX-1", kind=MediaKind.PHOTO, storage_key="crm/pouch/1/a.jpg",
                              file_name="SL01G-1-01.jpg", mime_type="image/jpeg", scope="pouch",
                              scope_id=str(shelf["onyx"].pk))
    return {**shelf, "jade": jade}


def _page(client, user, check):
    client.force_login(user)
    return client.get(reverse("inventory:quality", args=[check]))


def test_each_filter_lists_exactly_the_rails_live_count(client, accounts_user, flawed):
    counts = rows.summarise(rows.pouch_rows(accounts_user, services.stocked()))
    assert [counts[check] for check in CHECKS] == [1, 1, 2, 2]
    for check in CHECKS:
        body = _page(client, accounts_user, check).content.decode()
        assert body.count(ROW) == counts[check], check
        assert f'{TITLES[check]}<span class="ct">{counts[check]}</span>' in body, check
        assert f'class="on" href="{reverse("inventory:quality", args=[check])}"' in body, check


def test_each_row_opens_its_pouch(client, accounts_user, flawed):
    body = _page(client, accounts_user, "no_pouch_no").content.decode()
    assert f'{ROW}{reverse("inventory:pouch", args=[flawed["jade"].ref])}"' in body
    assert reverse("inventory:pouch", args=[flawed["onyx"].ref]) not in body
    assert "<th>Batch</th>" in body and "SL01G" in body
    body = _page(client, accounts_user, "no_size").content.decode()
    assert f'{ROW}{reverse("inventory:pouch", args=[flawed["ruby"].ref])}"' in body
    assert f'{ROW}{reverse("inventory:pouch", args=[flawed["jade"].ref])}"' in body


def test_money_shows_only_with_the_cost_right(client, accounts_user, sales_user, flawed):
    assert "Value</th>" in _page(client, accounts_user, "misfiled").content.decode()
    body = _page(client, sales_user, "misfiled").content.decode()
    assert "Value</th>" not in body and "₹50" not in body
    assert f'{ROW}{reverse("inventory:pouch", args=[flawed["ruby"].ref])}"' in body


def test_client_view_redirects_and_an_unknown_check_is_404(client, admin_user_, karigar_user, shelf):
    assert _page(client, karigar_user, "no_photo").status_code == 200
    assert _page(client, admin_user_, "bogus").status_code == 404
    client.post(reverse("inventory:set_view"), {"view": "client"})
    response = client.get(reverse("inventory:quality", args=["misfiled"]))
    assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf")


def test_the_batch_table_is_unchanged(client, admin_user_, shelf):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:batch", args=[shelf["batch"].pk]), {"view": "table"}).content.decode()
    assert "<th>Check</th>" in body and "<th>Batch</th>" not in body and body.count(ROW) == 2
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=finders_t2 ../nornament-app/.venv/bin/pytest inventory/tests/test_quality.py -p no:warnings`
Expected: FAIL with `ImportError: cannot import name 'TITLES' from 'inventory.views_quality'`.

- [ ] **Step 3: One place for the four predicates**

In `inventory/rows.py`, add after `CLIENT_HIDDEN`:

```python
#: the rail's data-quality checks, each a test on a pouch row: ``summarise`` counts them and the
#: filters list them, so a list always holds exactly the rail's count. Misfiled and no pouch no.
#: read keys a client row does not carry; neither is ever asked of one.
CHECKS = {
    "misfiled": lambda r: r["misfiled"],
    "no_pouch_no": lambda r: r["no_pouch_no"],
    "no_photo": lambda r: not r["photo_id"],
    "no_size": lambda r: r["size_kind"] in ("free", "none"),
}
```

and `summarise` becomes:

```python
def summarise(rows):
    """Totals for any set of rows — the whole shelf, one box colour, one batch.

    A total of something masked is itself masked: the key is left out, exactly
    as ``mask`` leaves out the field.
    """
    out = {
        "pouches": len(rows),
        "batches": len({r["batch_pk"] for r in rows}),
        "colours": len({r["box_colour"] for r in rows}),
        "ct": sum((r["ct"] or 0) for r in rows),
        "no_size": sum(1 for r in rows if CHECKS["no_size"](r)),
        "no_photo": sum(1 for r in rows if CHECKS["no_photo"](r)),
    }
    if _has(rows, "pouch_value"):
        out["value"] = sum((r["pouch_value"] or 0) for r in rows)
        out["unpriced"] = sum(1 for r in rows if r["pouch_value"] is None)
    if _has(rows, "misfiled"):
        out["misfiled"] = sum(1 for r in rows if CHECKS["misfiled"](r))
    if _has(rows, "no_pouch_no"):
        out["no_pouch_no"] = sum(1 for r in rows if CHECKS["no_pouch_no"](r))
        out["keyed"] = out["pouches"] - out["no_pouch_no"]
    if _has(rows, "carton"):
        out["boxes"] = sorted({r["carton"] for r in rows if r["carton"]}, key=lambda b: (len(b), b))
    return out
```

- [ ] **Step 4: The pouch table, shared**

`inventory/templates/inventory/_pouch_table.html` (the batch page's table, plus an optional Batch column):

```django
{% load inventory_extras %}<div style="overflow:auto"><table class="pt">
    <thead><tr>{% if show_batch %}<th>Batch</th>{% endif %}<th>Pouch</th><th>Category</th><th>Stone</th><th>Shape</th><th>Colour</th><th>Cut</th><th>Q</th>
      <th class="r">Pcs</th><th class="r">Carats</th>{% if money %}<th class="r">Rate</th><th class="r">Value</th>{% endif %}
      <th>Size (mm)</th><th>Remarks</th><th>Check</th></tr></thead>
    <tbody>{% for p in pouches %}
      <tr onclick="location.href='{% url 'inventory:pouch' p.ref %}'">
        {% if show_batch %}<td class="mono">{{ p.batch_code }}</td>{% endif %}
        <td class="bn"><a class="rowlink" href="{% url 'inventory:pouch' p.ref %}">{% if p.pouch_no %}{{ p.pouch_no }}{% else %}<span class="hint">none</span>{% endif %}</a></td>
        <td>{{ p.category }}</td><td>{{ p.stone_name }}</td><td>{{ p.shape }}</td><td>{{ p.colour }}</td>
        <td>{{ p.cut }}</td><td>{{ p.quality }}</td>
        <td class="r">{% if p.countable %}{{ p.pcs|grouped }}{% else %}<span class="hint">uncountable</span>{% endif %}</td>
        <td class="r">{{ p.ct|ct }}</td>
        {% if money %}<td class="r">{{ p.stone_rate|rupees }}</td><td class="r"><b>{{ p.pouch_value|rupees }}</b></td>{% endif %}
        <td class="mono" style="font-size:11px">{{ p.size_display|default:"—" }}</td>
        <td class="hint">{{ p.remarks }}</td>
        <td>{% if p.misfiled %}<span class="chip warn"><span class="dot"></span>colour</span>
          {% elif p.no_pouch_no %}<span class="chip crit"><span class="dot"></span>no pouch no.</span>
          {% elif money and p.pouch_value is None %}<span class="chip warn"><span class="dot"></span>unpriced</span>
          {% else %}<span class="chip good"><span class="dot"></span>ok</span>{% endif %}</td>
      </tr>{% endfor %}</tbody></table></div>
```

In `inventory/templates/inventory/batch.html`, the table card becomes:

```django
{% if view == 'table' %}
<div class="card" style="overflow:hidden">
  <div class="card-h"><span class="card-t">Pouches in {{ batch.code }}</span></div>
  {% include "inventory/_pouch_table.html" %}
</div>
{% else %}
```

(everything from `<div style="overflow:auto"><table class="pt">` to its closing `</table></div>` moves into the include; the grid branch is untouched).

- [ ] **Step 5: The view and its page**

`inventory/views_quality.py` (the whole file):

```python
"""The rail's data-quality filters: the pouches with one problem, in the batch page's table.

Internal only. Each list is the rail's own count, because both apply ``rows.CHECKS``
to the same rows.
"""
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect

from . import rows
from .views import _client, _everything, _page

#: the rail's labels, which the pages share
TITLES = {"misfiled": "Misfiled colour", "no_pouch_no": "No pouch no.", "no_photo": "Missing photos",
          "no_size": "No size in mm"}


@login_required
def quality(request, check):
    if _client(request):
        return redirect("inventory:shelf")
    if check not in rows.CHECKS:
        raise Http404("No such check.")
    everything = _everything(request)
    found = [r for r in everything if rows.CHECKS[check](r)]
    return _page(request, "inventory/quality.html", everything, tab="quality", check=check, title=TITLES[check],
                 pouches=found, money=bool(found) and "pouch_value" in found[0])
```

`inventory/templates/inventory/quality.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}{{ title }}{% endblock %}
{% block crumb %}Data quality &nbsp;›&nbsp; <b>{{ title }}</b>{% endblock %}
{% block content %}
<div class="shelfbar"><h1>{{ title }}</h1><span class="chip">{{ pouches|length|grouped }} pouch{{ pouches|length|pluralize:"es" }}</span></div>
<div class="card" style="overflow:hidden">
  {% if pouches %}{% include "inventory/_pouch_table.html" with show_batch=True %}
  {% else %}<div class="card-b"><span class="hint">None.</span></div>{% endif %}
</div>
{% endblock %}
```

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=finders_t2 ../nornament-app/.venv/bin/pytest inventory/tests/test_quality.py inventory/tests/test_views.py inventory/tests/test_client_view.py inventory/tests/test_finders_rail.py inventory/tests/test_masking.py -p no:warnings`
Expected: PASS.

Run: `POSTGRES_DB=finders_t2 ../nornament-app/.venv/bin/pytest inventory -p no:warnings`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add inventory/rows.py inventory/views_quality.py inventory/templates/inventory/_pouch_table.html \
  inventory/templates/inventory/batch.html inventory/templates/inventory/quality.html inventory/tests/test_quality.py
git commit -m "$(cat <<'EOF'
The four data-quality filters list the pouches the rail counts, in the batch page's table

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Splits & merges and Transfers

**Files:**
- Create: `inventory/templates/inventory/splits.html`, `inventory/templates/inventory/transfers.html`, `inventory/tests/test_split_transfer_lists.py`
- Modify: `inventory/views_lists.py` (replaces the two stubs)

**Interfaces:**
- Consumes: `StockDocument` (`SPLIT`, `TRANSFER`, `from_batch`, `from_pouch_no`, `to_batch`, `to_pouch_no`, `created_by`, `reverses`), `Movement.OUT/IN`, `ledger.ZERO`, `views._client/_everything/_page`, `inventory:document`; in tests `ledger_assort.split_pouch/transfer_pouch/SplitPart`, `ledger.reverse_document`.
- Produces:
  - `views_lists.splits(request)`: every split that is not itself a reversal, newest first (`-created_at`, `-pk`). Row keys `pk`, `number`, `occurred_on`, `source` (`"SL01G · 1"`), `source_ref`, `made` (list of `"SL01G · 3"`), `ct` (carats out of the source, loss included), `reversed`, `by`. `tab="splits"`.
  - `views_lists.transfers(request)`: every transfer that is not itself a reversal, newest first. Row keys `pk`, `number`, `occurred_on`, `ref` (the pouch's `NRN-`), `moved_from`, `moved_to` (`"SL01G · 2"`, `"SL02G · 5"`), `reversed`, `by`. `tab="transfers"`.
  - Both redirect to the shelf in client view. Each row's number links to `inventory:document`.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_split_transfer_lists.py`:

```python
"""The stones rail's Splits & merges and Transfers lists."""
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import ledger
from inventory.ledger_assort import SplitPart, split_pouch, transfer_pouch
from inventory.models import Batch

pytestmark = pytest.mark.django_db
D = Decimal


def _body(client, user, name):
    client.force_login(user)
    return client.get(reverse(name)).content.decode()


def _row(body, number):
    return body.split(f"<b>{number}</b>")[1].split("</tr>")[0]


def test_splits_list_every_split_newest_first(client, accounts_user, sales_user, shelf):
    assert "No splits yet." in _body(client, sales_user, "inventory:splits")
    first = split_pouch(accounts_user, shelf["onyx"], 4, D("2.5"),
                        [SplitPart("3", 2, D("1")), SplitPart("4", 2, D("1"))], loss_ct=D("0.5"))
    second = split_pouch(accounts_user, shelf["ruby"], None, D("10"), [SplitPart("5", None, D("10"))])
    body = _body(client, sales_user, "inventory:splits")
    assert body.index(second.number) < body.index(first.number)
    row = _row(body, first.number)
    assert "SL01G · 1" in row and shelf["onyx"].ref in row and "SL01G · 3, SL01G · 4" in row
    assert "2.50" in row and "Accounts" in row and "Reversed" not in row
    assert f'href="{reverse("inventory:document", args=[first.pk])}"' in body
    assert f'class="on" href="{reverse("inventory:splits")}"' in body


def test_a_reversed_split_reads_reversed_and_its_reversal_is_not_listed(client, accounts_user, shelf):
    doc = split_pouch(accounts_user, shelf["onyx"], 2, D("1"), [SplitPart("3", 2, D("1"))])
    reversal = ledger.reverse_document(accounts_user, doc)
    body = _body(client, accounts_user, "inventory:splits")
    assert "Reversed" in _row(body, doc.number) and reversal.number not in body


def test_transfers_list_where_each_pouch_was_filed_and_where_it_went(client, accounts_user, karigar_user, shelf):
    assert "No transfers yet." in _body(client, karigar_user, "inventory:transfers")
    to = Batch.objects.create(code="SL02G", box_colour_id="G", family="S", cls="L", seq="02")
    doc = transfer_pouch(accounts_user, shelf["ruby"], to, "5")
    body = _body(client, karigar_user, "inventory:transfers")
    row = _row(body, doc.number)
    assert shelf["ruby"].ref in row and "SL01G · 2" in row and "SL02G · 5" in row and "Accounts" in row
    assert f'href="{reverse("inventory:document", args=[doc.pk])}"' in body
    reversal = ledger.reverse_document(accounts_user, doc)
    body = _body(client, karigar_user, "inventory:transfers")
    assert "Reversed" in _row(body, doc.number) and reversal.number not in body


def test_neither_list_is_reachable_in_client_view(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    for name in ("inventory:splits", "inventory:transfers"):
        response = client.get(reverse(name))
        assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf"), name
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=finders_t3 ../nornament-app/.venv/bin/pytest inventory/tests/test_split_transfer_lists.py -p no:warnings`
Expected: FAIL: both lists answer 404 (the stubs), so "No splits yet." is not in the body.

- [ ] **Step 3: The two views**

In `inventory/views_lists.py`, remove `from django.http import Http404` and the two stubs, update the module docstring's first line to

```python
"""The rail's ledger lists: what is out on job work and on memo, recent documents, splits and transfers."""
```

and append:

```python
def _name(user):
    return (user.full_name or user.get_username()) if user else "system"


@login_required
def splits(request):
    """Every split, newest first: the pouch it came out of, the pouches it made, and the carats taken
    out (any loss included). A reversal is not listed on its own: the split it undid reads Reversed.
    Merges join this list when they are built (5c).

    ponytail: every split on one page; page through when there are hundreds.
    """
    if _client(request):
        return redirect("inventory:shelf")
    documents = (StockDocument.objects.filter(kind=Kind.SPLIT, reverses__isnull=True)
                 .select_related("created_by").prefetch_related("movements__pouch__batch")
                 .order_by("-created_at", "-pk"))
    rows = []
    for d in documents:
        moves = sorted(d.movements.all(), key=lambda m: m.pk)
        out = [m for m in moves if m.direction == Movement.OUT]
        source = out[0].pouch if out else None
        rows.append(mask(request.user, {
            "pk": d.pk, "number": d.number, "occurred_on": d.occurred_on,
            "source": str(source) if source else "", "source_ref": source.ref if source else "",
            "made": [str(m.pouch) for m in moves if m.direction == Movement.IN],
            "ct": sum((m.ct or ledger.ZERO for m in out), ledger.ZERO),
            "reversed": d.status == Status.REVERSED, "by": _name(d.created_by),
        }))
    return _page(request, "inventory/splits.html", _everything(request), tab="splits", rows=rows)


@login_required
def transfers(request):
    """Every transfer, newest first: the pouch, where it was filed and where it went. A reversal is
    not listed on its own: the transfer it undid reads Reversed.

    ponytail: every transfer on one page; page through when there are hundreds.
    """
    if _client(request):
        return redirect("inventory:shelf")
    documents = (StockDocument.objects.filter(kind=Kind.TRANSFER, reverses__isnull=True)
                 .select_related("created_by", "from_batch", "to_batch").prefetch_related("movements__pouch")
                 .order_by("-created_at", "-pk"))
    rows = [mask(request.user, {
        "pk": d.pk, "number": d.number, "occurred_on": d.occurred_on,
        "ref": next(iter(d.movements.all())).pouch.ref,
        "moved_from": f"{d.from_batch.code} · {d.from_pouch_no or '?'}",
        "moved_to": f"{d.to_batch.code} · {d.to_pouch_no}",
        "reversed": d.status == Status.REVERSED, "by": _name(d.created_by),
    }) for d in documents]
    return _page(request, "inventory/transfers.html", _everything(request), tab="transfers", rows=rows)
```

- [ ] **Step 4: The two pages**

`inventory/templates/inventory/splits.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Splits &amp; merges{% endblock %}
{% block crumb %}Stock control &nbsp;›&nbsp; <b>Splits &amp; merges</b>{% endblock %}
{% block content %}
<div class="shelfbar"><h1>Splits &amp; merges</h1></div>
<div class="card" style="overflow:hidden"><div style="overflow:auto"><table class="led">
  <thead><tr><th>Document</th><th>Date</th><th>Source pouch</th><th>New pouches</th><th class="r">Carats out</th><th>By</th><th></th></tr></thead>
  <tbody>{% for d in rows %}<tr>
    <td class="mono"><a href="{% url 'inventory:document' d.pk %}"><b>{{ d.number }}</b></a></td>
    <td>{{ d.occurred_on|date:"d M Y" }}</td>
    <td class="mono">{{ d.source }}<div class="hint">{{ d.source_ref }}</div></td>
    <td class="mono">{{ d.made|join:", " }}</td>
    <td class="r">{{ d.ct|ct }}</td>
    <td class="hint">{{ d.by }}</td>
    <td>{% if d.reversed %}<span class="chip crit"><span class="dot"></span>Reversed</span>{% endif %}</td></tr>
  {% empty %}<tr><td colspan="7" class="hint">No splits yet.</td></tr>{% endfor %}</tbody></table></div></div>
{% endblock %}
```

`inventory/templates/inventory/transfers.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Transfers{% endblock %}
{% block crumb %}Stock control &nbsp;›&nbsp; <b>Transfers</b>{% endblock %}
{% block content %}
<div class="shelfbar"><h1>Transfers</h1></div>
<div class="card" style="overflow:hidden"><div style="overflow:auto"><table class="led">
  <thead><tr><th>Document</th><th>Date</th><th>Pouch</th><th>From</th><th>To</th><th>By</th><th></th></tr></thead>
  <tbody>{% for d in rows %}<tr>
    <td class="mono"><a href="{% url 'inventory:document' d.pk %}"><b>{{ d.number }}</b></a></td>
    <td>{{ d.occurred_on|date:"d M Y" }}</td>
    <td class="mono">{{ d.ref }}</td>
    <td class="mono">{{ d.moved_from }}</td>
    <td class="mono">→ {{ d.moved_to }}</td>
    <td class="hint">{{ d.by }}</td>
    <td>{% if d.reversed %}<span class="chip crit"><span class="dot"></span>Reversed</span>{% endif %}</td></tr>
  {% empty %}<tr><td colspan="7" class="hint">No transfers yet.</td></tr>{% endfor %}</tbody></table></div></div>
{% endblock %}
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=finders_t3 ../nornament-app/.venv/bin/pytest inventory/tests/test_split_transfer_lists.py inventory/tests/test_ledger_lists.py inventory/tests/test_assort_views.py inventory/tests/test_masking.py -p no:warnings`
Expected: PASS.

Run: `POSTGRES_DB=finders_t3 ../nornament-app/.venv/bin/pytest inventory -p no:warnings`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add inventory/views_lists.py inventory/templates/inventory/splits.html inventory/templates/inventory/transfers.html \
  inventory/tests/test_split_transfer_lists.py
git commit -m "$(cat <<'EOF'
Splits & merges and Transfers list every document newest first, a reversed one marked Reversed

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: The diamond Movements tab and a ledger per line

**Files:**
- Create: `inventory/templates/inventory/diamonds/movements.html`, `inventory/templates/inventory/diamonds/line.html`, `inventory/tests/test_dia_movements.py`
- Modify: `inventory/views_dia_movements.py` (replaces the stub), `inventory/templates/inventory/diamonds/search.html`

**Interfaces:**
- Consumes: `views_diamonds.viewer/dia_page`; `ledger.DIAMOND_KINDS/party/ZERO`; `Movement.effect`; `dia_services.stocked_lines/rate_table`; `dia_rows.line_row`; `inventory:dia_jobs` (`?card=`), `inventory:dia_assorts` (`?doc=`), `inventory:dia_purchase`; the `dia_movements`/`dia_line` routes and the tab from Task 1. In tests: `ledger_dia_jobs.post_entry`, `ledger.undo_last/reverse_document`, `dia_services.recount_line`, the `dia_docs` and `ledger_docs` fixtures.
- Produces:
  - `views_dia_movements.opens(document, as_role="") -> str`: the URL a diamond document is read at — `dia_jobs?card=<pk>`, `dia_assorts?doc=<pk>` or `dia_purchase` — for the document a reversal reversed, carrying `as`.
  - `views_dia_movements.movements(request)`: the newest 100 diamond documents that are not reversals, newest first (`-created_at`, `-pk`), filtered by `?kind=` when it is a diamond kind. Row keys `pk`, `number`, `kind` (label), `karigar_name`/`vendor_name` (masked), `in_house`, `occurred_on`, `status`, `tone`, `lines`, `href`. `dtab="movements"`.
  - `views_dia_movements._ledger(user, line, as_role="") -> [dict]`, oldest first, each with `when`, `reason`, `note`, `reversal`, `sym`, `cls`, `direction`, `ct`, `balance` (after it, by `Movement.effect`), `number`, `href`, `ref`, `by`.
  - `views_dia_movements.line(request, ref)`: 404 for an unknown ref; else `row` (`dia_rows.line_row`, masked) and `moves` (newest first). `dtab="movements"`.
  - Search stock's table gains a leading Line column: each ref links to `inventory:dia_line`, carrying `?as=`.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_dia_movements.py`:

```python
"""The diamond Movements tab: recent diamond documents, and a ledger per line."""
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import dia_services, ledger, ledger_dia_jobs
from inventory.models import DiamondLine
from inventory.tests.conftest import DIA_COST, DIA_SUPPLIER, KARIGAR
from inventory.views_dia_movements import _ledger

pytestmark = pytest.mark.django_db
D = Decimal


def _get(client, user, url, query=None):
    client.force_login(user)
    return client.get(url, query or {})


def test_the_list_opens_each_document_on_its_own_screen_newest_first(client, accounts_user, dia_docs):
    card, assort, purchase = dia_docs["card"], dia_docs["assort"], dia_docs["purchase"]
    body = _get(client, accounts_user, reverse("inventory:dia_movements")).content.decode()
    assert body.index(purchase.number) < body.index(assort.number) < body.index(card.number)
    assert f'href="{reverse("inventory:dia_jobs")}?card={card.pk}"><b>{card.number}</b>' in body
    assert f'href="{reverse("inventory:dia_assorts")}?doc={assort.pk}"><b>{assort.number}</b>' in body
    assert f'href="{reverse("inventory:dia_purchase")}"><b>{purchase.number}</b>' in body
    assert KARIGAR in body and DIA_SUPPLIER in body
    assert f'class="on" href="{reverse("inventory:dia_movements")}">Movements</a>' in body


def test_the_kind_filter_and_stones_documents_never_listed(client, accounts_user, dia_docs, ledger_docs):
    url = reverse("inventory:dia_movements")
    body = _get(client, accounts_user, url, {"kind": "dia_assort"}).content.decode()
    assert dia_docs["assort"].number in body
    assert dia_docs["card"].number not in body and dia_docs["purchase"].number not in body
    every = _get(client, accounts_user, url).content.decode()
    assert ledger_docs["job"].number not in every and ledger_docs["purchase"].number not in every


def test_a_name_the_viewer_may_not_see_is_absent_never_in_house(client, sales_user, karigar_user, dia_docs):
    body = _get(client, sales_user, reverse("inventory:dia_movements")).content.decode()
    assert KARIGAR not in body and DIA_SUPPLIER not in body and "In-house" not in body
    assert dia_docs["card"].number in body
    assert _get(client, karigar_user, reverse("inventory:dia_movements")).status_code == 200


def test_the_line_ledger_runs_to_what_the_engine_holds(client, accounts_user, dia_docs):
    line, card = dia_docs["round"], dia_docs["card"]
    ledger_dia_jobs.post_entry(accounts_user, card, "set", line, D("0.25"))           # a settle: on hand unchanged
    ledger.undo_last(accounts_user, card)                                            # its reversal: unchanged too
    dia_services.recount_line(accounts_user, line, D("2"), note="re-imported from Sheet!9")    # 2.40 → 2.00
    reversal = ledger.reverse_document(accounts_user, card)                          # the issue undone: + 1
    moves = _ledger(accounts_user, line)
    held = dia_services.stocked_lines(DiamondLine.objects.filter(pk=line.pk)).get().on_ct
    assert [m["balance"] for m in moves] == [D("3.40"), D("2.40"), D("2.40"), D("2.40"), D("2.00"), D("3.00")]
    assert moves[-1]["balance"] == held
    body = _get(client, accounts_user, reverse("inventory:dia_line", args=[line.ref])).content.decode()
    assert "Sheet!3" in body and "re-imported from Sheet!9" in body          # the import's source rows
    assert f'href="{reverse("inventory:dia_jobs")}?card={card.pk}">{card.number}</a>' in body
    assert f'href="{reverse("inventory:dia_jobs")}?card={card.pk}">{reversal.number}</a>' in body
    assert "3.00 ct" in body and "DRFGH VS-SI" in body and "B-771" in body


def test_value_reads_own_cost_first_and_needs_the_cost_right(client, accounts_user, sales_user, dia_docs):
    bought = dia_docs["purchase"].movements.get().diamond
    url = reverse("inventory:dia_line", args=[bought.ref])
    body = _get(client, accounts_user, url).content.decode()
    assert "₹23,456" in body and "₹46,912" in body and DIA_COST not in body      # own cost, not the rate card
    rnd = _get(client, accounts_user, reverse("inventory:dia_line", args=[dia_docs["round"].ref])).content.decode()
    assert f"₹{DIA_COST}" in rnd                                                  # no own cost: the rate card's
    body = _get(client, sales_user, url).content.decode()
    assert "23,456" not in body and "46,912" not in body and "<label>Value</label>" not in body


def test_an_unknown_line_is_404(client, accounts_user, diamonds):
    assert _get(client, accounts_user, reverse("inventory:dia_line", args=["NRD-999999"])).status_code == 404


def test_search_stock_links_each_line_to_its_ledger(client, admin_user_, diamonds):
    rnd = diamonds["round"]
    body = _get(client, admin_user_, reverse("inventory:diamonds")).content.decode()
    assert f'href="{reverse("inventory:dia_line", args=[rnd.ref])}">{rnd.ref}</a>' in body
    body = _get(client, admin_user_, reverse("inventory:diamonds"), {"as": "SALES"}).content.decode()
    assert f'href="{reverse("inventory:dia_line", args=[rnd.ref])}?as=SALES">{rnd.ref}</a>' in body
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=finders_t4 ../nornament-app/.venv/bin/pytest inventory/tests/test_dia_movements.py -p no:warnings`
Expected: FAIL with `ImportError: cannot import name '_ledger' from 'inventory.views_dia_movements'`.

- [ ] **Step 3: The views**

`inventory/views_dia_movements.py` (the whole file):

```python
"""The diamond Movements tab: recent diamond documents, and a ledger per line.

Read-only and readable by every internal login, as the document screens are.
Built for ``viewer(request)``, so an admin's "Viewing as" preview masks like the
role and every link carries it. Diamonds have no client view, so the stones'
Internal / Client flag is not read here.
"""
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.urls import reverse

from stock.masking import mask

from . import dia_rows, dia_services, ledger
from .models import DiamondLine, StockDocument
from .views_diamonds import dia_page, viewer

Kind, Status = StockDocument.Kind, StockDocument.Status
TONE = {Status.OPEN: "warn", Status.CLOSED: "good", Status.REVERSED: "crit"}
SYMBOL = {1: ("＋", "in"), -1: ("−", "out"), 0: ("·", "adj")}
RECENT_CAP = 100
#: where each diamond document is read, and the query that picks it there
SCREEN = {Kind.DIA_JOB: ("inventory:dia_jobs", "card"), Kind.DIA_ASSORT: ("inventory:dia_assorts", "doc"),
          Kind.DIA_PURCHASE: ("inventory:dia_purchase", None)}


def opens(document, as_role=""):
    """The screen a diamond document is read on: its job card, its assortment, or Purchases (which
    lists them; a purchase has no page of its own). A reversal opens the document it reversed."""
    document = document.reverses or document
    name, key = SCREEN[document.kind]
    params = {key: document.pk} if key else {}
    if as_role:
        params["as"] = as_role
    return reverse(name) + (f"?{urlencode(params)}" if params else "")


def _as_role(request, user, role):
    return role if user is not request.user else ""


@login_required
def movements(request):
    """Recent diamond documents, newest first. A reversal is not listed on its own: the document
    it undid reads Reversed.

    ponytail: the newest 100; page through when someone asks for more.
    """
    user, role = viewer(request)
    as_role = _as_role(request, user, role)
    kind = request.GET.get("kind", "")
    documents = (StockDocument.objects.filter(kind__in=ledger.DIAMOND_KINDS, reverses__isnull=True)
                 .select_related("vendor").annotate(lines=Count("movements")))
    if kind in ledger.DIAMOND_KINDS:
        documents = documents.filter(kind=kind)
    rows = [mask(user, {"pk": d.pk, "number": d.number, "kind": d.get_kind_display(), **ledger.party(d),
                        "in_house": d.kind == Kind.DIA_JOB and d.vendor_id is None, "occurred_on": d.occurred_on,
                        "status": d.get_status_display(), "tone": TONE[d.status], "lines": d.lines,
                        "href": opens(d, as_role)})
            for d in documents.order_by("-created_at", "-pk")[:RECENT_CAP]]
    return dia_page(request, "inventory/diamonds/movements.html", dtab="movements", rows=rows, kind=kind,
                    kinds=[(value, label) for value, label in Kind.choices if value in ledger.DIAMOND_KINDS])


def _ledger(user, line, as_role=""):
    """Every movement of the line, oldest first, with the balance after it by the shared rule
    (``Movement.effect``: in adds, out takes, a settle counts 0, a reversal the opposite sign). A
    movement on a document links to that document's screen; an import's opening names the register
    row it came from (its ref), and a recount says so in its note."""
    rows, balance = [], ledger.ZERO
    moves = line.movements.select_related("document__reverses", "recorded_by").order_by("occurred_at", "pk")
    for m in moves:
        balance += m.effect * (m.ct or ledger.ZERO)
        doc = m.document
        symbol, cls = SYMBOL[m.effect]
        rows.append(mask(user, {
            "when": m.occurred_at, "reason": m.reason, "note": m.note, "reversal": bool(m.reverses_id),
            "sym": symbol, "cls": cls, "direction": m.get_direction_display(), "ct": m.ct, "balance": balance,
            "number": doc.number if doc else "", "href": opens(doc, as_role) if doc else "",
            "ref": m.ref if not doc or m.ref != doc.number else "",
            "by": (m.recorded_by.full_name or m.recorded_by.get_username()) if m.recorded_by_id else "system",
        }))
    return rows


@login_required
def line(request, ref):
    user, role = viewer(request)
    found = get_object_or_404(dia_services.stocked_lines(DiamondLine.objects.filter(ref=ref)))
    moves = _ledger(user, found, _as_role(request, user, role))
    return dia_page(request, "inventory/diamonds/line.html", dtab="movements",
                    row=dia_rows.line_row(user, found, dia_services.rate_table()), moves=list(reversed(moves)))
```

- [ ] **Step 4: The pages**

`inventory/templates/inventory/diamonds/movements.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Movements · Diamonds{% endblock %}
{% block crumb %}<b>Diamonds</b> &nbsp;›&nbsp; Movements{% endblock %}
{% block content %}
{% include "inventory/diamonds/_dsub.html" %}
<div class="dbanner"><h2>Movements</h2></div>

<div class="filterbar">
  <div class="fsel"><label>Kind</label>
    <form method="get" style="display:contents">
      {% if as_role %}<input type="hidden" name="as" value="{{ as_role }}">{% endif %}
      <select class="inp" name="kind" onchange="this.form.submit()"><option value="">All kinds</option>
        {% for value, label in kinds %}<option value="{{ value }}"{% if value == kind %} selected{% endif %}>{{ label }}</option>{% endfor %}</select></form></div>
</div>

<div class="card" style="overflow:hidden"><div style="overflow:auto"><table class="led">
  <thead><tr><th>Date</th><th>Document</th><th>Kind</th><th>Karigar / supplier</th><th class="r">Lines</th><th>Status</th></tr></thead>
  <tbody>{% for d in rows %}<tr>
    <td>{{ d.occurred_on|date:"d M Y" }}</td>
    <td class="mono"><a href="{{ d.href }}"><b>{{ d.number }}</b></a></td>
    <td>{{ d.kind }}</td>
    <td>{% if 'karigar_name' in d %}{{ d.karigar_name }}{% elif 'vendor_name' in d %}{{ d.vendor_name }}{% elif d.in_house %}In-house{% else %}<span class="hint">—</span>{% endif %}</td>
    <td class="r">{{ d.lines }}</td>
    <td><span class="chip {{ d.tone }}"><span class="dot"></span>{{ d.status }}</span></td></tr>
  {% empty %}<tr><td colspan="6" class="hint">No diamond documents yet.</td></tr>{% endfor %}</tbody></table></div></div>
{% endblock %}
```

`inventory/templates/inventory/diamonds/line.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}{{ row.ref }} · Diamonds{% endblock %}
{% block crumb %}<b>Diamonds</b> &nbsp;›&nbsp; <a href="{% url 'inventory:dia_movements' %}{% if as_role %}?as={{ as_role }}{% endif %}">Movements</a> &nbsp;›&nbsp; <b class="mono">{{ row.ref }}</b>{% endblock %}
{% block content %}
{% include "inventory/diamonds/_dsub.html" %}
<div class="dbanner"><h2><span class="mono">{{ row.ref }}</span> · <span class="mono">{{ row.item_code }}</span></h2></div>

<div class="filterbar">
  <div class="fsel"><label>Category</label><div class="ro2">{{ row.category }}</div></div>
  <div class="fsel"><label>Shape</label><div class="ro2">{{ row.shape }}</div></div>
  <div class="fsel"><label>Colour</label><div class="ro2">{{ row.colour|default:"—" }}</div></div>
  <div class="fsel"><label>Clarity</label><div class="ro2">{{ row.clarity|default:"—" }}</div></div>
  <div class="fsel"><label>Size</label><div class="ro2 mono">{{ row.size_text|default:"—" }}</div></div>
  <div class="fsel"><label>Band</label><div class="ro2 mono">{{ row.band }}</div></div>
  <div class="fsel"><label>Batch</label><div class="ro2 mono">{{ row.batch|default:"none" }}</div></div>
  <div class="fsel"><label>On hand</label><div class="ro2">{{ row.ct|ct }} ct</div></div>
  {% if 'cost_amount' in row %}<div class="fsel"><label>Cost / ct</label><div class="ro2">{% if row.cost_rate is not None %}{{ row.cost_rate|rupees }}{% else %}<span class="hint">not set</span>{% endif %}</div></div>
  <div class="fsel"><label>Value</label><div class="ro2">{{ row.cost_amount|rupees }}</div></div>{% endif %}
</div>

<div class="card" style="overflow:hidden">
  <div class="card-h"><span class="card-t">Movement ledger</span><span class="spacer"></span>
    <span class="hint">{{ moves|length }} movement{{ moves|length|pluralize }}</span></div>
  <div style="overflow:auto"><table class="led">
    <thead><tr><th>Date</th><th>Reason</th><th>Document</th><th>Dir</th><th class="r">Carats</th><th class="r">Balance after</th><th>By</th></tr></thead>
    <tbody>{% for m in moves %}<tr>
      <td>{{ m.when|date:"d M Y" }}<div class="hint">{{ m.when|date:"H:i" }}</div></td>
      <td><span class="chip">{{ m.reason }}</span>{% if m.reversal %}<div class="hint">↺ reversal</div>{% endif %}{% if m.note %}<div class="hint">{{ m.note }}</div>{% endif %}</td>
      <td>{% if m.href %}<div class="chal"><a href="{{ m.href }}">{{ m.number }}</a>{% if m.ref %} · {{ m.ref }}{% endif %}</div>
        {% elif m.ref %}<div class="chal">{{ m.ref }}</div>{% else %}<span class="hint">—</span>{% endif %}</td>
      <td class="dir {{ m.cls }}">{{ m.sym }} {{ m.direction }}</td>
      <td class="r">{{ m.ct|ct }}</td>
      <td class="r">{{ m.balance|ct }} ct</td>
      <td class="hint">{{ m.by }}</td></tr>
    {% empty %}<tr><td colspan="7" class="hint">No movements.</td></tr>{% endfor %}</tbody></table></div>
</div>
{% endblock %}
```

- [ ] **Step 5: Search stock's line refs**

In `inventory/templates/inventory/diamonds/search.html`, the table header line

```django
    <thead><tr><th>Category</th><th>Shape</th><th>Colour</th><th>Clarity</th><th>Size</th><th>Batch</th><th class="r">Carats</th>
```

becomes

```django
    <thead><tr><th>Line</th><th>Category</th><th>Shape</th><th>Colour</th><th>Clarity</th><th>Size</th><th>Batch</th><th class="r">Carats</th>
```

and the first row cells

```django
    <tbody>{% for r in rows %}<tr>
      <td>{{ r.category }}</td><td>{{ r.shape }}</td>
```

become

```django
    <tbody>{% for r in rows %}<tr>
      <td class="mono" style="font-size:11px"><a href="{% url 'inventory:dia_line' r.ref %}{% if as_role %}?as={{ as_role }}{% endif %}">{{ r.ref }}</a></td>
      <td>{{ r.category }}</td><td>{{ r.shape }}</td>
```

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=finders_t4 ../nornament-app/.venv/bin/pytest inventory/tests/test_dia_movements.py inventory/tests/test_dia_search_view.py inventory/tests/test_dia_wiring.py inventory/tests/test_masking.py -p no:warnings`
Expected: PASS.

Run: `POSTGRES_DB=finders_t4 ../nornament-app/.venv/bin/pytest inventory -p no:warnings`
Expected: PASS, the real-file and parity tests included.

- [ ] **Step 7: Commit**

```bash
git add inventory/views_dia_movements.py inventory/templates/inventory/diamonds/movements.html \
  inventory/templates/inventory/diamonds/line.html inventory/templates/inventory/diamonds/search.html \
  inventory/tests/test_dia_movements.py
git commit -m "$(cat <<'EOF'
The diamond Movements tab lists diamond documents by kind, and each line has its own ledger

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: The Suppliers link, the masking walk over every new page, and the spec records the plan's decisions

**Files:**
- Modify: `inventory/templates/inventory/_rail.html` (the Suppliers line), `inventory/tests/test_finders_rail.py` (appends), `inventory/tests/test_masking.py`, `inventory/tests/conftest.py`, `docs/superpowers/specs/2026-10-02-inventory-lists-and-finders-design.md`

**Interfaces:**
- Consumes: every URL name from Task 1; the `ledger_docs` and `dia_docs` fixtures; `ledger_assort.split_pouch/transfer_pouch/SplitPart`; `DiamondLine`, `Movement`.
- Produces:
  - The rail's Suppliers item links to `inventory:dia_settings` + `#suppliers` for a login holding `inv_masters` and `view_vendor`, outside client view; a padlock otherwise.
  - Fixture `finder_docs`: `{"stones": ledger_docs, "dia": dia_docs, "split": <SPL- document>, "transfer": <TRF- document>}`.
  - `test_masking.FINDER_SCREENS` joins the every-screen check; `PENDING` is gone.

- [ ] **Step 1: The Suppliers link, test first**

Append to `inventory/tests/test_finders_rail.py`:

```python
def test_suppliers_opens_the_supplier_card_for_whoever_keeps_suppliers(client, accounts_user, production_user,
                                                                       sales_user, shelf):
    target = f'href="{reverse("inventory:dia_settings")}#suppliers"'
    body = _shelf(client, accounts_user)
    assert target in body and 'Suppliers<span class="ct">🔒' not in body
    assert 'id="suppliers"' in client.get(reverse("inventory:dia_settings")).content.decode()
    client.post(reverse("inventory:set_view"), {"view": "client"})
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert target not in body and 'Suppliers<span class="ct">🔒' in body
    for user in (production_user, sales_user):          # Production sees suppliers but does not edit settings
        body = _shelf(client, user)
        assert target not in body and 'Suppliers<span class="ct">🔒' in body, user
```

Run: `POSTGRES_DB=finders_t5 ../nornament-app/.venv/bin/pytest inventory/tests/test_finders_rail.py -p no:warnings`
Expected: FAIL on `target in body` (Suppliers is still padlocked).

In `inventory/templates/inventory/_rail.html`, the Commercial line

```django
  <span class="locked"><span class="ic">⌗</span>Suppliers<span class="ct">🔒</span></span>
```

becomes

```django
  {% if caps.inv_masters and caps.view_vendor and not client_view %}<a href="{% url 'inventory:dia_settings' %}#suppliers"><span class="ic">⌗</span>Suppliers</a>
  {% else %}<span class="locked"><span class="ic">⌗</span>Suppliers<span class="ct">🔒</span></span>{% endif %}
```

Run the same command. Expected: PASS.

- [ ] **Step 2: A split and a transfer beside every document a name or a cost can leak from**

Append to `inventory/tests/conftest.py`:

```python
@pytest.fixture
def finder_docs(admin_user_, ledger_docs, dia_docs):
    """Every stones and diamond document the ledger fixtures make, plus a split of the onyx and a
    transfer of the ruby. The two fixtures share keys (``purchase``, ``supplier``), so each keeps
    its own dict."""
    from inventory.ledger_assort import SplitPart, split_pouch, transfer_pouch
    from inventory.models import Batch

    split = split_pouch(admin_user_, ledger_docs["onyx"], 2, Decimal("1"), [SplitPart("7", 2, Decimal("1"))])
    to = Batch.objects.create(code="SL02G", box_colour_id="G", family="S", cls="L", seq="02")
    transfer = transfer_pouch(admin_user_, ledger_docs["ruby"], to, "5")
    return {"stones": ledger_docs, "dia": dia_docs, "split": split, "transfer": transfer}
```

- [ ] **Step 3: Extend the walk**

In `inventory/tests/test_masking.py`:

1. The imports become (adding `from urllib.parse import urlencode` at the top):

```python
from urllib.parse import urlencode

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from inventory.models import DiamondLine, Movement, StockDocument
from inventory.tests.conftest import (
    CUSTOMER, DIA_COST, DIA_COST_VALUE, DIA_LINE_COST, DIA_OVERRIDE, DIA_SALE, DIA_SALE_VALUE, DIA_SUPPLIER, KARIGAR,
    PURCHASE_COST, SUPPLIER, VALUE,
)
```

2. Delete `PENDING`. In `test_every_inventory_screen_is_walked`:

```python
    covered = ({name for name, _, _ in SCREENS} | {name for name, _ in DIAMOND_SCREENS} | LEDGER_SCREENS
               | DIA_LEDGER_SCREENS | FINDER_SCREENS)
```

```python
    missing = named - covered - EXEMPT
```

3. Append the finders' walk at the end of the file:

```python
#: part 5a's finders, walked by test_no_finder_shows_a_login_what_it_may_not_see
FINDER_SCREENS = {"inventory:search", "inventory:quality", "inventory:splits", "inventory:transfers",
                  "inventory:dia_movements", "inventory:dia_line"}

#: what each login may not see on a finder (Production sees suppliers and karigars; the Karigar desk, karigars)
FINDER_SECRETS = {
    "sales_user": ("7,919", PURCHASE_COST, SUPPLIER, KARIGAR, DIA_SUPPLIER, DIA_LINE_COST, DIA_OVERRIDE, DIA_COST),
    "karigar_user": ("7,919", PURCHASE_COST, SUPPLIER, CUSTOMER, DIA_SUPPLIER, DIA_LINE_COST, DIA_OVERRIDE, DIA_COST),
    "production_user": ("7,919", PURCHASE_COST, CUSTOMER, DIA_LINE_COST, DIA_OVERRIDE, DIA_COST),
    "graphic_user": ("7,919", PURCHASE_COST, SUPPLIER, KARIGAR, CUSTOMER, DIA_SUPPLIER, DIA_LINE_COST, DIA_OVERRIDE,
                     DIA_COST),
}


def _dia_finder_urls():
    """The diamond Movements list, each kind of it, and every line's ledger."""
    movements = reverse("inventory:dia_movements")
    return ([movements] + [f"{movements}?kind={kind}" for kind in ("dia_job", "dia_assort", "dia_purchase")]
            + [reverse("inventory:dia_line", args=[ref]) for ref in DiamondLine.objects.values_list("ref", flat=True)])


def _stones_finder_urls(d):
    """Search (each kind of match), the four filters, and the two lists."""
    search = reverse("inventory:search")
    queries = ("SL01G", "Onyx", d["stones"]["onyx"].ref, "SL01G 7", "B-771", "DRFGH", "NRD-000001")
    return ([f"{search}?{urlencode({'q': q})}" for q in queries]
            + [reverse("inventory:quality", args=[check]) for check in ("misfiled", "no_pouch_no", "no_photo", "no_size")]
            + [reverse("inventory:splits"), reverse("inventory:transfers")])


@pytest.mark.parametrize("fixture", sorted(FINDER_SECRETS))
def test_no_finder_shows_a_login_what_it_may_not_see(client, finder_docs, request, fixture):
    client.force_login(request.getfixturevalue(fixture))
    for url in _stones_finder_urls(finder_docs) + _dia_finder_urls():
        response = client.get(url)
        assert response.status_code == 200, f"{url} returned {response.status_code}"
        body = response.content.decode()
        for secret in FINDER_SECRETS[fixture]:
            assert secret not in body, f"{url} leaked {secret!r} to {fixture}"


@pytest.mark.parametrize("role", ["SALES", "KARIGAR", "PRODUCTION", "GRAPHIC"])
def test_an_admin_preview_of_each_diamond_finder_masks_like_the_role(client, admin_user_, finder_docs, role):
    client.force_login(admin_user_)
    for url in _dia_finder_urls():
        previewed = f"{url}{'&' if '?' in url else '?'}as={role}"
        body = client.get(previewed).content.decode()
        for secret in DIA_SECRETS[role]:
            assert secret not in body, f"{previewed} leaked {secret!r}"


def test_each_finder_shows_names_and_cost_to_those_who_may_see_them(client, accounts_user, finder_docs):
    client.force_login(accounts_user)
    assert "₹7,919" in client.get(reverse("inventory:quality", args=["no_photo"])).content.decode()
    movements = client.get(reverse("inventory:dia_movements")).content.decode()
    assert KARIGAR in movements and DIA_SUPPLIER in movements
    assorted = finder_docs["dia"]["assort"].movements.get(reason=Movement.Reason.ASSORT_IN).diamond
    assert DIA_OVERRIDE in client.get(reverse("inventory:dia_line", args=[assorted.ref])).content.decode()
    splits = client.get(reverse("inventory:splits")).content.decode()
    assert finder_docs["split"].number in splits and "SL01G · 7" in splits
    assert "SL02G · 5" in client.get(reverse("inventory:transfers")).content.decode()


def test_client_view_reaches_no_stones_finder(client, admin_user_, finder_docs):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    for url in _stones_finder_urls(finder_docs):
        response = client.get(url)
        assert response.status_code == 302 and response["Location"] == reverse("inventory:shelf"), url
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert f'action="{reverse("inventory:search")}"' not in body and "Search batch, pouch, stone… 🔒" in body
```

- [ ] **Step 4: Run the walk**

Run: `POSTGRES_DB=finders_t5 ../nornament-app/.venv/bin/pytest inventory/tests/test_masking.py inventory/tests/test_finders_rail.py -p no:warnings`
Expected: PASS. A leak names the screen and the value. Fix it with a key test in the template or a `mask()` in the row, never a capability test.

- [ ] **Step 5: Record the planning decisions in the spec**

Append to `docs/superpowers/specs/2026-10-02-inventory-lists-and-finders-design.md`:

```markdown
## Changed while planning

- **Routes.** `search/`, `quality/<check>/` (misfiled, no_pouch_no, no_photo, no_size), `splits/`, `transfers/`, `diamonds/movements/`, `diamonds/lines/<ref>/`.
- **The search box** is a small form in the top bar on both sides. It is not the shell's `.search` box, which the phone layout hides, so it works on a phone too. In client view it stays padlocked, and the results page redirects to the shelf. On the diamond side, which has no client view, it is always live.
- **Matching.** A pouch ref, a batch code, a line ref and a batch no. match exactly. A stone name and an item code match by "contains". Case never matters. "Batch · pouch no." is read with or without the `·` (`SL01G · 1`, `SL01G 1`, `SL01G·1`). An item code is read the register's way (`drfgh vs si` finds `DRFGH VS-SI`). Each group shows the first 50 and says "first 50 of N". Pouches and lines with nothing on hand are found too.
- **Data-quality filters** share one predicate per check with the rail's counts (`rows.CHECKS`), so a list always holds exactly the rail's count. They use the batch page's pouch table (now one include) with a Batch column in front. Money shows as on the batch page, by the cost right. An unknown check is 404.
- **Splits & merges and Transfers.** A reversal is not listed on its own; the document it undid carries a Reversed chip. "Carats out" includes the split's loss. The pouches are named as they are filed now. Newest first is by when the document was posted.
- **Diamond Movements.** It lists the newest 100 documents and leaves out reversals, as the two stones lists do. A job card opens on Job cards (`?card=`), an assortment on Assortments (`?doc=`, which only the Assort right can read), and a purchase on Purchases, because a purchase has no page of its own. A line's ledger shows its movements newest first, as the pouch ledger does. On that ledger a reversal's number links to the document it reversed. Value is the cost value only (own cost first, else the rate card), shown with the cost right; the sale side is not shown. Diamond pages ignore the stones' Internal / Client flag, as diamond Search does, and carry an admin's "Viewing as".
- **Search stock** gains a Line column: each `NRD-` ref links to its ledger, carrying the preview.
- **Suppliers** is padlocked in client view as well.
- **Three earlier assertions changed.** They checked padlocks this part removes: the stones Transfers item and the diamond Movements tab (twice). They now check the link.
```

- [ ] **Step 6: Run the whole suite**

Run: `POSTGRES_DB=finders_t5 ../nornament-app/.venv/bin/pytest -p no:warnings`
Expected: only the known pre-existing S3 failure. Every earlier test is green and unchanged apart from Task 1's three padlock assertions. The real diamond file test passes (281 lines, 546.96 ct, cost ₹1,47,98,794 ± ₹10), and so do both parity tests.

Run: `POSTGRES_DB=finders_t5 ../nornament-app/.venv/bin/python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 7: Commit**

```bash
git add inventory/templates/inventory/_rail.html inventory/tests/test_finders_rail.py inventory/tests/test_masking.py \
  inventory/tests/conftest.py docs/superpowers/specs/2026-10-02-inventory-lists-and-finders-design.md
git commit -m "$(cat <<'EOF'
Suppliers opens diamond Settings' supplier card by right; the masking walk covers every finder; the spec records the plan's decisions

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Decided while planning

The spec did not pin these down. Task 5 records them in the spec's "Changed while planning".

1. **Routes and modules.** `inventory:search` (`views_search`), `inventory:quality` with the check's name (`views_quality`), `inventory:splits` and `inventory:transfers` (in `views_lists`, beside the other rail lists), `inventory:dia_movements` and `inventory:dia_line` (`views_dia_movements`). Task 1 routes all six. The five that Task 1 does not build point at `Http404` stubs. All six are `PENDING` in the every-screen check until Task 5 walks them.
2. **The search box** is a `<form>` with an `.inp` input, not the shell's `.search` box, because `.search` is `display:none` below 860px and the box must work on a phone. There is no new CSS; the size is set by inline style. In client view the box stays the padlocked `.search` div and the results view redirects to the shelf. On the diamond side the box is always live, because diamond pages never set `client_view`.
3. **Matching.**
   - **Exact, case-insensitive:** a pouch ref, a batch code, a line ref and a batch no.
   - **Contains, case-insensitive:** a stone name and an item code.
   - **Batch · pouch no.:** any query that splits into two words once `·` is read as a space.
   - **Item codes** go through `dia_rules.canonical_code(q.upper())`, so `drfgh vs si` finds `DRFGH VS-SI`. Prefix search (`SL01` finding `SL01G`) is left out, because the spec names whole codes.
   - **Results:** 50 per group, with "first 50 of N" when capped. Lines and pouches at zero are found, because a search is for finding, not for stock. Results carry no money keys at all.
4. **Data-quality filters.** The four predicates move into `rows.CHECKS`. `summarise` counts through them, and its numbers are unchanged. The filter applies the same predicate to the same `_everything(request)` rows, so the count equals the rail's by construction. The batch page's table moves into `_pouch_table.html` unchanged (the batch page renders identically), with an optional Batch column for a list that spans batches. Every internal role may open a filter, as every internal role sees the rail.
5. **Splits & merges and Transfers.** Each lists documents that are not reversals. A reversed one shows a Reversed chip, and its `REV-` document is not a row of its own. Columns follow the spec: a split shows its source pouch with its ref, its new pouches, carats out (split plus loss) and by; a transfer shows its pouch ref, from → to as recorded on the document, and by. Rows are newest first by `created_at`, and each number opens `inventory:document`. There is no cap yet (`ponytail:` noted in the docstrings).
6. **Diamond Movements list.** It shows diamond kinds only, leaves out reversals and is capped at 100, like the stones Movements list. The kind filter is a select of the three diamond kinds. A job card's counterparty column reads "In-house" only through the `in_house` key, never because a karigar was masked. `opens()` maps a job card to `dia_jobs?card=`, an assortment to `dia_assorts?doc=` and a purchase to `dia_purchase`, which lists recent purchases and has no per-document page. A login without the Assort right lands on "Not permitted", which is the existing screen's own rule. `?as=` is carried while previewing.
7. **The line ledger.** It shows its rows newest first, as the pouch ledger does. The balance is summed oldest first through `Movement.effect`, which is the `balance()` rule row by row, so the newest row's balance equals `stocked_lines().on_ct`. The Dir column shows the symbol and In / Out / Settle. A document links through `opens()`, and a reversal's `REV-` number opens the document it reversed. A movement with no document shows its `ref`: an import opening's ref is its register row (`Sheet!3`), and a recount carries its source in its note ("re-imported from Sheet!9"), which shows under the reason. Details come from `dia_rows.line_row`, so cost is the line's own cost first, else the rate card, and masked. Only Cost / ct and Value (`cost_amount`) are printed; the sale side is not. Every internal role may read it.
8. **Diamond pages and client view.** The Movements list and the line ledger ignore the stones' Internal / Client session flag. Diamond Search and the diamond ledgers already do, and the spec says diamonds have no client view. Only the stones finders redirect.
9. **Search stock's line refs.** The Search stock table had no ref column, so it gains a leading Line column with each `NRD-` ref linking to its ledger. The Item code cell is untouched, so `test_dia_search_view`'s `"DRFGH VS-SI</td>"` assertion keeps its meaning.
10. **Suppliers** is live for `inv_masters` + `view_vendor`, matching diamond Settings: the page needs Edit settings and the supplier card needs supplier sight. It is padlocked for everyone else **and in client view**, since the Commercial section shows in client view and no 5a screen is reachable there.
11. **Rail and tab wiring all in Task 1**, so no two parallel tasks edit `_rail.html` or `inventory_base.html`. The Suppliers line is Task 5's alone. Diamond stock stays `on` for every diamond page except Purchase and Movements.
12. **Three existing assertions change.** Each asserted a padlock the spec removes: Transfers in `test_ledger_lists`, and the diamond Movements tab in `test_dia_purchase_view` and `test_dia_wiring`. Task 1 rewrites each to assert the link and keeps their Stock take(s) padlock checks. The `test_dia_wiring` test is renamed `test_the_diamond_stock_take_tab_stays_locked`. No other existing test is edited.
13. **Merges** are not built here. Splits & merges lists splits only until 5c.
