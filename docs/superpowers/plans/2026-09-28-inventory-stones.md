# Inventory Part 1 (Stones) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the stones half of the Nornament Inventory prototype into working screens inside nornament-app — the shelf by box colour → batch → pouch, pouch detail with working Save / Add price / photos, a real movement ledger, a staff-only client view, and an importer for the owner's stones register.

**Architecture:** A new Django app `inventory` with its own shell (`templates/inventory_base.html`) and stylesheet (`static/css/inventory.css`, lifted verbatim from the prototype's `_head.html`). Pure rules in `inventory/rules.py`, writes in `inventory/services.py`, one row builder in `inventory/rows.py` that ends in the existing `stock.masking.mask()`, and an importer in `inventory/importers/` shaped like the IVY one (parse → analyse → review → commit). Quantities are never stored on a pouch: they are the sum of its movements.

**Tech Stack:** Django 5.2, Postgres 17, pytest + pytest-django, openpyxl 3.1 (already installed), htmx (vendored, unused here), `mediahub` for photos.

**Spec:** `docs/superpowers/specs/2026-09-28-inventory-stones-design.md` (decisions: `2026-09-28-inventory-overview.md`)

**Prototype source (read, never edit):** `../Nornament_Inventory/04-source-scripts/_head.html` (CSS lines 8–443, markup 446–576), `_script.html` lines 1–613 (stones logic), `build_ui.py` (loader).

## Global Constraints

- Follow the surrounding style: docstrings say *why*; no type annotations except dataclass fields (which `@dataclass` needs).
- All writes go through `inventory/services.py`. Views never write models directly.
- Masking is decided in one place: rows go through `stock.masking.mask()`. Templates test key presence (`{% if 'pouch_value' in row %}`), never capabilities, for anything money-shaped.
- Reuse, do not duplicate: `stock.services.ServiceError`, `stock.services.require`, `stock.services.log`, `stock.models.Vendor`, `stock.models.ImportBatch`, `stock.views._store_workbook`, `stock.views._batch_workbook`, `mediahub.services.attach_uploads`, `crm.templatetags.crm_extras.inr`.
- Terminology on screen: **Box colour → Batch (`SR01Y`) → Pouch (1, 2, 3)**. Source columns: `New Gati Code` = batch, `Batch No.` = pouch no.
- Prose stripped: no provenance badges ("in your file", "new field", "derived"), no footers, no explainer banners. Functional warnings stay.
- Items the prototype only names render padlocked (`🔒`, disabled), never as dead links.
- New capabilities: `inv_masters` (used now), `inv_purchase`, `inv_job`, `inv_assort` (declared for parts 2–4). New group `KARIGAR`.
- Client view is a session flag; in client mode the server never sends batch code, pouch no., carton, remarks, src, rates, values, supplier or data-quality flags. URLs address batches by pk and pouches by `NRN-` ref so no URL carries a batch code.
- Tests live in `inventory/tests/`; those that touch the database start with `pytestmark = pytest.mark.django_db` (pure-function tests do not), and use the real role-group fixtures from the root `conftest.py`.
- Run tests from the worktree root as: `../nornament-app/.venv/bin/pytest <path> -v` (the worktree's `.env` is a symlink to the main checkout's; `.venv` is not linked because it is not gitignored).

## Deviations from the spec, decided while planning

These are recorded in the spec by Task 12.

1. **No `inv_stones` tab.** Every role may open the stone shelf, so a `ROLE_TABS` entry would gate nothing — and it would turn the stock sidebar's "N of 10 tabs visible" into "11 of 10". Views are `login_required`; writes are gated by capability in the service.
2. **Misfiled rule follows the prototype exactly:** only box colours whose label starts with `?` are exempt. `BY` (Brown-Yellow) is unconfirmed but labelled, so its pouches are checked — that is how the prototype reaches 127.
3. **Size is parsed from `size_text` when read**, not stored as `size_kind`/`length_mm`/`width_mm`. Nothing in part 1 queries those columns.
4. **A rate of zero is allowed**; only a negative rate is refused. The sheet may carry zero rates, and the prototype valued them at ₹0 rather than "cannot be valued".
5. **The inventory masking walk lives in `inventory/tests/test_masking.py`** with its own every-screen-is-walked check, rather than widening the stock/CRM walk.
6. **Client view does not show a list price** — the per-client price flag is deferred, so a client sees "Available — enquire for price".
7. **Only database-touching tests carry `pytestmark = pytest.mark.django_db`.** Pure-function tests (`test_rules.py`, `test_import_parse.py`) do not. Ruled during execution.

## File Structure

| File | Responsibility |
|---|---|
| `inventory/__init__.py`, `inventory/apps.py` | the app |
| `inventory/seed.py` | the prototype's box-colour, family and class tables, as data |
| `inventory/models.py` | `BoxColour`, `CodePart`, `Batch`, `Pouch`, `Movement`, `PriceEntry` |
| `inventory/migrations/0001_initial.py` | generated |
| `inventory/migrations/0002_seed_codes.py` | loads `seed.py` |
| `inventory/rules.py` | pure rules ported from the prototype: batch code, size, colour family, colour hex, misfiled, silhouette SVG |
| `inventory/services.py` | on-hand query, value, open pouches, save details, add price, recount |
| `inventory/rows.py` | row builder (mask + client strip), summaries, shares, batch-code decoder |
| `inventory/importers/__init__.py` | package marker |
| `inventory/importers/stones.py` | read the stones register into `Row`s |
| `inventory/importers/plan.py` | analyse rows into `Item`s, read review decisions, commit |
| `inventory/templatetags/__init__.py`, `inventory_extras.py` | `rupees`, `ct`, `grouped`, `kg` filters and the `silhouette` tag |
| `inventory/views.py`, `inventory/urls.py` | thin views, `inventory:` namespace |
| `inventory/templates/inventory/*.html` | the screens |
| `templates/inventory_base.html` | the shell |
| `static/css/inventory.css` | prototype CSS verbatim + compat, dark mode, phone drawer |
| `accounts/capabilities.py`, `accounts/models.py`, `accounts/migrations/0004_inventory_capabilities.py` | the four capabilities and KARIGAR |
| `stock/masking.py` | six new gated field names |
| `stock/context_processors.py` | stamp `inventory.css` too |
| `stock/templates/stock/_nav.html`, `templates/crm_base.html` | link to the inventory |
| `crm/views.py` | `?item=` prefill for a new enquiry (the client-view Enquire button) |
| `config/settings.py`, `config/urls.py`, `conftest.py` | wiring and two user fixtures |
| `inventory/tests/…` | tests per task |

---

### Task 1: The app, the four capabilities, and the Karigar desk

**Files:**
- Create: `inventory/__init__.py`, `inventory/apps.py`, `inventory/views.py`, `inventory/urls.py`, `inventory/tests/__init__.py`, `inventory/tests/test_roles.py`
- Create: `accounts/migrations/0004_inventory_capabilities.py`
- Modify: `config/settings.py` (INSTALLED_APPS), `config/urls.py`, `accounts/capabilities.py`, `accounts/models.py` (`Capability.Meta.permissions`), `conftest.py`

**Interfaces:**
- Produces: `accounts.capabilities.INV_MASTERS`, `INV_PURCHASE`, `INV_JOB`, `INV_ASSORT` (strings `"accounts.inv_masters"` …); group `"KARIGAR"`; fixtures `karigar_user`, `production_user`; URL namespace `inventory`.

- [ ] **Step 1: Write the failing test**

`inventory/tests/test_roles.py`:

```python
"""Who holds which inventory right — the prototype's matrix, mapped onto our groups."""
import pytest

from accounts.capabilities import (
    INV_ASSORT, INV_JOB, INV_MASTERS, INV_PURCHASE, VIEW_COST, VIEW_MARGIN, VIEW_SALE,
)

pytestmark = pytest.mark.django_db

INVENTORY = (INV_MASTERS, INV_PURCHASE, INV_JOB, INV_ASSORT)


def test_owner_and_accounts_hold_every_inventory_right(admin_user_, accounts_user):
    for user in (admin_user_, accounts_user):
        for perm in INVENTORY:
            assert user.has_perm(perm), f"{user} lacks {perm}"


def test_the_karigar_desk_posts_job_cards_and_sees_no_money(karigar_user):
    assert karigar_user.has_perm(INV_JOB)
    for perm in (INV_MASTERS, INV_PURCHASE, INV_ASSORT, VIEW_COST, VIEW_SALE, VIEW_MARGIN):
        assert not karigar_user.has_perm(perm), f"karigar holds {perm}"


def test_production_is_stock_staff(production_user):
    assert production_user.has_perm(INV_JOB)
    assert not production_user.has_perm(INV_MASTERS)
    assert not production_user.has_perm(INV_ASSORT)


def test_sales_holds_no_inventory_right(sales_user):
    for perm in INVENTORY:
        assert not sales_user.has_perm(perm)


def test_the_karigar_desk_opens_no_stock_tab():
    from accounts.capabilities import ROLE_TABS

    assert ROLE_TABS["KARIGAR"] == ()
```

- [ ] **Step 2: Run it to see it fail**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_roles.py -v`
Expected: collection error — `inventory` is not an installed app / `INV_MASTERS` cannot be imported.

- [ ] **Step 3: Create the app**

`inventory/__init__.py`:

```python
"""Loose stones and diamonds: the raw material, before it is set into a piece.

Ported from the Nornament Inventory prototype. The finished-goods stock app is
``stock``; this is the material that goes into it.
"""
```

`inventory/apps.py`:

```python
from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = "inventory"
    verbose_name = "Stones and diamonds"
    default_auto_field = "django.db.models.BigAutoField"
```

`inventory/views.py`:

```python
"""The inventory screens. Thin: services write, rows mask, templates draw."""
```

`inventory/urls.py`:

```python
from django.urls import path  # noqa: F401  (routes arrive with their screens)

from . import views  # noqa: F401

app_name = "inventory"

urlpatterns = []
```

`inventory/tests/__init__.py`: empty file.

In `config/settings.py`, add `"inventory",` to `INSTALLED_APPS` after `"etl",`.

In `config/urls.py`, add after the `crm/` line:

```python
    path("inventory/", include("inventory.urls")),
```

- [ ] **Step 4: Add the capabilities**

In `accounts/capabilities.py`, after `EDIT_BOM = "accounts.edit_bom"`:

```python
#: the inventory's rights — the prototype's purchase / job / assort / masters
#: columns. Seeing money reuses view_cost, view_sale and view_margin, so a
#: login sees the same numbers in the inventory as in the stock app.
INV_MASTERS = "accounts.inv_masters"
INV_PURCHASE = "accounts.inv_purchase"
INV_JOB = "accounts.inv_job"
INV_ASSORT = "accounts.inv_assort"
```

Extend `ALL` with the four new names (keep the existing eight first):

```python
ALL = (
    VIEW_SALE,
    VIEW_COST,
    VIEW_VENDOR,
    MANAGE_MATERIALS,
    VIEW_MARGIN,
    ADJUST_STOCK,
    MELT,
    EDIT_BOM,
    INV_MASTERS,
    INV_PURCHASE,
    INV_JOB,
    INV_ASSORT,
)
```

In `ROLE_TABS`, add the line:

```python
    "KARIGAR": (),
```

In `ROLE_GROUPS`, change the `ACCOUNTS` and `PRODUCTION` caps and add `KARIGAR`:

```python
    "ACCOUNTS": {
        "name": "Accounts",
        "caps": (
            VIEW_COST, VIEW_SALE, MANAGE_MATERIALS, VIEW_VENDOR, VIEW_MARGIN, EDIT_BOM, ADJUST_STOCK,
            INV_MASTERS, INV_PURCHASE, INV_JOB, INV_ASSORT,
        ),
        "is_system": False,
    },
```

```python
    "PRODUCTION": {
        "name": "Production",
        "caps": (MANAGE_MATERIALS, VIEW_VENDOR, EDIT_BOM, INV_JOB),
        "is_system": False,
    },
    #: the prototype's "Karigar desk": posts job-card movements, sees no money
    "KARIGAR": {"name": "Karigar desk", "caps": (INV_JOB,), "is_system": False},
```

In `accounts/models.py`, append to `Capability.Meta.permissions`:

```python
            ("inv_masters", "Can edit inventory records and import stock"),
            ("inv_purchase", "Can post inventory purchases"),
            ("inv_job", "Can post job-card movements"),
            ("inv_assort", "Can post assortments"),
```

- [ ] **Step 5: Write the migration**

Run: `../nornament-app/.venv/bin/python manage.py makemigrations accounts -n inventory_capabilities`

It generates an `AlterModelOptions` on `capability`. Append a `RunPython` so the groups pick the new permissions up on deploy. The finished file:

```python
"""Four inventory capabilities, and the Karigar desk group that holds one of them."""
from django.db import migrations


def sync_groups(apps, schema_editor):
    from accounts.models import sync_role_groups

    sync_role_groups()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_role_groups")]

    operations = [
        # keep the AlterModelOptions exactly as makemigrations wrote it
        # ...
        migrations.RunPython(sync_groups, migrations.RunPython.noop),
    ]
```

- [ ] **Step 6: Add the fixtures**

In the root `conftest.py`, after `graphic_user`:

```python
@pytest.fixture
def production_user(db):
    """Stock staff: posts job cards, sees vendors, no cost."""
    return _user("workshop", "PRODUCTION", full_name="Production")


@pytest.fixture
def karigar_user(db):
    return _user("karigar", "KARIGAR", full_name="Karigar desk")
```

- [ ] **Step 7: Run the tests**

Run: `../nornament-app/.venv/bin/pytest -q`
Expected: all PASS. If anything asserts the old count of eight capabilities, update that assertion to twelve — say so in the commit message.

- [ ] **Step 8: Commit**

```bash
git add inventory config accounts conftest.py
git commit -m "Add the inventory app, its four rights, and the Karigar desk"
```

---

### Task 2: The prototype's rules, as pure functions

**Files:**
- Create: `inventory/rules.py`, `inventory/tests/test_rules.py`

**Interfaces:**
- Produces:
  - `parse_batch_code(code) -> (family, cls, seq, box) | None`
  - `parse_size(text) -> (kind, display, length, width)`; kind ∈ `lw | dia | multi | free | none`; length/width are `Decimal | None`
  - `colour_family(colour) -> str` (`""` when unknown)
  - `colour_hex(colour) -> "#rrggbb"`
  - `is_misfiled(colour, box_label) -> bool`
  - `shape_svg(shape, hex_colour) -> str` (an `<svg>` string)

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_rules.py`:

```python
from decimal import Decimal

from inventory import rules


def test_a_batch_code_reads_as_family_class_number_box_colour():
    assert rules.parse_batch_code("SR01Y") == ("S", "R", "01", "Y")
    assert rules.parse_batch_code("SP25SB") == ("S", "P", "25", "SB")
    assert rules.parse_batch_code("Broken") is None
    assert rules.parse_batch_code("") is None


def test_size_kinds():
    assert rules.parse_size("14*10") == ("lw", "14 x 10 mm", Decimal("14"), Decimal("10"))
    assert rules.parse_size("6") == ("dia", "6 mm", Decimal("6"), None)
    assert rules.parse_size("2,3,4,") == ("multi", "2, 3, 4 mm", Decimal("2"), None)
    assert rules.parse_size("14*9.5, 6") == ("multi", "14 x 9.5, 6 mm", Decimal("14"), Decimal("9.5"))
    assert rules.parse_size("Free Far") == ("free", "Free Far", None, None)
    assert rules.parse_size("") == ("none", "", None, None)
    assert rules.parse_size(None) == ("none", "", None, None)


def test_colour_family_takes_the_first_word_that_matches():
    assert rules.colour_family("Light Green") == "Green"
    assert rules.colour_family("Pink Red") == "Red"          # red is checked before pink
    assert rules.colour_family("Feroza") == "Turquoise / Feroza"
    assert rules.colour_family("Sea Blue") == "Sea Blue"
    assert rules.colour_family("Maroon") == "Red"
    assert rules.colour_family("N.A") == ""


def test_misfiled_compares_family_with_the_box():
    assert rules.is_misfiled("Red", "Green")
    assert not rules.is_misfiled("Light Green", "Green")
    assert not rules.is_misfiled("Sea Blue", "Blue")          # the one pairing that agrees
    assert not rules.is_misfiled("Red", "? unresolved")        # an unreadable box is never judged
    assert not rules.is_misfiled("N.A", "Green")               # nor an unreadable colour
    assert rules.is_misfiled("Pink", "Brown-Yellow")           # unconfirmed but labelled: judged


def test_colour_hex_falls_back_to_the_family_then_grey():
    assert rules.colour_hex("Light Green") == "#7bc79a"
    assert rules.colour_hex("Greenish") == "#2f9e6b"
    assert rules.colour_hex("") == "#b9b6ad"


def test_round_stones_are_circles_and_beads_have_a_hole():
    round_stone = rules.shape_svg("Round", "#cf3b3b")
    bead = rules.shape_svg("Beads Round", "#cf3b3b")
    assert '<circle cx="50" cy="50" r="30"' in round_stone and 'r="6.5"' not in round_stone
    assert 'r="6.5"' in bead
    assert "<ellipse" in rules.shape_svg("Oval", "#cf3b3b")
    assert rules.shape_svg("Oval", "#cf3b3b") != rules.shape_svg("Oval", "#cf3b3b")  # unique gradient ids
```

- [ ] **Step 2: Run to see them fail**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_rules.py -v`
Expected: FAIL — `cannot import name 'rules'`.

- [ ] **Step 3: Write `inventory/rules.py`**

```python
"""The prototype's rules, as pure functions.

Ported from ``build_ui.py`` and ``_script.html`` so the numbers here match the
ones the owner has already seen: the batch-code grammar, the size cell, the
colour family a free-text colour belongs to, and the silhouette each card draws
before a photo exists. Nothing here touches the database.
"""
import itertools
import re
from decimal import Decimal

BATCH_CODE = re.compile(r"^([A-Z])([A-Z])(\d+)([A-Z]+)$")


def parse_batch_code(code):
    """``SR01Y`` → ``("S", "R", "01", "Y")``: family, class, number, box colour."""
    match = BATCH_CODE.match((code or "").strip())
    return match.groups() if match else None


_LW = re.compile(r"^(\d+(?:\.\d+)?)\s*\*\s*(\d+(?:\.\d+)?)$")
_DIA = re.compile(r"^(\d+(?:\.\d+)?)$")
_NUMERIC = re.compile(r"^[\d.\s*,]+$")


def parse_size(text):
    """The ``Size Length * Width`` cell, in millimetres: (kind, display, length, width).

    Displays keep the digits as typed. The prototype printed parsed floats on
    multi-size cells, which is how "14" became "14.0".
    """
    value = (text or "").strip().rstrip(",*").strip()
    if not value:
        return ("none", "", None, None)
    match = _LW.match(value)
    if match:
        return ("lw", f"{match.group(1)} x {match.group(2)} mm", Decimal(match.group(1)), Decimal(match.group(2)))
    match = _DIA.match(value)
    if match:
        return ("dia", f"{match.group(1)} mm", Decimal(match.group(1)), None)
    if _NUMERIC.match(value):
        parts = []
        for piece in (p.strip() for p in value.split(",") if p.strip()):
            lw, dia = _LW.match(piece), _DIA.match(piece)
            if lw:
                parts.append((lw.group(1), lw.group(2)))
            elif dia:
                parts.append((dia.group(1), None))
        if parts:
            display = ", ".join(f"{a} x {b}" if b else a for a, b in parts) + " mm"
            length, width = parts[0]
            return ("multi", display, Decimal(length), Decimal(width) if width else None)
    return ("free", value, None, None)


#: first match wins, in this order — which is why "Pink Red" is Red
_FAMILY_WORDS = [
    ("feroza", "Turquoise / Feroza"), ("sea blue", "Sea Blue"), ("turq", "Turquoise / Feroza"),
    ("green", "Green"), ("maroon", "Red"), ("red", "Red"), ("pink", "Pink"), ("blue", "Blue"),
    ("purple", "Purple"), ("yellow", "Yellow"), ("golden", "Yellow"), ("orange", "Orange"),
    ("brown", "Brown"), ("white", "White"), ("black", "Black"), ("grey", "Grey"),
    ("multi", "Multi"), ("mix", "Multi"), ("peridot", "Green"),
]


def colour_family(colour):
    lowered = (colour or "").lower()
    for word, family in _FAMILY_WORDS:
        if word in lowered:
            return family
    return ""


def is_misfiled(colour, box_label):
    """A stone whose colour family is not its box's colour.

    Only a box whose label starts with ``?`` is exempt — the prototype's rule,
    and the one its 127 comes from. Sea Blue in a Blue box agrees.
    """
    got = colour_family(colour)
    expected = box_label or ""
    if not got or not expected or expected.startswith("?"):
        return False
    return got != expected and not (expected == "Blue" and got == "Sea Blue")


_COLOUR_HEX = {
    "green": "#2f9e6b", "light green": "#7bc79a", "dark green": "#1c6b47", "pale green": "#a8d8bd",
    "peridot green": "#8fbf3f", "yellowish green": "#9fbf45", "grey green": "#7f9686",
    "red": "#cf3b3b", "dark red": "#8f2222", "light red": "#e07070", "maroon": "#6f1f2a", "pink red": "#d9506e",
    "pink": "#e07ba0", "light pink": "#f0b3c7", "dark pink": "#c2436f", "pink light": "#f0b3c7",
    "blue": "#2f7fd0", "dark blue": "#1b4b8f", "light blue": "#7fb6e8", "blue light": "#7fb6e8",
    "sea blue": "#2f9ec4", "feroza": "#25b3b3",
    "purple": "#7a5bc4", "purple light": "#a894dd", "purple dark": "#4f3690",
    "yellow": "#e0a51e", "light yellow": "#f0d271", "yellow dark": "#b8801a", "yellow pale": "#f2e2a8",
    "golden yellow": "#d99a12", "yellow golden": "#d99a12",
    "orange": "#e07030", "light orange": "#f0a56f",
    "brown": "#8a5a3b", "brown light": "#b08560", "brown dark": "#5c3a24",
    "yellowish brown": "#a3762e", "brown yellowish": "#a3762e",
    "white": "#eceae2", "off white": "#e2ded1", "pale white": "#f2f0e9", "dull white": "#dedbd0",
    "steel white": "#d6d9db", "sparkle white": "#f4f2ea",
    "black": "#2e2e2b", "grey": "#9a9891",
    "multi": "#b06fc0", "mix": "#b06fc0", "red, pink": "#d9506e",
}
_FAMILY_HEX = {
    "Green": "#2f9e6b", "Red": "#cf3b3b", "Pink": "#e07ba0", "Blue": "#2f7fd0", "Sea Blue": "#2f9ec4",
    "Turquoise / Feroza": "#25b3b3", "Purple": "#7a5bc4", "Yellow": "#e0a51e", "Orange": "#e07030",
    "Brown": "#8a5a3b", "White": "#eceae2", "Black": "#2e2e2b", "Grey": "#9a9891", "Multi": "#b06fc0",
}


def colour_hex(colour):
    """The paint for a silhouette: the colour as recorded, else its family, else grey."""
    key = (colour or "").strip().lower()
    return _COLOUR_HEX.get(key) or _FAMILY_HEX.get(colour_family(colour), "#b9b6ad")


_ids = itertools.count(1)


def shape_svg(shape, hex_colour):
    """``shapeSVG`` from the prototype: the card is image-led before any photo exists.

    One fix: the prototype's first rule needed "bead" in the shape, so a plain
    "Round" fell through to the default ellipse. Round and mani are circles;
    beads (and mani, which is a bead) get the drill hole.
    """
    sh = (shape or "").lower()
    gid = f"g{next(_ids)}"
    c = hex_colour or "#b9b6ad"
    defs = (
        f'<defs><radialGradient id="{gid}" cx="34%" cy="28%">'
        '<stop offset="0%" stop-color="#fff" stop-opacity=".92"/>'
        f'<stop offset="38%" stop-color="{c}" stop-opacity="1"/>'
        f'<stop offset="100%" stop-color="{c}" stop-opacity="1"/></radialGradient></defs>'
    )
    st = f'fill="url(#{gid})" stroke="rgba(11,11,11,.18)" stroke-width="1.2"'
    if re.search(r"beads round|^round|^mani", sh):
        hole = '<circle cx="50" cy="50" r="6.5" fill="rgba(0,0,0,.35)"/>' if ("bead" in sh or sh.startswith("mani")) else ""
        body = f'<circle cx="50" cy="50" r="30" {st}/>{hole}'
    elif re.search(r"beads long|cylinder|drum", sh):
        body = f'<rect x="26" y="34" width="48" height="32" rx="15" {st}/><circle cx="50" cy="50" r="5" fill="rgba(0,0,0,.32)"/>'
    elif re.search(r"figurine|carv", sh):
        body = f'<path d="M50 16c11 0 15 9 12 16 8 3 14 11 14 21 0 16-12 27-26 27S24 69 24 53c0-10 6-18 14-21-3-7 1-16 12-16z" {st}/>'
    elif re.search(r"tear|drop|pear", sh):
        body = f'<path d="M50 14c9 14 22 24 22 40 0 15-10 26-22 26S28 69 28 54c0-16 13-26 22-40z" {st}/>'
    elif "marquise" in sh:
        body = f'<path d="M50 12c14 12 22 26 22 38S64 78 50 88C36 78 28 62 28 50S36 24 50 12z" {st}/>'
    elif "oval" in sh:
        body = f'<ellipse cx="50" cy="50" rx="27" ry="37" {st}/>'
    elif re.search(r"princess|square", sh):
        body = f'<rect x="20" y="20" width="60" height="60" rx="5" {st}/>'
    elif re.search(r"rect|bugutte|baguette", sh):
        body = f'<rect x="30" y="16" width="40" height="68" rx="4" {st}/>'
    elif "heart" in sh:
        body = f'<path d="M50 84C30 68 20 56 20 43c0-11 8-17 16-17 6 0 11 3 14 8 3-5 8-8 14-8 8 0 16 6 16 17 0 13-10 25-30 41z" {st}/>'
    elif re.search(r"triangle|trillion|kite", sh):
        body = f'<path d="M50 16 82 76H18z" {st}/>'
    elif "cushion" in sh:
        body = f'<rect x="19" y="19" width="62" height="62" rx="20" {st}/>'
    elif re.search(r"uneven|tumble|fancy|mix|free", sh):
        body = f'<path d="M32 24c14-7 34-5 43 6s9 30-2 41-33 14-44 4-11-44 3-51z" {st}/>'
    else:
        body = f'<ellipse cx="50" cy="50" rx="28" ry="36" {st}/>'
    highlight = '<ellipse cx="38" cy="30" rx="8" ry="11" fill="#fff" opacity=".5"/>'
    return f'<svg viewBox="0 0 100 100" aria-hidden="true">{defs}{body}{highlight}</svg>'
```

- [ ] **Step 4: Run the tests**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_rules.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add inventory/rules.py inventory/tests/test_rules.py
git commit -m "Port the prototype's batch code, size, colour and silhouette rules"
```

---

### Task 3: Models, seed tables, and the stock services

**Files:**
- Create: `inventory/seed.py`, `inventory/models.py`, `inventory/migrations/__init__.py`, `inventory/migrations/0001_initial.py` (generated), `inventory/migrations/0002_seed_codes.py`, `inventory/services.py`, `inventory/tests/conftest.py`, `inventory/tests/test_services.py`

**Interfaces:**
- Consumes: `INV_MASTERS`, `VIEW_COST`, `VIEW_SALE` (Task 1).
- Produces:
  - models `BoxColour(code, label, swatch, confirmed)`, `CodePart(kind, code, label, confirmed)` with `CodePart.FAMILY = "family"` and `CodePart.CLASS = "class"`, `Batch(code, box_colour, family, cls, seq)`, `Pouch(...)`, `Movement(...)` with `Movement.IN = "in"`, `Movement.OUT = "out"` and `Movement.Reason`, `PriceEntry(...)` with `PriceEntry.VALUATION`, `PURCHASE`, `LIST`
  - `models.TREATMENTS`, `models.ORIGINS`, `models.UNRESOLVED_SWATCH`
  - `seed.load(BoxColour, CodePart)`
  - `services.stocked(queryset=None)`: pouches annotated with `on_pcs`, `on_ct` and `rate`
  - `services.value_of(pouch) -> Decimal | None`
  - `services.open_pouches(user, specs, import_batch=None) -> [Pouch]`, where each spec is `(batch, fields, pcs, ct, rate)`
  - `services.open_pouch(user, batch, fields, pcs, ct, rate, import_batch=None) -> Pouch`
  - `services.save_details(user, pouch, **changes)`: changes limited to `treatment`, `origin`, `purchase_date`, `supplier`
  - `services.add_price(user, pouch, kind, rate, effective_from) -> PriceEntry`
  - `services.recount(user, pouch, pcs, ct, note="") -> [Movement]`
  - `services.latest_price(pouch, kind) -> PriceEntry | None`
  - fixture `shelf` → `{"batch", "onyx", "ruby", "supplier"}`

- [ ] **Step 1: Write the seed data**

`inventory/seed.py`:

```python
"""The prototype's code tables (``BOXCOL``, ``FAM``, ``CLS`` in build_ui.py), as data.

Kept out of the migration so a test can load the same rows the migration does.
Unconfirmed codes are the owner's open questions; they load as they are and are
corrected in Settings, not here.
"""
HATCH = "repeating-linear-gradient(45deg,#e2e0d7 0 6px,#f4f3f0 6px 12px)"

BOX_COLOURS = [
    # code, label, swatch (a CSS background), confirmed
    ("G", "Green", "#1baf7a", True),
    ("R", "Red", "#e34948", True),
    ("Y", "Yellow", "#eda100", True),
    ("W", "White", "#e8e6dd", True),
    ("M", "Multi", "linear-gradient(135deg,#e34948,#eda100,#1baf7a,#2a78d6)", True),
    ("B", "Blue", "#2a78d6", True),
    ("T", "Turquoise / Feroza", "#16b5b5", True),
    ("O", "Orange", "#eb6834", True),
    ("P", "Pink", "#e87ba4", True),
    ("SB", "Sea Blue", "#3f97d8", True),
    ("BK", "Black", "#4a4a46", True),
    ("PR", "Purple", "#7a63d8", True),
    ("BR", "Brown", "#a06a42", True),
    ("BY", "Brown-Yellow", "#b8912f", False),
    ("F", "? Fancy (pearl) — unconfirmed", "repeating-linear-gradient(45deg,#f0d9b0 0 6px,#faf3e6 6px 12px)", False),
    ("RG", "? unresolved", HATCH, False),
    ("RC", "? unresolved", HATCH, False),
    ("CM", "? unresolved", HATCH, False),
    ("C", "? unresolved", HATCH, False),
]

FAMILIES = [("S", "Stone", True), ("P", "Pearl", True), ("C", "CZ / American Diamond", True)]

CLASSES = [
    ("R", "Real", True),
    ("P", "Semi-Precious", True),
    ("L", "Lab / Man-made", True),
    ("S", "Shell or Synthetic ?", False),
    ("Z", "Zirconia", True),
]


def load(BoxColour, CodePart):
    """Idempotent: a code already there keeps whatever it has been corrected to."""
    for code, label, swatch, confirmed in BOX_COLOURS:
        BoxColour.objects.get_or_create(code=code, defaults={"label": label, "swatch": swatch, "confirmed": confirmed})
    for kind, rows in (("family", FAMILIES), ("class", CLASSES)):
        for code, label, confirmed in rows:
            CodePart.objects.get_or_create(kind=kind, code=code, defaults={"label": label, "confirmed": confirmed})
```

- [ ] **Step 2: Write the models**

`inventory/models.py`:

```python
"""Box colour → batch → pouch, and the two ledgers that hang off a pouch.

A pouch's quantity is never stored. It is the sum of its movements, so the only
way stock changes is by posting one, and a wrong entry is corrected by another
entry rather than by editing a number. Its value is carats on hand × the latest
valuation rate; a revaluation adds a row and overwrites nothing.

The batch code (``SR01Y``) says where a pouch is filed, which is exactly why it
is not the pouch's identity: re-filing would change it. The identity is the
``NRN-`` reference, assigned once.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .seed import HATCH

UNRESOLVED_SWATCH = HATCH

#: vocab.py's TREATMENT list; the blank choice is "Not recorded"
TREATMENTS = [(t, t) for t in [
    "Unknown", "None (verified)", "Heated", "Oiled / Resin", "Dyed", "Bleached",
    "Stabilised / Impregnated", "Coated (incl. AB / iridescent)", "Irradiated",
    "Diffused", "Glass-filled", "Reconstituted / Composite", "Laser Drilled",
]]

#: the prototype's origin list
ORIGINS = [(o, o) for o in [
    "Iran (feroza)", "China", "Burma / Myanmar", "Sri Lanka (Ceylon)", "Zambia", "Brazil",
    "Tanzania (Merelani)", "Africa — other", "India",
]]


class BoxColour(models.Model):
    code = models.CharField(max_length=4, primary_key=True)
    label = models.CharField(max_length=80)
    swatch = models.CharField(max_length=200, help_text="A CSS background: a colour, a gradient or a hatch.")
    confirmed = models.BooleanField(default=False)

    class Meta:
        db_table = "inv_box_colour"
        ordering = ["code"]

    def __str__(self):
        return f"{self.label} · {self.code}"


class CodePart(models.Model):
    """The first two letters of a batch code: material family, then class."""

    FAMILY, CLASS = "family", "class"

    kind = models.CharField(max_length=8, choices=[(FAMILY, "Material family"), (CLASS, "Class")])
    code = models.CharField(max_length=2)
    label = models.CharField(max_length=80)
    confirmed = models.BooleanField(default=False)

    class Meta:
        db_table = "inv_code_part"
        ordering = ["kind", "code"]
        constraints = [models.UniqueConstraint(fields=["kind", "code"], name="inv_code_part_key")]

    def __str__(self):
        return f"{self.kind} {self.code} = {self.label}"


class Batch(models.Model):
    code = models.CharField(max_length=16, unique=True)
    box_colour = models.ForeignKey(BoxColour, on_delete=models.PROTECT, related_name="batches")
    family = models.CharField(max_length=2)
    cls = models.CharField(max_length=2)
    seq = models.CharField(max_length=8)

    class Meta:
        db_table = "inv_batch"
        ordering = ["code"]
        verbose_name_plural = "batches"

    def __str__(self):
        return self.code


class Pouch(models.Model):
    ref = models.CharField(max_length=12, unique=True, editable=False)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="pouches")
    pouch_no = models.CharField(max_length=16, null=True, blank=True)
    carton = models.CharField("box no.", max_length=32, blank=True)

    # as typed in the register; normalising them is a data-quality job, not this one
    category = models.CharField(max_length=80, blank=True)
    stone_name = models.CharField(max_length=120, blank=True)
    colour = models.CharField(max_length=80, blank=True)
    shape = models.CharField(max_length=80, blank=True)
    cut = models.CharField(max_length=80, blank=True)
    quality = models.CharField(max_length=20, blank=True)
    size_text = models.CharField(max_length=80, blank=True)
    countable = models.BooleanField(default=True, help_text="A blank Pcs in the register: too small or too many to count.")
    remarks = models.TextField(blank=True)
    src = models.CharField(max_length=24, blank=True, help_text="Sheet and row it came from, e.g. SP!104.")
    import_batch = models.ForeignKey(
        "stock.ImportBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    treatment = models.CharField(max_length=40, blank=True, choices=TREATMENTS)
    origin = models.CharField(max_length=40, blank=True, choices=ORIGINS)
    purchase_date = models.DateField(null=True, blank=True)
    supplier = models.ForeignKey("stock.Vendor", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_pouch"
        ordering = ["batch__code", "pk"]
        verbose_name_plural = "pouches"
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "pouch_no"], condition=Q(pouch_no__isnull=False), name="inv_pouch_key"
            )
        ]

    def __str__(self):
        return f"{self.batch.code} · {self.pouch_no or '?'}"


class Movement(models.Model):
    """Append-only. Pieces and carats are separate because a pouch can move by either."""

    IN, OUT = "in", "out"

    class Reason(models.TextChoices):
        OPENING_BALANCE = "Opening Balance"
        PURCHASE = "Purchase"
        PURCHASE_RETURN = "Purchase Return"
        SALE = "Sale"
        SALES_RETURN = "Sales Return"
        MEMO_OUT = "Memo Out"
        MEMO_IN = "Memo In"
        JOB_WORK_OUT = "Job Work Out"
        JOB_WORK_IN = "Job Work In"
        CONSUMED = "Consumed in Production"
        WASTAGE = "Wastage / Loss in Process"
        BREAKAGE = "Breakage"
        SPLIT = "Split"
        MERGE = "Merge"
        TRANSFER = "Transfer"
        SAMPLE = "Sample"
        RECOUNT_ADJUSTMENT = "Recount Adjustment"

    pouch = models.ForeignKey(Pouch, on_delete=models.PROTECT, related_name="movements")
    occurred_at = models.DateTimeField(default=timezone.now)
    reason = models.CharField(max_length=32, choices=Reason.choices)
    direction = models.CharField(max_length=3, choices=[(IN, "In"), (OUT, "Out")])
    pcs = models.PositiveIntegerField(null=True, blank=True)
    ct = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    counterparty = models.ForeignKey("stock.Vendor", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    challan_no = models.CharField(max_length=40, blank=True)
    ref = models.CharField(max_length=40, blank=True)
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_movement"
        ordering = ["-occurred_at", "-pk"]

    def __str__(self):
        return f"{self.reason} {self.direction} {self.pouch_id}"


class PriceEntry(models.Model):
    """A dated rate per carat. Nothing is overwritten: the latest of a kind is current."""

    VALUATION, PURCHASE, LIST = "valuation", "purchase", "list"
    KINDS = [(VALUATION, "Valuation"), (PURCHASE, "Purchase"), (LIST, "List")]

    pouch = models.ForeignKey(Pouch, on_delete=models.PROTECT, related_name="prices")
    kind = models.CharField(max_length=10, choices=KINDS)
    rate = models.DecimalField(max_digits=14, decimal_places=4)
    effective_from = models.DateField(default=timezone.localdate)
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_price"
        ordering = ["-effective_from", "-pk"]

    def __str__(self):
        return f"{self.kind} {self.rate}/ct on {self.pouch_id}"
```

- [ ] **Step 3: Generate the migration, then write the seed migration**

Run: `../nornament-app/.venv/bin/python manage.py makemigrations inventory`
Expected: `inventory/migrations/0001_initial.py` is created, along with `migrations/__init__.py`.

`inventory/migrations/0002_seed_codes.py`:

```python
from django.db import migrations


def load(apps, schema_editor):
    from inventory import seed

    seed.load(apps.get_model("inventory", "BoxColour"), apps.get_model("inventory", "CodePart"))


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
```

- [ ] **Step 4: Write the failing service tests**

`inventory/tests/conftest.py`:

```python
"""A small shelf every inventory test can stand on.

Numbers are chosen to be findable in a response body and nowhere else: a
SALES login must never be shown 7,919 or 98,988, and a client must never be
shown SL01G, C-117 or the remark.
"""
from decimal import Decimal

import pytest

from inventory import seed, services
from inventory.models import Batch, BoxColour, CodePart

RATE = Decimal("7919")
VALUE = "98,988"          # 12.5 ct × ₹7,919, rounded
SUPPLIER = "Bhansali Gems"


@pytest.fixture
def shelf(admin_user_):
    from stock.models import Vendor

    seed.load(BoxColour, CodePart)
    supplier = Vendor.objects.create(code="BHG", name=SUPPLIER)
    batch = Batch.objects.create(code="SL01G", box_colour_id="G", family="S", cls="L", seq="01")
    onyx = services.open_pouch(
        admin_user_, batch,
        {"pouch_no": "1", "carton": "C-117", "category": "Man Made", "stone_name": "Green Onyx",
         "colour": "Green", "shape": "Oval", "cut": "Cabachon", "quality": "B", "size_text": "14*10",
         "remarks": "keep away from light", "src": "SL!2"},
        pcs=20, ct=Decimal("12.5"), rate=RATE,
    )
    onyx.supplier = supplier
    onyx.save(update_fields=["supplier"])
    ruby = services.open_pouch(
        admin_user_, batch,
        {"pouch_no": "2", "carton": "C-117", "category": "Man Made", "stone_name": "Ruby Glass",
         "colour": "Red", "shape": "Beads Round", "cut": "Regular", "quality": "A", "size_text": "Free Far",
         "src": "SL!3"},
        pcs=None, ct=Decimal("40"), rate=Decimal("50"),
    )
    return {"batch": batch, "onyx": onyx, "ruby": ruby, "supplier": supplier}
```

`inventory/tests/test_services.py`:

```python
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import services
from inventory.models import Movement, Pouch, PriceEntry
from stock.services import ServiceError

pytestmark = pytest.mark.django_db


def _held(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()


def test_opening_writes_a_balance_a_rate_and_a_reference(shelf):
    onyx = _held(shelf["onyx"])
    assert onyx.ref == "NRN-000001" and shelf["ruby"].ref == "NRN-000002"
    assert (onyx.on_pcs, onyx.on_ct, onyx.rate) == (20, Decimal("12.5"), Decimal("7919"))
    assert services.value_of(onyx) == Decimal("98987.5")
    assert onyx.movements.get().reason == Movement.Reason.OPENING_BALANCE


def test_an_uncountable_pouch_moves_by_weight_only(shelf):
    ruby = _held(shelf["ruby"])
    assert ruby.countable is False and ruby.on_pcs is None and ruby.on_ct == Decimal("40")


def test_quantity_is_the_sum_of_movements(shelf, admin_user_):
    onyx = shelf["onyx"]
    Movement.objects.create(pouch=onyx, reason=Movement.Reason.SALE, direction=Movement.OUT, pcs=5, ct=Decimal("2.5"))
    held = _held(onyx)
    assert (held.on_pcs, held.on_ct) == (15, Decimal("10"))


def test_no_weight_means_no_value(admin_user_, shelf):
    pouch = services.open_pouch(admin_user_, shelf["batch"], {"pouch_no": "3"}, pcs=1, ct=None, rate=Decimal("10"))
    assert services.value_of(_held(pouch)) is None


def test_the_latest_valuation_is_the_rate(shelf, admin_user_):
    services.add_price(admin_user_, shelf["onyx"], PriceEntry.VALUATION, Decimal("8000"), date(2030, 1, 1))
    assert _held(shelf["onyx"]).rate == Decimal("8000")
    assert shelf["onyx"].prices.count() == 2            # the old rate is kept


def test_sales_may_neither_save_nor_price(shelf, sales_user):
    with pytest.raises(PermissionDenied):
        services.save_details(sales_user, shelf["onyx"], treatment="Heated")
    with pytest.raises(PermissionDenied):
        services.add_price(sales_user, shelf["onyx"], PriceEntry.LIST, Decimal("1"), date.today())


def test_a_negative_rate_is_refused_and_zero_is_not(shelf, admin_user_):
    with pytest.raises(ServiceError):
        services.add_price(admin_user_, shelf["onyx"], PriceEntry.VALUATION, Decimal("-1"), date.today())
    services.add_price(admin_user_, shelf["onyx"], PriceEntry.LIST, Decimal("0"), date.today())


def test_save_details_writes_only_the_four_fields(shelf, accounts_user):
    services.save_details(accounts_user, shelf["onyx"], treatment="Heated", origin="Zambia")
    shelf["onyx"].refresh_from_db()
    assert (shelf["onyx"].treatment, shelf["onyx"].origin) == ("Heated", "Zambia")
    with pytest.raises(ServiceError):
        services.save_details(accounts_user, shelf["onyx"], stone_name="Emerald")
    with pytest.raises(ServiceError):
        services.save_details(accounts_user, shelf["onyx"], treatment="Painted gold")


def test_recount_posts_the_difference(shelf, admin_user_):
    moves = services.recount(admin_user_, shelf["onyx"], pcs=18, ct=Decimal("13"))
    assert len(moves) == 2
    held = _held(shelf["onyx"])
    assert (held.on_pcs, held.on_ct) == (18, Decimal("13"))
    assert services.recount(admin_user_, shelf["onyx"], pcs=18, ct=Decimal("13")) == []
```

- [ ] **Step 5: Run to see them fail**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_services.py -v`
Expected: FAIL — `inventory.services` has no `open_pouch`.

- [ ] **Step 6: Write `inventory/services.py`**

```python
"""Every write to the inventory, and the one query that reads a pouch's stock.

Quantities are sums of movements and value is carats × the latest valuation, so
``stocked`` is how every screen reads a pouch: one query, with pieces, carats and
rate annotated.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, F, OuterRef, Subquery, Sum, When
from django.utils import timezone

from accounts.capabilities import INV_MASTERS, VIEW_COST, VIEW_SALE
from stock.services import ServiceError, log, require

from .models import Movement, Pouch, PriceEntry

DETAIL_FIELDS = ("treatment", "origin", "purchase_date", "supplier")


def _by(user):
    return user if getattr(user, "is_authenticated", False) else None


def _signed(field):
    return Case(
        When(movements__direction=Movement.OUT, then=-F(f"movements__{field}")),
        default=F(f"movements__{field}"),
    )


def stocked(queryset=None):
    """Pouches with ``on_pcs``, ``on_ct`` and ``rate`` (the latest valuation)."""
    latest = (
        PriceEntry.objects.filter(pouch=OuterRef("pk"), kind=PriceEntry.VALUATION)
        .order_by("-effective_from", "-pk")
        .values("rate")[:1]
    )
    queryset = Pouch.objects.all() if queryset is None else queryset
    return queryset.select_related("batch__box_colour", "supplier").annotate(
        on_pcs=Sum(_signed("pcs")), on_ct=Sum(_signed("ct")), rate=Subquery(latest)
    )


def value_of(pouch):
    """Carats on hand × rate. ``None`` when either is missing — never zero."""
    if pouch.on_ct is None or pouch.rate is None:
        return None
    return pouch.on_ct * pouch.rate


def latest_price(pouch, kind):
    return pouch.prices.filter(kind=kind).order_by("-effective_from", "-pk").first()


def _check_quantities(pcs, ct, rate=None):
    if (pcs is not None and pcs < 0) or (ct is not None and ct < 0):
        raise ServiceError("A quantity cannot be negative; the direction says which way it moves.")
    if rate is not None and rate < 0:
        raise ServiceError("A rate cannot be negative.")


def _last_ref_number():
    # ponytail: read-the-max under the caller's transaction; the unique index
    # catches a race. Move to a DB sequence if two people ever create at once.
    last = Pouch.objects.order_by("-ref").values_list("ref", flat=True).first()
    return int(last[4:]) if last else 0


@transaction.atomic
def open_pouches(user, specs, import_batch=None):
    """Create pouches with an Opening Balance and, where there is one, a valuation.

    ``specs`` is a list of ``(batch, fields, pcs, ct, rate)``. Bulk, because an
    import opens three thousand of these and one request has to finish.
    """
    require(user, INV_MASTERS, "Only a role that edits inventory records can add stock.")
    number, now, today, by = _last_ref_number(), timezone.now(), timezone.localdate(), _by(user)
    pouches = []
    for batch, fields, pcs, ct, rate in specs:
        _check_quantities(pcs, ct, rate)
        number += 1
        pouches.append(Pouch(
            ref=f"NRN-{number:06d}", batch=batch, import_batch=import_batch,
            **{"countable": pcs is not None, **fields},
        ))
    Pouch.objects.bulk_create(pouches)
    Movement.objects.bulk_create([
        Movement(pouch=pouch, reason=Movement.Reason.OPENING_BALANCE, direction=Movement.IN,
                 pcs=pcs, ct=ct, occurred_at=now, recorded_by=by, ref=pouch.src)
        for pouch, (_, _, pcs, ct, _) in zip(pouches, specs)
    ])
    PriceEntry.objects.bulk_create([
        PriceEntry(pouch=pouch, kind=PriceEntry.VALUATION, rate=rate, effective_from=today, set_by=by)
        for pouch, (_, _, _, _, rate) in zip(pouches, specs) if rate is not None
    ])
    if pouches:
        log(user, "INSERT", "inv_pouch", f"{pouches[0].ref}..{pouches[-1].ref}", f"{len(pouches)} pouches opened")
    return pouches


def open_pouch(user, batch, fields, pcs, ct, rate, import_batch=None):
    return open_pouches(user, [(batch, fields, pcs, ct, rate)], import_batch)[0]


def save_details(user, pouch, **changes):
    """Treatment, origin, purchase date and supplier — the four fields the record adds."""
    require(user, INV_MASTERS, "Only a role that edits inventory records can save a pouch.")
    unknown = set(changes) - set(DETAIL_FIELDS)
    if unknown:
        raise ServiceError(f"{', '.join(sorted(unknown))} cannot be edited here.")
    old = {name: str(getattr(pouch, name) or "") for name in changes}
    for name, value in changes.items():
        setattr(pouch, name, value)
    try:
        pouch.full_clean(exclude=["batch", "import_batch"], validate_unique=False, validate_constraints=False)
    except ValidationError as error:
        raise ServiceError(error.messages[0]) from error
    pouch.save(update_fields=list(changes))
    log(user, "UPDATE", "inv_pouch", pouch.pk, str(pouch),
        old_values=old, new_values={name: str(getattr(pouch, name) or "") for name in changes})


def add_price(user, pouch, kind, rate, effective_from):
    require(user, INV_MASTERS, "Only a role that edits inventory records can set a price.")
    require(user, VIEW_SALE if kind == PriceEntry.LIST else VIEW_COST, "A price you may not see is not yours to set.")
    if kind not in dict(PriceEntry.KINDS):
        raise ServiceError(f"{kind} is not a kind of price.")
    _check_quantities(None, None, rate)
    entry = PriceEntry.objects.create(pouch=pouch, kind=kind, rate=rate, effective_from=effective_from, set_by=_by(user))
    log(user, "INSERT", "inv_price", entry.pk, f"{kind} {rate}/ct on {pouch}")
    return entry


@transaction.atomic
def recount(user, pouch, pcs, ct, note=""):
    """Bring the ledger to a counted figure: one adjustment per quantity that differs.

    Pieces and carats can move in opposite directions (a recount finds more
    pieces but less weight), so each gets its own movement. A figure of ``None``
    means "not counted", never "zero".
    """
    require(user, INV_MASTERS, "Only a role that edits inventory records can recount.")
    _check_quantities(pcs, ct)
    held = stocked(Pouch.objects.filter(pk=pouch.pk)).get()
    moves = []
    for field, counted, current in (("pcs", pcs, held.on_pcs), ("ct", ct, held.on_ct)):
        if counted is None or counted == (current or 0):
            continue
        delta = counted - (current or 0)
        quantities = {"pcs": None, "ct": None, field: abs(delta)}
        moves.append(Movement.objects.create(
            pouch=pouch, reason=Movement.Reason.RECOUNT_ADJUSTMENT,
            direction=Movement.IN if delta > 0 else Movement.OUT, note=note, recorded_by=_by(user), **quantities,
        ))
    if moves:
        log(user, "INSERT", "inv_movement", pouch.pk, f"recount of {pouch}: {len(moves)} adjustment(s)")
    return moves
```

- [ ] **Step 7: Run the tests**

Run: `../nornament-app/.venv/bin/pytest inventory/tests -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add inventory
git commit -m "Model box colour, batch and pouch, with quantity as the sum of movements"
```

---

### Task 4: Read the stones register

**Files:**
- Create: `inventory/importers/__init__.py`, `inventory/importers/stones.py`, `inventory/tests/fixtures_stones.py`, `inventory/tests/test_import_parse.py`

**Interfaces:**
- Produces:
  - `stones.SHEETS`, `stones.COLUMNS` (field → header)
  - `stones.Row` dataclass: `src, batch, pouch_no, carton, category, stone_name, shape, size_text, colour, cut, quality, remarks, pcs, ct, rate`
  - `stones.parse(fileobj) -> [Row]`
  - `stones.header_problems(fileobj) -> [str]`
  - `fixtures_stones.build_workbook(sheets=None) -> io.BytesIO`, and `fixtures_stones.SHEETS_DEFAULT`

- [ ] **Step 1: Write the fixture builder**

`inventory/tests/fixtures_stones.py`:

```python
"""A stones register in memory, shaped like the owner's.

One sheet per filing family, header in row 1. Every case the importer has to
decide about is here once: a duplicate key, a batch code that does not read, a
pouch with no number, an uncountable pouch, a pouch with no rate, and a Googri
sheet that must be ignored because Googri is not a stone.
"""
import io

from openpyxl import Workbook

from inventory.importers.stones import COLUMNS

HEADERS = list(COLUMNS.values())


def _row(batch, pouch_no, stone, colour, pcs, ct, rate, **extra):
    row = {
        "New Gati Code": batch, "Batch No.": pouch_no, "Box No": extra.get("box", 3),
        "Category": "Man Made", "Stone Name": stone, "Shape": extra.get("shape", "Oval"),
        "Size Length * Width": extra.get("size", "14*10"), "Colour": colour, "Cut": "Cabachon",
        "Quality": "B", "Pcs": pcs, "Weight in Cts / Qty": ct, "Price Per Carat / Pc": rate,
        "Remarks": extra.get("remarks"),
    }
    return [row[h] for h in HEADERS]


SHEETS_DEFAULT = {
    "SL": [
        _row("SL01G", 1, "Green Onyx", "Green", 20, 12.5, 100),         # SL!2
        _row("SL01G", 2, "Ruby Glass", "Red", None, 40, 50),             # SL!3  misfiled, uncountable
        _row("SL01G", 1, "Green Onyx", "Green", 5, 2, 100),              # SL!4  duplicate of SL!2
        _row("SL02G", None, "Jade", "Green", 3, 6, 200),                 # SL!5  no pouch no.
        _row("Broken", 1, "Unknown", "Green", 1, 1, 1),                  # SL!6  batch code does not read
        _row("SL03F", 1, "Pearl", "White", 10, 5, None),                 # SL!7  no rate; box F unconfirmed
    ],
    "Googri": [_row("GG01Y", 1, "Googri", "Yellow", 1, 1, 1)],
}


def build_workbook(sheets=None):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in (sheets or SHEETS_DEFAULT).items():
        sheet = workbook.create_sheet(name)
        sheet.append(HEADERS + ["New Code"])       # a dead column the reader must ignore
        for row in rows:
            sheet.append(row + ["X"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
```

- [ ] **Step 2: Write the failing test**

`inventory/tests/test_import_parse.py`:

```python
from decimal import Decimal

from inventory.importers import stones
from inventory.tests.fixtures_stones import build_workbook


def test_reads_the_five_stone_sheets_and_skips_googri():
    rows = stones.parse(build_workbook())
    assert [r.src for r in rows] == ["SL!2", "SL!3", "SL!4", "SL!5", "SL!6", "SL!7"]


def test_typed_values():
    first, ruby, _, jade, *_ = stones.parse(build_workbook())
    assert (first.batch, first.pouch_no, first.carton) == ("SL01G", "1", "3")
    assert (first.pcs, first.ct, first.rate) == (20, Decimal("12.5"), Decimal("100"))
    assert ruby.pcs is None                       # blank Pcs: uncountable
    assert jade.pouch_no == ""


def test_a_workbook_without_the_stone_columns_is_refused():
    from io import BytesIO
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "SL"
    book.active.append(["Jewel Code", "Gross Wt"])
    buffer = BytesIO()
    book.save(buffer)
    buffer.seek(0)
    assert stones.header_problems(buffer)
    assert stones.header_problems(build_workbook()) == []
```

- [ ] **Step 3: Run to see it fail**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_import_parse.py -v`
Expected: FAIL — `No module named 'inventory.importers'`.

- [ ] **Step 4: Write the reader**

`inventory/importers/__init__.py`:

```python
"""Reading the owner's stock registers into the inventory."""
```

`inventory/importers/stones.py`:

```python
"""The stones register: ``Nornament_Stones_Stock_Chetna_*.xlsx``.

Five sheets are stones (SP, PR, Mix, SR, SL). Googri and Jadau are finished
components, not stones, and are skipped. Row 1 is the header; 14 columns
matter and the rest (``New Code``, ``Old Gati Code``) are dead. Values are kept
as typed. Cleaning them up is a data-quality job, and the review screen is
where a human decides anything this reader cannot.
"""
from dataclasses import dataclass
from decimal import Decimal

from openpyxl import load_workbook

SHEETS = ("SP", "PR", "Mix", "SR", "SL")

COLUMNS = {
    "batch": "New Gati Code",
    "pouch_no": "Batch No.",
    "carton": "Box No",
    "category": "Category",
    "stone_name": "Stone Name",
    "shape": "Shape",
    "size_text": "Size Length * Width",
    "colour": "Colour",
    "cut": "Cut",
    "quality": "Quality",
    "pcs": "Pcs",
    "ct": "Weight in Cts / Qty",
    "rate": "Price Per Carat / Pc",
    "remarks": "Remarks",
}

REQUIRED = ("New Gati Code", "Weight in Cts / Qty")


@dataclass
class Row:
    src: str
    batch: str
    pouch_no: str
    carton: str
    category: str
    stone_name: str
    shape: str
    size_text: str
    colour: str
    cut: str
    quality: str
    remarks: str
    pcs: int = None
    ct: Decimal = None
    rate: Decimal = None


def _text(value):
    """A cell as the owner typed it. ``1.0`` from Excel is the pouch number 1."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _number(value):
    """Numbers only: "N.A" in a weight column is no weight, not an error."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


def _pieces(value):
    number = _number(value)
    # ponytail: a fractional piece count is rounded; flag it in review if one ever appears
    return None if number is None else int(number.to_integral_value())


def _sheets(workbook):
    return [name for name in SHEETS if name in workbook.sheetnames]


def _header(sheet):
    return [_text(cell) for cell in next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), [])]


def header_problems(fileobj):
    """Why this is not a stones register, or ``[]``."""
    try:
        workbook = load_workbook(fileobj, read_only=True, data_only=True)
    except Exception as error:
        return [f"It does not open as a workbook ({error})."]
    names = _sheets(workbook)
    if not names:
        return [f"None of the stone sheets ({', '.join(SHEETS)}) is in it."]
    problems = []
    for name in names:
        header = _header(workbook[name])
        missing = [column for column in REQUIRED if column not in header]
        if missing:
            problems.append(f"Sheet {name} has no {', '.join(missing)} column.")
    return problems


def parse(fileobj):
    workbook = load_workbook(fileobj, read_only=True, data_only=True)
    rows = []
    for name in _sheets(workbook):
        sheet = workbook[name]
        header = _header(sheet)
        where = {field: header.index(title) for field, title in COLUMNS.items() if title in header}
        for number, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if not any(v not in (None, "") for v in values):
                continue

            def cell(field):
                index = where.get(field)
                return values[index] if index is not None and index < len(values) else None

            rows.append(Row(
                src=f"{name}!{number}",
                batch=_text(cell("batch")).upper(),
                pouch_no=_text(cell("pouch_no")),
                carton=_text(cell("carton")),
                category=_text(cell("category")),
                stone_name=_text(cell("stone_name")),
                shape=_text(cell("shape")),
                size_text=_text(cell("size_text")),
                colour=_text(cell("colour")),
                cut=_text(cell("cut")),
                quality=_text(cell("quality")),
                remarks=_text(cell("remarks")),
                pcs=_pieces(cell("pcs")),
                ct=_number(cell("ct")),
                rate=_number(cell("rate")),
            ))
    return rows
```

- [ ] **Step 5: Run the tests**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_import_parse.py -v`
Expected: PASS. If `first.batch` comes back as `"SL01G"` but `Broken` comes back as `"BROKEN"`, that is intended — codes are upper-cased, and `BROKEN` still fails the grammar.

- [ ] **Step 6: Commit**

```bash
git add inventory/importers inventory/tests/fixtures_stones.py inventory/tests/test_import_parse.py
git commit -m "Read the stones register, five sheets, fourteen columns, as typed"
```

---

### Task 5: Decide, then commit

**Files:**
- Create: `inventory/importers/plan.py`, `inventory/tests/test_import_plan.py`

**Interfaces:**
- Consumes: `stones.Row`, `stones.parse`, `rules.parse_batch_code`, `services.open_pouches`, `services.recount`, `services.add_price`, `services.stocked`, the models.
- Produces:
  - `plan.Item` dataclass: `row, batch, pouch_no, skip, problem, suggestion, existing, held_pcs, held_ct, recount`
  - `plan.analyse(rows, decisions=None) -> [Item]`
  - `plan.read_decisions(post, items, decisions) -> dict`: decisions are keyed by `src`, each `{"batch", "pouch_no", "skip"}`
  - `plan.counts(items) -> dict` with keys `rows, skip, blocked, create, update, no_pouch_no, recount`
  - `plan.attention(items) -> [Item]`
  - `plan.commit(items, user, import_batch=None) -> {"created", "updated", "recounted", "skipped"}`

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_import_plan.py`:

```python
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import seed, services
from inventory.importers import plan, stones
from inventory.models import BoxColour, CodePart, Movement, Pouch
from inventory.tests.fixtures_stones import build_workbook
from stock.services import ServiceError

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _codes():
    seed.load(BoxColour, CodePart)


def _items(decisions=None):
    return plan.analyse(stones.parse(build_workbook()), decisions)


def _by_src(items):
    return {item.row.src: item for item in items}


def test_the_review_finds_every_case():
    items = _by_src(_items())
    assert items["SL!4"].problem and "SL!2" in items["SL!4"].problem      # duplicate key
    assert items["SL!6"].problem                                          # batch code does not read
    assert items["SL!5"].problem is None and items["SL!5"].suggestion == "1"
    assert items["SL!2"].problem is None and items["SL!7"].problem is None
    assert plan.counts(list(items.values()))["blocked"] == 2


def test_a_blocked_import_cannot_commit(admin_user_):
    with pytest.raises(ServiceError):
        plan.commit(_items(), admin_user_)
    assert not Pouch.objects.exists()


def _decided():
    return {"SL!4": {"batch": "", "pouch_no": "9", "skip": False}, "SL!6": {"batch": "", "pouch_no": "", "skip": True}}


def test_commit_opens_every_decided_row(admin_user_):
    result = plan.commit(_items(_decided()), admin_user_)
    assert result == {"created": 5, "updated": 0, "recounted": 0, "skipped": 1}
    assert Pouch.objects.get(batch__code="SL01G", pouch_no="9").stone_name == "Green Onyx"
    assert Pouch.objects.get(src="SL!5").pouch_no is None                # left blank, as decided
    assert BoxColour.objects.get(code="F").confirmed is False            # seeded, unconfirmed
    pearl = services.stocked(Pouch.objects.filter(src="SL!7")).get()
    assert pearl.rate is None                                            # no rate: cannot be valued


def test_reimport_updates_and_recounts(admin_user_):
    plan.commit(_items(_decided()), admin_user_)
    from inventory.tests.fixtures_stones import SHEETS_DEFAULT, _row

    changed = {"SL": [_row("SL01G", 1, "Green Onyx", "Green", 18, 13, 100)]}
    items = plan.analyse(stones.parse(build_workbook(changed)))
    assert items[0].existing is not None and items[0].recount
    result = plan.commit(items, admin_user_)
    assert result["updated"] == 1 and result["recounted"] == 1
    onyx = services.stocked(Pouch.objects.filter(batch__code="SL01G", pouch_no="1")).get()
    assert (onyx.on_pcs, onyx.on_ct) == (18, Decimal("13"))
    assert onyx.movements.filter(reason=Movement.Reason.RECOUNT_ADJUSTMENT).count() == 2


def test_fill_suggested_numbers_only_blank_ones():
    items = _items()
    post = {f"pouch_no:{i.row.src}": "" for i in plan.attention(items)}
    post |= {f"batch:{i.row.src}": "" for i in plan.attention(items)}
    post["fill_suggested"] = "1"
    decisions = plan.read_decisions(post, items, {})
    assert decisions["SL!5"]["pouch_no"] == "1"


def test_sales_cannot_import(sales_user):
    with pytest.raises(PermissionDenied):
        plan.commit(_items(_decided()), sales_user)
```

- [ ] **Step 2: Run to see them fail**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_import_plan.py -v`
Expected: FAIL — `cannot import name 'plan'`.

- [ ] **Step 3: Write `inventory/importers/plan.py`**

```python
"""What an import would do, then doing it.

``analyse`` writes nothing: it turns rows and the reviewer's decisions into
items, each either fine, blocked (``problem``), or an update to a pouch already
here. The review screen renders them; ``commit`` refuses while anything is
blocked and then writes everything in one transaction.

Decisions are keyed by source row (``SL!104``) because that is the one thing
about a row that the reviewer's edits cannot change.
"""
from collections import defaultdict
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from accounts.capabilities import INV_MASTERS
from stock.services import ServiceError, log, require

from .. import rules, services
from ..models import UNRESOLVED_SWATCH, Batch, BoxColour, CodePart, Pouch, PriceEntry


@dataclass
class Item:
    row: object
    batch: str
    pouch_no: str
    skip: bool = False
    problem: str = None
    suggestion: str = ""
    existing: object = None
    held_pcs: int = None
    held_ct: object = None
    recount: bool = False


def _item(row, choice):
    batch = (choice.get("batch") or row.batch).strip().upper()
    pouch_no = choice["pouch_no"].strip() if "pouch_no" in choice else row.pouch_no
    return Item(row=row, batch=batch, pouch_no=pouch_no, skip=bool(choice.get("skip")))


def _order(item):
    sheet, number = item.row.src.split("!")
    return (item.batch, sheet, int(number))


def _suggest(items):
    """The next free number in each batch, above the highest numeric one in use.

    Starting above the maximum is what makes a suggestion collision-free
    against numbers; a text pouch no. like "3A" is not counted.
    """
    top = defaultdict(int)
    for code, pouch_no in Pouch.objects.exclude(pouch_no=None).values_list("batch__code", "pouch_no"):
        if pouch_no.isdigit():
            top[code] = max(top[code], int(pouch_no))
    for item in items:
        if item.pouch_no.isdigit():
            top[item.batch] = max(top[item.batch], int(item.pouch_no))
    for item in sorted((i for i in items if not i.pouch_no), key=_order):
        top[item.batch] += 1
        item.suggestion = str(top[item.batch])


def _match(items):
    keyed = {(p.batch.code, p.pouch_no): p for p in Pouch.objects.exclude(pouch_no=None).select_related("batch")}
    unkeyed = {p.src: p for p in Pouch.objects.filter(pouch_no=None).exclude(src="")}
    for item in items:
        if not item.problem:
            item.existing = keyed.get((item.batch, item.pouch_no)) if item.pouch_no else unkeyed.get(item.row.src)
    ids = [item.existing.pk for item in items if item.existing]
    held = {p.pk: p for p in services.stocked(Pouch.objects.filter(pk__in=ids))}
    for item in items:
        if item.existing:
            pouch = held[item.existing.pk]
            item.held_pcs, item.held_ct = pouch.on_pcs, pouch.on_ct
            item.recount = (
                (item.row.pcs is not None and item.row.pcs != (pouch.on_pcs or 0))
                or (item.row.ct is not None and item.row.ct != (pouch.on_ct or 0))
            )


def analyse(rows, decisions=None):
    decisions = decisions or {}
    items = [_item(row, decisions.get(row.src) or {}) for row in rows]
    live = [item for item in items if not item.skip]
    for item in live:
        row = item.row
        if not rules.parse_batch_code(item.batch):
            item.problem = "Batch code does not read as family · class · number · box colour"
        elif (row.ct is not None and row.ct < 0) or (row.pcs is not None and row.pcs < 0):
            item.problem = "Negative weight or pieces"
    first = {}
    for item in live:
        if item.problem or not item.pouch_no:
            continue
        key = (item.batch, item.pouch_no)
        if key in first:
            item.problem = f"{item.batch} · {item.pouch_no} is also {first[key]}"
        else:
            first[key] = item.row.src
    _match(live)
    _suggest(items)
    return items


def read_decisions(post, items, decisions):
    """The review form's answers, merged into what was already decided."""
    decisions = dict(decisions or {})
    fill = bool(post.get("fill_suggested"))
    for item in items:
        src = item.row.src
        if f"pouch_no:{src}" not in post:
            continue
        choice = {
            "batch": (post.get(f"batch:{src}") or "").strip(),
            "pouch_no": (post.get(f"pouch_no:{src}") or "").strip(),
            "skip": bool(post.get(f"skip:{src}")),
        }
        if fill and not choice["pouch_no"] and item.suggestion:
            choice["pouch_no"] = item.suggestion
        decisions[src] = choice
    return decisions


def attention(items):
    return [item for item in items if item.problem or item.skip or not item.pouch_no]


def counts(items):
    live = [item for item in items if not item.skip]
    return {
        "rows": len(items),
        "skip": len(items) - len(live),
        "blocked": sum(1 for i in live if i.problem),
        "create": sum(1 for i in live if not i.problem and not i.existing),
        "update": sum(1 for i in live if i.existing),
        "no_pouch_no": sum(1 for i in live if not i.pouch_no),
        "recount": sum(1 for i in live if i.recount),
    }


def _batch(code, cache):
    if code in cache:
        return cache[code]
    family, cls, seq, box = rules.parse_batch_code(code)
    colour, _ = BoxColour.objects.get_or_create(
        code=box, defaults={"label": "? unresolved", "swatch": UNRESOLVED_SWATCH, "confirmed": False}
    )
    for kind, part in ((CodePart.FAMILY, family), (CodePart.CLASS, cls)):
        CodePart.objects.get_or_create(kind=kind, code=part, defaults={"label": "? unknown", "confirmed": False})
    cache[code], _ = Batch.objects.get_or_create(
        code=code, defaults={"box_colour": colour, "family": family, "cls": cls, "seq": seq}
    )
    return cache[code]


def _fields(item):
    row = item.row
    return {
        "pouch_no": item.pouch_no or None, "carton": row.carton, "category": row.category,
        "stone_name": row.stone_name, "colour": row.colour, "shape": row.shape, "cut": row.cut,
        "quality": row.quality, "size_text": row.size_text, "remarks": row.remarks, "src": row.src,
        "countable": row.pcs is not None,
    }


@transaction.atomic
def commit(items, user, import_batch=None):
    require(user, INV_MASTERS, "Only a role that edits inventory records can import stock.")
    blocked = [item for item in items if item.problem and not item.skip]
    if blocked:
        raise ServiceError(f"{len(blocked)} rows still need a decision.")
    result = {"created": 0, "updated": 0, "recounted": 0, "skipped": 0}
    cache, fresh = {}, []
    for item in items:
        if item.skip:
            result["skipped"] += 1
            continue
        batch = _batch(item.batch, cache)
        if item.existing is None:
            fresh.append((batch, _fields(item), item.row.pcs, item.row.ct, item.row.rate))
            continue
        pouch = item.existing
        for name, value in _fields(item).items():
            setattr(pouch, name, value)
        pouch.batch = batch
        pouch.save()
        result["updated"] += 1
        if item.recount:
            services.recount(user, pouch, item.row.pcs, item.row.ct, note=f"re-imported from {item.row.src}")
            result["recounted"] += 1
        current = services.stocked(Pouch.objects.filter(pk=pouch.pk)).get().rate
        if item.row.rate is not None and item.row.rate != current:
            services.add_price(user, pouch, PriceEntry.VALUATION, item.row.rate, timezone.localdate())
    result["created"] = len(services.open_pouches(user, fresh, import_batch=import_batch))
    log(user, "IMPORT", "inv_pouch", import_batch.pk if import_batch else "-", f"stones import {result}")
    return result
```

- [ ] **Step 4: Run the tests**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_import_plan.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add inventory/importers/plan.py inventory/tests/test_import_plan.py
git commit -m "Analyse a stones import into decisions, and commit only when none are open"
```

---

### Task 6: The shell, the stylesheet, and the shelf

**Files:**
- Create: `static/css/inventory.css`, `templates/inventory_base.html`, `inventory/templates/inventory/_rail.html`, `inventory/templates/inventory/_picture.html`, `inventory/templates/inventory/shelf.html`, `inventory/templatetags/__init__.py`, `inventory/templatetags/inventory_extras.py`, `inventory/rows.py`, `inventory/tests/test_views.py`
- Modify: `inventory/views.py`, `inventory/urls.py`, `stock/masking.py`, `stock/context_processors.py`

**Interfaces:**
- Consumes: `services.stocked`, `services.value_of`, `rules.*`, `stock.masking.mask`.
- Produces:
  - `rows.CLIENT_HIDDEN`
  - `rows.pouch_rows(user, pouches, client=False) -> [dict]`, where each dict has the keys listed in `pouch_row`
  - `rows.summarise(rows) -> dict`
  - `rows.by_colour(rows) -> [dict]`
  - `rows.by_batch(rows, labels) -> [dict]`
  - `rows.shares(row, rows) -> dict`
  - `rows.decoder(batch, labels) -> [dict]`
  - `views._page(request, template, everything, **context)` and `views._client(request)`
  - URL names `inventory:shelf` and `inventory:set_view`
  - template filters `rupees`, `ct`, `grouped` and `kg`, and the tag `{% silhouette shape hex %}`

- [ ] **Step 1: Write the failing view tests**

`inventory/tests/test_views.py`:

```python
import pytest
from django.urls import reverse

from inventory.tests.conftest import VALUE

pytestmark = pytest.mark.django_db


def test_the_shelf_groups_by_box_colour(client, admin_user_, shelf):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert "Shelf — by box colour" in body
    assert "Green" in body and "1,00,988" in body       # 98,987.50 + 2,000 across the box colour
    assert "1 misfiled" in body                     # Ruby Glass, red, in a green box


def test_every_role_may_open_the_shelf(client, shelf, sales_user, karigar_user, graphic_user, production_user):
    for user in (sales_user, karigar_user, graphic_user, production_user):
        client.force_login(user)
        assert client.get(reverse("inventory:shelf")).status_code == 200, user


def test_the_view_switch_is_remembered(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client", "next": reverse("inventory:shelf")})
    body = client.get(reverse("inventory:shelf")).content.decode()
    assert 'data-view="client"' in body and "Stock value" not in body
```

- [ ] **Step 2: Run to see them fail**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_views.py -v`
Expected: FAIL — `NoReverseMatch: 'shelf'`.

- [ ] **Step 3: Lift the stylesheet**

```bash
sed -n '8,443p' ../Nornament_Inventory/04-source-scripts/_head.html > static/css/inventory.css
```

Prepend this header as the first lines of `static/css/inventory.css`:

```css
/* Lifted verbatim from Nornament_Inventory/04-source-scripts/_head.html lines 8-443 —
   the visual spec. Everything after the "Django compat" rule below is added. */
```

Append to the end of `static/css/inventory.css`:

```css
/* ═══════════════════════ Django compat ═══════════════════════
   The prototype drew with <button onclick>; these are links and forms. */
a.imgcard{display:block;text-decoration:none}
.catsw a,.catsw span{display:block;text-align:center;text-decoration:none;color:var(--muted);font-size:12px;
  font-weight:560;padding:7px 4px;border-radius:6px}
.catsw a.on{background:var(--s1);color:#fff;box-shadow:0 1px 2px rgba(11,11,11,.18)}
.catsw span{opacity:.55;cursor:not-allowed}
.tabs a,.tabs button{background:none;border:0;color:var(--muted);font-size:13px;padding:11px 14px;cursor:pointer;
  border-bottom:2px solid transparent;margin-bottom:-1px;text-decoration:none}
.tabs a:hover{color:var(--ink2)}
.tabs a.on{color:var(--ink);border-bottom-color:var(--s1)}
.tabs button:disabled{color:#b5b3ac;cursor:default}
.bcrumb a{color:var(--s1);font-size:12px;text-decoration:none}
.bcrumb a:hover{text-decoration:underline}
.vtog a{color:var(--muted);font-size:12px;padding:5px 11px;border-radius:6px;text-decoration:none}
.vtog a.on{background:var(--raised);color:var(--ink);box-shadow:0 1px 2px rgba(11,11,11,.08)}
.vt{margin:0}
.nav .locked{display:flex;align-items:center;gap:10px;padding:7px 18px;color:var(--muted);font-size:13px;
  opacity:.6;cursor:not-allowed}
.nav .locked .ct{margin-left:auto;font-size:11px;font-variant-numeric:tabular-nums}
.search.locked{opacity:.6;cursor:not-allowed}
.btn:disabled{opacity:.5;cursor:not-allowed}
a.btn{text-decoration:none}
.rail-foot a{color:var(--s1);text-decoration:none}
.inline{display:inline}
.linkish{background:none;border:0;color:var(--s1);cursor:pointer;font:inherit;font-size:11px;padding:0}
/* the .rt role-pill rule was global and put a border on the tile badge */
.tile .badge.rt{border:0;border-radius:6px;font-size:11px;padding:2px 7px}
.tile img.photo,.ph img.photo{width:100%;height:100%;object-fit:cover}
.thumbs{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
.thumbs img{width:44px;height:44px;object-fit:cover;border-radius:6px;border:1px solid var(--border)}
.upload{position:relative;display:block;cursor:pointer}
.upload input{position:absolute;inset:0;opacity:0;cursor:pointer}
.pt td input.inp{padding:5px 8px;font-size:12px}
.tx-top{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
@media(max-width:1120px){.tx-top{grid-template-columns:1fr}}
select.chip{appearance:none;cursor:pointer;font:inherit;font-size:11px}
.messages{list-style:none;margin:0 0 14px}
.messages li{padding:9px 13px;border-radius:8px;font-size:13px;border:1px solid var(--border);
  background:var(--surface);margin-bottom:6px}
.messages .error{border-color:rgba(208,59,59,.42);background:rgba(208,59,59,.08);color:var(--critink)}
.messages .success{border-color:rgba(12,163,12,.35);background:rgba(12,163,12,.08);color:var(--goodink)}

/* ═══════════════════════ dark mode ═══════════════════════ */
:root[data-theme="dark"]{
  color-scheme:dark;
  --plane:#0d0d0d; --surface:#1a1a19; --raised:#242422; --sunken:#141413;
  --ink:#fff; --ink2:#c3c2b7; --muted:#898781; --line:#383835; --border:rgba(255,255,255,.12);
  --goodink:#3fd13f; --warnink:#fab219; --critink:#e06a6a; --infoink:#7fb2ee;
}
:root[data-theme="dark"] .top{background:rgba(13,13,13,.88)}
:root[data-theme="dark"] .tabs button:disabled{color:#55544f}

/* ═══════════════════════ phone: the rail becomes a drawer ═══════════════════════ */
.burger{display:none;flex:none;background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:5px 11px;font-size:16px;line-height:1.2;color:var(--ink2)}
.navscrim{display:none}
@media (max-width:860px){
  .app{grid-template-columns:1fr}
  .burger{display:inline-block}
  .rail{position:fixed;top:0;left:0;bottom:0;z-index:50;width:min(280px,84vw);height:100dvh;
    transform:translateX(-100%);transition:transform .22s ease;box-shadow:0 8px 24px rgba(11,11,11,.2)}
  body.navopen .rail{transform:none}
  .navscrim{display:block;position:fixed;inset:0;z-index:45;background:rgba(11,11,11,.42);backdrop-filter:blur(2px)}
  .navscrim[hidden]{display:none}
  body.navopen{overflow:hidden}
  .nav a,.nav .locked{padding:11px 18px}
  .top{padding:10px 14px;gap:9px;flex-wrap:wrap}
  .search{display:none}
  .tabs{position:static;overflow-x:auto;padding:0 10px}
  .wrap{padding:16px 14px 48px}
  .head-act{margin-left:0;flex-wrap:wrap}
  .kpis{grid-template-columns:1fr 1fr}
}
```

In `stock/context_processors.py`, `asset_version`, change the tuple `("app.css", "crm.css")` to `("app.css", "crm.css", "inventory.css")`.

- [ ] **Step 4: Gate the new money fields**

In `stock/masking.py`, add to `GATED_FIELDS`:

```python
    # the inventory's own names for the same three secrets
    "stone_rate": VIEW_COST,
    "pouch_value": VIEW_COST,
    "valuation_rate": VIEW_COST,
    "purchase_rate": VIEW_COST,
    "list_rate": VIEW_SALE,
    "supplier_name": VIEW_VENDOR,
```

- [ ] **Step 5: Write the template tags**

`inventory/templatetags/__init__.py`: empty.

`inventory/templatetags/inventory_extras.py`:

```python
"""Number formats the prototype used (``toLocaleString('en-IN')``), and its silhouettes."""
from decimal import Decimal

from django import template
from django.utils.safestring import mark_safe

from crm.templatetags import crm_extras
from inventory import rules

register = template.Library()


@register.filter
def rupees(value):
    """``₹1,72,49,719``, or ``—`` when there is no figure — never ``₹0`` for a missing one."""
    return "—" if value is None or value == "" else crm_extras.inr(value)


@register.filter
def grouped(value):
    return "—" if value is None or value == "" else crm_extras.inr(value).replace("₹", "")


@register.filter
def ct(value):
    """``10,56,315.10`` — carats to two places, Indian grouping."""
    if value is None or value == "":
        return "—"
    whole, frac = f"{Decimal(value):.2f}".split(".")
    return crm_extras.inr(whole).replace("₹", "") + "." + frac


@register.filter
def kg(value):
    """Carats as kilograms: a carat is 0.2 g."""
    return "—" if value is None else f"{Decimal(value) * Decimal('0.2') / 1000:.0f}"


@register.simple_tag
def silhouette(shape, hex_colour):
    # the shape only picks a branch in rules.shape_svg and the colour comes from
    # its own table, so nothing the owner typed reaches the markup
    return mark_safe(rules.shape_svg(shape, hex_colour))
```

- [ ] **Step 6: Write the row builder**

`inventory/rows.py`:

```python
"""The rows every inventory screen renders, built once and masked once.

A row is a plain dict. Money goes through ``stock.masking.mask`` like every
other screen in the app; client mode also strips the shelf layout, so the
server never sends what the client must not see. Templates test for a key
(``'pouch_value' in row``), never for a capability.

ponytail: every screen reads every pouch (≈3,000) and groups in Python —
one query, well under a second. Aggregate in SQL if the shelf passes ~50,000.
"""
from collections import Counter, defaultdict

from mediahub.models import MediaAsset
from stock.enums import MediaKind
from stock.masking import mask

from . import rules, services

#: what a client is never sent: where it is filed, what it cost, what is wrong with it
CLIENT_HIDDEN = {
    "batch_code", "pouch_no", "no_pouch_no", "carton", "family", "cls", "seq", "remarks", "src",
    "stone_rate", "pouch_value", "purchase_date", "supplier_name", "misfiled", "box_confirmed",
}


def _photos(pouch_ids):
    """First photo per pouch, by rank. One query."""
    first = {}
    assets = (
        MediaAsset.objects.filter(scope="pouch", scope_id__in=[str(i) for i in pouch_ids],
                                  kind=MediaKind.PHOTO, is_archived=False)
        .order_by("rank_order", "pk").values_list("scope_id", "pk")
    )
    for scope_id, pk in assets:
        first.setdefault(int(scope_id), pk)
    return first


def pouch_row(user, pouch, client=False, photo_id=None):
    box = pouch.batch.box_colour
    size_kind, size_display, _, _ = rules.parse_size(pouch.size_text)
    row = {
        "pk": pouch.pk, "ref": pouch.ref, "batch_pk": pouch.batch_id,
        "batch_code": pouch.batch.code, "pouch_no": pouch.pouch_no or "", "no_pouch_no": not pouch.pouch_no,
        "carton": pouch.carton, "box_colour": box.code, "box_label": box.label, "box_swatch": box.swatch,
        "box_confirmed": box.confirmed, "family": pouch.batch.family, "cls": pouch.batch.cls, "seq": pouch.batch.seq,
        "category": pouch.category, "stone_name": pouch.stone_name, "colour": pouch.colour,
        "shape": pouch.shape, "cut": pouch.cut, "quality": pouch.quality,
        "size_kind": size_kind, "size_display": size_display,
        "countable": pouch.countable, "pcs": pouch.on_pcs if pouch.countable else None, "ct": pouch.on_ct,
        "colour_hex": rules.colour_hex(pouch.colour), "misfiled": rules.is_misfiled(pouch.colour, box.label),
        "remarks": pouch.remarks, "src": pouch.src,
        "treatment": pouch.treatment, "origin": pouch.origin, "purchase_date": pouch.purchase_date,
        "supplier_name": pouch.supplier.name if pouch.supplier_id else None,
        "stone_rate": pouch.rate, "pouch_value": services.value_of(pouch),
        "photo_id": photo_id,
    }
    if client:
        row = {key: value for key, value in row.items() if key not in CLIENT_HIDDEN}
    return mask(user, row)


def pouch_rows(user, pouches, client=False):
    pouches = list(pouches)
    photos = _photos([p.pk for p in pouches])
    return [pouch_row(user, p, client=client, photo_id=photos.get(p.pk)) for p in pouches]


def _has(rows, key):
    return bool(rows) and key in rows[0]


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
        "no_size": sum(1 for r in rows if r["size_kind"] in ("free", "none")),
        "no_photo": sum(1 for r in rows if not r["photo_id"]),
    }
    if _has(rows, "pouch_value"):
        out["value"] = sum((r["pouch_value"] or 0) for r in rows)
        out["unpriced"] = sum(1 for r in rows if r["pouch_value"] is None)
    if _has(rows, "misfiled"):
        out["misfiled"] = sum(1 for r in rows if r["misfiled"])
    if _has(rows, "no_pouch_no"):
        out["no_pouch_no"] = sum(1 for r in rows if r["no_pouch_no"])
        out["keyed"] = out["pouches"] - out["no_pouch_no"]
    if _has(rows, "carton"):
        out["boxes"] = sorted({r["carton"] for r in rows if r["carton"]}, key=lambda b: (len(b), b))
    return out


def by_colour(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["box_colour"]].append(row)
    colours = []
    for code, group in groups.items():
        first = group[0]
        colours.append({
            "code": code, "label": first["box_label"], "swatch": first["box_swatch"],
            "confirmed": first.get("box_confirmed", True), **summarise(group),
        })
    colours.sort(key=lambda c: -(c.get("value") if c.get("value") is not None else c["ct"]))
    return colours


def label(labels, kind, code):
    part = labels.get((kind, code))
    return part.label if part else "? unknown"


def by_batch(rows, labels):
    """One card per batch, in batch-code order (the rows arrive that way)."""
    groups = {}
    for row in rows:
        groups.setdefault(row["batch_pk"], []).append(row)
    batches = []
    for pk, group in groups.items():
        first = group[0]
        names = Counter(r["stone_name"] or "—" for r in group).most_common(2)
        card = {
            "pk": pk, "names": ", ".join(name for name, _ in names), "shape": first["shape"],
            "hex": first["colour_hex"], "photo_id": next((r["photo_id"] for r in group if r["photo_id"]), None),
            **summarise(group),
        }
        if "batch_code" in first:
            card["code"] = first["batch_code"]
            card["family_label"] = label(labels, "family", first["family"])
            card["class_label"] = label(labels, "class", first["cls"])
        batches.append(card)
    return batches


def shares(row, rows):
    """This pouch's value as a share of its batch, its box colour and all stock."""
    def pct(part, whole, places):
        return "—" if not part or not whole else f"{100 * part / whole:.{places}f}"

    value = row["pouch_value"]
    batch = sum((r["pouch_value"] or 0) for r in rows if r["batch_pk"] == row["batch_pk"])
    colour = sum((r["pouch_value"] or 0) for r in rows if r["box_colour"] == row["box_colour"])
    total = sum((r["pouch_value"] or 0) for r in rows)
    return {"batch": pct(value, batch, 0), "colour": pct(value, colour, 1), "all": pct(value, total, 2)}


def decoder(batch, labels):
    """The batch-code strip: what each segment of ``SR01Y`` means, and which are doubtful."""
    box = batch.box_colour
    family, cls = labels.get(("family", batch.family)), labels.get(("class", batch.cls))
    return [
        {"char": batch.family, "label": "material family", "value": family.label if family else "? unknown",
         "doubt": not (family and family.confirmed)},
        {"char": batch.cls, "label": "class", "value": cls.label if cls else "? unknown",
         "doubt": not (cls and cls.confirmed)},
        {"char": batch.seq, "label": "batch no.", "value": "sequence within colour", "doubt": False},
        {"char": box.code, "label": "box colour", "value": box.label, "doubt": not box.confirmed},
    ]
```

- [ ] **Step 7: Write the views and URLs for the shelf**

Replace `inventory/views.py` with:

```python
"""The inventory screens. Thin: services write, rows mask, templates draw."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import rows, services
from .models import CodePart


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
```

Replace `inventory/urls.py` with:

```python
from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.shelf, name="shelf"),
    path("view/", views.set_view, name="set_view"),
]
```

- [ ] **Step 8: Write the shell**

`templates/inventory_base.html`:

```django
{% load static %}<!doctype html>
{% comment %}
The inventory's shell — the prototype's own markup (Nornament_Inventory
_head.html lines 446-534): the rail with the Stones/Diamonds switch, the top bar
with the Internal / Client preview toggle, and the tab strip. It does not load
app.css: both stylesheets define .card, .btn, .chip, .tabs and .nav, and they
would fight on every page.
{% endcomment %}
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Inventory{% endblock %} · Nornament</title>
  <link rel="stylesheet" href="{% static 'css/inventory.css' %}{{ asset_v }}">
  <script>document.documentElement.dataset.theme = localStorage.theme ??
    (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : '');</script>
</head>
<body data-view="{% if client_view %}client{% else %}internal{% endif %}">
{% include "_preloader.html" %}
<div class="app">
  <div class="navscrim" hidden></div>
  <aside class="rail" id="sidenav">
    <div class="brand"><div class="brand-mark"></div>
      <div><div class="brand-name">Nornament</div><div class="brand-sub">Inventory</div></div></div>
    <div class="catsw">
      <a class="on" href="{% url 'inventory:shelf' %}">◆ Stones</a>
      <span title="Coming soon">◇ Diamonds 🔒</span>
    </div>
    {% include "inventory/_rail.html" %}
    <div class="rail-foot">
      <div class="who"><span class="avatar">{{ user.get_username|first|upper }}</span>{{ user.full_name|default:user.get_username }} · {{ role_name }}</div>
      <a href="{% url 'stock:dashboard' %}">Stock</a> · <a href="{% url 'crm:dashboard' %}">CRM</a> ·
      <form method="post" action="{% url 'accounts:logout' %}" class="inline">{% csrf_token %}<button class="linkish">Sign out</button></form>
    </div>
  </aside>

  <div class="main">
    <div class="top">
      <button class="burger" type="button" aria-label="Show navigation" aria-controls="sidenav" aria-expanded="false">☰</button>
      <div class="crumb">{% block crumb %}{% endblock %}</div>
      <div class="spacer"></div>
      <div class="search locked" title="Coming soon">Search batch, pouch, stone… 🔒</div>
      <form class="vt" method="post" action="{% url 'inventory:set_view' %}">{% csrf_token %}
        <input type="hidden" name="next" value="{{ request.get_full_path }}">
        <button name="view" value="internal" class="{% if not client_view %}on{% endif %}">🔓 Internal</button>
        <button name="view" value="client" class="{% if client_view %}on{% endif %}">👁 Client preview</button>
      </form>
      <button class="btn sm" type="button" title="Toggle light / dark"
        onclick="const r=document.documentElement;r.dataset.theme=r.dataset.theme==='dark'?'':'dark';localStorage.theme=r.dataset.theme">◐</button>
    </div>

    <div class="tabs">
      <a class="{% if tab == 'shelf' %}on{% endif %}" href="{% url 'inventory:shelf' %}">Shelf</a>
      {% if pouch_ref %}<a class="{% if tab == 'lot' %}on{% endif %}" href="{% url 'inventory:pouch' pouch_ref %}">Pouch detail</a>
      {% else %}<button disabled>Pouch detail</button>{% endif %}
      {% if not client_view %}
        {% if pouch_ref %}<a class="{% if tab == 'tx' %}on{% endif %}" href="{% url 'inventory:movements' pouch_ref %}">Movements</a>
        {% else %}<button disabled>Movements</button>{% endif %}
        <button disabled title="Coming soon">Purchase 🔒</button>
      {% endif %}
      <button disabled title="Coming soon">Stock take 🔒</button>
    </div>

    <div class="wrap">
      {% if messages %}<ul class="messages">{% for message in messages %}<li class="{{ message.tags }}">{{ message }}</li>{% endfor %}</ul>{% endif %}
      {% block content %}{% endblock %}
    </div>
  </div>
</div>
<script>
/* The rail as a drawer below 860px — the same behaviour as base.html's. */
(function () {
  var burger = document.querySelector('.burger');
  var scrim = document.querySelector('.navscrim');
  if (!burger || !scrim) return;
  function show(open) {
    document.body.classList.toggle('navopen', open);
    burger.setAttribute('aria-expanded', open);
    scrim.hidden = !open;
  }
  burger.addEventListener('click', function () { show(!document.body.classList.contains('navopen')); });
  scrim.addEventListener('click', function () { show(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') show(false); });
  document.getElementById('sidenav').addEventListener('click', function (e) { if (e.target.closest('a')) show(false); });
})();
</script>
</body>
</html>
```

`inventory/templates/inventory/_rail.html`:

```django
{% load inventory_extras %}{% comment %}The prototype's rail, in its order. What
the prototype named but never built is shown locked, never as a dead link.{% endcomment %}
<div class="nav-h">Physical stock</div>
<nav class="nav">
  <a class="{% if tab == 'shelf' %}on{% endif %}" href="{% url 'inventory:shelf' %}"><span class="ic">▦</span>Box colours<span class="ct">{{ rail.colours }}</span></a>
  <a href="{% url 'inventory:shelf' %}"><span class="ic">◈</span>Batches<span class="ct">{{ rail.batches|grouped }}</span></a>
  <a href="{% url 'inventory:shelf' %}"><span class="ic">◆</span>Pouches<span class="ct">{{ rail.pouches|grouped }}</span></a>
  {% if rail.boxes %}<a href="{% url 'inventory:shelf' %}"><span class="ic">▤</span>Boxes<span class="ct">{{ rail.boxes|length }}</span></a>{% endif %}
</nav>

{% if not client_view %}
<div class="nav-h">Stock control</div>
<nav class="nav">
  {% if caps.inv_masters %}<a class="{% if tab == 'import' %}on{% endif %}" href="{% url 'inventory:import_home' %}"><span class="ic">⇅</span>Import stones</a>{% endif %}
  <span class="locked"><span class="ic">＋</span>Purchases<span class="ct">🔒</span></span>
  <span class="locked"><span class="ic">⇄</span>Movements<span class="ct">🔒</span></span>
  <span class="locked"><span class="ic">↗</span>Job work out<span class="ct">🔒</span></span>
  <span class="locked"><span class="ic">↘</span>Memo out<span class="ct">🔒</span></span>
  <span class="locked"><span class="ic">⊙</span>Stock takes<span class="ct">🔒</span></span>
  <span class="locked"><span class="ic">⤴</span>Splits &amp; merges<span class="ct">🔒</span></span>
  <span class="locked"><span class="ic">⇉</span>Transfers<span class="ct">🔒</span></span>
</nav>
{% endif %}

<div class="nav-h">Commercial</div>
<nav class="nav">
  {% if not client_view %}<span class="locked"><span class="ic">₹</span>Price list — cost<span class="ct">🔒</span></span>{% endif %}
  <span class="locked"><span class="ic">₹</span>Price list — selling<span class="ct">🔒</span></span>
  <span class="locked"><span class="ic">⌗</span>Suppliers<span class="ct">🔒</span></span>
  <span class="locked"><span class="ic">◐</span>Client lookbook<span class="ct">🔒</span></span>
</nav>

{% if not client_view %}
<div class="nav-h">Data quality</div>
<nav class="nav">
  {% if 'misfiled' in rail %}<span class="locked"><span class="ic" style="color:var(--warning)">⚑</span>Misfiled colour<span class="ct">{{ rail.misfiled|grouped }} 🔒</span></span>{% endif %}
  {% if 'no_pouch_no' in rail %}<span class="locked"><span class="ic" style="color:var(--critical)">!</span>No pouch no.<span class="ct">{{ rail.no_pouch_no|grouped }} 🔒</span></span>{% endif %}
  <span class="locked"><span class="ic">◱</span>Missing photos<span class="ct">{{ rail.no_photo|grouped }} 🔒</span></span>
  <span class="locked"><span class="ic">⤢</span>No size in mm<span class="ct">{{ rail.no_size|grouped }} 🔒</span></span>
</nav>
{% endif %}
```

`inventory/templates/inventory/_picture.html`:

```django
{% load inventory_extras %}{% if row.photo_id %}<img class="photo" src="{% url 'mediahub:media' row.photo_id %}" alt="{{ row.stone_name }}" loading="lazy">{% else %}{% silhouette row.shape row.colour_hex %}{% endif %}
```

- [ ] **Step 9: Write the shelf**

`inventory/templates/inventory/shelf.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Shelf{% endblock %}
{% block crumb %}Shelf{% endblock %}
{% block content %}
<div class="shelfbar"><h1>Shelf — by box colour</h1></div>

{% if not client_view %}
<div class="totstrip">
  {% if 'value' in totals %}<div class="tot heroTot"><div class="l">Stock value</div><div class="v">{{ totals.value|rupees }}</div><div class="f">weight in carats × rate</div></div>{% endif %}
  <div class="tot"><div class="l">Total weight</div><div class="v">{{ totals.ct|ct }} ct</div><div class="f">{{ totals.ct|kg }} kg</div></div>
  <div class="tot"><div class="l">Pouches</div><div class="v">{{ totals.pouches|grouped }}</div><div class="f">{{ totals.batches|grouped }} batches · {{ colours|length }} box colours</div></div>
  {% if 'unpriced' in totals %}<div class="tot"><div class="l">Not yet valued</div><div class="v">{{ totals.unpriced|grouped }}</div><div class="f">no weight or no rate</div></div>{% endif %}
</div>
{% if totals.no_pouch_no or totals.no_size %}
<div class="banner warn"><div class="banner-ic">!</div><div>
  <h4>{{ totals.no_pouch_no|grouped }} pouches have no pouch number, and {{ totals.no_size|grouped }} have no size in mm</h4>
  <p>Batch + pouch number keys {{ totals.keyed|grouped }} of {{ totals.pouches|grouped }} pouches.</p></div></div>
{% endif %}
{% endif %}

<div class="bcrumb"><b>All box colours</b></div>
<div class="colgrid2">
{% for c in colours %}
  <a class="imgcard" href="{% url 'inventory:colour' c.code %}">
    <div class="swtile" style="background:{{ c.swatch }}"><span class="code">{{ c.code }}</span></div>
    <div class="body">
      <div class="t1">{{ c.label }}</div>
      <div class="t2">{{ c.batches }} batches · {{ c.pouches|grouped }} pouches</div>
      {% if 'value' in c %}<div class="money">{{ c.value|rupees }}</div>{% endif %}
      <div class="t3">{{ c.ct|ct }} ct{% if c.boxes %} · box {{ c.boxes|slice:":3"|join:", " }}{% if c.boxes|length > 3 %}…{% endif %}{% endif %}</div>
      {% if not client_view %}<div class="flags">
        {% if not c.confirmed %}<span class="chip warn"><span class="dot"></span>code unknown</span>{% endif %}
        {% if c.misfiled %}<span class="chip warn"><span class="dot"></span>{{ c.misfiled }} misfiled</span>{% endif %}
        {% if c.unpriced %}<span class="chip warn"><span class="dot"></span>{{ c.unpriced }} unpriced</span>{% endif %}
      </div>{% endif %}
    </div>
  </a>
{% empty %}
  <p class="hint">No stones yet.</p>
{% endfor %}
</div>
{% endblock %}
```

The shelf links to `inventory:colour` and the rail to `inventory:import_home`; both arrive in later tasks. Until then add placeholder routes so the template reverses. In `inventory/urls.py`:

```python
    path("colours/<str:code>/", views.shelf, name="colour"),          # replaced in Task 7
    path("import/", views.shelf, name="import_home"),                  # replaced in Task 9
```

The base template also reverses `inventory:pouch` and `inventory:movements`, but only inside `{% if pouch_ref %}`, which no screen sets yet. Django resolves `{% url %}` lazily inside a false branch, so this is safe.

- [ ] **Step 10: Run the tests**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_views.py -v`
Expected: PASS.

- [ ] **Step 11: Look at it**

Run `../nornament-app/.venv/bin/python manage.py runserver`, log in as an admin, create one pouch from a shell as in the `shelf` fixture, open `/inventory/`, and compare it side by side with `01-prototype/nornament-ui-mockup.html` in a browser. They should match in layout, colours, radii and type. Fix only differences caused by the port; the prototype's CSS stays verbatim.

- [ ] **Step 12: Commit**

```bash
git add static/css/inventory.css templates/inventory_base.html inventory stock/masking.py stock/context_processors.py
git commit -m "The inventory shell, lifted from the prototype, and the shelf by box colour"
```

---

### Task 7: A box colour, and a batch as grid or table

**Files:**
- Create: `inventory/templates/inventory/colour.html`, `inventory/templates/inventory/batch.html`
- Modify: `inventory/views.py`, `inventory/urls.py`, `inventory/tests/test_views.py`

**Interfaces:**
- Consumes: `rows.by_batch`, `rows.decoder`, `views._labels`, `views._page`.
- Produces: URL names `inventory:colour` (`code`) and `inventory:batch` (`pk`).

- [ ] **Step 1: Write the failing tests**

Append to `inventory/tests/test_views.py`:

```python
def test_a_box_colour_lists_its_batches(client, admin_user_, shelf):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:colour", args=["G"])).content.decode()
    assert "Green — 1 batches" in body and "SL01G" in body and "2 pouches" in body
    assert "Stone · Lab / Man-made" in body and "1 colour mismatch" in body


def test_a_batch_shows_its_pouches_and_decodes_its_code(client, admin_user_, shelf):
    client.force_login(admin_user_)
    url = reverse("inventory:batch", args=[shelf["batch"].pk])
    grid = client.get(url).content.decode()
    assert "material family" in grid and "SL01G · 1" in grid and "uncountable" in grid
    table = client.get(url, {"view": "table"}).content.decode()
    assert "<th>Check</th>" in table and "chip good" in table          # Green Onyx: no flag, so ok


def test_show_all_lifts_the_forty_batch_cap(client, admin_user_, shelf):
    from inventory import services
    from inventory.models import Batch

    for n in range(2, 43):
        batch = Batch.objects.create(code=f"SL{n:02d}G", box_colour_id="G", family="S", cls="L", seq=f"{n:02d}")
        services.open_pouch(admin_user_, batch, {"pouch_no": "1", "colour": "Green"}, pcs=1, ct=1, rate=1)
    client.force_login(admin_user_)
    capped = client.get(reverse("inventory:colour", args=["G"])).content.decode()
    assert "Show all 42 batches" in capped
    assert "Show all" not in client.get(reverse("inventory:colour", args=["G"]), {"all": "1"}).content.decode()
```

- [ ] **Step 2: Run to see them fail**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_views.py -v`
Expected: the three new tests FAIL (the colour route is still the placeholder).

- [ ] **Step 3: Write the views**

Add to `inventory/views.py`:

```python
from django.shortcuts import get_object_or_404

from .models import Batch, BoxColour

BATCH_CAP = 40


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
```

In `inventory/urls.py`, replace the placeholder `colour` route and add `batch`:

```python
    path("colours/<str:code>/", views.colour, name="colour"),
    path("batches/<int:pk>/", views.batch, name="batch"),
```

- [ ] **Step 4: Write the templates**

`inventory/templates/inventory/colour.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}{{ box.label }}{% endblock %}
{% block crumb %}Shelf &nbsp;›&nbsp; {{ box.label }}{% endblock %}
{% block content %}
<div class="shelfbar"><h1>{{ box.label }} — {{ batch_total }} batches</h1></div>
<div class="bcrumb"><a href="{% url 'inventory:shelf' %}">All box colours</a> <span>›</span> <b>{{ box.label }} · {{ box.code }}</b></div>

<div class="cardgrid">
{% for b in batches %}
  <a class="imgcard" href="{% url 'inventory:batch' b.pk %}">
    <div class="tile" style="background:linear-gradient(160deg,#fbfaf7,{{ b.hex }}22)">
      {% if b.photo_id %}<img class="photo" src="{% url 'mediahub:media' b.photo_id %}" alt="" loading="lazy">{% else %}{% silhouette b.shape b.hex %}{% endif %}
      {% if b.code %}<span class="badge">{{ b.code }}</span>{% endif %}
      <span class="badge rt">{{ b.pouches }} pouch{{ b.pouches|pluralize:"es" }}</span>
      {% if not client_view and not b.photo_id %}<span class="nophoto">no photo yet</span>{% endif %}
    </div>
    <div class="body">
      <div class="t1">{{ b.names }}</div>
      {% if b.family_label %}<div class="t2">{{ b.family_label }} · {{ b.class_label }}</div>{% endif %}
      {% if 'value' in b %}<div class="money">{{ b.value|rupees }}</div>{% endif %}
      <div class="t3">{{ b.ct|ct }} ct{% if b.boxes %} · box {{ b.boxes|join:", " }}{% endif %}</div>
      {% if b.misfiled %}<div class="flags"><span class="chip warn"><span class="dot"></span>{{ b.misfiled }} colour mismatch</span></div>{% endif %}
    </div>
  </a>
{% endfor %}
</div>
{% if batches|length < batch_total %}
<div style="text-align:center;margin-top:18px"><a class="btn" href="?all=1">Show all {{ batch_total }} batches</a></div>
{% endif %}
{% endblock %}
```

`inventory/templates/inventory/batch.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}{% if client_view %}{{ names }}{% else %}{{ batch.code }}{% endif %}{% endblock %}
{% block crumb %}Shelf &nbsp;›&nbsp; {{ box.label }}{% if not client_view %} &nbsp;›&nbsp; <b class="mono">{{ batch.code }}</b>{% endif %}{% endblock %}
{% block content %}
<div class="shelfbar">
  <h1>{% if client_view %}{{ box.label }} · {{ names }}{% else %}Batch {{ batch.code }}{% endif %}</h1>
  <span class="spacer"></span>
  {% if not client_view %}<div class="vtog">
    <a class="{% if view == 'grid' %}on{% endif %}" href="?view=grid">▦ Grid</a>
    <a class="{% if view == 'table' %}on{% endif %}" href="?view=table">▤ Table</a>
  </div>{% endif %}
</div>
<div class="bcrumb"><a href="{% url 'inventory:shelf' %}">All box colours</a> <span>›</span>
  <a href="{% url 'inventory:colour' box.code %}">{{ box.label }} · {{ box.code }}</a>
  {% if not client_view %}<span>›</span> <b class="mono">{{ batch.code }}</b>{% endif %}</div>

{% if not client_view %}
<div class="dec-strip">
  {% for seg in decoder %}<div class="dec-seg{% if seg.doubt %} q{% endif %}"><div class="ch">{{ seg.char }}</div>
    <div class="lb">{{ seg.label }}</div><div class="vl">{{ seg.value }}</div></div>{% endfor %}
  <div class="dec-arrow">→</div>
  <div class="dec-seg" style="min-width:158px;border-color:rgba(42,120,214,.4)">
    <div class="ch" style="font-size:15px;padding-top:5px">{{ batch.code }}</div>
    <div class="lb">batch</div><div class="vl">+ pouch no. = the pouch</div></div>
</div>
{% endif %}

{% if view == 'table' %}
<div class="card" style="overflow:hidden">
  <div class="card-h"><span class="card-t">Pouches in {{ batch.code }}</span></div>
  <div style="overflow:auto"><table class="pt">
    <thead><tr><th>Pouch</th><th>Category</th><th>Stone</th><th>Shape</th><th>Colour</th><th>Cut</th><th>Q</th>
      <th class="r">Pcs</th><th class="r">Carats</th>{% if money %}<th class="r">Rate</th><th class="r">Value</th>{% endif %}
      <th>Size (mm)</th><th>Remarks</th><th>Check</th></tr></thead>
    <tbody>{% for p in pouches %}
      <tr onclick="location.href='{% url 'inventory:pouch' p.ref %}'">
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
</div>
{% else %}
<div class="cardgrid">
{% for p in pouches %}
  <a class="imgcard" href="{% url 'inventory:pouch' p.ref %}">
    <div class="tile" style="background:linear-gradient(160deg,#fbfaf7,{{ p.colour_hex }}22)">
      {% include "inventory/_picture.html" with row=p %}
      <span class="badge">{% if client_view %}{{ p.ref }}{% else %}{{ p.batch_code }} · {{ p.pouch_no|default:"?" }}{% endif %}</span>
      {% if p.quality %}<span class="badge rt">{{ p.quality }}</span>{% endif %}
      {% if not client_view and not p.photo_id %}<span class="nophoto">no photo yet</span>{% endif %}
    </div>
    <div class="body">
      <div class="t1">{{ p.stone_name|default:"Unidentified" }}</div>
      <div class="t2">{{ p.shape|default:"—" }} · {{ p.cut|default:"—" }}{% if p.size_display %} · {{ p.size_display }}{% endif %}</div>
      {% if 'pouch_value' in p %}<div class="money">{{ p.pouch_value|rupees }}</div>{% endif %}
      <div class="t3">{{ p.ct|ct }} ct · {% if p.countable %}{{ p.pcs|grouped }} pcs{% else %}uncountable{% endif %}</div>
      {% if not client_view %}<div class="flags">
        {% if p.misfiled %}<span class="chip warn"><span class="dot"></span>colour</span>{% endif %}
        {% if p.no_pouch_no %}<span class="chip crit"><span class="dot"></span>no pouch no.</span>{% endif %}
        {% if p.size_kind == 'free' or p.size_kind == 'none' %}<span class="chip"><span class="dot" style="background:var(--muted)"></span>{{ p.size_display|default:"no size" }}</span>{% endif %}
      </div>{% endif %}
    </div>
  </a>
{% endfor %}
</div>
{% endif %}
{% endblock %}
```

`inventory:pouch` does not exist yet. Add a temporary route so the batch page reverses — Task 8 replaces it:

```python
    path("pouches/<str:ref>/", views.shelf, name="pouch"),             # replaced in Task 8
```

Add `a.rowlink{color:inherit;text-decoration:none}` to the compat block in `static/css/inventory.css`.

- [ ] **Step 5: Run the tests**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_views.py -v`
Expected: PASS. In the table test, the second assertion is deliberately loose about markup; what matters is the `Check` header and an `ok` chip.

- [ ] **Step 6: Commit**

```bash
git add inventory static/css/inventory.css
git commit -m "A box colour's batches, and a batch's pouches as grid or table"
```

---

### Task 8: Pouch detail — Save, Add price, photos

**Files:**
- Create: `inventory/templates/inventory/pouch.html`, `inventory/tests/test_pouch.py`
- Modify: `inventory/views.py`, `inventory/urls.py`

**Interfaces:**
- Consumes: `services.save_details`, `services.add_price`, `services.latest_price`, `rows.shares`, `mediahub.services.attach_uploads`, `stock.masking.allowed`, `stock.masking.mask`.
- Produces: URL names `inventory:pouch` (`ref`), `inventory:pouch_save`, `inventory:pouch_price`, `inventory:pouch_photos`; and a `pouch_ref` context variable for the tab strip.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_pouch.py`:

```python
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory.models import PriceEntry
from inventory.tests.conftest import SUPPLIER, VALUE

pytestmark = pytest.mark.django_db


def _url(name, pouch):
    return reverse(name, args=[pouch.ref])


def test_the_detail_shows_value_shares_and_the_record(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(_url("inventory:pouch", shelf["onyx"])).content.decode()
    assert "SL01G · 1" in body and VALUE in body and SUPPLIER in body
    assert "of batch SL01G" in body and "98%" in body            # 98,988 of 1,00,988
    assert "Batch code" in body and "Stone" in body               # family decoded


def test_a_misfiled_pouch_says_so(client, admin_user_, shelf):
    client.force_login(admin_user_)
    body = client.get(_url("inventory:pouch", shelf["ruby"])).content.decode()
    assert "Colour mismatch — check filing" in body and "Filed under Green but recorded as Red" in body


def test_save_writes_the_four_fields(client, accounts_user, shelf):
    client.force_login(accounts_user)
    response = client.post(_url("inventory:pouch_save", shelf["onyx"]),
                           {"treatment": "Heated", "origin": "Zambia", "purchase_date": "2026-08-07",
                            "supplier": shelf["supplier"].pk})
    assert response.status_code == 302
    shelf["onyx"].refresh_from_db()
    assert (shelf["onyx"].treatment, shelf["onyx"].origin, str(shelf["onyx"].purchase_date)) == ("Heated", "Zambia", "2026-08-07")


def test_sales_may_not_save_or_price(client, sales_user, shelf):
    client.force_login(sales_user)
    assert client.post(_url("inventory:pouch_save", shelf["onyx"]), {"treatment": "Heated"}).status_code == 403
    assert client.post(_url("inventory:pouch_price", shelf["onyx"]),
                       {"kind": "list", "rate": "1", "effective_from": "2026-09-28"}).status_code == 403


def test_add_price_appends_a_dated_row(client, accounts_user, shelf):
    client.force_login(accounts_user)
    client.post(_url("inventory:pouch_price", shelf["onyx"]),
                {"kind": PriceEntry.LIST, "rate": "12000", "effective_from": "2026-09-28"})
    assert shelf["onyx"].prices.filter(kind=PriceEntry.LIST).get().rate == Decimal("12000")
    body = client.get(_url("inventory:pouch", shelf["onyx"])).content.decode()
    assert "12,000" in body


def test_photos_are_filed_under_the_pouch(client, accounts_user, shelf, monkeypatch):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from mediahub import storage
    from mediahub.models import MediaAsset

    monkeypatch.setattr(storage, "put_bytes", lambda key, data, mime: None)
    client.force_login(accounts_user)
    photo = SimpleUploadedFile("IMG_0001.jpg", b"\xff\xd8\xff", content_type="image/jpeg")
    client.post(_url("inventory:pouch_photos", shelf["onyx"]), {"photos": [photo]})
    asset = MediaAsset.objects.get(scope="pouch", scope_id=str(shelf["onyx"].pk))
    assert asset.file_name == "SL01G-1-01.jpg"
```

- [ ] **Step 2: Run to see them fail**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_pouch.py -v`
Expected: FAIL — the pouch route is still the placeholder.

- [ ] **Step 3: Write the views**

Add to `inventory/views.py`:

```python
import os
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.utils.dateparse import parse_date

from mediahub.services import attach_uploads
from stock.enums import MediaKind
from stock.masking import allowed, mask
from stock.models import Vendor
from stock.services import ServiceError

from .models import ORIGINS, TREATMENTS, Movement, Pouch, PriceEntry

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
```

The imports these views need, at the top of `inventory/views.py`: `from django.utils import timezone`, `from accounts.capabilities import INV_MASTERS`, `from mediahub.models import MediaAsset`, and `require` added to the `stock.services` import (`from stock.services import ServiceError, require`).

`PermissionDenied`, raised by `require` inside the services, is not caught. Django turns it into the 403 that the test expects.

In `inventory/urls.py`, replace the placeholder `pouch` route and add the three write routes:

```python
    path("pouches/<str:ref>/", views.pouch, name="pouch"),
    path("pouches/<str:ref>/save/", views.pouch_save, name="pouch_save"),
    path("pouches/<str:ref>/price/", views.pouch_price, name="pouch_price"),
    path("pouches/<str:ref>/photos/", views.pouch_photos, name="pouch_photos"),
    path("pouches/<str:ref>/movements/", views.pouch, name="movements"),   # replaced in Task 9
```

- [ ] **Step 4: Write the template**

`inventory/templates/inventory/pouch.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}{% if client_view %}{{ row.ref }}{% else %}{{ row.batch_code }} · {{ row.pouch_no|default:"?" }}{% endif %}{% endblock %}
{% block crumb %}Shelf &nbsp;›&nbsp; {{ box.label }} &nbsp;›&nbsp; {% if client_view %}{{ row.ref }}{% else %}<b class="mono">{{ row.batch_code }} · {{ row.pouch_no|default:"?" }}</b>{% endif %}{% endblock %}
{% block content %}
<div class="head">
  <div>
    <div class="k1">{% if client_view %}{{ row.ref }}{% else %}{{ row.batch_code }} · {{ row.pouch_no|default:"?" }}{% endif %}</div>
    <div class="k2">{{ row.stone_name|default:"Unidentified" }} · {{ row.shape|default:"—" }} · {{ row.cut|default:"—" }} · {{ row.colour|default:"—" }}{% if row.quality %} · {{ row.quality }}{% endif %}</div>
    <div class="meta">
      {% if client_view %}
        <span class="chip">Available — enquire for price</span>
      {% else %}
        {% if in_stock %}<span class="chip good"><span class="dot"></span>In stock</span>{% else %}<span class="chip"><span class="dot" style="background:var(--muted)"></span>Out of stock</span>{% endif %}
        <span class="chip">▤ Box {{ row.carton|default:"—" }}</span>
        <span class="chip">◈ Batch {{ row.batch_code }}</span>
        <span class="chip"><span class="dot" style="background:{{ row.box_swatch }}"></span>{{ row.box_label }} box</span>
        {% if row.misfiled %}<span class="chip warn"><span class="dot"></span>Colour mismatch — check filing</span>{% endif %}
        {% if 'pouch_value' in row and row.pouch_value is None %}<span class="chip crit"><span class="dot"></span>Cannot be valued</span>{% endif %}
        <span class="chip mono">{{ row.ref }}</span>
      {% endif %}
    </div>
  </div>
  <div class="head-act">
    {% if client_view %}
      <a class="btn pri" href="{% url 'crm:pipeline_new' 'enquiry' %}?item={{ row.ref|urlencode }}%20{{ row.stone_name|urlencode }}">✉ Enquire</a>
    {% else %}
      <button class="btn gho" disabled title="Coming soon">⤴ Split pouch 🔒</button>
      <a class="btn" href="{% url 'inventory:movements' row.ref %}">⇄ Movements</a>
      {% if caps.inv_masters %}<button class="btn pri" form="pouchform">Save</button>{% endif %}
    {% endif %}
  </div>
</div>

{% if 'pouch_value' in row %}
  {% if row.pouch_value is not None %}
  <div class="valpanel">
    <div class="vp-main"><div class="l">Pouch value</div>
      <div class="v">{{ row.pouch_value|rupees }}</div>
      <div class="f mono">{{ row.ct|ct }} ct × {{ row.stone_rate|rupees }}/ct</div></div>
    <div class="vp-side">
      <div class="vp-row"><span>of batch {{ row.batch_code }}</span><b>{{ shares.batch }}%</b></div>
      <div class="vp-row"><span>of the {{ row.box_label }} box</span><b>{{ shares.colour }}%</b></div>
      <div class="vp-row"><span>of all stock</span><b>{{ shares.all }}%</b></div>
    </div>
  </div>
  {% else %}
  <div class="banner crit"><div class="banner-ic">!</div><div>
    <h4>This pouch cannot be valued</h4><p>No {{ missing }} on file.</p></div></div>
  {% endif %}
{% endif %}

<div class="kpis">
  <div class="kpi"><div class="lab">Weight</div><div class="val tnum">{{ row.ct|ct }} <small>ct</small></div></div>
  {% if 'stone_rate' in row %}<div class="kpi"><div class="lab">Rate</div>
    <div class="val tnum">{{ row.stone_rate|rupees }} <small>/ ct</small></div><div class="foot">Price Per Carat / Pc</div></div>{% endif %}
  <div class="kpi"><div class="lab">Size</div>
    <div class="val">{% if row.size_kind == 'lw' or row.size_kind == 'dia' %}<span class="tnum">{{ size_mm }}</span> <small>mm</small>{% else %}<span style="font-size:15px;color:var(--muted)">{{ row.size_display|default:"Not recorded" }}</span>{% endif %}</div>
    <div class="foot">{{ size_foot }}</div></div>
  <div class="kpi"><div class="lab">Pieces</div>
    <div class="val">{% if row.countable %}<span class="tnum">{{ row.pcs|grouped }}</span> <small>pcs</small>{% else %}<span style="font-size:16px;color:var(--muted)">Uncountable</span>{% endif %}</div>
    <div class="foot">{% if row.countable and avg %}avg {{ avg|ct }} ct each{% endif %}</div></div>
</div>

<div class="cols">
  <div>
    <div class="card"><div class="card-h"><span class="card-t">Media</span>
        {% if not photos and not client_view %}<span class="chip warn" style="margin-left:auto"><span class="dot"></span>Placeholder</span>{% endif %}</div>
      <div class="card-b">
        <div class="ph" style="background:linear-gradient(160deg,#fbfaf7,{{ row.colour_hex }}2a)">
          {% if photos %}<img class="photo" src="{% url 'mediahub:media' photos.0.pk %}" alt="{{ row.stone_name }}">{% else %}{% silhouette row.shape row.colour_hex %}{% endif %}</div>
        {% if photos|length > 1 %}<div class="thumbs">{% for p in photos %}<a href="{% url 'mediahub:media' p.pk %}" target="_blank"><img src="{% url 'mediahub:media' p.pk %}" alt=""></a>{% endfor %}</div>{% endif %}
        {% if caps.inv_masters and not client_view %}
        <form method="post" enctype="multipart/form-data" action="{% url 'inventory:pouch_photos' row.ref %}">{% csrf_token %}
          <label class="drop upload"><b>Drop photos here</b>Filed as <span class="mono">{{ row.batch_code }}-{{ row.pouch_no|default:"X" }}-01.jpg</span>
            <input type="file" name="photos" accept="image/*" multiple onchange="this.form.requestSubmit()"></label>
        </form>{% endif %}
      </div></div>

    {% if not client_view %}
    <div class="card" style="margin-top:14px"><div class="card-h"><span class="card-t">Batch code</span></div>
      <div class="card-b">
        <div class="f"><div class="k">Family</div><div class="v">{{ family_label }}</div></div>
        <div class="f"><div class="k">Class</div><div class="v">{{ class_label }}</div></div>
        <div class="f"><div class="k">Batch no.</div><div class="v">{{ row.seq }}</div></div>
        <div class="f"><div class="k">Box colour</div><div class="v"><span class="chip"><span class="dot" style="background:{{ row.box_swatch }}"></span>{{ row.box_label }}</span></div></div>
        <div class="f{% if row.misfiled %} bad{% endif %}"><div class="k">Stone colour</div><div class="v">{{ row.colour|default:"—" }}</div></div>
        {% if row.misfiled %}<div class="hint" style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">
          <b style="color:var(--critink)">Mismatch.</b> Filed under {{ row.box_label }} but recorded as {{ row.colour }}.</div>{% endif %}
      </div></div>
    {% endif %}
  </div>

  <div class="card"><div class="card-h"><span class="card-t">The record</span></div>
    <div class="card-b">
      <form id="pouchform" method="post" action="{% url 'inventory:pouch_save' row.ref %}">{% csrf_token %}</form>
      {% if client_view %}
      <div class="grp"><div class="grp-t">Reference</div>
        <div class="f"><div class="k">Reference</div><div class="v mono">{{ row.ref }}</div></div></div>
      {% else %}
      <div class="grp"><div class="grp-t">Where it lives 🔒</div>
        <div class="f"><div class="k">Box (Box No)</div><div class="v">{{ row.carton|default:"—" }}</div></div>
        <div class="f"><div class="k">Batch (Gati code)</div><div class="v mono">{{ row.batch_code }}</div></div>
        <div class="f{% if row.no_pouch_no %} bad{% endif %}"><div class="k">Pouch no.</div><div class="v">{% if row.pouch_no %}{{ row.pouch_no }}{% else %}<span class="empty">Missing — no key</span>{% endif %}</div></div>
        <div class="f"><div class="k">Client reference</div><div class="v mono">{{ row.ref }}</div></div>
      </div>
      {% endif %}
      <div class="grp"><div class="grp-t">What it is</div>
        <div class="f"><div class="k">Category</div><div class="v">{{ row.category|default:"—" }}</div></div>
        <div class="f"><div class="k">Stone name</div><div class="v">{% if row.stone_name %}{{ row.stone_name }}{% else %}<span class="empty">Not captured</span>{% endif %}</div></div>
        <div class="f"><div class="k">Colour</div><div class="v">{% if row.colour %}{{ row.colour }}{% else %}<span class="empty">Not captured</span>{% endif %}</div></div>
        <div class="f"><div class="k">Shape</div><div class="v">{% if row.shape %}{{ row.shape }}{% else %}<span class="empty">Not captured</span>{% endif %}</div></div>
        <div class="f"><div class="k">Cut</div><div class="v">{% if row.cut %}{{ row.cut }}{% else %}<span class="empty">Not captured</span>{% endif %}</div></div>
        <div class="f"><div class="k">Quality</div><div class="v">{% if row.quality %}{{ row.quality }}{% else %}<span class="empty">Not captured</span>{% endif %}</div></div>
      </div>
      <div class="grp"><div class="grp-t">Size — millimetres</div>
        <div class="f"><div class="k">{% if row.size_kind == 'dia' %}Diameter{% else %}Length × width{% endif %}</div>
          <div class="v">{% if row.size_kind == 'lw' or row.size_kind == 'dia' or row.size_kind == 'multi' %}<b>{{ row.size_display }}</b>{% else %}<span class="empty">{{ row.size_display|default:"Not recorded" }}</span>{% endif %}</div></div>
      </div>
      <div class="grp"><div class="grp-t">Quantity &amp; price</div>
        <div class="f"><div class="k">Pcs</div><div class="v">{% if row.countable %}{{ row.pcs|grouped }}{% else %}<span class="empty">Uncountable</span>{% endif %}</div></div>
        <div class="f"><div class="k">Weight</div><div class="v">{{ row.ct|ct }} ct</div></div>
        {% if 'stone_rate' in row %}<div class="f"><div class="k">Rate</div><div class="v">{% if row.stone_rate is not None %}{{ row.stone_rate|rupees }} per carat{% else %}<span class="empty">Not captured</span>{% endif %}</div></div>{% endif %}
        {% if 'pouch_value' in row %}<div class="f"><div class="k">Pouch value</div><div class="v">{% if row.pouch_value is not None %}<b>{{ row.pouch_value|rupees }}</b> <span class="hint">= {{ row.ct|ct }} ct × {{ row.stone_rate|rupees }}</span>{% else %}<span class="empty">Cannot be calculated</span>{% endif %}</div></div>{% endif %}
        {% if 'list_rate' in prices %}<div class="f"><div class="k">List price</div><div class="v">{% if prices.list_rate is not None %}{{ prices.list_rate|rupees }} per carat{% else %}<span class="empty">Not set</span>{% endif %}</div></div>{% endif %}
      </div>
      <div class="grp"><div class="grp-t">Treatment &amp; origin</div>
        {% if caps.inv_masters and not client_view %}
        <div class="f"><div class="k">Treatment</div><div class="v"><select class="inp" name="treatment" form="pouchform" style="max-width:230px">
          <option value="">Not recorded</option>{% for value, label in treatments %}<option value="{{ value }}"{% if value == row.treatment %} selected{% endif %}>{{ label }}</option>{% endfor %}</select></div></div>
        <div class="f"><div class="k">Geographic origin</div><div class="v"><select class="inp" name="origin" form="pouchform" style="max-width:230px">
          <option value="">Not recorded</option>{% for value, label in origins %}<option value="{{ value }}"{% if value == row.origin %} selected{% endif %}>{{ label }}</option>{% endfor %}</select></div></div>
        <div class="f"><div class="k">Purchase date</div><div class="v"><input class="inp" type="date" name="purchase_date" form="pouchform" value="{{ row.purchase_date|date:'Y-m-d' }}" style="max-width:170px"></div></div>
        {% if 'supplier_name' in row %}<div class="f"><div class="k">Supplier</div><div class="v"><select class="inp" name="supplier" form="pouchform" style="max-width:230px">
          <option value="">Not recorded</option>{% for v in vendors %}<option value="{{ v.pk }}"{% if v.name == row.supplier_name %} selected{% endif %}>{{ v.name }}</option>{% endfor %}</select></div></div>{% endif %}
        {% else %}
        <div class="f"><div class="k">Treatment</div><div class="v">{{ row.treatment|default:"Not recorded" }}</div></div>
        <div class="f"><div class="k">Geographic origin</div><div class="v">{{ row.origin|default:"Not recorded" }}</div></div>
        {% if not client_view %}
        <div class="f"><div class="k">Purchase date</div><div class="v">{{ row.purchase_date|date:"d M Y"|default:"—" }}</div></div>
        {% if 'supplier_name' in row %}<div class="f"><div class="k">Supplier</div><div class="v">{{ row.supplier_name|default:"—" }}</div></div>{% endif %}
        {% endif %}
        {% endif %}
      </div>
      {% if not client_view %}
      <div class="grp"><div class="grp-t">Notes</div>
        <div class="f"><div class="k">Remarks</div><div class="v">{{ row.remarks|default:"—" }}</div></div></div>
      <div class="grp"><div class="grp-t">Source row</div>
        <div class="f"><div class="k">From</div><div class="v mono">{{ row.src|default:"—" }}</div></div></div>
      {% endif %}
    </div></div>

  <div>
    {% if not client_view and prices %}
    <div class="card"><div class="card-h"><span class="card-t">Price history</span><span class="lock" style="margin-left:auto">🔒 internal</span></div>
      <div class="card-b">
        {% if 'valuation_rate' in prices %}
        <div class="f" style="grid-template-columns:1fr auto"><div class="k">Rate on file</div><div class="v">{{ prices.valuation_rate|rupees }}<span class="hint"> per carat</span></div></div>
        <div class="f" style="grid-template-columns:1fr auto"><div class="k">Pouch value</div><div class="v"><b>{{ row.pouch_value|rupees }}</b></div></div>
        <div class="f" style="grid-template-columns:1fr auto"><div class="k">Purchase price</div><div class="v">{% if prices.purchase_rate is not None %}{{ prices.purchase_rate|rupees }}<span class="hint"> per carat</span>{% else %}<span class="empty">none recorded</span>{% endif %}</div></div>
        <div class="f" style="grid-template-columns:1fr auto"><div class="k">Current valuation</div><div class="v">{% if prices.valuation_date %}{{ prices.valuation_date|date:"d M Y" }}{% else %}<span class="empty">never valued</span>{% endif %}</div></div>
        {% endif %}
        {% if 'list_rate' in prices %}
        <div class="f" style="grid-template-columns:1fr auto"><div class="k">Selling / list price</div><div class="v">{% if prices.list_rate is not None %}{{ prices.list_rate|rupees }}<span class="hint"> per carat</span>{% else %}<span class="empty">not set</span>{% endif %}</div></div>
        {% endif %}
        {% if history %}
        <table class="led" style="margin-top:10px"><thead><tr><th>Date</th><th>Kind</th><th class="r">Rate / ct</th></tr></thead>
          <tbody>{% for e in history %}<tr><td>{{ e.effective_from|date:"d M Y" }}</td><td>{{ e.get_kind_display }}</td><td class="r">{{ e.rate|rupees }}</td></tr>{% endfor %}</tbody></table>
        {% endif %}
        {% if caps.inv_masters and price_kinds %}
        <form method="post" action="{% url 'inventory:pouch_price' row.ref %}" style="margin-top:10px">{% csrf_token %}
          <div class="two">
            <select class="inp" name="kind">{% for value, label in price_kinds %}<option value="{{ value }}">{{ label }}</option>{% endfor %}</select>
            <div class="unit"><input class="inp tnum" name="rate" inputmode="decimal" placeholder="0" required><span class="u">/ ct</span></div>
          </div>
          <input class="inp" type="date" name="effective_from" value="{% now 'Y-m-d' %}" style="margin-top:8px">
          <button class="btn" style="width:100%;margin-top:10px;justify-content:center">＋ Add price</button>
        </form>
        {% endif %}
      </div></div>
    {% endif %}

    {% if not client_view %}{% if not photos or movement_count < 2 or row.size_kind == 'free' or row.size_kind == 'none' %}
    <div class="notcap" style="margin-top:14px"><div class="t">Still not captured</div><ul>
      {% if not photos %}<li>Photos</li>{% endif %}
      {% if movement_count < 2 %}<li>In / out movement history</li>{% endif %}
      {% if row.size_kind == 'free' or row.size_kind == 'none' %}<li>Measured dimensions</li>{% endif %}
    </ul></div>
    {% endif %}{% endif %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Run the tests**

Run: `../nornament-app/.venv/bin/pytest inventory/tests -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add inventory
git commit -m "Pouch detail with a working Save, Add price and photo drop"
```

---

### Task 9: Movements, and the import screens

**Files:**
- Create: `inventory/templates/inventory/movements.html`, `inventory/templates/inventory/import_home.html`, `inventory/templates/inventory/import_review.html`, `inventory/tests/test_movements.py`, `inventory/tests/test_import_views.py`
- Modify: `inventory/views.py`, `inventory/urls.py`

**Interfaces:**
- Consumes: `plan.*`, `stones.*`, `stock.views._store_workbook`, `stock.views._batch_workbook`, `stock.models.ImportBatch`.
- Produces: URL names `inventory:movements` (`ref`), `inventory:import_home`, `inventory:import_review` (`batch_id`) and `inventory:import_commit` (`batch_id`).

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_movements.py`:

```python
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory.models import Movement

pytestmark = pytest.mark.django_db


def test_the_ledger_runs_a_balance(client, admin_user_, shelf):
    onyx = shelf["onyx"]
    Movement.objects.create(pouch=onyx, reason=Movement.Reason.SALE, direction=Movement.OUT, pcs=5, ct=Decimal("2.5"))
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:movements", args=[onyx.ref])).content.decode()
    assert "Opening Balance" in body and "Sale" in body
    assert "10.00 ct" in body and "15 pcs" in body            # balance after the sale
    assert "2 movements" in body


def test_filtering_by_reason_keeps_the_running_balance(client, admin_user_, shelf):
    onyx = shelf["onyx"]
    Movement.objects.create(pouch=onyx, reason=Movement.Reason.SALE, direction=Movement.OUT, pcs=5, ct=Decimal("2.5"))
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:movements", args=[onyx.ref]), {"reason": "Sale"}).content.decode()
    assert "10.00 ct" in body and "Opening Balance</span>" not in body


def test_client_view_never_opens_the_ledger(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    response = client.get(reverse("inventory:movements", args=[shelf["onyx"].ref]))
    assert response.status_code == 302
```

`inventory/tests/test_import_views.py`:

```python
import pytest
from django.urls import reverse

from inventory import seed
from inventory.models import BoxColour, CodePart, Pouch
from inventory.tests.fixtures_stones import build_workbook

pytestmark = pytest.mark.django_db


@pytest.fixture
def bucket(monkeypatch):
    from mediahub import storage

    book = build_workbook().getvalue()
    monkeypatch.setattr(storage, "put_bytes", lambda key, data, mime: None)
    monkeypatch.setattr(storage, "get_bytes", lambda key: book)
    return book


def test_upload_review_decide_commit(client, admin_user_, bucket):
    from django.core.files.uploadedfile import SimpleUploadedFile

    seed.load(BoxColour, CodePart)
    client.force_login(admin_user_)
    upload = SimpleUploadedFile("stones.xlsx", bucket,
                                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    review = client.post(reverse("inventory:import_home"), {"workbook": upload})
    assert review.status_code == 302
    url = review["Location"]
    body = client.get(url).content.decode()
    assert "SL!4" in body and "is also SL!2" in body

    batch_id = int(url.rstrip("/").split("/")[-1])
    blocked = client.post(reverse("inventory:import_commit", args=[batch_id]))
    assert blocked.status_code == 302 and not Pouch.objects.exists()

    form = {"pouch_no:SL!4": "9", "batch:SL!4": "", "pouch_no:SL!6": "", "batch:SL!6": "", "skip:SL!6": "1",
            "pouch_no:SL!5": "", "batch:SL!5": ""}
    client.post(url, form)
    client.post(reverse("inventory:import_commit", args=[batch_id]))
    assert Pouch.objects.count() == 5


def test_the_importer_is_closed_without_inv_masters(client, sales_user):
    client.force_login(sales_user)
    assert client.get(reverse("inventory:import_home")).status_code == 403
    assert client.post(reverse("inventory:import_commit", args=[1])).status_code == 403
```

- [ ] **Step 2: Run to see them fail**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_movements.py inventory/tests/test_import_views.py -v`
Expected: FAIL — the movements route is still the placeholder, and the import routes point at the shelf.

- [ ] **Step 3: Write the movements view**

Add to `inventory/views.py` (`timezone` is already imported from Task 8):

```python
from datetime import timedelta

#: the prototype's chip colours per reason
REASON_TONE = {"Memo In": "good", "Job Work In": "good", "Memo Out": "info", "Job Work Out": "warn",
               "Recount Adjustment": "info"}
PERIODS = [("", "All time"), ("12", "Last 12 months"), ("3", "Last 3 months")]


@login_required
def movements(request, ref):
    if _client(request):
        return redirect("inventory:pouch", ref=ref)
    obj = get_object_or_404(Pouch, ref=ref)
    everything = _everything(request)
    row = next(r for r in everything if r["pk"] == obj.pk)
    ledger, pcs, ct = [], 0, 0
    for move in obj.movements.select_related("counterparty", "recorded_by").order_by("occurred_at", "pk"):
        sign = 1 if move.direction == Movement.IN else -1
        pcs += sign * (move.pcs or 0)
        ct += sign * (move.ct or 0)
        ledger.append(mask(request.user, {
            "when": move.occurred_at, "reason": move.reason, "tone": REASON_TONE.get(move.reason, ""),
            "note": move.note, "dir": move.direction, "pcs": move.pcs, "ct": move.ct,
            "vendor_name": move.counterparty.name if move.counterparty_id else "",
            "ref": move.challan_no or move.ref, "bal_pcs": pcs, "bal_ct": ct,
            "by": (move.recorded_by.full_name or move.recorded_by.get_username()) if move.recorded_by_id else "system",
        }))
    total = len(ledger)
    reason, months = request.GET.get("reason", ""), request.GET.get("months", "")
    if reason:
        ledger = [m for m in ledger if m["reason"] == reason]
    if months.isdigit():
        since = timezone.now() - timedelta(days=31 * int(months))
        ledger = [m for m in ledger if m["when"] >= since]
    held = services.stocked(Pouch.objects.filter(pk=obj.pk)).get()
    return _page(request, "inventory/movements.html", everything, tab="tx", pouch_ref=obj.ref, row=row,
                 ledger=list(reversed(ledger)), ledger_total=total, reason=reason, months=months,
                 reasons=Movement.Reason.choices, periods=PERIODS,
                 in_stock=bool((held.on_ct or 0) > 0 or (held.on_pcs or 0) > 0))
```

- [ ] **Step 4: Write the import views**

Add to `inventory/views.py`:

`INV_MASTERS` is already imported from Task 8.

```python
from django.contrib.auth.decorators import permission_required

from stock.models import ImportBatch
from stock.views import _batch_workbook, _store_workbook

from .importers import plan, stones


@login_required
@permission_required(INV_MASTERS, raise_exception=True)
def import_home(request):
    if request.method == "POST":
        upload = request.FILES.get("workbook")
        if upload is None:
            messages.error(request, "Choose a workbook first.")
            return redirect("inventory:import_home")
        problems = stones.header_problems(upload)
        if problems:
            messages.error(request, f"That is not the stones register. {problems[0]}")
            return redirect("inventory:import_home")
        upload.seek(0)
        try:
            asset = _store_workbook(upload, request.user)
        except Exception as error:
            messages.error(request, f"Could not store the file. {error}")
            return redirect("inventory:import_home")
        batch = ImportBatch.objects.create(media=asset, source="STONES", created_by=request.user,
                                           status=ImportBatch.Status.REVIEWING)
        return redirect("inventory:import_review", batch_id=batch.pk)
    recent = ImportBatch.objects.filter(source="STONES").select_related("media")[:10]
    return _page(request, "inventory/import_home.html", _everything(request), tab="import", recent=recent)


@login_required
@permission_required(INV_MASTERS, raise_exception=True)
def import_review(request, batch_id):
    batch = get_object_or_404(ImportBatch, pk=batch_id, source="STONES")
    parsed = stones.parse(_batch_workbook(batch))
    items = plan.analyse(parsed, batch.decisions)
    if request.method == "POST" and batch.status == ImportBatch.Status.REVIEWING:
        batch.decisions = plan.read_decisions(request.POST, items, batch.decisions)
        batch.save(update_fields=["decisions"])
        return redirect("inventory:import_review", batch_id=batch.pk)
    return _page(request, "inventory/import_review.html", _everything(request), tab="import", batch=batch,
                 counts=plan.counts(items), attention=plan.attention(items),
                 recounts=[i for i in items if i.recount and not i.skip])


@login_required
@permission_required(INV_MASTERS, raise_exception=True)
@require_POST
def import_commit(request, batch_id):
    batch = get_object_or_404(ImportBatch, pk=batch_id, source="STONES")
    if batch.status == ImportBatch.Status.DONE:
        messages.error(request, "That import has already been committed.")
        return redirect("inventory:import_review", batch_id=batch.pk)
    items = plan.analyse(stones.parse(_batch_workbook(batch)), batch.decisions)
    try:
        result = plan.commit(items, request.user, import_batch=batch)
    except ServiceError as error:
        messages.error(request, error.messages[0])
        return redirect("inventory:import_review", batch_id=batch.pk)
    except Exception as error:  # the transaction has already rolled back
        batch.status, batch.result = ImportBatch.Status.FAILED, {"error": str(error)}
        batch.save(update_fields=["status", "result"])
        messages.error(request, f"Import failed, nothing was written. {error}")
        return redirect("inventory:import_review", batch_id=batch.pk)
    batch.status, batch.result, batch.finished_at = ImportBatch.Status.DONE, result, timezone.now()
    batch.save(update_fields=["status", "result", "finished_at"])
    messages.success(request, f"Imported: {result['created']} new, {result['updated']} updated, "
                              f"{result['recounted']} recounted, {result['skipped']} skipped.")
    return redirect("inventory:shelf")
```

In `inventory/urls.py`, replace the placeholder `movements` and `import_home` routes, and add the other two import routes:

```python
    path("pouches/<str:ref>/movements/", views.movements, name="movements"),
    path("import/", views.import_home, name="import_home"),
    path("import/<int:batch_id>/", views.import_review, name="import_review"),
    path("import/<int:batch_id>/commit/", views.import_commit, name="import_commit"),
```

- [ ] **Step 5: Write the templates**

`inventory/templates/inventory/movements.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Movements · {{ row.batch_code }} · {{ row.pouch_no|default:"?" }}{% endblock %}
{% block crumb %}Shelf &nbsp;›&nbsp; {{ row.box_label }} &nbsp;›&nbsp; <b class="mono">{{ row.batch_code }} · {{ row.pouch_no|default:"?" }}</b> &nbsp;›&nbsp; Movements{% endblock %}
{% block content %}
<div class="head">
  <div><div class="k1">{{ row.batch_code }} · {{ row.pouch_no|default:"?" }}</div>
    <div class="k2">Movements · {{ row.stone_name|default:"Unidentified" }} · batch {{ row.batch_code }}, box {{ row.carton|default:"—" }}</div>
    <div class="meta">
      {% if in_stock %}<span class="chip good"><span class="dot"></span>In stock</span>{% else %}<span class="chip"><span class="dot" style="background:var(--muted)"></span>Out of stock</span>{% endif %}
      <span class="chip">{{ ledger_total }} movement{{ ledger_total|pluralize }}</span></div></div>
  <div class="head-act">
    <a class="btn gho" href="{% url 'inventory:pouch' row.ref %}">← Pouch</a>
    <button class="btn gho" disabled title="Coming soon">⤴ Split 🔒</button>
    <button class="btn pri" disabled title="Coming soon">＋ Record movement 🔒</button></div>
</div>

<div class="tx-top">
  <div class="derived">
    <div style="display:flex;align-items:center;gap:9px"><span class="chip info"><span class="dot"></span>Derived</span>
      <span class="card-t">Current balance</span></div>
    <div class="drow">
      <div class="dq"><div class="lab">Pieces</div><div class="val tnum">{% if row.countable %}{{ row.pcs|grouped }} <small>pcs</small>{% else %}<span style="font-size:15px;color:var(--muted)">Uncountable</span>{% endif %}</div></div>
      <div class="dq"><div class="lab">Weight</div><div class="val tnum">{{ row.ct|ct }} <small>ct</small></div></div>
      {% if 'pouch_value' in row %}<div class="dq"><div class="lab">Value</div><div class="val tnum">{{ row.pouch_value|rupees }}</div></div>{% endif %}
    </div>
  </div>
  <div class="card"><div class="card-h"><span class="card-t">Where this pouch sits</span></div>
    <div class="card-b">
      <div style="display:flex;align-items:center;gap:9px;flex-wrap:wrap;font-size:13px">
        <span class="chip"><span class="dot" style="background:{{ row.box_swatch }}"></span>{{ row.box_label }}</span><span style="color:var(--muted)">›</span>
        <span class="chip mono">◈ {{ row.batch_code }}</span><span style="color:var(--muted)">›</span>
        <span class="chip mono">◆ pouch {{ row.pouch_no|default:"?" }}</span><span style="color:var(--muted)">·</span>
        <span class="chip">▤ box {{ row.carton|default:"—" }}</span></div>
      <button class="btn sm" style="margin-top:11px" disabled title="Coming soon">⇄ Transfer to another batch 🔒</button>
    </div></div>
</div>

<div class="tx-cols">
  <div class="card" style="overflow:hidden">
    <div class="card-h"><span class="card-t">Movement ledger</span><span class="spacer"></span>
      <form method="get" style="display:flex;gap:6px">
        <select class="chip" name="reason" onchange="this.form.submit()"><option value="">All reasons ▾</option>
          {% for value, label in reasons %}<option value="{{ value }}"{% if value == reason %} selected{% endif %}>{{ label }}</option>{% endfor %}</select>
        <select class="chip" name="months" onchange="this.form.submit()">
          {% for value, label in periods %}<option value="{{ value }}"{% if value == months %} selected{% endif %}>{{ label }} ▾</option>{% endfor %}</select>
      </form></div>
    <div style="overflow:auto"><table class="led">
      <thead><tr><th>Date</th><th>Reason</th><th>Dir</th><th class="r">Pcs</th><th class="r">Carats</th>
        <th>Counterparty / ref</th><th class="r">Balance after</th><th>By</th></tr></thead>
      <tbody>{% for m in ledger %}<tr>
        <td>{{ m.when|date:"d M Y" }}<div class="hint">{{ m.when|date:"H:i" }}</div></td>
        <td><span class="chip {{ m.tone }}">{% if m.tone %}<span class="dot"></span>{% endif %}{{ m.reason }}</span>{% if m.note %}<div class="hint">{{ m.note }}</div>{% endif %}</td>
        <td class="dir {{ m.dir }}">{% if m.dir == 'in' %}＋{% else %}−{% endif %}</td>
        <td class="r">{{ m.pcs|default_if_none:"—" }}</td><td class="r">{{ m.ct|ct }}</td>
        <td>{{ m.vendor_name }}{% if m.ref %}<div class="chal">{{ m.ref }}</div>{% endif %}</td>
        <td class="r">{{ m.bal_ct|ct }} ct<div class="hint tnum">{% if row.countable %}{{ m.bal_pcs }} pcs{% else %}no pcs{% endif %}</div></td>
        <td class="hint">{{ m.by }}</td></tr>
      {% empty %}<tr><td colspan="8" class="hint">No movements in this period.</td></tr>{% endfor %}</tbody></table></div>
  </div>

  <div><div class="card"><div class="card-h"><span class="card-t">Record movement</span><span class="lock" style="margin-left:auto">🔒</span></div>
    <div class="card-b"><fieldset disabled style="border:0">
      <div class="fld"><label>Reason</label><select class="inp">{% for value, label in reasons %}<option>{{ label }}</option>{% endfor %}</select></div>
      <div class="two">
        <div class="fld"><label>Pieces out</label><div class="unit"><input class="inp tnum"{% if not row.countable %} placeholder="uncountable"{% endif %}><span class="u">pcs</span></div></div>
        <div class="fld"><label>Weight out</label><div class="unit"><input class="inp tnum"><span class="u">ct</span></div></div></div>
      <div class="fld"><label>Karigar</label><select class="inp"><option>—</option></select></div>
      <div class="fld"><label>Delivery challan no. <span style="color:var(--critical)">*</span></label><input class="inp mono"></div>
      <div class="two"><div class="fld"><label>Date</label><input class="inp" type="date"></div>
        <div class="fld"><label>Expected back</label><input class="inp" type="date"></div></div>
      <button class="btn pri" style="width:100%;justify-content:center">Post movement</button>
    </fieldset></div></div></div>
</div>
{% endblock %}
```

`inventory/templates/inventory/import_home.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Import stones{% endblock %}
{% block crumb %}Import stones{% endblock %}
{% block content %}
<div class="shelfbar"><h1>Import stones</h1></div>
<div class="card" style="max-width:640px"><div class="card-h"><span class="card-t">Stones register</span></div>
  <div class="card-b">
    <form method="post" enctype="multipart/form-data">{% csrf_token %}
      <div class="fld"><label>Workbook (.xlsx) — sheets SP, PR, Mix, SR, SL</label>
        <input class="inp" type="file" name="workbook" accept=".xlsx" required></div>
      <button class="btn pri">Upload and review</button>
    </form>
  </div></div>
{% if recent %}
<div class="card" style="margin-top:14px;max-width:640px;overflow:hidden"><div class="card-h"><span class="card-t">Recent imports</span></div>
  <table class="pt"><thead><tr><th>#</th><th>File</th><th>Status</th><th>When</th></tr></thead>
    <tbody>{% for b in recent %}<tr onclick="location.href='{% url 'inventory:import_review' b.pk %}'">
      <td class="bn"><a class="rowlink" href="{% url 'inventory:import_review' b.pk %}">{{ b.pk }}</a></td>
      <td>{{ b.media.file_name }}</td><td>{{ b.get_status_display }}</td><td>{{ b.created_at|date:"d M Y H:i" }}</td></tr>{% endfor %}</tbody></table></div>
{% endif %}
{% endblock %}
```

`inventory/templates/inventory/import_review.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Import #{{ batch.pk }}{% endblock %}
{% block crumb %}Import stones &nbsp;›&nbsp; #{{ batch.pk }}{% endblock %}
{% block content %}
<div class="shelfbar"><h1>Review import #{{ batch.pk }}</h1><span class="spacer"></span>
  <a class="btn gho" href="{% url 'inventory:import_home' %}">← Imports</a></div>

<div class="totstrip">
  <div class="tot heroTot"><div class="l">Rows read</div><div class="v">{{ counts.rows|grouped }}</div>
    <div class="f">{{ counts.create|grouped }} new · {{ counts.update|grouped }} already here · {{ counts.skip|grouped }} skipped</div></div>
  <div class="tot"><div class="l">Blocked</div><div class="v">{{ counts.blocked|grouped }}</div><div class="f">need a decision before commit</div></div>
  <div class="tot"><div class="l">No pouch no.</div><div class="v">{{ counts.no_pouch_no|grouped }}</div><div class="f">imported without a key</div></div>
  <div class="tot"><div class="l">Recounts</div><div class="v">{{ counts.recount|grouped }}</div><div class="f">weight or pieces changed</div></div>
</div>

{% if batch.status == 'DONE' %}
<div class="banner"><div class="banner-ic">✓</div><div><h4>Imported {{ batch.finished_at|date:"d M Y H:i" }}</h4>
  <p>{{ batch.result.created }} new · {{ batch.result.updated }} updated · {{ batch.result.recounted }} recounted · {{ batch.result.skipped }} skipped</p></div></div>
{% else %}
<form method="post">{% csrf_token %}
<div class="card" style="overflow:hidden">
  <div class="card-h"><span class="card-t">Rows that need a decision</span><span class="spacer"></span>
    <button class="btn" name="fill_suggested" value="1">Fill suggested pouch numbers</button>
    <button class="btn">Save decisions</button></div>
  <div style="overflow:auto"><table class="pt">
    <thead><tr><th>Row</th><th>Batch</th><th>Pouch no.</th><th>Stone</th><th class="r">Carats</th><th>Problem</th><th>Skip</th></tr></thead>
    <tbody>{% for item in attention %}<tr class="{% if item.problem %}sel{% endif %}">
      <td class="mono">{{ item.row.src }}</td>
      <td><input class="inp mono" name="batch:{{ item.row.src }}" value="{{ item.batch }}" style="max-width:120px"></td>
      <td><input class="inp mono" name="pouch_no:{{ item.row.src }}" value="{{ item.pouch_no }}" placeholder="{{ item.suggestion }}" style="max-width:90px"></td>
      <td>{{ item.row.stone_name }}</td><td class="r">{{ item.row.ct|ct }}</td>
      <td>{% if item.skip %}<span class="chip"><span class="dot" style="background:var(--muted)"></span>skipped</span>
        {% elif item.problem %}<span class="chip crit"><span class="dot"></span>{{ item.problem }}</span>
        {% elif not item.pouch_no %}<span class="chip warn"><span class="dot"></span>no pouch no. — suggested {{ item.suggestion }}</span>{% endif %}</td>
      <td><input type="checkbox" name="skip:{{ item.row.src }}" value="1"{% if item.skip %} checked{% endif %}></td></tr>
    {% empty %}<tr><td colspan="7" class="hint">Nothing needs a decision.</td></tr>{% endfor %}</tbody></table></div>
</div>
</form>

{% if recounts %}
<div class="card" style="margin-top:14px;overflow:hidden"><div class="card-h"><span class="card-t">Recounts that will post</span></div>
  <table class="pt"><thead><tr><th>Pouch</th><th class="r">Carats held</th><th class="r">Carats in sheet</th><th class="r">Pieces held</th><th class="r">Pieces in sheet</th></tr></thead>
    <tbody>{% for item in recounts %}<tr><td class="bn">{{ item.batch }} · {{ item.pouch_no|default:"?" }}</td>
      <td class="r">{{ item.held_ct|ct }}</td><td class="r">{{ item.row.ct|ct }}</td>
      <td class="r">{{ item.held_pcs|default_if_none:"—" }}</td><td class="r">{{ item.row.pcs|default_if_none:"—" }}</td></tr>{% endfor %}</tbody></table></div>
{% endif %}

<form method="post" action="{% url 'inventory:import_commit' batch.pk %}" style="margin-top:14px">{% csrf_token %}
  <button class="btn pri"{% if counts.blocked %} disabled{% endif %}>Commit {{ counts.create|add:counts.update }} rows</button>
</form>
{% endif %}
{% endblock %}
```

- [ ] **Step 6: Run the tests**

Run: `../nornament-app/.venv/bin/pytest inventory/tests -v`
Expected: PASS. If the blocked-commit test gets a 403 instead of a 302, check that `permission_required` sits below `login_required`.

- [ ] **Step 7: Commit**

```bash
git add inventory
git commit -m "The movement ledger, and an import you review before it writes"
```

---

### Task 10: The client view, and the Enquire button

**Files:**
- Modify: `crm/views.py` (`pipeline_form` initial values)
- Create: `inventory/tests/test_client_view.py`

**Interfaces:**
- Consumes: the session flag from Task 6, `rows.CLIENT_HIDDEN`.
- Produces: `crm:pipeline_new` for an enquiry accepts `?item=` as the initial Item of Interest.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_client_view.py`:

```python
"""In client mode the server never sends the shelf layout, the money, or the flags.

The prototype hid these with CSS over the same data. Here they are never
rendered at all, and this walk is what keeps it that way.
"""
import pytest
from django.urls import reverse

from inventory.tests.conftest import SUPPLIER, VALUE

pytestmark = pytest.mark.django_db

LAYOUT = ["SL01G", "C-117", "keep away from light", "SL!2", VALUE, "7,919", SUPPLIER, "misfiled", "no pouch no."]


def _client_mode(client, user):
    client.force_login(user)
    client.post(reverse("inventory:set_view"), {"view": "client"})


def _screens(shelf):
    return [
        reverse("inventory:shelf"),
        reverse("inventory:colour", args=["G"]),
        reverse("inventory:batch", args=[shelf["batch"].pk]),
        reverse("inventory:batch", args=[shelf["batch"].pk]) + "?view=table",
        reverse("inventory:pouch", args=[shelf["onyx"].ref]),
        reverse("inventory:pouch", args=[shelf["ruby"].ref]),
    ]


def test_a_client_is_sent_no_layout_no_money_no_flags(client, admin_user_, shelf):
    _client_mode(client, admin_user_)
    for url in _screens(shelf):
        body = client.get(url).content.decode()
        for secret in LAYOUT:
            assert secret not in body, f"{url} sent {secret!r} in client view"


def test_a_client_sees_the_reference_and_can_enquire(client, admin_user_, shelf):
    _client_mode(client, admin_user_)
    body = client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()
    assert shelf["onyx"].ref in body and "enquire for price" in body and "✉ Enquire" in body


def test_the_enquiry_arrives_carrying_the_reference(client, admin_user_, shelf):
    client.force_login(admin_user_)
    body = client.get(reverse("crm:pipeline_new", args=["enquiry"]), {"item": f"{shelf['onyx'].ref} Green Onyx"}).content.decode()
    assert f'value="{shelf["onyx"].ref} Green Onyx"' in body


def test_internal_again_brings_everything_back(client, admin_user_, shelf):
    _client_mode(client, admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "internal"})
    assert "SL01G" in client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()
```

- [ ] **Step 2: Run to see them fail**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_client_view.py -v`
Expected: `test_the_enquiry_arrives_carrying_the_reference` FAILS, because the CRM ignores `?item=`. The others should already pass. If one of them fails, a template renders a hidden key outside a `client_view` guard; fix the template, not the test.

- [ ] **Step 3: Accept `?item=` on a new enquiry**

In `crm/views.py`, `pipeline_form`, directly after the two lines that read `request.GET.get("customer")`:

```python
            # the inventory's client view hands over the stone being asked about
            if kind == "enquiry" and request.GET.get("item"):
                initial["item_of_interest"] = request.GET["item"][:255]
```

- [ ] **Step 4: Run the tests**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_client_view.py crm -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add crm/views.py inventory/tests/test_client_view.py
git commit -m "Send a client nothing of the shelf, and let them enquire by reference"
```

---

### Task 11: The masking walk, and the way in from stock and CRM

**Files:**
- Create: `inventory/tests/test_masking.py`
- Modify: `stock/templates/stock/_nav.html`, `templates/crm_base.html`

**Interfaces:**
- Consumes: every `inventory:` URL name.

- [ ] **Step 1: Write the walk**

`inventory/tests/test_masking.py`:

```python
"""The SALES walk, for the inventory.

A showroom login sees stones and their sale side; it must never see a cost
rate, a valuation, a pouch value or a supplier. A new inventory screen that is
not listed here fails ``test_every_inventory_screen_is_walked``.
"""
import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from inventory.tests.conftest import SUPPLIER, VALUE

pytestmark = pytest.mark.django_db

SCREENS = [
    ("inventory:shelf", {}, ""),
    ("inventory:colour", {"code": "G"}, "?all=1"),
    ("inventory:batch", {"pk": "batch"}, ""),
    ("inventory:batch", {"pk": "batch"}, "?view=table"),
    ("inventory:pouch", {"ref": "onyx"}, ""),
    ("inventory:movements", {"ref": "onyx"}, ""),
]

#: POST-only, or gated whole on inv_masters and asserted to 403 below
EXEMPT = {
    "inventory:set_view", "inventory:pouch_save", "inventory:pouch_price", "inventory:pouch_photos",
    "inventory:import_home", "inventory:import_review", "inventory:import_commit",
}


def _url(name, kwargs, query, shelf):
    resolved = {}
    for key, value in kwargs.items():
        if key == "pk":
            resolved[key] = shelf[value].pk
        elif key == "ref":
            resolved[key] = shelf[value].ref
        else:
            resolved[key] = value
    return reverse(name, kwargs=resolved) + query


@pytest.mark.parametrize("fixture", ["sales_user", "karigar_user", "graphic_user"])
def test_no_cost_or_supplier_reaches_a_login_without_the_right(client, shelf, request, fixture):
    client.force_login(request.getfixturevalue(fixture))
    for name, kwargs, query in SCREENS:
        response = client.get(_url(name, kwargs, query, shelf))
        assert response.status_code == 200, f"{name} returned {response.status_code}"
        body = response.content.decode()
        for secret in (VALUE, "7,919", SUPPLIER):
            assert secret not in body, f"{name}{query} leaked {secret!r} to {fixture}"


def test_accounts_does_see_them(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(_url("inventory:pouch", {"ref": "onyx"}, "", shelf)).content.decode()
    assert VALUE in body and "7,919" in body and SUPPLIER in body


def test_the_writes_refuse_a_sales_login(client, sales_user, shelf):
    client.force_login(sales_user)
    ref = shelf["onyx"].ref
    for name in ("inventory:pouch_save", "inventory:pouch_price", "inventory:pouch_photos"):
        assert client.post(reverse(name, args=[ref]), {"kind": "list", "rate": "1"}).status_code == 403, name


def test_every_inventory_screen_is_walked():
    covered = {name for name, _, _ in SCREENS}
    named = set()
    for resolver in get_resolver().url_patterns:
        if isinstance(resolver, URLResolver) and resolver.app_name == "inventory":
            for pattern in resolver.url_patterns:
                if isinstance(pattern, URLPattern) and pattern.name:
                    named.add(f"inventory:{pattern.name}")
    missing = named - covered - EXEMPT
    assert not missing, f"inventory screens with no masking check: {sorted(missing)}"
```

- [ ] **Step 2: Run it**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_masking.py -v`
Expected: PASS. If it fails, the failure names the screen and the value it leaked. Fix the template: guard the value with a key test, never with a capability test.

- [ ] **Step 3: Link the inventory from the other two shells**

In `stock/templates/stock/_nav.html`, before the `<div class="navgrp">CRM</div>` block:

```django
<div class="navgrp">Inventory</div>
<a href="{% url 'inventory:shelf' %}"><span class="ico">◆</span>Stones</a>
```

In `templates/crm_base.html`, inside the `Stock` section, after the `Pieces` link:

```django
      <a class="ni" href="{% url 'inventory:shelf' %}"><span class="ni-i">◆</span><span>Stones</span></a>
```

- [ ] **Step 4: Run the whole suite**

Run: `../nornament-app/.venv/bin/pytest -q`
Expected: everything passes, including `stock/tests/test_masking.py`. That walk only covers the `stock` and `crm` namespaces, so the new nav links do not affect it.

- [ ] **Step 5: Commit**

```bash
git add inventory/tests/test_masking.py stock/templates/stock/_nav.html templates/crm_base.html
git commit -m "Walk every inventory screen as SALES, and link the inventory from stock and CRM"
```

---

### Task 12: Parity with the prototype, and the spec brought up to date

**Files:**
- Create: `inventory/tests/test_parity.py`
- Modify: `docs/superpowers/specs/2026-09-28-inventory-stones-design.md`

**Interfaces:**
- Consumes: the prototype's embedded data at `../Nornament_Inventory/01-prototype/nornament-ui-mockup.html`. The test is skipped when that file is absent, so no stock data is committed to the repo.

- [ ] **Step 1: Write the parity test**

`inventory/tests/test_parity.py`:

```python
"""The port reproduces the prototype's own totals.

The prototype's data (all 2,916 pouches, as the owner has already seen them) is
rebuilt into a register, imported through the real importer, and the shelf's
totals must match. It reads the prototype from beside the repo and skips if it
is not there, so no stock figures are ever committed.
"""
import io
import json
from decimal import Decimal

import pytest
from django.conf import settings
from openpyxl import Workbook

from inventory import rows as rows_mod
from inventory import rules, seed, services
from inventory.importers import plan, stones
from inventory.models import BoxColour, CodePart

pytestmark = [pytest.mark.django_db, pytest.mark.golden]

PROTOTYPE = settings.BASE_DIR.parent / "Nornament_Inventory" / "01-prototype" / "nornament-ui-mockup.html"

FIELD = {"gati": "New Gati Code", "batch": "Batch No.", "carton": "Box No", "cat": "Category", "name": "Stone Name",
         "shape": "Shape", "size": "Size Length * Width", "colour": "Colour", "cut": "Cut", "q": "Quality",
         "pcs": "Pcs", "wt": "Weight in Cts / Qty", "rate": "Price Per Carat / Pc", "rem": "Remarks"}


def _prototype_pouches():
    if not PROTOTYPE.exists():
        pytest.skip(f"{PROTOTYPE} is not beside the repo")
    for line in PROTOTYPE.read_text().splitlines():
        if line.startswith("const D = "):
            data = json.loads(line[len("const D = "):].rstrip().rstrip(";"))
            break
    return [p for c in data["colours"] for ps in c["p"].values() for p in ps] + data["unparsed"]


def _register(pouches):
    headers = list(stones.COLUMNS.values())
    book = Workbook()
    book.remove(book.active)
    sheets = {}
    for pouch in pouches:
        name, row = pouch["src"].split("!")
        if name not in sheets:
            sheets[name] = book.create_sheet(name)
            sheets[name].append(headers)
        for column, header in enumerate(headers, start=1):
            key = next(k for k, v in FIELD.items() if v == header)
            value = pouch.get(key)
            sheets[name].cell(row=int(row), column=column, value=None if value in ("", None) else value)
    buffer = io.BytesIO()
    book.save(buffer)
    buffer.seek(0)
    return buffer


def test_the_shelf_matches_the_prototype(admin_user_):
    seed.load(BoxColour, CodePart)
    items = plan.analyse(stones.parse(_register(_prototype_pouches())))
    decisions = {}
    for item in items:
        if item.problem and not rules.parse_batch_code(item.batch):
            decisions[item.row.src] = {"batch": "", "pouch_no": item.pouch_no, "skip": True}
        elif item.problem:
            decisions[item.row.src] = {"batch": "", "pouch_no": f"{item.pouch_no}-{item.row.src}", "skip": False}
    items = plan.analyse(stones.parse(_register(_prototype_pouches())), decisions)
    plan.commit(items, admin_user_)

    totals = rows_mod.summarise(rows_mod.pouch_rows(admin_user_, services.stocked()))
    assert totals["pouches"] == 2915                     # 2,916 less the one "Broken" code
    assert totals["batches"] == 697
    assert totals["colours"] == 19
    assert totals["misfiled"] == 127
    assert abs(totals["ct"] - Decimal("1056315.1")) < Decimal("0.5")
    assert abs(totals["value"] - Decimal("17249719")) <= 10
    assert totals["unpriced"] == 48
```

- [ ] **Step 2: Run it**

Run: `../nornament-app/.venv/bin/pytest inventory/tests/test_parity.py -v`
Expected: PASS. It takes a minute or two.

If `misfiled` or `value` disagrees, the port differs from `build_ui.py`. Compare `rules.colour_family` and `rules.is_misfiled` line by line against the prototype. Do not adjust the expected numbers; they are the owner's.

If `unpriced` reads 49, a zero weight is being treated as missing: check `_number` in `stones.py`.

- [ ] **Step 3: Bring the spec up to date**

In `docs/superpowers/specs/2026-09-28-inventory-stones-design.md`, add this section after "Testing":

```markdown
## Changed while planning

- **No `inv_stones` tab.** Every role opens the stone shelf, so a `ROLE_TABS` entry would gate nothing and would make the stock sidebar read "11 of 10 tabs". Views are `login_required`; writes are gated by capability in the service.
- **Misfiled follows the prototype exactly:** only a box whose label starts with `?` is exempt. BY is unconfirmed but labelled, so it is judged (that is how the prototype gets 127).
- **Size is parsed from `size_text` when read.** `size_kind`, `length_mm` and `width_mm` are not stored; nothing in part 1 queries them.
- **A zero rate is allowed;** only a negative one is refused. The prototype valued zero-rate pouches at ₹0 rather than as unvalued.
- **URLs carry a batch's pk and a pouch's `NRN-` ref**, so no link in client view carries a batch code.
- **The inventory's SALES walk is `inventory/tests/test_masking.py`,** with its own every-screen check.
- **Client view shows no list price** until the per-client price flag exists.
- **Only database-touching tests carry the `django_db` marker;** pure-function tests do not.
- **Parity** is `inventory/tests/test_parity.py` (marked `golden`). It reads the prototype from beside the repo and skips when it is absent.
```

In the Data model block, remove `size_kind (lw|dia|multi|free|none) · length_mm · width_mm` from `Pouch`. In the Errors section, change "rate ≤ 0" to "negative rate".

- [ ] **Step 4: Run the whole suite one last time**

Run: `../nornament-app/.venv/bin/pytest -q`
Expected: everything passes.

- [ ] **Step 5: Commit**

```bash
git add inventory/tests/test_parity.py docs/superpowers/specs/2026-09-28-inventory-stones-design.md
git commit -m "Prove the port reproduces the prototype's totals, and record what planning changed"
```
