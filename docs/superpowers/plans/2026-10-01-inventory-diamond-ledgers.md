# Inventory Part 4 (Diamond Ledgers) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the prototype's three diamond ledgers work: **Job cards**, **Assortments** and **Purchases**. They run on part 2's document and ledger engine, and a diamond line's own cost per carat (set by its purchase, carried through an assortment) wins over the rate card everywhere a cost or value is read.

**Architecture:** One engine, extended rather than copied. `inventory/ledger.py` learns that a movement's owner is a `Pouch` **or** a `DiamondLine`: its `Line`, its checks (a diamond line moves by carats, pieces optional and unchecked), its locking, outstanding, reversal and undo work for either. A job card closes only by hand and only at zero (`close_document`). Three new document kinds (`dia_job`, `dia_assort`, `dia_purchase`) are never listed on a stones screen. A new `DiamondLineCost` table holds a line's own cost; `dia_services.stocked_lines` annotates it and `dia_services.price` reads it first. Services per ledger sit in their own modules (`ledger_dia_jobs`, `ledger_dia_assort`, `ledger_dia_purchase`); views are thin, one per screen, built through `views_diamonds.viewer()` so the "Viewing as" preview masks like the role; rows end in `stock.masking.mask`.

**Tech Stack:** Django 5.2, Postgres 17, pytest + pytest-django, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-01-inventory-diamond-ledgers-design.md` (binding). Part 2: `2026-10-01-inventory-stones-ledger-design.md`, including its "Changed while planning" and "Owner rulings and review fixes". Part 3: `2026-09-30-inventory-diamonds-design.md`. Precedent plan: `docs/superpowers/plans/2026-10-01-inventory-stones-ledger.md`.

**Prototype source (read, never edit):** `../Nornament_Inventory/04-source-scripts/_script.html`. The three screens are `diaJob` 852–931, `diaAssort` 933–1013 and `diaPurchase` 1015–1078. `renderDia` 1179–1188 holds the sub-tabs, and the Search buttons are at 810–812. The diamond rail is in `_head.html` 465–471. Line N there is mockup line N+576. The CSS these screens need is already in `static/css/inventory.css`: `.dbanner`, `.filterbar`, `.fsel`, `.ro2`, `.led`, `.ledtot`, `.chal`, `.chip`, `.banner`, `.tx-cols`, `.two`, `.fld`, `.unit`, `.cons`, `.pt`, `.grp-t`, `.dsub`, `.ctrow`, `.inline`, `.card`, `.btn`, `.hint`, `.mono`, `.tnum`, `.r`. `.bal` is the prototype's class name on balance cells and carries no rule, which is fine.

## Global Constraints

- **Standalone rule:** add no new dependency on stock or CRM data. Part 2's ties stay as they are: karigars and suppliers are `stock.Vendor`, and customers come from `crm.Customer`. That customer tie is the owner's one exception of 2026-10-01, and this part uses no customers. Reuse, do not duplicate: `stock.services.ServiceError/require/log`, `stock.masking.mask/allowed`, `inventory.dia_services.save_supplier`, `ledger_jobs.karigar_choices`, `ledger_purchase.PurchaseHeader/PURCHASE_RIGHTS`, `views_diamonds.viewer/dia_page/PreviewUser`, `inputs.*`.
- **Masking:** rows are built once and end in `stock.masking.mask()`. Templates test **key presence** (`{% if 'karigar_name' in card %}`), never capabilities, for anything money- or name-shaped. The gated keys used here are `karigar_name` (inv_job), `vendor_name` (view_vendor), and `cost_rate` and `cost_amount` (view_cost). Job cards show no money. Action buttons and forms may test `caps.*` or a view flag, which is part 1's precedent for actions. A template never prints `doc.vendor` directly. A karigar the viewer may not see must never read as "In-house": `in_house` is its own key, true only when the card has no vendor.
- **"Viewing as":** every diamond ledger page is built for `viewer(request)`. For an admin with `?as=ROLE` that is a `PreviewUser` holding exactly that role's rights; for everyone else it is the real login. The page renders as that role, read-only or "Not permitted". Every form is hidden while previewing (`user is not request.user`), and every POST acts as the real login.
- **Errors:** every refusal is a `ServiceError` with a plain message. It shows on the form it came from: the assortment and purchase forms re-render with what was typed, and the job-card actions redirect back with a message. A missing right is `PermissionDenied` from `require` (403). Each POST view calls `require` for its right **before** reading the form, so a login without the right gets 403, never a form error.
- **One transaction per post, document locked first:** every service that writes is `@transaction.atomic`. `ledger.post` locks and re-reads the document, then locks the pouches or lines, and writes all of a document's movements or none. A new code, a new line, a new supplier or a cost row is created inside the same transaction as its post, so a refusal leaves nothing behind.
- **Views never write models.** Writes live in `inventory/ledger*.py` and `inventory/dia_services.py`.
- **Shell:** every screen extends `templates/inventory_base.html`: part 1's shell, CSS, dark mode and phone drawer. Diamond pages render through `views_diamonds.dia_page` (diamond rail, sub-tabs, no client toggle). Use only the existing classes in `static/css/inventory.css`; add no CSS. Wide tables sit in `<div style="overflow:auto">`. Never put `hidden` on an element whose class sets `display` (`.two`, `.banner`, `.btn`); wrap it in a plain `<div>` and hide that.
- **Prose stripped:** no explainer `<p>` from the prototype. That covers the dbanner paragraphs, "Debit = out to the karigar…", "Same ledger idea…", "There is no separate…" and "Suppliers are maintained in Settings…". Its labels, headings, chips, functional warnings and the "What posting will do" card stay.
- **Diamonds have no client view.** The diamond pages ignore the stones' Internal / Client session flag, as Search already does.
- **Numbers:** typed quantities and rates are read by `inputs.decimal/whole/day`, which allow at most 4 decimal places and refuse anything more, never rounding. Typed text is checked against its column by `inputs.fits`, which `ledger.open_document`, `ledger._check` (ref) and `dia_services.new_line`/`code_for` already call, and the inputs carry `maxlength`. Refusal messages print carats with `ledger._ct`: up to 4 places, trailing zeros trimmed.
- **Stones stay as they are:** every part 2 stones test (`inventory/tests/test_ledger*.py`, `test_document_view.py`, `test_record_movement.py`, `test_purchase_view.py`, `test_assort_views.py`, `test_movements.py`, `test_inputs.py`, `test_masking.py`) passes **unchanged** after every task. No task edits those test files except `test_masking.py`, which only gains entries. A stones failure is a bug in the change, never in the test.
- **Diamonds stay as they are:** the real diamond file test (`test_dia_real_file.py`: 281 lines, 546.96 ct, cost ₹1,47,98,794 ± ₹10) and the prototype parity test (`test_dia_parity.py`) pass unchanged. `../Dia_Stock_Nitesh.xlsx` is beside this worktree, so the real-file test runs rather than skips.
- Still padlocked (`🔒`, never a dead link): the diamond **Movements** and **Stock take** tabs. Assortments and Purchases are padlocked in the rail and sub-tabs for a login without their rights.
- Follow the surrounding style: docstrings say *why*, and there are no type annotations except on dataclass fields.
- Only database tests carry `pytestmark = pytest.mark.django_db`. Tests use the real role fixtures in the root `conftest.py` (`admin_user_`, `accounts_user`, `sales_user`, `graphic_user`, `production_user`, `karigar_user`) and in `inventory/tests/conftest.py` (`shelf`, `diamonds`, `parties`, `ledger_docs`, and `dia_docs` from Task 10). The `diamonds` fixture gives three lines. The round line is NRD-000001: `DRFGH VS-SI`, size `+6-12`, batch `B-771`, 3.40 ct, rate card cost ₹16,517 and sale ₹21,013. The princess line is NRD-000002: `DPCEF VVS-VS`, size `+2`, 0.85 ct, no rate. The polki line is NRD-000003: `FPL`, no clarity, 43.21 ct, no rate. The supplier is Kothari Exports, Mumbai.
- Run tests from the worktree root with a **private database name** per task: `POSTGRES_DB=dialedger_tN ../nornament-app/.venv/bin/pytest <paths> -p no:warnings`. Ignore one known pre-existing environmental failure: `stock/tests/test_import_commit.py::test_images_are_attached_in_chunks_and_are_resumable` (live S3 401).
- Commit messages end with a blank line and `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|---|---|
| `inventory/models.py` (modify) | `StockDocument.Kind` gains `DIA_JOB`, `DIA_ASSORT`, `DIA_PURCHASE` (column widened to 12); `Movement.Reason` gains `RETURNED_UNUSED`, `ASSORT_OUT`, `ASSORT_IN`; new `DiamondLineCost` |
| `inventory/migrations/0008_diamond_ledgers.py` (generated) | schema |
| `inventory/dia_services.py` (modify) | `stocked_lines` annotates `own_cost`; `price` reads it first; `new_line`, `listed`, `code_for`, `sized`, `line_label`, `line_choices`, `term_values` |
| `inventory/importers/dia_plan.py` (modify) | `_sized` delegates to `dia_services.sized` (one per-stone rule) |
| `inventory/ledger.py` (modify) | `STONE_KINDS`, `DIAMOND_KINDS`, `OWED`, `CLOSABLE`; `Line.owner` is a pouch or a diamond line; every check, lock, outstanding, reversal and undo for either; `close_document` |
| `inventory/views_lists.py`, `inventory/views_documents.py` (modify) | the stones lists and document page show stones kinds only |
| `inventory/ledger_dia_jobs.py` (new) | `open_card`, `post_entry`, the six entries, `credit_choices`, `owed` |
| `inventory/ledger_jobs.py` (modify) | `karigar_choices` counts a karigar named on a diamond job card |
| `inventory/ledger_dia_assort.py` (new) | `Destination`, `post_assortment` |
| `inventory/ledger_purchase.py` (modify) | `check_header` extracted, shared with diamonds |
| `inventory/ledger_dia_purchase.py` (new) | `DiaPurchaseLine`, `post_dia_purchase` |
| `inventory/views_dia_jobs.py` (stub in Task 2, built in Task 6) | Job cards page and its five POSTs |
| `inventory/views_dia_assort.py` (stub in Task 2, built in Task 7) | Assortments page (GET and POST) and reverse |
| `inventory/views_dia_purchase.py` (stub in Task 2, built in Task 8) | Purchases page (GET and POST) and reverse |
| `inventory/urls.py` (modify, Task 2 only) | every diamond ledger route |
| `inventory/views_diamonds.py`, `inventory/dia_rows.py`, `inventory/views_dia_settings.py` (modify, Task 9) | Search's purchase right, the rail counts, the Settings supplier "Purchases" count |
| `inventory/templates/inventory/diamonds/` | `jobs.html`, `assort.html`, `purchase.html` (new); `_rail.html`, `_dsub.html`, `search.html` (modify) |
| `templates/inventory_base.html` (modify, Task 8) | the diamond **Purchase** tab |
| `inventory/tests/…` | tests per task; the `dia_docs` fixture (Task 10) |
| `docs/superpowers/specs/2026-10-01-inventory-diamond-ledgers-design.md` (Task 10) | "Changed while planning" |

## Parallel waves

| Wave | Tasks | Files each task touches |
|---|---|---|
| 1 | **1** models, line cost, stones lists | `inventory/models.py`, `inventory/migrations/0008_*`, `inventory/dia_services.py`, `inventory/importers/dia_plan.py`, `inventory/ledger.py` (constants, `owed_by_document`), `inventory/views_lists.py`, `inventory/views_documents.py`, `inventory/tests/test_dia_ledger_models.py` |
| 2 | **2** engine, reserved routes | `inventory/ledger.py` (whole file), stub `inventory/views_dia_jobs.py`, `inventory/views_dia_assort.py`, `inventory/views_dia_purchase.py`, `inventory/urls.py`, `inventory/tests/test_masking.py` (`PENDING`), `inventory/tests/test_dia_ledger.py` |
| 3 | **3, 4, 5** in parallel | 3: `inventory/ledger_dia_jobs.py`, `inventory/ledger_jobs.py` (one line), `inventory/tests/test_ledger_dia_jobs.py` · 4: `inventory/ledger_dia_assort.py`, `inventory/tests/test_ledger_dia_assort.py` · 5: `inventory/ledger_dia_purchase.py`, `inventory/ledger_purchase.py` (`check_header`), `inventory/tests/test_ledger_dia_purchase.py` |
| 4 | **6, 7, 8, 9** in parallel | 6: `inventory/views_dia_jobs.py`, `diamonds/jobs.html`, `inventory/tests/test_dia_jobs_view.py` · 7: `inventory/views_dia_assort.py`, `diamonds/assort.html`, `inventory/tests/test_dia_assort_view.py` · 8: `inventory/views_dia_purchase.py`, `diamonds/purchase.html`, `templates/inventory_base.html`, `inventory/tests/test_dia_purchase_view.py` · 9: `diamonds/_rail.html`, `diamonds/_dsub.html`, `diamonds/search.html`, `inventory/views_diamonds.py`, `inventory/dia_rows.py`, `inventory/views_dia_settings.py`, `inventory/tests/test_dia_wiring.py` |
| 5 | **10** masking walk, spec | `inventory/tests/test_masking.py`, `inventory/tests/conftest.py`, the spec |

**Why wave 4 does not fight over files.** Task 2 routes every diamond ledger URL up front to stub views, each raising `Http404`, in the three modules wave 4 fills. It also lists those names as `PENDING` in the every-screen check. So the rail, the sub-tabs, Search's buttons and the top-bar Purchase tab can `{% url %}` the screens while they are built in parallel, and no wave-4 task edits `inventory/urls.py`, `conftest.py` or `test_masking.py`. Each wave-4 task owns its own view module, template and test file. Task 8 alone owns `inventory_base.html`, and Task 9 alone owns `_rail.html`, `_dsub.html` and `search.html`. Their tests read only their own markup: Task 9 checks the tabs on Search, which `inventory_base.html` renders, but only for the two padlocks that neither task changes.

**Why wave 3 does not fight either.** Each service is its own new module. The two shared edits are one line each in files no other wave-3 task touches: Task 3 edits `ledger_jobs.karigar_choices`, and Task 5 extracts `ledger_purchase.check_header`. Wave 3's tests reach each other's services only through the engine (`ledger.open_document/post`).

---

### Task 1: Diamond document kinds, a line's own cost, the code a description finds, and stones lists that never show a diamond document

**Files:**
- Modify: `inventory/models.py`, `inventory/dia_services.py`, `inventory/importers/dia_plan.py`, `inventory/ledger.py`, `inventory/views_lists.py`, `inventory/views_documents.py`
- Create: `inventory/migrations/0008_diamond_ledgers.py` (generated), `inventory/tests/test_dia_ledger_models.py`

**Interfaces:**
- Consumes: part 2's `StockDocument`, `Movement`, `ledger.PREFIX/RIGHT_FOR_KIND/owed_by_document/out_summary`; part 3's `DiamondLine`, `DiamondCode`, `DiamondTerm`, `DiamondRate`, `dia_services.rate_table/term/_last_ref_number`, `dia_rules.size_band/canonical_code/SHAPES/COLOURS/Sized`, `dia_seed.COLOUR_LADDER`.
- Produces:
  - `StockDocument.Kind.DIA_JOB = "dia_job"` ("Job card"), `DIA_ASSORT = "dia_assort"` ("Assortment"), `DIA_PURCHASE = "dia_purchase"` ("Diamond purchase"); `StockDocument.kind` is `max_length=12`.
  - `Movement.Reason.RETURNED_UNUSED = "Returned Unused"`, `ASSORT_OUT = "Assort Out"`, `ASSORT_IN = "Assort In"`.
  - `DiamondLineCost` (`db_table inv_dia_line_cost`): `line` (FK `DiamondLine`, related_name `"costs"`), `cost_rate` (14, 4), `effective_from` (date, default today), `set_by` (FK user, null), `document` (FK `StockDocument`, null, related_name `"+"`), `created_at`. Ordering `["-effective_from", "-pk"]`.
  - `ledger.STONE_KINDS`, `ledger.DIAMOND_KINDS` (tuples of `Kind`); `ledger.PREFIX` gains `DIA_JOB: "JC-"`, `DIA_ASSORT: "AS-"`, `DIA_PURCHASE: "DP-"`; `ledger.RIGHT_FOR_KIND` gains `DIA_JOB: INV_JOB`, `DIA_ASSORT: INV_ASSORT`, `DIA_PURCHASE: INV_PURCHASE`.
  - `dia_services.stocked_lines(queryset=None)` also annotates `own_cost` (the latest `DiamondLineCost.cost_rate` effective today or earlier, else `None`).
  - `dia_services.price(line, rates) -> (cost, sale)`: cost is the line's own cost, else the rate card at its exact size, else the rate card at any size; sale comes from the rate card only. It reads `line.own_cost` when annotated, else queries.
  - `dia_services.new_line(**fields) -> DiamondLine`, with the next `NRD-` ref and no movement.
  - `dia_services.listed(kind, value) -> DiamondTerm | None`. A blank value gives `None`; a value missing from the list raises `ServiceError("{value} is not on the {kind} list; add it in Settings first.")`.
  - `dia_services.code_for(user, shape, colour, clarity) -> DiamondCode`: finds an existing code, or creates one confirmed; `clarity` may be blank only when `colour` is a Fancy colour (see Decided while planning).
  - `dia_services.sized(size_text, pcs=None, ct=None) -> dia_rules.Sized`: part 3's band, with the per-stone rule.
  - `dia_services.line_label(line) -> "NRD-000001 · DRFGH VS-SI · +6-12 · B-771"`.
  - `dia_services.line_choices(queryset=None) -> [{"pk", "label", "ct"}]` for lines with carats on hand.
  - `dia_services.term_values(kind) -> [str]`: a master list in its order, with `?` and `(` values left out.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_dia_ledger_models.py`:

```python
"""Part 4's tables and reads: the diamond document kinds, the new reasons, a line's own cost, the
code a description finds, and stones lists that never show a diamond document."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from inventory import dia_rows, dia_services, ledger
from inventory.models import DiamondCode, DiamondLineCost, DiamondTerm, Movement, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
K, R = StockDocument.Kind, Movement.Reason


def _line(pk):
    return dia_services.stocked_lines().get(pk=pk)


def _cost(line, rate, **extra):
    return DiamondLineCost.objects.create(line=line, cost_rate=D(rate), **extra)


def test_the_diamond_kinds_and_reasons_exist():
    assert (K.DIA_JOB.label, K.DIA_ASSORT.label, K.DIA_PURCHASE.label) == ("Job card", "Assortment", "Diamond purchase")
    assert (R.RETURNED_UNUSED, R.ASSORT_OUT, R.ASSORT_IN) == ("Returned Unused", "Assort Out", "Assort In")
    doc = StockDocument.objects.create(kind=K.DIA_PURCHASE, number="2026/0442")      # twelve letters fit
    assert str(doc) == "Diamond purchase 2026/0442"
    StockDocument.objects.create(kind=K.PURCHASE, number="2026/0442")                 # a stones purchase may share it
    with pytest.raises(IntegrityError), transaction.atomic():
        StockDocument.objects.create(kind=K.DIA_PURCHASE, number="2026/0442")


def test_each_diamond_kind_has_a_prefix_and_a_right():
    assert {k: ledger.PREFIX[k] for k in ledger.DIAMOND_KINDS} == {
        K.DIA_JOB: "JC-", K.DIA_ASSORT: "AS-", K.DIA_PURCHASE: "DP-"}
    assert {k: ledger.RIGHT_FOR_KIND[k] for k in ledger.DIAMOND_KINDS} == {
        K.DIA_JOB: "accounts.inv_job", K.DIA_ASSORT: "accounts.inv_assort", K.DIA_PURCHASE: "accounts.inv_purchase"}
    assert set(ledger.STONE_KINDS) | set(ledger.DIAMOND_KINDS) == set(K.values)
    assert not set(ledger.STONE_KINDS) & set(ledger.DIAMOND_KINDS)


def test_a_lines_own_cost_wins_over_the_rate_card(diamonds):
    rnd, princess = diamonds["round"], diamonds["princess"]
    rates = dia_services.rate_table()
    assert dia_services.price(_line(rnd.pk), rates) == (D("16517"), D("21013"))
    _cost(rnd, "17777")
    assert dia_services.price(_line(rnd.pk), rates) == (D("17777"), D("21013"))       # sale stays the rate card's
    assert dia_services.price(_line(princess.pk), rates) == (None, None)              # neither: "not set"
    _cost(princess, "20000")
    assert dia_services.price(_line(princess.pk), rates) == (D("20000"), None)


def test_the_latest_own_cost_wins_and_a_future_one_waits(diamonds):
    rnd, today = diamonds["round"], timezone.localdate()
    _cost(rnd, "17000", effective_from=today - timedelta(days=3))
    _cost(rnd, "17500", effective_from=today)
    _cost(rnd, "99999", effective_from=today + timedelta(days=1))
    assert _line(rnd.pk).own_cost == D("17500")


def test_price_finds_the_own_cost_of_a_line_not_read_through_stocked_lines(diamonds):
    _cost(diamonds["round"], "17777")
    assert dia_services.price(diamonds["round"], dia_services.rate_table())[0] == D("17777")


def test_search_values_and_margin_read_the_own_cost(client, accounts_user, sales_user, diamonds):
    _cost(diamonds["round"], "17777")                                  # 3.40 ct × ₹17,777 = ₹60,441.80
    row = next(r for r in dia_rows.line_rows(accounts_user) if r["pk"] == diamonds["round"].pk)
    assert row["cost_amount"] == D("60441.80") and round(row["margin"], 2) == D("18.20")
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert "17,777" in body and "60,442" in body and "16,517" not in body
    client.force_login(sales_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert "17,777" not in body and "60,442" not in body


def test_a_description_finds_its_code_or_makes_a_confirmed_one(admin_user_, diamonds):
    assert dia_services.code_for(admin_user_, "Round", "F-G-H", "VS-SI").pk == "DRFGH VS-SI"
    made = dia_services.code_for(admin_user_, "Round", "G", "VS1")
    assert (made.pk, made.confirmed, made.note) == ("DRG VS1", True, "")
    assert (made.shape.value, made.colour.value, made.clarity.value) == ("Round", "G", "VS1")
    assert dia_services.code_for(admin_user_, "Round", "G", "VS1") == made              # found the second time
    assert dia_services.code_for(admin_user_, "Polki", "I-J", "SI-I").pk == "D Polki I-J SI-I"   # no token: words


@pytest.mark.parametrize("shape, colour, clarity, words", [
    ("", "G", "VS1", "Give the shape, colour and clarity"),
    ("Cushion", "G", "VS1", "Cushion is not on the shape list"),
    ("Round", "G", "VVS9", "VVS9 is not on the clarity list"),
])
def test_a_description_must_use_the_master_lists(admin_user_, diamonds, shape, colour, clarity, words):
    with pytest.raises(ServiceError, match=words):
        dia_services.code_for(admin_user_, shape, colour, clarity)
    assert not DiamondTerm.objects.filter(value__in=("Cushion", "VVS9")).exists()


def test_a_made_name_already_taken_is_refused(admin_user_, diamonds):
    DiamondCode.objects.create(item_code="DRG VS1", note="read another way")
    with pytest.raises(ServiceError, match="DRG VS1 already reads differently"):
        dia_services.code_for(admin_user_, "Round", "G", "VS1")


def test_a_new_line_takes_the_next_reference_and_holds_nothing(diamonds):
    rnd = diamonds["round"]
    fresh = dia_services.new_line(category=rnd.category, code=rnd.code, band=rnd.band, size_text="+6-12")
    assert fresh.ref == "NRD-000004" and _line(fresh.pk).on_ct is None


def test_size_bands_follow_part_3_including_the_per_stone_rule():
    assert dia_services.sized("+2").band == "+2-6"
    per_stone = dia_services.sized("mixed", 4, D("1"))
    assert (per_stone.band, per_stone.ct_lo, per_stone.ct_hi) == ("carat band", D("0.250"), D("0.250"))
    assert dia_services.sized("mixed", None, D("1")).band == "?"


def test_a_line_reads_as_ref_code_size_and_batch(diamonds):
    assert dia_services.line_label(_line(diamonds["round"].pk)) == "NRD-000001 · DRFGH VS-SI · +6-12 · B-771"
    choices = dia_services.line_choices()
    assert choices[0] == {"pk": diamonds["round"].pk, "label": "NRD-000001 · DRFGH VS-SI · +6-12 · B-771",
                          "ct": D("3.40")}
    assert [c["pk"] for c in choices] == [diamonds[k].pk for k in ("round", "princess", "polki")]


def test_pickers_never_offer_an_unresolved_value(diamonds):
    DiamondTerm.objects.create(kind="shape", value="? RD8")
    assert "? RD8" not in dia_services.term_values("shape") and "Round" in dia_services.term_values("shape")


def test_no_stones_list_or_page_shows_a_diamond_document(client, accounts_user, shelf, diamonds):
    doc = StockDocument.objects.create(kind=K.DIA_JOB, number="JC-000001")
    Movement.objects.create(diamond=diamonds["round"], document=doc, reason=R.JOB_WORK_OUT,
                            direction=Movement.OUT, ct=D("1"))
    client.force_login(accounts_user)
    for query in ("", "?kind=dia_job"):
        body = client.get(reverse("inventory:recent") + query).content.decode()
        assert "JC-000001" not in body and "Job card" not in body
    assert client.get(reverse("inventory:document", args=[doc.pk])).status_code == 404
    for name in ("inventory:document_settle", "inventory:document_undo", "inventory:document_reverse"):
        assert client.post(reverse(name, args=[doc.pk])).status_code == 404, name
    assert ledger.out_summary() == {"ct": D("0"), "value": D("0"), "documents": 0}
    assert ledger.owed_by_document([doc]) == {}
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=dialedger_t1 ../nornament-app/.venv/bin/pytest inventory/tests/test_dia_ledger_models.py -p no:warnings`
Expected: FAIL with `ImportError: cannot import name 'DiamondLineCost'`.

- [ ] **Step 3: The models**

In `inventory/models.py`, `StockDocument.Kind` becomes:

```python
    class Kind(models.TextChoices):
        PURCHASE = "purchase", "Purchase"
        JOB_WORK = "job_work", "Job work"
        MEMO = "memo", "Memo"
        SPLIT = "split", "Split"
        TRANSFER = "transfer", "Transfer"
        SINGLE = "single", "Single"
        # diamonds (part 4): listed only on the diamond screens, never on a stones one
        DIA_JOB = "dia_job", "Job card"
        DIA_ASSORT = "dia_assort", "Assortment"
        DIA_PURCHASE = "dia_purchase", "Diamond purchase"
```

and its `kind` field becomes:

```python
    kind = models.CharField(max_length=12, choices=Kind.choices)
```

In `Movement.Reason`, after `RECOUNT_ADJUSTMENT`:

```python
        # the diamond ledgers (part 4)
        RETURNED_UNUSED = "Returned Unused"
        ASSORT_OUT = "Assort Out"
        ASSORT_IN = "Assort In"
```

At the end of the file:

```python
class DiamondLineCost(models.Model):
    """A diamond line's own cost per carat, in INR: written by the purchase that brought it in, or
    carried by weight through an assortment. Latest wins, and it wins over the rate card (owner,
    2026-10-01). Imported lines have none and keep the rate card. Nothing is overwritten."""

    line = models.ForeignKey(DiamondLine, on_delete=models.PROTECT, related_name="costs")
    cost_rate = models.DecimalField(max_digits=14, decimal_places=4)
    effective_from = models.DateField(default=timezone.localdate)
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    document = models.ForeignKey(
        StockDocument, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text="The purchase or assortment that set it; empty for a manual change.",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_dia_line_cost"
        ordering = ["-effective_from", "-pk"]

    def __str__(self):
        return f"{self.cost_rate}/ct on {self.line_id}"
```

- [ ] **Step 4: A line's own cost, and the helpers the ledgers share**

In `inventory/dia_services.py`, the module docstring's second paragraph becomes:

```python
"""Diamond reads that every screen shares, and every diamond write.

Carats on hand are the sum of a line's movements (the stones' rule). Cost is
the line's own cost when a purchase or an assortment set one, else the
inventory's own rate card — the latest rate for the line's item code and size,
else for the code at any size — never the stock app's chart. Sale is always
the rate card's.
"""
```

The imports become:

```python
from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from openpyxl import load_workbook

from accounts.capabilities import INV_MASTERS, VIEW_COST, VIEW_SALE, VIEW_VENDOR
from stock.models import Vendor
from stock.services import ServiceError, log, require

from . import dia_rules, inputs
from .dia_rules import canonical_code
from .dia_seed import COLOUR_LADDER
from .models import DiamondCode, DiamondLine, DiamondLineCost, DiamondRate, DiamondTerm, Movement, balance
```

Replace `stocked_lines` and `price`:

```python
def _own_costs(line):
    """A line's own cost rows in force today, latest first: a row dated ahead waits for its day."""
    return (DiamondLineCost.objects.filter(line=line, effective_from__lte=timezone.localdate())
            .order_by("-effective_from", "-pk"))


def stocked_lines(queryset=None):
    """Lines with ``on_ct`` (the sum of their movements) and ``own_cost`` (their latest own cost per
    carat, or ``None`` for a line that never had one)."""
    queryset = DiamondLine.objects.all() if queryset is None else queryset
    return queryset.select_related(
        "category", "band", "shape_override", "colour_override", "code__shape", "code__colour", "code__clarity"
    ).annotate(
        on_ct=balance("ct"), own_cost=Subquery(_own_costs(OuterRef("pk")).values("cost_rate")[:1])
    ).order_by("pk")
```

```python
def price(line, rates):
    """(cost, sale) per carat; ``None`` is "not set".

    Cost is the line's own latest cost when it has one, else the rate card's for its code and
    size, else for its code at any size. Sale is the rate card's alone. A line read through
    ``stocked_lines`` carries ``own_cost``; any other is looked up, so no caller can skip it.
    """
    exact = rates.get((line.code_id, line.size_text), {})
    any_size = rates.get((line.code_id, ""), {})
    own = line.own_cost if hasattr(line, "own_cost") else _own_costs(line).values_list("cost_rate", flat=True).first()
    card = exact.get("cost") if exact.get("cost") is not None else any_size.get("cost")
    cost = own if own is not None else card
    sale = exact.get("sale") if exact.get("sale") is not None else any_size.get("sale")
    return cost, sale
```

After `_last_ref_number`, add:

```python
def new_line(**fields):
    """A line with the next ``NRD-`` reference and nothing in it: its carats arrive by the movement
    its caller posts (a purchase or an assortment), in the caller's transaction."""
    inputs.fits(DiamondLine, **fields)
    return DiamondLine.objects.create(ref=f"NRD-{_last_ref_number() + 1:06d}", **fields)


def line_label(line):
    """How a line is named wherever it is picked or listed: ref · item code · size · batch."""
    return f"{line.ref} · {line.code_id} · {line.size_text or line.band.value} · {line.batch_no or 'no batch'}"


def line_choices(queryset=None):
    """The lines with carats on hand, for a picker."""
    return [{"pk": line.pk, "label": line_label(line), "ct": line.on_ct}
            for line in stocked_lines(queryset).filter(on_ct__gt=0)]


def term_values(kind):
    """A master list's values for a picker, in its order. An unresolved ``?`` or ``(`` value is
    never offered: it is a reading to correct, not a grade to choose."""
    values = DiamondTerm.objects.filter(kind=kind).order_by("sort", "value").values_list("value", flat=True)
    return [value for value in values if not value.startswith(("?", "("))]


def listed(kind, value):
    """The master-list term for a typed value. A purchase or an assortment never adds to the lists:
    Settings does."""
    value = (value or "").strip()
    if not value:
        return None
    found = DiamondTerm.objects.filter(kind=kind, value=value).first()
    if found is None:
        raise ServiceError(f"{value} is not on the {kind} list; add it in Settings first.")
    return found


def _code_name(shape, colour, clarity):
    """A new code's name in the register's own grammar (``DRFGH VS-SI``) when the shape and colour
    have tokens, so it reads back the same; otherwise the plain words (``D Polki I-J SI-I``)."""
    shapes = {name: token for token, name in dia_rules.SHAPES}                 # OV after OVL: OV wins
    colours = {name: token for token, name in reversed(dia_rules.COLOURS)}     # KL and MN, never LC or LB
    if shape in shapes and (colour in colours or colour in COLOUR_LADDER):
        return canonical_code(f"D{shapes[shape]}{colours.get(colour, colour)} {clarity}")
    return canonical_code(f"D {shape} {colour} {clarity}")


def code_for(user, shape, colour, clarity):
    """The item code that means exactly this shape, colour and clarity — an existing one, a
    confirmed one first — else a new one, created confirmed (owner, 2026-10-01)."""
    values = [(value or "").strip() for value in (shape, colour, clarity)]
    if not all(values):
        raise ServiceError("Give the shape, colour and clarity.")
    shape, colour, clarity = (listed(kind, value) for kind, value in
                              zip((DiamondTerm.SHAPE, DiamondTerm.COLOUR, DiamondTerm.CLARITY), values))
    found = (DiamondCode.objects.filter(shape=shape, colour=colour, clarity=clarity)
             .order_by("-confirmed", "item_code").first())
    if found is not None:
        return found
    name = _code_name(shape.value, colour.value, clarity.value)
    inputs.fits(DiamondCode, item_code=name)
    if DiamondCode.objects.filter(pk=name).exists():
        raise ServiceError(f"{name} already reads differently; correct it in Settings first.")
    code = DiamondCode.objects.create(item_code=name, shape=shape, colour=colour, clarity=clarity, confirmed=True)
    log(user, "INSERT", "inv_dia_code", code.pk, f"{code.pk} from a description")
    return code


def sized(size_text, pcs=None, ct=None):
    """A size's band (part 3's rules). A size that fits no band is a carat band at its weight per
    stone, when there are pieces to divide by (the owner, 2026-09-30)."""
    out = dia_rules.size_band(size_text)
    if out.band == "?" and (pcs or 0) > 0 and (ct or 0) > 0:
        per_stone = (ct / pcs).quantize(Decimal("0.001"))
        return dia_rules.Sized("carat band", per_stone, per_stone)
    return out
```

In `inventory/importers/dia_plan.py`, `_sized` uses the one rule:

```python
def _sized(row):
    """A size that fits no band is banded by the weight per stone, when the file gives pieces (the owner, 2026-09-30)."""
    return dia_services.sized(row.band_text or row.size_text, row.pcs, row.ct)
```

`_sized` was the only user of `Decimal` in `dia_plan.py`, so delete its `from decimal import Decimal` line.

- [ ] **Step 5: The ledger's diamond kinds, and stones lists that show stones**

In `inventory/ledger.py`, add after `Kind, Status = …`:

```python
#: the stones kinds: every stones list and page shows only these
STONE_KINDS = (Kind.PURCHASE, Kind.JOB_WORK, Kind.MEMO, Kind.SPLIT, Kind.TRANSFER, Kind.SINGLE)
#: part 4's diamond kinds, shown only on the diamond screens
DIAMOND_KINDS = (Kind.DIA_JOB, Kind.DIA_ASSORT, Kind.DIA_PURCHASE)
```

`RIGHT_FOR_KIND` and `PREFIX` become:

```python
RIGHT_FOR_KIND = {
    Kind.PURCHASE: INV_PURCHASE, Kind.JOB_WORK: INV_JOB, Kind.MEMO: INV_MOVE,
    Kind.SPLIT: INV_ASSORT, Kind.TRANSFER: INV_ASSORT, Kind.SINGLE: INV_MOVE,
    Kind.DIA_JOB: INV_JOB, Kind.DIA_ASSORT: INV_ASSORT, Kind.DIA_PURCHASE: INV_PURCHASE,
}
#: automatic numbers; job work and memos carry the challan or memo no. people type
PREFIX = {Kind.PURCHASE: "PUR-", Kind.SPLIT: "SPL-", Kind.TRANSFER: "TRF-", Kind.SINGLE: "MOV-",
          Kind.DIA_JOB: "JC-", Kind.DIA_ASSORT: "AS-", Kind.DIA_PURCHASE: "DP-"}
```

In `owed_by_document`, the movements read are a pouch's only:

```python
    totals = [t for t in Movement.objects.filter(document__in=documents, pouch__isnull=False).order_by()
              .values("document", "pouch").annotate(pcs=_owed("pcs"), ct=_owed("ct"))
              if t["pcs"] or t["ct"]]
```

`out_summary` already reads only `OPENABLE`, which is stones job work and memos, and needs no change.

In `inventory/views_lists.py`, `recent` becomes:

```python
@login_required
def recent(request):
    """Recent stones documents across every pouch, newest first. A diamond document is never
    listed here: the diamond ledgers have their own screens.

    ponytail: the newest 100; page through when someone asks for more.
    """
    if _client(request):
        return redirect("inventory:shelf")
    kind = request.GET.get("kind", "")
    documents = (StockDocument.objects.filter(kind__in=ledger.STONE_KINDS)
                 .select_related("vendor", "customer").annotate(lines=Count("movements")))
    if kind in ledger.STONE_KINDS:
        documents = documents.filter(kind=kind)
    rows = [mask(request.user, {"pk": d.pk, "number": d.number, "kind": d.get_kind_display(), **ledger.party(d),
                                "occurred_on": d.occurred_on, "status": d.get_status_display(),
                                "tone": TONE[d.status], "lines": d.lines})
            for d in documents.order_by("-created_at", "-pk")[:RECENT_CAP]]
    return _page(request, "inventory/recent.html", _everything(request), tab="recent", rows=rows, kind=kind,
                 kinds=[(value, label) for value, label in Kind.choices if value in ledger.STONE_KINDS])
```

In `inventory/views_documents.py`, the stones document page and its three actions find stones documents only. In `document`:

```python
    doc = get_object_or_404(StockDocument.objects.select_related(
        "vendor", "customer", "reverses", "from_batch", "to_batch"), pk=pk, kind__in=ledger.STONE_KINDS)
```

and in each of `document_settle`, `document_undo` and `document_reverse`, replace `get_object_or_404(StockDocument, pk=pk)` with:

```python
    doc = get_object_or_404(StockDocument, pk=pk, kind__in=ledger.STONE_KINDS)
```

- [ ] **Step 6: Migration**

Run:

```bash
POSTGRES_DB=dialedger_t1 ../nornament-app/.venv/bin/python manage.py makemigrations inventory -n diamond_ledgers
POSTGRES_DB=dialedger_t1 ../nornament-app/.venv/bin/python manage.py makemigrations --check --dry-run
```

Expected: `inventory/migrations/0008_diamond_ledgers.py` is created, containing an `AlterField` on `stockdocument.kind`, an `AlterField` on `movement.reason` and a `CreateModel` for `DiamondLineCost`. The second command prints `No changes detected`.

- [ ] **Step 7: Run the tests**

Run: `POSTGRES_DB=dialedger_t1 ../nornament-app/.venv/bin/pytest inventory -p no:warnings`
Expected: PASS. That includes the new file, every part 2 stones test unchanged, `test_dia_real_file.py` (it runs, because the file is beside the worktree: 281 lines, 546.96 ct, cost within ₹10 of ₹1,47,98,794) and `test_dia_parity.py`.

- [ ] **Step 8: Commit**

```bash
git add inventory/models.py inventory/migrations/0008_diamond_ledgers.py inventory/dia_services.py \
  inventory/importers/dia_plan.py inventory/ledger.py inventory/views_lists.py inventory/views_documents.py \
  inventory/tests/test_dia_ledger_models.py
git commit -m "$(cat <<'EOF'
Diamond document kinds and reasons, a line's own cost ahead of the rate card, codes found from a description, stones lists kept to stones

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---
### Task 2: The ledger engine moves a pouch or a diamond line; job cards close by hand; the reserved routes

**Files:**
- Modify: `inventory/ledger.py` (the whole file is given below), `inventory/urls.py`, `inventory/tests/test_masking.py`
- Create: `inventory/tests/test_dia_ledger.py`
- Create (stubs, each replaced whole by its wave-4 task): `inventory/views_dia_jobs.py`, `inventory/views_dia_assort.py`, `inventory/views_dia_purchase.py`

**Interfaces:**
- Consumes: Task 1's kinds, reasons, `STONE_KINDS`, `DIAMOND_KINDS`, `PREFIX`, `RIGHT_FOR_KIND`, `dia_services.stocked_lines/new_line`.
- Produces:
  - `ledger.Line(owner, reason, direction, pcs=None, ct=None, note="", ref="", reverses=None)`, where `owner` is a `Pouch` or a `DiamondLine`. The field was `pouch`; every caller passes it positionally, so none changes.
  - `ledger.OWED = OPENABLE + (Kind.DIA_JOB,)`: the kinds whose credits are checked per owner against what is out. `ledger.OPENABLE` is unchanged, `(JOB_WORK, MEMO)`: the kinds that close themselves.
  - `ledger.CLOSABLE = (Kind.DIA_JOB,)`.
  - `ledger.CREATING` gains `ASSORT_IN`.
  - `ledger.outstanding(document) -> {owner pk: (pcs, ct)}`, keyed by diamond-line pk on a diamond kind and by pouch pk otherwise.
  - `ledger.close_document(user, document) -> StockDocument`. It needs the kind's right and works on a `CLOSABLE` kind only. It refuses with `"{doc} can close only at zero: {x} ct outstanding."` and with `"{doc} is closed; only an open card can close."`.
  - `ledger.post`, `ledger.reverse_document` and `ledger.undo_last` work for either owner. On a diamond line, carats are the quantity and pieces are optional and unchecked. A job card never closes itself, and an undo reopens it when something is outstanding again.
  - `ledger.party(document)`: a `DIA_JOB` with a vendor gives `{"karigar_name": …}`; a `DIA_PURCHASE` gives `{"vendor_name": …}`.
  - URL names, stubbed until wave 4:
    - `inventory:dia_jobs` (GET; `?card=`, `?closed=1`, `?as=`), `inventory:dia_job_new`, and `inventory:dia_job_post`, `inventory:dia_job_close`, `inventory:dia_job_undo`, `inventory:dia_job_reverse` (each takes `pk`);
    - `inventory:dia_assorts` (GET and POST; `?doc=`, `?as=`) and `inventory:dia_assort_reverse` (`pk`);
    - `inventory:dia_purchase` (GET and POST; `?as=`) and `inventory:dia_purchase_reverse` (`pk`).
  - View functions:
    - `views_dia_jobs.jobs(request)`, `job_new(request)`, `job_post(request, pk)`, `job_close(request, pk)`, `job_undo(request, pk)`, `job_reverse(request, pk)`;
    - `views_dia_assort.assorts(request)`, `assort_reverse(request, pk)`;
    - `views_dia_purchase.purchase(request)`, `purchase_reverse(request, pk)`.

**Every part 2 stones test must pass unchanged after this task.** Do not edit any of `inventory/tests/test_ledger.py`, `test_ledger_models.py`, `test_ledger_jobs.py`, `test_ledger_single.py`, `test_ledger_purchase.py`, `test_ledger_assort.py`, `test_ledger_lists.py`, `test_document_view.py`, `test_record_movement.py`, `test_purchase_view.py`, `test_assort_views.py`, `test_movements.py` or `test_inputs.py`. If one of them fails, the engine change is wrong. Step 5 runs them on their own before anything else.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_dia_ledger.py`:

```python
"""The ledger engine with a diamond line as the owner: carats are the quantity, a job card closes
by hand and only at zero, a created line blocks a reversal once it moves — and the invariant,
extended to diamond lines."""
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from inventory import dia_services, ledger, ledger_jobs
from inventory.ledger import Line
from inventory.models import Movement, StockDocument
from inventory.tests.conftest import DIA_SUPPLIER, KARIGAR
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
K, S, R = StockDocument.Kind, StockDocument.Status, Movement.Reason
IN, OUT, SETTLE = Movement.IN, Movement.OUT, Movement.SETTLE


def _ct(line):
    return dia_services.stocked_lines().get(pk=line.pk).on_ct


def _card(user, parties=None):
    return ledger.open_document(user, K.DIA_JOB, vendor=parties["karigar"] if parties else None)


def _bought(user, like, ct, number="INV-9"):
    """A purchase of one new line shaped like ``like``, straight through the engine."""
    doc = ledger.open_document(user, K.DIA_PURCHASE, number)
    fresh = dia_services.new_line(category=like.category, code=like.code, band=like.band, size_text=like.size_text)
    ledger.post(user, doc, [Line(fresh, R.PURCHASE, IN, None, D(ct))])
    return doc, fresh


def test_diamond_documents_number_themselves(admin_user_):
    kinds = (K.DIA_JOB, K.DIA_JOB, K.DIA_ASSORT, K.DIA_PURCHASE)
    assert [ledger.open_document(admin_user_, kind).number for kind in kinds] == [
        "JC-000001", "JC-000002", "AS-000001", "DP-000001"]
    assert ledger.open_document(admin_user_, K.DIA_PURCHASE, "2026/0442").number == "2026/0442"


def test_a_diamond_line_moves_by_carats(admin_user_, diamonds):
    rnd = diamonds["round"]
    doc = ledger.open_document(admin_user_, K.DIA_ASSORT)
    with pytest.raises(ServiceError, match="needs carats above zero"):
        ledger.post(admin_user_, doc, [Line(rnd, R.ASSORT_OUT, OUT, 3, None)])
    ledger.post(admin_user_, doc, [Line(rnd, R.ASSORT_OUT, OUT, 99, D("1.4"))])     # pieces ride along, unchecked
    assert _ct(rnd) == D("2.00") and doc.movements.get().diamond == rnd and doc.status == S.CLOSED


def test_no_diamond_line_goes_below_zero(admin_user_, diamonds):
    rnd, princess = diamonds["round"], diamonds["princess"]
    doc = ledger.open_document(admin_user_, K.DIA_ASSORT)
    with pytest.raises(ServiceError, match=r"Not enough in NRD-000002 .* below zero \(-0\.15 ct\)"):
        ledger.post(admin_user_, doc, [Line(rnd, R.ASSORT_OUT, OUT, None, D("1")),
                                       Line(princess, R.ASSORT_OUT, OUT, None, D("1"))])
    assert not doc.movements.exists() and _ct(rnd) == D("3.40")


def test_a_job_card_credit_cannot_exceed_what_that_line_has_out(admin_user_, diamonds, parties):
    rnd, princess = diamonds["round"], diamonds["princess"]
    card = _card(admin_user_, parties)
    ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_OUT, OUT, None, D("1")),
                                    Line(princess, R.JOB_WORK_OUT, OUT, None, D("0.5"))])
    assert ledger.outstanding(card) == {rnd.pk: (0, D("1")), princess.pk: (0, D("0.5"))}
    with pytest.raises(ServiceError, match="cannot exceed what is outstanding: JC-000001 has 0.5 ct of NRD-000002"):
        ledger.post(admin_user_, card, [Line(princess, R.CONSUMED, SETTLE, None, D("0.6"))])
    with pytest.raises(ServiceError, match="cannot exceed"):
        ledger.post(admin_user_, card, [Line(diamonds["polki"], R.JOB_WORK_IN, IN, None, D("0.1"))])  # never issued
    ledger.post(admin_user_, card, [Line(rnd, R.RETURNED_UNUSED, IN, None, D("0.4"))])
    assert ledger.outstanding(card)[rnd.pk] == (0, D("0.6")) and _ct(rnd) == D("2.80")


def test_a_job_card_never_closes_itself_and_closes_only_at_zero(admin_user_, diamonds, parties):
    rnd = diamonds["round"]
    card = _card(admin_user_, parties)
    ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_OUT, OUT, None, D("1"))])
    with pytest.raises(ServiceError, match="can close only at zero: 1 ct outstanding"):
        ledger.close_document(admin_user_, card)
    ledger.post(admin_user_, card, [Line(rnd, R.CONSUMED, SETTLE, None, D("1"))])
    card.refresh_from_db()
    assert card.status == S.OPEN                                  # balanced, still open: more may be issued
    ledger.close_document(admin_user_, card)
    card.refresh_from_db()
    assert card.status == S.CLOSED
    with pytest.raises(ServiceError, match="is closed; it takes no more entries"):
        ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_OUT, OUT, None, D("0.1"))])
    with pytest.raises(ServiceError, match="only an open card can close"):
        ledger.close_document(admin_user_, card)


def test_undo_reopens_a_closed_card(admin_user_, diamonds, parties):
    rnd = diamonds["round"]
    card = _card(admin_user_, parties)
    ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_OUT, OUT, None, D("1"))])
    ledger.post(admin_user_, card, [Line(rnd, R.WASTAGE, SETTLE, None, D("1"))])
    ledger.close_document(admin_user_, card)
    undone = ledger.undo_last(admin_user_, card)
    card.refresh_from_db()
    assert undone.reverses.reason == R.WASTAGE and undone.diamond == rnd
    assert card.status == S.OPEN and ledger.outstanding(card)[rnd.pk] == (0, D("1"))


def test_only_a_job_card_is_closed_by_hand(admin_user_, shelf, parties):
    job = ledger_jobs.job_work_out(admin_user_, shelf["onyx"], parties["karigar"], "2026/0431", 1, D("1"))
    with pytest.raises(ServiceError, match="closes itself"):
        ledger.close_document(admin_user_, job)


def test_closing_needs_the_job_cards_right(admin_user_, sales_user, diamonds):
    with pytest.raises(PermissionDenied):
        ledger.close_document(sales_user, _card(admin_user_))


def test_reversing_a_card_puts_every_line_back(admin_user_, diamonds, parties):
    rnd = diamonds["round"]
    card = _card(admin_user_, parties)
    ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_OUT, OUT, None, D("1"))])
    ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_IN, IN, None, D("0.25"))])
    reversal = ledger.reverse_document(admin_user_, card)
    card.refresh_from_db()
    assert card.status == S.REVERSED and (reversal.kind, reversal.status) == (K.DIA_JOB, S.CLOSED)
    assert _ct(rnd) == D("3.40")


def test_a_created_line_that_moved_since_blocks_the_reversal(admin_user_, diamonds, parties):
    bought, fresh = _bought(admin_user_, diamonds["round"], "2")
    card = _card(admin_user_, parties)
    ledger.post(admin_user_, card, [Line(fresh, R.JOB_WORK_OUT, OUT, None, D("0.5"))])
    with pytest.raises(ServiceError, match="NRD-000004 .* has moved since"):
        ledger.reverse_document(admin_user_, bought)
    ledger.reverse_document(admin_user_, card)                    # its later movement reversed …
    ledger.reverse_document(admin_user_, bought)                  # … the purchase reverses, the line stays at zero
    assert _ct(fresh) == D("0")


def test_an_assorted_line_counts_as_created(admin_user_, diamonds):
    princess = diamonds["princess"]
    doc = ledger.open_document(admin_user_, K.DIA_ASSORT)
    child = dia_services.new_line(category=princess.category, code=princess.code, band=princess.band, size_text="+2")
    ledger.post(admin_user_, doc, [Line(princess, R.ASSORT_OUT, OUT, None, D("0.5")),
                                   Line(child, R.ASSORT_IN, IN, None, D("0.5"))])
    again = ledger.open_document(admin_user_, K.DIA_ASSORT)
    ledger.post(admin_user_, again, [Line(child, R.ASSORT_OUT, OUT, None, D("0.1"))])
    with pytest.raises(ServiceError, match="has moved since"):
        ledger.reverse_document(admin_user_, doc)


def test_the_counterparty_of_a_card_is_a_karigar(admin_user_, diamonds, parties):
    assert ledger.party(_card(admin_user_, parties)) == {"karigar_name": KARIGAR}
    assert ledger.party(_card(admin_user_)) == {}                                       # In-house
    bought = ledger.open_document(admin_user_, K.DIA_PURCHASE, vendor=diamonds["supplier"])
    assert ledger.party(bought) == {"vendor_name": DIA_SUPPLIER}


def test_job_cards_never_count_as_stones_out(admin_user_, shelf, diamonds, parties):
    card = _card(admin_user_, parties)
    ledger.post(admin_user_, card, [Line(diamonds["round"], R.JOB_WORK_OUT, OUT, None, D("1"))])
    assert ledger.out_summary() == {"ct": D("0"), "value": D("0"), "documents": 0}


def test_on_hand_plus_out_on_cards_is_what_came_in_less_what_left_for_good(admin_user_, diamonds, parties):
    """The ledger invariant, for diamond lines: through every job-card entry, an undo, a purchase,
    an assortment with a sorting loss, and a reversal."""
    rnd, princess = diamonds["round"], diamonds["princess"]

    def owned():
        on_hand = sum((line.on_ct or 0 for line in dia_services.stocked_lines()), D("0"))
        cards = StockDocument.objects.filter(kind=K.DIA_JOB, reverses__isnull=True).exclude(status=S.REVERSED)
        return on_hand + sum((ct for card in cards for _, ct in ledger.outstanding(card).values()), D("0"))

    opening = D("47.46")                                                                # 3.40 + 0.85 + 43.21
    assert owned() == opening
    card = _card(admin_user_, parties)
    ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_OUT, OUT, None, D("2"))])
    ledger.post(admin_user_, card, [Line(rnd, R.JOB_WORK_IN, IN, None, D("0.5"))])
    ledger.post(admin_user_, card, [Line(rnd, R.RETURNED_UNUSED, IN, None, D("0.25"))])
    ledger.post(admin_user_, card, [Line(rnd, R.CONSUMED, SETTLE, None, D("1"))])     # left for good: 1
    ledger.post(admin_user_, card, [Line(rnd, R.BREAKAGE, SETTLE, None, D("0.1"))])   # broken …
    ledger.undo_last(admin_user_, card)                                                 # … then undone
    _bought(admin_user_, rnd, "1.5")                                                    # came in: 1.5
    sort = ledger.open_document(admin_user_, K.DIA_ASSORT)
    child = dia_services.new_line(category=princess.category, code=princess.code, band=princess.band, size_text="+2")
    ledger.post(admin_user_, sort, [Line(princess, R.ASSORT_OUT, OUT, None, D("0.5")),
                                    Line(princess, R.WASTAGE, OUT, None, D("0.05")),    # left for good: 0.05
                                    Line(child, R.ASSORT_IN, IN, None, D("0.5"))])
    other = _card(admin_user_)
    ledger.post(admin_user_, other, [Line(diamonds["polki"], R.JOB_WORK_OUT, OUT, None, D("3"))])
    ledger.reverse_document(admin_user_, other)                                         # nets to nothing
    assert owned() == opening + D("1.5") - D("1") - D("0.05")
    assert ledger.outstanding(card) == {rnd.pk: (0, D("0.25"))}


def test_the_diamond_ledger_screens_have_their_names():
    for name, args in [("inventory:dia_jobs", []), ("inventory:dia_job_new", []), ("inventory:dia_job_post", [1]),
                       ("inventory:dia_job_close", [1]), ("inventory:dia_job_undo", [1]),
                       ("inventory:dia_job_reverse", [1]), ("inventory:dia_assorts", []),
                       ("inventory:dia_assort_reverse", [1]), ("inventory:dia_purchase", []),
                       ("inventory:dia_purchase_reverse", [1])]:
        assert reverse(name, args=args)
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=dialedger_t2 ../nornament-app/.venv/bin/pytest inventory/tests/test_dia_ledger.py -p no:warnings`
Expected: FAIL. `post` writes `pouch=<DiamondLine>` (a `ValueError`), `close_document` does not exist, and the URL names do not reverse.

- [ ] **Step 3: Write `inventory/ledger.py`** (the whole file; Task 1's constants are kept)

```python
"""The stock ledger: documents, and the one way their movements are written.

Every action that moves stock — stones job work, a memo, a purchase, a split, a
transfer, a one-off sale or loss; a diamond job card, assortment or purchase —
opens a ``StockDocument`` and hands its movements to ``post``, which writes them
in one transaction and runs the checks every post shares: quantities above zero,
an uncountable pouch by weight only, a diamond line by carats, nothing settled
beyond what is out, nothing below zero. A movement's owner is a pouch or a
diamond line; stones and diamonds share this one engine. Nothing is edited
afterwards; a mistake is undone by posting the opposite movements.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal

from django.db import transaction
from django.db.models import Case, F, Q, Sum, When
from django.utils import timezone

from accounts.capabilities import INV_ASSORT, INV_JOB, INV_MOVE, INV_PURCHASE
from stock.services import ServiceError, log, require

from . import dia_services, inputs, services
from .models import Batch, DiamondLine, Movement, Pouch, StockDocument

ZERO = Decimal("0")
Kind, Status = StockDocument.Kind, StockDocument.Status

#: the stones kinds: every stones list and page shows only these
STONE_KINDS = (Kind.PURCHASE, Kind.JOB_WORK, Kind.MEMO, Kind.SPLIT, Kind.TRANSFER, Kind.SINGLE)
#: part 4's diamond kinds, shown only on the diamond screens
DIAMOND_KINDS = (Kind.DIA_JOB, Kind.DIA_ASSORT, Kind.DIA_PURCHASE)
#: the kinds that close themselves when nothing is outstanding (stones job work and memos)
OPENABLE = (Kind.JOB_WORK, Kind.MEMO)
#: the kinds whose credits are checked, owner by owner, against what is out on them
OWED = OPENABLE + (Kind.DIA_JOB,)
#: the kinds closed by hand, and only at zero (owner, 2026-10-01)
CLOSABLE = (Kind.DIA_JOB,)
#: the right that posts each kind — and so may undo, close or reverse it
RIGHT_FOR_KIND = {
    Kind.PURCHASE: INV_PURCHASE, Kind.JOB_WORK: INV_JOB, Kind.MEMO: INV_MOVE,
    Kind.SPLIT: INV_ASSORT, Kind.TRANSFER: INV_ASSORT, Kind.SINGLE: INV_MOVE,
    Kind.DIA_JOB: INV_JOB, Kind.DIA_ASSORT: INV_ASSORT, Kind.DIA_PURCHASE: INV_PURCHASE,
}
#: automatic numbers; job work and memos carry the challan or memo no. people type
PREFIX = {Kind.PURCHASE: "PUR-", Kind.SPLIT: "SPL-", Kind.TRANSFER: "TRF-", Kind.SINGLE: "MOV-",
          Kind.DIA_JOB: "JC-", Kind.DIA_ASSORT: "AS-", Kind.DIA_PURCHASE: "DP-"}
REVERSAL_PREFIX = "REV-"
#: the reasons that bring a pouch or a diamond line into being, so a reversal can find what it created
CREATING = (Movement.Reason.PURCHASE, Movement.Reason.SPLIT, Movement.Reason.ASSORT_IN)


@dataclass
class Line:
    """One movement to post. ``owner`` is a ``Pouch`` or a ``DiamondLine``; ``ref`` defaults to the
    document's number."""

    owner: Pouch | DiamondLine
    reason: str
    direction: str
    pcs: int | None = None
    ct: Decimal | None = None
    note: str = ""
    ref: str = ""
    reverses: Movement | None = None


def _diamond(owner):
    return isinstance(owner, DiamondLine)


def _by(user):
    return user if getattr(user, "is_authenticated", False) else None


def _when(day):
    """A movement's time: now when it happens today, else noon of the day it happened."""
    if day is None or day == timezone.localdate():
        return timezone.now()
    return timezone.make_aware(datetime.combine(day, time(12)))


def next_number(prefix):
    """``SPL-000001``: one above the highest number with this prefix.

    ponytail: read-the-max under the caller's transaction; the unique number
    constraint catches a race. A sequence if two people ever post at once.
    """
    last = (StockDocument.objects.filter(number__regex=rf"^{prefix}[0-9]{{6}}$")
            .order_by("-number").values_list("number", flat=True).first())
    return f"{prefix}{(int(last[len(prefix):]) if last else 0) + 1:06d}"


def open_document(user, kind, number="", **fields):
    """A new, open document.

    A typed number must be free among this kind's open and closed documents (a
    reversed one's may be reused). A blank one is drawn automatically — except
    for job work and memos, where goods leave without a sale and need theirs.
    """
    number = (number or "").strip()
    inputs.fits(StockDocument, number=number, **fields)
    if not number:
        if kind not in PREFIX:
            what = "delivery challan no." if kind == Kind.JOB_WORK else "memo no."
            raise ServiceError(f"A {what} is required whenever goods leave without a sale.")
        number = next_number(PREFIX[kind])
    elif StockDocument.objects.filter(kind=kind, number=number).exclude(status=Status.REVERSED).exists():
        raise ServiceError(f"{Kind(kind).label} {number} already exists; give it another number.")
    return StockDocument.objects.create(kind=kind, number=number, created_by=_by(user), **fields)


def _owed(field):
    """Out adds to what a document is owed; in and settle take from it; a reversal flips its sign."""
    value = F(field)
    return Sum(Case(
        When(direction=Movement.OUT, reverses__isnull=True, then=value),
        When(direction=Movement.OUT, then=-value),
        When(reverses__isnull=True, then=-value),
        default=value,
        output_field=Movement._meta.get_field(field),
    ))


def outstanding(document):
    """``{owner pk: (pcs, ct)}`` still out on a job work, a memo or a job card. The owners are
    diamond lines on a diamond document and pouches on a stones one."""
    field = "diamond" if document.kind in DIAMOND_KINDS else "pouch"
    totals = document.movements.order_by().values(field).annotate(pcs=_owed("pcs"), ct=_owed("ct"))
    return {t[field]: (t["pcs"] or 0, t["ct"] or ZERO) for t in totals}


def owed_by_document(documents):
    """``{document pk: [(pouch, pcs, ct)]}`` — what each of these job work or memo documents
    still has out, with the pouches read through ``services.stocked`` so each carries its
    current valuation ``rate``. Stones only: a diamond line is never a pouch."""
    totals = [t for t in Movement.objects.filter(document__in=documents, pouch__isnull=False).order_by()
              .values("document", "pouch").annotate(pcs=_owed("pcs"), ct=_owed("ct"))
              if t["pcs"] or t["ct"]]
    pouches = {p.pk: p for p in services.stocked(Pouch.objects.filter(pk__in={t["pouch"] for t in totals}))}
    owed = defaultdict(list)
    for t in totals:
        owed[t["document"]].append((pouches[t["pouch"]], t["pcs"] or 0, t["ct"] or ZERO))
    return owed


def out_summary():
    """Carats out on open stones job work and memos, valued at each pouch's current rate.

    An unvalued pouch adds nothing to the value, as on the shelf's Stock value.
    """
    documents = StockDocument.objects.filter(kind__in=OPENABLE, status=Status.OPEN)
    ct, value = ZERO, ZERO
    for lines in owed_by_document(documents).values():
        for pouch, _, owed_ct in lines:
            ct += owed_ct
            value += owed_ct * pouch.rate if pouch.rate is not None else ZERO
    return {"ct": ct, "value": value, "documents": documents.count()}


def party(document):
    """The counterparty, under the key that masks it.

    ``karigar_name`` (stones job work, a diamond job card) is seen by those who
    post job work, ``vendor_name`` by those who see suppliers, ``customer_name``
    by those who see sales. Callers mask.
    """
    if document is None:
        return {}
    if document.customer_id:
        return {"customer_name": document.customer.name}
    if document.vendor_id:
        karigar = document.kind in (Kind.JOB_WORK, Kind.DIA_JOB)
        return {("karigar_name" if karigar else "vendor_name"): document.vendor.name}
    return {}


def next_pouch_numbers(batches=None):
    """``{batch code: the next free pouch no.}`` — one above the highest numeric number in
    use (the importer's rule), so a suggestion never collides with a number."""
    batches = Batch.objects.all() if batches is None else batches
    top = dict.fromkeys(batches.values_list("code", flat=True), 0)
    numbered = Pouch.objects.filter(batch__in=batches).exclude(pouch_no=None)
    for code, number in numbered.values_list("batch__code", "pouch_no"):
        if number.isdigit():
            top[code] = max(top[code], int(number))
    return {code: n + 1 for code, n in top.items()}


def next_pouch_no(batch):
    return str(next_pouch_numbers(Batch.objects.filter(pk=batch.pk))[batch.code])


def pouch_no_free(batch, pouch_no):
    return not Pouch.objects.filter(batch=batch, pouch_no=pouch_no).exists()


def new_pouch(batch, **fields):
    """A pouch with the next ``NRN-`` reference and nothing in it: its stock arrives by the
    movement its caller posts."""
    inputs.fits(Pouch, **fields)
    return Pouch.objects.create(ref=f"NRN-{services._last_ref_number() + 1:06d}", batch=batch, **fields)


def _ct(value):
    """Up to 4 places (the column's own precision), trimming trailing zeros: a real
    shortfall like 0.0001 ct must never print as a misleadingly-rounded 0.00."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _check(document, owner, line, owed):
    if line.reverses is not None:
        return                      # a reversal repeats a movement that passed these once
    inputs.fits(Movement, ref=line.ref)
    if any(value is not None and value < 0 for value in (line.pcs, line.ct)):
        raise ServiceError("A quantity cannot be negative; the reason says which way it moves.")
    diamond = _diamond(owner)
    if diamond and not line.ct:
        raise ServiceError("A diamond movement needs carats above zero; pieces are optional.")
    if not (line.pcs or line.ct):
        raise ServiceError("A movement needs pieces or a weight above zero.")
    if not diamond and not owner.countable and line.pcs is not None:
        raise ServiceError(f"{owner} is uncountable: it moves by weight only.")
    if document.kind in OWED and line.direction != Movement.OUT:
        pcs, ct = owed.get(owner.pk, (0, ZERO))
        # a diamond line's pieces ride along unchecked: carats are its quantity
        if (not diamond and (line.pcs or 0) > pcs) or (line.ct or 0) > ct:
            pieces = f" and {pcs} pcs" if not diamond and owner.countable else ""
            raise ServiceError(f"Settling cannot exceed what is outstanding: {document.number} has "
                               f"{_ct(ct)} ct{pieces} of {owner} out.")
        owed[owner.pk] = (pcs - (line.pcs or 0), ct - (line.ct or 0))


def _check_balances(pouch_pks, line_pks=()):
    for pouch in services.stocked(Pouch.objects.filter(pk__in=pouch_pks)):
        if (pouch.on_ct or 0) < 0 or (pouch.countable and (pouch.on_pcs or 0) < 0):
            pieces = f" and {pouch.on_pcs or 0} pcs" if pouch.countable else ""
            raise ServiceError(f"Not enough in {pouch}: this would leave it below zero "
                               f"({_ct(pouch.on_ct or 0)} ct{pieces}).")
    for line in dia_services.stocked_lines(DiamondLine.objects.filter(pk__in=line_pks)):
        if (line.on_ct or 0) < 0:
            raise ServiceError(f"Not enough in {line}: this would leave it below zero ({_ct(line.on_ct)} ct).")


def _settle_status(document):
    """Job work and memos close themselves when nothing is outstanding. A job card closes only by
    ``close_document``, but reopens when something is outstanding again (an undo). Every other
    kind — and every reversal — closes when posted."""
    if document.kind in OWED and document.reverses_id is None:
        settled = all(ct == 0 and (pcs == 0 or document.kind in CLOSABLE)
                      for pcs, ct in outstanding(document).values())
        if document.kind in OPENABLE:
            status = Status.CLOSED if settled else Status.OPEN
        else:
            status = document.status if settled else Status.OPEN
    else:
        status = Status.CLOSED
    if document.status != status:
        document.status = status
        document.save(update_fields=["status"])


def _write(user, document, lines, occurred_on=None):
    """Write a document's movements — all of them, or none — check every owner's balance, and
    settle the document's status. Shared by ``post`` (an open document only) and ``undo_last``
    (which may do this on a document already closed)."""
    pouches = {p.pk: p for p in Pouch.objects.select_for_update().filter(
        pk__in={line.owner.pk for line in lines if not _diamond(line.owner)})}
    diamonds = {d.pk: d for d in DiamondLine.objects.select_for_update().filter(
        pk__in={line.owner.pk for line in lines if _diamond(line.owner)})}
    owed = outstanding(document) if document.kind in OWED else {}
    for line in lines:
        held = diamonds if _diamond(line.owner) else pouches
        _check(document, held[line.owner.pk], line, owed)
    at, by = _when(occurred_on), _by(user)
    challan = document.number if document.kind in OPENABLE else ""
    moves = Movement.objects.bulk_create([
        Movement(**{"diamond" if _diamond(line.owner) else "pouch": line.owner}, document=document,
                 reason=line.reason, direction=line.direction, pcs=line.pcs, ct=line.ct, note=line.note,
                 ref=line.ref or document.number, reverses=line.reverses, counterparty=document.vendor,
                 challan_no=challan, occurred_at=at, recorded_by=by)
        for line in lines
    ])
    _check_balances(list(pouches), list(diamonds))
    _settle_status(document)
    log(user, "INSERT", "inv_movement", document.pk, f"{document}: {len(moves)} movement(s)")
    return moves


@transaction.atomic
def post(user, document, lines, occurred_on=None):
    """Write a document's movements — all of them, or none — and settle its status.

    Internal: every caller has already checked the right for its action.
    ``occurred_on`` is the day it happened (``None`` is now). The document is locked and
    re-read first (document, then pouches or lines, as ``undo_last``), so a caller's stale
    copy can never post onto a document reversed or closed a moment ago.
    """
    document.refresh_from_db(from_queryset=StockDocument.objects.select_for_update())
    if document.status != Status.OPEN:
        raise ServiceError(f"{document} is {document.get_status_display().lower()}; it takes no more entries.")
    if not lines and document.reverses_id is None:
        raise ServiceError("Nothing to post.")
    return _write(user, document, lines, occurred_on)


@transaction.atomic
def close_document(user, document):
    """Close a job card by hand — only when nothing is outstanding on any line (owner,
    2026-10-01). Job work and memos close themselves; nothing else is closed by hand."""
    require(user, RIGHT_FOR_KIND[document.kind], "Only a role that posts this kind of document may close it.")
    document = StockDocument.objects.select_for_update().get(pk=document.pk)
    if document.kind not in CLOSABLE:
        raise ServiceError(f"{document} closes itself when nothing is outstanding.")
    if document.status != Status.OPEN:
        raise ServiceError(f"{document} is {document.get_status_display().lower()}; only an open card can close.")
    out = sum((ct for _, ct in outstanding(document).values()), ZERO)
    if out:
        raise ServiceError(f"{document.number} can close only at zero: {_ct(out)} ct outstanding.")
    document.status = Status.CLOSED
    document.save(update_fields=["status"])
    log(user, "UPDATE", "inv_document", document.pk, f"{document} closed")
    return document


def _unfile(document):
    """Put a transferred pouch back where it was, if nothing has re-filed it since."""
    pouch = document.movements.select_related("pouch__batch").get(reverses__isnull=True).pouch
    if (pouch.batch_id, pouch.pouch_no or "") != (document.to_batch_id, document.to_pouch_no):
        raise ServiceError(f"{pouch} has been re-filed since; reverse that transfer first.")
    if document.from_pouch_no and not pouch_no_free(document.from_batch, document.from_pouch_no):
        raise ServiceError(f"{document.from_batch} · {document.from_pouch_no} has been taken since.")
    pouch.batch_id, pouch.pouch_no = document.from_batch_id, document.from_pouch_no or None
    pouch.save(update_fields=["batch", "pouch_no"])


@transaction.atomic
def reverse_document(user, document, note=""):
    """Post the opposite of every movement on it not already reversed, on a new document
    that points back at it, and mark it Reversed. A pouch or line it created stays, at zero."""
    require(user, RIGHT_FOR_KIND[document.kind], "Only a role that posts this kind of document may reverse it.")
    document = StockDocument.objects.select_for_update().get(pk=document.pk)
    if document.status == Status.REVERSED:
        raise ServiceError(f"{document} is already reversed.")
    if document.reverses_id:
        raise ServiceError(f"{document} is itself a reversal; it cannot be reversed.")
    moves = list(document.movements.filter(reverses__isnull=True, reversal__isnull=True)
                 .select_related("pouch", "diamond"))
    created = [m for m in moves if m.direction == Movement.IN and m.reason in CREATING]
    later = (Q(pouch__in=[m.pouch_id for m in created if m.pouch_id])
             | Q(diamond__in=[m.diamond_id for m in created if m.diamond_id]))
    moved = (Movement.objects.filter(later, reverses__isnull=True, reversal__isnull=True)
             .exclude(document=document).select_related("pouch__batch", "diamond").first())
    if moved:
        raise ServiceError(f"{moved.pouch or moved.diamond} has moved since; reverse its later movements first.")
    if document.kind == Kind.TRANSFER:
        _unfile(document)
    reversal = StockDocument.objects.create(
        kind=document.kind, number=next_number(REVERSAL_PREFIX), vendor=document.vendor,
        customer=document.customer, reverses=document, note=note, created_by=_by(user),
    )
    post(user, reversal, [Line(m.pouch or m.diamond, m.reason, m.direction, m.pcs, m.ct,
                               note=f"Reverses {document.number}", reverses=m) for m in moves])
    document.status = Status.REVERSED
    document.save(update_fields=["status"])
    log(user, "REVERSAL", "inv_document", document.pk, f"{document} reversed by {reversal.number}")
    return reversal


@transaction.atomic
def undo_last(user, document):
    """Reverse the latest entry on a job work, a memo or a job card — open, or already closed
    — one wrong line, not the whole document. Never a reversed document, nor any other kind.
    Undoing recomputes the status the same way posting does: something outstanding again
    reopens it (owner, 2026-10-01)."""
    require(user, RIGHT_FOR_KIND[document.kind], "Only a role that posts this kind of document may undo its entries.")
    document = StockDocument.objects.select_for_update().get(pk=document.pk)
    if document.kind not in OWED or document.status not in (Status.OPEN, Status.CLOSED):
        raise ServiceError("Only an open or closed job work or memo, or a job card, has a last entry to undo.")
    last = (document.movements.filter(reverses__isnull=True, reversal__isnull=True)
            .select_related("pouch", "diamond").order_by("-pk").first())
    if last is None:
        raise ServiceError(f"{document} has nothing left to undo.")
    return _write(user, document, [Line(last.pouch or last.diamond, last.reason, last.direction, last.pcs, last.ct,
                                        note=f"Undoes {last.reason}", reverses=last)])[0]
```

- [ ] **Step 4: Reserve the diamond ledgers' routes**

Each stub module below is replaced whole by its wave-4 task. Routing them now lets the rail, the sub-tabs, Search and the top bar link to them while they are built in parallel.

`inventory/views_dia_jobs.py`:

```python
"""Diamond job cards — routed now so the diamond screens can link to one another; built by its own task."""
from django.http import Http404


def jobs(request):
    raise Http404("Not built yet.")


def job_new(request):
    raise Http404("Not built yet.")


def job_post(request, pk):
    raise Http404("Not built yet.")


def job_close(request, pk):
    raise Http404("Not built yet.")


def job_undo(request, pk):
    raise Http404("Not built yet.")


def job_reverse(request, pk):
    raise Http404("Not built yet.")
```

`inventory/views_dia_assort.py`:

```python
"""Diamond assortments — routed now so the diamond screens can link to one another; built by its own task."""
from django.http import Http404


def assorts(request):
    raise Http404("Not built yet.")


def assort_reverse(request, pk):
    raise Http404("Not built yet.")
```

`inventory/views_dia_purchase.py`:

```python
"""Diamond purchases — routed now so the diamond screens can link to one another; built by its own task."""
from django.http import Http404


def purchase(request):
    raise Http404("Not built yet.")


def purchase_reverse(request, pk):
    raise Http404("Not built yet.")
```

`inventory/urls.py`, the import becomes:

```python
from . import (
    views, views_assort, views_dia_assort, views_dia_import, views_dia_jobs, views_dia_purchase, views_dia_settings,
    views_diamonds, views_documents, views_ledger, views_lists, views_purchase,
)
```

and after the `diamonds/settings/` route add:

```python
    path("diamonds/jobs/", views_dia_jobs.jobs, name="dia_jobs"),
    path("diamonds/jobs/new/", views_dia_jobs.job_new, name="dia_job_new"),
    path("diamonds/jobs/<int:pk>/post/", views_dia_jobs.job_post, name="dia_job_post"),
    path("diamonds/jobs/<int:pk>/close/", views_dia_jobs.job_close, name="dia_job_close"),
    path("diamonds/jobs/<int:pk>/undo/", views_dia_jobs.job_undo, name="dia_job_undo"),
    path("diamonds/jobs/<int:pk>/reverse/", views_dia_jobs.job_reverse, name="dia_job_reverse"),
    path("diamonds/assortments/", views_dia_assort.assorts, name="dia_assorts"),
    path("diamonds/assortments/<int:pk>/reverse/", views_dia_assort.assort_reverse, name="dia_assort_reverse"),
    path("diamonds/purchases/", views_dia_purchase.purchase, name="dia_purchase"),
    path("diamonds/purchases/<int:pk>/reverse/", views_dia_purchase.purchase_reverse, name="dia_purchase_reverse"),
```

In `inventory/tests/test_masking.py`, add after `EXEMPT`:

```python
#: the diamond ledgers' screens, routed before they are built so they can link to one another;
#: the masking-walk task walks each of them and deletes this set
PENDING = {
    "inventory:dia_jobs", "inventory:dia_job_new", "inventory:dia_job_post", "inventory:dia_job_close",
    "inventory:dia_job_undo", "inventory:dia_job_reverse", "inventory:dia_assorts", "inventory:dia_assort_reverse",
    "inventory:dia_purchase", "inventory:dia_purchase_reverse",
}
```

and in `test_every_inventory_screen_is_walked`:

```python
    missing = named - covered - EXEMPT - PENDING
```

- [ ] **Step 5: Every part 2 stones test, unchanged**

Run:

```bash
POSTGRES_DB=dialedger_t2 ../nornament-app/.venv/bin/pytest inventory/tests/test_ledger.py \
  inventory/tests/test_ledger_models.py inventory/tests/test_ledger_jobs.py inventory/tests/test_ledger_single.py \
  inventory/tests/test_ledger_purchase.py inventory/tests/test_ledger_assort.py inventory/tests/test_ledger_lists.py \
  inventory/tests/test_document_view.py inventory/tests/test_record_movement.py inventory/tests/test_purchase_view.py \
  inventory/tests/test_assort_views.py inventory/tests/test_movements.py inventory/tests/test_inputs.py -p no:warnings
```

Expected: PASS, with not one of these files edited (`git diff --stat inventory/tests/` shows only `test_masking.py` and the new `test_dia_ledger.py`).

- [ ] **Step 6: Run the rest**

Run: `POSTGRES_DB=dialedger_t2 ../nornament-app/.venv/bin/pytest inventory -p no:warnings`
Expected: PASS. That includes the new file, `test_masking.py` (the reserved names are `PENDING`) and the real-file and parity tests.

- [ ] **Step 7: Commit**

```bash
git add inventory/ledger.py inventory/views_dia_jobs.py inventory/views_dia_assort.py inventory/views_dia_purchase.py \
  inventory/urls.py inventory/tests/test_masking.py inventory/tests/test_dia_ledger.py
git commit -m "$(cat <<'EOF'
The ledger engine moves a pouch or a diamond line; job cards close by hand only at zero; the diamond ledgers' routes

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---
### Task 3: Job cards — the six entries, per-line outstanding, close only at zero

**Files:**
- Create: `inventory/ledger_dia_jobs.py`, `inventory/tests/test_ledger_dia_jobs.py`
- Modify: `inventory/ledger_jobs.py` (`karigar_choices`, one line)

**Interfaces:**
- Consumes:
  - `ledger.open_document/post/Line/outstanding/close_document/undo_last/reverse_document/ZERO`;
  - `dia_services.stocked_lines/line_label/line_choices`;
  - `ledger_jobs.karigar_choices`.
- Produces:
  - `ledger_dia_jobs.ENTRIES`, a dict `{key: (label, reason, direction)}` holding six entries in the prototype's order:

    | key | label | reason | direction |
    |---|---|---|---|
    | `issue` | Issue to job card | Job Work Out | out |
    | `loose` | Received loose | Job Work In | in |
    | `set` | Consumed / set | Consumed in Production | settle |
    | `loss` | Loss in process | Wastage / Loss in Process | settle |
    | `unused` | Returned unused | Returned Unused | in |
    | `breakage` | Breakage | Breakage | settle |

  - `ledger_dia_jobs.ENTRY_LABEL = {reason: label}`.
  - `ledger_dia_jobs.ENTRY_CHOICES = [(key, "Issue to job card — debit"), …]`.
  - `ledger_dia_jobs.open_card(user, karigar, opened_on=None, note="") -> StockDocument`. It needs inv_job. `karigar` is `None` for In-house, otherwise it must be one of `karigar_choices(user)`.
  - `ledger_dia_jobs.post_entry(user, card, entry, line, ct, occurred_on=None, ref="", note="") -> Movement` (inv_job).
  - `ledger_dia_jobs.credit_choices(card) -> [{"pk", "label", "ct"}]`: the card's lines with carats outstanding, each with what is out.
  - `ledger_dia_jobs.owed(card) -> Decimal`: the card's total outstanding.
  - The issue picker is `dia_services.line_choices()`. Closing is `ledger.close_document`, undo is `ledger.undo_last`, and reverse is `ledger.reverse_document`. Task 2's engine has all three, and none is wrapped here.
  - `ledger_jobs.karigar_choices(user)`: for a login without supplier sight, it now offers vendors named on a stones challan **or** a diamond job card.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_ledger_dia_jobs.py`:

```python
"""Diamond job cards, per rule: the six entries, per-line outstanding, close only at zero, refused
after close, undo reopens, reverse."""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from inventory import dia_services, ledger, ledger_jobs
from inventory.ledger_dia_jobs import ENTRY_CHOICES, ENTRY_LABEL, credit_choices, open_card, owed, post_entry
from inventory.models import Movement, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
S, R = StockDocument.Status, Movement.Reason


def _ct(line):
    return dia_services.stocked_lines().get(pk=line.pk).on_ct


@pytest.fixture
def card(accounts_user, diamonds, parties):
    """The prototype's JC card: both lines issued on one challan."""
    card = open_card(accounts_user, parties["karigar"], date(2026, 5, 4))
    post_entry(accounts_user, card, "issue", diamonds["round"], D("3.40"), date(2026, 5, 4), "CH 2026/0417")
    post_entry(accounts_user, card, "issue", diamonds["princess"], D("0.85"), date(2026, 5, 4), "CH 2026/0417")
    return card


def test_a_card_opens_numbered_with_its_karigar_or_in_house(accounts_user, diamonds, parties):
    first = open_card(accounts_user, parties["karigar"], date(2026, 5, 4), "rings for the Diwali order")
    assert (first.number, first.kind, first.status) == ("JC-000001", StockDocument.Kind.DIA_JOB, S.OPEN)
    assert (first.vendor, first.occurred_on, first.note) == (parties["karigar"], date(2026, 5, 4),
                                                            "rings for the Diwali order")
    assert open_card(accounts_user, None).vendor is None


def test_an_issue_takes_the_carats_off_the_line(card, diamonds):
    assert (_ct(diamonds["round"]), _ct(diamonds["princess"])) == (D("0"), D("0"))
    first = card.movements.order_by("pk").first()
    assert (first.reason, first.direction, first.ref, first.counterparty) == (
        R.JOB_WORK_OUT, Movement.OUT, "CH 2026/0417", card.vendor)
    assert timezone.localtime(first.occurred_at).date() == date(2026, 5, 4)
    assert owed(card) == D("4.25")


def test_the_six_entries_and_how_each_moves(accounts_user, card, diamonds):
    rnd = diamonds["round"]
    post_entry(accounts_user, card, "loose", rnd, D("0.85"), ref="CH 2026/0417")   # back into the line
    post_entry(accounts_user, card, "unused", rnd, D("0.40"))                       # never worked: back too
    post_entry(accounts_user, card, "set", rnd, D("1.50"), ref="JOB")               # settled, not returned
    post_entry(accounts_user, card, "loss", rnd, D("0.05"))
    post_entry(accounts_user, card, "breakage", rnd, D("0.10"))
    assert _ct(rnd) == D("1.25")
    assert ledger.outstanding(card)[rnd.pk] == (0, D("0.50"))
    posted = list(card.movements.order_by("pk").values_list("reason", "direction"))[2:]
    assert posted == [(R.JOB_WORK_IN, "in"), (R.RETURNED_UNUSED, "in"), (R.CONSUMED, "settle"),
                      (R.WASTAGE, "settle"), (R.BREAKAGE, "settle")]
    assert [ENTRY_LABEL[reason] for reason, _ in posted] == [
        "Received loose", "Returned unused", "Consumed / set", "Loss in process", "Breakage"]


def test_the_stock_control_select_reads_as_the_prototype():
    assert ENTRY_CHOICES == [("issue", "Issue to job card — debit"), ("loose", "Received loose — credit"),
                             ("set", "Consumed / set — credit"), ("loss", "Loss in process — credit"),
                             ("unused", "Returned unused — credit"), ("breakage", "Breakage — credit")]


def test_a_credit_settles_only_its_own_line(accounts_user, card, diamonds):
    with pytest.raises(ServiceError, match="cannot exceed what is outstanding"):
        post_entry(accounts_user, card, "set", diamonds["princess"], D("1.00"))     # 0.85 out on that line
    with pytest.raises(ServiceError, match="cannot exceed"):
        post_entry(accounts_user, card, "loose", diamonds["polki"], D("0.10"))       # never issued here
    assert [(c["pk"], c["ct"]) for c in credit_choices(card)] == [
        (diamonds["round"].pk, D("3.40")), (diamonds["princess"].pk, D("0.85"))]
    assert credit_choices(card)[0]["label"] == "NRD-000001 · DRFGH VS-SI · +6-12 · B-771"


def test_a_card_closes_only_at_zero_and_then_takes_nothing(accounts_user, card, diamonds):
    with pytest.raises(ServiceError, match="can close only at zero: 4.25 ct outstanding"):
        ledger.close_document(accounts_user, card)
    post_entry(accounts_user, card, "set", diamonds["round"], D("3.40"))
    post_entry(accounts_user, card, "unused", diamonds["princess"], D("0.85"))
    card.refresh_from_db()
    assert card.status == S.OPEN                          # balanced, but only Close closes it
    ledger.close_document(accounts_user, card)
    card.refresh_from_db()
    assert card.status == S.CLOSED
    with pytest.raises(ServiceError, match="is closed; it takes no more entries"):
        post_entry(accounts_user, card, "issue", diamonds["polki"], D("1"))


def test_undo_reopens_a_closed_card(accounts_user, card, diamonds):
    post_entry(accounts_user, card, "set", diamonds["round"], D("3.40"))
    post_entry(accounts_user, card, "unused", diamonds["princess"], D("0.85"))
    ledger.close_document(accounts_user, card)
    ledger.undo_last(accounts_user, card)
    card.refresh_from_db()
    assert card.status == S.OPEN and owed(card) == D("0.85") and _ct(diamonds["princess"]) == D("0")


def test_reversing_a_card_puts_its_lines_back_and_it_takes_nothing_more(accounts_user, card, diamonds):
    post_entry(accounts_user, card, "loose", diamonds["round"], D("1"))
    ledger.reverse_document(accounts_user, card)
    card.refresh_from_db()
    assert card.status == S.REVERSED
    assert (_ct(diamonds["round"]), _ct(diamonds["princess"])) == (D("3.40"), D("0.85"))
    with pytest.raises(ServiceError, match="is reversed; it takes no more entries"):
        post_entry(accounts_user, card, "issue", diamonds["round"], D("1"))


def test_an_issue_cannot_take_more_than_the_line_holds(accounts_user, diamonds):
    card = open_card(accounts_user, None)
    with pytest.raises(ServiceError, match="below zero"):
        post_entry(accounts_user, card, "issue", diamonds["princess"], D("0.9"))


@pytest.mark.parametrize("entry, line, ct, words", [
    ("swap", "round", "1", "Choose the stock-control entry"),
    ("issue", None, "1", "Choose the line"),
    ("issue", "round", None, "needs carats above zero"),
    ("issue", "round", "0.00001", "more than 4 decimal places"),
])
def test_an_entry_needs_its_kind_its_line_and_its_carats(accounts_user, diamonds, entry, line, ct, words):
    from inventory import inputs

    card = open_card(accounts_user, None)
    with pytest.raises(ServiceError, match=words):
        post_entry(accounts_user, card, entry, diamonds[line] if line else None, inputs.decimal(ct, "Carats"))
    assert not card.movements.exists()


def test_a_job_card_needs_the_right(sales_user, accounts_user, diamonds):
    with pytest.raises(PermissionDenied):
        open_card(sales_user, None)
    card = open_card(accounts_user, None)
    with pytest.raises(PermissionDenied):
        post_entry(sales_user, card, "issue", diamonds["round"], D("1"))


def test_the_karigar_desk_names_only_karigars_already_on_a_challan_or_card(karigar_user, accounts_user, diamonds,
                                                                           parties):
    with pytest.raises(ServiceError, match="Choose the karigar"):
        open_card(karigar_user, parties["karigar"])                     # never named anywhere yet
    assert open_card(karigar_user, None).vendor is None                  # In-house is always there
    open_card(accounts_user, parties["karigar"])                         # named once, by a login that sees suppliers
    assert open_card(karigar_user, parties["karigar"]).vendor == parties["karigar"]
    assert diamonds["supplier"].pk not in {c["pk"] for c in ledger_jobs.karigar_choices(karigar_user)}
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=dialedger_t3 ../nornament-app/.venv/bin/pytest inventory/tests/test_ledger_dia_jobs.py -p no:warnings`
Expected: FAIL with `No module named 'inventory.ledger_dia_jobs'`.

- [ ] **Step 3: Write `inventory/ledger_dia_jobs.py`**

```python
"""Diamond job cards: diamonds issued to a karigar, or in-house, on a card that is a ledger.

An issue is a debit: out of the line, owed by the card. Received loose and
returned unused are credits that come back into the line; consumed / set, loss
in process and breakage are credits that settle what is out without returning
it. Each entry carries its own date and challan or reference, so one card spans
several challans. A card stays open — more may be issued to it — until someone
closes it, and only at zero (``ledger.close_document``).
"""
from django.db import transaction
from django.utils import timezone

from accounts.capabilities import INV_JOB
from stock.services import ServiceError, require

from . import dia_services, ledger, ledger_jobs
from .models import DiamondLine, Movement, StockDocument

Kind, Reason = StockDocument.Kind, Movement.Reason

#: the prototype's six stock-control entries, in its order: (label, reason, direction)
ENTRIES = {
    "issue": ("Issue to job card", Reason.JOB_WORK_OUT, Movement.OUT),
    "loose": ("Received loose", Reason.JOB_WORK_IN, Movement.IN),
    "set": ("Consumed / set", Reason.CONSUMED, Movement.SETTLE),
    "loss": ("Loss in process", Reason.WASTAGE, Movement.SETTLE),
    "unused": ("Returned unused", Reason.RETURNED_UNUSED, Movement.IN),
    "breakage": ("Breakage", Reason.BREAKAGE, Movement.SETTLE),
}
#: the entry a movement on a card was posted as, for the ledger's chip
ENTRY_LABEL = {reason: label for label, reason, _ in ENTRIES.values()}
#: the "Stock control" select, in the prototype's words: a debit goes out, a credit comes back or settles
ENTRY_CHOICES = [(key, f"{label} — {'debit' if direction == Movement.OUT else 'credit'}")
                 for key, (label, _, direction) in ENTRIES.items()]


@transaction.atomic
def open_card(user, karigar, opened_on=None, note=""):
    """A new open card, numbered ``JC-…``. ``karigar`` is ``None`` for In-house, else one of
    ``ledger_jobs.karigar_choices(user)``: the masked choice list is the rule, as on a stones
    challan, so the Karigar desk cannot name a supplier it has never been shown."""
    require(user, INV_JOB, "Only a role that posts job cards can open one.")
    if karigar is not None and karigar.pk not in {choice["pk"] for choice in ledger_jobs.karigar_choices(user)}:
        raise ServiceError("Choose the karigar, or In-house.")
    return ledger.open_document(user, Kind.DIA_JOB, occurred_on=opened_on or timezone.localdate(),
                                vendor=karigar, note=(note or "").strip())


@transaction.atomic
def post_entry(user, card, entry, line, ct, occurred_on=None, ref="", note=""):
    """One entry on an open card, dated and referenced on its own. A credit is checked against
    what that line has out on this card; an issue against what the line holds."""
    require(user, INV_JOB, "Only a role that posts job cards can post an entry.")
    if card.kind != Kind.DIA_JOB:
        raise ServiceError(f"{card} is not a job card.")
    if entry not in ENTRIES:
        raise ServiceError("Choose the stock-control entry.")
    if line is None:
        raise ServiceError("Choose the line.")
    _, reason, direction = ENTRIES[entry]
    move = ledger.Line(line, reason, direction, None, ct, note=(note or "").strip(), ref=(ref or "").strip())
    return ledger.post(user, card, [move], occurred_on)[0]


def credit_choices(card):
    """The lines this card still has out, each with what is outstanding on it: what a credit may name."""
    out = {pk: ct for pk, (_, ct) in ledger.outstanding(card).items() if ct > 0}
    lines = dia_services.stocked_lines(DiamondLine.objects.filter(pk__in=out))
    return [{"pk": line.pk, "label": dia_services.line_label(line), "ct": out[line.pk]} for line in lines]


def owed(card):
    """The carats the card still has out, all lines together."""
    return sum((ct for _, ct in ledger.outstanding(card).values()), ledger.ZERO)
```

The `"more than 4 decimal places"` case is refused by `inputs.decimal` before it reaches the service. It sits in this test because that read is the one every job-card form uses.

- [ ] **Step 4: A karigar named on a job card is a karigar the Karigar desk may name**

In `inventory/ledger_jobs.py`, `karigar_choices` becomes:

```python
def karigar_choices(user):
    """Who goods may go to on job work, or a diamond job card, as this login may see them.

    Karigars and suppliers share one list. A login without sight of suppliers
    (the Karigar desk) is offered only those already named on a challan or a
    job card, so the list never shows it a supplier.
    """
    vendors = Vendor.objects.filter(is_active=True)
    if not allowed(user, "vendor_name"):
        named = StockDocument.objects.filter(kind__in=(Kind.JOB_WORK, Kind.DIA_JOB)).values("vendor")
        vendors = vendors.filter(pk__in=named)
    return [mask(user, {"pk": v.pk, "karigar_name": v.name}) for v in vendors.order_by("name")]
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=dialedger_t3 ../nornament-app/.venv/bin/pytest inventory/tests/test_ledger_dia_jobs.py inventory/tests/test_ledger_jobs.py inventory/tests/test_record_movement.py -p no:warnings`
Expected: PASS. The two stones files run unchanged, because `karigar_choices` feeds the stones Record movement form.

- [ ] **Step 6: Commit**

```bash
git add inventory/ledger_dia_jobs.py inventory/ledger_jobs.py inventory/tests/test_ledger_dia_jobs.py
git commit -m "$(cat <<'EOF'
Diamond job cards: the six entries, credits per line, Close only at zero

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Assortments — destinations become new lines, the parcel's cost kept whole

**Files:**
- Create: `inventory/ledger_dia_assort.py`, `inventory/tests/test_ledger_dia_assort.py`

**Interfaces:**
- Consumes:
  - `ledger.open_document/post/Line/reverse_document/_ct`;
  - `dia_services.stocked_lines/rate_table/price/new_line/code_for/sized/term`;
  - `DiamondLineCost`.
- Produces:
  - dataclass `ledger_dia_assort.Destination(shape, colour, clarity, size_text, ct, cost_per_ct=None)`. The first three are master-list values. A blank `size_text` is the source's size, and `cost_per_ct` is an override.
  - `ledger_dia_assort.post_assortment(user, source, take_out, destinations, loss=None, occurred_on=None, note="") -> StockDocument`. It needs inv_assort, and view_cost as well when any override is given. The document is `AS-…` and is closed when posted.
  - The movements it writes, all on that one document:
    - on the source: `Assort Out` of (take out − loss), and a `Wastage / Loss in Process` out of the loss (notes `source parcel` and `Sorting loss`);
    - on each new line: `Assort In` of its carats (note `from NRD-…`).
  - Each new line gets one `DiamondLineCost` row, dated the assortment's date, with `document` set: its override, or else the source's cost × take out ÷ (take out − loss) to 4 places. A source with no cost writes no row.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_ledger_dia_assort.py`:

```python
"""Assortment, per rule: balances to 4 places, new lines, weight that stays in grade, the loss,
cost carried with the loss absorbed, an override, a source with no cost, refusals, reversal."""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied

from accounts.models import User
from inventory import dia_services, ledger
from inventory.ledger_dia_assort import Destination, post_assortment
from inventory.models import DiamondLine, DiamondLineCost, Movement, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
K, S, R = StockDocument.Kind, StockDocument.Status, Movement.Reason
CARRIED = D("16940.5128")            # ₹16,517 × 2.00 ct ÷ (2.00 − 0.05) ct, to 4 places


def _line(pk):
    return dia_services.stocked_lines().get(pk=pk)


def _ct(line):
    return _line(line.pk).on_ct


def _cost(line):
    return dia_services.price(_line(line.pk), dia_services.rate_table())[0]


def _new(doc):
    return [m.diamond for m in doc.movements.filter(reason=R.ASSORT_IN)
            .select_related("diamond__code", "diamond__band", "diamond__category").order_by("pk")]


def _dests():
    return [Destination("Round", "E-F", "VVS-VS", "+6-12", D("1.20")),     # upgraded on a re-look
            Destination("Round", "I-J", "SI-I", "+2", D("0.75"))]          # downgraded, smaller sieve


def test_a_balanced_assortment_makes_new_lines_and_leaves_the_rest_in_grade(accounts_user, diamonds):
    rnd = diamonds["round"]
    doc = post_assortment(accounts_user, rnd, D("2.00"), _dests(), D("0.05"), date(2026, 8, 2),
                          "re-sieved after client return")
    assert (doc.kind, doc.number, doc.status, doc.note) == (K.DIA_ASSORT, "AS-000001", S.CLOSED,
                                                           "re-sieved after client return")
    assert _ct(rnd) == D("1.40")                                       # what stayed in grade stays on the source
    up, down = _new(doc)
    assert (up.code_id, up.category, up.batch_no, up.size_text, up.band.value) == (
        "DREF VVS-VS", rnd.category, "B-771", "+6-12", "+6-11")
    assert (down.code_id, down.band.value, down.code.confirmed) == ("DRIJ SI-I", "+2-6", True)
    assert (_ct(up), _ct(down)) == (D("1.20"), D("0.75"))
    assert list(doc.movements.order_by("pk").values_list("reason", "direction", "ct")) == [
        (R.ASSORT_OUT, "out", D("1.95")), (R.WASTAGE, "out", D("0.05")),
        (R.ASSORT_IN, "in", D("1.20")), (R.ASSORT_IN, "in", D("0.75"))]


def test_the_cost_is_carried_with_the_loss_absorbed(accounts_user, diamonds):
    doc = post_assortment(accounts_user, diamonds["round"], D("2.00"), _dests(), D("0.05"), date(2026, 8, 2))
    up, down = _new(doc)
    assert (_cost(up), _cost(down)) == (CARRIED, CARRIED)
    rows = DiamondLineCost.objects.filter(document=doc)
    assert rows.count() == 2 and {r.effective_from for r in rows} == {date(2026, 8, 2)}
    # the parcel's cost is kept whole: 1.95 ct at the carried rate is what 2.00 ct cost at the source's
    assert abs(D("1.95") * CARRIED - D("2.00") * D("16517")) < D("0.01")


def test_an_override_sets_that_destinations_cost(accounts_user, diamonds):
    dests = _dests()
    dests[0].cost_per_ct = D("20000")
    up, down = _new(post_assortment(accounts_user, diamonds["round"], D("2.00"), dests, D("0.05")))
    assert (_cost(up), _cost(down)) == (D("20000"), CARRIED)


def test_a_source_with_no_cost_gives_no_own_cost(accounts_user, diamonds):
    doc = post_assortment(accounts_user, diamonds["princess"], D("0.85"),
                          [Destination("Princess", "G", "VS1", "", D("0.85"))])
    (child,) = _new(doc)
    assert not DiamondLineCost.objects.filter(line=child).exists()
    assert child.size_text == "+2"                                     # a blank size keeps the source's
    assert dia_services.price(_line(child.pk), dia_services.rate_table()) == (None, None)


@pytest.mark.parametrize("take_out, loss, words", [
    (D("2.00"), None, "0.05 ct unaccounted"),
    (D("1.90"), D("0.05"), "-0.1 ct unaccounted"),
    (D("2.0001"), D("0.05"), "0.0001 ct unaccounted"),
    (None, None, "taken out"),
])
def test_an_assortment_must_balance_to_four_places(accounts_user, diamonds, take_out, loss, words):
    with pytest.raises(ServiceError, match=words):
        post_assortment(accounts_user, diamonds["round"], take_out, _dests(), loss)
    assert not StockDocument.objects.exists() and _ct(diamonds["round"]) == D("3.40")


def test_every_destination_needs_carats_and_a_listed_description(accounts_user, diamonds):
    with pytest.raises(ServiceError, match="Every destination needs carats"):
        post_assortment(accounts_user, diamonds["round"], D("1"), [Destination("Round", "G", "VS1", "", None)])
    with pytest.raises(ServiceError, match="Cushion is not on the shape list"):
        post_assortment(accounts_user, diamonds["round"], D("1"), [Destination("Cushion", "G", "VS1", "", D("1"))])
    with pytest.raises(ServiceError, match="Add at least one destination"):
        post_assortment(accounts_user, diamonds["round"], D("1"), [], D("1"))
    assert not StockDocument.objects.exists() and DiamondLine.objects.count() == 3


def test_taking_out_more_than_the_line_holds_is_refused(accounts_user, diamonds):
    with pytest.raises(ServiceError, match="below zero"):
        post_assortment(accounts_user, diamonds["princess"], D("1"), [Destination("Princess", "G", "VS1", "", D("1"))])
    assert DiamondLine.objects.count() == 3


def test_an_untouched_assortment_reverses_whole(accounts_user, diamonds):
    doc = post_assortment(accounts_user, diamonds["round"], D("2.00"), _dests(), D("0.05"))
    up, down = _new(doc)
    ledger.reverse_document(accounts_user, doc)
    assert (_ct(diamonds["round"]), _ct(up), _ct(down)) == (D("3.40"), D("0"), D("0"))


def test_reversal_is_refused_once_a_new_line_has_moved(accounts_user, diamonds):
    doc = post_assortment(accounts_user, diamonds["round"], D("2.00"), _dests(), D("0.05"))
    up, _ = _new(doc)
    card = ledger.open_document(accounts_user, K.DIA_JOB)
    ledger.post(accounts_user, card, [ledger.Line(up, R.JOB_WORK_OUT, Movement.OUT, None, D("0.5"))])
    with pytest.raises(ServiceError, match="has moved since"):
        ledger.reverse_document(accounts_user, doc)


def test_assorting_needs_the_right_and_an_override_needs_sight_of_cost(production_user, accounts_user, diamonds):
    with pytest.raises(PermissionDenied):
        post_assortment(production_user, diamonds["round"], D("2.00"), _dests(), D("0.05"))
    Group.objects.get(name="ACCOUNTS").permissions.remove(Permission.objects.get(codename="view_cost"))
    blind = User.objects.get(pk=accounts_user.pk)                     # a fresh object: no cached permissions
    dests = _dests()
    dests[0].cost_per_ct = D("20000")
    with pytest.raises(PermissionDenied):
        post_assortment(blind, diamonds["round"], D("2.00"), dests, D("0.05"))
    post_assortment(blind, diamonds["round"], D("2.00"), _dests(), D("0.05"))   # a carried cost needs no sight of it
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=dialedger_t4 ../nornament-app/.venv/bin/pytest inventory/tests/test_ledger_dia_assort.py -p no:warnings`
Expected: FAIL with `No module named 'inventory.ledger_dia_assort'`.

- [ ] **Step 3: Write `inventory/ledger_dia_assort.py`**

```python
"""Diamond assortment: re-grading part of a line's carats into new lines.

Sorting moves weight; it does not make or lose it. What is taken out of the
source line equals what goes into the destinations plus the sorting loss, to 4
places. Each destination becomes a new line with the source's category and
batch no.; weight that stays in grade simply stays on the source. The parcel's
cost is kept whole: the destinations' cost per carat absorbs the loss, so what
the carats cost does not shrink because some were lost in sorting.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from accounts.capabilities import INV_ASSORT, VIEW_COST
from stock.services import ServiceError, require

from . import dia_services, ledger
from .models import DiamondLine, DiamondLineCost, DiamondTerm, Movement, StockDocument

ZERO, PLACES = Decimal("0"), Decimal("0.0001")
Reason = Movement.Reason


@dataclass
class Destination:
    shape: str
    colour: str
    clarity: str
    size_text: str                          # blank: the source's size
    ct: Decimal | None
    cost_per_ct: Decimal | None = None      # an override; else carried from the source


def _by(user):
    return user if getattr(user, "is_authenticated", False) else None


def _check(source, take_out, destinations, loss):
    if source is None:
        raise ServiceError("Choose the source line.")
    if take_out is None or take_out <= 0:
        raise ServiceError("Enter the carats taken out of the source line.")
    if not destinations:
        raise ServiceError("Add at least one destination.")
    if any(d.ct is None or d.ct <= 0 for d in destinations):
        raise ServiceError("Every destination needs carats.")
    if any(d.cost_per_ct is not None and d.cost_per_ct <= 0 for d in destinations):
        raise ServiceError("A cost per carat must be positive.")
    if loss < 0:
        raise ServiceError("A sorting loss cannot be negative.")
    unaccounted = take_out - sum((d.ct for d in destinations), loss)
    if unaccounted:
        raise ServiceError(f"{ledger._ct(unaccounted)} ct unaccounted — an assortment must balance.")


@transaction.atomic
def post_assortment(user, source, take_out, destinations, loss=None, occurred_on=None, note=""):
    """Take ``take_out`` carats from ``source`` into new lines, less a sorting loss written off on
    the source. Posts only when it balances; the new lines, their codes and their costs are
    written in the same transaction, so a refusal leaves none of them."""
    require(user, INV_ASSORT, "Only a role that assorts can post an assortment.")
    if any(d.cost_per_ct is not None for d in destinations):
        require(user, VIEW_COST, "A cost you may not see is not yours to set.")
    loss = loss or ZERO
    _check(source, take_out, destinations, loss)
    held = dia_services.stocked_lines(DiamondLine.objects.filter(pk=source.pk)).get()
    cost = dia_services.price(held, dia_services.rate_table())[0]
    carried = (cost * take_out / (take_out - loss)).quantize(PLACES) if cost is not None else None
    document = ledger.open_document(user, StockDocument.Kind.DIA_ASSORT,
                                    occurred_on=occurred_on or timezone.localdate(), note=(note or "").strip())
    lines = [ledger.Line(source, Reason.ASSORT_OUT, Movement.OUT, None, take_out - loss, note="source parcel")]
    if loss:
        lines.append(ledger.Line(source, Reason.WASTAGE, Movement.OUT, None, loss, note="Sorting loss"))
    costs = []
    for d in destinations:
        size = (d.size_text or "").strip() or source.size_text
        sized = dia_services.sized(size)
        line = dia_services.new_line(
            category=source.category, code=dia_services.code_for(user, d.shape, d.colour, d.clarity),
            batch_no=source.batch_no, size_text=size, band=dia_services.term(DiamondTerm.BAND, sized.band),
            ct_lo=sized.ct_lo, ct_hi=sized.ct_hi,
        )
        lines.append(ledger.Line(line, Reason.ASSORT_IN, Movement.IN, None, d.ct, note=f"from {source.ref}"))
        rate = d.cost_per_ct if d.cost_per_ct is not None else carried
        if rate is not None:
            costs.append(DiamondLineCost(line=line, cost_rate=rate, effective_from=document.occurred_on,
                                         set_by=_by(user), document=document))
    ledger.post(user, document, lines, occurred_on)
    DiamondLineCost.objects.bulk_create(costs)
    return document
```

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=dialedger_t4 ../nornament-app/.venv/bin/pytest inventory/tests/test_ledger_dia_assort.py -p no:warnings`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add inventory/ledger_dia_assort.py inventory/tests/test_ledger_dia_assort.py
git commit -m "$(cat <<'EOF'
Diamond assortments: balanced to 4 places, destinations as new lines, cost carried with the loss absorbed

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Diamond purchases — described lines, codes found or made, a landed cost per line

**Files:**
- Create: `inventory/ledger_dia_purchase.py`, `inventory/tests/test_ledger_dia_purchase.py`
- Modify: `inventory/ledger_purchase.py` (extract `check_header`)

**Interfaces:**
- Consumes:
  - `ledger.open_document/post/Line/reverse_document`;
  - `ledger_purchase.PurchaseHeader/PURCHASE_RIGHTS`;
  - `dia_services.listed/code_for/sized/new_line/term/price/rate_table`;
  - `DiamondLineCost`.
- Produces:
  - `ledger_purchase.check_header(header, lines)`. It raises on a missing supplier, no lines, a currency other than INR or USD, USD without a rate, a rate ≤ 0, or negative extras. The stones purchase and the diamond purchase share it, so the stones messages are unchanged.
  - dataclass `ledger_dia_purchase.DiaPurchaseLine(category, shape, colour, clarity, size_text, pcs, ct, cost_per_ct, batch_no="")`. The first four are master-list values, and `pcs` is optional.
  - `ledger_dia_purchase.post_dia_purchase(user, header, lines) -> StockDocument`. It needs all of `PURCHASE_RIGHTS`. The document is a `DIA_PURCHASE`, numbered by the invoice no. or `DP-…`, and closed when posted. Each line becomes:
    - a new line, with its code found or made from shape + colour + clarity and its band from the size (per-stone rule included);
    - a `Purchase` in movement carrying pieces and carats;
    - a `DiamondLineCost` of cost × rate + extras ÷ total carats, to 4 places, dated the purchase date.
  - It never writes `DiamondRate`, and never touches a sale price.
  - The view, not this service, creates a new supplier, inside the same transaction (Task 8, the stones precedent).

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_ledger_dia_purchase.py`:

```python
"""Diamond purchase, per rule: new lines; the code found or created; INR and USD cost with landed
extras; the rate card and sale untouched; the checks; reversal."""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied

from accounts.models import User
from inventory import dia_services, ledger
from inventory.ledger_dia_purchase import DiaPurchaseLine, post_dia_purchase
from inventory.ledger_purchase import PurchaseHeader
from inventory.models import DiamondLine, DiamondRate, Movement, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
K, S, R = StockDocument.Kind, StockDocument.Status, Movement.Reason


def _line(pk):
    return dia_services.stocked_lines().get(pk=pk)


def _bought(doc):
    return [m.diamond for m in doc.movements.select_related(
        "diamond__category", "diamond__band", "diamond__code").order_by("pk")]


def _header(supplier, **changes):
    return PurchaseHeader(supplier=supplier, occurred_on=date(2026, 8, 7), invoice_no="2026/0442", **changes)


def _lines():
    """The prototype's two lines: 14.20 ct round at ₹16,500 and 3.60 ct princess at ₹21,000."""
    return [DiaPurchaseLine("Natural Diamond", "Round", "F-G-H", "VS-SI", "+6-12", None, D("14.20"), D("16500"),
                            "B-901"),
            DiaPurchaseLine("Natural Diamond", "Princess", "E-F", "VVS-VS", "+2", 40, D("3.60"), D("21000"))]


def test_each_line_becomes_a_new_line_with_its_own_cost(accounts_user, diamonds):
    supplier = diamonds["supplier"]
    doc = post_dia_purchase(accounts_user, _header(supplier, landed_extras=D("1780")), _lines())
    assert (doc.kind, doc.number, doc.status, doc.vendor, doc.currency, doc.landed_extras) == (
        K.DIA_PURCHASE, "2026/0442", S.CLOSED, supplier, "INR", D("1780"))
    rnd, princess = _bought(doc)
    assert (rnd.ref, rnd.code_id, rnd.category.value, rnd.batch_no, rnd.size_text, rnd.band.value) == (
        "NRD-000004", "DRFGH VS-SI", "Natural Diamond", "B-901", "+6-12", "+6-11")
    assert (princess.ref, princess.code_id, princess.band.value, princess.batch_no) == (
        "NRD-000005", "DPCEF VVS-VS", "+2-6", "")
    assert list(doc.movements.order_by("pk").values_list("reason", "direction", "pcs", "ct")) == [
        (R.PURCHASE, "in", None, D("14.20")), (R.PURCHASE, "in", 40, D("3.60"))]
    rates = dia_services.rate_table()
    # ₹1,780 ÷ 17.80 ct = ₹100 a carat on top; the own cost wins over the rate card's ₹16,517
    assert dia_services.price(_line(rnd.pk), rates) == (D("16600"), D("21013"))
    assert dia_services.price(_line(princess.pk), rates) == (D("21100"), None)


def test_a_new_description_makes_a_confirmed_code(accounts_user, diamonds):
    line = DiaPurchaseLine("Natural Diamond", "Round", "G", "VS1", "+6", None, D("1"), D("30000"))
    (fresh,) = _bought(post_dia_purchase(accounts_user, _header(diamonds["supplier"]), [line]))
    assert (fresh.code_id, fresh.code.confirmed, fresh.band.value) == ("DRG VS1", True, "+6-11")


def test_a_usd_purchase_needs_its_rate_and_is_costed_in_inr(accounts_user, diamonds):
    line = [DiaPurchaseLine("Natural Diamond", "Round", "F-G-H", "VS-SI", "+6-12", None, D("2"), D("200"))]
    with pytest.raises(ServiceError, match="USD needs the rate"):
        post_dia_purchase(accounts_user, _header(diamonds["supplier"], currency="USD"), line)
    with pytest.raises(ServiceError, match="rate must be positive"):
        post_dia_purchase(accounts_user, _header(diamonds["supplier"], currency="USD", fx_rate=D("-1")), line)
    doc = post_dia_purchase(accounts_user, _header(diamonds["supplier"], currency="USD", fx_rate=D("83.5"),
                                                   landed_extras=D("100")), line)
    (fresh,) = _bought(doc)
    assert doc.fx_rate == D("83.5")
    assert dia_services.price(_line(fresh.pk), dia_services.rate_table())[0] == D("16750")   # 200 × 83.5 + 100 ÷ 2


def test_the_rate_card_and_sale_prices_are_untouched(accounts_user, diamonds):
    before = list(DiamondRate.objects.values_list("pk", "code", "size_text", "cost_rate", "sale_rate"))
    post_dia_purchase(accounts_user, _header(diamonds["supplier"]), _lines())
    assert list(DiamondRate.objects.values_list("pk", "code", "size_text", "cost_rate", "sale_rate")) == before
    assert dia_services.price(_line(diamonds["round"].pk), dia_services.rate_table()) == (D("16517"), D("21013"))


@pytest.mark.parametrize("field, value, words", [
    ("clarity", "", "needs category, shape, colour, clarity and size"),
    ("size_text", " ", "needs category, shape, colour, clarity and size"),
    ("category", "Moissanite", "Moissanite is not on the category list"),
    ("shape", "Cushion", "Cushion is not on the shape list"),
    ("ct", D("0"), "weight must be positive"),
    ("cost_per_ct", None, "cost per carat must be positive"),
])
def test_every_line_is_described_weighed_and_costed(accounts_user, diamonds, field, value, words):
    lines = _lines()
    setattr(lines[1], field, value)
    with pytest.raises(ServiceError, match=words):
        post_dia_purchase(accounts_user, _header(diamonds["supplier"]), lines)
    assert not StockDocument.objects.exists() and DiamondLine.objects.count() == 3


def test_a_supplier_and_a_line_are_required(accounts_user, diamonds):
    with pytest.raises(ServiceError, match="Choose the supplier"):
        post_dia_purchase(accounts_user, _header(None), _lines())
    with pytest.raises(ServiceError, match="at least one line"):
        post_dia_purchase(accounts_user, _header(diamonds["supplier"]), [])


def test_no_invoice_no_draws_an_automatic_number_and_a_typed_one_is_unique(accounts_user, diamonds):
    assert post_dia_purchase(accounts_user, _header(diamonds["supplier"], invoice_no=""), _lines()[:1]).number == "DP-000001"
    post_dia_purchase(accounts_user, _header(diamonds["supplier"]), _lines()[:1])
    with pytest.raises(ServiceError, match="already exists"):
        post_dia_purchase(accounts_user, _header(diamonds["supplier"]), _lines()[:1])


def test_a_size_that_reads_as_no_band_is_banded_per_stone(accounts_user, diamonds):
    line = DiaPurchaseLine("Natural Diamond", "Round", "F-G-H", "VS-SI", "mixed", 8, D("2"), D("16000"))
    (fresh,) = _bought(post_dia_purchase(accounts_user, _header(diamonds["supplier"]), [line]))
    assert (fresh.band.value, fresh.ct_lo, fresh.ct_hi) == ("carat band", D("0.250"), D("0.250"))


def test_a_purchase_needs_the_right_and_sight_of_cost_and_suppliers(production_user, accounts_user, diamonds):
    with pytest.raises(PermissionDenied):
        post_dia_purchase(production_user, _header(diamonds["supplier"]), _lines())
    Group.objects.get(name="ACCOUNTS").permissions.remove(Permission.objects.get(codename="view_vendor"))
    with pytest.raises(PermissionDenied):
        post_dia_purchase(User.objects.get(pk=accounts_user.pk), _header(diamonds["supplier"]), _lines())


def test_a_reversed_purchase_leaves_its_lines_at_zero(accounts_user, diamonds):
    doc = post_dia_purchase(accounts_user, _header(diamonds["supplier"]), _lines())
    ledger.reverse_document(accounts_user, doc)
    assert [_line(line.pk).on_ct for line in _bought(doc)] == [D("0"), D("0")]
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=dialedger_t5 ../nornament-app/.venv/bin/pytest inventory/tests/test_ledger_dia_purchase.py -p no:warnings`
Expected: FAIL with `No module named 'inventory.ledger_dia_purchase'`.

- [ ] **Step 3: One header check for both purchases**

In `inventory/ledger_purchase.py`, replace `_check` with:

```python
def check_header(header, lines):
    """What every purchase's header needs, stones or diamonds: a supplier, a line, and INR or USD
    with its rate to INR."""
    if header.supplier is None:
        raise ServiceError("Choose the supplier.")
    if not lines:
        raise ServiceError("Add at least one line.")
    if header.currency not in ("INR", "USD"):
        raise ServiceError("A purchase is in INR or USD.")
    if header.currency == "USD" and header.fx_rate is None:
        raise ServiceError("A purchase in USD needs the rate to INR.")
    if header.fx_rate is not None and header.fx_rate <= 0:
        raise ServiceError("A rate must be positive.")
    if (header.landed_extras or ZERO) < 0:
        raise ServiceError("Landed extras cannot be negative.")


def _check(header, lines):
    check_header(header, lines)
    seen = set()
    for line in lines:
        number = (line.pouch_no or "").strip()
        if not number:
            raise ServiceError(f"Give every line in {line.batch} a pouch no.")
        if (line.batch.pk, number) in seen or not ledger.pouch_no_free(line.batch, number):
            raise ServiceError(f"{line.batch} · {number} already exists — give it a new number.")
        seen.add((line.batch.pk, number))
        if line.ct is None or line.ct <= 0:
            raise ServiceError("A weight must be positive.")
        if line.cost_per_ct is None or line.cost_per_ct <= 0:
            raise ServiceError("A rate must be positive.")
```

- [ ] **Step 4: Write `inventory/ledger_dia_purchase.py`**

```python
"""Diamond purchase: the one way new diamond stock enters with a cost.

Each line is described — category, shape, colour, clarity, size — not coded.
Its item code is found, or created confirmed, from shape + colour + clarity;
its band comes from the size (part 3's rules). It becomes a new line with an in
movement (Purchase) and its own cost per carat in INR: what was paid × the
rate, plus the landed extras spread by weight. A purchase never sets a sale
price and never writes the rate card.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from stock.services import ServiceError, require

from . import dia_services, ledger
from .ledger_purchase import PURCHASE_RIGHTS, check_header
from .models import DiamondLineCost, DiamondTerm, Movement, StockDocument

ZERO, PLACES = Decimal("0"), Decimal("0.0001")


@dataclass
class DiaPurchaseLine:
    category: str
    shape: str
    colour: str
    clarity: str
    size_text: str
    pcs: int | None
    ct: Decimal | None
    cost_per_ct: Decimal | None
    batch_no: str = ""


def _check(lines):
    for line in lines:
        described = (line.category, line.shape, line.colour, line.clarity, line.size_text)
        if not all((value or "").strip() for value in described):
            raise ServiceError("A purchase line needs category, shape, colour, clarity and size.")
        if line.ct is None or line.ct <= 0:
            raise ServiceError("A weight must be positive.")
        if line.cost_per_ct is None or line.cost_per_ct <= 0:
            raise ServiceError("A cost per carat must be positive.")


@transaction.atomic
def post_dia_purchase(user, header, lines):
    """New lines only, each with its own landed cost. ``header`` is part 2's ``PurchaseHeader``."""
    for permission in PURCHASE_RIGHTS:
        require(user, permission, "Recording a purchase needs the purchase right and sight of cost and suppliers.")
    check_header(header, lines)
    _check(lines)
    usd = header.currency == "USD"
    fx = header.fx_rate if usd else Decimal("1")
    extras = header.landed_extras or ZERO
    per_ct = extras / sum(line.ct for line in lines)             # extras spread by weight
    document = ledger.open_document(
        user, StockDocument.Kind.DIA_PURCHASE, header.invoice_no, vendor=header.supplier,
        occurred_on=header.occurred_on, currency=header.currency, fx_rate=header.fx_rate if usd else None,
        landed_extras=extras, note=header.note,
    )
    by = user if getattr(user, "is_authenticated", False) else None
    moves, costs = [], []
    for line in lines:
        size = line.size_text.strip()
        sized = dia_services.sized(size, line.pcs, line.ct)
        fresh = dia_services.new_line(
            category=dia_services.listed(DiamondTerm.CATEGORY, line.category),
            code=dia_services.code_for(user, line.shape, line.colour, line.clarity),
            batch_no=(line.batch_no or "").strip(), size_text=size,
            band=dia_services.term(DiamondTerm.BAND, sized.band), ct_lo=sized.ct_lo, ct_hi=sized.ct_hi,
        )
        moves.append(ledger.Line(fresh, Movement.Reason.PURCHASE, Movement.IN, line.pcs, line.ct))
        costs.append(DiamondLineCost(line=fresh, cost_rate=(line.cost_per_ct * fx + per_ct).quantize(PLACES),
                                     effective_from=header.occurred_on, set_by=by, document=document))
    ledger.post(user, document, moves, header.occurred_on)
    DiamondLineCost.objects.bulk_create(costs)
    return document
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=dialedger_t5 ../nornament-app/.venv/bin/pytest inventory/tests/test_ledger_dia_purchase.py inventory/tests/test_ledger_purchase.py inventory/tests/test_purchase_view.py -p no:warnings`
Expected: PASS. The two stones purchase files run unchanged.

- [ ] **Step 6: Commit**

```bash
git add inventory/ledger_dia_purchase.py inventory/ledger_purchase.py inventory/tests/test_ledger_dia_purchase.py
git commit -m "$(cat <<'EOF'
Diamond purchases: described lines, codes found or made, a landed cost per line, the rate card untouched

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---
### Task 6: The Job cards screen

**Files:**
- Replace: `inventory/views_dia_jobs.py` (the Task 2 stub)
- Create: `inventory/templates/inventory/diamonds/jobs.html`, `inventory/tests/test_dia_jobs_view.py`

**Interfaces:**
- Consumes:
  - `ledger_dia_jobs.open_card/post_entry/credit_choices/owed/ENTRY_CHOICES/ENTRY_LABEL`;
  - `ledger.party/outstanding/close_document/undo_last/reverse_document/_ct`;
  - `ledger_jobs.karigar_choices`;
  - `dia_services.line_choices/line_label`;
  - `views_diamonds.viewer/dia_page`;
  - `inputs.*`;
  - the `_dsub.html` include, which Task 9 fills in with `dtab="jobs"`.
- Produces:
  - `views_dia_jobs.jobs(request)` (GET). It takes `?card=<pk>`, `?closed=1` and `?as=<ROLE>` (admin preview). It is readable by every internal login, read-only without inv_job.
  - `job_new(request)` (POST `karigar`, where blank means In-house, plus `opened_on` and `note`).
  - `job_post(request, pk)` (POST `entry`, `line`, `ct`, `occurred_on`, `ref`).
  - `job_close(request, pk)`, `job_undo(request, pk)`, `job_reverse(request, pk)`.
  - Every POST needs inv_job (403) and redirects to `dia_jobs?card=<pk>` with a message. The template renders with `dtab="jobs"`.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_dia_jobs_view.py`:

```python
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import dia_services, ledger
from inventory.ledger_dia_jobs import open_card, post_entry
from inventory.models import StockDocument
from inventory.tests.conftest import KARIGAR

pytestmark = pytest.mark.django_db
D = Decimal
S = StockDocument.Status


def _card(user, diamonds, parties, karigar=True):
    card = open_card(user, parties["karigar"] if karigar else None)
    post_entry(user, card, "issue", diamonds["round"], D("1"), ref="CH 2026/0417")
    return card


def _get(client, user, query=""):
    client.force_login(user)
    return client.get(reverse("inventory:dia_jobs") + query).content.decode()


def test_the_job_card_page_reads_as_the_prototype(client, accounts_user, diamonds, parties):
    card = _card(accounts_user, diamonds, parties)
    body = _get(client, accounts_user)
    for text in ("Job cards", "Karigar", "Opened", "Status", f"Ledger — {card.number}", "Stock control", "Line",
                 "Debit (ct)", "Credit (ct)", "Balance", "Totals", "Issue to job card", "CH 2026/0417",
                 "1 ct outstanding", KARIGAR, "Post an entry", "Issue to job card — debit",
                 "Returned unused — credit", "Breakage — credit", "Challan / ref", "＋ New job card",
                 "↺ Undo last entry", "Reverse", "NRD-000001 · DRFGH VS-SI · +6-12 · B-771"):
        assert text in body, text
    assert "A job card is a" not in body and "Debit = out to the karigar" not in body       # prose stripped
    assert "balanced — can close" not in body
    assert reverse("inventory:dia_job_close", args=[card.pk]) not in body                     # Close only at zero


def test_open_cards_by_default_and_closed_on_request(client, accounts_user, diamonds, parties):
    shut = open_card(accounts_user, None)
    ledger.close_document(accounts_user, shut)
    live = _card(accounts_user, diamonds, parties)
    body = _get(client, accounts_user)
    assert live.number in body and shut.number not in body and "Show closed" in body
    body = _get(client, accounts_user, "?closed=1")
    assert shut.number in body and "(closed)" in body and "Open only" in body
    body = _get(client, accounts_user, f"?card={shut.pk}")
    assert f"Ledger — {shut.number}" in body and "In-house" in body and "Post an entry" not in body


def test_a_balanced_card_offers_close(client, accounts_user, diamonds, parties):
    card = _card(accounts_user, diamonds, parties)
    post_entry(accounts_user, card, "set", diamonds["round"], D("1"))
    body = _get(client, accounts_user)
    assert "balanced — can close" in body and reverse("inventory:dia_job_close", args=[card.pk]) in body


def test_posting_from_the_page(client, accounts_user, diamonds, parties):
    client.force_login(accounts_user)
    response = client.post(reverse("inventory:dia_job_new"),
                           {"karigar": parties["karigar"].pk, "opened_on": "2026-05-04", "note": ""})
    card = StockDocument.objects.get(kind=StockDocument.Kind.DIA_JOB)
    assert response["Location"] == reverse("inventory:dia_jobs") + f"?card={card.pk}"
    url = reverse("inventory:dia_job_post", args=[card.pk])
    client.post(url, {"entry": "issue", "line": diamonds["round"].pk, "ct": "2", "occurred_on": "2026-05-04",
                      "ref": "CH 2026/0417"})
    client.post(url, {"entry": "loose", "line": diamonds["round"].pk, "ct": "0.5", "occurred_on": "", "ref": ""})
    assert ledger.outstanding(card) == {diamonds["round"].pk: (0, D("1.5"))}
    response = client.post(url, {"entry": "set", "line": diamonds["round"].pk, "ct": "9"}, follow=True)
    assert "cannot exceed what is outstanding" in response.content.decode()
    response = client.post(reverse("inventory:dia_job_close", args=[card.pk]), follow=True)
    assert "can close only at zero: 1.5 ct outstanding" in response.content.decode()


def test_an_unknown_karigar_is_refused_not_taken_as_in_house(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    response = client.post(reverse("inventory:dia_job_new"), {"karigar": "999999", "opened_on": ""}, follow=True)
    assert "Choose the karigar" in response.content.decode() and not StockDocument.objects.exists()


def test_close_undo_and_reverse_from_the_page(client, accounts_user, diamonds, parties):
    card = _card(accounts_user, diamonds, parties)
    client.force_login(accounts_user)
    client.post(reverse("inventory:dia_job_post", args=[card.pk]),
                {"entry": "unused", "line": diamonds["round"].pk, "ct": "1"})
    response = client.post(reverse("inventory:dia_job_close", args=[card.pk]), follow=True)
    card.refresh_from_db()
    assert card.status == S.CLOSED and f"{card.number} closed." in response.content.decode()
    response = client.post(reverse("inventory:dia_job_undo", args=[card.pk]), follow=True)
    card.refresh_from_db()
    assert card.status == S.OPEN and "Undone: Returned unused." in response.content.decode()
    response = client.post(reverse("inventory:dia_job_reverse", args=[card.pk]), follow=True)
    card.refresh_from_db()
    assert card.status == S.REVERSED and "Reversed by REV-000001" in response.content.decode()
    assert dia_services.stocked_lines().get(pk=diamonds["round"].pk).on_ct == D("3.40")


def test_every_internal_role_reads_a_card_and_only_job_cards_may_write(
        client, sales_user, graphic_user, karigar_user, accounts_user, diamonds, parties):
    card = _card(accounts_user, diamonds, parties)
    for user, label in ((sales_user, "Sales / Showroom"), (graphic_user, "Graphic / Media")):
        body = _get(client, user)
        assert card.number in body and f"read only for {label}" in body
        assert KARIGAR not in body and "Post an entry" not in body and "＋ New job card" not in body
    body = _get(client, karigar_user)
    assert KARIGAR in body and "Post an entry" in body and "read only" not in body


def test_an_admin_preview_reads_as_the_role_with_every_form_hidden(client, admin_user_, diamonds, parties):
    _card(admin_user_, diamonds, parties)
    body = _get(client, admin_user_, "?as=SALES")
    assert "read only for Sales / Showroom" in body and KARIGAR not in body and "Post an entry" not in body
    body = _get(client, admin_user_, "?as=PRODUCTION")
    assert KARIGAR in body and "read only" not in body
    for form in ("Post an entry", "＋ New job card", "↺ Undo last entry"):
        assert form not in body, form


def test_the_writes_need_job_cards(client, sales_user, accounts_user, diamonds, parties):
    card = _card(accounts_user, diamonds, parties)
    client.force_login(sales_user)
    for name, args, data in [
        ("inventory:dia_job_new", [], {}),
        ("inventory:dia_job_post", [card.pk], {"entry": "loose", "line": diamonds["round"].pk, "ct": "1"}),
        ("inventory:dia_job_close", [card.pk], {}),
        ("inventory:dia_job_undo", [card.pk], {}),
        ("inventory:dia_job_reverse", [card.pk], {}),
    ]:
        assert client.post(reverse(name, args=args), data).status_code == 403, name
    assert card.movements.count() == 1 and StockDocument.objects.count() == 1
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=dialedger_t6 ../nornament-app/.venv/bin/pytest inventory/tests/test_dia_jobs_view.py -p no:warnings`
Expected: FAIL. The routes answer 404 (the stubs).

- [ ] **Step 3: Write `inventory/views_dia_jobs.py`** (replacing the stub)

```python
"""Diamond job cards: the prototype's ledger, working.

Readable by every internal login, read-only without Job cards; a karigar's name
needs Job cards, as on stones. The page is built for the viewer, so an admin's
"Viewing as" preview shows what that role would see, with every form hidden;
every POST acts as the real login, needs Job cards, and comes back to the card
with what happened.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.capabilities import INV_JOB, ROLE_GROUPS
from stock.masking import mask
from stock.models import Vendor
from stock.services import ServiceError, require

from . import dia_services, inputs, ledger, ledger_dia_jobs, ledger_jobs
from .models import DiamondLine, Movement, StockDocument
from .views_diamonds import dia_page, viewer

Kind, Status = StockDocument.Kind, StockDocument.Status


def _card_row(user, card):
    """A card for the picker and the header, masked: a karigar the viewer may not see is simply
    absent, and never reads as In-house — ``in_house`` says that on its own."""
    return mask(user, {"pk": card.pk, "number": card.number, "in_house": card.vendor_id is None, **ledger.party(card),
                       "opened": card.occurred_on, "status": card.get_status_display().lower()})


def _ledger(card):
    """The card's entries, oldest first, as debits and credits with a running balance: out to the
    karigar is a debit; back, set or written off is a credit; an undone entry counts the other way."""
    rows, balance, debit, credit = [], ledger.ZERO, ledger.ZERO, ledger.ZERO
    moves = card.movements.select_related("diamond__band", "recorded_by").order_by("occurred_at", "pk")
    for m in moves:
        sign = 1 if m.direction == Movement.OUT else -1
        if m.reverses_id:
            sign = -sign
        ct = m.ct or ledger.ZERO
        balance += sign * ct
        debit, credit = (debit + ct, credit) if sign > 0 else (debit, credit + ct)
        label = ledger_dia_jobs.ENTRY_LABEL.get(m.reason, m.reason)
        rows.append({
            "when": m.occurred_at, "label": f"↺ {label}" if m.reverses_id else label,
            "tone": "" if m.reverses_id else ("warn" if m.direction == Movement.OUT else "good"),
            "line": dia_services.line_label(m.diamond), "ref": m.ref,
            "debit": ct if sign > 0 else None, "credit": None if sign > 0 else ct, "balance": balance,
            "by": (m.recorded_by.full_name or m.recorded_by.get_username()) if m.recorded_by_id else "system",
        })
    return rows, {"debit": debit, "credit": credit, "balance": debit - credit}


@login_required
def jobs(request):
    user, role = viewer(request)
    previewing = user is not request.user
    every = StockDocument.objects.filter(kind=Kind.DIA_JOB, reverses__isnull=True).select_related("vendor")
    raw = request.GET.get("card", "")
    card = every.filter(pk=raw).first() if raw.isdigit() else None
    closed = request.GET.get("closed") == "1" or (card is not None and card.status != Status.OPEN)
    listed = list((every if closed else every.filter(status=Status.OPEN)).order_by("-occurred_on", "-pk"))
    card = card or (listed[0] if listed else None)
    may = request.user.has_perm(INV_JOB) and not previewing
    context = {}
    if card is not None:
        rows, totals = _ledger(card)
        out = ledger_dia_jobs.owed(card)
        live = card.status == Status.OPEN
        undoable = card.movements.filter(reverses__isnull=True, reversal__isnull=True).exists()
        context = dict(
            card=_card_row(user, card), rows=rows, totals=totals, out_text=ledger._ct(out),
            can_post=may and live, can_close=may and live and out == 0,
            can_undo=may and card.status != Status.REVERSED and undoable,
            can_reverse=may and card.status != Status.REVERSED,
            issue=dia_services.line_choices() if may and live else [],
            credit=ledger_dia_jobs.credit_choices(card) if may and live else [],
        )
    return dia_page(
        request, "inventory/diamonds/jobs.html", dtab="jobs", role_label=ROLE_GROUPS[role]["name"],
        read_only=not user.has_perm(INV_JOB), may=may, closed=closed,
        cards=[_card_row(user, c) for c in listed], entries=ledger_dia_jobs.ENTRY_CHOICES,
        karigars=ledger_jobs.karigar_choices(request.user) if may else [],
        today=timezone.localdate().isoformat(), **context,
    )


def _card(pk):
    return get_object_or_404(StockDocument, pk=pk, kind=Kind.DIA_JOB, reverses__isnull=True)


def _back(pk):
    return redirect(f"{reverse('inventory:dia_jobs')}?card={pk}")


@login_required
@require_POST
def job_new(request):
    require(request.user, INV_JOB, "Only a role that posts job cards can open one.")
    raw = (request.POST.get("karigar") or "").strip()
    try:
        karigar = Vendor.objects.filter(pk=raw).first() if raw.isdigit() else None
        if raw and karigar is None:
            raise ServiceError("Choose the karigar, or In-house.")
        card = ledger_dia_jobs.open_card(request.user, karigar, inputs.day(request.POST.get("opened_on"), "Opened"),
                                         request.POST.get("note", ""))
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
        return redirect("inventory:dia_jobs")
    messages.success(request, f"Job card {card.number} opened.")
    return _back(card.pk)


@login_required
@require_POST
def job_post(request, pk):
    require(request.user, INV_JOB, "Only a role that posts job cards can post an entry.")
    card = _card(pk)
    raw = request.POST.get("line") or ""
    line = DiamondLine.objects.filter(pk=raw).first() if raw.isdigit() else None
    try:
        ledger_dia_jobs.post_entry(request.user, card, request.POST.get("entry", ""), line,
                                   inputs.decimal(request.POST.get("ct"), "Carats"),
                                   inputs.day(request.POST.get("occurred_on")), request.POST.get("ref", ""))
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
    else:
        messages.success(request, "Posted.")
    return _back(card.pk)


def _act(request, pk, act, done):
    """Close, undo or reverse a card as the real login, and come back to it with what happened."""
    require(request.user, INV_JOB, "Only a role that posts job cards may change one.")
    card = _card(pk)
    try:
        result = act(request.user, card)
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
    else:
        messages.success(request, done(result))
    return _back(card.pk)


@login_required
@require_POST
def job_close(request, pk):
    return _act(request, pk, ledger.close_document, lambda card: f"{card.number} closed.")


@login_required
@require_POST
def job_undo(request, pk):
    return _act(request, pk, ledger.undo_last,
                lambda move: f"Undone: {ledger_dia_jobs.ENTRY_LABEL.get(move.reason, move.reason)}.")


@login_required
@require_POST
def job_reverse(request, pk):
    return _act(request, pk, ledger.reverse_document, lambda reversal: f"Reversed by {reversal.number}.")
```

- [ ] **Step 4: Write `inventory/templates/inventory/diamonds/jobs.html`**

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Job cards · Diamonds{% endblock %}
{% block crumb %}<b>Diamonds</b> &nbsp;›&nbsp; Job cards{% endblock %}
{% block content %}
{% include "inventory/diamonds/_dsub.html" %}
<div class="dbanner"><h2>Job cards</h2></div>

<div class="filterbar">
  <div class="fsel"><label>Job card</label>
    <form method="get" style="display:contents">
      {% if as_role %}<input type="hidden" name="as" value="{{ as_role }}">{% endif %}
      {% if closed %}<input type="hidden" name="closed" value="1">{% endif %}
      <select class="inp" name="card" onchange="this.form.submit()">
        {% for c in cards %}<option value="{{ c.pk }}"{% if card and c.pk == card.pk %} selected{% endif %}>{{ c.number }} — {% if c.in_house %}In-house{% elif 'karigar_name' in c %}{{ c.karigar_name }}{% else %}karigar{% endif %} ({{ c.status }})</option>
        {% empty %}<option value="">No job cards</option>{% endfor %}
      </select></form></div>
  {% if card %}
  <div class="fsel"><label>Karigar</label><div class="ro2">{% if card.in_house %}In-house{% elif 'karigar_name' in card %}{{ card.karigar_name }}{% else %}—{% endif %}</div></div>
  <div class="fsel"><label>Opened</label><div class="ro2">{{ card.opened|date:"d M Y" }}</div></div>
  <div class="fsel"><label>Status</label><div class="ro2">
    {% if card.status == 'reversed' %}<span class="chip crit"><span class="dot"></span>reversed</span>
    {% elif card.status == 'closed' %}<span class="chip good"><span class="dot"></span>closed</span>
    {% elif out_text == '0' %}<span class="chip good"><span class="dot"></span>balanced — can close</span>
    {% else %}<span class="chip warn"><span class="dot"></span>{{ out_text }} ct outstanding</span>{% endif %}</div></div>
  {% endif %}
  <div class="fsel"><label>&nbsp;</label>
    {% if closed %}<a class="chip" href="?{% if as_role %}as={{ as_role }}{% endif %}">Open only</a>
    {% else %}<a class="chip" href="?closed=1{% if as_role %}&amp;as={{ as_role }}{% endif %}">Show closed</a>{% endif %}</div>
  {% if may %}
  <div class="fsel"><label>&nbsp;</label>
    <details class="inline"><summary class="btn sm pri">＋ New job card</summary>
      <form method="post" action="{% url 'inventory:dia_job_new' %}" class="ctrow" style="margin-top:8px">{% csrf_token %}
        <select class="inp" name="karigar" style="width:180px"><option value="">In-house</option>
          {% for k in karigars %}{% if 'karigar_name' in k %}<option value="{{ k.pk }}">{{ k.karigar_name }}</option>{% endif %}{% endfor %}</select>
        <input class="inp" type="date" name="opened_on" value="{{ today }}" style="width:150px">
        <input class="inp" name="note" placeholder="Note" style="width:180px">
        <button class="btn pri">Open job card</button></form></details></div>
  {% endif %}
</div>

{% if card %}
<div class="card" style="overflow:hidden">
  <div class="card-h"><span class="card-t">Ledger — {{ card.number }}</span><span class="spacer"></span>
    {% if read_only %}<span class="hint">read only for {{ role_label }}</span>{% endif %}
    {% if can_undo %}<form method="post" action="{% url 'inventory:dia_job_undo' card.pk %}" class="inline">{% csrf_token %}
      <button class="btn sm gho" onclick="return confirm('Undo the last entry on {{ card.number|escapejs }}?')">↺ Undo last entry</button></form>{% endif %}
    {% if can_close %}<form method="post" action="{% url 'inventory:dia_job_close' card.pk %}" class="inline">{% csrf_token %}
      <button class="btn sm pri">Close</button></form>{% endif %}
    {% if can_reverse %}<form method="post" action="{% url 'inventory:dia_job_reverse' card.pk %}" class="inline">{% csrf_token %}
      <button class="btn sm" onclick="return confirm('Reverse every entry on {{ card.number|escapejs }}?')">Reverse</button></form>{% endif %}
  </div>
  <div style="overflow:auto"><table class="led">
    <thead><tr><th>Date</th><th>Stock control</th><th>Line</th><th>Ref</th>
      <th class="r">Debit (ct)</th><th class="r">Credit (ct)</th><th class="r">Balance</th><th>By</th></tr></thead>
    <tbody>{% for r in rows %}<tr>
      <td>{{ r.when|date:"d M Y" }}</td>
      <td><span class="chip {{ r.tone }}"><span class="dot"></span>{{ r.label }}</span></td>
      <td class="mono">{{ r.line }}</td>
      <td class="chal">{{ r.ref }}</td>
      <td class="r">{% if r.debit is not None %}<b>{{ r.debit|ct }}</b>{% endif %}</td>
      <td class="r">{% if r.credit is not None %}<b>{{ r.credit|ct }}</b>{% endif %}</td>
      <td class="r bal">{{ r.balance|ct }}</td>
      <td class="hint">{{ r.by }}</td></tr>
    {% empty %}<tr><td colspan="8" class="hint">No entries yet.</td></tr>{% endfor %}
      <tr class="ledtot"><td colspan="4"><b>Totals</b></td>
        <td class="r"><b>{{ totals.debit|ct }}</b></td><td class="r"><b>{{ totals.credit|ct }}</b></td>
        <td class="r"><b>{{ totals.balance|ct }}</b></td><td></td></tr>
    </tbody></table></div>
</div>

{% if can_post %}
<div class="card" style="margin-top:14px"><div class="card-h"><span class="card-t">Post an entry</span></div>
  <div class="card-b"><form method="post" action="{% url 'inventory:dia_job_post' card.pk %}" class="filterbar" style="margin:0">{% csrf_token %}
    <div class="fsel"><label>Stock control</label><select class="inp" name="entry">
      {% for value, label in entries %}<option value="{{ value }}">{{ label }}</option>{% endfor %}</select></div>
    <div class="fsel"><label>Line</label><select class="inp" name="line">
      <optgroup label="In stock — to issue">{% for l in issue %}<option value="{{ l.pk }}">{{ l.label }} — {{ l.ct|ct }} ct</option>{% endfor %}</optgroup>
      {% if credit %}<optgroup label="Out on this card — to credit">{% for l in credit %}<option value="{{ l.pk }}">{{ l.label }} — {{ l.ct|ct }} ct out</option>{% endfor %}</optgroup>{% endif %}
    </select></div>
    <div class="fsel"><label>Carats</label>
      <div class="unit"><input class="inp tnum" name="ct" inputmode="decimal" placeholder="0.00"><span class="u">ct</span></div></div>
    <div class="fsel"><label>Date</label><input class="inp" type="date" name="occurred_on" value="{{ today }}"></div>
    <div class="fsel"><label>Challan / ref</label><input class="inp mono" name="ref" maxlength="40"></div>
    <div class="fsel"><label>&nbsp;</label><button class="btn pri">Post</button></div>
  </form></div></div>
{% endif %}
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=dialedger_t6 ../nornament-app/.venv/bin/pytest inventory/tests/test_dia_jobs_view.py inventory/tests/test_masking.py -p no:warnings`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add inventory/views_dia_jobs.py inventory/templates/inventory/diamonds/jobs.html inventory/tests/test_dia_jobs_view.py
git commit -m "$(cat <<'EOF'
The Job cards screen: the card ledger with a running balance, post an entry, Close at zero, undo, reverse

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---
### Task 7: The Assortments screen

**Files:**
- Replace: `inventory/views_dia_assort.py` (the Task 2 stub)
- Create: `inventory/templates/inventory/diamonds/assort.html`, `inventory/tests/test_dia_assort_view.py`

**Interfaces:**
- Consumes:
  - `ledger_dia_assort.post_assortment/Destination`;
  - `ledger.reverse_document/ZERO`;
  - `dia_services.line_choices/term_values`;
  - `views_diamonds.viewer/dia_page`;
  - `inputs.*`;
  - part 2's `split.html` live-balance pattern.
- Produces:
  - `views_dia_assort.assorts(request)`:
    - GET takes `?doc=<pk>` and `?as=<ROLE>`.
    - POST takes `source`, `take_out`, `occurred_on`, `note`, `loss` and the destination rows, each a list: `shape`, `colour`, `clarity`, `size_text`, `ct` and `cost` (cost only for view_cost).
    - It needs inv_assort: a POST without it is 403, and a GET shows "Not permitted for {role}".
    - A refusal re-renders the form with the rows as typed; success redirects to `dia_assorts?doc=<pk>`.
  - `assort_reverse(request, pk)` (POST, inv_assort).
  - The template renders with `dtab="assort"`.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_dia_assort_view.py`:

```python
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

from accounts.models import User
from inventory import ledger
from inventory.models import Movement, StockDocument

pytestmark = pytest.mark.django_db
D = Decimal


def _post(client, user, diamonds, **changes):
    """The prototype's AS card: 2.00 ct out of the round line, two destinations, 0.05 ct sorting loss.
    A change of ``None`` leaves that field out of the post."""
    data = {"source": diamonds["round"].pk, "take_out": "2.00", "occurred_on": "2026-08-02",
            "note": "re-sieved after client return", "shape": ["Round", "Round"], "colour": ["E-F", "I-J"],
            "clarity": ["VVS-VS", "SI-I"], "size_text": ["+6-12", "+2"], "ct": ["1.20", "0.75"],
            "cost": ["", ""], "loss": "0.05"}
    client.force_login(user)
    return client.post(reverse("inventory:dia_assorts"),
                       {key: value for key, value in (data | changes).items() if value is not None})


def test_the_assortment_screen_reads_as_the_prototype(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:dia_assorts")).content.decode()
    for text in ("Assortments", "＋ New assortment", "Source line", "Take out", "Reason", "＋ Add destination",
                 "Shape", "Colour", "Clarity", "Size", "Carats", "Cost / ct", "Sorting loss",
                 "ct unaccounted — cannot post", "balances", "Post assortment",
                 "NRD-000001 · DRFGH VS-SI · +6-12 · B-771 — 3.40 ct"):
        assert text in body, text
    assert "Same ledger idea" not in body and "Debits and credits must match" not in body      # prose stripped


def test_a_balanced_assortment_posts_and_shows_its_ledger(client, accounts_user, diamonds):
    response = _post(client, accounts_user, diamonds)
    doc = StockDocument.objects.get(kind=StockDocument.Kind.DIA_ASSORT)
    assert response["Location"] == reverse("inventory:dia_assorts") + f"?doc={doc.pk}"
    body = client.get(response["Location"]).content.decode()
    for text in (f"Assortment {doc.number} posted.", f"Ledger — {doc.number}", "Posted by", "Balance", "balances",
                 "re-sieved after client return", "Code", "Movement", "Note", "Debit (ct)", "Credit (ct)", "Running",
                 "Assort out", "Assort in", "Sorting loss", "written off", "Totals",
                 "DRFGH VS-SI · +6-11", "DREF VVS-VS · +6-11", "DRIJ SI-I · +2-6", "2.00", "1.20", "0.75", "0.05"):
        assert text in body, text


def test_an_unbalanced_assortment_comes_back_with_its_rows(client, accounts_user, diamonds):
    response = _post(client, accounts_user, diamonds, loss="")
    body = response.content.decode()
    assert response.status_code == 200 and "0.05 ct unaccounted — an assortment must balance" in body
    assert 'value="1.20"' in body and 'value="0.75"' in body and 'value="+6-12"' in body
    assert not StockDocument.objects.exists()


def test_the_cost_column_needs_sight_of_cost(client, accounts_user, diamonds):
    Group.objects.get(name="ACCOUNTS").permissions.remove(Permission.objects.get(codename="view_cost"))
    blind = User.objects.get(pk=accounts_user.pk)
    client.force_login(blind)
    body = client.get(reverse("inventory:dia_assorts")).content.decode()
    assert "＋ New assortment" in body and "Cost / ct" not in body
    assert _post(client, blind, diamonds, cost=None).status_code == 302          # a carried cost needs no sight of it
    response = _post(client, blind, diamonds, cost=["20000", ""])
    assert response.status_code == 403                                          # an override does


def test_others_are_not_permitted(client, production_user, sales_user, diamonds):
    for user, label in ((production_user, "Production"), (sales_user, "Sales / Showroom")):
        client.force_login(user)
        body = client.get(reverse("inventory:dia_assorts")).content.decode()
        assert f"Not permitted for {label}" in body and "＋ New assortment" not in body
    assert _post(client, production_user, diamonds).status_code == 403
    assert not StockDocument.objects.exists()


def test_an_admin_preview_reads_as_the_role(client, admin_user_, diamonds):
    _post(client, admin_user_, diamonds)
    body = client.get(reverse("inventory:dia_assorts"), {"as": "SALES"}).content.decode()
    assert "Not permitted for Sales / Showroom" in body and "Assort out" not in body
    body = client.get(reverse("inventory:dia_assorts"), {"as": "ACCOUNTS"}).content.decode()
    assert "Assort out" in body and "＋ New assortment" not in body and ">Reverse</button>" not in body


def test_reverse_from_the_screen_and_its_refusal(client, accounts_user, diamonds):
    _post(client, accounts_user, diamonds)
    doc = StockDocument.objects.get(kind=StockDocument.Kind.DIA_ASSORT)
    up = doc.movements.filter(reason=Movement.Reason.ASSORT_IN).order_by("pk").first().diamond
    card = ledger.open_document(accounts_user, StockDocument.Kind.DIA_JOB)
    ledger.post(accounts_user, card, [ledger.Line(up, Movement.Reason.JOB_WORK_OUT, Movement.OUT, None, D("0.5"))])
    response = client.post(reverse("inventory:dia_assort_reverse", args=[doc.pk]), follow=True)
    assert "has moved since" in response.content.decode()
    ledger.reverse_document(accounts_user, card)
    response = client.post(reverse("inventory:dia_assort_reverse", args=[doc.pk]), follow=True)
    body = response.content.decode()
    assert "Reversed by REV-000002" in body and "(reversed)" in body and ">Reverse</button>" not in body
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=dialedger_t7 ../nornament-app/.venv/bin/pytest inventory/tests/test_dia_assort_view.py -p no:warnings`
Expected: FAIL. The routes answer 404 (the stubs).

- [ ] **Step 3: Write `inventory/views_dia_assort.py`** (replacing the stub)

```python
"""Diamond assortments: the prototype's must-balance ledger, working.

Seen and posted with the Assort right; any other role — or an admin previewing
one — sees "Not permitted". The form posts only when it balances, and a refusal
comes back on the form with what was typed. Every POST acts as the real login.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.capabilities import INV_ASSORT, ROLE_GROUPS
from stock.masking import mask
from stock.services import ServiceError, require

from . import dia_services, inputs, ledger, ledger_dia_assort
from .models import DiamondLine, DiamondTerm, Movement, StockDocument
from .views_diamonds import dia_page, viewer

Kind, Status, Reason = StockDocument.Kind, StockDocument.Status, Movement.Reason
DEST_FIELDS = ("shape", "colour", "clarity", "size_text", "ct", "cost")


def _typed(post):
    """The destination rows as typed; a row with nothing in it is no destination. A login without
    sight of cost has no cost column, so its rows are padded with blanks."""
    n = len(post.getlist("ct"))
    columns = [post.getlist(name) or [""] * n for name in DEST_FIELDS]
    rows = [dict(zip(DEST_FIELDS, values)) for values in zip(*columns)]
    return [row for row in rows if any((value or "").strip() for value in row.values())]


def _destinations(rows):
    return [ledger_dia_assort.Destination(
        shape=(row["shape"] or "").strip(), colour=(row["colour"] or "").strip(),
        clarity=(row["clarity"] or "").strip(), size_text=(row["size_text"] or "").strip(),
        ct=inputs.decimal(row["ct"], "Carats"), cost_per_ct=inputs.decimal(row["cost"], "Cost / ct"),
    ) for row in rows]


def _code(line):
    return f"{line.code_id} · {line.band.value}"


def _ledger(doc):
    """The prototype's ledger: the source debited with everything taken out of it, each destination
    credited, and the sorting loss a credit that settles the difference — so it runs to zero."""
    moves = list(doc.movements.filter(reverses__isnull=True).select_related("diamond__band").order_by("pk"))
    out = [m for m in moves if m.reason == Reason.ASSORT_OUT]
    loss = sum((m.ct for m in moves if m.reason == Reason.WASTAGE), ledger.ZERO)
    taken = sum((m.ct for m in out), loss)
    rows, running = [], taken
    if out:
        rows.append({"code": _code(out[0].diamond), "movement": "Assort out", "tone": "warn",
                     "note": f"source parcel · {out[0].diamond.ref}", "debit": taken, "running": running})
    for m in moves:
        if m.reason == Reason.ASSORT_IN:
            running -= m.ct
            rows.append({"code": _code(m.diamond), "movement": "Assort in", "tone": "good", "note": m.diamond.ref,
                         "credit": m.ct, "running": running})
    if loss:
        running -= loss
        rows.append({"code": "Sorting loss", "movement": "Sorting loss", "tone": "good", "note": "written off",
                     "credit": loss, "running": running})
    return rows, {"debit": taken, "credit": taken - running, "diff": running}


@login_required
def assorts(request):
    form, rows, error = {}, [], None
    if request.method == "POST":
        require(request.user, INV_ASSORT, "Only a role that assorts can post an assortment.")
        form, rows = request.POST, _typed(request.POST)
        raw = form.get("source") or ""
        source = DiamondLine.objects.filter(pk=raw).first() if raw.isdigit() else None
        try:
            doc = ledger_dia_assort.post_assortment(
                request.user, source, inputs.decimal(form.get("take_out"), "Take out"), _destinations(rows),
                inputs.decimal(form.get("loss"), "Sorting loss"), inputs.day(form.get("occurred_on")),
                form.get("note", ""),
            )
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            messages.success(request, f"Assortment {doc.number} posted.")
            return redirect(f"{reverse('inventory:dia_assorts')}?doc={doc.pk}")
    user, role = viewer(request)
    role_label = ROLE_GROUPS[role]["name"]
    if not user.has_perm(INV_ASSORT):
        return dia_page(request, "inventory/diamonds/assort.html", dtab="assort", denied=True, role_label=role_label)
    posted = list(StockDocument.objects.filter(kind=Kind.DIA_ASSORT, reverses__isnull=True)
                  .select_related("created_by").order_by("-occurred_on", "-pk"))
    raw = request.GET.get("doc", "")
    doc = next((d for d in posted if str(d.pk) == raw), posted[0] if posted else None)
    context = {}
    if doc is not None:
        lines, totals = _ledger(doc)
        by = (doc.created_by.full_name or doc.created_by.get_username()) if doc.created_by_id else "system"
        context = {"doc": doc, "ledger": lines, "totals": totals, "by": by}
    previewing = user is not request.user
    return dia_page(
        request, "inventory/diamonds/assort.html", dtab="assort", denied=False, role_label=role_label,
        posted=posted, can_post=not previewing,
        can_reverse=not previewing and doc is not None and doc.status != Status.REVERSED,
        form=form, dests=rows or [dict.fromkeys(DEST_FIELDS, "")], error=error,
        money=mask(user, {"cost_rate": None}), sources=dia_services.line_choices(),
        shapes=dia_services.term_values(DiamondTerm.SHAPE), colours=dia_services.term_values(DiamondTerm.COLOUR),
        clarities=dia_services.term_values(DiamondTerm.CLARITY), today=timezone.localdate().isoformat(), **context,
    )


@login_required
@require_POST
def assort_reverse(request, pk):
    require(request.user, INV_ASSORT, "Only a role that assorts can reverse an assortment.")
    doc = get_object_or_404(StockDocument, pk=pk, kind=Kind.DIA_ASSORT, reverses__isnull=True)
    try:
        reversal = ledger.reverse_document(request.user, doc)
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
    else:
        messages.success(request, f"Reversed by {reversal.number}.")
    return redirect(f"{reverse('inventory:dia_assorts')}?doc={doc.pk}")
```

- [ ] **Step 4: Write `inventory/templates/inventory/diamonds/assort.html`**

The balance line uses `ledger._ct`'s rule: 4 places, trailing zeros trimmed. The server's refusal says the same thing in the same form.

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Assortments · Diamonds{% endblock %}
{% block crumb %}<b>Diamonds</b> &nbsp;›&nbsp; Assortments{% endblock %}
{% block content %}
{% include "inventory/diamonds/_dsub.html" %}
<div class="dbanner"><h2>Assortments</h2></div>
{% if denied %}
<div class="banner crit"><div class="banner-ic">✕</div><div><h4>Not permitted for {{ role_label }}</h4></div></div>
{% else %}

{% if doc %}
<div class="filterbar">
  <div class="fsel"><label>Assortment</label>
    <form method="get" style="display:contents">{% if as_role %}<input type="hidden" name="as" value="{{ as_role }}">{% endif %}
      <select class="inp" name="doc" onchange="this.form.submit()">
        {% for d in posted %}<option value="{{ d.pk }}"{% if d.pk == doc.pk %} selected{% endif %}>{{ d.number }} — {{ d.occurred_on|date:"d M Y" }} ({% if d.status == 'reversed' %}reversed{% else %}balanced{% endif %})</option>{% endfor %}
      </select></form></div>
  <div class="fsel"><label>Posted by</label><div class="ro2">{{ by }}</div></div>
  <div class="fsel"><label>Reason</label><div class="ro2">{{ doc.note|default:"—" }}</div></div>
  <div class="fsel"><label>Balance</label><div class="ro2">
    {% if doc.status == 'reversed' %}<span class="chip crit"><span class="dot"></span>reversed</span>
    {% else %}<span class="chip good"><span class="dot"></span>balances</span>{% endif %}</div></div>
</div>

<div class="card" style="overflow:hidden;margin-bottom:14px">
  <div class="card-h"><span class="card-t">Ledger — {{ doc.number }}</span><span class="spacer"></span>
    {% if can_reverse %}<form method="post" action="{% url 'inventory:dia_assort_reverse' doc.pk %}" class="inline">{% csrf_token %}
      <button class="btn sm" onclick="return confirm('Reverse {{ doc.number|escapejs }}?')">Reverse</button></form>{% endif %}</div>
  <div style="overflow:auto"><table class="led">
    <thead><tr><th>Code</th><th>Movement</th><th>Note</th>
      <th class="r">Debit (ct)</th><th class="r">Credit (ct)</th><th class="r">Running</th></tr></thead>
    <tbody>{% for r in ledger %}<tr>
      <td class="mono"><b>{{ r.code }}</b></td>
      <td><span class="chip {{ r.tone }}"><span class="dot"></span>{{ r.movement }}</span></td>
      <td class="hint">{{ r.note }}</td>
      <td class="r">{% if 'debit' in r %}<b>{{ r.debit|ct }}</b>{% endif %}</td>
      <td class="r">{% if 'credit' in r %}<b>{{ r.credit|ct }}</b>{% endif %}</td>
      <td class="r bal">{{ r.running|ct }}</td></tr>{% endfor %}
      <tr class="ledtot"><td colspan="3"><b>Totals</b></td>
        <td class="r"><b>{{ totals.debit|ct }}</b></td><td class="r"><b>{{ totals.credit|ct }}</b></td>
        <td class="r"><b>{{ totals.diff|ct }}</b></td></tr>
    </tbody></table></div>
</div>
{% endif %}

{% if can_post %}
{% if error %}<div class="banner crit"><div class="banner-ic">!</div><div><h4>{{ error }}</h4></div></div>{% endif %}
<form method="post" id="assort" class="card" style="overflow:hidden">{% csrf_token %}
  <div class="card-h"><span class="card-t">＋ New assortment</span><span class="spacer"></span>
    <button class="btn sm" type="button" id="adddest">＋ Add destination</button></div>
  <div class="card-b"><div class="filterbar" style="margin:0">
    <div class="fsel"><label>Source line</label><select class="inp" name="source"><option value="">—</option>
      {% for s in sources %}<option value="{{ s.pk }}"{% if form.source == s.pk|stringformat:"s" %} selected{% endif %}>{{ s.label }} — {{ s.ct|ct }} ct</option>{% endfor %}</select></div>
    <div class="fsel"><label>Take out</label>
      <div class="unit"><input class="inp tnum" name="take_out" inputmode="decimal" value="{{ form.take_out|default:'' }}"><span class="u">ct</span></div></div>
    <div class="fsel"><label>Date</label><input class="inp" type="date" name="occurred_on" value="{{ form.occurred_on|default:today }}"></div>
    <div class="fsel"><label>Reason</label><input class="inp" name="note" value="{{ form.note|default:'' }}"></div>
  </div></div>
  <div style="overflow:auto"><table class="led" id="dests">
    <thead><tr><th>Shape</th><th>Colour</th><th>Clarity</th><th>Size</th><th class="r">Carats</th>
      {% if 'cost_rate' in money %}<th class="r">Cost / ct</th>{% endif %}</tr></thead>
    <tbody>{% for d in dests %}<tr>
      <td><select class="inp" name="shape"><option value=""></option>{% for v in shapes %}<option{% if v == d.shape %} selected{% endif %}>{{ v }}</option>{% endfor %}</select></td>
      <td><select class="inp" name="colour"><option value=""></option>{% for v in colours %}<option{% if v == d.colour %} selected{% endif %}>{{ v }}</option>{% endfor %}</select></td>
      <td><select class="inp" name="clarity"><option value=""></option>{% for v in clarities %}<option{% if v == d.clarity %} selected{% endif %}>{{ v }}</option>{% endfor %}</select></td>
      <td><input class="inp mono" name="size_text" maxlength="40" value="{{ d.size_text }}" placeholder="as the source" style="width:110px"></td>
      <td class="r"><input class="inp tnum" name="ct" inputmode="decimal" value="{{ d.ct }}" style="width:90px"></td>
      {% if 'cost_rate' in money %}<td class="r"><input class="inp tnum" name="cost" inputmode="decimal" value="{{ d.cost }}" placeholder="carried" style="width:100px"></td>{% endif %}
    </tr>{% endfor %}</tbody>
    <tfoot><tr class="ledtot"><td colspan="4"><b>Sorting loss</b></td>
      <td class="r"><input class="inp tnum" name="loss" inputmode="decimal" value="{{ form.loss|default:'' }}" style="width:90px"></td>
      {% if 'cost_rate' in money %}<td></td>{% endif %}</tr></tfoot>
  </table></div>
  <div class="card-b" style="border-top:1px solid var(--border)">
    <div id="balanced" hidden><span class="chip good"><span class="dot"></span>balances</span></div>
    <div id="unbalanced" hidden><div class="banner crit" style="margin:0"><div class="banner-ic">!</div><div>
      <h4><span id="diff"></span> ct unaccounted — cannot post</h4></div></div></div>
    <button class="btn pri" id="postassort" style="margin-top:10px">Post assortment</button>
  </div>
</form>
<script>
/* The assortment's balance line: taken out against destinations plus the sorting loss, to 4 places. */
(function () {
  var form = document.getElementById('assort'), body = form.querySelector('#dests tbody');
  function num(v) { v = parseFloat(String(v || '').replace(/,/g, '')); return isFinite(v) ? v : 0; }
  function trim(v) { return v.toFixed(4).replace(/\.?0+$/, '') || '0'; }
  function check() {
    var into = num(form.elements.loss.value);
    body.querySelectorAll('[name=ct]').forEach(function (input) { into += num(input.value); });
    var diff = Math.round((num(form.elements.take_out.value) - into) * 10000) / 10000;
    document.getElementById('diff').textContent = trim(diff);
    document.getElementById('balanced').hidden = diff !== 0;
    document.getElementById('unbalanced').hidden = diff === 0;
    document.getElementById('postassort').disabled = diff !== 0;
  }
  document.getElementById('adddest').addEventListener('click', function () {
    var tr = body.lastElementChild.cloneNode(true);
    tr.querySelectorAll('input').forEach(function (input) { input.value = ''; });
    tr.querySelectorAll('select').forEach(function (select) { select.selectedIndex = 0; });
    body.appendChild(tr);
    check();
  });
  form.addEventListener('input', check);
  form.addEventListener('change', check);
  check();
})();
</script>
{% endif %}
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=dialedger_t7 ../nornament-app/.venv/bin/pytest inventory/tests/test_dia_assort_view.py inventory/tests/test_masking.py -p no:warnings`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add inventory/views_dia_assort.py inventory/templates/inventory/diamonds/assort.html inventory/tests/test_dia_assort_view.py
git commit -m "$(cat <<'EOF'
The Assortments screen: posted ledgers, a new assortment with a live balance line, reverse

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---
### Task 8: The Purchases screen and the diamond Purchase tab

**Files:**
- Replace: `inventory/views_dia_purchase.py` (the Task 2 stub)
- Create: `inventory/templates/inventory/diamonds/purchase.html`, `inventory/tests/test_dia_purchase_view.py`
- Modify: `templates/inventory_base.html` (the diamond tab strip)

**Interfaces:**
- Consumes:
  - `ledger_dia_purchase.post_dia_purchase/DiaPurchaseLine`;
  - `ledger_purchase.PurchaseHeader/PURCHASE_RIGHTS`;
  - `ledger.party/reverse_document/ZERO`;
  - `dia_services.save_supplier/term_values`;
  - `DiamondLineCost`;
  - `views_diamonds.viewer/dia_page`;
  - `inputs.*`;
  - part 2's `purchase.html` pattern: JS lines, live totals, re-render on refusal.
- Produces:
  - `views_dia_purchase.purchase(request)`:
    - GET takes `?as=<ROLE>`.
    - POST takes `supplier` (a pk, or `new` with `new_code` and `new_name`), `occurred_on`, `invoice_no`, `currency`, `fx_rate`, `landed_extras`, `note`, and the line lists `category`, `shape`, `colour`, `clarity`, `size_text`, `batch_no`, `pcs`, `ct`, `cost`.
    - It needs all of `PURCHASE_RIGHTS`: a POST without them is 403, and a GET shows "Not permitted for {role}".
    - A refusal re-renders with what was typed; success redirects to `dia_purchase` with a message.
  - `purchase_reverse(request, pk)` (POST, inv_purchase).
  - The template renders with `dtab="purchase"`.
  - The diamond top bar's **Purchase** tab links here for holders of `PURCHASE_RIGHTS`; for anyone else it is `<button disabled>Purchase 🔒</button>`. Movements and Stock take stay padlocked.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_dia_purchase_view.py`:

```python
import pytest
from django.urls import reverse

from inventory.models import StockDocument
from stock.models import Vendor

pytestmark = pytest.mark.django_db


def _post(client, user, diamonds, **changes):
    """The prototype's purchase: 14.20 ct round at ₹16,500 and 3.60 ct princess at ₹21,000, ₹1,780 extras.
    A change of ``None`` leaves that field out of the post."""
    data = {"supplier": diamonds["supplier"].pk, "occurred_on": "2026-08-07", "invoice_no": "2026/0442",
            "currency": "INR", "fx_rate": "", "landed_extras": "1780", "note": "",
            "category": ["Natural Diamond", "Natural Diamond"], "shape": ["Round", "Princess"],
            "colour": ["F-G-H", "E-F"], "clarity": ["VS-SI", "VVS-VS"], "size_text": ["+6-12", "+2"],
            "batch_no": ["B-901", ""], "pcs": ["", "40"], "ct": ["14.20", "3.60"], "cost": ["16500", "21000"]}
    client.force_login(user)
    return client.post(reverse("inventory:dia_purchase"),
                       {key: value for key, value in (data | changes).items() if value is not None})


def test_the_purchase_screen_reads_as_the_prototype(client, accounts_user, diamonds):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:dia_purchase")).content.decode()
    for text in ("Purchase — the only way diamond stock enters", "The purchase", "Supplier", "Purchase date",
                 "Invoice no.", "Currency", "INR ₹", "USD $", "Lines — each becomes a stock line", "Category",
                 "Shape", "Colour", "Clarity", "Size", "Pieces", "Carats", "Cost / ct", "＋ Add line",
                 "Landed extras — freight, duty, certification", "What posting will do",
                 "reason <code>Purchase</code>", "sale price is <b>not</b> set here", "Post purchase",
                 "Recent purchases", "Kothari Exports, Mumbai", "＋ New supplier…"):
        assert text in body, text
    assert "There is no separate" not in body and "Suppliers are maintained in Settings" not in body   # prose stripped


def test_a_purchase_posts_and_lists_as_recent(client, accounts_user, diamonds):
    response = _post(client, accounts_user, diamonds)
    assert response["Location"] == reverse("inventory:dia_purchase")
    doc = StockDocument.objects.get(kind=StockDocument.Kind.DIA_PURCHASE)
    assert doc.movements.count() == 2
    body = client.get(response["Location"]).content.decode()
    assert "Purchase 2026/0442 posted." in body and "17.80" in body
    assert "₹3,11,680" in body                     # 14.20 × ₹16,600 + 3.60 × ₹21,100: landed, extras spread by weight


def test_a_refusal_comes_back_with_what_was_typed(client, accounts_user, diamonds):
    response = _post(client, accounts_user, diamonds, clarity=["VS-SI", ""])
    body = response.content.decode()
    assert response.status_code == 200 and "needs category, shape, colour, clarity and size" in body
    assert 'value="14.20"' in body and 'value="B-901"' in body and not StockDocument.objects.exists()


def test_usd_needs_its_rate(client, accounts_user, diamonds):
    assert "USD needs the rate" in _post(client, accounts_user, diamonds, currency="USD").content.decode()


def test_a_new_supplier_stands_or_falls_with_its_purchase(client, admin_user_, diamonds):
    _post(client, admin_user_, diamonds, supplier="new", new_code="SRT", new_name="Surat Diamonds",
          clarity=["VS-SI", ""])
    assert not Vendor.objects.filter(code="SRT").exists()
    _post(client, admin_user_, diamonds, supplier="new", new_code="SRT", new_name="Surat Diamonds")
    assert StockDocument.objects.get(kind=StockDocument.Kind.DIA_PURCHASE).vendor.name == "Surat Diamonds"


def test_others_are_not_permitted(client, production_user, sales_user, karigar_user, diamonds):
    for user, label in ((production_user, "Production"), (sales_user, "Sales / Showroom"),
                        (karigar_user, "Karigar desk")):
        client.force_login(user)
        body = client.get(reverse("inventory:dia_purchase")).content.decode()
        assert f"Not permitted for {label}" in body and "Post purchase" not in body
    assert _post(client, production_user, diamonds).status_code == 403
    assert not StockDocument.objects.exists()


def test_an_admin_preview_lists_without_the_form(client, admin_user_, diamonds):
    _post(client, admin_user_, diamonds)
    body = client.get(reverse("inventory:dia_purchase"), {"as": "ACCOUNTS"}).content.decode()
    assert "Recent purchases" in body and "2026/0442" in body
    assert "Post purchase" not in body and ">Reverse</button>" not in body
    body = client.get(reverse("inventory:dia_purchase"), {"as": "PRODUCTION"}).content.decode()
    assert "Not permitted for Production" in body and "2026/0442" not in body


def test_reverse_from_recent_purchases(client, accounts_user, diamonds):
    _post(client, accounts_user, diamonds)
    doc = StockDocument.objects.get(kind=StockDocument.Kind.DIA_PURCHASE)
    body = client.post(reverse("inventory:dia_purchase_reverse", args=[doc.pk]), follow=True).content.decode()
    assert "Reversed by REV-000001" in body and "Reversed</span>" in body


def test_the_diamond_purchase_tab(client, accounts_user, production_user, diamonds):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert f'href="{reverse("inventory:dia_purchase")}">Purchase</a>' in body
    assert "Movements 🔒" in body and "Stock take 🔒" in body
    client.force_login(production_user)
    body = client.get(reverse("inventory:diamonds")).content.decode()
    assert "<button disabled>Purchase 🔒</button>" in body
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=dialedger_t8 ../nornament-app/.venv/bin/pytest inventory/tests/test_dia_purchase_view.py -p no:warnings`
Expected: FAIL. The routes answer 404 (the stubs), and the tab is still `Purchase 🔒`.

- [ ] **Step 3: Write `inventory/views_dia_purchase.py`** (replacing the stub)

```python
"""Diamond purchases: the prototype's screen, posting through ``ledger_dia_purchase``.

Needs Record purchases with sight of cost and suppliers; any other role — or an
admin previewing one — sees "Not permitted". A refusal comes back on the form
with what was typed; a new supplier stands or falls with its purchase. Every
POST acts as the real login.
"""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.capabilities import INV_PURCHASE, ROLE_GROUPS
from stock.masking import mask
from stock.models import Vendor
from stock.services import ServiceError, require

from . import dia_services, inputs, ledger, ledger_dia_purchase
from .ledger_purchase import PURCHASE_RIGHTS, PurchaseHeader
from .models import DiamondLineCost, DiamondTerm, StockDocument
from .views_diamonds import dia_page, viewer

Kind, Status = StockDocument.Kind, StockDocument.Status
FIELDS = ("category", "shape", "colour", "clarity", "size_text", "batch_no", "pcs", "ct", "cost")
TONE = {Status.OPEN: "warn", Status.CLOSED: "good", Status.REVERSED: "crit"}
RECENT_CAP = 20


def _typed(post):
    """The lines as typed, a dict per row; a row left wholly blank is no line."""
    rows = [dict(zip(FIELDS, values)) for values in zip(*(post.getlist(name) for name in FIELDS))]
    return [row for row in rows if any((value or "").strip() for value in row.values())]


def _lines(rows):
    return [ledger_dia_purchase.DiaPurchaseLine(
        category=(row["category"] or "").strip(), shape=(row["shape"] or "").strip(),
        colour=(row["colour"] or "").strip(), clarity=(row["clarity"] or "").strip(),
        size_text=(row["size_text"] or "").strip(), pcs=inputs.whole(row["pcs"], "Pieces"),
        ct=inputs.decimal(row["ct"], "Carats"), cost_per_ct=inputs.decimal(row["cost"], "Cost / ct"),
        batch_no=(row["batch_no"] or "").strip(),
    ) for row in rows]


def _supplier(user, post):
    """The chosen supplier, or a new one saved by Settings' rule, inside the purchase's transaction."""
    raw = post.get("supplier") or ""
    if raw == "new":
        return dia_services.save_supplier(user, None, post.get("new_code"), post.get("new_name"), "", "")
    return Vendor.objects.filter(pk=raw, is_active=True).first() if raw.isdigit() else None


def _recent(user):
    """The latest diamond purchases: when, from whom, how many carats, at what landed cost.

    ponytail: the newest 20; page through when someone asks for more.
    """
    documents = list(StockDocument.objects.filter(kind=Kind.DIA_PURCHASE, reverses__isnull=True)
                     .select_related("vendor").prefetch_related("movements")
                     .order_by("-occurred_on", "-pk")[:RECENT_CAP])
    rates = {(c.document_id, c.line_id): c.cost_rate for c in DiamondLineCost.objects.filter(document__in=documents)}
    rows = []
    for d in documents:
        moves = list(d.movements.all())
        rows.append(mask(user, {
            "pk": d.pk, "number": d.number, "occurred_on": d.occurred_on, **ledger.party(d),
            "ct": sum((m.ct for m in moves), ledger.ZERO),
            "cost_amount": sum((m.ct * rates.get((d.pk, m.diamond_id), 0) for m in moves), ledger.ZERO),
            "status": d.get_status_display(), "tone": TONE[d.status], "reversed": d.status == Status.REVERSED,
        }))
    return rows


@login_required
def purchase(request):
    form, rows, error = {}, [dict.fromkeys(FIELDS, "")], None
    if request.method == "POST":
        for permission in PURCHASE_RIGHTS:
            require(request.user, permission,
                    "Recording a purchase needs the purchase right and sight of cost and suppliers.")
        form, rows = request.POST, _typed(request.POST) or rows
        try:
            with transaction.atomic():           # a new supplier stands or falls with its purchase
                currency = form.get("currency", "INR")
                header = PurchaseHeader(
                    supplier=_supplier(request.user, form),
                    occurred_on=inputs.day(form.get("occurred_on"), "Purchase date") or timezone.localdate(),
                    invoice_no=form.get("invoice_no", ""), currency=currency,
                    fx_rate=inputs.decimal(form.get("fx_rate"), "Rate to INR") if currency == "USD" else None,
                    landed_extras=inputs.decimal(form.get("landed_extras"), "Landed extras") or Decimal("0"),
                    note=form.get("note", ""),
                )
                document = ledger_dia_purchase.post_dia_purchase(request.user, header, _lines(_typed(form)))
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            messages.success(request, f"Purchase {document.number} posted.")
            return redirect("inventory:dia_purchase")
    user, role = viewer(request)
    role_label = ROLE_GROUPS[role]["name"]
    if not all(user.has_perm(permission) for permission in PURCHASE_RIGHTS):
        return dia_page(request, "inventory/diamonds/purchase.html", dtab="purchase", denied=True,
                        role_label=role_label)
    previewing = user is not request.user
    return dia_page(
        request, "inventory/diamonds/purchase.html", dtab="purchase", denied=False, role_label=role_label,
        can_post=not previewing, can_reverse=not previewing, form=form, lines=rows, error=error,
        suppliers=[mask(user, {"pk": v.pk, "vendor_name": v.name, "city": v.city})
                   for v in Vendor.objects.filter(is_active=True).order_by("name")],
        categories=dia_services.term_values(DiamondTerm.CATEGORY), shapes=dia_services.term_values(DiamondTerm.SHAPE),
        colours=dia_services.term_values(DiamondTerm.COLOUR), clarities=dia_services.term_values(DiamondTerm.CLARITY),
        recent=_recent(user), today=timezone.localdate().isoformat(),
    )


@login_required
@require_POST
def purchase_reverse(request, pk):
    require(request.user, INV_PURCHASE, "Only a role that records purchases can reverse one.")
    doc = get_object_or_404(StockDocument, pk=pk, kind=Kind.DIA_PURCHASE, reverses__isnull=True)
    try:
        reversal = ledger.reverse_document(request.user, doc)
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
    else:
        messages.success(request, f"Reversed by {reversal.number}.")
    return redirect("inventory:dia_purchase")
```

- [ ] **Step 4: Write `inventory/templates/inventory/diamonds/purchase.html`**

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Purchases · Diamonds{% endblock %}
{% block crumb %}<b>Diamonds</b> &nbsp;›&nbsp; Purchases{% endblock %}
{% block content %}
{% include "inventory/diamonds/_dsub.html" %}
{% if denied %}
<div class="dbanner"><h2>Purchases</h2></div>
<div class="banner crit"><div class="banner-ic">✕</div><div><h4>Not permitted for {{ role_label }}</h4></div></div>
{% else %}
<div class="dbanner"><h2>Purchase — the only way diamond stock enters</h2></div>
{% if error %}<div class="banner crit"><div class="banner-ic">!</div><div><h4>{{ error }}</h4></div></div>{% endif %}

<div class="tx-cols">
  {% if can_post %}
  <form method="post" id="purchase" class="card">{% csrf_token %}
    <div class="card-h"><span class="card-t">The purchase</span></div>
    <div class="card-b">
      <div class="two">
        <div class="fld"><label>Supplier <span style="color:var(--critical)">*</span></label>
          <select class="inp" name="supplier"><option value="">—</option>
            {% for s in suppliers %}{% if 'vendor_name' in s %}<option value="{{ s.pk }}"{% if form.supplier == s.pk|stringformat:"s" %} selected{% endif %}>{{ s.vendor_name }}{% if s.city %}, {{ s.city }}{% endif %}</option>{% endif %}{% endfor %}
            {% if caps.inv_masters and caps.view_vendor %}<option value="new"{% if form.supplier == 'new' %} selected{% endif %}>＋ New supplier…</option>{% endif %}
          </select></div>
        <div class="fld"><label>Purchase date <span style="color:var(--critical)">*</span></label>
          <input class="inp" type="date" name="occurred_on" value="{{ form.occurred_on|default:today }}"></div>
      </div>
      <div id="newsupplier" hidden><div class="two">
        <div class="fld"><label>Supplier code</label><input class="inp mono" name="new_code" maxlength="32" value="{{ form.new_code|default:'' }}"></div>
        <div class="fld"><label>Supplier name</label><input class="inp" name="new_name" maxlength="120" value="{{ form.new_name|default:'' }}"></div>
      </div></div>
      <div class="two">
        <div class="fld"><label>Invoice no.</label>
          <input class="inp mono" name="invoice_no" maxlength="40" placeholder="2026/0442" value="{{ form.invoice_no|default:'' }}"></div>
        <div class="fld"><label>Currency</label><select class="inp" name="currency">
          <option value="INR"{% if form.currency != 'USD' %} selected{% endif %}>INR ₹</option>
          <option value="USD"{% if form.currency == 'USD' %} selected{% endif %}>USD $</option></select></div>
      </div>
      <div id="fx" hidden><div class="fld"><label>Rate to INR <span style="color:var(--critical)">*</span></label>
        <div class="unit"><input class="inp tnum" name="fx_rate" inputmode="decimal" value="{{ form.fx_rate|default:'' }}"><span class="u">₹ / $</span></div></div></div>

      <div class="grp-t" style="margin:16px 0 9px">Lines — each becomes a stock line</div>
      <div style="overflow:auto"><table class="pt" id="lines"><thead><tr>
        <th>Category</th><th>Shape</th><th>Colour</th><th>Clarity</th><th>Size</th><th>Batch</th>
        <th class="r">Pieces</th><th class="r">Carats</th><th class="r">Cost / ct</th><th class="r">Cost</th></tr></thead>
        <tbody>{% for l in lines %}<tr>
          <td><select class="inp" name="category"><option value=""></option>{% for v in categories %}<option{% if v == l.category %} selected{% endif %}>{{ v }}</option>{% endfor %}</select></td>
          <td><select class="inp" name="shape"><option value=""></option>{% for v in shapes %}<option{% if v == l.shape %} selected{% endif %}>{{ v }}</option>{% endfor %}</select></td>
          <td><select class="inp" name="colour"><option value=""></option>{% for v in colours %}<option{% if v == l.colour %} selected{% endif %}>{{ v }}</option>{% endfor %}</select></td>
          <td><select class="inp" name="clarity"><option value=""></option>{% for v in clarities %}<option{% if v == l.clarity %} selected{% endif %}>{{ v }}</option>{% endfor %}</select></td>
          <td><input class="inp mono" name="size_text" maxlength="40" value="{{ l.size_text }}" style="width:90px"></td>
          <td><input class="inp mono" name="batch_no" maxlength="40" value="{{ l.batch_no }}" style="width:80px"></td>
          <td class="r"><input class="inp tnum" name="pcs" inputmode="numeric" value="{{ l.pcs }}" style="width:70px"></td>
          <td class="r"><input class="inp tnum" name="ct" inputmode="decimal" value="{{ l.ct }}" style="width:80px"></td>
          <td class="r"><input class="inp tnum" name="cost" inputmode="decimal" value="{{ l.cost }}" style="width:90px"></td>
          <td class="r"><b class="lineval">—</b></td></tr>{% endfor %}</tbody></table></div>
      <button class="btn sm" type="button" id="addline" style="margin-top:9px">＋ Add line</button>

      <div class="fld" style="margin-top:12px"><label>Landed extras — freight, duty, certification</label>
        <div class="unit"><input class="inp tnum" name="landed_extras" inputmode="decimal" placeholder="0" value="{{ form.landed_extras|default:'' }}"><span class="u">₹</span></div></div>
      <div class="cons"><b>What posting will do</b>
        <span class="ok">✓</span> create <span id="w-n">0</span> stock lines with sequential references<br>
        <span class="ok">✓</span> post an <code>in</code> movement on each — reason <code>Purchase</code><br>
        <span class="ok">✓</span> write <code>cost per carat</code> on each line, dated <span id="w-date"></span><br>
        <span class="ok">✓</span> total <b id="w-total">₹0</b> across <span id="w-ct">0.00</span> ct<br>
        <span class="ok">✓</span> landed extras <b id="w-extra">₹0</b> spread by weight<br>
        <span style="color:var(--warnink)">!</span> sale price is <b>not</b> set here — it is a separate decision by whoever holds the sale right
      </div>
      <div class="fld" style="margin-top:12px"><label>Note</label><input class="inp" name="note" value="{{ form.note|default:'' }}"></div>
      <button class="btn pri" style="width:100%;justify-content:center">Post purchase</button>
    </div></form>
  {% endif %}

  <div class="card"><div class="card-h"><span class="card-t">Recent purchases</span></div>
    <div class="card-b" style="overflow:auto"><table class="pt">
      <thead><tr><th>Date</th><th>Invoice</th><th>Supplier</th><th class="r">Carats</th><th class="r">Cost</th><th></th></tr></thead>
      <tbody>{% for r in recent %}<tr>
        <td>{{ r.occurred_on|date:"d M Y" }}</td>
        <td class="mono">{{ r.number }}</td>
        <td>{% if 'vendor_name' in r %}{{ r.vendor_name }}{% else %}—{% endif %}</td>
        <td class="r tnum">{{ r.ct|ct }}</td>
        <td class="r">{% if 'cost_amount' in r %}{{ r.cost_amount|rupees }}{% endif %}</td>
        <td>{% if r.reversed %}<span class="chip {{ r.tone }}"><span class="dot"></span>{{ r.status }}</span>
          {% elif can_reverse %}<form method="post" action="{% url 'inventory:dia_purchase_reverse' r.pk %}" class="inline">{% csrf_token %}
            <button class="btn sm gho" onclick="return confirm('Reverse purchase {{ r.number|escapejs }}?')">Reverse</button></form>{% endif %}</td>
      </tr>{% empty %}<tr><td colspan="6" class="hint">No diamond purchases yet.</td></tr>{% endfor %}</tbody></table></div></div>
</div>

{% if can_post %}
<script>
/* Totals as typed, and the fields USD and a new supplier need. */
(function () {
  var form = document.getElementById('purchase'), body = form.querySelector('#lines tbody');
  function num(v) { v = parseFloat(String(v || '').replace(/,/g, '')); return isFinite(v) ? v : 0; }
  function inr(v) { return '₹' + Math.round(v).toLocaleString('en-IN'); }
  function field(tr, name) { return tr.querySelector('[name=' + name + ']'); }
  function total() {
    var usd = form.currency.value === 'USD', fx = usd ? num(form.fx_rate.value) : 1, n = 0, ct = 0, cost = 0;
    body.querySelectorAll('tr').forEach(function (tr) {
      var w = num(field(tr, 'ct').value), c = num(field(tr, 'cost').value) * fx;
      tr.querySelector('.lineval').textContent = w && c ? inr(w * c) : '—';
      if (w) { n += 1; ct += w; cost += w * c; }
    });
    document.getElementById('w-n').textContent = n;
    document.getElementById('w-ct').textContent = ct.toFixed(2);
    document.getElementById('w-total').textContent = inr(cost);
    document.getElementById('w-extra').textContent = inr(num(form.landed_extras.value));
    document.getElementById('w-date').textContent = form.occurred_on.value;
    document.getElementById('fx').hidden = !usd;
    document.getElementById('newsupplier').hidden = form.supplier.value !== 'new';
  }
  form.addEventListener('input', total);
  form.addEventListener('change', total);
  document.getElementById('addline').addEventListener('click', function () {
    var tr = body.lastElementChild.cloneNode(true);
    tr.querySelectorAll('input').forEach(function (input) { input.value = ''; });
    tr.querySelectorAll('select').forEach(function (select) { select.selectedIndex = 0; });
    body.appendChild(tr);
    total();
  });
  total();
})();
</script>
{% endif %}
{% endif %}
{% endblock %}
```

- [ ] **Step 5: The diamond Purchase tab**

In `templates/inventory_base.html`, the diamond branch of the tab strip becomes:

```django
      {% if side == 'diamonds' %}
        <button disabled title="Coming soon">Movements 🔒</button>
        {% if caps.inv_purchase and caps.view_cost and caps.view_vendor %}<a class="{% if dtab == 'purchase' %}on{% endif %}" href="{% url 'inventory:dia_purchase' %}">Purchase</a>
        {% else %}<button disabled>Purchase 🔒</button>{% endif %}
        <a class="{% if dtab != 'purchase' %}on{% endif %}" href="{% url 'inventory:diamonds' %}">Diamond stock</a>
        <button disabled title="Coming soon">Stock take 🔒</button>
```

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=dialedger_t8 ../nornament-app/.venv/bin/pytest inventory/tests/test_dia_purchase_view.py inventory/tests/test_dia_search_view.py inventory/tests/test_masking.py -p no:warnings`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add inventory/views_dia_purchase.py inventory/templates/inventory/diamonds/purchase.html \
  templates/inventory_base.html inventory/tests/test_dia_purchase_view.py
git commit -m "$(cat <<'EOF'
The diamond Purchases screen and top-bar tab: described lines, landed extras, recent purchases, reverse

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---
### Task 9: Wiring — the rail, the sub-tabs, Search's buttons, real counts, and Settings' supplier purchases

**Files:**
- Modify: `inventory/templates/inventory/diamonds/_rail.html`, `inventory/templates/inventory/diamonds/_dsub.html`, `inventory/templates/inventory/diamonds/search.html`, `inventory/views_diamonds.py`, `inventory/dia_rows.py`, `inventory/views_dia_settings.py`
- Create: `inventory/tests/test_dia_wiring.py`

**Interfaces:**
- Consumes:
  - the URL names from Task 2;
  - `ledger_purchase.PURCHASE_RIGHTS`;
  - `StockDocument.Kind/Status`;
  - Tasks 3 to 5's services, in tests only.
- Produces:
  - `dia_rows.rail_counts()` gains `"jobs"` (open job cards) and `"assorts"` (assortments posted, not reversed).
  - The Search view's `can["purchase"]` means all of `PURCHASE_RIGHTS`.
  - The rail and the `.dsub` link Job cards for everyone, and Assortments and Purchases for holders of their rights, padlocked for anyone else. The sub-tabs carry `?as=`. `dtab` values are `jobs`, `assort` and `purchase`.
  - Search's `⚒ Job card`, `⇅ Assort` and `＋ Purchase` become links for holders, carrying `?as=`.
  - The Settings supplier "Purchases" column counts that supplier's purchase documents, stones and diamond, leaving out reversals and reversed documents.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_dia_wiring.py`:

```python
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import dia_rows, ledger
from inventory.ledger_dia_assort import Destination, post_assortment
from inventory.ledger_dia_jobs import open_card
from inventory.ledger_dia_purchase import DiaPurchaseLine, post_dia_purchase
from inventory.ledger_purchase import PurchaseHeader

pytestmark = pytest.mark.django_db
D = Decimal


def _search(client, user, query=""):
    client.force_login(user)
    return client.get(reverse("inventory:diamonds") + query).content.decode()


def test_the_rail_sub_tabs_and_search_open_the_ledgers_by_right(client, accounts_user, karigar_user, sales_user,
                                                                diamonds):
    urls = {name: reverse(f"inventory:{name}") for name in ("dia_jobs", "dia_assorts", "dia_purchase")}
    body = _search(client, accounts_user)
    assert all(f'href="{url}"' in body for url in urls.values())
    assert "⚒ Job card</a>" in body and "⇅ Assort</a>" in body and "＋ Purchase</a>" in body
    assert "Coming soon\">Job cards" not in body and "Job cards 🔒" not in body
    body = _search(client, karigar_user)
    assert f'href="{urls["dia_jobs"]}"' in body and "⚒ Job card</a>" in body
    assert f'href="{urls["dia_assorts"]}"' not in body and f'href="{urls["dia_purchase"]}"' not in body
    assert 'Assortments<span class="ct">🔒' in body and 'Purchases<span class="ct">🔒' in body     # the rail
    assert "Assortments 🔒" in body and "Purchases 🔒" in body                                     # the sub-tabs
    body = _search(client, sales_user)
    assert f'href="{urls["dia_jobs"]}"' in body                     # every internal role reads job cards
    assert "⚒ Job card" not in body and "⇅ Assort" not in body and "＋ Purchase" not in body


def test_a_preview_carries_into_the_ledgers(client, admin_user_, diamonds):
    body = _search(client, admin_user_, "?as=PRODUCTION")
    assert f'href="{reverse("inventory:dia_jobs")}?as=PRODUCTION">⚒ Job card</a>' in body
    assert f'href="{reverse("inventory:dia_jobs")}?as=PRODUCTION">Job cards</a>' in body
    assert "⇅ Assort</a>" not in body                               # Production holds no Assort right


def test_rail_counts_are_real(client, accounts_user, diamonds, parties):
    open_card(accounts_user, None)
    shut = open_card(accounts_user, parties["karigar"])
    ledger.close_document(accounts_user, shut)
    post_assortment(accounts_user, diamonds["round"], D("1"), [Destination("Round", "G", "VS1", "", D("1"))])
    undone = post_assortment(accounts_user, diamonds["princess"], D("0.5"),
                             [Destination("Princess", "G", "VS1", "", D("0.5"))])
    ledger.reverse_document(accounts_user, undone)
    counts = dia_rows.rail_counts()
    assert (counts["jobs"], counts["assorts"]) == (1, 1)
    body = _search(client, accounts_user)
    assert 'Job cards<span class="ct">1</span>' in body and 'Assortments<span class="ct">1</span>' in body


def test_settings_counts_each_suppliers_purchases(client, accounts_user, diamonds):
    line = DiaPurchaseLine("Natural Diamond", "Round", "F-G-H", "VS-SI", "+6-12", None, D("1"), D("16000"))
    supplier = diamonds["supplier"]
    post_dia_purchase(accounts_user, PurchaseHeader(supplier=supplier, occurred_on=date(2026, 8, 7), invoice_no="K-1"),
                      [line])
    gone = post_dia_purchase(accounts_user, PurchaseHeader(supplier=supplier, occurred_on=date(2026, 8, 7),
                                                           invoice_no="K-2"), [line])
    ledger.reverse_document(accounts_user, gone)
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:dia_settings")).content.decode()
    row = body.split("Kothari Exports</b>")[1].split("</tr>")[0]
    assert '<td class="r">1</td>' in row


def test_the_diamond_movements_and_stock_take_tabs_stay_locked(client, accounts_user, diamonds):
    body = _search(client, accounts_user)
    assert "Movements 🔒" in body and "Stock take 🔒" in body
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=dialedger_t9 ../nornament-app/.venv/bin/pytest inventory/tests/test_dia_wiring.py -p no:warnings`
Expected: FAIL. The rail still shows `Job cards 🔒`, `rail_counts()` has no `"jobs"` key, and Settings counts every Purchase movement rather than documents.

- [ ] **Step 3: The rail and the sub-tabs**

`inventory/templates/inventory/diamonds/_rail.html`, the first `<nav>` becomes:

```django
<div class="nav-h">Diamonds — internal</div>
<nav class="nav">
  <a class="{% if dtab == 'search' %}on{% endif %}" href="{% url 'inventory:diamonds' %}"><span class="ic">🔍</span>Search stock<span class="ct">{{ drail.lines|grouped }}</span></a>
  <a class="{% if dtab == 'jobs' %}on{% endif %}" href="{% url 'inventory:dia_jobs' %}"><span class="ic">⚒</span>Job cards<span class="ct">{{ drail.jobs }}</span></a>
  {% if caps.inv_assort %}<a class="{% if dtab == 'assort' %}on{% endif %}" href="{% url 'inventory:dia_assorts' %}"><span class="ic">⇅</span>Assortments<span class="ct">{{ drail.assorts }}</span></a>
  {% else %}<span class="locked"><span class="ic">⇅</span>Assortments<span class="ct">🔒</span></span>{% endif %}
  {% if caps.inv_purchase and caps.view_cost and caps.view_vendor %}<a class="{% if dtab == 'purchase' %}on{% endif %}" href="{% url 'inventory:dia_purchase' %}"><span class="ic">＋</span>Purchases</a>
  {% else %}<span class="locked"><span class="ic">＋</span>Purchases<span class="ct">🔒</span></span>{% endif %}
  {% if caps.inv_masters %}<a class="{% if dtab == 'import' %}on{% endif %}" href="{% url 'inventory:dia_import_home' %}"><span class="ic">⇅</span>Import diamonds</a>{% endif %}
</nav>
```

`inventory/templates/inventory/diamonds/_dsub.html` (the whole file):

```django
<div class="dsub">
  <a class="{% if dtab == 'search' %}on{% endif %}" href="{% url 'inventory:diamonds' %}{% if as_role %}?as={{ as_role }}{% endif %}">Search stock</a>
  <a class="{% if dtab == 'jobs' %}on{% endif %}" href="{% url 'inventory:dia_jobs' %}{% if as_role %}?as={{ as_role }}{% endif %}">Job cards</a>
  {% if caps.inv_assort %}<a class="{% if dtab == 'assort' %}on{% endif %}" href="{% url 'inventory:dia_assorts' %}{% if as_role %}?as={{ as_role }}{% endif %}">Assortments</a>
  {% else %}<span title="Not permitted">Assortments 🔒</span>{% endif %}
  {% if caps.inv_purchase and caps.view_cost and caps.view_vendor %}<a class="{% if dtab == 'purchase' %}on{% endif %}" href="{% url 'inventory:dia_purchase' %}{% if as_role %}?as={{ as_role }}{% endif %}">Purchases</a>
  {% else %}<span title="Not permitted">Purchases 🔒</span>{% endif %}
  <a class="{% if dtab == 'settings' %}on{% endif %}" href="{% url 'inventory:dia_settings' %}{% if as_role %}?as={{ as_role }}{% endif %}">Settings</a>
</div>
```

The rail and the sub-tabs test the **real** login's `caps`, because what a login may open is its own, not the previewed role's. An admin previewing Sales still reaches the Assortments page, which then reads "Not permitted for Sales / Showroom", the prototype's behaviour.

- [ ] **Step 4: Search's buttons, built for the previewed role**

In `inventory/views_diamonds.py`, import the purchase rights:

```python
from .ledger_purchase import PURCHASE_RIGHTS
```

and in `search`, the `can` dict becomes:

```python
    can = {"cost": user.has_perm(VIEW_COST), "sale": user.has_perm(VIEW_SALE), "margin": user.has_perm(VIEW_MARGIN),
           "job": user.has_perm("accounts.inv_job"), "assort": user.has_perm("accounts.inv_assort"),
           "purchase": all(user.has_perm(permission) for permission in PURCHASE_RIGHTS)}
```

In `inventory/templates/inventory/diamonds/search.html`, the stock card's header buttons become:

```django
  <div class="card-h"><span class="card-t">Stock</span><span class="spacer"></span>
    {% if can.job %}<a class="btn sm" href="{% url 'inventory:dia_jobs' %}{% if as_role %}?as={{ as_role }}{% endif %}">⚒ Job card</a>{% endif %}
    {% if can.assort %}<a class="btn sm" href="{% url 'inventory:dia_assorts' %}{% if as_role %}?as={{ as_role }}{% endif %}">⇅ Assort</a>{% endif %}
    {% if can.purchase %}<a class="btn sm pri" href="{% url 'inventory:dia_purchase' %}{% if as_role %}?as={{ as_role }}{% endif %}">＋ Purchase</a>{% endif %}</div>
```

- [ ] **Step 5: Real counts**

In `inventory/dia_rows.py`, import the document (the existing import line, plus `StockDocument`) and add two counts:

```python
from .models import DiamondCode, DiamondLine, DiamondTerm, StockDocument
```

```python
def rail_counts():
    by_kind = defaultdict(int)
    for kind in DiamondTerm.objects.values_list("kind", flat=True):
        by_kind[kind] += 1
    documents = StockDocument.objects.filter(reverses__isnull=True)
    return {"lines": dia_services.stocked_lines().exclude(on_ct=0).count(), "codes": DiamondCode.objects.count(),
            "categories": by_kind["category"], "shapes": by_kind["shape"], "colours": by_kind["colour"],
            "clarities": by_kind["clarity"], "bands": by_kind["band"],
            # the prototype's rail badges: open job cards, and assortments posted and standing
            "jobs": documents.filter(kind=StockDocument.Kind.DIA_JOB, status=StockDocument.Status.OPEN).count(),
            "assorts": documents.filter(kind=StockDocument.Kind.DIA_ASSORT)
                                .exclude(status=StockDocument.Status.REVERSED).count()}
```

In `inventory/views_dia_settings.py`, the import from `.models` becomes:

```python
from .models import DiamondCode, DiamondTerm, StockDocument
```

add `from collections import Counter` to the imports, and replace the `purchases` loop with:

```python
    # purchases per supplier: documents, stones and diamond, that stand (not a reversal, not reversed)
    purchases = Counter(StockDocument.objects.filter(
        kind__in=(StockDocument.Kind.PURCHASE, StockDocument.Kind.DIA_PURCHASE), reverses__isnull=True,
    ).exclude(status=StockDocument.Status.REVERSED).values_list("vendor_id", flat=True))
```

(`purchases.get(v.pk, 0)` in the suppliers rows reads a `Counter` unchanged.)

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=dialedger_t9 ../nornament-app/.venv/bin/pytest inventory/tests/test_dia_wiring.py inventory/tests/test_dia_search_view.py inventory/tests/test_dia_settings.py inventory/tests/test_masking.py -p no:warnings`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add inventory/templates/inventory/diamonds/_rail.html inventory/templates/inventory/diamonds/_dsub.html \
  inventory/templates/inventory/diamonds/search.html inventory/views_diamonds.py inventory/dia_rows.py \
  inventory/views_dia_settings.py inventory/tests/test_dia_wiring.py
git commit -m "$(cat <<'EOF'
Unlock the diamond ledgers in the rail, sub-tabs and Search by right; real rail counts and supplier purchases

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---
### Task 10: The masking walk covers every diamond ledger screen and write, and the spec records the plan's decisions

**Files:**
- Modify: `inventory/tests/test_masking.py`, `inventory/tests/conftest.py`, `docs/superpowers/specs/2026-10-01-inventory-diamond-ledgers-design.md`

**Interfaces:**
- Consumes:
  - every `inventory:dia_*` ledger URL name;
  - `ledger_dia_jobs.open_card/post_entry`;
  - `ledger_dia_assort.post_assortment/Destination`;
  - `ledger_dia_purchase.post_dia_purchase/DiaPurchaseLine`;
  - `ledger_purchase.PurchaseHeader`;
  - fixtures `diamonds`, `parties`, `shelf`.
- Produces:
  - fixture `dia_docs`, which returns `diamonds | parties | {"card", "assort", "purchase"}`: a job card naming the karigar with one issue, an assortment with an override, and a purchase from Kothari Exports.
  - constants `DIA_LINE_COST = "23,456"` (the purchase's cost per carat) and `DIA_OVERRIDE = "18,888"` (the assortment's override).
  - `PENDING` is gone; `DIA_LEDGER_SCREENS` joins the every-screen check.

- [ ] **Step 1: A document of each diamond kind a name or a cost can leak from**

Append to `inventory/tests/conftest.py`:

```python
#: a diamond purchase's cost per carat and an assortment's override, findable in a body and nowhere else
DIA_LINE_COST = "23,456"
DIA_OVERRIDE = "18,888"


@pytest.fixture
def dia_docs(admin_user_, diamonds, parties):
    """A job card (karigar), an assortment with a cost override, and a purchase (supplier, cost)."""
    from datetime import date

    from inventory import ledger_dia_assort, ledger_dia_jobs, ledger_dia_purchase
    from inventory.ledger_purchase import PurchaseHeader

    card = ledger_dia_jobs.open_card(admin_user_, parties["karigar"])
    ledger_dia_jobs.post_entry(admin_user_, card, "issue", diamonds["round"], Decimal("1"), ref="CH 2026/0417")
    assort = ledger_dia_assort.post_assortment(
        admin_user_, diamonds["polki"], Decimal("3"),
        [ledger_dia_assort.Destination("Round", "G", "VS1", "+2", Decimal("3"), Decimal("18888"))],
    )
    purchase = ledger_dia_purchase.post_dia_purchase(
        admin_user_, PurchaseHeader(supplier=diamonds["supplier"], occurred_on=date(2026, 8, 7), invoice_no="DIA-7731"),
        [ledger_dia_purchase.DiaPurchaseLine("Natural Diamond", "Round", "F-G-H", "VS-SI", "+6-12", None,
                                             Decimal("2"), Decimal("23456"))],
    )
    return {**diamonds, **parties, "card": card, "assort": assort, "purchase": purchase}
```

- [ ] **Step 2: Extend the walk**

In `inventory/tests/test_masking.py`:

1. The imports become:

```python
from inventory.models import Movement, StockDocument
from inventory.tests.conftest import (
    CUSTOMER, DIA_COST, DIA_COST_VALUE, DIA_LINE_COST, DIA_OVERRIDE, DIA_SALE, DIA_SALE_VALUE, DIA_SUPPLIER, KARIGAR,
    PURCHASE_COST, SUPPLIER, VALUE,
)
```

2. Add to `EXEMPT`:

```python
    # diamond ledger writes: POST-only; each refuses a login without its right (403), asserted in
    # test_the_diamond_ledger_writes_refuse_a_login_without_the_right below
    "inventory:dia_job_new", "inventory:dia_job_post", "inventory:dia_job_close", "inventory:dia_job_undo",
    "inventory:dia_job_reverse", "inventory:dia_assort_reverse", "inventory:dia_purchase_reverse",
```

3. Delete `PENDING`. In `test_every_inventory_screen_is_walked`:

```python
    covered = ({name for name, _, _ in SCREENS} | {name for name, _ in DIAMOND_SCREENS} | LEDGER_SCREENS
               | DIA_LEDGER_SCREENS)
```

```python
    missing = named - covered - EXEMPT
```

4. Add the diamond ledgers' walk at the end of the file:

```python
#: the diamond ledgers' screens, walked by test_no_diamond_ledger_screen_shows_a_login_what_it_may_not_see
DIA_LEDGER_SCREENS = {"inventory:dia_jobs", "inventory:dia_assorts", "inventory:dia_purchase"}

#: what each role may not see on a diamond ledger screen (Production sees suppliers; the Karigar desk, karigars)
DIA_SECRETS = {
    "SALES": (KARIGAR, DIA_SUPPLIER, DIA_LINE_COST, DIA_OVERRIDE, DIA_COST),
    "KARIGAR": (DIA_SUPPLIER, DIA_LINE_COST, DIA_OVERRIDE, DIA_COST),
    "PRODUCTION": (DIA_LINE_COST, DIA_OVERRIDE, DIA_COST),
    "GRAPHIC": (KARIGAR, DIA_SUPPLIER, DIA_LINE_COST, DIA_OVERRIDE, DIA_COST),
}
#: the forms a page shows only to a login that may post, and never in a preview
DIA_FORMS = ("Post an entry", "＋ New job card", "↺ Undo last entry", "＋ New assortment", "Post purchase",
             ">Reverse</button>")


def _dia_ledger_urls(d):
    """Every diamond ledger screen, with each document picked."""
    jobs, assorts = reverse("inventory:dia_jobs"), reverse("inventory:dia_assorts")
    return [jobs, f"{jobs}?card={d['card'].pk}", f"{jobs}?closed=1", assorts, f"{assorts}?doc={d['assort'].pk}",
            reverse("inventory:dia_purchase")]


def _dia_urls(d):
    """The ledger screens plus Search and Settings, where a purchased or assorted line's own cost
    and a supplier's purchases now show."""
    return _dia_ledger_urls(d) + [reverse("inventory:diamonds"), reverse("inventory:dia_settings")]


@pytest.mark.parametrize("fixture, role", [("sales_user", "SALES"), ("karigar_user", "KARIGAR"),
                                           ("production_user", "PRODUCTION"), ("graphic_user", "GRAPHIC")])
def test_no_diamond_ledger_screen_shows_a_login_what_it_may_not_see(client, dia_docs, request, fixture, role):
    client.force_login(request.getfixturevalue(fixture))
    for url in _dia_urls(dia_docs):
        response = client.get(url)
        assert response.status_code == 200, f"{url} returned {response.status_code}"
        body = response.content.decode()
        for secret in DIA_SECRETS[role]:
            assert secret not in body, f"{url} leaked {secret!r} to {fixture}"


@pytest.mark.parametrize("role", ["SALES", "KARIGAR", "PRODUCTION", "GRAPHIC", "ACCOUNTS"])
def test_an_admin_preview_of_each_diamond_ledger_masks_like_the_role_and_hides_every_form(
        client, admin_user_, dia_docs, role):
    client.force_login(admin_user_)
    ledger_urls = _dia_ledger_urls(dia_docs)
    for url in _dia_urls(dia_docs):
        previewed = f"{url}{'&' if '?' in url else '?'}as={role}"
        body = client.get(previewed).content.decode()
        for secret in DIA_SECRETS.get(role, ()):
            assert secret not in body, f"{previewed} leaked {secret!r}"
        # Settings' rights matrix has a "Post purchase" column, so only the ledger screens are checked for forms
        for form in DIA_FORMS if url in ledger_urls else ():
            assert form not in body, f"{previewed} showed {form!r} in a preview"


def test_each_diamond_name_and_cost_reaches_those_who_may_see_it(client, accounts_user, karigar_user, dia_docs):
    client.force_login(karigar_user)
    assert KARIGAR in client.get(reverse("inventory:dia_jobs")).content.decode()
    client.force_login(accounts_user)
    assert KARIGAR in client.get(reverse("inventory:dia_jobs")).content.decode()
    purchases = client.get(reverse("inventory:dia_purchase")).content.decode()
    assert DIA_SUPPLIER in purchases and "₹46,912" in purchases                   # 2 ct × ₹23,456
    search = client.get(reverse("inventory:diamonds")).content.decode()
    assert DIA_LINE_COST in search and DIA_OVERRIDE in search
    assert "Cost / ct" in client.get(reverse("inventory:dia_assorts")).content.decode()


def test_the_diamond_ledger_writes_refuse_a_login_without_the_right(client, sales_user, dia_docs):
    d = dia_docs
    client.force_login(sales_user)
    before = (Movement.objects.count(), StockDocument.objects.count())
    for url, data in [
        (reverse("inventory:dia_job_new"), {}),
        (reverse("inventory:dia_job_post", args=[d["card"].pk]), {"entry": "loose", "line": d["round"].pk, "ct": "1"}),
        (reverse("inventory:dia_job_close", args=[d["card"].pk]), {}),
        (reverse("inventory:dia_job_undo", args=[d["card"].pk]), {}),
        (reverse("inventory:dia_job_reverse", args=[d["card"].pk]), {}),
        (reverse("inventory:dia_assorts"), {"source": d["round"].pk, "take_out": "1", "ct": "1"}),
        (reverse("inventory:dia_assort_reverse", args=[d["assort"].pk]), {}),
        (reverse("inventory:dia_purchase"), {"supplier": d["supplier"].pk}),
        (reverse("inventory:dia_purchase_reverse", args=[d["purchase"].pk]), {}),
    ]:
        assert client.post(url, data).status_code == 403, url
    assert (Movement.objects.count(), StockDocument.objects.count()) == before


def test_no_stones_screen_lists_or_opens_a_diamond_document(client, accounts_user, shelf, dia_docs):
    client.force_login(accounts_user)
    recent = client.get(reverse("inventory:recent")).content.decode()
    for doc in ("card", "assort", "purchase"):
        assert dia_docs[doc].number not in recent, doc
        assert client.get(reverse("inventory:document", args=[dia_docs[doc].pk])).status_code == 404, doc
    for url in (reverse("inventory:job_work_list") + "?closed=1", reverse("inventory:shelf")):
        assert dia_docs["card"].number not in client.get(url).content.decode(), url
```

- [ ] **Step 3: Run the walk**

Run: `POSTGRES_DB=dialedger_t10 ../nornament-app/.venv/bin/pytest inventory/tests/test_masking.py -p no:warnings`
Expected: PASS. A leak names the screen and the value. Fix it with a key test in the template or a `mask()` in the row, never a capability test.

- [ ] **Step 4: Record the planning decisions in the spec**

Append to `docs/superpowers/specs/2026-10-01-inventory-diamond-ledgers-design.md`:

```markdown
## Changed while planning

- **Numbers.** Job cards are `JC-000001`, assortments `AS-000001` and purchases without an invoice no. `DP-000001` (part 2's six-digit automatic numbers, not the prototype's `JC-2026-0311`). A diamond purchase's invoice no. is unique among diamond purchases; a stones purchase may share it. The document kinds read "Job card", "Assortment" and "Diamond purchase"; the kind column is widened to 12 characters for `dia_purchase`.
- **The six job-card entries.** Issue to job card is a debit (Job Work Out, out). Received loose (Job Work In) and Returned unused (Returned Unused) are credits that come back into the line. Consumed / set (Consumed in Production), Loss in process (Wastage / Loss in Process) and Breakage (Breakage) are credits that settle. Received loose and Returned unused move stock the same way; only their reason, and so the ledger's chip, tells them apart. Job-card entries carry carats only.
- **The line picker** names a line as ref · item code · size · batch (`NRD-000001 · DRFGH VS-SI · +6-12 · B-771`) with its carats. An issue may pick any line with carats on hand; a credit, the card's lines with carats out (each shown with what is out). The server checks either way.
- **The engine.** A movement's owner is a pouch or a diamond line. A diamond line moves by carats; its pieces ride along unchecked. A job card's credits are checked per line against what is out; a job card never closes itself, closes by `Close` only at zero, and an undo reopens it when something is outstanding again. Stones job work and memos are unchanged.
- **An assortment's movements.** The source gets an Assort Out of what went into new lines and a Wastage / Loss in Process out of the sorting loss (the stones split's precedent); each destination an Assort In. The screen shows the prototype's ledger: the source debited with everything taken out, each destination and the sorting loss credited, running to zero. A blank destination size is the source's size.
- **Cost carried through an assortment** is source cost per ct × taken out ÷ (taken out − loss), to 4 places, dated the assortment's date; an override needs sight of cost, a carried cost does not.
- **Codes from a description.** The existing code with exactly that shape, colour and clarity is used (a confirmed one first). Otherwise a new code is created confirmed, named in the register's grammar (`DRG VS1`) when the shape and colour have tokens, else in words (`D Polki I-J SI-I`); if that name already reads differently, the post is refused. Shape, colour, clarity and category must already be on the master lists: a purchase or assortment never adds to them.
- **A purchase line** may carry a batch no. (a Batch column beside Size). Its band follows part 3's rules, the per-stone rule included (shared with the importer). Its own cost is cost × rate + extras ÷ the purchase's total carats, to 4 places, dated the purchase date. A new supplier is saved with the purchase, in its transaction (Edit settings + supplier sight, as on stones).
- **Own cost wins everywhere** because `stocked_lines` carries it and `price` reads it first; the Settings rate card and the importer's rate comparison stay the rate card's alone.
- **Stones screens show stones.** The rail's Movements list and its kind filter show stones kinds only; the stones document page and its actions answer 404 for a diamond document; what is out on job work counts stones only.
- **A karigar named on a diamond job card** may be named again by the Karigar desk, as one named on a stones challan; In-house is a card with no karigar, and a karigar the viewer may not see never reads as In-house.
- **Rights in the rail.** Job cards are linked for every internal role, with the count of open cards. Assortments (count: posted and standing) and Purchases are linked for holders of their rights and padlocked otherwise; a holder's preview of another role still reaches them and reads "Not permitted for {role}". Search's ⚒ / ⇅ / ＋ carry the preview.
- **Settings' supplier "Purchases"** counts that supplier's purchase documents, stones and diamond, that stand (not a reversal, not reversed).
- **Corrections on the screens.** Reverse sits on a job card's ledger, an assortment's ledger and each row of Recent purchases (the newest 20, with each purchase's landed cost).
- **Carats on screen** are shown to 2 places as the prototype did; the job card's outstanding chip and every refusal print up to 4 places, trailing zeros trimmed.
```

- [ ] **Step 5: Run the whole suite**

Run: `POSTGRES_DB=dialedger_t10 ../nornament-app/.venv/bin/pytest -p no:warnings`
Expected: only the known pre-existing S3 failure. Every part 2 stones test is unchanged and green, the real diamond file test passes (281 lines, 546.96 ct, cost ₹1,47,98,794 ± ₹10), and the parity test passes.

Run: `POSTGRES_DB=dialedger_t10 ../nornament-app/.venv/bin/python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 6: Commit**

```bash
git add inventory/tests/test_masking.py inventory/tests/conftest.py docs/superpowers/specs/2026-10-01-inventory-diamond-ledgers-design.md
git commit -m "$(cat <<'EOF'
Walk every diamond ledger screen and write as every role and in the preview, and record the plan's decisions

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Decided while planning

The spec did not pin these down. Task 10 records them in the spec's "Changed while planning".

1. **Kinds and numbers.** The three diamond kinds are `dia_job` ("Job card"), `dia_assort` ("Assortment") and `dia_purchase` ("Diamond purchase"). `StockDocument.kind` widens from 10 to 12 characters, because `dia_purchase` is 12. Automatic numbers use part 2's `ledger.next_number`: `JC-000001`, `AS-000001`, `DP-000001` (six digits), not the prototype's `JC-2026-0311`. A typed purchase invoice no. is unique per kind, so a diamond purchase and a stones purchase may share one.
2. **The six entries map to reasons and directions** as follows. Issue to job card is a debit: Job Work Out, out. Received loose is Job Work In, in. Returned unused is the new Returned Unused, in. Consumed / set is Consumed in Production, settle. Loss in process is Wastage / Loss in Process, settle. Breakage is Breakage, settle. The select reads "{label} — debit / credit" as the prototype's does. Entries carry carats only, with no pieces.
3. **Returned unused and Received loose** both put carats back on the line and take them off what the card owes; the balance effect is identical. Each has its own reason, so the ledger's chip ("Returned unused" against "Received loose") and any later report can tell stones that came back after work from stones never worked. Both chips are green credits. An undone entry shows "↺ {label}" with no tone, on the opposite side.
4. **The line picker** identifies a line by ref · item code · size (band if no size) · batch ("no batch" if blank), `dia_services.line_label`, with its carats; the option value is the line's pk. It is one `<select>` with two optgroups: "In stock — to issue" (every line with carats on hand) and "Out on this card — to credit" (the card's lines with carats out, and how much). There is no JavaScript. The server's checks (below zero, cannot exceed what is outstanding on that line) are the rule.
5. **The engine.** `Line.pouch` becomes `Line.owner`. Every caller passes it positionally, so none changes. `OPENABLE` (closes itself) stays stones-only. `OWED` (credits checked per owner) adds `dia_job`, and `CLOSABLE` (`dia_job`) closes only by `ledger.close_document`. A job card's status is recomputed on every write: it reopens when something is outstanding again and otherwise keeps its status. `undo_last` accepts a `dia_job`, and its refusal message keeps the stones prefix so part 2's tests match. A diamond movement needs carats above zero; its pieces are stored but never checked. `out_summary` and `owed_by_document` stay stones-only.
6. **Close is the engine's**, `ledger.close_document`, rather than a `close_card` wrapper in `ledger_dia_jobs`, which would add nothing. The same goes for undo and reverse. Its refusals are "{JC-…} can close only at zero: {x} ct outstanding." and "… only an open card can close.".
7. **An assortment's movements** follow the stones split precedent. The source gets Assort Out of (taken out − loss) plus a Wastage / Loss in Process out of the loss, so the source drops by exactly what was taken out. The screen rebuilds the prototype's view from those movements: one "Assort out" debit of the whole amount taken out, an "Assort in" credit per destination, and a "Sorting loss" credit, running to zero. A blank destination size takes the source's size. New lines get the source's category and batch no., and a blank `src`.
8. **The carried cost** is quantized to 4 places, the column's precision, and dated the assortment's date, with `document` set. An override is refused without `view_cost`; a carried cost needs no sight of it, because the user never sees or types it. A source with no cost at all writes no row.
9. **Codes.**
   - **Lookup.** `code_for` looks for the code whose shape, colour and clarity terms are exactly those given, ordered confirmed first and then by name. Otherwise it creates one, confirmed, named `D` + shape token + colour token + clarity when the grammar has the tokens (`DRG VS1`, `DREF VVS-VS`), else in words (`D Polki I-J SI-I`).
   - **Clash.** If that name already exists with another reading, the post is refused and the reading is corrected in Settings.
   - **The lists.** Every value must already be on its master list. Purchases and assortments never create terms; the pickers offer only `dia_services.term_values` (no `?` or `(` values).
   - **What is required.** Shape and colour are required, for purchases and assortment destinations alike; clarity is required too **unless the colour is a Fancy colour** (controller ruling during planning review, 2026-10-01: the owner's file holds many fancy lots, e.g. DFY/DFO, whose codes have no clarity). For a fancy colour with blank clarity, `code_for` finds the existing code with that shape and colour and no clarity (e.g. Mix + Fancy Yellow → DFY), or creates one named in the register's grammar without a clarity suffix.
10. **Purchase lines.**
    - **Band.** It comes from `dia_services.sized`: part 3's `size_band` plus the per-stone rule, which the importer now calls too, so there is one rule.
    - **Batch.** An optional Batch column sits beside Size, since spec rule 3 allows a batch no.
    - **Cost.** Own cost = cost/ct × rate (1 for INR) + extras ÷ the purchase's total carats, to 4 places, dated the purchase date.
    - **What it reuses.** It reuses part 2's `PurchaseHeader`, `PURCHASE_RIGHTS` and a newly extracted `check_header`, so the header messages match stones word for word.
11. **"＋ New supplier…"** is saved by the view inside the purchase's `transaction.atomic`, exactly as the stones purchase view does (`dia_services.save_supplier`, which needs Edit settings and supplier sight), rather than inside `post_dia_purchase`. This keeps the service's signature to header and lines.
12. **Own cost first, everywhere.** `stocked_lines` annotates `own_cost` with a subquery, as `services.stocked` does for a pouch's rate. `price` reads that annotation, or queries for a line not read through `stocked_lines`, so no caller can skip it. This covers Search rows, tiles and margin (`dia_rows.line_row`), the assortment's source cost, and the real-file test's sum, which is unchanged because imported lines have no own cost. The Settings rate card and the importer's "rate differs" comparison stay the rate card's alone. A future-dated own cost waits for its day, like a rate.
13. **Stones screens show stones.** `ledger.STONE_KINDS` filters the rail's Movements list and its kind filter. The stones document page and its settle, undo and reverse actions answer 404 for a diamond document. `owed_by_document` reads pouch movements only.
14. **Karigars and In-house.** `karigar_choices` counts vendors named on a stones challan or a diamond job card, so the Karigar desk may re-use a karigar Admin or Accounts named on either. In-house is a card with no vendor. The card row carries `in_house` as its own key, so a karigar masked from the viewer shows as "karigar" in the picker and "—" in the header, never as "In-house". An unknown karigar pk is refused, never taken as In-house.
15. **Preview and rights on the screens.** Each page is built for `viewer(request)`, and forms appear only when not previewing and the real login holds the right. Job cards read "read only for {role}" when the viewed role lacks Job cards. Assortments and Purchases render "Not permitted for {role}" (the role's display name, e.g. "Sales / Showroom"). Every POST view calls `require` before reading the form, so a login without the right gets 403 and nothing is parsed.
16. **Rail, sub-tabs and Search.** Job cards is a live link for every internal login, counting open cards. Assortments, counting posted and not reversed, and Purchases, with no count as in the prototype, are live for holders of their rights and padlocked otherwise. These use the **real** login's `caps`, so an admin's preview of another role still reaches a page that then says "Not permitted". The sub-tabs and Search's ⚒ / ⇅ / ＋ carry `?as=`, and Search's buttons follow the previewed role. The diamond top bar's Purchase tab is live for purchase-right holders. Movements and Stock take stay padlocked.
17. **Settings' supplier "Purchases"** counts purchase documents of both kinds that stand (`reverses` null, not Reversed). It used to count stones and diamond Purchase movements, which counted one purchase once per line.
18. **Where corrections live.** The job card ledger's header holds ↺ Undo last entry, Close (shown only at zero) and Reverse. The assortment ledger's header holds Reverse. Each row of Recent purchases holds Reverse, or a "Reversed" chip once it is reversed. Recent purchases lists the newest 20, each with carats and its landed cost (Σ carats × the cost each line got).
19. **Formatting.** Ledger tables show carats to 2 places, the `ct` filter and the prototype's `fmtW`. The job card's "{x} ct outstanding" chip, the assortment's live balance line and every refusal print up to 4 places with trailing zeros trimmed (`ledger._ct`, mirrored in the JS).
20. **Parallel build.** Task 2 routes every diamond ledger URL to `Http404` stubs in the three modules wave 4 fills, and lists them as `PENDING` in the every-screen check. Task 10 removes `PENDING`. So the rail, the sub-tabs, Search and the top bar link to the screens while they are built in parallel, and no wave-4 task edits `urls.py`.
