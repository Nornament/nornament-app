# Inventory Part 3 (Diamonds) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make diamond stock real inside the inventory app — an importer for the diamond register, the prototype's Search stock screen with cascading bubble filters, and a Settings page (editable rights, suppliers, master lists, item codes, rate card, range → grade expansion).

**Architecture:** Diamonds live in the existing `inventory` app: `DiamondTerm` (every master list), `DiamondCode` (the item-code table), `DiamondLine` (one stock line, `NRD-` ref), `DiamondRate` (the inventory's own rate card). The existing `Movement` ledger gains an optional diamond link beside its pouch link, so carats on hand are the sum of movements exactly as for pouches. Pure rules (`dia_rules`, `dia_search`) are separate from the database; services write; rows mask through `stock.masking.mask`; views are thin.

**Tech Stack:** Django 5.2, Postgres 17, pytest + pytest-django, openpyxl 3.1 (installed), no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-30-inventory-diamonds-design.md`

**Prototype source (read, never edit):** `../Nornament_Inventory/04-source-scripts/_script.html` lines 615–850 (search) and 1080–1188 (settings, sub-tabs), `build_dia.py` (un-pivot, decoder, bands), `_head.html` (CSS already lifted verbatim into `static/css/inventory.css`: `.dsub`, `.rolebar`, `.rights`, `.rt`, `.searchcard`, `.srow`, `.slab`, `.shint`, `.bubrow`, `.bub`, `.bub.big`, `.catnote`, `.ctrow`, `.dbanner`, `.totstrip`, `.tot`, `.heroTot`, `.pt`, `.chip`).

## Global Constraints

- **Standalone rule:** add no new dependency on stock or CRM data. Diamond prices come from `DiamondRate`, never from `stock.RateChart`. Reusing part 1's patterns is allowed and expected: suppliers are `stock.Vendor`, imports use `stock.ImportBatch` and `stock.views._store_workbook/_batch_workbook`, masking is `stock.masking.mask/allowed`, writes use `stock.services.ServiceError/require/log`.
- Follow the surrounding style: docstrings say *why*; no type annotations except dataclass fields.
- Views never write models; writes live in `inventory/dia_services.py` or the importer's `commit()`.
- Money is masked only through `stock.masking` with the existing gated names `cost_rate`, `cost_amount`, `sale_rate`, `sale_amount`, `margin`, `vendor_name`; templates test key presence, never capabilities, for money.
- Prose stripped: no explainer banners, footers or "you define all of this" copy; functional warnings and the prototype's labels stay.
- Things the prototype shows but part 4 builds (Job cards, Assortments, Purchases, the ⚒ ⇅ ＋ buttons, the Movements / Purchase / Stock take tabs) render padlocked (`🔒`, disabled), never as dead links.
- Diamonds are internal only: the Internal / Client preview toggle is hidden on diamond pages.
- Terminology on screen follows the prototype: Category, Shape, Colour, Clarity, Size, Carats, Batch, Item code, Read.
- Only database tests carry `pytestmark = pytest.mark.django_db`; pure-function tests do not. Tests use the real role fixtures in the root `conftest.py`.
- Run tests from the repo root with `.venv/bin/pytest <path> -v` (from a sibling worktree: `POSTGRES_DB=<private name> ../nornament-app/.venv/bin/pytest <path> -v`). Known pre-existing environmental failure to ignore: `stock/tests/test_import_commit.py::test_images_are_attached_in_chunks_and_are_resumable` (live S3 401).
- Commit messages end with a blank line and `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Decided while planning (recorded in the spec by Task 11)

1. **Category belongs to the line, not the code.** The prototype takes each line's category from column A of its own row; `DiamondLine.category` holds it and `DiamondCode` holds shape, colour and clarity.
2. **A line can carry a shape override.** When a code names no shape and the size is a carat band with a shape prefix (`TR 0.20-0.24`), the prototype took the shape from the size; `DiamondLine.shape_override` holds that.
3. **The carat-band size prefixes use the IVY reading too:** `PR` = Pear, `PC` = Princess (the prototype had both its code table and this one swapped).
4. **A single leftover ladder letter is a colour grade.** `DTBG` → Tapered Baguette, colour G; `SOMG` → Marquise, colour G — as the prototype read them — but unconfirmed.
5. **Setting a rate needs both `view_cost` and `view_sale`**, because a rate row carries both.
6. **The band list is seeded with `?`** for sizes that fit no band.

## File Structure

| File | Responsibility |
|---|---|
| `inventory/dia_seed.py` | seed data: categories, ladders, ranges with expansions, fancy colours, bands |
| `inventory/models.py` (modify) | `DiamondTerm`, `DiamondCode`, `DiamondLine`, `DiamondRate`; `Movement` gains `diamond` |
| `inventory/migrations/0003_diamonds.py` (generated) · `0004_seed_diamond_terms.py` | schema; seed |
| `stock/models.py` (modify) · `stock/migrations/0010_vendor_terms.py` | `Vendor.terms` |
| `inventory/dia_rules.py` | pure: item-code decoder, size → band |
| `inventory/dia_search.py` | pure: filters, colour/clarity buckets, matching, bubbles |
| `inventory/importers/diamonds.py` | read the diamond register (un-pivot) |
| `inventory/importers/dia_plan.py` | analyse → decisions → commit for diamonds |
| `inventory/dia_services.py` | diamond reads (carats, rates) and every diamond write |
| `inventory/dia_rows.py` | masked line rows, rail counts, master-list usage |
| `accounts/models.py` (modify) | add-only `sync_role_groups` |
| `inventory/views_diamonds.py` | Search stock, the viewer / preview, `_dia_page` |
| `inventory/views_dia_settings.py` | Settings page and its POST endpoints |
| `inventory/views_dia_import.py` | diamond import screens |
| `inventory/urls.py` (modify) | routes |
| `templates/inventory_base.html` (modify) | stones/diamonds switch, rail and tabs by side |
| `inventory/templates/inventory/diamonds/*.html` | `_rail.html`, `_dsub.html`, `search.html`, `settings.html`, `import_home.html`, `import_review.html` |
| `inventory/tests/…` | tests per task; `fixtures_diamonds.py`; `diamonds` fixture in `conftest.py` |

## Parallel waves

| Wave | Tasks |
|---|---|
| 1 | 1 models · 2 dia_rules · 3 reader · 4 add-only sync · 5 dia_search |
| 2 | 6 services + rows (needs 1, 2) |
| 3 | 7 import plan (needs 3, 6) · 8 shell + Search (needs 5, 6) |
| 4 | 9 Settings (needs 8) · 10 import screens (needs 7, 8) |
| 5 | 11 masking walk, preview, parity, spec (needs all) |

Tasks 2, 3 and 5 are pure modules with no database; in a parallel worktree they must not create `inventory/__init__.py`-level files owned by others.

---

### Task 1: Diamond models, the shared ledger, and seed terms

**Files:**
- Create: `inventory/dia_seed.py`, `inventory/migrations/0003_diamonds.py` (generated), `inventory/migrations/0004_seed_diamond_terms.py`, `stock/migrations/0010_vendor_terms.py` (generated), `inventory/tests/test_dia_models.py`
- Modify: `inventory/models.py`, `stock/models.py` (`Vendor`)

**Interfaces:**
- Produces: models `DiamondTerm` (constants `CATEGORY, SHAPE, COLOUR, CLARITY, BAND`; method `grades() -> list[str]`), `DiamondCode`, `DiamondLine`, `DiamondRate`; `Movement.diamond`; `dia_seed.load(DiamondTerm)`; `dia_seed.COLOUR_LADDER`, `CLARITY_LADDER`, `COLOUR_RANGES`, `CLARITY_RANGES`, `FANCY`, `CATEGORIES`, `BANDS`; `Vendor.terms`.

- [ ] **Step 1: Write the failing test**

`inventory/tests/test_dia_models.py`:

```python
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from inventory import dia_seed, services
from inventory.models import DiamondCode, DiamondLine, DiamondTerm, Movement

pytestmark = pytest.mark.django_db


@pytest.fixture
def terms():
    dia_seed.load(DiamondTerm)
    return {(t.kind, t.value): t for t in DiamondTerm.objects.all()}


def test_the_ladders_and_ranges_are_seeded_in_order(terms):
    colours = list(DiamondTerm.objects.filter(kind=DiamondTerm.COLOUR).values_list("value", flat=True))
    assert colours[:4] == ["D", "E", "F", "G"]
    assert terms[("colour", "F-G-H")].grades() == ["F", "G", "H"]
    assert terms[("clarity", "SI-I")].grades() == ["SI1", "SI2", "SI3", "I1"]
    assert terms[("colour", "G")].grades() == ["G"]
    assert terms[("colour", "Fancy Yellow")].grades() == []
    assert list(DiamondTerm.objects.filter(kind=DiamondTerm.BAND).values_list("value", flat=True)) == dia_seed.BANDS


def test_seeding_twice_changes_nothing(terms):
    before = DiamondTerm.objects.count()
    dia_seed.load(DiamondTerm)
    assert DiamondTerm.objects.count() == before


def test_a_movement_belongs_to_a_pouch_or_a_diamond_never_both(terms, shelf):
    code = DiamondCode.objects.create(item_code="DRFGH VS-SI")
    line = DiamondLine.objects.create(ref="NRD-000001", category=terms[("category", "Natural Diamond")],
                                      code=code, band=terms[("band", "+6-11")], size_text="+6-12")
    Movement.objects.create(diamond=line, reason=Movement.Reason.OPENING_BALANCE, direction=Movement.IN,
                            ct=Decimal("3.4"))
    with pytest.raises(IntegrityError), transaction.atomic():
        Movement.objects.create(reason=Movement.Reason.SALE, direction=Movement.OUT, ct=Decimal("1"))
    with pytest.raises(IntegrityError), transaction.atomic():
        Movement.objects.create(pouch=shelf["onyx"], diamond=line, reason=Movement.Reason.SALE,
                                direction=Movement.OUT, ct=Decimal("1"))


def test_pouch_stock_is_unchanged_by_the_new_link(shelf):
    held = services.stocked().get(pk=shelf["onyx"].pk)
    assert held.on_ct == Decimal("12.5")
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/pytest inventory/tests/test_dia_models.py -v`
Expected: FAIL — `cannot import name 'dia_seed'`.

- [ ] **Step 3: Write `inventory/dia_seed.py`**

```python
"""The diamond master lists as the prototype read them (``build_dia.py``), as data.

Ranges carry the single grades they stand for, so a filter on "G" finds a line
recorded as F-G-H. These are the prototype's readings, not the owner's rulings:
Settings is where they are corrected, and loading again never overwrites a
correction.
"""
CATEGORIES = ["Natural Diamond", "HPHT Lab Grown", "Lab Grown (CVD?)", "Solitaire", "Foil Polki"]

COLOUR_LADDER = ["D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P",
                 "Q-R", "S-T", "U-V", "W-X", "Y-Z"]
CLARITY_LADDER = ["FL", "IF", "VVS1", "VVS2", "VS1", "VS2", "SI1", "SI2", "SI3", "I1", "I2", "I3"]

COLOUR_RANGES = {"D-E-F": "D E F", "E-F": "E F", "F-G-H": "F G H", "G-H": "G H",
                 "I-J": "I J", "K-L": "K L", "M-N": "M N"}
CLARITY_RANGES = {"VVS-VS": "VVS1 VVS2 VS1 VS2", "VS-SI": "VS1 VS2 SI1 SI2",
                  "SI-I": "SI1 SI2 SI3 I1", "I1-I2": "I1 I2"}

FANCY = ["Fancy Yellow", "Fancy Pink", "Fancy Orange", "Fancy Green",
         "Fancy Blue", "Fancy Brown", "Fancy Black", "Fancy Grey"]

#: non-overlapping, in the order the Size row shows them; "?" is a size that fits none
BANDS = ["-2", "+2-6", "+6-11", "11-20", "20+", "carat band", "?"]


def load(DiamondTerm):
    """Idempotent: a value already there keeps whatever it has been corrected to."""
    def put(kind, value, sort, expands_to=""):
        DiamondTerm.objects.get_or_create(kind=kind, value=value,
                                          defaults={"sort": sort, "expands_to": expands_to})

    for n, value in enumerate(CATEGORIES):
        put("category", value, n)
    for n, value in enumerate(COLOUR_LADDER):
        put("colour", value, n)
    for n, (value, grades) in enumerate(COLOUR_RANGES.items()):
        put("colour", value, 100 + n, grades)
    for n, value in enumerate(FANCY):
        put("colour", value, 200 + n)
    for n, value in enumerate(CLARITY_LADDER):
        put("clarity", value, n)
    for n, (value, grades) in enumerate(CLARITY_RANGES.items()):
        put("clarity", value, 100 + n, grades)
    for n, value in enumerate(BANDS):
        put("band", value, n)
```

- [ ] **Step 4: Add the models**

In `inventory/models.py`, change `Movement.pouch` to optional, add `diamond`, and add the constraint:

```python
    pouch = models.ForeignKey(Pouch, on_delete=models.PROTECT, related_name="movements", null=True, blank=True)
    diamond = models.ForeignKey(
        "DiamondLine", on_delete=models.PROTECT, related_name="movements", null=True, blank=True
    )
```

```python
    class Meta:
        db_table = "inv_movement"
        ordering = ["-occurred_at", "-pk"]
        constraints = [
            # one ledger for both kinds of stock: a movement moves exactly one thing
            models.CheckConstraint(
                condition=Q(pouch__isnull=False, diamond__isnull=True) | Q(pouch__isnull=True, diamond__isnull=False),
                name="inv_movement_one_owner",
            )
        ]

    def __str__(self):
        return f"{self.reason} {self.direction} {self.pouch_id or self.diamond_id}"
```

Append to `inventory/models.py`:

```python
class DiamondTerm(models.Model):
    """One value in one of the diamond master lists.

    Every list the Settings page edits is rows here, so renaming a value renames
    it on every code and line that uses it.
    """

    CATEGORY, SHAPE, COLOUR, CLARITY, BAND = "category", "shape", "colour", "clarity", "band"
    KINDS = [(CATEGORY, "Category"), (SHAPE, "Shape"), (COLOUR, "Colour grade"),
             (CLARITY, "Clarity grade"), (BAND, "Size band")]

    kind = models.CharField(max_length=10, choices=KINDS)
    value = models.CharField(max_length=60)
    sort = models.IntegerField(default=1000)
    expands_to = models.CharField(
        max_length=120, blank=True, help_text="Space-separated single grades this range stands for."
    )

    class Meta:
        db_table = "inv_dia_term"
        ordering = ["kind", "sort", "value"]
        constraints = [models.UniqueConstraint(fields=["kind", "value"], name="inv_dia_term_key")]

    def __str__(self):
        return self.value

    def grades(self):
        """The single grades a filter chip matches this value by.

        A range answers for each grade it spans; a plain grade for itself; a
        fancy colour or an unresolved token for none, so it never poses as a grade.
        """
        if self.expands_to:
            return self.expands_to.split()
        if self.value.startswith(("?", "(", "Fancy")):
            return []
        return [self.value]


class DiamondCode(models.Model):
    """One item code (``DRFGH VS-SI``) and what it means. Fixed once, every line follows."""

    item_code = models.CharField(max_length=40, primary_key=True)
    shape = models.ForeignKey(DiamondTerm, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    colour = models.ForeignKey(DiamondTerm, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    clarity = models.ForeignKey(DiamondTerm, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    confirmed = models.BooleanField(default=False)
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        db_table = "inv_dia_code"
        ordering = ["item_code"]

    def __str__(self):
        return self.item_code


class DiamondLine(models.Model):
    """One diamond stock line. Carats on hand are the sum of its movements."""

    ref = models.CharField(max_length=12, unique=True, editable=False)
    category = models.ForeignKey(DiamondTerm, on_delete=models.PROTECT, related_name="+")
    code = models.ForeignKey(DiamondCode, on_delete=models.PROTECT, related_name="lines")
    shape_override = models.ForeignKey(
        DiamondTerm, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text="From a carat-band size prefix, when the code names no shape.",
    )
    batch_no = models.CharField(max_length=40, blank=True)
    size_text = models.CharField(max_length=40, blank=True)
    band = models.ForeignKey(DiamondTerm, on_delete=models.PROTECT, related_name="+")
    ct_lo = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    ct_hi = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    src = models.CharField(max_length=24, blank=True, help_text="Sheet and row it came from.")
    import_batch = models.ForeignKey(
        "stock.ImportBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_dia_line"
        ordering = ["pk"]

    def __str__(self):
        return f"{self.ref} {self.code_id}"

    @property
    def shape(self):
        return self.shape_override or self.code.shape


class DiamondRate(models.Model):
    """The inventory's own rate card: per item code, per size ("" = any size). Latest wins."""

    code = models.ForeignKey(DiamondCode, on_delete=models.PROTECT, related_name="rates")
    size_text = models.CharField(max_length=40, blank=True)
    cost_rate = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    sale_rate = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    effective_from = models.DateField(default=timezone.localdate)
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_dia_rate"
        ordering = ["code", "size_text", "-effective_from", "-pk"]

    def __str__(self):
        return f"{self.code_id} {self.size_text or 'any size'}"
```

In `stock/models.py`, `Vendor`, after `city`:

```python
    terms = models.CharField(max_length=60, blank=True, help_text="Payment terms, e.g. 30 days, Advance.")
```

- [ ] **Step 5: Migrations**

Run:

```bash
.venv/bin/python manage.py makemigrations stock -n vendor_terms
.venv/bin/python manage.py makemigrations inventory -n diamonds
```

Create `inventory/migrations/0004_seed_diamond_terms.py`:

```python
from django.db import migrations


def load(apps, schema_editor):
    from inventory import dia_seed

    dia_seed.load(apps.get_model("inventory", "DiamondTerm"))


class Migration(migrations.Migration):
    dependencies = [("inventory", "0003_diamonds")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/pytest inventory -q` — Expected: PASS (the new file and every part 1 test).
Run: `.venv/bin/python manage.py makemigrations --check --dry-run` — Expected: `No changes detected`.

- [ ] **Step 7: Commit**

```bash
git add inventory stock/models.py stock/migrations/0010_vendor_terms.py
git commit -m "Model diamond lines, codes, terms and rates on the shared movement ledger"
```

---

### Task 2: Decode item codes and sizes

**Files:**
- Create: `inventory/dia_rules.py`, `inventory/tests/test_dia_rules.py`

**Interfaces:**
- Produces: `dia_rules.decode(item_code) -> Decoded` (dataclass: `shape`, `colour`, `clarity`, `note`, property `confirmed`); `dia_rules.size_band(size_text) -> Sized` (dataclass: `band`, `ct_lo`, `ct_hi`, `shape`).

- [ ] **Step 1: Write the failing test**

`inventory/tests/test_dia_rules.py`:

```python
from decimal import Decimal

import pytest

from inventory.dia_rules import decode, size_band


@pytest.mark.parametrize("code, shape, colour, clarity", [
    ("DRFGH VS-SI", "Round", "F-G-H", "VS-SI"),
    ("DRKL SI-I", "Round", "K-L", "SI-I"),              # R is Round, not "Rejection K-L"
    ("DTBFGH VS-SI", "Tapered Baguette", "F-G-H", "VS-SI"),
    ("DMMN VVS-VS", "Marquise", "M-N", "VVS-VS"),
    ("DPCEF VVS-VS", "Princess", "E-F", "VVS-VS"),       # the IVY export: PC is Princess
    ("DPRGH", "Pear", "G-H", ""),                        # and PR is Pear
    ("DRSCIJ", "Rose Cut", "I-J", ""),
    ("DPIOVL", "Pie Cut Oval", "", ""),
    ("DPIPCEF VVS-VS", "Pie Cut Princess", "E-F", "VVS-VS"),
    ("DFY", "Fancy Colour", "Fancy Yellow", ""),
    ("DFBR", "Fancy Colour", "Fancy Brown", ""),
    ("HPHTRGH VS-SI", "Round", "G-H", "VS-SI"),
])
def test_codes_that_read_cleanly(code, shape, colour, clarity):
    out = decode(code)
    assert (out.shape, out.colour, out.clarity) == (shape, colour, clarity)
    assert out.confirmed, out.note


@pytest.mark.parametrize("code, shape, colour", [
    ("DRLC VS-SI", "Round", "? LC"),
    ("DASCLB", "Asscher", "? LB"),
    ("DTBBL", "Tapered Baguette", "? BL"),
    ("DPIRD8", "? PI RD8", ""),
])
def test_unresolved_tokens_stay_visible_and_unconfirmed(code, shape, colour):
    out = decode(code)
    assert (out.shape, out.colour) == (shape, colour)
    assert not out.confirmed


def test_a_single_grade_letter_is_read_but_not_confirmed():
    out = decode("SOMG VS1")
    assert (out.shape, out.colour, out.clarity) == ("Marquise", "G", "VS1")
    assert not out.confirmed


def test_foil_polki_and_the_bare_code():
    polki = decode("FPL")
    assert polki.shape == "Polki" and not polki.confirmed and "FPL" in polki.note
    bare = decode("D")
    assert bare.shape == "" and not bare.confirmed


@pytest.mark.parametrize("size, band", [
    ("0000-000", "-2"), ("0-1", "-2"), ("+1", "-2"), ("-2BG", "-2"),
    ("+2", "+2-6"), ("+5", "+2-6"), ("+6", "+6-11"), ("+6-12", "+6-11"),
    ("+11", "11-20"), ("+80-100", "20+"), ("", "?"), ("mixed", "?"),
])
def test_sizes_fall_into_the_prototype_bands(size, band):
    assert size_band(size).band == band


def test_a_carat_band_carries_its_range_and_shape():
    sized = size_band("TR 0.20-0.24")
    assert (sized.band, sized.ct_lo, sized.ct_hi, sized.shape) == ("carat band", Decimal("0.20"), Decimal("0.24"), "Trillion")
    assert size_band("PR 0.10-0.12").shape == "Pear"
    assert size_band("PC 0.16-0.19").shape == "Princess"
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/pytest inventory/tests/test_dia_rules.py -v` — Expected: FAIL (`No module named 'inventory.dia_rules'`).

- [ ] **Step 3: Write `inventory/dia_rules.py`**

```python
"""Reading a diamond item code and a size, as pure functions.

The grammar is the prototype's (``build_dia.py``) with the IVY export's own
Shape/ShapeName columns as the correction: PC is Princess and PR is Pear (the
prototype had them swapped), PI is "pie cut" in front of a shape, RSC is Rose
Cut. Anything that does not read becomes a ``?`` value and leaves the code
unconfirmed, so it is visible in Settings rather than guessed.
"""
import re
from dataclasses import dataclass
from decimal import Decimal

from .dia_seed import COLOUR_LADDER

#: clarity suffix after a space; spaces inside become hyphens
CLARITIES = ["VVS-VS", "VVS VS", "VS-SI", "VS SI", "SI-I", "SI I", "I1-I2", "VVS1", "VVS2", "VS1", "VS2"]
#: origin prefix; the line's category comes from its sheet column, so this is only stripped
ORIGINS = ["HPHT", "LG", "SO", "FP", "D"]
#: longest first — RSC before R, OVL before OV
SHAPES = [("RSC", "Rose Cut"), ("EMR", "Emerald"), ("ASC", "Asscher"), ("HRT", "Heart"), ("RD8", "? RD8"),
          ("OVL", "Oval"), ("OV", "Oval"), ("PC", "Princess"), ("PR", "Pear"), ("TB", "Tapered Baguette"),
          ("TR", "Trillion"), ("M", "Marquise"), ("R", "Round"), ("F", "Fancy Colour")]
FANCY = {"Y": "Fancy Yellow", "P": "Fancy Pink", "O": "Fancy Orange", "G": "Fancy Green", "B": "Fancy Blue",
         "BR": "Fancy Brown", "BL": "Fancy Black", "GL": "Fancy Grey"}
COLOURS = [("FGH", "F-G-H"), ("EF", "E-F"), ("GH", "G-H"), ("IJ", "I-J"), ("KL", "K-L"), ("MN", "M-N"),
           ("LC", "? LC"), ("LB", "? LB")]


@dataclass
class Decoded:
    shape: str = ""
    colour: str = ""
    clarity: str = ""
    note: str = ""

    @property
    def confirmed(self):
        values = (self.shape, self.colour, self.clarity)
        return not self.note and bool(self.shape) and not any(v.startswith("?") for v in values)


def decode(item_code):
    out = Decoded()
    t = (item_code or "").strip()
    for clarity in CLARITIES:
        if t.endswith(" " + clarity):
            out.clarity = clarity.replace(" ", "-")
            t = t[: -(len(clarity) + 1)].strip()
            break
    origin = next((o for o in ORIGINS if t.startswith(o)), "")
    if origin:
        t = t[len(origin):]
    else:
        out.note = "origin prefix not recognised"
    pie = t.startswith("PI")
    if pie:
        t = t[2:]
    for token, name in SHAPES:
        if t.startswith(token):
            out.shape, t = name, t[len(token):]
            break
    if pie:
        out.shape = f"? PI {out.shape[2:]}" if out.shape.startswith("?") else (f"Pie Cut {out.shape}" if out.shape else "? PI")
    if out.shape == "Fancy Colour" and t:
        out.colour, t = FANCY.get(t, f"? {t}"), ""
        if out.colour.startswith("?"):
            out.note = "fancy colour letter not recognised"
    if origin == "FP":
        out.shape = out.shape or "Polki"
        if t:
            out.note, t = f"FP{t} — is the {t} part of the product name?", ""
    if t:
        for token, name in COLOURS:
            if t.startswith(token):
                out.colour, t = name, t[len(token):]
                break
        else:
            if t in COLOUR_LADDER:
                out.colour, out.note = t, "single colour grade — confirm"
            else:
                out.colour, out.note = f"? {t}", out.note or "colour token not recognised"
            t = ""
    if t:
        out.note = out.note or f"left over: {t}"
    if not out.shape:
        out.note = out.note or "no shape in the code"
    return out


SUB = re.compile(r"^(0+)-(0+)$|^0-1$")
SIEVE_SINGLE = re.compile(r"^\+(\d+)$")
SIEVE_RANGE = re.compile(r"^\+(\d+)-(\d+)$")
CARAT = re.compile(r"^([A-Z]{1,3})\s+([\d.]+)-([\d.]+)$")
#: size prefixes on carat-banded goods, read the IVY way (PR Pear, PC Princess)
CARAT_SHAPES = {"PR": "Pear", "PC": "Princess", "M": "Marquise", "AS": "Asscher", "OV": "Oval", "EM": "Emerald",
                "TR": "Trillion", "H": "Heart", "TB": "Tapered Baguette", "R": "Round"}


@dataclass
class Sized:
    band: str
    ct_lo: Decimal = None
    ct_hi: Decimal = None
    shape: str = ""


def _sieve(lower):
    # "+2-6" read as passes +2, held by 6 — so +6 is the next band. Open question 7.
    return "+2-6" if lower < 6 else "+6-11" if lower < 11 else "11-20" if lower < 20 else "20+"


def size_band(size_text):
    z = (size_text or "").strip()
    if SUB.match(z) or z == "+1" or z.startswith("-2"):
        return Sized("-2")
    match = SIEVE_SINGLE.match(z) or SIEVE_RANGE.match(z)
    if match:
        return Sized(_sieve(int(match.group(1))))
    match = CARAT.match(z)
    if match:
        prefix = match.group(1)
        return Sized("carat band", Decimal(match.group(2)), Decimal(match.group(3)),
                     CARAT_SHAPES.get(prefix, f"? {prefix}"))
    return Sized("?")
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest inventory/tests/test_dia_rules.py -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add inventory/dia_rules.py inventory/tests/test_dia_rules.py
git commit -m "Read diamond item codes and sizes, with the IVY export's shape names"
```

---

### Task 3: Read the diamond register

**Files:**
- Create: `inventory/importers/diamonds.py`, `inventory/tests/fixtures_diamonds.py`, `inventory/tests/test_dia_parse.py`

**Interfaces:**
- Produces: `diamonds.CATEGORY_NAMES`; `diamonds.Row` dataclass `(src, category, batch_no, item_code, size_text, ct)`; `diamonds.parse(fileobj) -> [Row]`; `diamonds.header_problems(fileobj) -> [str]`; `fixtures_diamonds.build_workbook(rows=None) -> io.BytesIO`, `fixtures_diamonds.ROWS_DEFAULT`.

- [ ] **Step 1: Write the fixture and the failing test**

`inventory/tests/fixtures_diamonds.py`:

```python
"""A diamond register in memory, shaped the way build_dia.py documents DIAMOND 31.

Columns A category · B batch · C item code · D (unused) · E size · F weight.
The pivot leaves A–C and E blank when they repeat, puts "Total" rows under
groups, and ends with unlabelled grand-total rows — the ones that once produced
a phantom 1,350 ct. Every one of those shapes is here once.
"""
import io

from openpyxl import Workbook

HEADER = ["Raw Material", "Batch No", "Item Code", "", "Size", "Weight"]

ROWS_DEFAULT = [
    ["Diamond", "", "DRFGH VS-SI", "", "0000-000", 20.13],       # Sheet!2  no batch yet
    ["", "B-771", "DRFGH VS-SI", "", "+6-12", 3.40],              # Sheet!3
    ["", "", "", "", "+2", 1.15],                                 # Sheet!4  carries B-771, DRFGH VS-SI
    ["", "", "DPCEF VVS-VS", "", "+2", 0.85],                     # Sheet!5  carries B-771
    ["Diamond Total", "", "", "", "", 25.53],                     # Sheet!6  skipped
    ["Foil Polki", "BW-1", "FPL", "", "20+", 43.21],              # Sheet!7
    ["", "", "DTRLC VS-SI", "", "TR 0.20-0.24", 0.93],            # Sheet!8  carries Foil Polki / BW-1
    ["", "", "", "", "", 1350.00],                                # Sheet!9  grand total, skipped
]


def build_workbook(rows=None):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet"
    sheet.append(HEADER)
    for row in rows if rows is not None else ROWS_DEFAULT:
        sheet.append([None if cell == "" else cell for cell in row])
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
```

`inventory/tests/test_dia_parse.py`:

```python
from decimal import Decimal

from inventory.importers import diamonds
from inventory.tests.fixtures_diamonds import build_workbook


def test_the_pivot_unrolls_into_lines():
    rows = diamonds.parse(build_workbook())
    assert [r.src for r in rows] == ["Sheet!2", "Sheet!3", "Sheet!4", "Sheet!5", "Sheet!7", "Sheet!8"]
    first, second, carried, recoded, polki, trillion = rows
    assert (first.category, first.batch_no, first.item_code, first.size_text, first.ct) == (
        "Natural Diamond", "", "DRFGH VS-SI", "0000-000", Decimal("20.13"))
    assert (carried.batch_no, carried.item_code, carried.size_text) == ("B-771", "DRFGH VS-SI", "+2")
    assert (recoded.batch_no, recoded.item_code) == ("B-771", "DPCEF VVS-VS")
    assert (polki.category, trillion.category, trillion.batch_no) == ("Foil Polki", "Foil Polki", "BW-1")


def test_totals_never_become_stock():
    assert sum(r.ct for r in diamonds.parse(build_workbook())) == Decimal("69.67")


def test_a_workbook_that_is_not_the_register_is_refused():
    from io import BytesIO
    from openpyxl import Workbook

    book = Workbook()
    book.active.append(["Jewel Code", "Gross Wt"])
    buffer = BytesIO()
    book.save(buffer)
    buffer.seek(0)
    assert diamonds.header_problems(buffer)
    assert diamonds.header_problems(build_workbook()) == []
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/pytest inventory/tests/test_dia_parse.py -v` — Expected: FAIL (`cannot import name 'diamonds'`).

- [ ] **Step 3: Write `inventory/importers/diamonds.py`**

```python
"""The diamond register (``DIAMOND 31.xlsx``): a pivot, unrolled into lines.

Built to the layout ``build_dia.py`` documents, because the workbook itself is
not yet on hand: sheet ``Sheet``, columns A category · B batch · C item code ·
D unused · E size · F weight. When the real file arrives, this parse (and its
fixture) is the only thing that should need to change.
"""
from dataclasses import dataclass
from decimal import Decimal

from openpyxl import load_workbook

SHEET = "Sheet"

CATEGORY_NAMES = {"Diamond": "Natural Diamond", "HPHT Diamond": "HPHT Lab Grown", "Lab Grown": "Lab Grown (CVD?)",
                  "Solitare": "Solitaire", "Foil Polki": "Foil Polki"}


@dataclass
class Row:
    src: str
    category: str
    batch_no: str
    item_code: str
    size_text: str
    ct: Decimal


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _sheet(workbook):
    return workbook[SHEET] if SHEET in workbook.sheetnames else workbook.worksheets[0]


def header_problems(fileobj):
    """Why this is not the diamond register, or ``[]``."""
    try:
        workbook = load_workbook(fileobj, read_only=True, data_only=True)
    except Exception as error:
        return [f"It does not open as a workbook ({error})."]
    for values in _sheet(workbook).iter_rows(max_row=10, values_only=True):
        cells = [_text(v) for v in values[:2]] + [""] * 2
        if cells[0] == "Raw Material" or cells[1] == "Batch No":
            return []
    return ["No 'Raw Material' / 'Batch No' header in the first ten rows."]


def parse(fileobj):
    sheet = _sheet(load_workbook(fileobj, read_only=True, data_only=True))
    current = {"category": "", "batch_no": "", "item_code": "", "size_text": ""}
    rows = []
    for number, values in enumerate(sheet.iter_rows(values_only=True), start=1):
        values = list(values) + [None] * 6
        a, b, c, d, e = (_text(v) for v in values[:5])
        weight = values[5]
        if a == "Raw Material" or b == "Batch No":
            continue
        if "Total" in a + b + c + d:
            continue
        if not (a or b or c or d or e):
            continue            # the pivot's unlabelled grand totals
        if a:
            current["category"] = CATEGORY_NAMES.get(a, a)
        if b:
            current["batch_no"] = b
        if c:
            current["item_code"] = c
        if e:
            current["size_text"] = e
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            continue
        rows.append(Row(src=f"{sheet.title}!{number}", ct=Decimal(str(weight)).quantize(Decimal("0.01")), **current))
    return rows
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest inventory/tests/test_dia_parse.py -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add inventory/importers/diamonds.py inventory/tests/fixtures_diamonds.py inventory/tests/test_dia_parse.py
git commit -m "Unroll the diamond register's pivot into lines, skipping every total"
```

---

### Task 4: Role groups that remember edits

**Files:**
- Modify: `accounts/models.py` (`sync_role_groups`)
- Create: `accounts/tests/test_role_sync.py`

**Interfaces:**
- Produces: `sync_role_groups()` with add-only semantics (same signature and return value).

- [ ] **Step 1: Write the failing test**

`accounts/tests/test_role_sync.py`:

```python
import pytest
from django.contrib.auth.models import Group, Permission

from accounts.models import sync_role_groups

pytestmark = pytest.mark.django_db


def test_an_admins_untick_survives_a_resync():
    sync_role_groups()
    accounts = Group.objects.get(name="ACCOUNTS")
    accounts.permissions.remove(Permission.objects.get(codename="inv_assort"))
    sync_role_groups()
    assert not accounts.permissions.filter(codename="inv_assort").exists()


def test_a_new_right_is_granted_to_the_roles_that_list_it():
    Permission.objects.filter(codename="inv_assort").delete()     # as if the right were brand new
    sync_role_groups()
    assert Group.objects.get(name="ACCOUNTS").permissions.filter(codename="inv_assort").exists()
    assert not Group.objects.get(name="SALES").permissions.filter(codename="inv_assort").exists()


def test_a_new_role_gets_its_full_defaults():
    Group.objects.filter(name="KARIGAR").delete()
    sync_role_groups()
    assert list(Group.objects.get(name="KARIGAR").permissions.values_list("codename", flat=True)) == ["inv_job"]
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/pytest accounts/tests/test_role_sync.py -v` — Expected: `test_an_admins_untick_survives_a_resync` FAILS (the sync resets permissions).

- [ ] **Step 3: Make the sync add-only**

Replace `sync_role_groups` in `accounts/models.py`:

```python
def sync_role_groups():
    """Create the role groups and give each its default capabilities — once.

    Rights are editable on the inventory's Settings page, so a deploy must never
    put back a right an admin took away. A group gets its full defaults only when
    it is first created; after that, only a capability that did not exist before
    this run is granted, to the groups that list it by default. For that to work
    a migration that adds a capability runs this before Django's own post-migrate
    step creates the permission row.

    Idempotent: run from data migrations, from ``load_legacy`` and from tests.
    """
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    from .capabilities import ROLE_GROUPS

    content_type, _ = ContentType.objects.get_or_create(app_label="accounts", model="capability")
    by_codename, new = {}, set()
    for codename, label in Capability._meta.permissions:
        permission, created = Permission.objects.get_or_create(
            codename=codename, content_type=content_type, defaults={"name": label}
        )
        by_codename[codename] = permission
        if created:
            new.add(codename)

    for code, spec in ROLE_GROUPS.items():
        group, created = Group.objects.get_or_create(name=code)
        defaults = [by_codename[cap.split(".", 1)[1]] for cap in spec["caps"]]
        if created:
            group.permissions.set(defaults)
        else:
            group.permissions.add(*[p for p in defaults if p.codename in new])
    return by_codename
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest accounts inventory/tests/test_roles.py stock/tests/test_masking.py -q` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add accounts/models.py accounts/tests/test_role_sync.py
git commit -m "Grant a role's defaults once, so an admin's edits survive every deploy"
```

---

### Task 5: The search, as pure functions

**Files:**
- Create: `inventory/dia_search.py`, `inventory/tests/test_dia_search.py`

**Interfaces:**
- Consumes: row dicts with keys `category, shape, colour, clarity, cols, clars, band, batch, ct, ct_lo, ct_hi` (Task 6 builds them).
- Produces: `Filters` (dataclass: `cat, shape, col, clar, band, batch, ct_from, ct_to, as_role`; `Filters.from_query(querydict)`; `.active`; `.href(**changes)`; `.toggled(key, value)`; `.with_cat(value)`); `col_bucket(row)`; `clar_bucket(row)`; `select(rows, f, skip=None)`; `bubbles(rows, f, key, order=None)`; `category_bubbles(rows, f)`.

- [ ] **Step 1: Write the failing test**

`inventory/tests/test_dia_search.py`:

```python
from decimal import Decimal

from django.http import QueryDict

from inventory.dia_search import Filters, bubbles, category_bubbles, col_bucket, select


def _row(category, shape, colour, cols, clarity, clars, band, ct, batch="B1", lo=None, hi=None):
    return {"category": category, "shape": shape, "colour": colour, "cols": cols, "clarity": clarity,
            "clars": clars, "band": band, "ct": Decimal(ct), "batch": batch, "ct_lo": lo, "ct_hi": hi}


ROWS = [
    _row("Natural Diamond", "Round", "F-G-H", ["F", "G", "H"], "VS-SI", ["VS1", "VS2", "SI1", "SI2"], "+6-11", "3.40"),
    _row("Natural Diamond", "Princess", "E-F", ["E", "F"], "VVS-VS", ["VVS1", "VVS2", "VS1", "VS2"], "+2-6", "1.15", batch="B2"),
    _row("Natural Diamond", "Fancy Colour", "Fancy Yellow", [], "", [], "-2", "20.13"),
    _row("Foil Polki", "Polki", "", [], "", [], "20+", "43.21"),
    _row("Natural Diamond", "Trillion", "? LC", [], "VS-SI", ["VS1", "VS2", "SI1", "SI2"], "carat band", "0.93",
         lo=Decimal("0.20"), hi=Decimal("0.24")),
]


def _f(query=""):
    return Filters.from_query(QueryDict(query))


def test_a_range_grade_counts_under_each_grade():
    found = {b["value"]: b["n"] for b in bubbles(ROWS, _f(), "col", order=["D", "E", "F", "G", "H"])}
    assert found["F"] == 2 and found["G"] == 1 and found["E"] == 1


def test_colour_buckets():
    assert col_bucket(ROWS[2]) == ["Fancy Yellow"]
    assert col_bucket(ROWS[3]) == ["(no colour stated)"]
    assert col_bucket(ROWS[4]) == ["? unresolved token"]


def test_each_row_ignores_its_own_filter():
    f = _f("shape=Round")
    shapes = {b["value"] for b in bubbles(ROWS, f, "shape")}
    assert {"Round", "Princess", "Polki"} <= shapes            # the shape row is not narrowed by itself
    assert {b["value"] for b in bubbles(ROWS, f, "band")} == {"+6-11"}


def test_filters_and_across_rows_or_within():
    assert len(select(ROWS, _f("col=E&col=G"))) == 2
    assert len(select(ROWS, _f("col=E&band=%2B6-11"))) == 0


def test_choosing_a_category_clears_the_rest_but_not_carats():
    f = _f("shape=Round&batch=B1&ct_from=0.1").with_cat("Foil Polki")
    assert (f.cat, f.shape, f.batch, f.ct_from) == ("Foil Polki", (), "", Decimal("0.1"))


def test_carats_overlap_and_exclude_unbanded_lines():
    assert [r["shape"] for r in select(ROWS, _f("ct_from=0.22"))] == ["Trillion"]
    assert select(ROWS, _f("ct_from=0.3")) == []
    assert select(ROWS, _f("ct_from=nonsense")) == ROWS        # an unreadable number is ignored


def test_batch_filter_and_category_bubbles():
    assert len(select(ROWS, _f("batch=B2"))) == 1
    cats = category_bubbles(ROWS, _f())
    assert cats[0]["value"] == "Foil Polki"                    # heaviest first
    assert cats[0]["href"].startswith("?cat=Foil+Polki")


def test_toggling_builds_links():
    f = _f("shape=Round")
    assert "shape=Round" not in f.toggled("shape", "Round").href()
    assert "shape=Princess" in f.toggled("shape", "Princess").href()
    assert _f("as=SALES").toggled("band", "-2").href().endswith("&as=SALES")
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/pytest inventory/tests/test_dia_search.py -v` — Expected: FAIL (`No module named 'inventory.dia_search'`).

- [ ] **Step 3: Write `inventory/dia_search.py`**

```python
"""Search stock's filtering, as pure functions over row dicts (``dMatch``/``bubbles``).

Rows AND across filter rows and OR within one; each row of bubbles is counted
from every filter except its own, so choosing Round still shows Princess as an
option. A range grade answers for every grade it spans. Filters live in the
URL, so a search is a link.
"""
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

LIST_KEYS = ("shape", "col", "clar", "band")


def _number(raw):
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError):
        return None
    return value if value.is_finite() else None


@dataclass(frozen=True)
class Filters:
    cat: str = ""
    shape: tuple = ()
    col: tuple = ()
    clar: tuple = ()
    band: tuple = ()
    batch: str = ""
    ct_from: Decimal = None
    ct_to: Decimal = None
    as_role: str = ""

    @classmethod
    def from_query(cls, query):
        return cls(
            cat=query.get("cat", ""), batch=query.get("batch", ""),
            ct_from=_number(query.get("ct_from")), ct_to=_number(query.get("ct_to")),
            as_role=query.get("as", ""),
            **{key: tuple(query.getlist(key)) for key in LIST_KEYS},
        )

    @property
    def active(self):
        return bool(self.cat or self.batch or self.ct_from is not None or self.ct_to is not None
                    or any(getattr(self, key) for key in LIST_KEYS))

    def href(self):
        pairs = [("cat", self.cat)] + [(key, v) for key in LIST_KEYS for v in getattr(self, key)]
        pairs += [("batch", self.batch), ("ct_from", self.ct_from), ("ct_to", self.ct_to), ("as", self.as_role)]
        return "?" + urlencode([(k, v) for k, v in pairs if v not in ("", None)])

    def toggled(self, key, value):
        values = getattr(self, key)
        return replace(self, **{key: tuple(v for v in values if v != value) if value in values else values + (value,)})

    def with_cat(self, value):
        return replace(self, cat=value, shape=(), col=(), clar=(), band=(), batch="")

    def cleared(self):
        return Filters(as_role=self.as_role)


def col_bucket(row):
    if row["cols"]:
        return row["cols"]
    colour = row["colour"] or ""
    if not colour:
        return ["(no colour stated)"]
    if colour.startswith("Fancy"):
        return [colour]
    if colour.startswith("?"):
        return ["? unresolved token"]
    return ["? misread from the item code"]


def clar_bucket(row):
    if row["clars"]:
        return row["clars"]
    return [f"? {row['clarity']}" if row["clarity"] else "(no clarity stated)"]


def _values(row, key):
    if key == "col":
        return col_bucket(row)
    if key == "clar":
        return clar_bucket(row)
    return [row[key]]


def matches(row, f, skip=None):
    if skip != "cat" and f.cat and row["category"] != f.cat:
        return False
    for key in LIST_KEYS:
        chosen = getattr(f, key)
        if skip != key and chosen and not set(chosen) & set(_values(row, key)):
            return False
    if skip != "batch" and f.batch and row["batch"] != f.batch:
        return False
    if skip != "ct" and (f.ct_from is not None or f.ct_to is not None):
        if row["ct_lo"] is None:
            return False
        if f.ct_from is not None and row["ct_hi"] < f.ct_from:
            return False
        if f.ct_to is not None and row["ct_lo"] > f.ct_to:
            return False
    return True


def select(rows, f, skip=None):
    return [row for row in rows if matches(row, f, skip)]


def bubbles(rows, f, key, order=None):
    """Only values that exist in the current selection, with carats and line counts."""
    tally = {}
    for row in select(rows, f, skip=key):
        for value in _values(row, key):
            n, ct = tally.get(value, (0, Decimal("0")))
            tally[value] = (n + 1, ct + (row["ct"] or 0))
    if order is not None:
        keys = [v for v in order if v in tally] + sorted(v for v in tally if v not in order)
    else:
        keys = sorted(tally, key=lambda v: -tally[v][1])
    chosen = getattr(f, key)
    return [{"value": v, "n": tally[v][0], "ct": tally[v][1], "on": v in chosen, "href": f.toggled(key, v).href()}
            for v in keys]


def category_bubbles(rows, f):
    tally = {}
    for row in select(rows, f, skip="cat"):
        n, ct = tally.get(row["category"], (0, Decimal("0")))
        tally[row["category"]] = (n + 1, ct + (row["ct"] or 0))
    return [{"value": c, "n": tally[c][0], "ct": tally[c][1], "on": f.cat == c, "href": f.with_cat(c).href()}
            for c in sorted(tally, key=lambda c: -tally[c][1])]
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest inventory/tests/test_dia_search.py -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add inventory/dia_search.py inventory/tests/test_dia_search.py
git commit -m "Port the diamond search's cascading filters as pure functions"
```

---

### Task 6: Diamond services and rows

**Files:**
- Create: `inventory/dia_services.py`, `inventory/dia_rows.py`, `inventory/tests/test_dia_services.py`
- Modify: `inventory/tests/conftest.py` (add the `diamonds` fixture and its constants)

**Interfaces:**
- Consumes: Task 1 models and `dia_seed`; Task 2 `dia_rules`; `stock.services.ServiceError/require/log`; `stock.masking.mask`; `accounts.capabilities`.
- Produces:
  - `dia_services.stocked_lines(queryset=None)` (annotated `on_ct`); `rate_table() -> {(code_id, size_text): DiamondRate}`; `price(line, rates) -> (cost_rate|None, sale_rate|None)`;
  - `open_lines(user, specs, import_batch=None) -> [DiamondLine]` where a spec is a dict with keys `category, code, batch_no, size_text, band, ct_lo, ct_hi, shape_override, src, ct`;
  - `recount_line(user, line, ct, note="") -> Movement|None`;
  - `term(kind, value)` (get-or-create) ; `add_term(user, kind, value)`; `rename_term(user, term, value)`; `delete_term(user, term)`; `set_expansion(user, term, grades_text)`;
  - `save_code(user, code, shape, colour, clarity, confirmed, note)`;
  - `set_rate(user, code, size_text, cost_rate, sale_rate, effective_from)`; `load_ivy_rates(user, fileobj) -> {"loaded": int, "unknown": int}`;
  - `save_supplier(user, vendor, code, name, city, terms) -> Vendor`;
  - `RIGHTS` (list of `(codename, label)`), `ROLE_ORDER`; `set_right(user, role, codename, on)`;
  - `dia_rows.line_rows(user, queryset=None) -> [dict]`; `dia_rows.term_usage(lines) -> {term_pk: (n, ct)}`; `dia_rows.rail_counts() -> dict`.
  - fixture `diamonds` → `{"round": line, "princess": line, "polki": line, "supplier": vendor}`; constants `DIA_COST = "16,517"`, `DIA_COST_VALUE = "56,158"`, `DIA_SALE = "21,013"`, `DIA_SALE_VALUE = "71,444"`.

- [ ] **Step 1: Add the fixture**

Append to `inventory/tests/conftest.py`:

```python
#: the round line: 3.40 ct × ₹16,517 cost = ₹56,157.80, × ₹21,013 sale = ₹71,444.20
DIA_COST, DIA_COST_VALUE = "16,517", "56,158"
DIA_SALE, DIA_SALE_VALUE = "21,013", "71,444"
DIA_SUPPLIER = "Kothari Exports"


@pytest.fixture
def diamonds(admin_user_):
    from datetime import date

    from inventory import dia_seed, dia_services
    from inventory.models import DiamondCode, DiamondTerm
    from stock.models import Vendor

    dia_seed.load(DiamondTerm)
    t = dia_services.term
    round_code = DiamondCode.objects.create(
        item_code="DRFGH VS-SI", shape=t("shape", "Round"), colour=t("colour", "F-G-H"),
        clarity=t("clarity", "VS-SI"), confirmed=True)
    princess = DiamondCode.objects.create(
        item_code="DPCEF VVS-VS", shape=t("shape", "Princess"), colour=t("colour", "E-F"),
        clarity=t("clarity", "VVS-VS"), confirmed=True)
    polki = DiamondCode.objects.create(item_code="FPL", shape=t("shape", "Polki"), note="FPL — is the L part of the product name?")
    natural, foil = t("category", "Natural Diamond"), t("category", "Foil Polki")
    lines = dia_services.open_lines(admin_user_, [
        {"category": natural, "code": round_code, "batch_no": "B-771", "size_text": "+6-12",
         "band": t("band", "+6-11"), "src": "Sheet!3", "ct": Decimal("3.40")},
        {"category": natural, "code": princess, "batch_no": "B-771", "size_text": "+2",
         "band": t("band", "+2-6"), "src": "Sheet!5", "ct": Decimal("0.85")},
        {"category": foil, "code": polki, "batch_no": "BW-1", "size_text": "20+",
         "band": t("band", "20+"), "src": "Sheet!7", "ct": Decimal("43.21")},
    ])
    dia_services.set_rate(admin_user_, round_code, "+6-12", Decimal("16517"), Decimal("21013"), date(2026, 9, 1))
    supplier = Vendor.objects.create(code="KOT", name=DIA_SUPPLIER, city="Mumbai", terms="Advance")
    return {"round": lines[0], "princess": lines[1], "polki": lines[2], "supplier": supplier}
```

- [ ] **Step 2: Write the failing tests**

`inventory/tests/test_dia_services.py`:

```python
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import dia_rows, dia_services
from inventory.models import DiamondRate, DiamondTerm, Movement
from stock.services import ServiceError

pytestmark = pytest.mark.django_db


def _line(pk):
    return dia_services.stocked_lines().get(pk=pk)


def test_opening_gives_a_ref_and_a_balance(diamonds):
    assert diamonds["round"].ref == "NRD-000001"
    assert _line(diamonds["round"].pk).on_ct == Decimal("3.40")


def test_price_by_exact_size_then_any_size_then_not_set(diamonds, admin_user_):
    rates = dia_services.rate_table()
    assert dia_services.price(_line(diamonds["round"].pk), rates) == (Decimal("16517"), Decimal("21013"))
    assert dia_services.price(_line(diamonds["princess"].pk), rates) == (None, None)
    dia_services.set_rate(admin_user_, diamonds["princess"].code, "", Decimal("21000"), Decimal("27000"), date(2026, 9, 1))
    assert dia_services.price(_line(diamonds["princess"].pk), dia_services.rate_table())[0] == Decimal("21000")


def test_the_latest_rate_wins(diamonds, admin_user_):
    dia_services.set_rate(admin_user_, diamonds["round"].code, "+6-12", Decimal("1"), Decimal("2"), date(2030, 1, 1))
    assert dia_services.price(_line(diamonds["round"].pk), dia_services.rate_table()) == (Decimal("1"), Decimal("2"))
    assert DiamondRate.objects.count() == 2


def test_rows_mask_money_by_role(diamonds, sales_user, accounts_user, karigar_user):
    def row(user):
        return next(r for r in dia_rows.line_rows(user) if r["ref"] == "NRD-000001")
    full = row(accounts_user)
    assert (full["cost_amount"], full["sale_amount"]) == (Decimal("56157.8000"), Decimal("71444.2000"))
    assert round(full["margin"], 1) == Decimal("27.2")
    assert "cost_rate" not in row(sales_user) and "sale_rate" in row(sales_user)
    assert "sale_rate" not in row(karigar_user)
    assert full["cols"] == ["F", "G", "H"] and full["shape"] == "Round"


def test_recount_posts_the_difference(diamonds, admin_user_):
    move = dia_services.recount_line(admin_user_, diamonds["round"], Decimal("3.10"))
    assert (move.direction, move.ct, move.reason) == (Movement.OUT, Decimal("0.30"), Movement.Reason.RECOUNT_ADJUSTMENT)
    assert dia_services.recount_line(admin_user_, diamonds["round"], Decimal("3.10")) is None


def test_terms_rename_and_refuse_deletes_in_use(diamonds, admin_user_):
    round_shape = DiamondTerm.objects.get(kind="shape", value="Round")
    with pytest.raises(ServiceError):
        dia_services.delete_term(admin_user_, round_shape)
    with pytest.raises(ServiceError):
        dia_services.rename_term(admin_user_, round_shape, "Princess")
    dia_services.rename_term(admin_user_, round_shape, "Round Brilliant")
    assert next(r for r in dia_rows.line_rows(admin_user_) if r["ref"] == "NRD-000001")["shape"] == "Round Brilliant"
    spare = dia_services.add_term(admin_user_, "shape", "Cushion")
    dia_services.delete_term(admin_user_, spare)


def test_expansion_only_names_grades_that_exist(diamonds, admin_user_):
    si_i = DiamondTerm.objects.get(kind="clarity", value="SI-I")
    dia_services.set_expansion(admin_user_, si_i, "SI1 SI2 SI3 I1 I2")
    assert si_i.grades()[-1] == "I2"
    with pytest.raises(ServiceError):
        dia_services.set_expansion(admin_user_, si_i, "SI1 Z9")


def test_a_rate_needs_both_money_rights(diamonds, sales_user):
    with pytest.raises(PermissionDenied):
        dia_services.set_rate(sales_user, diamonds["round"].code, "", Decimal("1"), Decimal("1"), date.today())


def test_rates_load_from_the_ivy_export(diamonds, admin_user_):
    import io
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(["Karigar export"])
    sheet.append([])
    header = [""] * 40
    header[20], header[26], header[32], header[33] = "Item Code", "Size", "Cost Rate", "Sale Rate"
    sheet.append(header)
    for code, size, cost, sale in (("DPCEF VVS-VS", "+2", 21000, 27500), ("DZZZ", "+2", 1, 1)):
        row = [None] * 40
        row[20], row[26], row[32], row[33] = code, size, cost, sale
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    buffer.seek(0)
    assert dia_services.load_ivy_rates(admin_user_, buffer) == {"loaded": 1, "unknown": 1}
    assert dia_services.price(_line(diamonds["princess"].pk), dia_services.rate_table()) == (Decimal("21000"), Decimal("27500"))


def test_rights_are_set_by_an_admin_only_and_never_on_admin(diamonds, admin_user_, accounts_user):
    dia_services.set_right(admin_user_, "SALES", "inv_job", True)
    from django.contrib.auth.models import Group
    assert Group.objects.get(name="SALES").permissions.filter(codename="inv_job").exists()
    with pytest.raises(PermissionDenied):
        dia_services.set_right(accounts_user, "SALES", "inv_job", False)
    with pytest.raises(ServiceError):
        dia_services.set_right(admin_user_, "ADMIN", "view_cost", False)


def test_suppliers_have_unique_codes(diamonds, admin_user_):
    with pytest.raises(ServiceError):
        dia_services.save_supplier(admin_user_, None, "KOT", "Another", "Surat", "")
    created = dia_services.save_supplier(admin_user_, None, "BHA", "Bhansali Diamonds", "Surat", "30 days")
    assert created.terms == "30 days"


def test_rail_counts(diamonds):
    counts = dia_rows.rail_counts()
    assert counts["lines"] == 3 and counts["categories"] == 5 and counts["shapes"] >= 3
```

- [ ] **Step 3: Run to see them fail**

Run: `.venv/bin/pytest inventory/tests/test_dia_services.py -v` — Expected: FAIL (`No module named 'inventory.dia_services'`).

- [ ] **Step 4: Write `inventory/dia_services.py`**

```python
"""Diamond reads that every screen shares, and every diamond write.

Carats on hand are the sum of a line's movements (the stones' rule). Price is
the inventory's own rate card — the latest rate for the line's item code and
size, else for the code at any size — never the stock app's chart.
"""
from decimal import Decimal

from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Case, DecimalField, F, Sum, When
from django.utils import timezone
from openpyxl import load_workbook

from accounts.capabilities import INV_MASTERS, VIEW_COST, VIEW_SALE
from stock.models import Vendor
from stock.services import ServiceError, log, require

from .models import DiamondCode, DiamondLine, DiamondRate, DiamondTerm, Movement

#: the prototype's seven rights, as the permissions they are
RIGHTS = [("view_cost", "See cost"), ("view_sale", "See sale"), ("view_margin", "See margin"),
          ("inv_purchase", "Post purchase"), ("inv_job", "Job cards"), ("inv_assort", "Assort"),
          ("inv_masters", "Edit settings")]
ROLE_ORDER = ["ADMIN", "ACCOUNTS", "SALES", "GRAPHIC", "PRODUCTION", "KARIGAR"]

#: IVY export: header on row 3, diamond band columns by position (the names repeat across bands)
IVY_HEADER_ROW, IVY_CODE, IVY_SIZE, IVY_COST, IVY_SALE = 3, 20, 26, 32, 33


def _by(user):
    return user if getattr(user, "is_authenticated", False) else None


def stocked_lines(queryset=None):
    signed = Case(
        When(movements__direction=Movement.OUT, then=-F("movements__ct")),
        default=F("movements__ct"),
        output_field=DecimalField(max_digits=14, decimal_places=4),
    )
    queryset = DiamondLine.objects.all() if queryset is None else queryset
    return queryset.select_related(
        "category", "band", "shape_override", "code__shape", "code__colour", "code__clarity"
    ).annotate(on_ct=Sum(signed)).order_by("pk")


def rate_table():
    """The current rate per (code, size): later effective dates, then later rows, win."""
    table = {}
    for rate in DiamondRate.objects.order_by("effective_from", "pk"):
        table[(rate.code_id, rate.size_text)] = rate
    return table


def price(line, rates):
    rate = rates.get((line.code_id, line.size_text)) or rates.get((line.code_id, ""))
    return (rate.cost_rate, rate.sale_rate) if rate else (None, None)


def term(kind, value):
    found, _ = DiamondTerm.objects.get_or_create(kind=kind, value=value)
    return found


def _last_ref_number():
    # ponytail: read-the-max under the caller's transaction, as for pouches
    last = DiamondLine.objects.order_by("-ref").values_list("ref", flat=True).first()
    return int(last[4:]) if last else 0


@transaction.atomic
def open_lines(user, specs, import_batch=None):
    """New lines, each with an Opening Balance of its carats."""
    require(user, INV_MASTERS, "Only a role that edits inventory records can add stock.")
    number, now, by = _last_ref_number(), timezone.now(), _by(user)
    lines, weights = [], []
    for spec in specs:
        spec = dict(spec)
        ct = spec.pop("ct")
        if ct is not None and ct < 0:
            raise ServiceError("A weight cannot be negative.")
        number += 1
        lines.append(DiamondLine(ref=f"NRD-{number:06d}", import_batch=import_batch, **spec))
        weights.append(ct)
    DiamondLine.objects.bulk_create(lines)
    Movement.objects.bulk_create([
        Movement(diamond=line, reason=Movement.Reason.OPENING_BALANCE, direction=Movement.IN,
                 ct=ct, occurred_at=now, recorded_by=by, ref=line.src)
        for line, ct in zip(lines, weights)
    ])
    if lines:
        log(user, "INSERT", "inv_dia_line", f"{lines[0].ref}..{lines[-1].ref}", f"{len(lines)} diamond lines opened")
    return lines


def recount_line(user, line, ct, note=""):
    require(user, INV_MASTERS, "Only a role that edits inventory records can recount.")
    if ct is None or ct < 0:
        raise ServiceError("A counted weight has to be zero or more.")
    held = stocked_lines(DiamondLine.objects.filter(pk=line.pk)).get().on_ct or Decimal("0")
    if ct == held:
        return None
    move = Movement.objects.create(
        diamond=line, reason=Movement.Reason.RECOUNT_ADJUSTMENT, direction=Movement.IN if ct > held else Movement.OUT,
        ct=abs(ct - held), note=note, recorded_by=_by(user),
    )
    log(user, "INSERT", "inv_movement", line.pk, f"recount of {line.ref}: {held} → {ct} ct")
    return move


def _in_use(t):
    if t.kind == DiamondTerm.CATEGORY:
        return DiamondLine.objects.filter(category=t).exists()
    if t.kind == DiamondTerm.BAND:
        return DiamondLine.objects.filter(band=t).exists()
    if t.kind == DiamondTerm.SHAPE:
        return DiamondCode.objects.filter(shape=t).exists() or DiamondLine.objects.filter(shape_override=t).exists()
    field = "colour" if t.kind == DiamondTerm.COLOUR else "clarity"
    return DiamondCode.objects.filter(**{field: t}).exists()


def add_term(user, kind, value):
    require(user, INV_MASTERS, "Only a role that edits settings can add a value.")
    value = (value or "").strip()
    if kind not in dict(DiamondTerm.KINDS) or not value:
        raise ServiceError("A value needs a list and a name.")
    if DiamondTerm.objects.filter(kind=kind, value=value).exists():
        raise ServiceError(f"{value} is already on the list.")
    created = DiamondTerm.objects.create(kind=kind, value=value)
    log(user, "INSERT", "inv_dia_term", created.pk, f"{kind}: {value}")
    return created


def rename_term(user, t, value):
    require(user, INV_MASTERS, "Only a role that edits settings can rename a value.")
    value = (value or "").strip()
    if not value:
        raise ServiceError("A value cannot be blank.")
    if DiamondTerm.objects.filter(kind=t.kind, value=value).exclude(pk=t.pk).exists():
        raise ServiceError(f"{value} is already on the list.")
    old, t.value = t.value, value
    t.save(update_fields=["value"])
    log(user, "UPDATE", "inv_dia_term", t.pk, f"{t.kind}: {old} → {value}")


def delete_term(user, t):
    require(user, INV_MASTERS, "Only a role that edits settings can delete a value.")
    if _in_use(t):
        raise ServiceError(f"{t.value} is in use and cannot be deleted.")
    log(user, "DELETE", "inv_dia_term", t.pk, f"{t.kind}: {t.value}")
    t.delete()


def set_expansion(user, t, grades_text):
    require(user, INV_MASTERS, "Only a role that edits settings can change an expansion.")
    grades = (grades_text or "").split()
    known = set(DiamondTerm.objects.filter(kind=t.kind, expands_to="").values_list("value", flat=True))
    unknown = [g for g in grades if g not in known]
    if unknown:
        raise ServiceError(f"Not a single {t.kind} grade: {', '.join(unknown)}.")
    t.expands_to = " ".join(grades)
    t.save(update_fields=["expands_to"])
    log(user, "UPDATE", "inv_dia_term", t.pk, f"{t.value} expands to {t.expands_to or 'nothing'}")


def save_code(user, code, shape, colour, clarity, confirmed, note):
    require(user, INV_MASTERS, "Only a role that edits settings can change an item code.")
    for value, kind in ((shape, DiamondTerm.SHAPE), (colour, DiamondTerm.COLOUR), (clarity, DiamondTerm.CLARITY)):
        if value is not None and value.kind != kind:
            raise ServiceError(f"{value} is not a {kind}.")
    code.shape, code.colour, code.clarity = shape, colour, clarity
    code.confirmed, code.note = bool(confirmed), (note or "").strip()[:120]
    code.save()
    log(user, "UPDATE", "inv_dia_code", code.pk, f"{code.pk}: {shape} / {colour} / {clarity}, confirmed={code.confirmed}")


def _rate(value):
    if value is None:
        return None
    value = Decimal(value)
    if not value.is_finite() or value < 0 or abs(value) >= 10 ** 10:
        raise ServiceError("A rate has to be a number from 0 up to ten digits.")
    return value


def set_rate(user, code, size_text, cost_rate, sale_rate, effective_from):
    """A new dated row; nothing overwritten. A row carries both rates, so both rights are needed."""
    require(user, INV_MASTERS, "Only a role that edits settings can set a rate.")
    require(user, VIEW_COST, "A cost you may not see is not yours to set.")
    require(user, VIEW_SALE, "A sale price you may not see is not yours to set.")
    rate = DiamondRate.objects.create(
        code=code, size_text=(size_text or "").strip(), cost_rate=_rate(cost_rate), sale_rate=_rate(sale_rate),
        effective_from=effective_from or timezone.localdate(), set_by=_by(user),
    )
    log(user, "INSERT", "inv_dia_rate", rate.pk, f"{code.pk} {rate.size_text or 'any size'}")
    return rate


def load_ivy_rates(user, fileobj):
    """Rates from the IVY export file (not the stock app): item code, size, cost and sale rate."""
    require(user, INV_MASTERS, "Only a role that edits settings can load rates.")
    require(user, VIEW_COST, "A cost you may not see is not yours to set.")
    require(user, VIEW_SALE, "A sale price you may not see is not yours to set.")
    sheet = load_workbook(fileobj, read_only=True, data_only=True).active
    codes = set(DiamondCode.objects.values_list("item_code", flat=True))
    found, unknown = {}, set()
    for values in sheet.iter_rows(min_row=IVY_HEADER_ROW + 1, values_only=True):
        values = list(values) + [None] * 40
        code = str(values[IVY_CODE] or "").strip()
        if not code or values[IVY_COST] is None and values[IVY_SALE] is None:
            continue
        if code not in codes:
            unknown.add(code)
            continue
        size = str(values[IVY_SIZE] or "").strip()
        found[(code, size)] = (values[IVY_COST], values[IVY_SALE])
    today = timezone.localdate()
    with transaction.atomic():
        for (code, size), (cost, sale) in found.items():
            DiamondRate.objects.create(code_id=code, size_text=size, effective_from=today, set_by=_by(user),
                                       cost_rate=_rate(None if cost is None else str(cost)),
                                       sale_rate=_rate(None if sale is None else str(sale)))
    log(user, "IMPORT", "inv_dia_rate", "-", f"{len(found)} rates from the IVY export, {len(unknown)} unknown codes")
    return {"loaded": len(found), "unknown": len(unknown)}


def save_supplier(user, vendor, code, name, city, terms):
    require(user, INV_MASTERS, "Only a role that edits settings can change suppliers.")
    code, name = (code or "").strip().upper(), (name or "").strip()
    if not code or not name:
        raise ServiceError("A supplier needs a code and a name.")
    clash = Vendor.objects.filter(code=code)
    if vendor is not None:
        clash = clash.exclude(pk=vendor.pk)
    if clash.exists():
        raise ServiceError(f"Supplier code {code} is already used.")
    vendor = vendor or Vendor()
    vendor.code, vendor.name, vendor.city, vendor.terms = code, name, (city or "").strip(), (terms or "").strip()
    vendor.save()
    log(user, "UPDATE", "vendor", vendor.pk, f"{vendor.code} {vendor.name}")
    return vendor


def set_right(user, role, codename, on):
    """Tick or untick one right for one role. Admins only; the Admin role is never edited."""
    if not (user and user.is_authenticated and user.is_admin()):
        raise PermissionDenied("Only an admin can change user rights.")
    if role == "ADMIN":
        raise ServiceError("The Admin role always holds every right.")
    if role not in ROLE_ORDER or codename not in dict(RIGHTS):
        raise ServiceError("Unknown role or right.")
    group = Group.objects.get(name=role)
    permission = Permission.objects.get(codename=codename, content_type__app_label="accounts")
    (group.permissions.add if on else group.permissions.remove)(permission)
    log(user, "UPDATE", "auth_group", group.pk, f"{role}: {codename} {'on' if on else 'off'}")
```

- [ ] **Step 5: Write `inventory/dia_rows.py`**

```python
"""Diamond rows, built once and masked once — the stones' rule, for lines.

Cost, sale and margin carry the stock app's gated names, so ``mask`` removes
them for a role without the right and the table simply has no such column.
"""
from collections import defaultdict
from decimal import Decimal

from stock.masking import mask

from . import dia_services
from .models import DiamondCode, DiamondLine, DiamondTerm


def line_row(user, line, rates):
    code = line.code
    shape, colour, clarity = line.shape, code.colour, code.clarity
    cost, sale = dia_services.price(line, rates)
    ct = line.on_ct
    row = {
        "pk": line.pk, "ref": line.ref, "category": line.category.value,
        "shape": shape.value if shape else "(unresolved)",
        "colour": colour.value if colour else "", "clarity": clarity.value if clarity else "",
        "cols": colour.grades() if colour else [], "clars": clarity.grades() if clarity else [],
        "band": line.band.value, "size_text": line.size_text, "batch": line.batch_no,
        "item_code": code.item_code, "confirmed": code.confirmed, "note": code.note,
        "ct": ct, "ct_lo": line.ct_lo, "ct_hi": line.ct_hi,
        "cost_rate": cost, "sale_rate": sale,
        "cost_amount": ct * cost if ct is not None and cost is not None else None,
        "sale_amount": ct * sale if ct is not None and sale is not None else None,
        "margin": (sale - cost) / cost * 100 if cost and sale is not None else None,
    }
    return mask(user, row)


def line_rows(user, queryset=None):
    rates = dia_services.rate_table()
    return [line_row(user, line, rates) for line in dia_services.stocked_lines(queryset)]


def term_usage(lines):
    """Lines and carats per term, for the Settings lists' "In use" and "Carats" columns."""
    usage = defaultdict(lambda: [0, Decimal("0")])
    for line in lines:
        shape = line.shape
        for t in (line.category, line.band, shape, line.code.colour, line.code.clarity):
            if t is not None:
                usage[t.pk][0] += 1
                usage[t.pk][1] += line.on_ct or 0
    return usage


def rail_counts():
    by_kind = defaultdict(int)
    for kind in DiamondTerm.objects.values_list("kind", flat=True):
        by_kind[kind] += 1
    return {"lines": DiamondLine.objects.count(), "codes": DiamondCode.objects.count(),
            "categories": by_kind["category"], "shapes": by_kind["shape"], "colours": by_kind["colour"],
            "clarities": by_kind["clarity"], "bands": by_kind["band"]}
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/pytest inventory -q` — Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add inventory/dia_services.py inventory/dia_rows.py inventory/tests/conftest.py inventory/tests/test_dia_services.py
git commit -m "Diamond lines, rates, master lists and rights, written through one service"
```

---

### Task 7: Analyse and commit a diamond import

**Files:**
- Create: `inventory/importers/dia_plan.py`, `inventory/tests/test_dia_import_plan.py`

**Interfaces:**
- Consumes: `diamonds.Row`, `diamonds.parse`, `dia_rules.decode/size_band`, `dia_services.term/open_lines/recount_line/stocked_lines`, models.
- Produces:
  - `NewCode` dataclass `(item_code, shape, colour, clarity, note, confirmed)`;
  - `Item` dataclass `(row, action, existing, problem, candidates, held_ct, recount)`; action ∈ `new | update | skip`;
  - `analyse(rows, decisions=None) -> Plan` where `Plan` has `items`, `codes` (list of `NewCode`), `missing` (list of `(line, action)`), and `counts()` (`rows, new, update, skip, blocked, recount, codes, missing, zero`);
  - `read_decisions(post, plan, decisions) -> dict` — keys `row:<src>` → `{"action": "new|skip|map", "line": "<ref>"}`, `code:<item>` → `{"shape","colour","clarity","confirmed"}`, `missing:<ref>` → `"keep|zero"`;
  - `commit(plan, user, import_batch=None) -> {"created","updated","recounted","zeroed","skipped","codes"}`.

- [ ] **Step 1: Write the failing test**

`inventory/tests/test_dia_import_plan.py`:

```python
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import dia_seed, dia_services
from inventory.importers import dia_plan, diamonds
from inventory.models import DiamondCode, DiamondLine, DiamondTerm
from inventory.tests.fixtures_diamonds import ROWS_DEFAULT, build_workbook
from stock.services import ServiceError

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _terms():
    dia_seed.load(DiamondTerm)


def _plan(rows=None, decisions=None):
    return dia_plan.analyse(diamonds.parse(build_workbook(rows)), decisions)


def test_a_first_import_opens_every_line_and_proposes_every_code(admin_user_):
    plan = _plan()
    counts = plan.counts()
    assert (counts["new"], counts["codes"], counts["blocked"]) == (6, 4, 0)
    proposed = {c.item_code: c for c in plan.codes}
    assert proposed["DPCEF VVS-VS"].shape == "Princess"
    assert proposed["DTRLC VS-SI"].colour == "? LC" and not proposed["DTRLC VS-SI"].confirmed
    result = dia_plan.commit(plan, admin_user_)
    assert (result["created"], result["codes"]) == (6, 4)
    trillion = DiamondLine.objects.get(src="Sheet!8")
    assert (trillion.band.value, trillion.ct_lo, trillion.category.value) == ("carat band", Decimal("0.200"), "Foil Polki")
    assert DiamondCode.objects.get(pk="FPL").shape.value == "Polki"


def test_a_reviewed_code_is_created_as_decided(admin_user_):
    plan = _plan()
    post = {"code:DTRLC VS-SI:shape": "Trillion", "code:DTRLC VS-SI:colour": "L", "code:DTRLC VS-SI:clarity": "VS-SI",
            "code:DTRLC VS-SI:confirmed": "1"}
    decisions = dia_plan.read_decisions(post, plan, {})
    dia_plan.commit(_plan(decisions=decisions), admin_user_)
    code = DiamondCode.objects.get(pk="DTRLC VS-SI")
    assert (code.colour.value, code.confirmed) == ("L", True)


def test_reimport_matches_recounts_and_lists_missing_lines(admin_user_):
    dia_plan.commit(_plan(), admin_user_)
    changed = [list(r) for r in ROWS_DEFAULT]
    changed[1][5] = 3.10                                     # B-771 DRFGH +6-12 lost 0.30 ct
    del changed[6]                                           # the trillion line is gone from the file
    plan = _plan(changed)
    counts = plan.counts()
    assert (counts["new"], counts["update"], counts["recount"], counts["missing"]) == (0, 5, 1, 1)
    decisions = dia_plan.read_decisions({f"missing:{plan.missing[0][0].ref}": "zero"}, plan, {})
    result = dia_plan.commit(_plan(changed, decisions), admin_user_)
    assert (result["recounted"], result["zeroed"]) == (1, 1)
    line = dia_services.stocked_lines().get(src="Sheet!3")
    assert line.on_ct == Decimal("3.10")


DUP = ["Diamond", "B-771", "DRFGH VS-SI", "", "+6-12", 3.40]


def test_an_ambiguous_row_blocks_until_decided(admin_user_):
    dia_plan.commit(_plan([list(DUP), list(DUP)]), admin_user_)       # two lines share one key, Sheet!2 and Sheet!3
    shifted = [list(ROWS_DEFAULT[0]), ["Diamond", "B-900", "DPCEF VVS-VS", "", "+2", 0.85], list(DUP), list(DUP)]
    plan = _plan(shifted)                                             # the pair moved to Sheet!4 and Sheet!5
    assert plan.counts()["blocked"] == 2
    with pytest.raises(ServiceError):
        dia_plan.commit(plan, admin_user_)
    refs = list(DiamondLine.objects.order_by("pk").values_list("ref", flat=True))
    post = {"row:Sheet!4": "map", "row:Sheet!4:line": refs[0], "row:Sheet!5": "map", "row:Sheet!5:line": refs[1]}
    decided = dia_plan.read_decisions(post, plan, {})
    assert _plan(shifted, decided).counts()["blocked"] == 0


def test_sales_cannot_import(sales_user):
    with pytest.raises(PermissionDenied):
        dia_plan.commit(_plan(), sales_user)
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/pytest inventory/tests/test_dia_import_plan.py -v` — Expected: FAIL (`cannot import name 'dia_plan'`).

- [ ] **Step 3: Write `inventory/importers/dia_plan.py`**

```python
"""What a diamond import would do, then doing it.

The register is re-exported and re-imported periodically, and diamond lines
have no clean key (many have no batch number). A row matches an existing line
by batch + item code + size; when that is not unique it falls back to the sheet
row, and when that is still ambiguous a human decides. Nothing is written until
``commit``, which refuses while anything is undecided.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from django.db import transaction

from accounts.capabilities import INV_MASTERS
from stock.services import ServiceError, log, require

from .. import dia_rules, dia_services
from ..models import DiamondCode, DiamondLine, DiamondTerm


@dataclass
class NewCode:
    item_code: str
    shape: str = ""
    colour: str = ""
    clarity: str = ""
    note: str = ""
    confirmed: bool = False


@dataclass
class Item:
    row: object
    action: str = "new"
    existing: object = None
    problem: str = None
    candidates: list = field(default_factory=list)
    held_ct: object = None
    recount: bool = False


@dataclass
class Plan:
    items: list
    codes: list
    missing: list

    def counts(self):
        live = [i for i in self.items if i.action != "skip"]
        return {
            "rows": len(self.items), "skip": len(self.items) - len(live),
            "new": sum(1 for i in live if i.action == "new" and not i.problem),
            "update": sum(1 for i in live if i.action == "update"),
            "blocked": sum(1 for i in live if i.problem),
            "recount": sum(1 for i in live if i.recount),
            "codes": len(self.codes), "missing": len(self.missing),
            "zero": sum(1 for _, action in self.missing if action == "zero"),
        }


def _key(batch_no, item_code, size_text):
    return (batch_no, item_code, size_text)


def _codes(rows, decisions):
    known = set(DiamondCode.objects.values_list("item_code", flat=True))
    proposals = {}
    for row in rows:
        if row.item_code in known or row.item_code in proposals:
            continue
        decoded = dia_rules.decode(row.item_code)
        choice = decisions.get(f"code:{row.item_code}") or {}
        proposals[row.item_code] = NewCode(
            item_code=row.item_code, note=decoded.note,
            shape=choice.get("shape", decoded.shape), colour=choice.get("colour", decoded.colour),
            clarity=choice.get("clarity", decoded.clarity),
            confirmed=choice["confirmed"] if "confirmed" in choice else decoded.confirmed,
        )
    return list(proposals.values())


def analyse(rows, decisions=None):
    decisions = decisions or {}
    existing = list(DiamondLine.objects.select_related("code"))
    by_key, by_src, by_ref = defaultdict(list), {}, {}
    for line in existing:
        by_key[_key(line.batch_no, line.code_id, line.size_text)].append(line)
        by_ref[line.ref] = line
        if line.src:
            by_src[line.src] = line
    in_sheet = Counter(_key(r.batch_no, r.item_code, r.size_text) for r in rows)

    items, taken = [], {}
    for row in rows:
        item = Item(row=row)
        choice = decisions.get(f"row:{row.src}") or {}
        candidates = by_key.get(_key(row.batch_no, row.item_code, row.size_text), [])
        if choice.get("action") == "skip":
            item.action = "skip"
        elif choice.get("action") == "new":
            item.action = "new"
        elif choice.get("action") == "map" and choice.get("line") in by_ref:
            item.action, item.existing = "update", by_ref[choice["line"]]
        elif len(candidates) == 1 and in_sheet[_key(row.batch_no, row.item_code, row.size_text)] == 1:
            item.action, item.existing = "update", candidates[0]
        elif candidates and by_src.get(row.src) in candidates:
            item.action, item.existing = "update", by_src[row.src]
        elif candidates:
            item.problem = f"{len(candidates)} lines share this batch, code and size"
            item.candidates = candidates
        if item.existing is not None:
            if item.existing.pk in taken:
                item.problem = f"{item.existing.ref} is already matched to {taken[item.existing.pk]}"
                item.candidates = candidates or [item.existing]
                item.existing, item.action = None, "new"
            else:
                taken[item.existing.pk] = row.src
        items.append(item)

    held = {line.pk: line.on_ct for line in dia_services.stocked_lines(
        DiamondLine.objects.filter(pk__in=[i.existing.pk for i in items if i.existing]))}
    for item in items:
        if item.existing is not None:
            item.held_ct = held.get(item.existing.pk)
            item.recount = item.row.ct != (item.held_ct or 0)

    missing = [(line, decisions.get(f"missing:{line.ref}", "keep"))
               for line in existing if line.pk not in taken]
    return Plan(items=items, codes=_codes(rows, decisions), missing=missing)


def read_decisions(post, plan, decisions):
    """The review form's answers, merged into what was already decided."""
    decisions = dict(decisions or {})
    for item in plan.items:
        name = f"row:{item.row.src}"
        if name in post:
            decisions[name] = {"action": post.get(name), "line": post.get(f"{name}:line", "")}
    for code in plan.codes:
        name = f"code:{code.item_code}"
        if f"{name}:shape" in post:
            decisions[name] = {"shape": post.get(f"{name}:shape", "").strip(),
                               "colour": post.get(f"{name}:colour", "").strip(),
                               "clarity": post.get(f"{name}:clarity", "").strip(),
                               "confirmed": bool(post.get(f"{name}:confirmed"))}
    for line, _ in plan.missing:
        name = f"missing:{line.ref}"
        if name in post:
            decisions[name] = "zero" if post.get(name) == "zero" else "keep"
    return decisions


def _term(kind, value):
    return dia_services.term(kind, value) if value else None


@transaction.atomic
def commit(plan, user, import_batch=None):
    require(user, INV_MASTERS, "Only a role that edits inventory records can import stock.")
    blocked = [i for i in plan.items if i.problem and i.action != "skip"]
    if blocked:
        raise ServiceError(f"{len(blocked)} rows still need a decision.")
    for code in plan.codes:
        DiamondCode.objects.create(
            item_code=code.item_code, shape=_term(DiamondTerm.SHAPE, code.shape),
            colour=_term(DiamondTerm.COLOUR, code.colour), clarity=_term(DiamondTerm.CLARITY, code.clarity),
            confirmed=code.confirmed, note=code.note,
        )
    result = {"created": 0, "updated": 0, "recounted": 0, "zeroed": 0, "skipped": 0, "codes": len(plan.codes)}
    fresh = []
    for item in plan.items:
        row = item.row
        if item.action == "skip":
            result["skipped"] += 1
            continue
        sized = dia_rules.size_band(row.size_text)
        code = DiamondCode.objects.get(pk=row.item_code)
        fields = {
            "category": dia_services.term(DiamondTerm.CATEGORY, row.category),
            "batch_no": row.batch_no, "size_text": row.size_text,
            "band": dia_services.term(DiamondTerm.BAND, sized.band),
            "ct_lo": sized.ct_lo, "ct_hi": sized.ct_hi, "src": row.src,
            "shape_override": _term(DiamondTerm.SHAPE, sized.shape) if sized.shape and code.shape_id is None else None,
        }
        if item.existing is None:
            fresh.append({"code": code, "ct": row.ct, **fields})
            continue
        line = item.existing
        changed = [name for name, value in fields.items() if getattr(line, name) != value]
        for name in changed:
            setattr(line, name, fields[name])
        if changed:
            line.save(update_fields=changed)
        result["updated"] += 1
        if item.recount:
            dia_services.recount_line(user, line, row.ct, note=f"re-imported from {row.src}")
            result["recounted"] += 1
    result["created"] = len(dia_services.open_lines(user, fresh, import_batch=import_batch))
    for line, action in plan.missing:
        if action == "zero" and dia_services.recount_line(user, line, 0, note="not in the re-imported register"):
            result["zeroed"] += 1
    log(user, "IMPORT", "inv_dia_line", import_batch.pk if import_batch else "-", f"diamond import {result}")
    return result
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest inventory/tests/test_dia_import_plan.py -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add inventory/importers/dia_plan.py inventory/tests/test_dia_import_plan.py
git commit -m "Analyse a diamond import: propose codes, match lines, list what vanished"
```

---

### Task 8: The diamond shell and Search stock

**Files:**
- Create: `inventory/views_diamonds.py`, `inventory/templates/inventory/diamonds/_rail.html`, `inventory/templates/inventory/diamonds/_dsub.html`, `inventory/templates/inventory/diamonds/search.html`, `inventory/tests/test_dia_search_view.py`
- Modify: `templates/inventory_base.html`, `inventory/urls.py`

**Interfaces:**
- Consumes: `dia_rows.line_rows/rail_counts`, `dia_search.*`, `dia_seed`, `accounts.capabilities.ROLE_GROUPS`.
- Produces: `views_diamonds.viewer(request) -> (user_like, role_code)`, `views_diamonds.dia_page(request, template, **context)`, `PreviewUser`; URL name `inventory:diamonds`; templates `diamonds/_rail.html`, `diamonds/_dsub.html` (context `dtab`) for Tasks 9 and 10; base-template context `side = "diamonds"`.

- [ ] **Step 1: Write the failing test**

`inventory/tests/test_dia_search_view.py`:

```python
import pytest
from django.urls import reverse

from inventory.tests.conftest import DIA_COST, DIA_SALE_VALUE

pytestmark = pytest.mark.django_db


def test_search_shows_the_stock_and_the_filters(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert "Natural Diamond" in body and "Foil Polki" in body and "start here" in body
    assert "3 of 3 lines" in body and DIA_COST in body and DIA_SALE_VALUE in body
    assert "Diamonds are internal only — no client view" in body
    assert "Client preview" not in body                  # no client view on the diamond side


def test_a_filter_narrows_the_table(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:diamonds"), {"cat": "Foil Polki"}).content.decode()
    assert "1 of 3 lines" in body and "Showing only what" in body and "FPL" in body
    assert "DRFGH VS-SI</td>" not in body


def test_sales_sees_no_cost_column(client, sales_user, diamonds):
    client.force_login(sales_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert "Cost / ct" not in body and DIA_COST not in body and "Hidden for Sales / Showroom" in body


def test_an_admin_can_preview_a_role(client, admin_user_, diamonds):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:diamonds"), {"as": "SALES"}).content.decode()
    assert DIA_COST not in body and "✕ cost" in body


def test_a_non_admin_cannot_preview(client, sales_user, diamonds):
    client.force_login(sales_user)
    body = client.get(reverse("inventory:diamonds"), {"as": "ADMIN"}).content.decode()
    assert DIA_COST not in body
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/pytest inventory/tests/test_dia_search_view.py -v` — Expected: FAIL (`NoReverseMatch: 'diamonds'`).

- [ ] **Step 3: Write `inventory/views_diamonds.py`**

```python
"""Diamond Search stock, and what every diamond page shares.

The "Viewing as" selector is the prototype's; here it is real only for an
admin, who sees the page exactly as another role would — the masking runs for
a stand-in holding that role's permissions. Everyone else sees their own role.
"""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.shortcuts import render

from accounts.capabilities import ROLE_GROUPS, VIEW_COST, VIEW_MARGIN, VIEW_SALE
from accounts.context_processors import _role_code

from . import dia_rows, dia_search, dia_seed
from .models import DiamondTerm

TABLE_CAP = 300


class PreviewUser:
    """Just enough of a user for masking: authenticated, holding one role's rights."""

    is_authenticated = True
    is_superuser = False

    def __init__(self, role):
        group = Group.objects.get(name=role)
        self.perms = {f"{p.content_type.app_label}.{p.codename}"
                      for p in group.permissions.select_related("content_type")}

    def has_perm(self, perm, obj=None):
        return perm in self.perms


def viewer(request):
    """(who the page is built for, their role code). Only an admin may borrow another role."""
    wanted = request.GET.get("as", "")
    if wanted in ROLE_GROUPS and request.user.is_admin() and wanted != "ADMIN":
        return PreviewUser(wanted), wanted
    return request.user, _role_code(request.user)


def dia_page(request, template, **context):
    """Every diamond page: the diamond rail, the diamond tabs, no client toggle."""
    context.update(side="diamonds", drail=dia_rows.rail_counts())
    return render(request, template, context)


def _order(kind):
    return list(DiamondTerm.objects.filter(kind=kind).order_by("sort", "value").values_list("value", flat=True))


def _totals(rows, everything):
    """Totals of what is in view; which money keys exist is read off any row, so an
    empty selection still shows ₹0 to a role that may see money, not "Hidden"."""
    sample = everything[0] if everything else {}
    out = {"ct": sum((r["ct"] or 0) for r in rows), "n": len(rows)}
    for key in ("cost_amount", "sale_amount"):
        if key in sample:
            out[key] = sum((r[key] or 0) for r in rows)
    if "cost_amount" in out and "sale_amount" in out and "margin" in sample:
        cost, sale = out["cost_amount"], out["sale_amount"]
        out["margin"] = (sale - cost) / cost * 100 if cost else None
        out["gross"] = sale - cost
    return out


@login_required
def search(request):
    user, role = viewer(request)
    everything = dia_rows.line_rows(user)
    f = dia_search.Filters.from_query(request.GET)
    shown = dia_search.select(everything, f)
    table = sorted(shown, key=lambda r: -(r["ct"] or 0))[:TABLE_CAP]
    can = {"cost": user.has_perm(VIEW_COST), "sale": user.has_perm(VIEW_SALE), "margin": user.has_perm(VIEW_MARGIN),
           "job": user.has_perm("accounts.inv_job"), "assort": user.has_perm("accounts.inv_assort"),
           "purchase": user.has_perm("accounts.inv_purchase")}
    shapes_here = {r["shape"] for r in dia_search.select(everything, f, skip="shape") if r["category"] == f.cat}
    return dia_page(
        request, "inventory/diamonds/search.html", dtab="search", f=f, role=role,
        role_label=ROLE_GROUPS[role]["name"], roles=[(code, spec["name"]) for code, spec in ROLE_GROUPS.items()],
        can_preview=request.user.is_admin(), can=can, rows=table, shown=len(shown), total=len(everything),
        all_ct=sum((r["ct"] or 0) for r in everything), totals=_totals(shown, everything),
        cats=dia_search.category_bubbles(everything, f), cat_shapes=len(shapes_here),
        shape_bubbles=dia_search.bubbles(everything, f, "shape"),
        col_bubbles=dia_search.bubbles(everything, f, "col", order=[v for v in dia_seed.COLOUR_LADDER]),
        clar_bubbles=dia_search.bubbles(everything, f, "clar", order=[v for v in dia_seed.CLARITY_LADDER]),
        band_bubbles=dia_search.bubbles(everything, f, "band", order=_order(DiamondTerm.BAND)),
        all_href=f.with_cat("").href(), clear_href=f.cleared().href(), money=bool(table) and "cost_rate" in table[0],
        sale_money=bool(table) and "sale_rate" in table[0], margin_money=bool(table) and "margin" in table[0],
    )
```

Add to `inventory/urls.py`:

```python
from . import views_diamonds
```

```python
    path("diamonds/", views_diamonds.search, name="diamonds"),
```

- [ ] **Step 4: Teach the shell about sides**

In `templates/inventory_base.html`, replace the `catsw` block:

```django
    <div class="catsw">
      <a class="{% if side != 'diamonds' %}on{% endif %}" href="{% url 'inventory:shelf' %}">◆ Stones</a>
      <a class="{% if side == 'diamonds' %}on{% endif %}" href="{% url 'inventory:diamonds' %}">◇ Diamonds</a>
    </div>
    {% if side == 'diamonds' %}{% include "inventory/diamonds/_rail.html" %}{% else %}{% include "inventory/_rail.html" %}{% endif %}
```

(delete the old `{% include "inventory/_rail.html" %}` line that followed it).

Wrap the client toggle so it only shows on the stones side:

```django
      {% if side != 'diamonds' %}
      <form class="vt" method="post" action="{% url 'inventory:set_view' %}">{% csrf_token %}
        ...unchanged...
      </form>
      {% endif %}
```

Replace the `<div class="tabs">…</div>` block with:

```django
    <div class="tabs">
      {% if side == 'diamonds' %}
        <button disabled title="Coming soon">Movements 🔒</button>
        <button disabled title="Coming soon">Purchase 🔒</button>
        <a class="on" href="{% url 'inventory:diamonds' %}">Diamond stock</a>
        <button disabled title="Coming soon">Stock take 🔒</button>
      {% else %}
        <a class="{% if tab == 'shelf' %}on{% endif %}" href="{% url 'inventory:shelf' %}">Shelf</a>
        {% if pouch_ref %}<a class="{% if tab == 'lot' %}on{% endif %}" href="{% url 'inventory:pouch' pouch_ref %}">Pouch detail</a>
        {% else %}<button disabled>Pouch detail</button>{% endif %}
        {% if not client_view %}
          {% if pouch_ref %}<a class="{% if tab == 'tx' %}on{% endif %}" href="{% url 'inventory:movements' pouch_ref %}">Movements</a>
          {% else %}<button disabled>Movements</button>{% endif %}
          <button disabled title="Coming soon">Purchase 🔒</button>
        {% endif %}
        <button disabled title="Coming soon">Stock take 🔒</button>
      {% endif %}
    </div>
```

Add to the compat block of `static/css/inventory.css` (the sub-tab bar is `<a>`s here, the prototype's were buttons):

```css
.dsub a,.dsub span{flex:1;text-align:center;color:var(--muted);font-size:13px;font-weight:560;padding:9px 6px;
  border-radius:7px;text-decoration:none}
.dsub a:hover{color:var(--ink)}
.dsub a.on{background:var(--s1);color:#fff;box-shadow:0 1px 3px rgba(11,11,11,.2)}
.dsub span{opacity:.55;cursor:not-allowed}
a.bub{text-decoration:none}
```

- [ ] **Step 5: Write the diamond templates**

`inventory/templates/inventory/diamonds/_rail.html`:

```django
{% load inventory_extras %}{% comment %}The prototype's diamond rail. The seven
Settings links jump to their card on the one Settings page.{% endcomment %}
<div class="nav-h">Diamonds — internal</div>
<nav class="nav">
  <a class="{% if dtab == 'search' %}on{% endif %}" href="{% url 'inventory:diamonds' %}"><span class="ic">🔍</span>Search stock<span class="ct">{{ drail.lines|grouped }}</span></a>
  <span class="locked"><span class="ic">⚒</span>Job cards<span class="ct">🔒</span></span>
  <span class="locked"><span class="ic">⇅</span>Assortments<span class="ct">🔒</span></span>
  <span class="locked"><span class="ic">＋</span>Purchases<span class="ct">🔒</span></span>
  {% if caps.inv_masters %}<a class="{% if dtab == 'import' %}on{% endif %}" href="{% url 'inventory:dia_import_home' %}"><span class="ic">⇅</span>Import diamonds</a>{% endif %}
</nav>
<div class="nav-h">Settings</div>
<nav class="nav">
  <a href="{% url 'inventory:dia_settings' %}#rights"><span class="ic">◈</span>User rights</a>
  <a href="{% url 'inventory:dia_settings' %}#suppliers"><span class="ic">⌗</span>Suppliers</a>
  <a href="{% url 'inventory:dia_settings' %}#category"><span class="ic">◇</span>Categories<span class="ct">{{ drail.categories }}</span></a>
  <a href="{% url 'inventory:dia_settings' %}#shape"><span class="ic">◆</span>Shapes<span class="ct">{{ drail.shapes }}</span></a>
  <a href="{% url 'inventory:dia_settings' %}#colour"><span class="ic">◈</span>Colour grades<span class="ct">{{ drail.colours }}</span></a>
  <a href="{% url 'inventory:dia_settings' %}#clarity"><span class="ic">◇</span>Clarity grades<span class="ct">{{ drail.clarities }}</span></a>
  <a href="{% url 'inventory:dia_settings' %}#band"><span class="ic">⊞</span>Size bands<span class="ct">{{ drail.bands }}</span></a>
</nav>
```

`inventory/templates/inventory/diamonds/_dsub.html`:

```django
<div class="dsub">
  <a class="{% if dtab == 'search' %}on{% endif %}" href="{% url 'inventory:diamonds' %}">Search stock</a>
  <span title="Coming soon">Job cards 🔒</span>
  <span title="Coming soon">Assortments 🔒</span>
  <span title="Coming soon">Purchases 🔒</span>
  <a class="{% if dtab == 'settings' %}on{% endif %}" href="{% url 'inventory:dia_settings' %}">Settings</a>
</div>
```

`inventory/templates/inventory/diamonds/search.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Search stock · Diamonds{% endblock %}
{% block crumb %}<b>Diamonds</b> &nbsp;›&nbsp; Search stock{% endblock %}
{% block content %}
{% include "inventory/diamonds/_dsub.html" %}

<div class="rolebar">
  <span class="hint">Viewing as</span>
  {% if can_preview %}
  <form method="get" style="display:contents">
    <select class="inp" name="as" style="max-width:180px" onchange="this.form.submit()">
      {% for code, name in roles %}<option value="{% if code != 'ADMIN' %}{{ code }}{% endif %}"{% if code == role %} selected{% endif %}>{{ name }}</option>{% endfor %}
    </select>
  </form>
  {% else %}<span class="ro2">{{ role_label }}</span>{% endif %}
  <span class="rights">
    <span class="rt {% if can.cost %}yes{% else %}no{% endif %}">{% if can.cost %}✓{% else %}✕{% endif %} cost</span>
    <span class="rt {% if can.sale %}yes{% else %}no{% endif %}">{% if can.sale %}✓{% else %}✕{% endif %} sale</span>
    <span class="rt {% if can.margin %}yes{% else %}no{% endif %}">{% if can.margin %}✓{% else %}✕{% endif %} margin</span>
  </span>
  <span class="spacer"></span>
  <span class="chip">Diamonds are internal only — no client view</span>
</div>

<div class="searchcard">
  <div class="srow">
    <div class="slab">Category<div class="shint">start here</div></div>
    <div class="bubrow">
      <a class="bub big{% if not f.cat %} on{% endif %}" href="{{ all_href }}"><b>All</b><span>{{ all_ct|ct }} ct · {{ total }}</span></a>
      {% for b in cats %}<a class="bub big{% if b.on %} on{% endif %}" href="{{ b.href }}"><b>{{ b.value }}</b><span>{{ b.ct|ct }} ct · {{ b.n }}</span></a>{% endfor %}
    </div>
  </div>
  {% if f.cat %}<div class="catnote">Showing only what <b>{{ f.cat }}</b> actually holds — {{ cat_shapes }} shapes.</div>{% endif %}
  <div class="srow"><div class="slab">Shape</div><div class="bubrow">{% include "inventory/diamonds/_bubbles.html" with list=shape_bubbles %}</div></div>
  <div class="srow"><div class="slab">Colour</div><div class="bubrow">{% include "inventory/diamonds/_bubbles.html" with list=col_bubbles %}</div></div>
  <div class="srow"><div class="slab">Clarity</div><div class="bubrow">{% include "inventory/diamonds/_bubbles.html" with list=clar_bubbles %}</div></div>
  <div class="srow"><div class="slab">Size</div><div class="bubrow">{% include "inventory/diamonds/_bubbles.html" with list=band_bubbles %}</div></div>
  <div class="srow last">
    <div class="slab">Carats</div>
    <form method="get" class="ctrow">
      {% if f.cat %}<input type="hidden" name="cat" value="{{ f.cat }}">{% endif %}
      {% for v in f.shape %}<input type="hidden" name="shape" value="{{ v }}">{% endfor %}
      {% for v in f.col %}<input type="hidden" name="col" value="{{ v }}">{% endfor %}
      {% for v in f.clar %}<input type="hidden" name="clar" value="{{ v }}">{% endfor %}
      {% for v in f.band %}<input type="hidden" name="band" value="{{ v }}">{% endfor %}
      {% if f.as_role %}<input type="hidden" name="as" value="{{ f.as_role }}">{% endif %}
      <span class="hint">From</span><input class="inp tnum" name="ct_from" style="width:88px" value="{{ f.ct_from|default_if_none:'' }}" placeholder="Any" onchange="this.form.submit()">
      <span class="hint">To</span><input class="inp tnum" name="ct_to" style="width:88px" value="{{ f.ct_to|default_if_none:'' }}" placeholder="Any" onchange="this.form.submit()">
      <span class="hint">Batch</span><input class="inp mono" name="batch" style="width:110px" value="{{ f.batch }}" placeholder="Any" onchange="this.form.submit()">
      <span class="spacer"></span>
      {% if f.active %}<a class="btn" href="{{ clear_href }}">Clear all</a>{% endif %}
      <span class="btn pri">{{ shown }} lines · {{ totals.ct|ct }} ct</span>
    </form>
  </div>
</div>

<div class="totstrip">
  <div class="tot heroTot"><div class="l">Quantity in view</div><div class="v">{{ totals.ct|ct }} ct</div><div class="f">{{ shown }} of {{ total }} lines</div></div>
  {% if 'cost_amount' in totals %}<div class="tot"><div class="l">Cost value</div><div class="v">{{ totals.cost_amount|rupees }}</div><div class="f">at the cost rate on each line</div></div>
  {% else %}<div class="tot"><div class="l">Cost value</div><div class="v" style="color:var(--muted);font-size:17px">Hidden for {{ role_label }}</div><div class="f">no cost rights on this role</div></div>{% endif %}
  {% if 'sale_amount' in totals %}<div class="tot"><div class="l">Sale value</div><div class="v">{{ totals.sale_amount|rupees }}</div><div class="f">at the sale rate on each line</div></div>
  {% else %}<div class="tot"><div class="l">Sale value</div><div class="v" style="color:var(--muted);font-size:17px">Hidden</div><div class="f">&nbsp;</div></div>{% endif %}
  {% if 'margin' in totals %}<div class="tot"><div class="l">Margin</div><div class="v">{% if totals.margin is not None %}{{ totals.margin|floatformat:1 }}%{% else %}—{% endif %}</div><div class="f">{{ totals.gross|rupees }} gross</div></div>
  {% else %}<div class="tot"><div class="l">Margin</div><div class="v" style="color:var(--muted);font-size:17px">Hidden</div><div class="f">&nbsp;</div></div>{% endif %}
</div>

<div class="card" style="overflow:hidden">
  <div class="card-h"><span class="card-t">Stock</span><span class="spacer"></span>
    {% if can.job %}<button class="btn sm" disabled title="Coming soon">⚒ Job card 🔒</button>{% endif %}
    {% if can.assort %}<button class="btn sm" disabled title="Coming soon">⇅ Assort 🔒</button>{% endif %}
    {% if can.purchase %}<button class="btn sm pri" disabled title="Coming soon">＋ Purchase 🔒</button>{% endif %}</div>
  <div style="overflow:auto;max-height:620px"><table class="pt">
    <thead><tr><th>Category</th><th>Shape</th><th>Colour</th><th>Clarity</th><th>Size</th><th>Batch</th><th class="r">Carats</th>
      {% if money %}<th class="r">Cost / ct</th><th class="r">Cost value</th>{% endif %}
      {% if sale_money %}<th class="r">Sale / ct</th><th class="r">Sale value</th>{% endif %}
      {% if margin_money %}<th class="r">Margin</th>{% endif %}
      <th>Item code</th><th>Read</th></tr></thead>
    <tbody>{% for r in rows %}<tr>
      <td>{{ r.category }}</td><td>{{ r.shape }}</td>
      <td>{% if r.colour %}{{ r.colour }}{% else %}<span class="hint">—</span>{% endif %}</td>
      <td>{% if r.clarity %}{{ r.clarity }}{% else %}<span class="hint">—</span>{% endif %}</td>
      <td class="mono">{{ r.band }}<div class="hint">{{ r.size_text }}</div></td>
      <td class="mono" style="font-size:11px">{% if r.batch %}{{ r.batch }}{% else %}<span class="chip crit"><span class="dot"></span>none</span>{% endif %}</td>
      <td class="r"><b>{{ r.ct|ct }}</b></td>
      {% if money %}<td class="r">{% if r.cost_rate is not None %}{{ r.cost_rate|rupees }}{% else %}<span class="hint">not set</span>{% endif %}</td>
        <td class="r">{{ r.cost_amount|rupees }}</td>{% endif %}
      {% if sale_money %}<td class="r">{% if r.sale_rate is not None %}{{ r.sale_rate|rupees }}{% else %}<span class="hint">not set</span>{% endif %}</td>
        <td class="r"><b>{{ r.sale_amount|rupees }}</b></td>{% endif %}
      {% if margin_money %}<td class="r">{% if r.margin is not None %}{{ r.margin|floatformat:0 }}%{% else %}—{% endif %}</td>{% endif %}
      <td class="mono" style="font-size:11px">{{ r.item_code }}</td>
      <td>{% if r.confirmed %}<span class="chip good"><span class="dot"></span>clean</span>{% else %}<span class="chip warn"><span class="dot"></span>{{ r.note|default:"check" }}</span>{% endif %}</td>
    </tr>{% endfor %}</tbody></table></div>
  {% if shown > rows|length %}<div class="card-b" style="border-top:1px solid var(--border)"><div class="hint">Showing the {{ rows|length }} heaviest of {{ shown }}.</div></div>{% endif %}
</div>
{% endblock %}
```

Create `inventory/templates/inventory/diamonds/_bubbles.html`:

```django
{% load inventory_extras %}{% for b in list %}<a class="bub{% if b.on %} on{% endif %}" href="{{ b.href }}"><b>{{ b.value }}</b><span>{{ b.ct|ct }} ct · {{ b.n }}</span></a>{% empty %}<span class="hint">nothing in this category</span>{% endfor %}
```

The `_rail.html` reverses `inventory:dia_settings` and `inventory:dia_import_home`, which Tasks 9 and 10 add. Add placeholder routes now in `inventory/urls.py`, marked for replacement:

```python
    path("diamonds/settings/", views_diamonds.search, name="dia_settings"),            # replaced in Task 9
    path("diamonds/import/", views_diamonds.search, name="dia_import_home"),           # replaced in Task 10
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/pytest inventory -q` — Expected: PASS (every stones test still green: the stones side renders exactly as before).

- [ ] **Step 7: Commit**

```bash
git add inventory templates/inventory_base.html static/css/inventory.css
git commit -m "Diamond Search stock: the prototype's cascading bubbles over real lines"
```

---

### Task 9: Settings

**Files:**
- Create: `inventory/views_dia_settings.py`, `inventory/templates/inventory/diamonds/settings.html`, `inventory/tests/test_dia_settings.py`
- Modify: `inventory/urls.py` (replace the `dia_settings` placeholder, add the POST routes)

**Interfaces:**
- Consumes: `views_diamonds.dia_page/viewer`, `dia_services.*` (Task 6), `dia_rows.term_usage`.
- Produces: URL names `inventory:dia_settings`, `inventory:dia_term_add`, `dia_term_rename` (`pk`), `dia_term_delete` (`pk`), `dia_expansion` (`pk`), `dia_code_save` (`code`), `dia_rate_save`, `dia_rates_ivy`, `dia_supplier_save`, `dia_right_toggle`.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_dia_settings.py`:

```python
import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from inventory.models import DiamondRate, DiamondTerm
from inventory.tests.conftest import DIA_COST, DIA_SUPPLIER

pytestmark = pytest.mark.django_db


def test_settings_lists_everything_for_an_editor(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:dia_settings")).content.decode()
    for heading in ("User rights", "Suppliers", "Categories", "Shapes", "Colour grades", "Clarity grades",
                    "Size bands", "Item codes", "Rate card", "Range → grade expansion"):
        assert heading in body, heading
    assert DIA_SUPPLIER in body and "Advance" in body and DIA_COST in body
    assert 'id="shape"' in body                                # the rail's anchors land


def test_settings_is_refused_without_the_masters_right(client, sales_user, diamonds):
    client.force_login(sales_user)
    body = client.get(reverse("inventory:dia_settings")).content.decode()
    assert "Not permitted for Sales / Showroom" in body and "Rate card" not in body
    assert client.post(reverse("inventory:dia_term_add"), {"kind": "shape", "value": "Cushion"}).status_code == 403


def test_add_rename_delete_a_value(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    client.post(reverse("inventory:dia_term_add"), {"kind": "shape", "value": "Cushion"})
    cushion = DiamondTerm.objects.get(kind="shape", value="Cushion")
    client.post(reverse("inventory:dia_term_rename", args=[cushion.pk]), {"value": "Cushion Brilliant"})
    cushion.refresh_from_db()
    assert cushion.value == "Cushion Brilliant"
    client.post(reverse("inventory:dia_term_delete", args=[cushion.pk]))
    assert not DiamondTerm.objects.filter(pk=cushion.pk).exists()
    in_use = DiamondTerm.objects.get(kind="shape", value="Round")
    response = client.post(reverse("inventory:dia_term_delete", args=[in_use.pk]), follow=True)
    assert "in use" in response.content.decode()


def test_a_rate_can_be_set_and_codes_edited(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    client.post(reverse("inventory:dia_rate_save"), {"code": "DPCEF VVS-VS", "size_text": "", "cost_rate": "21000",
                                                     "sale_rate": "27000", "effective_from": "2026-09-30"})
    assert DiamondRate.objects.filter(code_id="DPCEF VVS-VS").exists()
    shape = DiamondTerm.objects.get(kind="shape", value="Round")
    client.post(reverse("inventory:dia_code_save", args=["FPL"]),
                {"shape": shape.pk, "colour": "", "clarity": "", "confirmed": "1", "note": ""})
    from inventory.models import DiamondCode
    assert DiamondCode.objects.get(pk="FPL").confirmed


def test_only_an_admin_toggles_rights(client, admin_user_, accounts_user, diamonds):
    client.force_login(accounts_user)
    assert client.post(reverse("inventory:dia_right_toggle"), {"role": "SALES", "right": "inv_job", "on": "1"}).status_code == 403
    client.force_login(admin_user_)
    client.post(reverse("inventory:dia_right_toggle"), {"role": "SALES", "right": "inv_job", "on": "1"})
    assert Group.objects.get(name="SALES").permissions.filter(codename="inv_job").exists()


def test_suppliers_can_be_added(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    client.post(reverse("inventory:dia_supplier_save"), {"code": "bha", "name": "Bhansali Diamonds", "city": "Surat", "terms": "30 days"})
    from stock.models import Vendor
    assert Vendor.objects.get(code="BHA").terms == "30 days"
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/bin/pytest inventory/tests/test_dia_settings.py -v` — Expected: FAIL (the settings route is still the placeholder).

- [ ] **Step 3: Write `inventory/views_dia_settings.py`**

```python
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
             for r in dia_services.rate_table().values()]
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
```

`PermissionDenied` raised by `require` or `set_right` is not caught, so Django answers 403.

In `inventory/urls.py`, import and replace the `dia_settings` placeholder:

```python
from . import views_dia_settings
```

```python
    path("diamonds/settings/", views_dia_settings.settings_page, name="dia_settings"),
    path("diamonds/settings/terms/", views_dia_settings.term_add, name="dia_term_add"),
    path("diamonds/settings/terms/<int:pk>/rename/", views_dia_settings.term_rename, name="dia_term_rename"),
    path("diamonds/settings/terms/<int:pk>/delete/", views_dia_settings.term_delete, name="dia_term_delete"),
    path("diamonds/settings/terms/<int:pk>/expansion/", views_dia_settings.expansion, name="dia_expansion"),
    path("diamonds/settings/codes/<str:code>/", views_dia_settings.code_save, name="dia_code_save"),
    path("diamonds/settings/rates/", views_dia_settings.rate_save, name="dia_rate_save"),
    path("diamonds/settings/rates/ivy/", views_dia_settings.rates_ivy, name="dia_rates_ivy"),
    path("diamonds/settings/suppliers/", views_dia_settings.supplier_save, name="dia_supplier_save"),
    path("diamonds/settings/rights/", views_dia_settings.right_toggle, name="dia_right_toggle"),
```

- [ ] **Step 4: Write `inventory/templates/inventory/diamonds/settings.html`**

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Settings · Diamonds{% endblock %}
{% block crumb %}<b>Diamonds</b> &nbsp;›&nbsp; Settings{% endblock %}
{% block content %}
{% include "inventory/diamonds/_dsub.html" %}
{% if denied %}
<div class="dbanner"><h2>Settings</h2></div>
<div class="banner crit"><div class="banner-ic">✕</div><div><h4>Not permitted for {{ role_name }}</h4>
  <p>Master lists, suppliers and user rights need the Edit settings right.</p></div></div>
{% else %}
<div class="dbanner"><h2>Settings</h2></div>

<div class="card" id="rights" style="margin-bottom:14px">
  <div class="card-h"><span class="card-t">User rights</span></div>
  <div class="card-b"><table class="pt">
    <thead><tr><th>Role</th>{% for codename, label in rights %}<th>{{ label }}</th>{% endfor %}</tr></thead>
    <tbody>{% for role in matrix %}<tr{% if role.code == role_code %} class="sel"{% endif %}>
      <td><b>{{ role.name }}</b>{% if role.code == role_code %} <span class="chip info"><span class="dot"></span>you</span>{% endif %}</td>
      {% for codename, on in role.cells %}<td>
        {% if is_admin and not role.locked %}
        <form method="post" action="{% url 'inventory:dia_right_toggle' %}" class="inline">{% csrf_token %}
          <input type="hidden" name="role" value="{{ role.code }}"><input type="hidden" name="right" value="{{ codename }}">
          <input type="hidden" name="on" value="{% if on %}0{% else %}1{% endif %}">
          <button class="chip {% if on %}good{% endif %}" style="cursor:pointer">{% if on %}<span class="dot"></span>yes{% else %}<span class="dot" style="background:var(--muted)"></span>no{% endif %}</button>
        </form>
        {% elif on %}<span class="chip good"><span class="dot"></span>yes</span>
        {% else %}<span class="chip"><span class="dot" style="background:var(--muted)"></span>no</span>{% endif %}
      </td>{% endfor %}
    </tr>{% endfor %}</tbody></table></div>
</div>

<div class="card" id="suppliers" style="margin-bottom:14px">
  <div class="card-h"><span class="card-t">Suppliers</span><span class="spacer"></span>
    <details class="inline"><summary class="btn sm pri">＋ Add supplier</summary>
      <form method="post" action="{% url 'inventory:dia_supplier_save' %}" class="ctrow" style="margin-top:8px">{% csrf_token %}
        <input class="inp mono" name="code" placeholder="Code" style="width:90px" required>
        <input class="inp" name="name" placeholder="Supplier" style="width:180px" required>
        <input class="inp" name="city" placeholder="City" style="width:120px">
        <input class="inp" name="terms" placeholder="Terms" style="width:110px">
        <button class="btn pri">Save</button></form></details></div>
  <div class="card-b"><table class="pt">
    <thead><tr><th>Supplier</th><th>City</th><th>Terms</th><th class="r">Purchases</th><th>Actions</th></tr></thead>
    <tbody>{% for v, n in suppliers %}<tr>
      <td><b>{{ v.name }}</b> <span class="hint mono">{{ v.code }}</span></td><td>{{ v.city|default:"—" }}</td><td>{{ v.terms|default:"—" }}</td>
      <td class="r">{{ n }}</td>
      <td><details><summary class="btn sm gho">Edit</summary>
        <form method="post" action="{% url 'inventory:dia_supplier_save' %}" class="ctrow" style="margin-top:6px">{% csrf_token %}
          <input type="hidden" name="pk" value="{{ v.pk }}">
          <input class="inp mono" name="code" value="{{ v.code }}" style="width:90px" required>
          <input class="inp" name="name" value="{{ v.name }}" style="width:170px" required>
          <input class="inp" name="city" value="{{ v.city|default:'' }}" style="width:110px">
          <input class="inp" name="terms" value="{{ v.terms }}" style="width:100px">
          <button class="btn pri">Save</button></form></details></td>
    </tr>{% empty %}<tr><td colspan="5" class="hint">No suppliers yet.</td></tr>{% endfor %}</tbody></table></div>
</div>

{% for kind, title, items in cards %}
<div class="card" id="{{ kind }}" style="margin-bottom:14px">
  <div class="card-h"><span class="card-t">{{ title }}</span><span class="spacer"></span>
    <span class="hint">{{ items|length }} values</span>
    <details class="inline"><summary class="btn sm pri">＋ Add</summary>
      <form method="post" action="{% url 'inventory:dia_term_add' %}" class="ctrow" style="margin-top:8px">{% csrf_token %}
        <input type="hidden" name="kind" value="{{ kind }}"><input class="inp" name="value" required style="width:180px">
        <button class="btn pri">Add</button></form></details></div>
  <div class="card-b"><table class="pt">
    <thead><tr><th>Value</th><th>In use</th><th class="r">Carats</th><th>Actions</th></tr></thead>
    <tbody>{% for item in items %}<tr>
      <td>{% if item.bad %}<span class="chip warn"><span class="dot"></span>{{ item.term.value }}</span>{% else %}<b>{{ item.term.value }}</b>{% endif %}</td>
      <td>{% if item.n %}{{ item.n }} line{{ item.n|pluralize }}{% else %}<span class="hint">unused</span>{% endif %}</td>
      <td class="r">{% if item.ct %}{{ item.ct|ct }}{% else %}—{% endif %}</td>
      <td><details class="inline"><summary class="btn sm gho">Rename</summary>
          <form method="post" action="{% url 'inventory:dia_term_rename' item.term.pk %}" class="ctrow" style="margin-top:6px">{% csrf_token %}
            <input class="inp" name="value" value="{{ item.term.value }}" style="width:160px" required><button class="btn pri">Save</button></form></details>
        {% if item.n %}<span class="hint" style="margin-left:6px">in use</span>
        {% else %}<form method="post" action="{% url 'inventory:dia_term_delete' item.term.pk %}" class="inline">{% csrf_token %}<button class="btn sm gho">Delete</button></form>{% endif %}</td>
    </tr>{% endfor %}</tbody></table></div>
</div>
{% endfor %}

<div class="card" id="codes" style="margin-bottom:14px">
  <div class="card-h"><span class="card-t">Item codes</span><span class="spacer"></span><span class="hint">{{ codes|length }} codes</span></div>
  <div class="card-b" style="overflow:auto"><table class="pt">
    <thead><tr><th>Code</th><th>Shape</th><th>Colour</th><th>Clarity</th><th>Read</th><th class="r">Lines</th><th>Actions</th></tr></thead>
    <tbody>{% for c, n in codes %}<tr>
      <td class="mono"><b>{{ c.item_code }}</b></td><td>{{ c.shape|default:"—" }}</td><td>{{ c.colour|default:"—" }}</td><td>{{ c.clarity|default:"—" }}</td>
      <td>{% if c.confirmed %}<span class="chip good"><span class="dot"></span>clean</span>{% else %}<span class="chip warn"><span class="dot"></span>{{ c.note|default:"unconfirmed" }}</span>{% endif %}</td>
      <td class="r">{{ n }}</td>
      <td><details><summary class="btn sm gho">Edit</summary>
        <form method="post" action="{% url 'inventory:dia_code_save' c.item_code %}" class="ctrow" style="margin-top:6px">{% csrf_token %}
          <select class="inp" name="shape" style="width:150px"><option value="">—</option>{% for t in terms_of.shape %}<option value="{{ t.pk }}"{% if t.pk == c.shape_id %} selected{% endif %}>{{ t.value }}</option>{% endfor %}</select>
          <select class="inp" name="colour" style="width:120px"><option value="">—</option>{% for t in terms_of.colour %}<option value="{{ t.pk }}"{% if t.pk == c.colour_id %} selected{% endif %}>{{ t.value }}</option>{% endfor %}</select>
          <select class="inp" name="clarity" style="width:110px"><option value="">—</option>{% for t in terms_of.clarity %}<option value="{{ t.pk }}"{% if t.pk == c.clarity_id %} selected{% endif %}>{{ t.value }}</option>{% endfor %}</select>
          <label class="hint"><input type="checkbox" name="confirmed" value="1"{% if c.confirmed %} checked{% endif %}> confirmed</label>
          <input class="inp" name="note" value="{{ c.note }}" placeholder="note" style="width:160px">
          <button class="btn pri">Save</button></form></details></td>
    </tr>{% endfor %}</tbody></table></div>
</div>

<div class="card" id="rates" style="margin-bottom:14px">
  <div class="card-h"><span class="card-t">Rate card</span><span class="spacer"></span>
    {% if can_rate %}<form method="post" enctype="multipart/form-data" action="{% url 'inventory:dia_rates_ivy' %}" class="inline">{% csrf_token %}
      <label class="btn sm upload">Load rates from IVY export<input type="file" name="workbook" accept=".xlsx" onchange="this.form.requestSubmit()"></label></form>{% endif %}</div>
  <div class="card-b" style="overflow:auto"><table class="pt">
    <thead><tr><th>Code</th><th>Size</th><th class="r">Cost / ct</th><th class="r">Sale / ct</th><th>From</th></tr></thead>
    <tbody>{% for r in rates %}<tr><td class="mono">{{ r.code }}</td><td class="mono">{{ r.size_text|default:"any size" }}</td>
      <td class="r">{% if 'cost_rate' in r %}{{ r.cost_rate|rupees }}{% else %}<span class="hint">hidden</span>{% endif %}</td>
      <td class="r">{% if 'sale_rate' in r %}{{ r.sale_rate|rupees }}{% else %}<span class="hint">hidden</span>{% endif %}</td>
      <td>{{ r.effective_from|date:"d M Y" }}</td></tr>{% empty %}<tr><td colspan="5" class="hint">No rates yet.</td></tr>{% endfor %}</tbody></table>
    {% if can_rate %}<form method="post" action="{% url 'inventory:dia_rate_save' %}" class="ctrow" style="margin-top:10px">{% csrf_token %}
      <select class="inp mono" name="code" style="width:170px" required>{% for c, n in codes %}<option>{{ c.item_code }}</option>{% endfor %}</select>
      <input class="inp mono" name="size_text" placeholder="size (blank = any)" style="width:140px">
      <input class="inp tnum" name="cost_rate" placeholder="cost / ct" style="width:110px">
      <input class="inp tnum" name="sale_rate" placeholder="sale / ct" style="width:110px">
      <input class="inp" type="date" name="effective_from" value="{{ today|date:'Y-m-d' }}" style="width:150px">
      <button class="btn pri">Set rate</button></form>{% endif %}
  </div>
</div>

<div class="card" id="expansion">
  <div class="card-h"><span class="card-t">Range → grade expansion</span></div>
  <div class="card-b"><table class="pt">
    <thead><tr><th>Range</th><th>Expands to</th><th>Correct it</th></tr></thead>
    <tbody>{% for t in expansions %}<tr>
      <td class="mono"><b>{{ t.value }}</b></td>
      <td>{% if t.expands_to %}{{ t.grades|join:" · " }}{% else %}<span class="chip crit"><span class="dot"></span>unresolved</span>{% endif %}</td>
      <td><form method="post" action="{% url 'inventory:dia_expansion' t.pk %}" class="ctrow">{% csrf_token %}
        <input class="inp" name="grades" value="{{ t.expands_to }}" style="max-width:230px"><button class="btn sm">Save</button></form></td>
    </tr>{% endfor %}</tbody></table></div>
</div>
{% endif %}
{% endblock %}
```

`role_code` and `role_name` come from the existing `accounts` context processor.

Add to the compat block of `static/css/inventory.css`:

```css
details.inline{display:inline-block}
details summary{list-style:none;cursor:pointer}
details summary::-webkit-details-marker{display:none}
button.chip{font:inherit;font-size:11px}
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest inventory -q` — Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add inventory static/css/inventory.css
git commit -m "Diamond Settings: rights, suppliers, master lists, codes, rates, expansions"
```

---

### Task 10: The diamond import screens

**Files:**
- Create: `inventory/views_dia_import.py`, `inventory/templates/inventory/diamonds/import_home.html`, `inventory/templates/inventory/diamonds/import_review.html`, `inventory/tests/test_dia_import_views.py`
- Modify: `inventory/urls.py` (replace the `dia_import_home` placeholder, add review and commit)

**Interfaces:**
- Consumes: `diamonds.parse/header_problems`, `dia_plan.analyse/read_decisions/commit`, `views_diamonds.dia_page`, `stock.views._store_workbook/_batch_workbook`, `stock.models.ImportBatch`.
- Produces: URL names `inventory:dia_import_home`, `inventory:dia_import_review` (`batch_id`), `inventory:dia_import_commit` (`batch_id`).

- [ ] **Step 1: Write the failing test**

`inventory/tests/test_dia_import_views.py`:

```python
import pytest
from django.urls import reverse

from inventory import dia_seed
from inventory.models import DiamondLine, DiamondTerm
from inventory.tests.fixtures_diamonds import build_workbook

pytestmark = pytest.mark.django_db


@pytest.fixture
def bucket(monkeypatch):
    from mediahub import storage

    book = build_workbook().getvalue()
    monkeypatch.setattr(storage, "put_bytes", lambda key, data, mime: None)
    monkeypatch.setattr(storage, "get_bytes", lambda key: book)
    return book


def test_upload_review_commit(client, admin_user_, bucket):
    from django.core.files.uploadedfile import SimpleUploadedFile

    dia_seed.load(DiamondTerm)
    client.force_login(admin_user_)
    upload = SimpleUploadedFile("DIAMOND 31.xlsx", bucket,
                                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    review = client.post(reverse("inventory:dia_import_home"), {"workbook": upload})
    assert review.status_code == 302
    body = client.get(review["Location"]).content.decode()
    assert "DTRLC VS-SI" in body and "? LC" in body               # a new code waiting for review
    batch_id = int(review["Location"].rstrip("/").split("/")[-1])
    client.post(reverse("inventory:dia_import_commit", args=[batch_id]))
    assert DiamondLine.objects.count() == 6
    again = client.post(reverse("inventory:dia_import_commit", args=[batch_id]), follow=True)
    assert "already been committed" in again.content.decode()


def test_the_importer_is_closed_without_inv_masters(client, sales_user):
    client.force_login(sales_user)
    assert client.get(reverse("inventory:dia_import_home")).status_code == 403
    assert client.post(reverse("inventory:dia_import_commit", args=[1])).status_code == 403
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/pytest inventory/tests/test_dia_import_views.py -v` — Expected: FAIL (placeholder route).

- [ ] **Step 3: Write `inventory/views_dia_import.py`**

```python
"""Upload → review → commit for the diamond register, the stones importer's shape."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.capabilities import INV_MASTERS
from stock.models import ImportBatch
from stock.services import ServiceError
from stock.views import _batch_workbook, _store_workbook

from .importers import dia_plan, diamonds
from .models import DiamondTerm
from .views_diamonds import dia_page

SOURCE = "DIAMONDS"


@login_required
@permission_required(INV_MASTERS, raise_exception=True)
def import_home(request):
    if request.method == "POST":
        upload = request.FILES.get("workbook")
        if upload is None:
            messages.error(request, "Choose a workbook first.")
            return redirect("inventory:dia_import_home")
        problems = diamonds.header_problems(upload)
        if problems:
            messages.error(request, f"That is not the diamond register. {problems[0]}")
            return redirect("inventory:dia_import_home")
        upload.seek(0)
        try:
            asset = _store_workbook(upload, request.user)
        except Exception as error:
            messages.error(request, f"Could not store the file. {error}")
            return redirect("inventory:dia_import_home")
        batch = ImportBatch.objects.create(media=asset, source=SOURCE, created_by=request.user,
                                           status=ImportBatch.Status.REVIEWING)
        return redirect("inventory:dia_import_review", batch_id=batch.pk)
    recent = ImportBatch.objects.filter(source=SOURCE).select_related("media")[:10]
    return dia_page(request, "inventory/diamonds/import_home.html", dtab="import", recent=recent)


@login_required
@permission_required(INV_MASTERS, raise_exception=True)
def import_review(request, batch_id):
    batch = get_object_or_404(ImportBatch, pk=batch_id, source=SOURCE)
    rows = diamonds.parse(_batch_workbook(batch))
    plan = dia_plan.analyse(rows, batch.decisions)
    if request.method == "POST" and batch.status == ImportBatch.Status.REVIEWING:
        batch.decisions = dia_plan.read_decisions(request.POST, plan, batch.decisions)
        batch.save(update_fields=["decisions"])
        return redirect("inventory:dia_import_review", batch_id=batch.pk)
    terms = {kind: list(DiamondTerm.objects.filter(kind=kind).values_list("value", flat=True))
             for kind in (DiamondTerm.SHAPE, DiamondTerm.COLOUR, DiamondTerm.CLARITY)}
    return dia_page(request, "inventory/diamonds/import_review.html", dtab="import", batch=batch, plan=plan,
                    counts=plan.counts(), blocked=[i for i in plan.items if i.problem and i.action != "skip"],
                    recounts=[i for i in plan.items if i.recount], terms=terms)


@login_required
@permission_required(INV_MASTERS, raise_exception=True)
@require_POST
def import_commit(request, batch_id):
    batch = get_object_or_404(ImportBatch, pk=batch_id, source=SOURCE)
    claimable = [ImportBatch.Status.REVIEWING, ImportBatch.Status.FAILED]
    if not ImportBatch.objects.filter(pk=batch.pk, status__in=claimable).update(status=ImportBatch.Status.COMMITTING):
        messages.error(request, "That import has already been committed, or is being committed now.")
        return redirect("inventory:dia_import_review", batch_id=batch.pk)
    try:
        plan = dia_plan.analyse(diamonds.parse(_batch_workbook(batch)), batch.decisions)
        result = dia_plan.commit(plan, request.user, import_batch=batch)
    except ServiceError as error:
        batch.save(update_fields=["status"])        # back to what it was: rows still need deciding
        messages.error(request, error.messages[0])
        return redirect("inventory:dia_import_review", batch_id=batch.pk)
    except Exception as error:  # the transaction has already rolled back
        batch.status, batch.result = ImportBatch.Status.FAILED, {"error": str(error)}
        batch.save(update_fields=["status", "result"])
        messages.error(request, f"Import failed, nothing was written. {error}")
        return redirect("inventory:dia_import_review", batch_id=batch.pk)
    batch.status, batch.result, batch.finished_at = ImportBatch.Status.DONE, result, timezone.now()
    batch.save(update_fields=["status", "result", "finished_at"])
    messages.success(request, f"Imported: {result['created']} new, {result['updated']} updated, "
                              f"{result['recounted']} recounted, {result['zeroed']} set to zero, "
                              f"{result['codes']} new codes.")
    return redirect("inventory:diamonds")
```

In `inventory/urls.py`, import and replace the placeholder:

```python
from . import views_dia_import
```

```python
    path("diamonds/import/", views_dia_import.import_home, name="dia_import_home"),
    path("diamonds/import/<int:batch_id>/", views_dia_import.import_review, name="dia_import_review"),
    path("diamonds/import/<int:batch_id>/commit/", views_dia_import.import_commit, name="dia_import_commit"),
```

- [ ] **Step 4: Write the templates**

`inventory/templates/inventory/diamonds/import_home.html`:

```django
{% extends "inventory_base.html" %}
{% block title %}Import diamonds{% endblock %}
{% block crumb %}<b>Diamonds</b> &nbsp;›&nbsp; Import{% endblock %}
{% block content %}
<div class="shelfbar"><h1>Import diamonds</h1></div>
<div class="card" style="max-width:640px"><div class="card-h"><span class="card-t">Diamond register</span></div>
  <div class="card-b"><form method="post" enctype="multipart/form-data">{% csrf_token %}
    <div class="fld"><label>Workbook (.xlsx) — the DIAMOND pivot</label>
      <input class="inp" type="file" name="workbook" accept=".xlsx" required></div>
    <button class="btn pri">Upload and review</button></form></div></div>
{% if recent %}
<div class="card" style="margin-top:14px;max-width:640px;overflow:hidden"><div class="card-h"><span class="card-t">Recent imports</span></div>
  <table class="pt"><thead><tr><th>#</th><th>File</th><th>Status</th><th>When</th></tr></thead>
    <tbody>{% for b in recent %}<tr onclick="location.href='{% url 'inventory:dia_import_review' b.pk %}'">
      <td class="bn"><a class="rowlink" href="{% url 'inventory:dia_import_review' b.pk %}">{{ b.pk }}</a></td>
      <td>{{ b.media.file_name }}</td><td>{{ b.get_status_display }}</td><td>{{ b.created_at|date:"d M Y H:i" }}</td></tr>{% endfor %}</tbody></table></div>
{% endif %}
{% endblock %}
```

`inventory/templates/inventory/diamonds/import_review.html`:

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Diamond import #{{ batch.pk }}{% endblock %}
{% block crumb %}<b>Diamonds</b> &nbsp;›&nbsp; Import #{{ batch.pk }}{% endblock %}
{% block content %}
<div class="shelfbar"><h1>Review import #{{ batch.pk }}</h1><span class="spacer"></span>
  <a class="btn gho" href="{% url 'inventory:dia_import_home' %}">← Imports</a></div>

<div class="totstrip">
  <div class="tot heroTot"><div class="l">Rows read</div><div class="v">{{ counts.rows|grouped }}</div>
    <div class="f">{{ counts.new }} new · {{ counts.update }} already here · {{ counts.skip }} skipped</div></div>
  <div class="tot"><div class="l">Blocked</div><div class="v">{{ counts.blocked }}</div><div class="f">need a decision before commit</div></div>
  <div class="tot"><div class="l">New item codes</div><div class="v">{{ counts.codes }}</div><div class="f">created as reviewed below</div></div>
  <div class="tot"><div class="l">Recounts</div><div class="v">{{ counts.recount }}</div><div class="f">{{ counts.missing }} lines not in this file</div></div>
</div>

{% if batch.status == 'DONE' %}
<div class="banner"><div class="banner-ic">✓</div><div><h4>Imported {{ batch.finished_at|date:"d M Y H:i" }}</h4>
  <p>{{ batch.result.created }} new · {{ batch.result.updated }} updated · {{ batch.result.recounted }} recounted · {{ batch.result.zeroed }} set to zero · {{ batch.result.codes }} new codes</p></div></div>
{% else %}
<form method="post">{% csrf_token %}
{% if plan.codes %}
<div class="card" style="overflow:hidden;margin-bottom:14px"><div class="card-h"><span class="card-t">New item codes</span><span class="spacer"></span><button class="btn">Save decisions</button></div>
  <div style="overflow:auto"><table class="pt">
    <thead><tr><th>Code</th><th>Shape</th><th>Colour</th><th>Clarity</th><th>Confirmed</th><th>Read</th></tr></thead>
    <tbody>{% for c in plan.codes %}<tr class="{% if not c.confirmed %}sel{% endif %}">
      <td class="mono"><b>{{ c.item_code }}</b></td>
      <td><input class="inp" name="code:{{ c.item_code }}:shape" value="{{ c.shape }}" list="dl-shape" style="width:150px"></td>
      <td><input class="inp" name="code:{{ c.item_code }}:colour" value="{{ c.colour }}" list="dl-colour" style="width:110px"></td>
      <td><input class="inp" name="code:{{ c.item_code }}:clarity" value="{{ c.clarity }}" list="dl-clarity" style="width:100px"></td>
      <td><input type="checkbox" name="code:{{ c.item_code }}:confirmed" value="1"{% if c.confirmed %} checked{% endif %}></td>
      <td>{% if c.note %}<span class="chip warn"><span class="dot"></span>{{ c.note }}</span>{% else %}<span class="chip good"><span class="dot"></span>clean</span>{% endif %}</td>
    </tr>{% endfor %}</tbody></table></div></div>
  <datalist id="dl-shape">{% for v in terms.shape %}<option value="{{ v }}">{% endfor %}</datalist>
  <datalist id="dl-colour">{% for v in terms.colour %}<option value="{{ v }}">{% endfor %}</datalist>
  <datalist id="dl-clarity">{% for v in terms.clarity %}<option value="{{ v }}">{% endfor %}</datalist>
{% endif %}

{% if blocked %}
<div class="card" style="overflow:hidden;margin-bottom:14px"><div class="card-h"><span class="card-t">Rows that need a decision</span><span class="spacer"></span><button class="btn">Save decisions</button></div>
  <table class="pt"><thead><tr><th>Row</th><th>Batch</th><th>Item code</th><th>Size</th><th class="r">Carats</th><th>Problem</th><th>Decision</th></tr></thead>
    <tbody>{% for i in blocked %}<tr class="sel">
      <td class="mono">{{ i.row.src }}</td><td class="mono">{{ i.row.batch_no|default:"—" }}</td><td class="mono">{{ i.row.item_code }}</td><td class="mono">{{ i.row.size_text }}</td>
      <td class="r">{{ i.row.ct|ct }}</td><td><span class="chip crit"><span class="dot"></span>{{ i.problem }}</span></td>
      <td><select class="inp" name="row:{{ i.row.src }}" style="width:120px"><option value="map">map to line</option><option value="new">new line</option><option value="skip">skip</option></select>
        <select class="inp mono" name="row:{{ i.row.src }}:line" style="width:130px">{% for line in i.candidates %}<option>{{ line.ref }}</option>{% endfor %}</select></td>
    </tr>{% endfor %}</tbody></table></div>
{% endif %}

{% if plan.missing %}
<div class="card" style="overflow:hidden;margin-bottom:14px"><div class="card-h"><span class="card-t">Lines in the app but not in this file</span><span class="spacer"></span><button class="btn">Save decisions</button></div>
  <table class="pt"><thead><tr><th>Line</th><th>Item code</th><th>Batch</th><th>Size</th><th>Decision</th></tr></thead>
    <tbody>{% for line, action in plan.missing %}<tr>
      <td class="mono">{{ line.ref }}</td><td class="mono">{{ line.code_id }}</td><td class="mono">{{ line.batch_no|default:"—" }}</td><td class="mono">{{ line.size_text }}</td>
      <td><select class="inp" name="missing:{{ line.ref }}" style="width:150px"><option value="keep"{% if action == 'keep' %} selected{% endif %}>leave as is</option><option value="zero"{% if action == 'zero' %} selected{% endif %}>recount to 0</option></select></td>
    </tr>{% endfor %}</tbody></table></div>
{% endif %}
</form>

{% if recounts %}
<div class="card" style="overflow:hidden;margin-bottom:14px"><div class="card-h"><span class="card-t">Recounts that will post</span></div>
  <table class="pt"><thead><tr><th>Line</th><th>Item code</th><th class="r">Carats held</th><th class="r">Carats in file</th></tr></thead>
    <tbody>{% for i in recounts %}<tr><td class="mono">{{ i.existing.ref }}</td><td class="mono">{{ i.row.item_code }}</td>
      <td class="r">{{ i.held_ct|ct }}</td><td class="r">{{ i.row.ct|ct }}</td></tr>{% endfor %}</tbody></table></div>
{% endif %}

<form method="post" action="{% url 'inventory:dia_import_commit' batch.pk %}">{% csrf_token %}
  <button class="btn pri"{% if counts.blocked %} disabled{% endif %}>Commit {{ counts.new|add:counts.update }} rows</button></form>
{% endif %}
{% endblock %}
```

The code decisions post values, not term pks: `dia_plan.commit` creates any value that is not on a list yet, so a reviewer can type a new shape name.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest inventory -q` — Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add inventory
git commit -m "Upload, review and commit the diamond register from the browser"
```

---

### Task 11: The masking walk, parity with the prototype, and the spec

**Files:**
- Modify: `inventory/tests/test_masking.py`, `docs/superpowers/specs/2026-09-30-inventory-diamonds-design.md`
- Create: `inventory/tests/test_dia_parity.py`

**Interfaces:**
- Consumes: every `inventory:` diamond URL name; the prototype's embedded `const DD` data.

- [ ] **Step 1: Extend the walk**

In `inventory/tests/test_masking.py`:

1. Import the diamond constants:

```python
from inventory.tests.conftest import DIA_COST, DIA_COST_VALUE, DIA_SALE, DIA_SALE_VALUE, DIA_SUPPLIER, SUPPLIER, VALUE
```

2. Add the diamond screens and exemptions:

```python
DIAMOND_SCREENS = [
    ("inventory:diamonds", ""),
    ("inventory:diamonds", "?cat=Natural+Diamond"),
    ("inventory:dia_settings", ""),
]
```

```python
EXEMPT = {
    "inventory:set_view", "inventory:pouch_save", "inventory:pouch_price", "inventory:pouch_photos", "inventory:photo",
    "inventory:import_home", "inventory:import_review", "inventory:import_commit",
    # diamond writes: POST-only and gated on inv_masters (or admin), asserted in test_dia_settings
    "inventory:dia_term_add", "inventory:dia_term_rename", "inventory:dia_term_delete", "inventory:dia_expansion",
    "inventory:dia_code_save", "inventory:dia_rate_save", "inventory:dia_rates_ivy", "inventory:dia_supplier_save",
    "inventory:dia_right_toggle",
    # gated whole on inv_masters, asserted in test_dia_import_views
    "inventory:dia_import_home", "inventory:dia_import_review", "inventory:dia_import_commit",
}
```

3. Add the diamond walk:

```python
@pytest.mark.parametrize("fixture, secrets", [
    ("sales_user", (DIA_COST, DIA_COST_VALUE, DIA_SUPPLIER)),
    ("karigar_user", (DIA_COST, DIA_COST_VALUE, DIA_SALE, DIA_SALE_VALUE, DIA_SUPPLIER)),
    ("graphic_user", (DIA_COST, DIA_COST_VALUE, DIA_SALE, DIA_SALE_VALUE, DIA_SUPPLIER)),
])
def test_no_diamond_money_reaches_a_login_without_the_right(client, diamonds, request, fixture, secrets):
    client.force_login(request.getfixturevalue(fixture))
    for name, query in DIAMOND_SCREENS:
        response = client.get(reverse(name) + query)
        assert response.status_code == 200, f"{name} returned {response.status_code}"
        body = response.content.decode()
        for secret in secrets:
            assert secret not in body, f"{name}{query} leaked {secret!r} to {fixture}"


def test_accounts_sees_diamond_money(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert DIA_COST in body and DIA_COST_VALUE in body and DIA_SALE_VALUE in body
    assert DIA_SUPPLIER in client.get(reverse("inventory:dia_settings")).content.decode()


def test_an_admin_preview_masks_like_the_role(client, admin_user_, diamonds):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:diamonds"), {"as": "KARIGAR"}).content.decode()
    for secret in (DIA_COST, DIA_SALE, DIA_SALE_VALUE):
        assert secret not in body
```

4. In `test_every_inventory_screen_is_walked`, count the diamond screens as covered:

```python
    covered = {name for name, _, _ in SCREENS} | {name for name, _ in DIAMOND_SCREENS}
```

- [ ] **Step 2: Run the walk**

Run: `.venv/bin/pytest inventory/tests/test_masking.py -v` — Expected: PASS. A leak failure names the screen and value: fix the template with a key test, never a capability test. The Settings page is refused for SALES/KARIGAR/GRAPHIC (no `inv_masters`), so it returns 200 with the "Not permitted" banner and no money.

- [ ] **Step 3: Write the parity test**

`inventory/tests/test_dia_parity.py`:

```python
"""The diamond port reproduces the prototype's own diamond figures.

The prototype's embedded data (``const DD``: 348 lines as the owner has seen
them) is rebuilt into a register in file order, imported through the real
importer, and must land on the prototype's counts and carats. Read from beside
the repo; skipped when absent, so no stock figures are committed.
"""
import io
import json
from collections import defaultdict
from decimal import Decimal

import pytest
from django.conf import settings
from openpyxl import Workbook

from inventory import dia_seed, dia_services
from inventory.importers import dia_plan, diamonds
from inventory.models import DiamondCode, DiamondTerm

pytestmark = [pytest.mark.django_db, pytest.mark.golden]

PROTOTYPE = settings.BASE_DIR.parent / "Nornament_Inventory" / "01-prototype" / "nornament-ui-mockup.html"
RAW_CATEGORY = {name: raw for raw, name in diamonds.CATEGORY_NAMES.items()}


def _prototype_rows():
    if not PROTOTYPE.exists():
        pytest.skip(f"{PROTOTYPE} is not beside the repo")
    for line in PROTOTYPE.read_text().splitlines():
        if line.startswith("const DD = "):
            return json.loads(line[len("const DD = "):].rstrip().rstrip(";"))["rows"]
    pytest.fail("no const DD in the prototype")


def _register(rows):
    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet"
    sheet.append(["Raw Material", "Batch No", "Item Code", "", "Size", "Weight"])
    for r in rows:
        sheet.append([RAW_CATEGORY[r["cat"]], r["batch"] or None, r["item"], None, r["size"], r["wt"]])
    buffer = io.BytesIO()
    book.save(buffer)
    buffer.seek(0)
    return buffer


def test_the_diamonds_match_the_prototype(admin_user_):
    dia_seed.load(DiamondTerm)
    plan = dia_plan.analyse(diamonds.parse(_register(_prototype_rows())))
    assert plan.counts()["blocked"] == 0
    dia_plan.commit(plan, admin_user_)

    lines = list(dia_services.stocked_lines())
    assert len(lines) == 348
    assert sum(line.on_ct for line in lines) == Decimal("673.90")
    assert len({line.batch_no for line in lines if line.batch_no}) == 270
    assert DiamondCode.objects.count() == 84

    by_cat, by_band = defaultdict(lambda: [0, Decimal("0")]), defaultdict(lambda: [0, Decimal("0")])
    for line in lines:
        by_cat[line.category.value][0] += 1
        by_cat[line.category.value][1] += line.on_ct
        by_band[line.band.value][0] += 1
        by_band[line.band.value][1] += line.on_ct
    assert {k: (n, ct) for k, (n, ct) in by_cat.items()} == {
        "Natural Diamond": (329, Decimal("563.20")), "Foil Polki": (10, Decimal("105.58")),
        "HPHT Lab Grown": (5, Decimal("2.81")), "Solitaire": (3, Decimal("2.26")),
        "Lab Grown (CVD?)": (1, Decimal("0.05")),
    }
    assert {k: (n, ct) for k, (n, ct) in by_band.items()} == {
        "-2": (118, Decimal("445.69")), "+2-6": (46, Decimal("21.11")), "+6-11": (73, Decimal("71.22")),
        "11-20": (31, Decimal("17.63")), "20+": (9, Decimal("67.85")), "carat band": (71, Decimal("50.40")),
    }
```

- [ ] **Step 4: Run it**

Run: `.venv/bin/pytest inventory/tests/test_dia_parity.py -v` — Expected: PASS. If a count disagrees, compare `dia_rules.size_band` and `importers/diamonds.parse` with `build_dia.py` line by line. Never edit the expected numbers — they are the prototype's.

- [ ] **Step 5: Record the planning decisions in the spec**

Append to `docs/superpowers/specs/2026-09-30-inventory-diamonds-design.md`:

```markdown
## Changed while planning

- **Category belongs to the line.** The prototype takes each line's category from column A of its row, so `DiamondLine.category` holds it; `DiamondCode` holds shape, colour and clarity.
- **A line can carry a shape override** (`DiamondLine.shape_override`): when a code names no shape and the size is a carat band with a shape prefix (`TR 0.20-0.24`), the shape comes from the size, as in the prototype.
- **Carat-band size prefixes read the IVY way too:** `PR` = Pear, `PC` = Princess.
- **A single leftover ladder letter is a colour grade** (`DTBG` → colour G, `SOMG` → Marquise G), as the prototype read it, but the code stays unconfirmed.
- **Setting a rate needs both `view_cost` and `view_sale`**, because one rate row carries both.
- **The band list is seeded with `?`** for a size that fits no band.
- **Diamond parity** is `inventory/tests/test_dia_parity.py` (marked `golden`): the prototype's `const DD` rebuilt in file order and imported must give 348 lines, 673.90 ct, 270 batches, 84 codes and the prototype's category and band totals.
```

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/pytest -q` — Expected: only the known pre-existing S3 failure.
Run: `.venv/bin/python manage.py makemigrations --check --dry-run` — Expected: `No changes detected`.

- [ ] **Step 7: Commit**

```bash
git add inventory/tests/test_masking.py inventory/tests/test_dia_parity.py docs/superpowers/specs/2026-09-30-inventory-diamonds-design.md
git commit -m "Walk the diamond screens as every role, and prove the diamonds match the prototype"
```
