# Inventory Part 2 (Stones Ledger) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make stones stock move — Record movement (every reason a person posts), Purchase, Split pouch, Transfer to another batch, a page per document with settle / undo / reverse, the Job work out and Memo out lists, the rail's Movements, and the shelf's "Out on job work / memo" figure.

**Architecture:** One header, `StockDocument`, for every kind of post; movements hang off it. `inventory/ledger.py` is the only writer of movements for these actions: `post()` writes a document's movements in one transaction and runs every shared check (quantities above zero, uncountable by weight only, nothing settled beyond what is out, no pouch below zero), and reversals are new movements that point at the one they cancel. A `settle` direction records what is consumed, lost or sold while out, and never touches a balance; the one balance rule (`models.balance`) is shared by stones and diamonds. Services per action sit in their own modules (`ledger_jobs`, `ledger_single`, `ledger_purchase`, `ledger_assort`); views are thin and per screen; rows go through `stock.masking.mask`.

**Tech Stack:** Django 5.2, Postgres 17, pytest + pytest-django, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-01-inventory-stones-ledger-design.md` (binding). Part 1: `2026-09-28-inventory-stones-design.md`.

**Prototype source (read, never edit):** `../Nornament_Inventory/04-source-scripts/_script.html` — `renderTx` lines 468–613 (Movements page, ledger, the "Record movement" card, its 12 reasons, field labels, "Checks that will run"), `renderPurchase` 1211–1302 (purchase screen, Price list and Stock control cards), `diaJob` 853–931 and `diaAssort` 934–1013 (the ledger-card and must-balance patterns). Line N there is mockup line N+576. The CSS the screens use is already in `static/css/inventory.css` (`.tx-top`, `.tx-cols`, `.derived`, `.led`, `.ledtot`, `.dir`, `.chal`, `.fld`, `.two`, `.unit`, `.cons`, `.filterbar`, `.fsel`, `.ro2`, `.pt`, `.totstrip`, `.tot`, `.banner`, `.chip`, `.dbanner`).

## Global Constraints

- **Standalone rule:** add no new dependency on stock or CRM data, with the one exception the owner made on 2026-10-01: **customers come from the CRM** (`crm.Customer`) for memos, sales and sales returns. Karigars and suppliers are `stock.Vendor` (part 1's existing tie). Reuse, do not duplicate: `stock.services.ServiceError/require/log`, `stock.masking.mask/allowed`, `inventory.dia_services.save_supplier`.
- **Masking:** rows are built once and end in `stock.masking.mask()`. Templates test **key presence** (`{% if 'pouch_value' in row %}`), never capabilities, for anything money- or name-shaped. Gated keys used here: `cost_amount`, `pouch_value`, `purchase_rate`, `stone_rate` (view_cost); `vendor_name` (view_vendor); `customer_name` (view_sale) and `karigar_name` (inv_job), both added to `stock/masking.py` by Task 1. Action buttons may test `caps.*` (part 1's precedent for actions). A template never prints `doc.vendor` or `doc.customer` directly.
- **Errors:** every refusal is a `ServiceError` with a plain message, shown on the form it came from (the form re-renders with what was typed) or, on the document page, as a message. A missing right is `PermissionDenied` from `require`, which Django answers with 403.
- **One transaction per post:** every service that writes is `@transaction.atomic`; `ledger.post` writes all of a document's movements or none.
- **Views never write models;** writes live in `inventory/ledger*.py` (and `services.recount` for the importer).
- **Shell:** every screen extends `templates/inventory_base.html` (part 1 shell, CSS, dark mode, phone drawer). Use only existing classes of `static/css/inventory.css`; add no CSS. Wide tables sit in `<div style="overflow:auto">`. Never put `hidden` on an element whose class sets `display` (`.two`, `.banner`, `.btn`) — wrap it in a plain `<div>` and hide that.
- **Prose stripped:** no explainer banners, footers or "why" paragraphs from the prototype; its labels, functional warnings and the "Checks that will run" / "What posting will do" cards stay.
- **Client view:** none of the new screens or POSTs is reachable in client view — each redirects (`_client(request)`), so no counterparty or reference ever reaches a client.
- Still padlocked (`🔒`, never a dead link): Stock takes, Merge, Splits & merges, Transfers, Price lists, Suppliers, Client lookbook, the diamond ledgers.
- Follow the surrounding style: docstrings say *why*; no type annotations except dataclass fields.
- Only database tests carry `pytestmark = pytest.mark.django_db`; pure-function tests do not. Tests use the real role fixtures in the root `conftest.py` (`admin_user_`, `accounts_user`, `sales_user`, `graphic_user`, `production_user`, `karigar_user`) and `inventory/tests/conftest.py` (`shelf`, `diamonds`, and `parties` from Task 2).
- Run tests from the repo root with a **private database name** per task: `POSTGRES_DB=ledger_tN .venv/bin/pytest <paths> -p no:warnings` (from a sibling worktree: `POSTGRES_DB=ledger_tN ../nornament-app/.venv/bin/pytest <paths> -p no:warnings`). Known pre-existing environmental failure to ignore: `stock/tests/test_import_commit.py::test_images_are_attached_in_chunks_and_are_resumable` (live S3 401).
- Commit messages end with a blank line and `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|---|---|
| `inventory/models.py` (modify) | `StockDocument`; `Movement.document`, `Movement.SETTLE`, `Movement.reverses`, `Movement.effect`; `Pouch.parent`; `balance()` — the one balance rule |
| `inventory/migrations/0007_stones_ledger.py` (generated) | schema |
| `accounts/capabilities.py`, `accounts/models.py`, `accounts/migrations/0005_inv_move.py` | the `inv_move` right ("Record stock movements"), through the add-only sync |
| `stock/views.py` (modify) | the stock Settings → Permissions matrix gains the `inv_move` row |
| `stock/masking.py` (modify) | `karigar_name` → inv_job, `customer_name` → view_sale |
| `inventory/services.py`, `inventory/dia_services.py` (modify) | balances through `balance()`; `recount_deltas`; `RIGHTS` gains `inv_move` |
| `inventory/inputs.py` | reading form fields: blank → `None`, anything else must read |
| `inventory/ledger.py` | numbering, `open_document`, `post` and its checks, outstanding, reversal, undo, pouch numbers, `party`, `out_summary` |
| `inventory/ledger_jobs.py` | job work out / settle, memo out / settle, karigar and customer choices |
| `inventory/ledger_single.py` | sale, sales return, purchase return, breakage, wastage, sample, consumed, recount |
| `inventory/ledger_purchase.py` | `post_purchase`, `PurchaseHeader`, `PurchaseLine`, `PURCHASE_RIGHTS` |
| `inventory/ledger_assort.py` | `split_pouch`, `SplitPart`, `transfer_pouch` |
| `inventory/views_ledger.py` | pouch Movements page and Record movement POST |
| `inventory/views_purchase.py` | Record a purchase |
| `inventory/views_assort.py` | Split pouch, Transfer to another batch |
| `inventory/views_documents.py` | document page, settle / undo / reverse |
| `inventory/views_lists.py` | Job work out, Memo out, rail Movements |
| `inventory/urls.py` (modify, Task 2 only) | every ledger route |
| `inventory/rows.py`, `inventory/views.py` (modify) | shelf "Out" tile; the old movements view leaves `views.py` |
| `inventory/templates/inventory/` | `movements.html` (rewrite), `purchase.html`, `split.html`, `transfer.html`, `document.html`, `out_list.html`, `recent.html`; `_rail.html`, `_totals.html`, `pouch.html` (modify) |
| `templates/inventory_base.html` (modify) | the Purchase tab |
| `inventory/tests/…` | tests per task; `parties` and `ledger_docs` fixtures |

## Parallel waves

| Wave | Tasks | Files each task touches |
|---|---|---|
| 1 | **1** models, migrations, balances, right | `inventory/models.py`, `inventory/migrations/0007_*`, `inventory/services.py`, `inventory/dia_services.py`, `inventory/views.py` (one line), `accounts/*`, `stock/masking.py`, `stock/views.py` (one row), `inventory/tests/test_ledger_models.py` |
| 2 | **2** ledger core | `inventory/ledger.py`, `inventory/inputs.py`, five stub view modules, `inventory/urls.py`, `inventory/tests/conftest.py`, `inventory/tests/test_masking.py`, `inventory/tests/test_ledger.py`, `inventory/tests/test_inputs.py` |
| 3 | **3, 4, 5, 6** in parallel | 3: `ledger_jobs.py` + test · 4: `ledger_single.py`, `services.py` + test · 5: `ledger_purchase.py` + test · 6: `ledger_assort.py` + test |
| 4 | **7, 8, 9, 10, 11** in parallel | 7: `views_ledger.py`, `movements.html`, `views.py` (removes the old `movements` view) · 8: `views_purchase.py`, `purchase.html`, `inventory_base.html` · 9: `views_assort.py`, `split.html`, `transfer.html`, `pouch.html` · 10: `views_documents.py`, `document.html` · 11: `views_lists.py`, `out_list.html`, `recent.html`, `_rail.html`, `_totals.html`, `rows.py`, `views.py` (one line in `shelf`) |
| 5 | **12** masking walk, spec | `inventory/tests/test_masking.py`, `inventory/tests/conftest.py`, the spec |

**Why wave 4 does not fight over files:** Task 2 routes every ledger URL up front to stub views (each raising `Http404`) in the modules wave 4 fills, and lists the names as `PENDING` in the every-screen check. So screens can `{% url %}` one another while built in parallel, and no wave-4 task edits `inventory/urls.py`. The only file two wave-4 tasks share is `inventory/views.py`: Task 7 deletes lines 3, 27–33 and the `movements` view (≈ lines 232–260); Task 11 changes one line in `shelf` (≈ line 70). The hunks are far apart and git merges them; if it does not, the controller keeps both changes.

---

### Task 1: Documents, settle, reversals and the shared balance rule

**Files:**
- Modify: `inventory/models.py`, `inventory/services.py`, `inventory/dia_services.py`, `inventory/views.py`, `accounts/capabilities.py`, `accounts/models.py`, `stock/masking.py`, `stock/views.py` (`CAPABILITY_MATRIX`)
- Create: `inventory/migrations/0007_stones_ledger.py` (generated), `accounts/migrations/0005_inv_move.py`, `inventory/tests/test_ledger_models.py`

**Interfaces:**
- Produces:
  - `StockDocument` (`db_table inv_document`) with `Kind` (`PURCHASE="purchase"`, `JOB_WORK="job_work"`, `MEMO="memo"`, `SPLIT="split"`, `TRANSFER="transfer"`, `SINGLE="single"`), `Status` (`OPEN="open"`, `CLOSED="closed"`, `REVERSED="reversed"`), fields `kind, number, status, vendor, customer, occurred_on, expected_back, note, currency, fx_rate, landed_extras, from_batch, from_pouch_no, to_batch, to_pouch_no, reverses (related_name "reversals"), created_by, created_at`; `__str__` → `"Job work 2026/0431"`; unique `(kind, number)` among non-reversed documents.
  - `Movement.SETTLE = "settle"`; `Movement.document` (FK, related_name `"movements"`); `Movement.reverses` (one-to-one to `Movement`, related_name `"reversal"`); `Movement.effect` → `1 | -1 | 0`.
  - `Pouch.parent` (related_name `"children"`).
  - `inventory.models.balance(field) -> Sum` for `"pcs"` / `"ct"` over `movements__`.
  - `accounts.capabilities.INV_MOVE = "accounts.inv_move"`; `dia_services.RIGHTS` gains `("inv_move", "Record stock movements")`; the stock Settings → Permissions matrix (`stock.views.CAPABILITY_MATRIX`) gains its row.
  - gated keys `karigar_name` (INV_JOB), `customer_name` (VIEW_SALE).

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_ledger_models.py`:

```python
"""The ledger's tables: documents, settles, reversals, a split's parent, and the new right."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError, transaction
from django.urls import reverse

from accounts.capabilities import INV_MOVE
from accounts.models import sync_role_groups
from inventory import dia_services, services
from inventory.models import Movement, Pouch, StockDocument
from stock.masking import mask

pytestmark = pytest.mark.django_db
D = Decimal
R = Movement.Reason


def _held(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()


def _move(pouch, reason, direction, ct, pcs=None, **extra):
    return Movement.objects.create(pouch=pouch, reason=reason, direction=direction, ct=D(ct), pcs=pcs, **extra)


def test_a_settle_never_changes_a_pouch_balance(shelf):
    _move(shelf["onyx"], R.CONSUMED, Movement.SETTLE, "2", pcs=3)
    held = _held(shelf["onyx"])
    assert (held.on_pcs, held.on_ct) == (20, D("12.5"))


def test_a_reversal_counts_with_the_opposite_sign(shelf):
    onyx, ruby = shelf["onyx"], shelf["ruby"]
    sale = _move(onyx, R.SALE, Movement.OUT, "2.5", pcs=5)
    assert (_held(onyx).on_pcs, _held(onyx).on_ct) == (15, D("10"))
    _move(onyx, R.SALE, Movement.OUT, "2.5", pcs=5, reverses=sale)
    assert (_held(onyx).on_pcs, _held(onyx).on_ct) == (20, D("12.5"))
    back = _move(ruby, R.SALES_RETURN, Movement.IN, "1")
    _move(ruby, R.SALES_RETURN, Movement.IN, "1", reverses=back)
    lost = _move(ruby, R.WASTAGE, Movement.SETTLE, "4")
    _move(ruby, R.WASTAGE, Movement.SETTLE, "4", reverses=lost)
    assert _held(ruby).on_ct == D("40")


def test_a_movement_is_reversed_at_most_once(shelf):
    sale = _move(shelf["onyx"], R.SALE, Movement.OUT, "1")
    _move(shelf["onyx"], R.SALE, Movement.OUT, "1", reverses=sale)
    with pytest.raises(IntegrityError), transaction.atomic():
        _move(shelf["onyx"], R.SALE, Movement.OUT, "1", reverses=sale)


def test_diamond_balances_follow_the_same_rule(diamonds):
    line = diamonds["round"]

    def ct():
        return dia_services.stocked_lines().get(pk=line.pk).on_ct

    sale = Movement.objects.create(diamond=line, reason=R.SALE, direction=Movement.OUT, ct=D("1.4"))
    assert ct() == D("2.00")
    Movement.objects.create(diamond=line, reason=R.CONSUMED, direction=Movement.SETTLE, ct=D("0.5"))
    assert ct() == D("2.00")
    Movement.objects.create(diamond=line, reason=R.SALE, direction=Movement.OUT, ct=D("1.4"), reverses=sale)
    assert ct() == D("3.40")


def test_the_movements_page_runs_its_balance_by_the_same_rule(client, admin_user_, shelf):
    onyx = shelf["onyx"]
    sale = _move(onyx, R.SALE, Movement.OUT, "2.5", pcs=5)
    _move(onyx, R.SALE, Movement.OUT, "2.5", pcs=5, reverses=sale)
    _move(onyx, R.CONSUMED, Movement.SETTLE, "1", pcs=1)
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:movements", args=[onyx.ref])).content.decode()
    assert "4 movements" in body and "10.00 ct" in body
    assert body.count("12.50 ct<div") == 3      # balance after the opening, the reversal and the settle


def test_a_document_number_is_unique_per_kind_until_reversed():
    K = StockDocument.Kind
    first = StockDocument.objects.create(kind=K.JOB_WORK, number="2026/0431")
    with pytest.raises(IntegrityError), transaction.atomic():
        StockDocument.objects.create(kind=K.JOB_WORK, number="2026/0431")
    StockDocument.objects.create(kind=K.MEMO, number="2026/0431")          # another kind may share it
    first.status = StockDocument.Status.REVERSED
    first.save()
    StockDocument.objects.create(kind=K.JOB_WORK, number="2026/0431")      # a reversed one's number is free


def test_movements_hang_off_their_document(shelf):
    doc = StockDocument.objects.create(kind=StockDocument.Kind.SINGLE, number="MOV-000001")
    _move(shelf["onyx"], R.BREAKAGE, Movement.OUT, "1", document=doc)
    assert doc.movements.get().reason == R.BREAKAGE and doc.status == StockDocument.Status.OPEN
    assert str(doc) == "Single MOV-000001"


def test_a_split_pouch_remembers_its_parent(shelf):
    child = Pouch.objects.create(ref="NRN-000099", batch=shelf["batch"], pouch_no="9", parent=shelf["onyx"])
    assert list(shelf["onyx"].children.all()) == [child]


def test_record_stock_movements_belongs_to_admin_and_accounts(
    admin_user_, accounts_user, sales_user, production_user, karigar_user, graphic_user
):
    assert admin_user_.has_perm(INV_MOVE) and accounts_user.has_perm(INV_MOVE)
    for user in (sales_user, production_user, karigar_user, graphic_user):
        assert not user.has_perm(INV_MOVE), user


def test_the_add_only_sync_grants_the_new_right():
    Permission.objects.filter(codename="inv_move").delete()      # as if the right were brand new
    sync_role_groups()
    holders = set(Group.objects.filter(permissions__codename="inv_move").values_list("name", flat=True))
    assert holders == {"ADMIN", "ACCOUNTS"}


def test_both_rights_matrices_carry_it(client, admin_user_, diamonds):
    client.force_login(admin_user_)
    body = client.get(reverse("inventory:dia_settings")).content.decode()
    assert "Record stock movements" in body and 'value="inv_move"' in body
    body = client.get(reverse("stock:settings"), {"tab": "perms"}).content.decode()
    assert "Record stock movements" in body and "inv_move" in body


def test_karigar_and_customer_names_mask_by_their_rights(
    karigar_user, production_user, sales_user, graphic_user, accounts_user
):
    row = {"karigar_name": "Mahesh Karigar", "customer_name": "Kalyan Retail"}
    assert mask(karigar_user, row) == {"karigar_name": "Mahesh Karigar"}
    assert mask(production_user, row) == {"karigar_name": "Mahesh Karigar"}
    assert mask(sales_user, row) == {"customer_name": "Kalyan Retail"}
    assert mask(graphic_user, row) == {}
    assert mask(accounts_user, row) == row
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=ledger_t1 .venv/bin/pytest inventory/tests/test_ledger_models.py -p no:warnings`
Expected: FAIL — `ImportError: cannot import name 'INV_MOVE'`.

- [ ] **Step 3: The right, through the add-only sync**

`accounts/capabilities.py` — after `INV_ASSORT`:

```python
#: everything that moves stock that is not job work, a purchase or an assortment:
#: sales, returns, memos, losses, samples, recounts (inventory part 2)
INV_MOVE = "accounts.inv_move"
```

Add `INV_MOVE` to the end of `ALL`, and to the end of the `ACCOUNTS` caps tuple:

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
    INV_MOVE,
)
```

```python
        "caps": (
            VIEW_COST, VIEW_SALE, MANAGE_MATERIALS, VIEW_VENDOR, VIEW_MARGIN, EDIT_BOM, ADJUST_STOCK,
            INV_MASTERS, INV_PURCHASE, INV_JOB, INV_ASSORT, INV_MOVE,
        ),
```

`accounts/models.py`, `Capability.Meta.permissions` — append:

```python
            ("inv_move", "Can record stock movements"),
```

Create `accounts/migrations/0005_inv_move.py`:

```python
"""The Record stock movements right, granted by the add-only sync to the roles that list it.

The sync runs here, before Django's own post-migrate step creates the
permission row, so it sees the right as new and grants it to Admin and Accounts
without putting back any right an admin has taken away.
"""
from django.db import migrations


def sync_groups(apps, schema_editor):
    from accounts.models import sync_role_groups

    sync_role_groups()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_inventory_capabilities'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='capability',
            options={'default_permissions': (), 'managed': False, 'permissions': [('view_sale', 'Can see sale prices'), ('view_cost', 'Can see cost prices'), ('view_vendor', 'Can see vendors'), ('manage_materials', 'Can see the material breakup'), ('view_margin', 'Can see margins'), ('adjust_stock', 'Can adjust stock'), ('melt', 'Can melt a piece'), ('edit_bom', 'Can edit a bill of materials'), ('inv_masters', 'Can edit inventory records and import stock'), ('inv_purchase', 'Can post inventory purchases'), ('inv_job', 'Can post job-card movements'), ('inv_assort', 'Can post assortments'), ('inv_move', 'Can record stock movements')]},
        ),
        migrations.RunPython(sync_groups, migrations.RunPython.noop),
    ]
```

`inventory/dia_services.py` — `RIGHTS` gains the column, so the rights matrix shows it and `set_right` accepts it:

```python
#: the prototype's seven rights, as the permissions they are, plus part 2's Record stock movements
RIGHTS = [("view_cost", "See cost"), ("view_sale", "See sale"), ("view_margin", "See margin"),
          ("inv_purchase", "Post purchase"), ("inv_job", "Job cards"), ("inv_assort", "Assort"),
          ("inv_move", "Record stock movements"), ("inv_masters", "Edit settings")]
```

`stock/views.py`, `CAPABILITY_MATRIX` — append, so the stock Settings → Permissions tab lists every right:

```python
    ("inv_move", "Record stock movements", "Stones: sales, returns, memos, losses, samples, recounts"),
```

- [ ] **Step 4: The two new gated names**

`stock/masking.py` — import `INV_JOB` and add to the end of `GATED_FIELDS`:

```python
from accounts.capabilities import INV_JOB, MANAGE_MATERIALS, VIEW_COST, VIEW_MARGIN, VIEW_SALE, VIEW_VENDOR
```

```python
    # the stones ledger's counterparties: a karigar is seen by those who post job work
    # (the Karigar desk has no view_vendor), a customer by those who see sales
    "karigar_name": INV_JOB,
    "customer_name": VIEW_SALE,
```

- [ ] **Step 5: The models**

`inventory/models.py`. Change the `django.db.models` import:

```python
from django.db.models import Case, F, Q, Sum, Value, When
```

In `Pouch`, after `supplier`:

```python
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children",
        help_text="The pouch a split took this one from.",
    )
```

Add `StockDocument` between `Pouch` and `Movement`:

```python
class StockDocument(models.Model):
    """The header every stock-moving action posts its movements under.

    One shape for every kind, so a challan, a memo, a purchase bill, a split, a
    transfer and a one-off sale are listed, read and reversed the same way. Job
    work and memos stay open while goods are out; every other kind closes when
    it is posted. Nothing on it is edited afterwards: a reversal is a new
    document that points back at this one.
    """

    class Kind(models.TextChoices):
        PURCHASE = "purchase", "Purchase"
        JOB_WORK = "job_work", "Job work"
        MEMO = "memo", "Memo"
        SPLIT = "split", "Split"
        TRANSFER = "transfer", "Transfer"
        SINGLE = "single", "Single"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"
        REVERSED = "reversed", "Reversed"

    CURRENCIES = [("INR", "INR"), ("USD", "USD")]

    kind = models.CharField(max_length=10, choices=Kind.choices)
    number = models.CharField(max_length=40)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    vendor = models.ForeignKey(
        "stock.Vendor", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text="The supplier (purchase, purchase return) or the karigar (job work).",
    )
    # SET_NULL, as stock.Sale does: the CRM deletes customers, and a memo must not block it
    customer = models.ForeignKey("crm.Customer", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    occurred_on = models.DateField(default=timezone.localdate)
    expected_back = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True)
    currency = models.CharField(max_length=3, choices=CURRENCIES, blank=True)
    fx_rate = models.DecimalField("rate to INR", max_digits=12, decimal_places=4, null=True, blank=True)
    landed_extras = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    # a transfer's from and to, so reversing it can file the pouch back
    from_batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    from_pouch_no = models.CharField(max_length=16, blank=True)
    to_batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    to_pouch_no = models.CharField(max_length=16, blank=True)
    reverses = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversals")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "inv_document"
        ordering = ["-created_at", "-pk"]
        constraints = [
            # a reversed document's number may be used again
            models.UniqueConstraint(
                fields=["kind", "number"], condition=~Q(status="reversed"), name="inv_document_number"
            )
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.number}"
```

In `Movement`: replace the docstring and direction constants, change `direction`, add `document`, `reverses` and `effect`:

```python
class Movement(models.Model):
    """Append-only. Pieces and carats are separate because a pouch can move by either.

    A ``settle`` is recorded against a document — goods already out, consumed,
    lost or sold — and never counts in a balance. A movement that ``reverses``
    another repeats its pouch, direction and quantities, and counts with the
    opposite sign.
    """

    IN, OUT, SETTLE = "in", "out", "settle"
```

```python
    direction = models.CharField(max_length=6, choices=[(IN, "In"), (OUT, "Out"), (SETTLE, "Settle")])
```

After `recorded_at`:

```python
    document = models.ForeignKey(
        StockDocument, null=True, blank=True, on_delete=models.PROTECT, related_name="movements",
        help_text="Empty for opening balances and import recounts.",
    )
    reverses = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversal",
        help_text="The movement this one cancels.",
    )
```

After `__str__`:

```python
    @property
    def effect(self):
        """+1, −1 or 0: what this movement does to its pouch's balance — ``balance``'s rule, row by row."""
        if self.direction == self.SETTLE:
            return 0
        sign = 1 if self.direction == self.IN else -1
        return -sign if self.reverses_id else sign


def balance(field):
    """The sum of ``pcs`` or ``ct`` over ``movements`` that is a pouch's (or a diamond line's) balance.

    In adds and out subtracts; a settle never counts, because the goods it
    settles had already left; a reversal counts with the opposite sign of the
    movement it cancels. Stones and diamonds share this table, so every
    balance reads through here.
    """
    value = F(f"movements__{field}")
    return Sum(Case(
        When(movements__direction=Movement.SETTLE, then=Value(0)),
        When(movements__direction=Movement.OUT, movements__reverses__isnull=True, then=-value),
        When(movements__direction=Movement.IN, movements__reverses__isnull=False, then=-value),
        default=value,
        output_field=Movement._meta.get_field(field),
    ))
```

- [ ] **Step 6: Every balance reads through `balance`**

`inventory/services.py` — delete `_signed`, change the imports and `stocked`:

```python
from django.db.models import OuterRef, Subquery
```

```python
from .models import Movement, Pouch, PriceEntry, balance
```

```python
    return queryset.select_related("batch__box_colour", "supplier").annotate(
        on_pcs=balance("pcs"), on_ct=balance("ct"), rate=Subquery(latest)
    ).order_by("batch__code", "pk")
```

`inventory/dia_services.py` — delete the `from django.db.models import Case, DecimalField, F, Sum, When` line, import `balance`, and replace `stocked_lines`:

```python
from .models import DiamondCode, DiamondLine, DiamondRate, DiamondTerm, Movement, balance
```

```python
def stocked_lines(queryset=None):
    queryset = DiamondLine.objects.all() if queryset is None else queryset
    return queryset.select_related(
        "category", "band", "shape_override", "colour_override", "code__shape", "code__colour", "code__clarity"
    ).annotate(on_ct=balance("ct")).order_by("pk")
```

`inventory/views.py`, in `movements`, the running balance follows the same rule:

```python
        sign = move.effect
```

- [ ] **Step 7: Migrations**

Run:

```bash
POSTGRES_DB=ledger_t1 .venv/bin/python manage.py makemigrations inventory -n stones_ledger
POSTGRES_DB=ledger_t1 .venv/bin/python manage.py makemigrations --check --dry-run
```

Expected: `inventory/migrations/0007_stones_ledger.py` is created (it depends on the latest `crm` migration for `Customer`), then `No changes detected` — the hand-written `accounts/migrations/0005_inv_move.py` must match `Capability.Meta` exactly.

- [ ] **Step 8: Run the tests**

Run: `POSTGRES_DB=ledger_t1 .venv/bin/pytest inventory accounts stock/tests/test_masking.py stock/tests/test_views.py -p no:warnings`
Expected: PASS — the new file and every existing inventory, accounts and stock-masking test.

- [ ] **Step 9: Commit**

```bash
git add inventory/models.py inventory/migrations/0007_stones_ledger.py inventory/services.py inventory/dia_services.py \
  inventory/views.py inventory/tests/test_ledger_models.py accounts/capabilities.py accounts/models.py \
  accounts/migrations/0005_inv_move.py stock/masking.py stock/views.py
git commit -m "$(cat <<'EOF'
Stock documents, settle and reversing movements, one balance rule, and the Record stock movements right

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---
### Task 2: The ledger core, form inputs, and the reserved routes

**Files:**
- Create: `inventory/ledger.py`, `inventory/inputs.py`, `inventory/tests/test_ledger.py`, `inventory/tests/test_inputs.py`
- Create (stubs, each replaced whole by its wave-4 task): `inventory/views_ledger.py`, `inventory/views_purchase.py`, `inventory/views_assort.py`, `inventory/views_documents.py`, `inventory/views_lists.py`
- Modify: `inventory/urls.py`, `inventory/tests/conftest.py`, `inventory/tests/test_masking.py`

**Interfaces:**
- Consumes: Task 1's `StockDocument`, `Movement.SETTLE/effect/reverses/document`, `Pouch.parent`, `services.stocked`, `services._last_ref_number`.
- Produces:
  - `ledger.Line` dataclass `(pouch, reason, direction, pcs=None, ct=None, note="", ref="", reverses=None)`;
  - `ledger.ZERO`, `ledger.OPENABLE` (`(Kind.JOB_WORK, Kind.MEMO)`), `ledger.RIGHT_FOR_KIND` (`{kind: permission}`), `ledger.PREFIX`, `ledger.REVERSAL_PREFIX = "REV-"`;
  - `ledger.next_number(prefix) -> str`; `ledger.open_document(user, kind, number="", **fields) -> StockDocument` (fields: any `StockDocument` field);
  - `ledger.post(user, document, lines, occurred_on=None) -> [Movement]`;
  - `ledger.outstanding(document) -> {pouch_pk: (pcs, ct)}`; `ledger.owed_by_document(documents) -> {document_pk: [(pouch, pcs, ct)]}` (pouches from `services.stocked`, so each has `.rate`, `.on_ct`, `.on_pcs`);
  - `ledger.reverse_document(user, document, note="") -> StockDocument` (the reversal); `ledger.undo_last(user, document) -> Movement`;
  - `ledger.next_pouch_numbers(batches=None) -> {batch_code: int}`; `ledger.next_pouch_no(batch) -> str`; `ledger.pouch_no_free(batch, pouch_no) -> bool`; `ledger.new_pouch(batch, **fields) -> Pouch`;
  - `ledger.party(document) -> {}` | `{"karigar_name": …}` | `{"vendor_name": …}` | `{"customer_name": …}` (unmasked; callers mask);
  - `ledger.out_summary() -> {"ct": Decimal, "value": Decimal, "documents": int}`;
  - `inputs.decimal(raw, label) -> Decimal|None`; `inputs.whole(raw, label) -> int|None`; `inputs.day(raw, label="Date") -> date|None` — each raises `ServiceError` naming `label`;
  - URL names (stubbed until wave 4): `inventory:movement_post` (`ref`), `inventory:split` (`ref`), `inventory:transfer` (`ref`), `inventory:purchase`, `inventory:document` (`pk`), `inventory:document_settle` (`pk`), `inventory:document_undo` (`pk`), `inventory:document_reverse` (`pk`), `inventory:job_work_list`, `inventory:memo_list`, `inventory:recent`; `inventory:movements` now routes through `views_ledger.movements`;
  - view functions: `views_ledger.movements(request, ref)`, `views_ledger.movement_post(request, ref)`, `views_purchase.purchase(request)`, `views_assort.split(request, ref)`, `views_assort.transfer(request, ref)`, `views_documents.document/document_settle/document_undo/document_reverse(request, pk)`, `views_lists.job_work_list(request)`, `views_lists.memo_list(request)`, `views_lists.recent(request)`;
  - fixture `parties` → `{"karigar": Vendor (code "MAH"), "customer": Customer (code "C-881")}`; constants `KARIGAR = "Mahesh Karigar"`, `CUSTOMER = "Kalyan Retail"`.

- [ ] **Step 1: Add the parties fixture**

Append to `inventory/tests/conftest.py`:

```python
KARIGAR = "Mahesh Karigar"
CUSTOMER = "Kalyan Retail"


@pytest.fixture
def parties(db):
    """A karigar (a supplier-list entry, as part 1 keeps them) and a CRM customer."""
    from crm.models import Customer
    from stock.models import Vendor

    return {
        "karigar": Vendor.objects.create(code="MAH", name=KARIGAR, city="Johari Bazar"),
        "customer": Customer.objects.create(customer_code="C-881", name=CUSTOMER),
    }
```

- [ ] **Step 2: Write the failing tests**

`inventory/tests/test_inputs.py`:

```python
from datetime import date
from decimal import Decimal

import pytest

from inventory import inputs
from stock.services import ServiceError


def test_blank_is_none():
    assert inputs.decimal("  ", "Weight") is None
    assert inputs.whole("", "Pieces") is None
    assert inputs.day(None) is None


def test_numbers_read_with_or_without_grouping():
    assert inputs.decimal("1,800.50", "Cost / ct") == Decimal("1800.50")
    assert inputs.whole("12", "Pieces") == 12


@pytest.mark.parametrize("raw", ["abc", "NaN", "Infinity", "1e12"])
def test_anything_else_is_refused_by_its_label(raw):
    with pytest.raises(ServiceError, match="Weight"):
        inputs.decimal(raw, "Weight")


def test_pieces_are_whole():
    with pytest.raises(ServiceError, match="whole number"):
        inputs.whole("2.5", "Pieces")


def test_dates():
    assert inputs.day("2026-10-01") == date(2026, 10, 1)
    with pytest.raises(ServiceError, match="Expected back"):
        inputs.day("2026-02-30", "Expected back")
```

`inventory/tests/test_ledger.py`:

```python
"""The ledger core: numbers, the one post and its checks, outstanding, reversal, undo — and the invariant."""
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from inventory import ledger, services
from inventory.ledger import Line
from inventory.models import Batch, Movement, Pouch, StockDocument
from inventory.tests.conftest import CUSTOMER, KARIGAR
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
K, S, R = StockDocument.Kind, StockDocument.Status, Movement.Reason
IN, OUT, SETTLE = Movement.IN, Movement.OUT, Movement.SETTLE


def _held(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()


def _job(user, parties, number="2026/0431"):
    return ledger.open_document(user, K.JOB_WORK, number, vendor=parties["karigar"])


def _memo(user, parties, number="MEMO-0088"):
    return ledger.open_document(user, K.MEMO, number, customer=parties["customer"])


def _single(user, pouch, reason, direction, ct, pcs=None):
    doc = ledger.open_document(user, K.SINGLE)
    ledger.post(user, doc, [Line(pouch, reason, direction, pcs, D(ct))])
    return doc


def test_automatic_numbers_count_up_per_prefix(admin_user_):
    kinds = (K.SPLIT, K.SPLIT, K.TRANSFER, K.SINGLE, K.PURCHASE)
    assert [ledger.open_document(admin_user_, kind).number for kind in kinds] == [
        "SPL-000001", "SPL-000002", "TRF-000001", "MOV-000001", "PUR-000001"]


def test_a_typed_number_is_free_per_kind_until_reversed(admin_user_, parties):
    first = _job(admin_user_, parties)
    with pytest.raises(ServiceError, match="already exists"):
        _job(admin_user_, parties)
    _memo(admin_user_, parties, "2026/0431")            # another kind may share it
    first.status = S.REVERSED
    first.save()
    assert _job(admin_user_, parties).number == "2026/0431"


@pytest.mark.parametrize("kind, words", [
    (K.JOB_WORK, "delivery challan no. is required"), (K.MEMO, "memo no. is required")])
def test_goods_leaving_without_a_sale_need_a_number(admin_user_, kind, words):
    with pytest.raises(ServiceError, match=words):
        ledger.open_document(admin_user_, kind, "  ")


def test_a_post_writes_every_movement_or_none(admin_user_, shelf):
    onyx = shelf["onyx"]
    doc = ledger.open_document(admin_user_, K.SINGLE)
    with pytest.raises(ServiceError, match="below zero"):
        ledger.post(admin_user_, doc, [Line(onyx, R.SALE, OUT, 2, D("1")), Line(onyx, R.BREAKAGE, OUT, 1, D("20"))])
    assert not doc.movements.exists() and _held(onyx).on_ct == D("12.5")


def test_pieces_cannot_go_below_zero_either(admin_user_, shelf):
    with pytest.raises(ServiceError, match="below zero"):
        _single(admin_user_, shelf["onyx"], R.SALE, OUT, "1", pcs=21)


def test_an_uncountable_pouch_moves_by_weight_only(admin_user_, shelf):
    with pytest.raises(ServiceError, match="uncountable"):
        _single(admin_user_, shelf["ruby"], R.SALE, OUT, "1", pcs=1)
    _single(admin_user_, shelf["ruby"], R.SALE, OUT, "1")
    assert _held(shelf["ruby"]).on_ct == D("39")


@pytest.mark.parametrize("pcs, ct, words", [(None, "0", "above zero"), (None, "-1", "negative"), (-2, "1", "negative")])
def test_a_quantity_must_be_above_zero(admin_user_, shelf, pcs, ct, words):
    with pytest.raises(ServiceError, match=words):
        _single(admin_user_, shelf["onyx"], R.BREAKAGE, OUT, ct, pcs=pcs)


def test_a_single_closes_when_posted_and_takes_no_more(admin_user_, shelf):
    doc = _single(admin_user_, shelf["onyx"], R.SAMPLE, OUT, "1", pcs=1)
    assert doc.status == S.CLOSED
    with pytest.raises(ServiceError, match="takes no more entries"):
        ledger.post(admin_user_, doc, [Line(shelf["onyx"], R.SAMPLE, OUT, 1, D("1"))])


def test_job_work_stays_open_until_settled_then_closes_itself(admin_user_, shelf, parties):
    onyx = shelf["onyx"]
    doc = _job(admin_user_, parties)
    ledger.post(admin_user_, doc, [Line(onyx, R.JOB_WORK_OUT, OUT, 5, D("3"))])
    assert doc.status == S.OPEN and ledger.outstanding(doc) == {onyx.pk: (5, D("3"))}
    ledger.post(admin_user_, doc, [Line(onyx, R.JOB_WORK_IN, IN, 2, D("1"))])
    assert doc.status == S.OPEN
    ledger.post(admin_user_, doc, [Line(onyx, R.CONSUMED, SETTLE, 3, D("2"))])
    assert doc.status == S.CLOSED and ledger.outstanding(doc) == {onyx.pk: (0, D("0"))}
    held = _held(onyx)
    assert (held.on_pcs, held.on_ct) == (17, D("10.5"))       # the settle took nothing more off the shelf


def test_settling_cannot_exceed_what_is_outstanding(admin_user_, shelf, parties):
    doc = _job(admin_user_, parties)
    ledger.post(admin_user_, doc, [Line(shelf["onyx"], R.JOB_WORK_OUT, OUT, 2, D("3"))])
    with pytest.raises(ServiceError, match="cannot exceed what is outstanding"):
        ledger.post(admin_user_, doc, [Line(shelf["onyx"], R.JOB_WORK_IN, IN, 1, D("3.5"))])
    with pytest.raises(ServiceError, match="cannot exceed"):
        ledger.post(admin_user_, doc, [Line(shelf["ruby"], R.WASTAGE, SETTLE, None, D("1"))])    # never sent out


def test_reversing_puts_everything_back_on_a_new_document(admin_user_, shelf):
    onyx = shelf["onyx"]
    doc = _single(admin_user_, onyx, R.SALE, OUT, "2", pcs=4)
    reversal = ledger.reverse_document(admin_user_, doc)
    doc.refresh_from_db()
    assert doc.status == S.REVERSED and reversal.reverses == doc and reversal.status == S.CLOSED
    assert (reversal.number, reversal.kind) == ("REV-000001", K.SINGLE)
    assert (_held(onyx).on_pcs, _held(onyx).on_ct) == (20, D("12.5"))
    with pytest.raises(ServiceError, match="already reversed"):
        ledger.reverse_document(admin_user_, doc)
    with pytest.raises(ServiceError, match="itself a reversal"):
        ledger.reverse_document(admin_user_, reversal)


def test_a_reversal_that_would_go_below_zero_is_refused(admin_user_, shelf):
    onyx = shelf["onyx"]
    back = _single(admin_user_, onyx, R.SALES_RETURN, IN, "5")
    _single(admin_user_, onyx, R.SALE, OUT, "17")
    with pytest.raises(ServiceError, match="below zero"):
        ledger.reverse_document(admin_user_, back)
    back.refresh_from_db()
    assert back.status == S.CLOSED and not StockDocument.objects.filter(reverses=back).exists()


def test_reversing_needs_the_right_for_its_kind(admin_user_, karigar_user, shelf):
    doc = _single(admin_user_, shelf["onyx"], R.BREAKAGE, OUT, "1")
    with pytest.raises(PermissionDenied):
        ledger.reverse_document(karigar_user, doc)


def test_a_created_pouch_that_moved_since_blocks_the_reversal(admin_user_, shelf):
    doc = ledger.open_document(admin_user_, K.PURCHASE, "B-1")
    fresh = ledger.new_pouch(shelf["batch"], pouch_no="9", stone_name="Tanzanite")
    ledger.post(admin_user_, doc, [Line(fresh, R.PURCHASE, IN, 6, D("10"))])
    _single(admin_user_, fresh, R.SALE, OUT, "1", pcs=1)
    with pytest.raises(ServiceError, match="has moved since"):
        ledger.reverse_document(admin_user_, doc)


def test_a_reversed_purchase_leaves_its_pouch_at_zero(admin_user_, shelf):
    doc = ledger.open_document(admin_user_, K.PURCHASE, "B-2")
    fresh = ledger.new_pouch(shelf["batch"], pouch_no="9")
    ledger.post(admin_user_, doc, [Line(fresh, R.PURCHASE, IN, 6, D("10"))])
    ledger.reverse_document(admin_user_, doc)
    held = _held(fresh)
    assert Pouch.objects.filter(pk=fresh.pk).exists() and (held.on_pcs, held.on_ct) == (0, D("0"))


def test_undo_reverses_only_the_latest_entry(admin_user_, shelf, parties):
    onyx = shelf["onyx"]
    doc = _job(admin_user_, parties)
    ledger.post(admin_user_, doc, [Line(onyx, R.JOB_WORK_OUT, OUT, 4, D("3"))])
    ledger.post(admin_user_, doc, [Line(onyx, R.JOB_WORK_IN, IN, 1, D("1"))])
    undone = ledger.undo_last(admin_user_, doc)
    assert undone.reverses.reason == R.JOB_WORK_IN and undone.document == doc
    assert ledger.outstanding(doc)[onyx.pk] == (4, D("3")) and _held(onyx).on_ct == D("9.5")
    doc.refresh_from_db()
    assert doc.status == S.OPEN


def test_undo_is_only_for_an_open_job_work_or_memo(admin_user_, shelf):
    doc = _single(admin_user_, shelf["onyx"], R.BREAKAGE, OUT, "1")
    with pytest.raises(ServiceError, match="Only an open job work or memo"):
        ledger.undo_last(admin_user_, doc)


def test_reversing_a_transfer_files_the_pouch_back(admin_user_, shelf):
    onyx, home = shelf["onyx"], shelf["batch"]
    other = Batch.objects.create(code="SP14B", box_colour_id="B", family="S", cls="P", seq="14")
    doc = ledger.open_document(admin_user_, K.TRANSFER, from_batch=home, from_pouch_no="1",
                               to_batch=other, to_pouch_no="3")
    ledger.post(admin_user_, doc, [Line(onyx, R.TRANSFER, SETTLE, 20, D("12.5"))])
    onyx.batch, onyx.pouch_no = other, "3"
    onyx.save()
    assert _held(onyx).on_ct == D("12.5")
    ledger.reverse_document(admin_user_, doc)
    onyx.refresh_from_db()
    assert (onyx.batch_id, onyx.pouch_no) == (home.pk, "1") and _held(onyx).on_ct == D("12.5")


def test_pouch_numbers_and_references(shelf):
    batch = shelf["batch"]
    assert ledger.next_pouch_no(batch) == "3" and ledger.next_pouch_numbers()["SL01G"] == 3
    assert not ledger.pouch_no_free(batch, "2") and ledger.pouch_no_free(batch, "3")
    assert ledger.new_pouch(batch, pouch_no="3").ref == "NRN-000003"


def test_the_counterparty_comes_under_the_key_that_masks_it(admin_user_, shelf, parties):
    assert ledger.party(_job(admin_user_, parties)) == {"karigar_name": KARIGAR}
    assert ledger.party(_memo(admin_user_, parties)) == {"customer_name": CUSTOMER}
    bought = ledger.open_document(admin_user_, K.PURCHASE, vendor=shelf["supplier"])
    assert ledger.party(bought) == {"vendor_name": shelf["supplier"].name}
    assert ledger.party(None) == {}


def test_what_is_out_is_valued_at_each_pouchs_rate(admin_user_, shelf, parties):
    job = _job(admin_user_, parties)
    ledger.post(admin_user_, job, [Line(shelf["onyx"], R.JOB_WORK_OUT, OUT, 2, D("2"))])
    memo = _memo(admin_user_, parties)
    ledger.post(admin_user_, memo, [Line(shelf["ruby"], R.MEMO_OUT, OUT, None, D("4"))])
    assert ledger.out_summary() == {"ct": D("6"), "value": D("16038"), "documents": 2}     # 2 × 7,919 + 4 × 50


def test_on_shelf_plus_out_is_what_came_in_less_what_left_for_good(admin_user_, shelf, parties):
    """The ledger invariant, through every kind of post, an undo and a reversal."""
    onyx, ruby = shelf["onyx"], shelf["ruby"]

    def owned():
        return sum(p.on_ct or 0 for p in services.stocked()) + ledger.out_summary()["ct"]

    opening = D("52.5")
    assert owned() == opening
    job = _job(admin_user_, parties)
    ledger.post(admin_user_, job, [Line(onyx, R.JOB_WORK_OUT, OUT, 6, D("4"))])
    ledger.post(admin_user_, job, [Line(onyx, R.JOB_WORK_IN, IN, 1, D("1"))])
    ledger.post(admin_user_, job, [Line(onyx, R.CONSUMED, SETTLE, 2, D("1"))])            # left for good: 1
    memo = _memo(admin_user_, parties)
    ledger.post(admin_user_, memo, [Line(ruby, R.MEMO_OUT, OUT, None, D("10"))])
    ledger.post(admin_user_, memo, [Line(ruby, R.MEMO_IN, IN, None, D("3"))])
    ledger.post(admin_user_, memo, [Line(ruby, R.SALE, SETTLE, None, D("2"))])              # sold …
    ledger.undo_last(admin_user_, memo)                                                       # … then undone
    _single(admin_user_, onyx, R.SALE, OUT, "1", pcs=1)                                       # left for good: 1
    _single(admin_user_, onyx, R.SALES_RETURN, IN, "0.5")                                     # came back: 0.5
    bought = ledger.open_document(admin_user_, K.PURCHASE, "B-3")
    fresh = ledger.new_pouch(shelf["batch"], pouch_no="9")
    ledger.post(admin_user_, bought, [Line(fresh, R.PURCHASE, IN, 6, D("10"))])            # came in: 10
    broken = _single(admin_user_, ruby, R.BREAKAGE, OUT, "1")
    ledger.reverse_document(admin_user_, broken)                                              # nets to nothing
    assert owned() == opening + D("10") + D("0.5") - D("1") - D("1")
    assert ledger.out_summary()["ct"] == D("2") + D("7")


def test_the_ledger_screens_have_their_names():
    for name, args in [("inventory:purchase", []), ("inventory:job_work_list", []), ("inventory:memo_list", []),
                       ("inventory:recent", []), ("inventory:document", [1]), ("inventory:document_settle", [1]),
                       ("inventory:document_undo", [1]), ("inventory:document_reverse", [1]),
                       ("inventory:split", ["NRN-000001"]), ("inventory:transfer", ["NRN-000001"]),
                       ("inventory:movement_post", ["NRN-000001"]), ("inventory:movements", ["NRN-000001"])]:
        assert reverse(name, args=args)
```

- [ ] **Step 3: Run them to see them fail**

Run: `POSTGRES_DB=ledger_t2 .venv/bin/pytest inventory/tests/test_ledger.py inventory/tests/test_inputs.py -p no:warnings`
Expected: FAIL — `cannot import name 'inputs' from 'inventory'` / `cannot import name 'ledger'`.

- [ ] **Step 4: Write `inventory/inputs.py`**

```python
"""Reading the ledger forms' fields: blank is ``None``, anything else must read.

Every refusal names the field, so the message on the form says which box is wrong.
"""
from decimal import Decimal, InvalidOperation

from django.utils.dateparse import parse_date

from stock.services import ServiceError


def decimal(raw, label):
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        value = None
    # the columns hold ten digits before the point; NaN and Infinity parse but are not numbers
    if value is None or not value.is_finite() or abs(value) >= 10 ** 10:
        raise ServiceError(f"{label}: {raw} is not a number.")
    return value


def whole(raw, label):
    value = decimal(raw, label)
    if value is None:
        return None
    if value != value.to_integral_value():
        raise ServiceError(f"{label} must be a whole number.")
    return int(value)


def day(raw, label="Date"):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        value = parse_date(raw)
    except ValueError:
        value = None
    if value is None:
        raise ServiceError(f"{label}: {raw} does not read as a date.")
    return value
```

- [ ] **Step 5: Write `inventory/ledger.py`**

```python
"""The stones ledger: documents, and the one way their movements are written.

Every action that moves stock — job work, a memo, a purchase, a split, a
transfer, a one-off sale or loss — opens a ``StockDocument`` and hands its
movements to ``post``, which writes them in one transaction and runs the checks
every post shares: quantities above zero, an uncountable pouch by weight only,
nothing settled beyond what is out, no pouch below zero. Nothing is edited
afterwards; a mistake is undone by posting the opposite movements.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal

from django.db import transaction
from django.db.models import Case, F, Sum, When
from django.utils import timezone

from accounts.capabilities import INV_ASSORT, INV_JOB, INV_MOVE, INV_PURCHASE
from stock.services import ServiceError, log, require

from . import services
from .models import Batch, Movement, Pouch, StockDocument

ZERO = Decimal("0")
Kind, Status = StockDocument.Kind, StockDocument.Status

#: the kinds that stay open while goods are out with someone
OPENABLE = (Kind.JOB_WORK, Kind.MEMO)
#: the right that posts each kind — and so may undo or reverse it
RIGHT_FOR_KIND = {
    Kind.PURCHASE: INV_PURCHASE, Kind.JOB_WORK: INV_JOB, Kind.MEMO: INV_MOVE,
    Kind.SPLIT: INV_ASSORT, Kind.TRANSFER: INV_ASSORT, Kind.SINGLE: INV_MOVE,
}
#: automatic numbers; job work and memos carry the challan or memo no. people type
PREFIX = {Kind.PURCHASE: "PUR-", Kind.SPLIT: "SPL-", Kind.TRANSFER: "TRF-", Kind.SINGLE: "MOV-"}
REVERSAL_PREFIX = "REV-"
#: the reasons that bring a pouch into being, so a reversal can find what it created
CREATING = (Movement.Reason.PURCHASE, Movement.Reason.SPLIT)


@dataclass
class Line:
    """One movement to post. ``ref`` defaults to the document's number."""

    pouch: Pouch
    reason: str
    direction: str
    pcs: int | None = None
    ct: Decimal | None = None
    note: str = ""
    ref: str = ""
    reverses: Movement | None = None


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
    """``{pouch pk: (pcs, ct)}`` still out on a job work or memo document."""
    totals = document.movements.order_by().values("pouch").annotate(pcs=_owed("pcs"), ct=_owed("ct"))
    return {t["pouch"]: (t["pcs"] or 0, t["ct"] or ZERO) for t in totals}


def owed_by_document(documents):
    """``{document pk: [(pouch, pcs, ct)]}`` — what each of these job work or memo documents
    still has out, with the pouches read through ``services.stocked`` so each carries its
    current valuation ``rate``."""
    totals = [t for t in Movement.objects.filter(document__in=documents).order_by()
              .values("document", "pouch").annotate(pcs=_owed("pcs"), ct=_owed("ct"))
              if t["pcs"] or t["ct"]]
    pouches = {p.pk: p for p in services.stocked(Pouch.objects.filter(pk__in={t["pouch"] for t in totals}))}
    owed = defaultdict(list)
    for t in totals:
        owed[t["document"]].append((pouches[t["pouch"]], t["pcs"] or 0, t["ct"] or ZERO))
    return owed


def out_summary():
    """Carats out on open job work and memos, valued at each pouch's current rate.

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

    ``karigar_name`` is seen by those who post job work, ``vendor_name`` by those
    who see suppliers, ``customer_name`` by those who see sales. Callers mask.
    """
    if document is None:
        return {}
    if document.customer_id:
        return {"customer_name": document.customer.name}
    if document.vendor_id:
        return {("karigar_name" if document.kind == Kind.JOB_WORK else "vendor_name"): document.vendor.name}
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
    return Pouch.objects.create(ref=f"NRN-{services._last_ref_number() + 1:06d}", batch=batch, **fields)


def _check(document, pouch, line, owed):
    if line.reverses is not None:
        return                      # a reversal repeats a movement that passed these once
    if any(value is not None and value < 0 for value in (line.pcs, line.ct)):
        raise ServiceError("A quantity cannot be negative; the reason says which way it moves.")
    if not (line.pcs or line.ct):
        raise ServiceError("A movement needs pieces or a weight above zero.")
    if not pouch.countable and line.pcs is not None:
        raise ServiceError(f"{pouch} is uncountable: it moves by weight only.")
    if document.kind in OPENABLE and line.direction != Movement.OUT:
        pcs, ct = owed.get(pouch.pk, (0, ZERO))
        if (line.pcs or 0) > pcs or (line.ct or 0) > ct:
            pieces = f" and {pcs} pcs" if pouch.countable else ""
            raise ServiceError(f"Settling cannot exceed what is outstanding: {document.number} has "
                               f"{ct:.2f} ct{pieces} of {pouch} out.")
        owed[pouch.pk] = (pcs - (line.pcs or 0), ct - (line.ct or 0))


def _check_balances(pks):
    for pouch in services.stocked(Pouch.objects.filter(pk__in=pks)):
        if (pouch.on_ct or 0) < 0 or (pouch.countable and (pouch.on_pcs or 0) < 0):
            pieces = f" and {pouch.on_pcs or 0} pcs" if pouch.countable else ""
            raise ServiceError(f"Not enough in {pouch}: this would leave it below zero "
                               f"({pouch.on_ct or 0:.2f} ct{pieces}).")


def _settle_status(document):
    """Job work and memos close themselves when nothing is outstanding; every other kind —
    and every reversal — closes when posted."""
    if document.kind in OPENABLE and document.reverses_id is None:
        settled = all(pcs == 0 and ct == 0 for pcs, ct in outstanding(document).values())
        status = Status.CLOSED if settled else Status.OPEN
    else:
        status = Status.CLOSED
    if document.status != status:
        document.status = status
        document.save(update_fields=["status"])


@transaction.atomic
def post(user, document, lines, occurred_on=None):
    """Write a document's movements — all of them, or none — and settle its status.

    Internal: every caller has already checked the right for its action.
    ``occurred_on`` is the day it happened (``None`` is now).
    """
    if document.status != Status.OPEN:
        raise ServiceError(f"{document} is {document.get_status_display().lower()}; it takes no more entries.")
    locked = Pouch.objects.select_for_update().filter(pk__in={line.pouch.pk for line in lines})
    pouches = {pouch.pk: pouch for pouch in locked}
    owed = outstanding(document) if document.kind in OPENABLE else {}
    for line in lines:
        _check(document, pouches[line.pouch.pk], line, owed)
    at, by = _when(occurred_on), _by(user)
    challan = document.number if document.kind in OPENABLE else ""
    moves = Movement.objects.bulk_create([
        Movement(pouch=line.pouch, document=document, reason=line.reason, direction=line.direction,
                 pcs=line.pcs, ct=line.ct, note=line.note, ref=line.ref or document.number,
                 reverses=line.reverses, counterparty=document.vendor, challan_no=challan,
                 occurred_at=at, recorded_by=by)
        for line in lines
    ])
    _check_balances(list(pouches))
    _settle_status(document)
    log(user, "INSERT", "inv_movement", document.pk, f"{document}: {len(moves)} movement(s)")
    return moves


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
    that points back at it, and mark it Reversed. A pouch it created stays, at zero."""
    require(user, RIGHT_FOR_KIND[document.kind], "Only a role that posts this kind of document may reverse it.")
    document = StockDocument.objects.select_for_update().get(pk=document.pk)
    if document.status == Status.REVERSED:
        raise ServiceError(f"{document} is already reversed.")
    if document.reverses_id:
        raise ServiceError(f"{document} is itself a reversal; it cannot be reversed.")
    moves = list(document.movements.filter(reverses__isnull=True, reversal__isnull=True).select_related("pouch"))
    created = [m.pouch_id for m in moves if m.direction == Movement.IN and m.reason in CREATING]
    moved = (Movement.objects.filter(pouch__in=created).exclude(document=document)
             .select_related("pouch__batch").first())
    if moved:
        raise ServiceError(f"{moved.pouch} has moved since; reverse its later movements first.")
    if document.kind == Kind.TRANSFER:
        _unfile(document)
    reversal = StockDocument.objects.create(
        kind=document.kind, number=next_number(REVERSAL_PREFIX), vendor=document.vendor,
        customer=document.customer, reverses=document, note=note, created_by=_by(user),
    )
    post(user, reversal, [Line(m.pouch, m.reason, m.direction, m.pcs, m.ct, note=f"Reverses {document.number}",
                               reverses=m) for m in moves])
    document.status = Status.REVERSED
    document.save(update_fields=["status"])
    log(user, "REVERSAL", "inv_document", document.pk, f"{document} reversed by {reversal.number}")
    return reversal


@transaction.atomic
def undo_last(user, document):
    """Reverse the latest entry on an open job work or memo — one wrong line, not the whole challan."""
    require(user, RIGHT_FOR_KIND[document.kind], "Only a role that posts this kind of document may undo its entries.")
    document = StockDocument.objects.select_for_update().get(pk=document.pk)
    if document.kind not in OPENABLE or document.status != Status.OPEN:
        raise ServiceError("Only an open job work or memo has a last entry to undo.")
    last = (document.movements.filter(reverses__isnull=True, reversal__isnull=True)
            .select_related("pouch").order_by("-pk").first())
    if last is None:
        raise ServiceError(f"{document} has nothing left to undo.")
    return post(user, document, [Line(last.pouch, last.reason, last.direction, last.pcs, last.ct,
                                      note=f"Undoes {last.reason}", reverses=last)])[0]
```

- [ ] **Step 6: Reserve the ledger's routes**

Each stub module below is replaced whole by its wave-4 task. Routing them now lets those screens link to one another while they are built in parallel.

`inventory/views_ledger.py`:

```python
"""A pouch's Movements page and its Record movement form.

Until the Record movement task builds this module the page is part 1's, and the
post route answers 404 — routed now so the other ledger screens can link to it.
"""
from django.http import Http404

from .views import movements  # noqa: F401  (the route's view until this module is built)


def movement_post(request, ref):
    raise Http404("Not built yet.")
```

`inventory/views_purchase.py`:

```python
"""Record a purchase — routed now so the other ledger screens can link to it; built by its own task."""
from django.http import Http404


def purchase(request):
    raise Http404("Not built yet.")
```

`inventory/views_assort.py`:

```python
"""Split pouch and Transfer to another batch — routed now so the other ledger screens can link to them."""
from django.http import Http404


def split(request, ref):
    raise Http404("Not built yet.")


def transfer(request, ref):
    raise Http404("Not built yet.")
```

`inventory/views_documents.py`:

```python
"""The document page and its actions — routed now so the other ledger screens can link to it."""
from django.http import Http404


def document(request, pk):
    raise Http404("Not built yet.")


def document_settle(request, pk):
    raise Http404("Not built yet.")


def document_undo(request, pk):
    raise Http404("Not built yet.")


def document_reverse(request, pk):
    raise Http404("Not built yet.")
```

`inventory/views_lists.py`:

```python
"""Job work out, Memo out and the rail's Movements — routed now so the other ledger screens can link to them."""
from django.http import Http404


def job_work_list(request):
    raise Http404("Not built yet.")


def memo_list(request):
    raise Http404("Not built yet.")


def recent(request):
    raise Http404("Not built yet.")
```

`inventory/urls.py` — the import line and the pouch routes become:

```python
from . import (
    views, views_assort, views_dia_import, views_dia_settings, views_diamonds, views_documents, views_ledger,
    views_lists, views_purchase,
)
```

```python
    path("pouches/<str:ref>/movements/", views_ledger.movements, name="movements"),
    path("pouches/<str:ref>/movements/post/", views_ledger.movement_post, name="movement_post"),
    path("pouches/<str:ref>/split/", views_assort.split, name="split"),
    path("pouches/<str:ref>/transfer/", views_assort.transfer, name="transfer"),
    path("purchases/new/", views_purchase.purchase, name="purchase"),
    path("documents/<int:pk>/", views_documents.document, name="document"),
    path("documents/<int:pk>/settle/", views_documents.document_settle, name="document_settle"),
    path("documents/<int:pk>/undo/", views_documents.document_undo, name="document_undo"),
    path("documents/<int:pk>/reverse/", views_documents.document_reverse, name="document_reverse"),
    path("job-work/", views_lists.job_work_list, name="job_work_list"),
    path("memos/", views_lists.memo_list, name="memo_list"),
    path("movements/", views_lists.recent, name="recent"),
```

(The first line replaces the existing `views.movements` route; the others are new, placed after it.)

`inventory/tests/test_masking.py` — after `EXEMPT`, and in `test_every_inventory_screen_is_walked`:

```python
#: the ledger's screens, routed before they are built so they can link to one another;
#: the masking-walk task walks each of them and deletes this set
PENDING = {
    "inventory:movement_post", "inventory:split", "inventory:transfer", "inventory:purchase",
    "inventory:document", "inventory:document_settle", "inventory:document_undo", "inventory:document_reverse",
    "inventory:job_work_list", "inventory:memo_list", "inventory:recent",
}
```

```python
    missing = named - covered - EXEMPT - PENDING
```

- [ ] **Step 7: Run the tests**

Run: `POSTGRES_DB=ledger_t2 .venv/bin/pytest inventory -p no:warnings`
Expected: PASS — the new files, and every existing inventory test (the movements page still works through `views_ledger`).

- [ ] **Step 8: Commit**

```bash
git add inventory/ledger.py inventory/inputs.py inventory/views_ledger.py inventory/views_purchase.py \
  inventory/views_assort.py inventory/views_documents.py inventory/views_lists.py inventory/urls.py \
  inventory/tests/conftest.py inventory/tests/test_masking.py inventory/tests/test_ledger.py inventory/tests/test_inputs.py
git commit -m "$(cat <<'EOF'
The stones ledger core: one post with every check, outstanding, reversal and undo, and the ledger's routes

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---
### Task 3: Job work and memos

**Files:**
- Create: `inventory/ledger_jobs.py`, `inventory/tests/test_ledger_jobs.py`

**Interfaces:**
- Consumes: `ledger.open_document/post/Line/outstanding`; `StockDocument`; `stock.masking.allowed/mask`; `crm.models.Customer`; `stock.models.Vendor`.
- Produces:
  - `ledger_jobs.job_work_out(user, pouch, karigar, challan_no, pcs, ct, occurred_on=None, expected_back=None, note="") -> StockDocument` (inv_job; opens the challan or adds to the open one of that number);
  - `ledger_jobs.settle_job_work(user, document, pouch, how, pcs, ct, occurred_on=None, note="") -> Movement` (inv_job; `how` in `"in" | "consumed" | "loss"`);
  - `ledger_jobs.memo_out(user, pouch, customer, memo_no, pcs, ct, occurred_on=None, expected_back=None, note="") -> StockDocument` (inv_move);
  - `ledger_jobs.settle_memo(user, document, pouch, how, pcs, ct, occurred_on=None, note="") -> Movement` (inv_move; `how` in `"in" | "sold"`);
  - `ledger_jobs.JOB_SETTLE`, `ledger_jobs.MEMO_SETTLE` (`{how: (reason, direction)}`);
  - `ledger_jobs.karigar_choices(user) -> [{"pk", "karigar_name"?}]`; `ledger_jobs.customer_choices(user) -> [{"code", "customer_name"?}]` (masked).

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_ledger_jobs.py`:

```python
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import ledger, ledger_jobs, services
from inventory.models import Movement, Pouch, StockDocument
from inventory.tests.conftest import CUSTOMER, KARIGAR, SUPPLIER
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
S = StockDocument.Status


def _ct(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get().on_ct


def _out(user, shelf, parties, **changes):
    args = {"pouch": shelf["onyx"], "karigar": parties["karigar"], "challan_no": "2026/0431", "pcs": 6, "ct": D("4")}
    return ledger_jobs.job_work_out(user, **(args | changes))


def test_out_partly_back_consumed_and_lost_closes_at_zero(admin_user_, shelf, parties):
    onyx = shelf["onyx"]
    doc = _out(admin_user_, shelf, parties, occurred_on=date(2026, 10, 1), expected_back=date(2026, 10, 8))
    assert (doc.kind, doc.number, doc.status) == (StockDocument.Kind.JOB_WORK, "2026/0431", S.OPEN)
    assert doc.vendor == parties["karigar"] and doc.expected_back == date(2026, 10, 8)
    assert _ct(onyx) == D("8.5")
    ledger_jobs.settle_job_work(admin_user_, doc, onyx, "in", 2, D("1"))
    ledger_jobs.settle_job_work(admin_user_, doc, onyx, "consumed", 3, D("2.5"))
    doc.refresh_from_db()
    assert doc.status == S.OPEN                     # 1 pc and 0.5 ct still out: it cannot close early
    lost = ledger_jobs.settle_job_work(admin_user_, doc, onyx, "loss", 1, D("0.5"))
    doc.refresh_from_db()
    assert (lost.reason, lost.direction) == (Movement.Reason.WASTAGE, Movement.SETTLE)
    assert doc.status == S.CLOSED and _ct(onyx) == D("9.5")


def test_a_challan_can_take_more_pouches(admin_user_, shelf, parties):
    doc = _out(admin_user_, shelf, parties)
    again = _out(admin_user_, shelf, parties, pouch=shelf["ruby"], pcs=None, ct=D("5"))
    assert again == doc and set(ledger.outstanding(doc)) == {shelf["onyx"].pk, shelf["ruby"].pk}


def test_an_open_challan_belongs_to_one_karigar(admin_user_, shelf, parties):
    _out(admin_user_, shelf, parties)
    with pytest.raises(ServiceError, match="open with someone else"):
        _out(admin_user_, shelf, parties, karigar=shelf["supplier"])


def test_goods_out_need_a_challan_and_a_karigar(admin_user_, shelf, parties):
    with pytest.raises(ServiceError, match="challan no. is required"):
        _out(admin_user_, shelf, parties, challan_no=" ")
    with pytest.raises(ServiceError, match="Choose the karigar"):
        _out(admin_user_, shelf, parties, karigar=None)


def test_expected_back_cannot_come_before_the_date(admin_user_, shelf, parties):
    with pytest.raises(ServiceError, match="Expected back cannot be before"):
        _out(admin_user_, shelf, parties, occurred_on=date(2026, 10, 8), expected_back=date(2026, 10, 1))


def test_settling_is_capped_at_what_is_out(admin_user_, shelf, parties):
    doc = _out(admin_user_, shelf, parties)
    with pytest.raises(ServiceError, match="cannot exceed"):
        ledger_jobs.settle_job_work(admin_user_, doc, shelf["onyx"], "in", 7, D("1"))


def test_a_closed_challan_takes_nothing_more_and_keeps_its_number(admin_user_, shelf, parties):
    doc = _out(admin_user_, shelf, parties)
    ledger_jobs.settle_job_work(admin_user_, doc, shelf["onyx"], "in", 6, D("4"))
    doc.refresh_from_db()
    assert doc.status == S.CLOSED
    with pytest.raises(ServiceError, match="takes no more entries"):
        ledger_jobs.settle_job_work(admin_user_, doc, shelf["onyx"], "loss", None, D("0.1"))
    with pytest.raises(ServiceError, match="already exists"):
        _out(admin_user_, shelf, parties)


def test_memo_out_returned_then_sold(admin_user_, shelf, parties):
    ruby = shelf["ruby"]
    doc = ledger_jobs.memo_out(admin_user_, ruby, parties["customer"], "MEMO-0088", None, D("10"),
                               expected_back=date(2026, 12, 1))
    assert doc.customer == parties["customer"] and doc.kind == StockDocument.Kind.MEMO and _ct(ruby) == D("30")
    ledger_jobs.settle_memo(admin_user_, doc, ruby, "in", None, D("6"))
    sold = ledger_jobs.settle_memo(admin_user_, doc, ruby, "sold", None, D("4"))
    doc.refresh_from_db()
    assert (sold.reason, sold.direction) == (Movement.Reason.SALE, Movement.SETTLE)
    assert doc.status == S.CLOSED and _ct(ruby) == D("36")


def test_a_memo_needs_a_customer_and_a_number(admin_user_, shelf, parties):
    with pytest.raises(ServiceError, match="Choose the customer"):
        ledger_jobs.memo_out(admin_user_, shelf["ruby"], None, "MEMO-0088", None, D("1"))
    with pytest.raises(ServiceError, match="memo no. is required"):
        ledger_jobs.memo_out(admin_user_, shelf["ruby"], parties["customer"], "", None, D("1"))


def test_settling_the_wrong_way_or_the_wrong_kind_is_refused(admin_user_, shelf, parties):
    doc = _out(admin_user_, shelf, parties)
    with pytest.raises(ServiceError, match="Unknown way"):
        ledger_jobs.settle_job_work(admin_user_, doc, shelf["onyx"], "sold", 1, D("1"))
    with pytest.raises(ServiceError, match="not a memo"):
        ledger_jobs.settle_memo(admin_user_, doc, shelf["onyx"], "in", 1, D("1"))


def test_who_may_post_what(karigar_user, production_user, sales_user, shelf, parties):
    doc = _out(karigar_user, shelf, parties)                        # the Karigar desk posts job work
    ledger_jobs.settle_job_work(production_user, doc, shelf["onyx"], "in", 1, D("1"))
    with pytest.raises(PermissionDenied):
        ledger_jobs.memo_out(karigar_user, shelf["ruby"], parties["customer"], "MEMO-1", None, D("1"))
    with pytest.raises(PermissionDenied):
        _out(sales_user, shelf, parties, challan_no="2026/0500")


def test_karigar_choices_follow_what_the_login_may_see(admin_user_, karigar_user, production_user, shelf, parties):
    def names(user):
        return [choice.get("karigar_name") for choice in ledger_jobs.karigar_choices(user)]

    assert SUPPLIER in names(production_user) and KARIGAR in names(production_user)
    assert names(karigar_user) == []            # no challan yet, and suppliers are not theirs to see
    _out(admin_user_, shelf, parties)
    assert names(karigar_user) == [KARIGAR]


def test_customer_choices_are_named_only_for_those_who_see_sales(accounts_user, production_user, parties):
    assert ledger_jobs.customer_choices(accounts_user) == [{"code": "C-881", "customer_name": CUSTOMER}]
    assert ledger_jobs.customer_choices(production_user) == [{"code": "C-881"}]
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=ledger_t3 .venv/bin/pytest inventory/tests/test_ledger_jobs.py -p no:warnings`
Expected: FAIL — `cannot import name 'ledger_jobs'`.

- [ ] **Step 3: Write `inventory/ledger_jobs.py`**

```python
"""Job work and memos: goods out to a karigar or a client on a numbered document,
settled pouch by pouch until nothing is outstanding.

Out takes the goods off the pouch — they are not in the box — and the document
holds what is owed. Coming back is an in; consumed, lost or sold is a settle,
which clears what is owed without touching the pouch again.
"""
from django.db import transaction
from django.utils import timezone

from accounts.capabilities import INV_JOB, INV_MOVE
from crm.models import Customer
from stock.masking import allowed, mask
from stock.models import Vendor
from stock.services import ServiceError, require

from . import ledger
from .models import Movement, StockDocument

Kind, Status, Reason = StockDocument.Kind, StockDocument.Status, Movement.Reason

#: how goods on a challan or a memo are settled: (reason, direction)
JOB_SETTLE = {"in": (Reason.JOB_WORK_IN, Movement.IN), "consumed": (Reason.CONSUMED, Movement.SETTLE),
              "loss": (Reason.WASTAGE, Movement.SETTLE)}
MEMO_SETTLE = {"in": (Reason.MEMO_IN, Movement.IN), "sold": (Reason.SALE, Movement.SETTLE)}


def _goods_out(user, kind, reason, number, pouch, pcs, ct, occurred_on, expected_back, note, party):
    occurred_on = occurred_on or timezone.localdate()
    if expected_back and expected_back < occurred_on:
        raise ServiceError("Expected back cannot be before the date.")
    number = (number or "").strip()
    document = (StockDocument.objects.select_for_update()
                .filter(kind=kind, number=number, status=Status.OPEN).first()) if number else None
    if document is None:
        document = ledger.open_document(user, kind, number, occurred_on=occurred_on,
                                        expected_back=expected_back, note=note, **party)
    elif any(getattr(document, f"{field}_id") != value.pk for field, value in party.items()):
        raise ServiceError(f"{document} is open with someone else; give these goods a new number.")
    ledger.post(user, document, [ledger.Line(pouch, reason, Movement.OUT, pcs, ct, note=note)], occurred_on)
    return document


@transaction.atomic
def job_work_out(user, pouch, karigar, challan_no, pcs, ct, occurred_on=None, expected_back=None, note=""):
    """Goods out to a karigar on a delivery challan; the same open challan may take more pouches."""
    require(user, INV_JOB, "Only a role that posts job cards can send goods out on job work.")
    if karigar is None:
        raise ServiceError("Choose the karigar.")
    return _goods_out(user, Kind.JOB_WORK, Reason.JOB_WORK_OUT, challan_no, pouch, pcs, ct,
                      occurred_on, expected_back, note, {"vendor": karigar})


@transaction.atomic
def memo_out(user, pouch, customer, memo_no, pcs, ct, occurred_on=None, expected_back=None, note=""):
    """Goods out to a client on approval; the same open memo may take more pouches."""
    require(user, INV_MOVE, "Only a role that records stock movements can send goods out on memo.")
    if customer is None:
        raise ServiceError("Choose the customer.")
    return _goods_out(user, Kind.MEMO, Reason.MEMO_OUT, memo_no, pouch, pcs, ct,
                      occurred_on, expected_back, note, {"customer": customer})


def _settle(user, document, kind, table, pouch, how, pcs, ct, occurred_on, note):
    if document.kind != kind:
        raise ServiceError(f"{document} is not a {Kind(kind).label.lower()}.")
    if how not in table:
        raise ServiceError(f"Unknown way to settle a {Kind(kind).label.lower()}: {how}.")
    reason, direction = table[how]
    line = ledger.Line(pouch, reason, direction, pcs, ct, note=note)
    return ledger.post(user, document, [line], occurred_on)[0]


def settle_job_work(user, document, pouch, how, pcs, ct, occurred_on=None, note=""):
    """``how``: ``in`` (back into the pouch), ``consumed`` or ``loss`` (settled, never returned)."""
    require(user, INV_JOB, "Only a role that posts job cards can settle a challan.")
    return _settle(user, document, Kind.JOB_WORK, JOB_SETTLE, pouch, how, pcs, ct, occurred_on, note)


def settle_memo(user, document, pouch, how, pcs, ct, occurred_on=None, note=""):
    """``how``: ``in`` (returned to the pouch) or ``sold`` (settled against the memo)."""
    require(user, INV_MOVE, "Only a role that records stock movements can settle a memo.")
    return _settle(user, document, Kind.MEMO, MEMO_SETTLE, pouch, how, pcs, ct, occurred_on, note)


def karigar_choices(user):
    """Who goods may go to on job work, as this login may see them.

    Karigars and suppliers share one list. A login without sight of suppliers
    (the Karigar desk) is offered only those already named on a challan, so the
    list never shows it a supplier.
    """
    vendors = Vendor.objects.filter(is_active=True)
    if not allowed(user, "vendor_name"):
        vendors = vendors.filter(pk__in=StockDocument.objects.filter(kind=Kind.JOB_WORK).values("vendor"))
    return [mask(user, {"pk": v.pk, "karigar_name": v.name}) for v in vendors.order_by("name")]


def customer_choices(user):
    """CRM customers by code, named only for a login that may see sales.

    ponytail: the whole CRM in one datalist; a search endpoint if it passes ~10,000.
    """
    return [mask(user, {"code": c.customer_code, "customer_name": c.name})
            for c in Customer.objects.order_by("name").only("customer_code", "name")]
```

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=ledger_t3 .venv/bin/pytest inventory/tests/test_ledger_jobs.py inventory/tests/test_ledger.py -p no:warnings`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add inventory/ledger_jobs.py inventory/tests/test_ledger_jobs.py
git commit -m "$(cat <<'EOF'
Job work and memos: goods out on a numbered document, settled until nothing is outstanding

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Single movements and recount

**Files:**
- Create: `inventory/ledger_single.py`, `inventory/tests/test_ledger_single.py`
- Modify: `inventory/services.py` (`recount_deltas`, shared by `recount`)

**Interfaces:**
- Consumes: `ledger.open_document/post/Line`; `services.stocked`, `services._check_quantities`.
- Produces:
  - `ledger_single.SINGLE` (`{reason: direction}` for Sale, Sales Return, Purchase Return, Breakage, Wastage / Loss in Process, Sample, Consumed in Production), `NEEDS_CUSTOMER`, `NEEDS_SUPPLIER`;
  - `ledger_single.post_single(user, pouch, reason, pcs, ct, occurred_on=None, customer=None, supplier=None, ref="", note="") -> StockDocument` (inv_move);
  - `ledger_single.post_recount(user, pouch, pcs, ct, occurred_on=None, note="") -> StockDocument | None` (inv_move; `None` when the count matches);
  - `services.recount_deltas(pouch, pcs, ct) -> [(field, direction, quantity)]`.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_ledger_single.py`:

```python
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import ledger_single, services
from inventory.models import Movement, Pouch, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
R, IN, OUT = Movement.Reason, Movement.IN, Movement.OUT


def _held(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()


@pytest.mark.parametrize("reason, direction, ct_after", [
    (R.SALE, OUT, "11.5"), (R.SALES_RETURN, IN, "13.5"), (R.PURCHASE_RETURN, OUT, "11.5"),
    (R.BREAKAGE, OUT, "11.5"), (R.WASTAGE, OUT, "11.5"), (R.SAMPLE, OUT, "11.5"), (R.CONSUMED, OUT, "11.5"),
])
def test_every_single_reason_posts_a_closed_document(accounts_user, shelf, parties, reason, direction, ct_after):
    doc = ledger_single.post_single(accounts_user, shelf["onyx"], reason, 1, D("1"), customer=parties["customer"],
                                    supplier=shelf["supplier"], ref="INV 2026/1188")
    move = doc.movements.get()
    assert (doc.kind, doc.status, doc.number) == (StockDocument.Kind.SINGLE, StockDocument.Status.CLOSED, "MOV-000001")
    assert (move.reason, move.direction, move.ref) == (reason, direction, "INV 2026/1188")
    assert _held(shelf["onyx"]).on_ct == D(ct_after)


def test_only_a_sale_or_return_names_a_customer_and_only_a_purchase_return_a_supplier(accounts_user, shelf, parties):
    both = {"customer": parties["customer"], "supplier": shelf["supplier"]}
    sale = ledger_single.post_single(accounts_user, shelf["onyx"], R.SALE, 1, D("1"), **both)
    assert sale.customer == parties["customer"] and sale.vendor is None
    back = ledger_single.post_single(accounts_user, shelf["onyx"], R.PURCHASE_RETURN, 1, D("1"), **both)
    assert back.vendor == shelf["supplier"] and back.customer is None
    broken = ledger_single.post_single(accounts_user, shelf["onyx"], R.BREAKAGE, 1, D("1"), **both)
    assert broken.vendor is None and broken.customer is None


def test_a_sale_needs_a_customer_and_a_purchase_return_a_supplier(accounts_user, shelf):
    with pytest.raises(ServiceError, match="Choose the customer"):
        ledger_single.post_single(accounts_user, shelf["onyx"], R.SALES_RETURN, None, D("1"))
    with pytest.raises(ServiceError, match="Choose the supplier"):
        ledger_single.post_single(accounts_user, shelf["onyx"], R.PURCHASE_RETURN, None, D("1"))


def test_job_work_is_not_posted_from_the_shelf(accounts_user, shelf):
    with pytest.raises(ServiceError, match="not posted from the shelf"):
        ledger_single.post_single(accounts_user, shelf["onyx"], R.JOB_WORK_OUT, 1, D("1"))


def test_a_recount_posts_the_differences_on_one_document(accounts_user, shelf):
    onyx = shelf["onyx"]
    doc = ledger_single.post_recount(accounts_user, onyx, 22, D("12"))
    pieces, weight = doc.movements.get(ct=None), doc.movements.get(pcs=None)
    assert (pieces.direction, pieces.pcs, weight.direction, weight.ct) == (IN, 2, OUT, D("0.5"))
    assert {pieces.reason, weight.reason} == {R.RECOUNT_ADJUSTMENT}
    assert (_held(onyx).on_pcs, _held(onyx).on_ct) == (22, D("12"))
    assert ledger_single.post_recount(accounts_user, onyx, 22, D("12")) is None


def test_an_uncountable_pouch_is_recounted_by_weight_only(accounts_user, shelf):
    with pytest.raises(ServiceError, match="uncountable"):
        ledger_single.post_recount(accounts_user, shelf["ruby"], 5, None)
    ledger_single.post_recount(accounts_user, shelf["ruby"], None, D("38"))
    assert _held(shelf["ruby"]).on_ct == D("38")


def test_a_count_must_be_given_and_not_negative(accounts_user, shelf):
    with pytest.raises(ServiceError, match="counted pieces or weight"):
        ledger_single.post_recount(accounts_user, shelf["onyx"], None, None)
    with pytest.raises(ServiceError, match="negative"):
        ledger_single.post_recount(accounts_user, shelf["onyx"], None, D("-1"))


def test_singles_need_the_movements_right(production_user, karigar_user, shelf, parties):
    for user in (production_user, karigar_user):
        with pytest.raises(PermissionDenied):
            ledger_single.post_single(user, shelf["onyx"], R.BREAKAGE, 1, D("1"))
        with pytest.raises(PermissionDenied):
            ledger_single.post_recount(user, shelf["onyx"], 19, None)


def test_the_importers_recount_is_unchanged(admin_user_, shelf):
    moves = services.recount(admin_user_, shelf["onyx"], 18, None)
    assert len(moves) == 1 and moves[0].document is None and moves[0].direction == OUT
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=ledger_t4 .venv/bin/pytest inventory/tests/test_ledger_single.py -p no:warnings`
Expected: FAIL — `cannot import name 'ledger_single'`.

- [ ] **Step 3: One recount rule, two callers**

`inventory/services.py` — replace `recount` with:

```python
def recount_deltas(pouch, pcs, ct):
    """``(field, direction, quantity)`` for each counted figure that differs from the ledger.

    A figure of ``None`` means "not counted", never "zero". Pieces and carats
    can move in opposite directions (a recount finds more pieces but less
    weight), so each is its own adjustment.
    """
    _check_quantities(pcs, ct)
    held = stocked(Pouch.objects.filter(pk=pouch.pk)).get()
    deltas = []
    for field, counted, current in (("pcs", pcs, held.on_pcs), ("ct", ct, held.on_ct)):
        if counted is None or counted == (current or 0):
            continue
        delta = counted - (current or 0)
        deltas.append((field, Movement.IN if delta > 0 else Movement.OUT, abs(delta)))
    return deltas


@transaction.atomic
def recount(user, pouch, pcs, ct, note=""):
    """The importer's recount: bring the ledger to a counted figure, under the masters right.

    The Record movement form's Recount Adjustment posts the same differences on
    a document, through ``ledger_single.post_recount``.
    """
    require(user, INV_MASTERS, "Only a role that edits inventory records can recount.")
    moves = [
        Movement.objects.create(
            pouch=pouch, reason=Movement.Reason.RECOUNT_ADJUSTMENT, direction=direction, note=note,
            recorded_by=_by(user), **{"pcs": None, "ct": None, field: quantity},
        )
        for field, direction, quantity in recount_deltas(pouch, pcs, ct)
    ]
    if moves:
        log(user, "INSERT", "inv_movement", pouch.pk, f"recount of {pouch}: {len(moves)} adjustment(s)")
    return moves
```

- [ ] **Step 4: Write `inventory/ledger_single.py`**

```python
"""Single movements: a sale, a return, a loss, a sample or a recount — one pouch, one
``MOV-`` document, closed when posted."""
from django.db import transaction
from django.utils import timezone

from accounts.capabilities import INV_MOVE
from stock.services import ServiceError, require

from . import ledger, services
from .models import Movement, StockDocument

Reason = Movement.Reason

#: what may be posted from the shelf, and which way each moves
SINGLE = {
    Reason.SALE: Movement.OUT, Reason.SALES_RETURN: Movement.IN, Reason.PURCHASE_RETURN: Movement.OUT,
    Reason.BREAKAGE: Movement.OUT, Reason.WASTAGE: Movement.OUT, Reason.SAMPLE: Movement.OUT,
    Reason.CONSUMED: Movement.OUT,
}
NEEDS_CUSTOMER = (Reason.SALE, Reason.SALES_RETURN)
NEEDS_SUPPLIER = (Reason.PURCHASE_RETURN,)


@transaction.atomic
def post_single(user, pouch, reason, pcs, ct, occurred_on=None, customer=None, supplier=None, ref="", note=""):
    """One movement on its own document.

    ``ref`` (an invoice no., or the reference a return answers to) stays on the
    movement rather than numbering the document: one invoice may cover several
    pouches, and a document's number is unique per kind.
    """
    require(user, INV_MOVE, "Only a role that records stock movements can post this.")
    if reason not in SINGLE:
        raise ServiceError(f"{reason} is not posted from the shelf.")
    if reason in NEEDS_CUSTOMER and customer is None:
        raise ServiceError("Choose the customer.")
    if reason in NEEDS_SUPPLIER and supplier is None:
        raise ServiceError("Choose the supplier.")
    document = ledger.open_document(
        user, StockDocument.Kind.SINGLE, occurred_on=occurred_on or timezone.localdate(), note=note,
        customer=customer if reason in NEEDS_CUSTOMER else None,
        vendor=supplier if reason in NEEDS_SUPPLIER else None,
    )
    line = ledger.Line(pouch, reason, SINGLE[reason], pcs, ct, note=note, ref=(ref or "").strip())
    ledger.post(user, document, [line], occurred_on)
    return document


@transaction.atomic
def post_recount(user, pouch, pcs, ct, occurred_on=None, note=""):
    """Bring a pouch to the counted figures: the difference per quantity, on one document.

    ``None`` when the count matches the ledger, so nothing is posted.
    """
    require(user, INV_MOVE, "Only a role that records stock movements can post a recount.")
    if pcs is None and ct is None:
        raise ServiceError("Enter the counted pieces or weight.")
    deltas = services.recount_deltas(pouch, pcs, ct)
    if not deltas:
        return None
    document = ledger.open_document(user, StockDocument.Kind.SINGLE,
                                    occurred_on=occurred_on or timezone.localdate(), note=note)
    ledger.post(user, document, [
        ledger.Line(pouch, Reason.RECOUNT_ADJUSTMENT, direction, note=note, **{field: quantity})
        for field, direction, quantity in deltas
    ], occurred_on)
    return document
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=ledger_t4 .venv/bin/pytest inventory/tests/test_ledger_single.py inventory/tests/test_services.py inventory/tests/test_import_plan.py -p no:warnings`
Expected: PASS (the importer's recount tests included).

- [ ] **Step 6: Commit**

```bash
git add inventory/ledger_single.py inventory/services.py inventory/tests/test_ledger_single.py
git commit -m "$(cat <<'EOF'
Single movements and the recount, each on its own closed document

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Purchase

**Files:**
- Create: `inventory/ledger_purchase.py`, `inventory/tests/test_ledger_purchase.py`

**Interfaces:**
- Consumes: `ledger.open_document/post/Line/new_pouch/pouch_no_free/reverse_document`; `PriceEntry`; `services.stocked/latest_price`.
- Produces:
  - `ledger_purchase.PURCHASE_RIGHTS = (INV_PURCHASE, VIEW_COST, VIEW_VENDOR)` (what the purchase screen and the "Purchase" reason require);
  - dataclass `PurchaseHeader(supplier, occurred_on, invoice_no="", currency="INR", fx_rate=None, landed_extras=Decimal("0"), note="")`;
  - dataclass `PurchaseLine(batch, pouch_no, stone_name, shape, colour, pcs, ct, cost_per_ct)`;
  - `ledger_purchase.post_purchase(user, header, lines) -> StockDocument` (inv_purchase + view_cost).

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_ledger_purchase.py`:

```python
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied

from accounts.models import User
from inventory import ledger, services
from inventory.ledger_purchase import PurchaseHeader, PurchaseLine, post_purchase
from inventory.models import Movement, Pouch, PriceEntry, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal


def _held(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()


def _lines(batch):
    return [
        PurchaseLine(batch=batch, pouch_no="3", stone_name="Tanzanite", shape="Oval", colour="Blue",
                     pcs=12, ct=D("42.50"), cost_per_ct=D("1800")),
        PurchaseLine(batch=batch, pouch_no="4", stone_name="Tanzanite", shape="Round", colour="Blue",
                     pcs=None, ct=D("11.20"), cost_per_ct=D("2400")),
    ]


def _header(supplier, **changes):
    return PurchaseHeader(supplier=supplier, occurred_on=date(2026, 8, 7), invoice_no="2026/0442", **changes)


def test_a_purchase_opens_new_pouches_with_cost_and_landed_valuation(accounts_user, shelf):
    supplier, batch = shelf["supplier"], shelf["batch"]
    doc = post_purchase(accounts_user, _header(supplier, landed_extras=D("5370")), _lines(batch))
    assert (doc.kind, doc.number, doc.status) == (StockDocument.Kind.PURCHASE, "2026/0442", StockDocument.Status.CLOSED)
    assert (doc.vendor, doc.currency, doc.landed_extras) == (supplier, "INR", D("5370"))
    three, four = Pouch.objects.get(batch=batch, pouch_no="3"), Pouch.objects.get(batch=batch, pouch_no="4")
    assert (three.supplier, three.purchase_date, three.stone_name, three.shape, three.countable) == (
        supplier, date(2026, 8, 7), "Tanzanite", "Oval", True)
    assert not four.countable
    assert three.movements.get().reason == Movement.Reason.PURCHASE
    held = _held(three)
    assert (held.on_pcs, held.on_ct, held.rate) == (12, D("42.5"), D("1900"))    # 1,800 + 5,370 ÷ 53.70 ct
    assert services.latest_price(three, PriceEntry.PURCHASE).rate == D("1800")
    assert _held(four).rate == D("2500")
    assert not PriceEntry.objects.filter(kind=PriceEntry.LIST).exists()           # selling price is not set here


def test_a_usd_purchase_needs_its_rate_and_is_costed_in_inr(accounts_user, shelf):
    lines = [PurchaseLine(batch=shelf["batch"], pouch_no="3", stone_name="Tanzanite", shape="Oval", colour="Blue",
                          pcs=2, ct=D("1"), cost_per_ct=D("20"))]
    with pytest.raises(ServiceError, match="USD needs the rate"):
        post_purchase(accounts_user, _header(shelf["supplier"], currency="USD"), lines)
    with pytest.raises(ServiceError, match="rate must be positive"):
        post_purchase(accounts_user, _header(shelf["supplier"], currency="USD", fx_rate=D("-1")), lines)
    doc = post_purchase(accounts_user, _header(shelf["supplier"], currency="USD", fx_rate=D("83.5")), lines)
    pouch = Pouch.objects.get(batch=shelf["batch"], pouch_no="3")
    assert doc.fx_rate == D("83.5") and services.latest_price(pouch, PriceEntry.PURCHASE).rate == D("1670")


def test_an_existing_pouch_number_is_refused_and_nothing_is_written(accounts_user, shelf):
    lines = _lines(shelf["batch"])
    lines[0].pouch_no = "1"
    with pytest.raises(ServiceError, match="SL01G · 1 already exists"):
        post_purchase(accounts_user, _header(shelf["supplier"]), lines)
    assert Pouch.objects.count() == 2 and not StockDocument.objects.exists()


def test_the_same_number_twice_in_one_purchase_is_refused(accounts_user, shelf):
    lines = _lines(shelf["batch"])
    lines[1].pouch_no = "3"
    with pytest.raises(ServiceError, match="already exists"):
        post_purchase(accounts_user, _header(shelf["supplier"]), lines)


@pytest.mark.parametrize("field, value, words", [
    ("ct", D("0"), "weight must be positive"), ("cost_per_ct", D("-1"), "rate must be positive"),
    ("cost_per_ct", None, "rate must be positive"), ("pouch_no", " ", "pouch no."),
])
def test_every_line_needs_a_number_a_weight_and_a_rate(accounts_user, shelf, field, value, words):
    lines = _lines(shelf["batch"])
    setattr(lines[0], field, value)
    with pytest.raises(ServiceError, match=words):
        post_purchase(accounts_user, _header(shelf["supplier"]), lines)


def test_a_supplier_and_a_line_are_required(accounts_user, shelf):
    with pytest.raises(ServiceError, match="Choose the supplier"):
        post_purchase(accounts_user, _header(None), _lines(shelf["batch"]))
    with pytest.raises(ServiceError, match="at least one line"):
        post_purchase(accounts_user, _header(shelf["supplier"]), [])


def test_no_invoice_no_draws_an_automatic_number(accounts_user, shelf):
    doc = post_purchase(accounts_user, _header(shelf["supplier"], invoice_no=""), _lines(shelf["batch"])[:1])
    assert doc.number == "PUR-000001"


def test_a_purchase_needs_the_right_and_sight_of_cost(production_user, accounts_user, shelf):
    with pytest.raises(PermissionDenied):
        post_purchase(production_user, _header(shelf["supplier"]), _lines(shelf["batch"]))
    Group.objects.get(name="ACCOUNTS").permissions.remove(Permission.objects.get(codename="view_cost"))
    blind = User.objects.get(pk=accounts_user.pk)                 # a fresh object: no cached permissions
    with pytest.raises(PermissionDenied):
        post_purchase(blind, _header(shelf["supplier"]), _lines(shelf["batch"]))


def test_a_reversed_purchase_leaves_its_pouches_at_zero(accounts_user, shelf):
    doc = post_purchase(accounts_user, _header(shelf["supplier"]), _lines(shelf["batch"]))
    ledger.reverse_document(accounts_user, doc)
    for number in ("3", "4"):
        assert _held(Pouch.objects.get(batch=shelf["batch"], pouch_no=number)).on_ct == D("0")
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=ledger_t5 .venv/bin/pytest inventory/tests/test_ledger_purchase.py -p no:warnings`
Expected: FAIL — `No module named 'inventory.ledger_purchase'`.

- [ ] **Step 3: Write `inventory/ledger_purchase.py`**

```python
"""Record a purchase: the one clean way new stock enters.

Each line opens a new pouch (supplier and purchase date set), posts a Purchase
in movement on it, writes what was paid per carat in INR as a ``purchase``
price, and values it at landed cost — that price plus the purchase's freight,
duty and cutting spread by weight. The selling price is a separate decision.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction

from accounts.capabilities import INV_PURCHASE, VIEW_COST, VIEW_VENDOR
from stock.models import Vendor
from stock.services import ServiceError, require

from . import ledger
from .models import Batch, Movement, PriceEntry, StockDocument

ZERO, PLACES = Decimal("0"), Decimal("0.0001")
#: what the purchase screen needs: the right, and sight of the cost and supplier it writes
PURCHASE_RIGHTS = (INV_PURCHASE, VIEW_COST, VIEW_VENDOR)


@dataclass
class PurchaseHeader:
    supplier: Vendor | None
    occurred_on: date
    invoice_no: str = ""
    currency: str = "INR"
    fx_rate: Decimal | None = None
    landed_extras: Decimal = ZERO
    note: str = ""


@dataclass
class PurchaseLine:
    batch: Batch
    pouch_no: str
    stone_name: str
    shape: str
    colour: str
    pcs: int | None
    ct: Decimal | None
    cost_per_ct: Decimal | None


def _check(header, lines):
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


@transaction.atomic
def post_purchase(user, header, lines):
    """New pouches only: a line on an existing batch + pouch no. is refused (known limit)."""
    require(user, INV_PURCHASE, "Only a role that records purchases can post one.")
    require(user, VIEW_COST, "A purchase writes a cost you may not see.")
    _check(header, lines)
    usd = header.currency == "USD"
    fx = header.fx_rate if usd else Decimal("1")
    extras = header.landed_extras or ZERO
    per_ct = extras / sum(line.ct for line in lines)         # extras spread by weight
    document = ledger.open_document(
        user, StockDocument.Kind.PURCHASE, header.invoice_no, vendor=header.supplier,
        occurred_on=header.occurred_on, currency=header.currency, fx_rate=header.fx_rate if usd else None,
        landed_extras=extras, note=header.note,
    )
    by = user if getattr(user, "is_authenticated", False) else None
    moves, prices = [], []
    for line in lines:
        pouch = ledger.new_pouch(
            line.batch, pouch_no=line.pouch_no.strip(), stone_name=line.stone_name, shape=line.shape,
            colour=line.colour, countable=line.pcs is not None, supplier=header.supplier,
            purchase_date=header.occurred_on,
        )
        cost = (line.cost_per_ct * fx).quantize(PLACES)
        prices += [
            PriceEntry(pouch=pouch, kind=PriceEntry.PURCHASE, rate=cost, effective_from=header.occurred_on, set_by=by),
            PriceEntry(pouch=pouch, kind=PriceEntry.VALUATION, rate=(cost + per_ct).quantize(PLACES),
                       effective_from=header.occurred_on, set_by=by),
        ]
        moves.append(ledger.Line(pouch, Movement.Reason.PURCHASE, Movement.IN, line.pcs, line.ct))
    ledger.post(user, document, moves, header.occurred_on)
    PriceEntry.objects.bulk_create(prices)
    return document
```

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=ledger_t5 .venv/bin/pytest inventory/tests/test_ledger_purchase.py -p no:warnings`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add inventory/ledger_purchase.py inventory/tests/test_ledger_purchase.py
git commit -m "$(cat <<'EOF'
Purchases: new pouches, a Purchase movement, the cost row and a landed valuation

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Split and transfer

**Files:**
- Create: `inventory/ledger_assort.py`, `inventory/tests/test_ledger_assort.py`

**Interfaces:**
- Consumes: `ledger.open_document/post/Line/new_pouch/pouch_no_free/reverse_document`; `services.stocked`; `PriceEntry`.
- Produces:
  - dataclass `SplitPart(pouch_no, pcs, ct, size_text="", remarks="")`;
  - `ledger_assort.split_pouch(user, source, out_pcs, out_ct, parts, loss_pcs=None, loss_ct=None, note="") -> StockDocument` (inv_assort);
  - `ledger_assort.transfer_pouch(user, pouch, to_batch, to_pouch_no, note="") -> StockDocument` (inv_assort; mutates `pouch.batch` / `pouch.pouch_no`);
  - `ledger_assort.COPIED` (the attributes a new pouch takes from its parent).

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_ledger_assort.py`:

```python
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from inventory import ledger, ledger_assort, services
from inventory.ledger_assort import SplitPart
from inventory.models import Batch, Movement, Pouch, StockDocument
from stock.services import ServiceError

pytestmark = pytest.mark.django_db
D = Decimal
R = Movement.Reason


def _held(pouch):
    return services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()


def _other():
    return Batch.objects.create(code="SP14B", box_colour_id="B", family="S", cls="P", seq="14")


def _split(user, shelf, **changes):
    args = {"source": shelf["onyx"], "out_pcs": 10, "out_ct": D("6"), "loss_pcs": 1, "loss_ct": D("0.5"),
            "parts": [SplitPart("3", 6, D("3.5"), size_text="10*8", remarks="the larger ones"), SplitPart("4", 3, D("2"))]}
    return ledger_assort.split_pouch(user, **(args | changes))


def test_a_split_balances_and_carries_the_parent_across(accounts_user, shelf):
    onyx, batch = shelf["onyx"], shelf["batch"]
    doc = _split(accounts_user, shelf)
    assert (doc.kind, doc.number, doc.status) == (StockDocument.Kind.SPLIT, "SPL-000001", StockDocument.Status.CLOSED)
    three = Pouch.objects.get(batch=batch, pouch_no="3")
    assert three.parent == onyx and (three.size_text, three.remarks) == ("10*8", "the larger ones")
    assert (three.stone_name, three.shape, three.carton, three.supplier, three.countable) == (
        "Green Onyx", "Oval", "C-117", shelf["supplier"], True)
    held = _held(three)
    assert (held.on_pcs, held.on_ct, held.rate) == (6, D("3.5"), D("7919"))       # the parent's valuation rate
    assert (_held(onyx).on_pcs, _held(onyx).on_ct) == (10, D("6.5"))
    out = doc.movements.get(pouch=onyx, reason=R.SPLIT)
    assert (out.direction, out.pcs, out.ct) == (Movement.OUT, 9, D("5.5"))
    loss = doc.movements.get(pouch=onyx, reason=R.WASTAGE)
    assert (loss.direction, loss.pcs, loss.ct) == (Movement.OUT, 1, D("0.5"))
    assert doc.movements.filter(reason=R.SPLIT, direction=Movement.IN).count() == 2


def test_an_unbalanced_split_is_refused(accounts_user, shelf):
    with pytest.raises(ServiceError, match="0.50 ct unaccounted"):
        _split(accounts_user, shelf, loss_ct=None)
    with pytest.raises(ServiceError, match="1 pcs unaccounted"):
        _split(accounts_user, shelf, loss_pcs=None)
    assert not StockDocument.objects.exists()


def test_a_split_cannot_take_more_than_the_pouch_holds(accounts_user, shelf):
    with pytest.raises(ServiceError, match="below zero"):
        _split(accounts_user, shelf, out_pcs=6, out_ct=D("13"), loss_pcs=None, loss_ct=None,
               parts=[SplitPart("3", 6, D("13"))])


def test_new_pouch_numbers_must_be_free(accounts_user, shelf):
    with pytest.raises(ServiceError, match="taken"):
        _split(accounts_user, shelf, parts=[SplitPart("2", 6, D("3.5")), SplitPart("4", 3, D("2"))])
    with pytest.raises(ServiceError, match="taken"):
        _split(accounts_user, shelf, parts=[SplitPart("3", 6, D("3.5")), SplitPart("3", 3, D("2"))])


def test_an_uncountable_pouch_splits_by_weight(accounts_user, shelf):
    ruby = shelf["ruby"]
    ledger_assort.split_pouch(accounts_user, ruby, None, D("40"), [SplitPart("3", None, D("25")), SplitPart("4", None, D("15"))])
    assert _held(ruby).on_ct == D("0") and not Pouch.objects.get(batch=shelf["batch"], pouch_no="3").countable
    with pytest.raises(ServiceError, match="Enter the weight"):
        ledger_assort.split_pouch(accounts_user, ruby, None, None, [SplitPart("5", None, D("1"))])


def test_reversing_a_split_restores_the_parent_and_leaves_the_new_pouches_at_zero(accounts_user, shelf):
    doc = _split(accounts_user, shelf)
    ledger.reverse_document(accounts_user, doc)
    assert (_held(shelf["onyx"]).on_pcs, _held(shelf["onyx"]).on_ct) == (20, D("12.5"))
    assert _held(Pouch.objects.get(batch=shelf["batch"], pouch_no="3")).on_ct == D("0")


def test_a_split_whose_new_pouch_has_moved_is_not_reversed(accounts_user, shelf):
    doc = _split(accounts_user, shelf)
    three = Pouch.objects.get(batch=shelf["batch"], pouch_no="3")
    sale = ledger.open_document(accounts_user, StockDocument.Kind.SINGLE)
    ledger.post(accounts_user, sale, [ledger.Line(three, R.SALE, Movement.OUT, 1, D("0.5"))])
    with pytest.raises(ServiceError, match="moved since"):
        ledger.reverse_document(accounts_user, doc)


def test_a_transfer_re_files_the_whole_pouch(accounts_user, shelf):
    onyx, other = shelf["onyx"], _other()
    doc = ledger_assort.transfer_pouch(accounts_user, onyx, other, "1", note="re-sorted")
    onyx.refresh_from_db()
    assert (onyx.batch, onyx.pouch_no, onyx.ref) == (other, "1", "NRN-000001")
    assert (doc.kind, doc.number, doc.from_batch, doc.from_pouch_no, doc.to_batch, doc.to_pouch_no) == (
        StockDocument.Kind.TRANSFER, "TRF-000001", shelf["batch"], "1", other, "1")
    move = doc.movements.get()
    assert (move.reason, move.direction, move.pcs, move.ct) == (R.TRANSFER, Movement.SETTLE, 20, D("12.5"))
    assert (_held(onyx).on_pcs, _held(onyx).on_ct) == (20, D("12.5"))


def test_a_transfer_needs_another_existing_batch_and_a_free_number(accounts_user, shelf):
    other = _other()
    with pytest.raises(ServiceError, match="Choose the batch"):
        ledger_assort.transfer_pouch(accounts_user, shelf["onyx"], None, "1")
    with pytest.raises(ServiceError, match="choose another"):
        ledger_assort.transfer_pouch(accounts_user, shelf["onyx"], shelf["batch"], "9")
    ledger_assort.transfer_pouch(accounts_user, shelf["onyx"], other, "1")
    with pytest.raises(ServiceError, match="taken"):
        ledger_assort.transfer_pouch(accounts_user, shelf["ruby"], other, "1")


def test_an_empty_pouch_is_not_transferred(accounts_user, shelf):
    sale = ledger.open_document(accounts_user, StockDocument.Kind.SINGLE)
    ledger.post(accounts_user, sale, [ledger.Line(shelf["ruby"], R.SALE, Movement.OUT, None, D("40"))])
    with pytest.raises(ServiceError, match="above zero"):
        ledger_assort.transfer_pouch(accounts_user, shelf["ruby"], _other(), "1")


def test_a_reversed_transfer_files_the_pouch_back(accounts_user, shelf):
    onyx = shelf["onyx"]
    doc = ledger_assort.transfer_pouch(accounts_user, onyx, _other(), "1")
    ledger.reverse_document(accounts_user, doc)
    onyx.refresh_from_db()
    assert (onyx.batch, onyx.pouch_no) == (shelf["batch"], "1")


def test_split_and_transfer_need_the_assort_right(production_user, shelf):
    with pytest.raises(PermissionDenied):
        _split(production_user, shelf)
    with pytest.raises(PermissionDenied):
        ledger_assort.transfer_pouch(production_user, shelf["onyx"], _other(), "1")
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=ledger_t6 .venv/bin/pytest inventory/tests/test_ledger_assort.py -p no:warnings`
Expected: FAIL — `cannot import name 'ledger_assort'`.

- [ ] **Step 3: Write `inventory/ledger_assort.py`**

```python
"""Splitting a pouch, and re-filing one into another batch.

A split moves weight, it does not make or lose it: what comes out of the pouch
equals what goes into the new pouches plus any loss, in carats, and in pieces
when the pouch is counted (the diamond assortment's rule). A transfer changes
only where a pouch is filed; its quantity and its ``NRN-`` reference stay.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from accounts.capabilities import INV_ASSORT
from stock.services import ServiceError, require

from . import ledger, services
from .models import Movement, Pouch, PriceEntry, StockDocument

Reason = Movement.Reason
#: what a new pouch takes from the pouch it was split from
COPIED = ("category", "stone_name", "colour", "shape", "cut", "quality", "carton", "supplier",
          "treatment", "origin", "purchase_date", "countable")


@dataclass
class SplitPart:
    pouch_no: str
    pcs: int | None
    ct: Decimal | None
    size_text: str = ""
    remarks: str = ""


def _by(user):
    return user if getattr(user, "is_authenticated", False) else None


def _free_numbers(batch, parts):
    numbers = [(part.pouch_no or "").strip() for part in parts]
    for number in numbers:
        if not number or numbers.count(number) > 1 or not ledger.pouch_no_free(batch, number):
            raise ServiceError(f"{batch} · {number or '(blank)'} is taken — a new pouch number must be free in its batch.")
    return numbers


@transaction.atomic
def split_pouch(user, source, out_pcs, out_ct, parts, loss_pcs=None, loss_ct=None, note=""):
    """Take ``out_pcs`` / ``out_ct`` from ``source`` into new pouches in its batch, less an
    optional loss. The new pouches carry the source's current valuation rate."""
    require(user, INV_ASSORT, "Only a role that assorts can split a pouch.")
    if out_ct is None or out_ct <= 0:
        raise ServiceError("Enter the weight that comes out of the pouch.")
    if not parts:
        raise ServiceError("Add at least one new pouch.")
    numbers = _free_numbers(source.batch, parts)
    unaccounted = out_ct - sum((part.ct or 0 for part in parts), loss_ct or 0)
    if unaccounted:
        raise ServiceError(f"{unaccounted:.2f} ct unaccounted — a split must balance.")
    if source.countable:
        short = (out_pcs or 0) - sum((part.pcs or 0 for part in parts), loss_pcs or 0)
        if short:
            raise ServiceError(f"{short} pcs unaccounted — a split must balance.")
    rate = services.stocked(Pouch.objects.filter(pk=source.pk)).get().rate
    document = ledger.open_document(user, StockDocument.Kind.SPLIT, note=note)
    moved_pcs = None if out_pcs is None else out_pcs - (loss_pcs or 0)
    lines = [ledger.Line(source, Reason.SPLIT, Movement.OUT, moved_pcs, out_ct - (loss_ct or 0), note=note)]
    if loss_pcs or loss_ct:
        lines.append(ledger.Line(source, Reason.WASTAGE, Movement.OUT, loss_pcs, loss_ct, note="Loss in the split"))
    children = []
    for part, number in zip(parts, numbers):
        child = ledger.new_pouch(source.batch, pouch_no=number, parent=source, size_text=part.size_text,
                                 remarks=part.remarks, **{field: getattr(source, field) for field in COPIED})
        children.append(child)
        lines.append(ledger.Line(child, Reason.SPLIT, Movement.IN, part.pcs, part.ct, note=note))
    ledger.post(user, document, lines)
    if rate is not None:
        PriceEntry.objects.bulk_create([PriceEntry(pouch=child, kind=PriceEntry.VALUATION, rate=rate, set_by=_by(user))
                                        for child in children])
    return document


@transaction.atomic
def transfer_pouch(user, pouch, to_batch, to_pouch_no, note=""):
    """Re-file the whole pouch into an existing batch under a pouch no. free there.

    One Transfer movement records it (direction settle, the balance moved, for
    the record); the document holds the from and the to, so it can be reversed.
    """
    require(user, INV_ASSORT, "Only a role that assorts can re-file a pouch.")
    to_pouch_no = (to_pouch_no or "").strip()
    if to_batch is None:
        raise ServiceError("Choose the batch to re-file into; it must already exist.")
    if to_batch.pk == pouch.batch_id:
        raise ServiceError(f"{pouch} is already in {to_batch}; choose another batch.")
    if not to_pouch_no or not ledger.pouch_no_free(to_batch, to_pouch_no):
        raise ServiceError(f"{to_batch} · {to_pouch_no or '(blank)'} is taken — a new pouch number must be free in its batch.")
    held = services.stocked(Pouch.objects.filter(pk=pouch.pk)).get()
    document = ledger.open_document(
        user, StockDocument.Kind.TRANSFER, note=note, from_batch=pouch.batch, from_pouch_no=pouch.pouch_no or "",
        to_batch=to_batch, to_pouch_no=to_pouch_no,
    )
    trail = f"{pouch.batch.code} · {pouch.pouch_no or '?'} → {to_batch.code} · {to_pouch_no}"
    ledger.post(user, document, [ledger.Line(pouch, Reason.TRANSFER, Movement.SETTLE,
                                             held.on_pcs if pouch.countable else None, held.on_ct, note=trail)])
    pouch.batch, pouch.pouch_no = to_batch, to_pouch_no
    pouch.save(update_fields=["batch", "pouch_no"])
    return document
```

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_DB=ledger_t6 .venv/bin/pytest inventory/tests/test_ledger_assort.py inventory/tests/test_ledger.py -p no:warnings`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add inventory/ledger_assort.py inventory/tests/test_ledger_assort.py
git commit -m "$(cat <<'EOF'
Split a pouch into new ones that must balance, and re-file a whole pouch into another batch

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---
### Task 7: The pouch's Movements page records movements

**Files:**
- Replace: `inventory/views_ledger.py` (the Task 2 stub), `inventory/templates/inventory/movements.html`
- Modify: `inventory/views.py` (the old `movements` view leaves)
- Create: `inventory/tests/test_record_movement.py`

**Interfaces:**
- Consumes: `ledger.party/owed_by_document/ZERO`; `ledger_jobs.job_work_out/memo_out/settle_job_work/settle_memo/karigar_choices/customer_choices`; `ledger_single.post_single/post_recount`; `ledger_purchase.PURCHASE_RIGHTS`; `inputs.*`; `views._client/_everything/_page`; URL names `inventory:movement_post`, `inventory:document`, `inventory:purchase`, `inventory:split`, `inventory:transfer` (Task 2).
- Produces: `views_ledger.movements(request, ref)`, `views_ledger.movement_post(request, ref)`; `views_ledger.REASONS`, `views_ledger.offered(user) -> [(reason, word)]`, `views_ledger.REASON_TONE`, `views_ledger.TRANSFER = "Transfer to another batch"`.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_record_movement.py`:

```python
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import ledger_jobs, services
from inventory.models import Movement, StockDocument
from inventory.tests.conftest import KARIGAR, SUPPLIER

pytestmark = pytest.mark.django_db
D = Decimal
ALL = ["Job Work Out", "Job Work In", "Sale", "Sales Return", "Memo Out", "Memo In", "Purchase",
       "Consumed in Production", "Wastage / Loss in Process", "Breakage", "Transfer to another batch",
       "Recount Adjustment", "Purchase Return", "Sample"]
JOB = ["Job Work Out", "Job Work In", "Consumed in Production", "Wastage / Loss in Process"]


def _body(client, user, pouch):
    client.force_login(user)
    return client.get(reverse("inventory:movements", args=[pouch.ref])).content.decode()


def _offered(body):
    return [reason for reason in ALL if f'value="{reason}" data-word' in body]


def _post(client, user, pouch, data, **extra):
    client.force_login(user)
    return client.post(reverse("inventory:movement_post", args=[pouch.ref]), data, **extra)


def test_the_form_offers_only_what_the_viewer_may_post(
    client, shelf, admin_user_, accounts_user, karigar_user, production_user, sales_user
):
    assert _offered(_body(client, admin_user_, shelf["onyx"])) == ALL
    assert _offered(_body(client, accounts_user, shelf["onyx"])) == ALL
    assert _offered(_body(client, karigar_user, shelf["onyx"])) == JOB
    assert _offered(_body(client, production_user, shelf["onyx"])) == JOB
    body = _body(client, sales_user, shelf["onyx"])
    assert _offered(body) == [] and "Post movement" not in body


def test_the_card_carries_the_prototypes_fields_and_checks(client, admin_user_, shelf):
    onyx = shelf["onyx"]
    body = _body(client, admin_user_, onyx)
    for text in ('Pieces <span class="qword">out</span>', "Karigar", "Delivery challan no.", "Expected back",
                 "Checks that will run", "<code>challan_no</code> present", "Out on Job Work",
                 "<code>20 − out pcs ≥ 0</code>", "Post movement", "⤴ Split", "⇄ Transfer to another batch"):
        assert text in body, text
    for url in (reverse("inventory:purchase"), reverse("inventory:split", args=[onyx.ref]),
                reverse("inventory:transfer", args=[onyx.ref])):
        assert url in body, url
    assert "🔒" not in body.split('id="record"')[1].split("</form>")[0]


def test_job_work_out_posts_and_the_ledger_links_its_challan(client, admin_user_, shelf, parties):
    onyx = shelf["onyx"]
    response = _post(client, admin_user_, onyx, {
        "reason": "Job Work Out", "pcs": "6", "ct": "4", "karigar": parties["karigar"].pk,
        "challan_no": "2026/0431", "occurred_on": "2026-10-01", "expected_back": "2026-10-08"})
    assert response.status_code == 302
    doc = StockDocument.objects.get(number="2026/0431")
    body = _body(client, admin_user_, onyx)
    assert KARIGAR in body and reverse("inventory:document", args=[doc.pk]) in body and "8.50 ct" in body


def test_a_refusal_comes_back_on_the_form_with_what_was_typed(client, admin_user_, shelf, parties):
    response = _post(client, admin_user_, shelf["onyx"], {
        "reason": "Job Work Out", "pcs": "6", "ct": "4.25", "karigar": parties["karigar"].pk, "challan_no": ""})
    body = response.content.decode()
    assert response.status_code == 200 and "challan no. is required" in body
    assert 'value="4.25"' in body and 'value="Job Work Out" data-word="out" selected' in body
    assert not Movement.objects.filter(reason="Job Work Out").exists()


def test_too_much_out_is_refused_in_plain_words(client, admin_user_, shelf, parties):
    response = _post(client, admin_user_, shelf["onyx"], {"reason": "Sale", "ct": "99", "customer": "C-881"})
    assert "Not enough in SL01G · 1" in response.content.decode()


def test_a_reason_the_viewer_may_not_post_is_a_403(client, karigar_user, shelf):
    assert _post(client, karigar_user, shelf["onyx"], {"reason": "Sale", "ct": "1"}).status_code == 403


def test_a_sale_against_a_memo_settles_it(client, accounts_user, shelf, parties):
    ruby = shelf["ruby"]
    memo = ledger_jobs.memo_out(accounts_user, ruby, parties["customer"], "MEMO-0088", None, D("5"))
    _post(client, accounts_user, ruby, {"reason": "Sale", "ct": "5", "memo": memo.pk})
    memo.refresh_from_db()
    assert memo.status == StockDocument.Status.CLOSED and services.stocked().get(pk=ruby.pk).on_ct == D("35")


def test_consumed_settles_a_challan_when_one_is_chosen_and_else_leaves_the_shelf(client, accounts_user, shelf, parties):
    onyx = shelf["onyx"]
    job = ledger_jobs.job_work_out(accounts_user, onyx, parties["karigar"], "2026/0431", 4, D("3"))
    _post(client, accounts_user, onyx, {"reason": "Consumed in Production", "pcs": "4", "ct": "3", "challan": job.pk})
    job.refresh_from_db()
    assert job.status == StockDocument.Status.CLOSED and services.stocked().get(pk=onyx.pk).on_ct == D("9.5")
    _post(client, accounts_user, onyx, {"reason": "Consumed in Production", "pcs": "1", "ct": "1", "challan": ""})
    assert services.stocked().get(pk=onyx.pk).on_ct == D("8.5")


def test_a_recount_from_the_form_posts_the_difference(client, accounts_user, shelf):
    onyx = shelf["onyx"]
    _post(client, accounts_user, onyx, {"reason": "Recount Adjustment", "pcs": "18", "ct": "12.5"})
    assert services.stocked().get(pk=onyx.pk).on_pcs == 18
    response = _post(client, accounts_user, onyx, {"reason": "Recount Adjustment", "pcs": "18", "ct": "12.5"}, follow=True)
    assert "nothing was posted" in response.content.decode()


def test_the_karigar_desk_is_offered_only_karigars_it_has_used(client, admin_user_, karigar_user, shelf, parties):
    body = _body(client, karigar_user, shelf["ruby"])
    assert SUPPLIER not in body and KARIGAR not in body
    ledger_jobs.job_work_out(admin_user_, shelf["onyx"], parties["karigar"], "2026/0431", 1, D("1"))
    body = _body(client, karigar_user, shelf["ruby"])
    assert KARIGAR in body and SUPPLIER not in body


def test_client_view_reaches_neither_the_page_nor_the_post(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    assert client.get(reverse("inventory:movements", args=[shelf["onyx"].ref])).status_code == 302
    assert client.post(reverse("inventory:movement_post", args=[shelf["onyx"].ref]), {"reason": "Sale"}).status_code == 302
    assert not Movement.objects.filter(reason="Sale").exists()
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=ledger_t7 .venv/bin/pytest inventory/tests/test_record_movement.py -p no:warnings`
Expected: FAIL — the card is still part 1's locked one (`_offered` finds nothing; the post route answers 404).

- [ ] **Step 3: Write `inventory/views_ledger.py`** (replacing the stub)

```python
"""A pouch's Movements page, and its Record movement form.

The form is the prototype's card made to work: the reasons this login may post,
the fields each reason needs, and the checks the server will run. Every post
goes through the ledger services; a refusal comes back on the form with what
was typed still in it.
"""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.capabilities import INV_ASSORT, INV_JOB, INV_MOVE
from crm.models import Customer
from stock.masking import mask
from stock.models import Vendor
from stock.services import ServiceError

from . import inputs, ledger, ledger_jobs, ledger_single, services
from .ledger_purchase import PURCHASE_RIGHTS
from .models import Movement, Pouch, StockDocument
from .views import _client, _everything, _page

Reason, Kind, Status = Movement.Reason, StockDocument.Kind, StockDocument.Status

#: the prototype's chip colours per reason
REASON_TONE = {Reason.MEMO_IN: "good", Reason.JOB_WORK_IN: "good", Reason.MEMO_OUT: "info",
               Reason.JOB_WORK_OUT: "warn", Reason.RECOUNT_ADJUSTMENT: "info"}
PERIODS = [("", "All time"), ("12", "Last 12 months"), ("3", "Last 3 months")]
TRANSFER = "Transfer to another batch"
#: the card's reasons — the prototype's twelve in its order, then the two it left out — each
#: with the rights that may post it (any one). Purchase needs all of PURCHASE_RIGHTS; it and
#: Transfer open their own screens.
REASONS = [
    (Reason.JOB_WORK_OUT, (INV_JOB,)), (Reason.JOB_WORK_IN, (INV_JOB,)), (Reason.SALE, (INV_MOVE,)),
    (Reason.SALES_RETURN, (INV_MOVE,)), (Reason.MEMO_OUT, (INV_MOVE,)), (Reason.MEMO_IN, (INV_MOVE,)),
    (Reason.PURCHASE, None), (Reason.CONSUMED, (INV_JOB, INV_MOVE)), (Reason.WASTAGE, (INV_JOB, INV_MOVE)),
    (Reason.BREAKAGE, (INV_MOVE,)), (TRANSFER, (INV_ASSORT,)), (Reason.RECOUNT_ADJUSTMENT, (INV_MOVE,)),
    (Reason.PURCHASE_RETURN, (INV_MOVE,)), (Reason.SAMPLE, (INV_MOVE,)),
]
#: the word the quantity labels take: "Pieces out", "Weight in", "Pieces counted"
WORD = {Reason.JOB_WORK_IN: "in", Reason.MEMO_IN: "in", Reason.SALES_RETURN: "in",
        Reason.RECOUNT_ADJUSTMENT: "counted"}
SYMBOL = {1: ("＋", "in"), -1: ("−", "out"), 0: ("·", "adj")}


def offered(user):
    """``[(reason, word)]`` — only the reasons this login may post."""
    out = []
    for reason, rights in REASONS:
        may = all(map(user.has_perm, PURCHASE_RIGHTS)) if rights is None else any(map(user.has_perm, rights))
        if may:
            out.append((str(reason), WORD.get(reason, "out")))
    return out


def _ledger(user, pouch):
    """The pouch's movements, oldest first, each with the balance after it and its
    counterparty under the key that masks it."""
    rows, pcs, ct = [], 0, 0
    moves = pouch.movements.select_related("counterparty", "recorded_by", "document__vendor", "document__customer")
    for move in moves.order_by("occurred_at", "pk"):
        pcs += move.effect * (move.pcs or 0)
        ct += move.effect * (move.ct or 0)
        if move.document_id:
            party, number = ledger.party(move.document), move.document.number
            ref = move.ref if move.ref != number else ""
        else:
            party, number = ({"vendor_name": move.counterparty.name} if move.counterparty_id else {}), ""
            ref = move.challan_no or move.ref
        symbol, cls = SYMBOL[move.effect]
        rows.append(mask(user, {
            "when": move.occurred_at, "reason": move.reason, "tone": REASON_TONE.get(move.reason, ""),
            "note": move.note, "sym": symbol, "cls": cls, "reversal": bool(move.reverses_id),
            "pcs": move.pcs, "ct": move.ct, "doc_pk": move.document_id, "number": number, "ref": ref,
            "bal_pcs": pcs, "bal_ct": ct, **party,
            "by": (move.recorded_by.full_name or move.recorded_by.get_username()) if move.recorded_by_id else "system",
        }))
    return rows


def _open_on(user, pouch, kind):
    """Open challans or memos holding some of this pouch, with how much each still has of it."""
    documents = list(StockDocument.objects.filter(kind=kind, status=Status.OPEN, movements__pouch=pouch)
                     .distinct().select_related("vendor", "customer"))
    owed = ledger.owed_by_document(documents)
    return [mask(user, {"pk": d.pk, "number": d.number, **ledger.party(d),
                        "ct": sum((ct for p, _, ct in owed.get(d.pk, []) if p.pk == pouch.pk), ledger.ZERO)})
            for d in documents]


def _movements_page(request, obj, form=None, error=None):
    user = request.user
    everything = _everything(request)
    row = next(r for r in everything if r["pk"] == obj.pk)
    rows = _ledger(user, obj)
    total = len(rows)
    reason, months = request.GET.get("reason", ""), request.GET.get("months", "")
    if reason:
        rows = [m for m in rows if m["reason"] == reason]
    if months.isdigit():
        since = timezone.now() - timedelta(days=31 * int(months))
        rows = [m for m in rows if m["when"] >= since]
    held = services.stocked(Pouch.objects.filter(pk=obj.pk)).get()
    record = offered(user)
    names = {name for name, _ in record}
    form = form or {}
    return _page(
        request, "inventory/movements.html", everything, tab="tx", pouch_ref=obj.ref, row=row,
        ledger=list(reversed(rows)), ledger_total=total, reason=reason, months=months,
        reasons=Movement.Reason.choices, periods=PERIODS,
        in_stock=bool((held.on_ct or 0) > 0 or (held.on_pcs or 0) > 0),
        record=record, form=form, error=error, today=timezone.localdate().isoformat(),
        chosen=form.get("reason") or request.GET.get("record") or (record[0][0] if record else ""),
        qty_reasons="|".join(name for name, _ in record if name not in (Reason.PURCHASE, TRANSFER)),
        karigars=ledger_jobs.karigar_choices(user) if Reason.JOB_WORK_OUT in names else [],
        challans=_open_on(user, obj, Kind.JOB_WORK) if names & {Reason.JOB_WORK_IN, Reason.CONSUMED, Reason.WASTAGE} else [],
        memos=_open_on(user, obj, Kind.MEMO) if names & {Reason.MEMO_IN, Reason.SALE} else [],
        customers=ledger_jobs.customer_choices(user) if names & {Reason.MEMO_OUT, Reason.SALE, Reason.SALES_RETURN} else [],
        suppliers=[mask(user, {"pk": v.pk, "vendor_name": v.name})
                   for v in Vendor.objects.filter(is_active=True).order_by("name")]
        if Reason.PURCHASE_RETURN in names else [],
    )


@login_required
def movements(request, ref):
    if _client(request):
        return redirect("inventory:pouch", ref=ref)
    return _movements_page(request, get_object_or_404(Pouch, ref=ref))


def _vendor(raw):
    raw = raw or ""
    return Vendor.objects.filter(pk=raw, is_active=True).first() if raw.isdigit() else None


def _customer(raw):
    raw = (raw or "").strip()
    return Customer.objects.filter(customer_code=raw).first() if raw else None


def _open(raw, kind):
    raw = raw or ""
    document = StockDocument.objects.filter(pk=raw, kind=kind).first() if raw.isdigit() else None
    if document is None:
        raise ServiceError(f"Choose the open {'challan' if kind == Kind.JOB_WORK else 'memo'} to settle against.")
    return document


def _record(user, pouch, reason, post):
    """Post one Record movement form: the document it landed on, or ``None`` for a matching count."""
    pcs, ct = inputs.whole(post.get("pcs"), "Pieces"), inputs.decimal(post.get("ct"), "Weight")
    when = inputs.day(post.get("occurred_on")) or timezone.localdate()
    back, note = inputs.day(post.get("expected_back"), "Expected back"), (post.get("note") or "").strip()
    if reason == Reason.JOB_WORK_OUT:
        return ledger_jobs.job_work_out(user, pouch, _vendor(post.get("karigar")), post.get("challan_no"),
                                        pcs, ct, when, back, note)
    if reason == Reason.MEMO_OUT:
        return ledger_jobs.memo_out(user, pouch, _customer(post.get("customer")), post.get("memo_no"),
                                    pcs, ct, when, back, note)
    if reason == Reason.JOB_WORK_IN or (reason in (Reason.CONSUMED, Reason.WASTAGE) and post.get("challan")):
        how = {Reason.JOB_WORK_IN: "in", Reason.CONSUMED: "consumed", Reason.WASTAGE: "loss"}[reason]
        return ledger_jobs.settle_job_work(user, _open(post.get("challan"), Kind.JOB_WORK), pouch, how,
                                           pcs, ct, when, note).document
    if reason == Reason.MEMO_IN or (reason == Reason.SALE and post.get("memo")):
        how = "in" if reason == Reason.MEMO_IN else "sold"
        return ledger_jobs.settle_memo(user, _open(post.get("memo"), Kind.MEMO), pouch, how,
                                       pcs, ct, when, note).document
    if reason == Reason.RECOUNT_ADJUSTMENT:
        return ledger_single.post_recount(user, pouch, pcs, ct, when, note)
    return ledger_single.post_single(user, pouch, reason, pcs, ct, when, customer=_customer(post.get("customer")),
                                     supplier=_vendor(post.get("supplier")), ref=post.get("ref"), note=note)


@login_required
@require_POST
def movement_post(request, ref):
    if _client(request):
        return redirect("inventory:pouch", ref=ref)
    obj = get_object_or_404(Pouch.objects.select_related("batch"), ref=ref)
    reason = request.POST.get("reason", "")
    if reason not in {name for name, _ in offered(request.user)}:
        raise PermissionDenied("That movement is not yours to post.")
    try:
        document = _record(request.user, obj, reason, request.POST)
    except ServiceError as refused:
        return _movements_page(request, obj, form=request.POST, error=refused.messages[0])
    if document is None:
        messages.info(request, "The count matches the ledger; nothing was posted.")
    else:
        messages.success(request, f"Posted on {document.number}.")
    return redirect("inventory:movements", ref=ref)
```

- [ ] **Step 4: Rewrite `inventory/templates/inventory/movements.html`**

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
    {% if caps.inv_assort %}<a class="btn gho" href="{% url 'inventory:split' row.ref %}">⤴ Split</a>{% endif %}
    {% if record %}<a class="btn pri" href="#record">＋ Record movement</a>{% endif %}</div>
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
      {% if caps.inv_assort %}<a class="btn sm" style="margin-top:11px" href="{% url 'inventory:transfer' row.ref %}">⇄ Transfer to another batch</a>{% endif %}
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
        <td><span class="chip {{ m.tone }}">{% if m.tone %}<span class="dot"></span>{% endif %}{{ m.reason }}</span>{% if m.reversal %}<div class="hint">↺ reversal</div>{% endif %}{% if m.note %}<div class="hint">{{ m.note }}</div>{% endif %}</td>
        <td class="dir {{ m.cls }}">{{ m.sym }}</td>
        <td class="r">{{ m.pcs|default_if_none:"—" }}</td><td class="r">{{ m.ct|ct }}</td>
        <td>{% if 'karigar_name' in m %}{{ m.karigar_name }}{% elif 'customer_name' in m %}{{ m.customer_name }}{% elif 'vendor_name' in m %}{{ m.vendor_name }}{% endif %}
          {% if m.doc_pk %}<div class="chal"><a href="{% url 'inventory:document' m.doc_pk %}">{{ m.number }}</a>{% if m.ref %} · {{ m.ref }}{% endif %}</div>{% elif m.ref %}<div class="chal">{{ m.ref }}</div>{% endif %}</td>
        <td class="r">{{ m.bal_ct|ct }} ct<div class="hint tnum">{% if row.countable %}{{ m.bal_pcs }} pcs{% else %}no pcs{% endif %}</div></td>
        <td class="hint">{{ m.by }}</td></tr>
      {% empty %}<tr><td colspan="8" class="hint">No movements in this period.</td></tr>{% endfor %}</tbody></table></div>
  </div>

  <div><div class="card" id="record"><div class="card-h"><span class="card-t">Record movement</span></div>
    <div class="card-b">
    {% if record %}
    <form method="post" action="{% url 'inventory:movement_post' row.ref %}" id="recform">{% csrf_token %}
      {% if error %}<div class="banner crit"><div class="banner-ic">!</div><div><h4>{{ error }}</h4></div></div>{% endif %}
      <div class="fld"><label>Reason</label><select class="inp" name="reason">
        {% for value, word in record %}<option value="{{ value }}" data-word="{{ word }}"{% if value == chosen %} selected{% endif %}>{{ value }}</option>{% endfor %}</select></div>
      <div data-for="Purchase"><a class="btn" href="{% url 'inventory:purchase' %}">＋ Record a purchase</a></div>
      <div data-for="Transfer to another batch"><a class="btn" href="{% url 'inventory:transfer' row.ref %}">⇄ Transfer to another batch</a></div>
      <div data-for="{{ qty_reasons }}"><div class="two">
        <div class="fld"><label>Pieces <span class="qword">out</span></label>
          <div class="unit"><input class="inp tnum" name="pcs" inputmode="numeric" value="{{ form.pcs|default:'' }}"{% if not row.countable %} disabled placeholder="uncountable"{% endif %}><span class="u">pcs</span></div></div>
        <div class="fld"><label>Weight <span class="qword">out</span></label>
          <div class="unit"><input class="inp tnum" name="ct" inputmode="decimal" value="{{ form.ct|default:'' }}"><span class="u">ct</span></div></div>
      </div></div>
      <div class="fld" data-for="Job Work Out"><label>Karigar</label><select class="inp" name="karigar"><option value="">—</option>
        {% for k in karigars %}{% if 'karigar_name' in k %}<option value="{{ k.pk }}"{% if form.karigar == k.pk|stringformat:"s" %} selected{% endif %}>{{ k.karigar_name }}</option>{% endif %}{% endfor %}</select></div>
      <div class="fld" data-for="Job Work Out"><label>Delivery challan no. <span style="color:var(--critical)">*</span></label>
        <input class="inp mono" name="challan_no" value="{{ form.challan_no|default:'' }}"></div>
      <div class="fld" data-for="Job Work In|Consumed in Production|Wastage / Loss in Process"><label>Open challan</label>
        <select class="inp" name="challan"><option value="">— from the shelf —</option>
          {% for d in challans %}<option value="{{ d.pk }}"{% if form.challan == d.pk|stringformat:"s" %} selected{% endif %}>{{ d.number }}{% if 'karigar_name' in d %} · {{ d.karigar_name }}{% endif %} · {{ d.ct|ct }} ct out</option>{% endfor %}</select></div>
      <div class="fld" data-for="Memo Out|Sale|Sales Return"><label>Customer</label>
        <input class="inp" name="customer" list="customers" placeholder="customer code" value="{{ form.customer|default:'' }}">
        <datalist id="customers">{% for c in customers %}<option value="{{ c.code }}">{% if 'customer_name' in c %}{{ c.customer_name }}{% endif %}</option>{% endfor %}</datalist></div>
      <div class="fld" data-for="Memo Out"><label>Memo no. <span style="color:var(--critical)">*</span></label>
        <input class="inp mono" name="memo_no" value="{{ form.memo_no|default:'' }}"></div>
      <div class="fld" data-for="Memo In|Sale"><label>Open memo</label>
        <select class="inp" name="memo"><option value="">— a direct sale —</option>
          {% for d in memos %}<option value="{{ d.pk }}"{% if form.memo == d.pk|stringformat:"s" %} selected{% endif %}>{{ d.number }}{% if 'customer_name' in d %} · {{ d.customer_name }}{% endif %} · {{ d.ct|ct }} ct out</option>{% endfor %}</select></div>
      <div class="fld" data-for="Purchase Return"><label>Supplier</label><select class="inp" name="supplier"><option value="">—</option>
        {% for s in suppliers %}{% if 'vendor_name' in s %}<option value="{{ s.pk }}"{% if form.supplier == s.pk|stringformat:"s" %} selected{% endif %}>{{ s.vendor_name }}</option>{% endif %}{% endfor %}</select></div>
      <div class="fld" data-for="Sale|Sales Return|Purchase Return"><label>Invoice / ref no.</label>
        <input class="inp mono" name="ref" value="{{ form.ref|default:'' }}"></div>
      <div data-for="{{ qty_reasons }}"><div class="two">
        <div class="fld"><label>Date</label><input class="inp" type="date" name="occurred_on" value="{{ form.occurred_on|default:today }}"></div>
        <div class="fld" data-for="Job Work Out|Memo Out"><label>Expected back</label><input class="inp" type="date" name="expected_back" value="{{ form.expected_back|default:'' }}"></div>
      </div></div>
      <div class="fld" data-for="{{ qty_reasons }}"><label>Note</label><input class="inp" name="note" value="{{ form.note|default:'' }}"></div>
      <div class="cons"><b>Checks that will run</b>
        <span data-for="Job Work Out|Sale|Memo Out|Consumed in Production|Wastage / Loss in Process|Breakage|Purchase Return|Sample">
          {% if row.countable %}<span class="ok">✓</span> <code>{{ row.pcs }} − out pcs ≥ 0</code><br>{% else %}<span style="color:var(--warnink)">!</span> uncountable — weight only<br>{% endif %}
          <span class="ok">✓</span> <code>{{ row.ct|ct }} ct − out ≥ 0</code><br></span>
        <span data-for="Job Work Out"><span class="ok">✓</span> <code>challan_no</code> present<br>
          <span style="color:var(--warning)">!</span> status → <code>Out on Job Work</code><br></span>
        <span data-for="Memo Out"><span class="ok">✓</span> <code>memo_no</code> present<br>
          <span style="color:var(--warning)">!</span> status → <code>Out on Memo</code><br></span>
        <span data-for="Job Work In|Memo In|Consumed in Production|Wastage / Loss in Process|Sale"><span class="ok">✓</span> against a challan or memo: <code>≤ outstanding</code><br></span>
        <span data-for="Sales Return"><span class="ok">✓</span> <code>weight &gt; 0</code><br></span>
        <span data-for="Recount Adjustment"><span class="ok">✓</span> posts <code>counted − balance</code>, in or out<br>
          {% if not row.countable %}<span style="color:var(--warnink)">!</span> uncountable — weight only<br>{% endif %}</span>
        <span data-for="Purchase|Transfer to another batch">checked on its own screen</span>
      </div>
      <div data-for="{{ qty_reasons }}"><button class="btn pri" style="width:100%;justify-content:center">Post movement</button></div>
    </form>
    {% else %}<p class="hint">No movement here is yours to post.</p>{% endif %}
    </div></div></div>
</div>
<script>
/* Show the chosen reason's fields and checks; the server ignores the rest. */
(function () {
  var form = document.getElementById('recform');
  if (!form) return;
  function show() {
    var chosen = form.elements.reason.selectedOptions[0];
    form.querySelectorAll('[data-for]').forEach(function (el) {
      el.hidden = el.dataset.for.split('|').indexOf(chosen.value) < 0;
    });
    form.querySelectorAll('.qword').forEach(function (el) { el.textContent = chosen.dataset.word; });
  }
  form.elements.reason.addEventListener('change', show);
  show();
})();
</script>
{% endblock %}
```

- [ ] **Step 5: The old view leaves `inventory/views.py`**

Delete from `inventory/views.py`: the line `from datetime import timedelta`, the `REASON_TONE` and `PERIODS` constants, the whole `movements` view, and `Movement` from the models import (nothing else there uses any of them). The import becomes:

```python
from .models import ORIGINS, TREATMENTS, Batch, BoxColour, CodePart, Pouch, PriceEntry
```

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=ledger_t7 .venv/bin/pytest inventory -p no:warnings`
Expected: PASS — the new file, `test_movements.py` and `test_ledger_models.py` (same ledger, same running balance) and the masking walk (the card offers a SALES, KARIGAR or GRAPHIC login no supplier).

- [ ] **Step 7: Commit**

```bash
git add inventory/views_ledger.py inventory/views.py inventory/templates/inventory/movements.html inventory/tests/test_record_movement.py
git commit -m "$(cat <<'EOF'
Record movement works: the prototype's card, every reason a login may post, its checks, refusals on the form

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---
### Task 8: The purchase screen

**Files:**
- Replace: `inventory/views_purchase.py` (the Task 2 stub)
- Create: `inventory/templates/inventory/purchase.html`, `inventory/tests/test_purchase_view.py`
- Modify: `templates/inventory_base.html` (the Purchase tab)

**Interfaces:**
- Consumes: `ledger_purchase.PurchaseHeader/PurchaseLine/post_purchase/PURCHASE_RIGHTS`; `ledger.next_pouch_numbers`; `dia_services.save_supplier`; `inputs.*`; `views._client/_everything/_page`; URL `inventory:document`.
- Produces: `views_purchase.purchase(request)` (GET form, POST post); the Purchase tab as a link for `caps.inv_purchase`. The rail's "＋ Purchases" is Task 11's.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_purchase_view.py`:

```python
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import services
from inventory.models import Pouch, StockDocument
from stock.models import Vendor

pytestmark = pytest.mark.django_db
D = Decimal


def _post(client, user, shelf, **changes):
    data = {"supplier": shelf["supplier"].pk, "occurred_on": "2026-08-07", "invoice_no": "2026/0442",
            "currency": "INR", "fx_rate": "", "landed_extras": "5370",
            "batch": ["SL01G", "sl01g"], "pouch_no": ["3", "4"], "stone_name": ["Tanzanite", "Tanzanite"],
            "shape": ["Oval", "Round"], "colour": ["Blue", "Blue"], "pcs": ["12", ""], "ct": ["42.50", "11.20"],
            "cost": ["1,800", "2400"]}
    client.force_login(user)
    return client.post(reverse("inventory:purchase"), data | changes)


def test_the_screen_is_the_prototypes(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:purchase")).content.decode()
    for text in ("Record a purchase", "The purchase", "Supplier", "Purchase date", "Invoice / bill no.", "Currency",
                 "Landed extras — freight, duty, cutting", "Lines in this purchase", "Pieces", "Cost value",
                 "＋ Add line", "What posting will do", "selling price is <b>not</b> set here", "Post purchase",
                 "Price list", "Realised price", "Stock control", "Recount Adjustment"):
        assert text in body, text
    assert shelf["supplier"].name in body and '"SL01G": 3' in body       # the next free pouch no., for suggesting


@pytest.mark.parametrize("fixture", ["sales_user", "production_user", "karigar_user", "graphic_user"])
def test_the_screen_needs_the_purchase_right(client, shelf, request, fixture):
    client.force_login(request.getfixturevalue(fixture))
    assert client.get(reverse("inventory:purchase")).status_code == 403


def test_posting_opens_the_pouches_and_lands_on_the_document(client, accounts_user, shelf):
    response = _post(client, accounts_user, shelf)
    doc = StockDocument.objects.get(number="2026/0442")
    assert response.status_code == 302 and response["Location"] == reverse("inventory:document", args=[doc.pk])
    four = Pouch.objects.get(batch=shelf["batch"], pouch_no="4")
    assert not four.countable and services.stocked().get(pk=four.pk).rate == D("2500")


def test_a_refusal_comes_back_with_the_lines(client, accounts_user, shelf):
    response = _post(client, accounts_user, shelf, pouch_no=["1", "4"])
    body = response.content.decode()
    assert response.status_code == 200 and "SL01G · 1 already exists" in body
    assert 'value="Tanzanite"' in body and 'value="42.50"' in body
    assert not StockDocument.objects.exists()


def test_usd_needs_its_rate(client, accounts_user, shelf):
    assert "USD needs the rate" in _post(client, accounts_user, shelf, currency="USD").content.decode()


def test_a_purchase_files_into_an_existing_batch(client, accounts_user, shelf):
    body = _post(client, accounts_user, shelf, batch=["ZZ99Q", "SL01G"]).content.decode()
    assert "Batch ZZ99Q does not exist" in body


def test_a_new_supplier_is_created_with_the_purchase(client, accounts_user, shelf):
    _post(client, accounts_user, shelf, supplier="new", new_code="rls", new_name="Ratanlal & Sons")
    assert StockDocument.objects.get().vendor == Vendor.objects.get(code="RLS")


def test_a_refused_purchase_creates_no_supplier(client, accounts_user, shelf):
    _post(client, accounts_user, shelf, supplier="new", new_code="rls", new_name="Ratanlal & Sons", pouch_no=["1", "4"])
    assert not Vendor.objects.filter(code="RLS").exists()


def test_the_purchase_tab_opens_for_those_who_may(client, accounts_user, sales_user, shelf):
    client.force_login(accounts_user)
    assert f'href="{reverse("inventory:purchase")}">Purchase</a>' in client.get(reverse("inventory:shelf")).content.decode()
    client.force_login(sales_user)
    assert "<button disabled>Purchase</button>" in client.get(reverse("inventory:shelf")).content.decode()


def test_client_view_never_opens_it(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    assert client.get(reverse("inventory:purchase")).status_code == 302
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=ledger_t8 .venv/bin/pytest inventory/tests/test_purchase_view.py -p no:warnings`
Expected: FAIL — the route answers 404 (the stub).

- [ ] **Step 3: Write `inventory/views_purchase.py`** (replacing the stub)

```python
"""Record a purchase: the prototype's screen, posting through ``ledger_purchase``."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone

from stock.masking import mask
from stock.models import Vendor
from stock.services import ServiceError, require

from . import dia_services, inputs, ledger, ledger_purchase
from .models import Batch
from .views import _client, _everything, _page

FIELDS = ("batch", "pouch_no", "stone_name", "shape", "colour", "pcs", "ct", "cost")
#: the prototype's Stock control card: everything that moves stock
STOCK_CONTROL = ["Purchase", "Purchase Return", "Sale", "Sales Return", "Memo Out", "Memo In", "Job Work Out",
                 "Job Work In", "Consumed in Production", "Wastage / Loss in Process", "Breakage", "Split", "Merge",
                 "Transfer", "Sample", "Recount Adjustment"]
#: the prototype's Price list card
PRICE_LIST = [("Cost per carat", "from the purchase"), ("Landed cost", "+ freight, duty, cutting"),
              ("Current valuation", "set on revaluation"), ("Selling / list price", "set separately"),
              ("Realised price", "from each sale")]


def _typed(post):
    """The lines as typed, a dict per row; a row left wholly blank is no line."""
    rows = [dict(zip(FIELDS, values)) for values in zip(*(post.getlist(name) for name in FIELDS))]
    return [row for row in rows if any((value or "").strip() for value in row.values())]


def _lines(rows):
    codes = {(row["batch"] or "").strip().upper() for row in rows}
    batches = {batch.code: batch for batch in Batch.objects.filter(code__in=codes)}
    lines = []
    for row in rows:
        code = (row["batch"] or "").strip().upper()
        if code not in batches:
            raise ServiceError(f"Batch {code or '(blank)'} does not exist; a purchase files into an existing batch.")
        lines.append(ledger_purchase.PurchaseLine(
            batch=batches[code], pouch_no=row["pouch_no"] or "", stone_name=(row["stone_name"] or "").strip(),
            shape=(row["shape"] or "").strip(), colour=(row["colour"] or "").strip(),
            pcs=inputs.whole(row["pcs"], "Pieces"), ct=inputs.decimal(row["ct"], "Weight"),
            cost_per_ct=inputs.decimal(row["cost"], "Cost / ct"),
        ))
    return lines


def _supplier(user, post):
    raw = post.get("supplier") or ""
    if raw == "new":
        return dia_services.save_supplier(user, None, post.get("new_code"), post.get("new_name"), "", "")
    return Vendor.objects.filter(pk=raw, is_active=True).first() if raw.isdigit() else None


@login_required
def purchase(request):
    if _client(request):
        return redirect("inventory:shelf")
    for permission in ledger_purchase.PURCHASE_RIGHTS:
        require(request.user, permission, "Recording a purchase needs the purchase right and sight of cost and suppliers.")
    form, rows, error = {}, [dict.fromkeys(FIELDS, "")], None
    if request.method == "POST":
        form, rows = request.POST, _typed(request.POST) or rows
        try:
            with transaction.atomic():           # a new supplier stands or falls with its purchase
                header = ledger_purchase.PurchaseHeader(
                    supplier=_supplier(request.user, form),
                    occurred_on=inputs.day(form.get("occurred_on"), "Purchase date") or timezone.localdate(),
                    invoice_no=form.get("invoice_no", ""), currency=form.get("currency", "INR"),
                    fx_rate=inputs.decimal(form.get("fx_rate"), "Rate to INR"),
                    landed_extras=inputs.decimal(form.get("landed_extras"), "Landed extras") or Decimal("0"),
                    note=form.get("note", ""),
                )
                document = ledger_purchase.post_purchase(request.user, header, _lines(_typed(form)))
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            messages.success(request, f"Purchase {document.number} posted.")
            return redirect("inventory:document", pk=document.pk)
    return _page(
        request, "inventory/purchase.html", _everything(request), tab="purchase", form=form, lines=rows, error=error,
        suppliers=[mask(request.user, {"pk": v.pk, "vendor_name": v.name})
                   for v in Vendor.objects.filter(is_active=True).order_by("name")],
        next_numbers=ledger.next_pouch_numbers(), today=timezone.localdate().isoformat(),
        stock_control=STOCK_CONTROL, price_list=PRICE_LIST,
    )
```

- [ ] **Step 4: Write `inventory/templates/inventory/purchase.html`**

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Record a purchase{% endblock %}
{% block crumb %}Stock control &nbsp;›&nbsp; <b>Purchase</b>{% endblock %}
{% block content %}
<div class="shelfbar"><h1>Record a purchase</h1><span class="spacer"></span>
  <span class="chip info"><span class="dot"></span>Stones</span></div>
{% if error %}<div class="banner crit"><div class="banner-ic">!</div><div><h4>{{ error }}</h4></div></div>{% endif %}

<form method="post" id="purchase">{% csrf_token %}
<div class="tx-cols">
  <div class="card"><div class="card-h"><span class="card-t">The purchase</span></div>
    <div class="card-b">
      <div class="two">
        <div class="fld"><label>Supplier <span style="color:var(--critical)">*</span></label>
          <select class="inp" name="supplier"><option value="">—</option>
            {% if caps.inv_masters %}<option value="new"{% if form.supplier == 'new' %} selected{% endif %}>＋ New supplier…</option>{% endif %}
            {% for s in suppliers %}{% if 'vendor_name' in s %}<option value="{{ s.pk }}"{% if form.supplier == s.pk|stringformat:"s" %} selected{% endif %}>{{ s.vendor_name }}</option>{% endif %}{% endfor %}
          </select></div>
        <div class="fld"><label>Purchase date <span style="color:var(--critical)">*</span></label>
          <input class="inp" type="date" name="occurred_on" value="{{ form.occurred_on|default:today }}"></div>
      </div>
      <div id="newsupplier" hidden><div class="two">
        <div class="fld"><label>Supplier code</label><input class="inp mono" name="new_code" value="{{ form.new_code|default:'' }}"></div>
        <div class="fld"><label>Supplier name</label><input class="inp" name="new_name" value="{{ form.new_name|default:'' }}"></div>
      </div></div>
      <div class="two">
        <div class="fld"><label>Invoice / bill no.</label>
          <input class="inp mono" name="invoice_no" placeholder="e.g. 2026/0442" value="{{ form.invoice_no|default:'' }}"></div>
        <div class="fld"><label>Currency</label><select class="inp" name="currency">
          <option{% if form.currency != 'USD' %} selected{% endif %}>INR</option>
          <option{% if form.currency == 'USD' %} selected{% endif %}>USD</option></select></div>
      </div>
      <div id="fx" hidden><div class="fld"><label>Rate to INR <span style="color:var(--critical)">*</span></label>
        <div class="unit"><input class="inp tnum" name="fx_rate" inputmode="decimal" value="{{ form.fx_rate|default:'' }}"><span class="u">₹ / $</span></div></div></div>
      <div class="fld"><label>Landed extras — freight, duty, cutting</label>
        <div class="unit"><input class="inp tnum" name="landed_extras" inputmode="decimal" placeholder="0" value="{{ form.landed_extras|default:'' }}"><span class="u">₹</span></div></div>

      <div class="grp-t" style="margin:16px 0 10px">Lines in this purchase</div>
      <div style="overflow:auto"><table class="pt" id="lines"><thead><tr>
        <th>Batch</th><th>Pouch</th><th>Stone</th><th>Shape</th><th>Colour</th>
        <th class="r">Pieces</th><th class="r">Weight (ct)</th><th class="r">Cost / ct</th><th class="r">Cost value</th></tr></thead>
        <tbody>{% for l in lines %}<tr>
          <td><input class="inp mono" name="batch" list="batches" value="{{ l.batch }}" style="width:88px"></td>
          <td><input class="inp mono" name="pouch_no" value="{{ l.pouch_no }}" style="width:58px"></td>
          <td><input class="inp" name="stone_name" value="{{ l.stone_name }}" style="width:130px"></td>
          <td><input class="inp" name="shape" value="{{ l.shape }}" style="width:90px"></td>
          <td><input class="inp" name="colour" value="{{ l.colour }}" style="width:90px"></td>
          <td class="r"><input class="inp tnum" name="pcs" inputmode="numeric" placeholder="uncountable" value="{{ l.pcs }}" style="width:96px"></td>
          <td class="r"><input class="inp tnum" name="ct" inputmode="decimal" value="{{ l.ct }}" style="width:84px"></td>
          <td class="r"><input class="inp tnum" name="cost" inputmode="decimal" value="{{ l.cost }}" style="width:90px"></td>
          <td class="r"><b class="lineval">—</b></td></tr>{% endfor %}</tbody></table></div>
      <button class="btn sm" type="button" id="addline" style="margin-top:10px">＋ Add line</button>

      <div class="cons" style="margin-top:14px"><b>What posting will do</b>
        <span class="ok">✓</span> create <span id="w-n">0</span> new pouches<br>
        <span class="ok">✓</span> post an <code>in</code> movement on each — reason <code>Purchase</code><br>
        <span class="ok">✓</span> write a <code>cost</code> price row dated <span id="w-date"></span><br>
        <span class="ok">✓</span> total cost <b id="w-total">₹0</b> across <span id="w-ct">0.00</span> ct<br>
        <span class="ok">✓</span> value each at landed cost — <b id="w-extra">₹0</b> spread by weight<br>
        <span style="color:var(--warnink)">!</span> selling price is <b>not</b> set here — that is a separate decision on the price list
      </div>
      <div class="fld" style="margin-top:12px"><label>Note</label><input class="inp" name="note" value="{{ form.note|default:'' }}"></div>
      <button class="btn pri" style="width:100%;justify-content:center">Post purchase</button>
    </div></div>

  <div>
    <div class="card"><div class="card-h"><span class="card-t">Price list</span></div>
      <div class="card-b">{% for label, source in price_list %}
        <div class="f" style="grid-template-columns:1fr auto"><div class="k">{{ label }}</div><div class="v">{{ source }}</div></div>{% endfor %}
      </div></div>
    <div class="card" style="margin-top:14px"><div class="card-h"><span class="card-t">Stock control</span></div>
      <div class="card-b">{% for reason in stock_control %}<span class="chip" style="margin:0 4px 5px 0">{{ reason }}</span>{% endfor %}</div></div>
  </div>
</div>
</form>
<datalist id="batches">{% for code in next_numbers %}<option value="{{ code }}">{% endfor %}</datalist>
{{ next_numbers|json_script:"next-pouch" }}
<script>
/* Totals as typed, the next free pouch no. per batch, and the fields USD and a new supplier need. */
(function () {
  var form = document.getElementById('purchase'), body = form.querySelector('#lines tbody');
  var next = JSON.parse(document.getElementById('next-pouch').textContent);
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
  function suggest(tr) {
    var code = field(tr, 'batch').value.trim().toUpperCase(), pouch = field(tr, 'pouch_no');
    if (pouch.value || !(code in next)) return;
    var n = next[code];
    body.querySelectorAll('tr').forEach(function (other) {
      var no = parseInt(field(other, 'pouch_no').value, 10);
      if (other !== tr && field(other, 'batch').value.trim().toUpperCase() === code && no >= n) n = no + 1;
    });
    pouch.value = n;
  }
  form.addEventListener('input', total);
  form.addEventListener('change', function (e) {
    if (e.target.name === 'batch') suggest(e.target.closest('tr'));
    total();
  });
  document.getElementById('addline').addEventListener('click', function () {
    var tr = body.lastElementChild.cloneNode(true);
    tr.querySelectorAll('input').forEach(function (input) { input.value = ''; });
    body.appendChild(tr);
    total();
  });
  total();
})();
</script>
{% endblock %}
```

- [ ] **Step 5: The Purchase tab**

`templates/inventory_base.html`, in the stones tabs, replace `<button disabled title="Coming soon">Purchase 🔒</button>` (the one inside `{% if not client_view %}`) with:

```django
          {% if caps.inv_purchase %}<a class="{% if tab == 'purchase' %}on{% endif %}" href="{% url 'inventory:purchase' %}">Purchase</a>
          {% else %}<button disabled>Purchase</button>{% endif %}
```

The diamond side's `Purchase 🔒` stays (part 4).

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_DB=ledger_t8 .venv/bin/pytest inventory -p no:warnings`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add inventory/views_purchase.py inventory/templates/inventory/purchase.html templates/inventory_base.html inventory/tests/test_purchase_view.py
git commit -m "$(cat <<'EOF'
Record a purchase: the prototype's screen with lines, live totals and its two cards, posting new pouches

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Split pouch and Transfer to another batch screens

**Files:**
- Replace: `inventory/views_assort.py` (the Task 2 stub)
- Create: `inventory/templates/inventory/split.html`, `inventory/templates/inventory/transfer.html`, `inventory/tests/test_assort_views.py`
- Modify: `inventory/templates/inventory/pouch.html` (the "⤴ Split pouch" button)

**Interfaces:**
- Consumes: `ledger_assort.split_pouch/transfer_pouch/SplitPart`; `ledger.next_pouch_no/next_pouch_numbers`; `inputs.*`; `views._client/_everything/_page`; URL `inventory:document`.
- Produces: `views_assort.split(request, ref)`, `views_assort.transfer(request, ref)` (GET form, POST post; 403 without `inv_assort`).

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_assort_views.py`:

```python
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory.models import Batch, Pouch, StockDocument

pytestmark = pytest.mark.django_db
D = Decimal


def _other():
    return Batch.objects.create(code="SP14B", box_colour_id="B", family="S", cls="P", seq="14")


def _split(client, user, pouch, **changes):
    data = {"out_pcs": "10", "out_ct": "6", "pouch_no": ["3", "4"], "pcs": ["6", "3"], "ct": ["3.5", "2"],
            "size_text": ["10*8", "14*10"], "remarks": ["", ""], "loss_pcs": "1", "loss_ct": "0.5", "note": ""}
    client.force_login(user)
    return client.post(reverse("inventory:split", args=[pouch.ref]), data | changes)


def test_the_split_screen_starts_from_the_whole_balance(client, accounts_user, shelf):
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:split", args=[shelf["onyx"].ref])).content.decode()
    for text in ("Split pouch", "Source pouch", "＋ Add pouch", "Wastage / Loss in Process", "Post split",
                 "ct unaccounted — cannot post", "balances"):
        assert text in body, text
    assert 'name="out_ct" value="12.50"' in body and 'name="pouch_no" value="3"' in body


def test_a_balanced_split_posts_and_lands_on_its_document(client, accounts_user, shelf):
    response = _split(client, accounts_user, shelf["onyx"])
    doc = StockDocument.objects.get(kind=StockDocument.Kind.SPLIT)
    assert response["Location"] == reverse("inventory:document", args=[doc.pk])
    assert Pouch.objects.get(batch=shelf["batch"], pouch_no="3").parent == shelf["onyx"]


def test_an_unbalanced_split_comes_back_with_its_rows(client, accounts_user, shelf):
    response = _split(client, accounts_user, shelf["onyx"], loss_ct="")
    body = response.content.decode()
    assert response.status_code == 200 and "0.50 ct unaccounted" in body and 'value="3.5"' in body
    assert not StockDocument.objects.exists()


def test_an_uncountable_pouch_splits_by_weight_from_the_screen(client, accounts_user, shelf):
    response = _split(client, accounts_user, shelf["ruby"], out_pcs="", out_ct="40", pcs=["", ""], ct=["25", "15"],
                      loss_pcs="", loss_ct="")
    assert response.status_code == 302


def test_the_assort_screens_need_the_right(client, production_user, shelf):
    client.force_login(production_user)
    for name in ("inventory:split", "inventory:transfer"):
        assert client.get(reverse(name, args=[shelf["onyx"].ref])).status_code == 403, name


def test_transfer_suggests_a_number_and_re_files(client, accounts_user, shelf):
    other, onyx = _other(), shelf["onyx"]
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:transfer", args=[onyx.ref])).content.decode()
    assert "Transfer to another batch" in body and '"SP14B": 1' in body and '"SL01G":' not in body
    response = client.post(reverse("inventory:transfer", args=[onyx.ref]), {"batch": "sp14b", "pouch_no": "1"}, follow=True)
    onyx.refresh_from_db()
    assert onyx.batch == other and "Re-filed as SP14B · 1 on TRF-000001" in response.content.decode()


def test_a_taken_number_comes_back_on_the_form(client, accounts_user, shelf):
    other = _other()
    Pouch.objects.create(ref="NRN-000050", batch=other, pouch_no="1")
    client.force_login(accounts_user)
    response = client.post(reverse("inventory:transfer", args=[shelf["onyx"].ref]), {"batch": "SP14B", "pouch_no": "1"})
    assert response.status_code == 200 and "is taken" in response.content.decode()


def test_the_pouch_page_opens_the_split(client, accounts_user, sales_user, shelf):
    url = reverse("inventory:split", args=[shelf["onyx"].ref])
    client.force_login(accounts_user)
    body = client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()
    assert url in body and "⤴ Split pouch" in body
    client.force_login(sales_user)
    assert url not in client.get(reverse("inventory:pouch", args=[shelf["onyx"].ref])).content.decode()


def test_client_view_reaches_neither_screen(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    for name in ("inventory:split", "inventory:transfer"):
        assert client.get(reverse(name, args=[shelf["onyx"].ref])).status_code == 302
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=ledger_t9 .venv/bin/pytest inventory/tests/test_assort_views.py -p no:warnings`
Expected: FAIL — the routes answer 404 (the stubs).

- [ ] **Step 3: Write `inventory/views_assort.py`** (replacing the stub)

```python
"""Split pouch and Transfer to another batch — the two assort screens.

Both need the assort right, neither is reachable in client view, and a refusal
comes back on the form with what was typed.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect

from accounts.capabilities import INV_ASSORT
from stock.services import ServiceError, require

from . import inputs, ledger, ledger_assort
from .models import Batch, Pouch
from .views import _client, _everything, _page

PART_FIELDS = ("pouch_no", "pcs", "ct", "size_text", "remarks")


def _typed_parts(post):
    """The destination rows as typed; a row left wholly blank is no pouch."""
    rows = [dict(zip(PART_FIELDS, values)) for values in zip(*(post.getlist(name) for name in PART_FIELDS))]
    return [row for row in rows if any((value or "").strip() for value in row.values())]


def _parts(rows):
    return [ledger_assort.SplitPart(pouch_no=row["pouch_no"] or "", pcs=inputs.whole(row["pcs"], "Pieces"),
                                    ct=inputs.decimal(row["ct"], "Carats"), size_text=(row["size_text"] or "").strip(),
                                    remarks=(row["remarks"] or "").strip())
            for row in rows]


def _assort(request, ref, message):
    """The pouch and its row, after the right and the client-view checks."""
    require(request.user, INV_ASSORT, message)
    obj = get_object_or_404(Pouch.objects.select_related("batch"), ref=ref)
    everything = _everything(request)
    return obj, everything, next(r for r in everything if r["pk"] == obj.pk)


@login_required
def split(request, ref):
    if _client(request):
        return redirect("inventory:shelf")
    source, everything, row = _assort(request, ref, "Only a role that assorts can split a pouch.")
    blank = {"pouch_no": ledger.next_pouch_no(source.batch), "pcs": "", "ct": "", "size_text": source.size_text,
             "remarks": ""}
    form = {"out_pcs": row["pcs"] if row["pcs"] is not None else "",
            "out_ct": f"{row['ct']:.2f}" if row["ct"] is not None else ""}
    parts, error = [blank], None
    if request.method == "POST":
        form, parts = request.POST, _typed_parts(request.POST) or [blank]
        try:
            document = ledger_assort.split_pouch(
                request.user, source, inputs.whole(form.get("out_pcs"), "Pieces out"),
                inputs.decimal(form.get("out_ct"), "Weight out"), _parts(_typed_parts(form)),
                inputs.whole(form.get("loss_pcs"), "Loss pieces"), inputs.decimal(form.get("loss_ct"), "Loss weight"),
                (form.get("note") or "").strip(),
            )
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            messages.success(request, f"Split posted as {document.number}.")
            return redirect("inventory:document", pk=document.pk)
    return _page(request, "inventory/split.html", everything, tab="tx", pouch_ref=source.ref, row=row,
                 form=form, parts=parts, error=error)


@login_required
def transfer(request, ref):
    if _client(request):
        return redirect("inventory:shelf")
    obj, everything, row = _assort(request, ref, "Only a role that assorts can re-file a pouch.")
    form, error = {}, None
    if request.method == "POST":
        form = request.POST
        code = (form.get("batch") or "").strip().upper()
        try:
            document = ledger_assort.transfer_pouch(request.user, obj, Batch.objects.filter(code=code).first(),
                                                    form.get("pouch_no"), (form.get("note") or "").strip())
        except ServiceError as refused:
            error = refused.messages[0]
        else:
            messages.success(request, f"Re-filed as {obj} on {document.number}.")
            return redirect("inventory:pouch", ref=obj.ref)
    numbers = ledger.next_pouch_numbers()
    numbers.pop(obj.batch.code, None)
    return _page(request, "inventory/transfer.html", everything, tab="tx", pouch_ref=obj.ref, row=row,
                 form=form, error=error, next_numbers=numbers)
```

- [ ] **Step 4: Write `inventory/templates/inventory/split.html`**

Uncountable pouches get `readonly` (not `disabled`) piece inputs in the rows, so every row still posts a `pcs` value and the columns stay aligned.

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Split · {{ row.batch_code }} · {{ row.pouch_no|default:"?" }}{% endblock %}
{% block crumb %}Shelf &nbsp;›&nbsp; {{ row.box_label }} &nbsp;›&nbsp; <b class="mono">{{ row.batch_code }} · {{ row.pouch_no|default:"?" }}</b> &nbsp;›&nbsp; Split{% endblock %}
{% block content %}
<div class="dbanner"><h2>Split pouch</h2></div>
{% if error %}<div class="banner crit"><div class="banner-ic">!</div><div><h4>{{ error }}</h4></div></div>{% endif %}
<form method="post" id="split">{% csrf_token %}
<div class="filterbar">
  <div class="fsel"><label>Source pouch</label><div class="ro2 mono">{{ row.batch_code }} · {{ row.pouch_no|default:"?" }} — {{ row.stone_name|default:"Unidentified" }}</div></div>
  <div class="fsel"><label>Balance</label><div class="ro2">{% if row.countable %}{{ row.pcs|grouped }} pcs · {% endif %}{{ row.ct|ct }} ct</div></div>
  <div class="fsel"><label>Take out — pieces</label>
    <input class="inp tnum" name="out_pcs" inputmode="numeric" value="{{ form.out_pcs|default:'' }}"{% if not row.countable %} readonly placeholder="uncountable"{% endif %}></div>
  <div class="fsel"><label>Take out — carats</label>
    <div class="unit"><input class="inp tnum" name="out_ct" value="{{ form.out_ct|default:'' }}" inputmode="decimal"><span class="u">ct</span></div></div>
</div>

<div class="card" style="overflow:hidden">
  <div class="card-h"><span class="card-t">New pouches in {{ row.batch_code }}</span><span class="spacer"></span>
    <button class="btn sm" type="button" id="addpouch">＋ Add pouch</button></div>
  <div style="overflow:auto"><table class="led" id="parts">
    <thead><tr><th>Pouch no.</th><th class="r">Pieces</th><th class="r">Carats</th><th>Size</th><th>Remarks</th></tr></thead>
    <tbody>{% for p in parts %}<tr>
      <td><input class="inp mono" name="pouch_no" value="{{ p.pouch_no }}" style="width:80px"></td>
      <td class="r"><input class="inp tnum" name="pcs" inputmode="numeric" value="{{ p.pcs }}" style="width:80px"{% if not row.countable %} readonly placeholder="—"{% endif %}></td>
      <td class="r"><input class="inp tnum" name="ct" inputmode="decimal" value="{{ p.ct }}" style="width:90px"></td>
      <td><input class="inp" name="size_text" value="{{ p.size_text }}" style="width:110px"></td>
      <td><input class="inp" name="remarks" value="{{ p.remarks }}" style="width:180px"></td></tr>{% endfor %}</tbody>
    <tfoot><tr class="ledtot"><td><b>Wastage / Loss in Process</b></td>
      <td class="r"><input class="inp tnum" name="loss_pcs" inputmode="numeric" value="{{ form.loss_pcs|default:'' }}" style="width:80px"{% if not row.countable %} readonly placeholder="—"{% endif %}></td>
      <td class="r"><input class="inp tnum" name="loss_ct" inputmode="decimal" value="{{ form.loss_ct|default:'' }}" style="width:90px"></td>
      <td colspan="2"></td></tr></tfoot>
  </table></div>
  <div class="card-b" style="border-top:1px solid var(--border)">
    <div id="balanced" hidden><span class="chip good"><span class="dot"></span>balances</span></div>
    <div id="unbalanced" hidden><div class="banner crit" style="margin:0"><div class="banner-ic">!</div><div>
      <h4><span id="diff"></span> ct unaccounted — cannot post</h4></div></div></div>
    <div class="fld" style="margin-top:12px"><label>Note</label><input class="inp" name="note" value="{{ form.note|default:'' }}"></div>
    <button class="btn pri" id="postsplit">Post split</button>
  </div>
</div>
</form>
<script>
/* The assortment's balance line: what comes out against what goes in plus the loss. */
(function () {
  var form = document.getElementById('split'), body = form.querySelector('#parts tbody');
  function num(v) { v = parseFloat(String(v || '').replace(/,/g, '')); return isFinite(v) ? v : 0; }
  function check() {
    var into = num(form.elements.loss_ct.value);
    body.querySelectorAll('[name=ct]').forEach(function (input) { into += num(input.value); });
    var diff = Math.round((num(form.elements.out_ct.value) - into) * 10000) / 10000;
    document.getElementById('diff').textContent = diff.toFixed(2);
    document.getElementById('balanced').hidden = diff !== 0;
    document.getElementById('unbalanced').hidden = diff === 0;
    document.getElementById('postsplit').disabled = diff !== 0;
  }
  document.getElementById('addpouch').addEventListener('click', function () {
    var last = body.lastElementChild, tr = last.cloneNode(true);
    var no = parseInt(last.querySelector('[name=pouch_no]').value, 10);
    tr.querySelectorAll('input').forEach(function (input) { if (input.name !== 'size_text') input.value = ''; });
    if (!isNaN(no)) tr.querySelector('[name=pouch_no]').value = no + 1;
    body.appendChild(tr);
    check();
  });
  form.addEventListener('input', check);
  check();
})();
</script>
{% endblock %}
```

- [ ] **Step 5: Write `inventory/templates/inventory/transfer.html`**

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Transfer · {{ row.batch_code }} · {{ row.pouch_no|default:"?" }}{% endblock %}
{% block crumb %}Shelf &nbsp;›&nbsp; {{ row.box_label }} &nbsp;›&nbsp; <b class="mono">{{ row.batch_code }} · {{ row.pouch_no|default:"?" }}</b> &nbsp;›&nbsp; Transfer{% endblock %}
{% block content %}
<div class="dbanner"><h2>Transfer to another batch</h2></div>
{% if error %}<div class="banner crit"><div class="banner-ic">!</div><div><h4>{{ error }}</h4></div></div>{% endif %}
<form method="post" class="card" id="transfer">{% csrf_token %}<div class="card-b">
  <div class="filterbar" style="margin:0">
    <div class="fsel"><label>From</label><div class="ro2 mono">{{ row.batch_code }} · {{ row.pouch_no|default:"?" }}</div></div>
    <div class="fsel"><label>Quantity</label><div class="ro2">{% if row.countable %}{{ row.pcs|grouped }} pcs · {% endif %}{{ row.ct|ct }} ct — unchanged</div></div>
    <div class="fsel"><label>Target batch</label><input class="inp mono" name="batch" list="batches" value="{{ form.batch|default:'' }}" required></div>
    <div class="fsel"><label>Pouch no. there</label><input class="inp mono" name="pouch_no" value="{{ form.pouch_no|default:'' }}" required></div>
  </div>
  <div class="fld" style="margin-top:12px"><label>Note</label><input class="inp" name="note" value="{{ form.note|default:'' }}"></div>
  <div class="hint" style="margin-bottom:10px">Keeps its reference <span class="mono">{{ row.ref }}</span>.</div>
  <button class="btn pri">Post transfer</button>
</div></form>
<datalist id="batches">{% for code in next_numbers %}<option value="{{ code }}">{% endfor %}</datalist>
{{ next_numbers|json_script:"next-pouch" }}
<script>
/* Suggest the next free pouch no. in the batch chosen. */
(function () {
  var form = document.getElementById('transfer'), next = JSON.parse(document.getElementById('next-pouch').textContent);
  form.elements.batch.addEventListener('change', function () {
    var code = form.elements.batch.value.trim().toUpperCase();
    if (code in next) form.elements.pouch_no.value = next[code];
  });
})();
</script>
{% endblock %}
```

- [ ] **Step 6: The pouch page's Split button**

`inventory/templates/inventory/pouch.html`, in the head actions, replace `<button class="btn gho" disabled title="Coming soon">⤴ Split pouch 🔒</button>` with:

```django
      {% if caps.inv_assort %}<a class="btn gho" href="{% url 'inventory:split' row.ref %}">⤴ Split pouch</a>{% endif %}
```

- [ ] **Step 7: Run the tests**

Run: `POSTGRES_DB=ledger_t9 .venv/bin/pytest inventory -p no:warnings`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add inventory/views_assort.py inventory/templates/inventory/split.html inventory/templates/inventory/transfer.html \
  inventory/templates/inventory/pouch.html inventory/tests/test_assort_views.py
git commit -m "$(cat <<'EOF'
Split pouch and Transfer to another batch screens, with the assortment's balance line

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---
### Task 10: The document page

**Files:**
- Replace: `inventory/views_documents.py` (the Task 2 stub)
- Create: `inventory/templates/inventory/document.html`, `inventory/tests/test_document_view.py`

**Interfaces:**
- Consumes: `ledger.party/owed_by_document/undo_last/reverse_document/OPENABLE/RIGHT_FOR_KIND`; `ledger_jobs.settle_job_work/settle_memo`; `inputs.*`; `views._client/_everything/_page`; `PriceEntry`.
- Produces: `views_documents.document(request, pk)` (every internal login, masked), `document_settle(request, pk)` (POST `pouch`, `how`, `pcs`, `ct`, `occurred_on`, `note`), `document_undo(request, pk)`, `document_reverse(request, pk)` (POST `note`) — each POST redirects back to the document with a message; a missing right is 403.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_document_view.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import ledger_jobs, ledger_single, services
from inventory.ledger_purchase import PurchaseHeader, PurchaseLine, post_purchase
from inventory.models import Movement, StockDocument
from inventory.tests.conftest import CUSTOMER, KARIGAR, SUPPLIER

pytestmark = pytest.mark.django_db
D = Decimal


def _job(user, shelf, parties):
    return ledger_jobs.job_work_out(user, shelf["onyx"], parties["karigar"], "2026/0431", 6, D("4"),
                                    expected_back=date.today() + timedelta(days=7))


def _memo(user, shelf, parties):
    return ledger_jobs.memo_out(user, shelf["ruby"], parties["customer"], "MEMO-0088", None, D("5"))


def _body(client, user, doc):
    client.force_login(user)
    return client.get(reverse("inventory:document", args=[doc.pk])).content.decode()


def test_a_job_work_page_shows_what_is_out_and_how_to_settle_it(client, accounts_user, shelf, parties):
    body = _body(client, accounts_user, _job(accounts_user, shelf, parties))
    for text in ("Job work 2026/0431", KARIGAR, "Open", "4.00 ct outstanding", "Received back", "Consumed", "Loss",
                 "↺ Undo last entry", "Reverse document", "₹31,676"):         # 4 ct × ₹7,919
        assert text in body, text


def test_settling_from_the_page_closes_the_challan(client, accounts_user, shelf, parties):
    doc, onyx = _job(accounts_user, shelf, parties), shelf["onyx"]
    client.force_login(accounts_user)
    url = reverse("inventory:document_settle", args=[doc.pk])
    client.post(url, {"pouch": onyx.pk, "how": "in", "pcs": "2", "ct": "1", "occurred_on": ""})
    client.post(url, {"pouch": onyx.pk, "how": "consumed", "pcs": "4", "ct": "3", "occurred_on": ""})
    doc.refresh_from_db()
    assert doc.status == StockDocument.Status.CLOSED
    body = _body(client, accounts_user, doc)
    assert "Closed" in body and "Received back" not in body and "↺ Undo last entry" not in body


def test_too_much_back_comes_back_as_a_message(client, accounts_user, shelf, parties):
    doc = _job(accounts_user, shelf, parties)
    client.force_login(accounts_user)
    response = client.post(reverse("inventory:document_settle", args=[doc.pk]),
                           {"pouch": shelf["onyx"].pk, "how": "in", "ct": "9"}, follow=True)
    assert "cannot exceed what is outstanding" in response.content.decode()


def test_undo_and_reverse_from_the_page(client, accounts_user, shelf, parties):
    doc, onyx = _job(accounts_user, shelf, parties), shelf["onyx"]
    ledger_jobs.settle_job_work(accounts_user, doc, onyx, "in", 1, D("1"))
    client.force_login(accounts_user)
    client.post(reverse("inventory:document_undo", args=[doc.pk]))
    assert services.stocked().get(pk=onyx.pk).on_ct == D("8.5")
    response = client.post(reverse("inventory:document_reverse", args=[doc.pk]), follow=True)
    doc.refresh_from_db()
    assert doc.status == StockDocument.Status.REVERSED and "Reversed by REV-000001" in response.content.decode()
    assert services.stocked().get(pk=onyx.pk).on_ct == D("12.5")


def test_a_refused_reversal_is_a_message(client, accounts_user, shelf, parties):
    back = ledger_single.post_single(accounts_user, shelf["onyx"], Movement.Reason.SALES_RETURN, None, D("5"),
                                     customer=parties["customer"])
    ledger_single.post_single(accounts_user, shelf["onyx"], Movement.Reason.SALE, None, D("17"),
                              customer=parties["customer"])
    client.force_login(accounts_user)
    response = client.post(reverse("inventory:document_reverse", args=[back.pk]), follow=True)
    assert "below zero" in response.content.decode()


def test_a_memo_offers_returned_and_sold(client, accounts_user, shelf, parties):
    body = _body(client, accounts_user, _memo(accounts_user, shelf, parties))
    assert "Memo MEMO-0088" in body and CUSTOMER in body and "Returned" in body and "Sold" in body


def test_who_sees_which_name_and_which_action(client, admin_user_, sales_user, karigar_user, production_user, shelf, parties):
    job, memo = _job(admin_user_, shelf, parties), _memo(admin_user_, shelf, parties)
    body = _body(client, sales_user, job)
    assert "2026/0431" in body and KARIGAR not in body and "Received back" not in body and "Reverse document" not in body
    assert CUSTOMER in _body(client, sales_user, memo)
    body = _body(client, karigar_user, job)
    assert KARIGAR in body and "Received back" in body and "31,676" not in body
    assert CUSTOMER not in _body(client, karigar_user, memo)
    assert CUSTOMER not in _body(client, production_user, memo)


def test_a_purchase_page_shows_its_cost_only_to_those_who_see_cost(client, accounts_user, production_user, shelf):
    doc = post_purchase(accounts_user, PurchaseHeader(supplier=shelf["supplier"], occurred_on=date(2026, 8, 7),
                                                      invoice_no="B-77", landed_extras=D("100")),
                        [PurchaseLine(batch=shelf["batch"], pouch_no="3", stone_name="Tanzanite", shape="Oval",
                                      colour="Blue", pcs=6, ct=D("2"), cost_per_ct=D("4321"))])
    body = _body(client, accounts_user, doc)
    assert "Purchase B-77" in body and "4,321" in body and SUPPLIER in body and "landed extras ₹100" in body
    body = _body(client, production_user, doc)
    assert "4,321" not in body and "landed extras" not in body


def test_writes_need_the_right(client, admin_user_, sales_user, shelf, parties):
    doc = _job(admin_user_, shelf, parties)
    client.force_login(sales_user)
    for name in ("inventory:document_settle", "inventory:document_undo", "inventory:document_reverse"):
        response = client.post(reverse(name, args=[doc.pk]), {"pouch": shelf["onyx"].pk, "how": "in", "ct": "1"})
        assert response.status_code == 403, name


def test_client_view_never_opens_a_document(client, admin_user_, shelf, parties):
    doc = _job(admin_user_, shelf, parties)
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    assert client.get(reverse("inventory:document", args=[doc.pk])).status_code == 302
    assert client.post(reverse("inventory:document_reverse", args=[doc.pk])).status_code == 302
    doc.refresh_from_db()
    assert doc.status == StockDocument.Status.OPEN
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=ledger_t10 .venv/bin/pytest inventory/tests/test_document_view.py -p no:warnings`
Expected: FAIL — the routes answer 404 (the stubs).

- [ ] **Step 3: Write `inventory/views_documents.py`** (replacing the stub)

```python
"""A document's page: what it is, what moved on it, what is still out, and its actions.

Readable by every internal login, masked like every other screen; the actions
— settle, undo the last entry, reverse — need the right for the document's kind.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from stock.masking import mask
from stock.services import ServiceError

from . import inputs, ledger, ledger_jobs
from .models import Pouch, PriceEntry, StockDocument
from .views import _client, _everything, _page

Kind, Status = StockDocument.Kind, StockDocument.Status
#: how an open document's outstanding pouches are settled, in the prototype's words
SETTLE_CHOICES = {Kind.JOB_WORK: [("in", "Received back"), ("consumed", "Consumed"), ("loss", "Loss")],
                  Kind.MEMO: [("in", "Returned"), ("sold", "Sold")]}
TONE = {Status.OPEN: "warn", Status.CLOSED: "good", Status.REVERSED: "crit"}
SYMBOL = {1: ("＋", "in"), -1: ("−", "out"), 0: ("·", "adj")}


def _moves(user, doc):
    """The document's movements, oldest first; a purchase's carry the cost per carat it wrote."""
    bought = doc.kind == Kind.PURCHASE
    rates = dict(PriceEntry.objects.filter(kind=PriceEntry.PURCHASE, pouch__movements__document=doc)
                 .values_list("pouch", "rate")) if bought else {}
    rows = []
    for m in doc.movements.select_related("pouch__batch", "recorded_by").order_by("occurred_at", "pk"):
        symbol, cls = SYMBOL[m.effect]
        rows.append(mask(user, {
            "when": m.occurred_at, "ref": m.pouch.ref, "pouch": str(m.pouch), "reason": m.reason,
            "reversal": bool(m.reverses_id), "sym": symbol, "cls": cls, "pcs": m.pcs, "ct": m.ct, "note": m.note,
            "by": (m.recorded_by.full_name or m.recorded_by.get_username()) if m.recorded_by_id else "system",
            **({"purchase_rate": rates.get(m.pouch_id)} if bought else {}),
        }))
    return rows


@login_required
def document(request, pk):
    if _client(request):
        return redirect("inventory:shelf")
    doc = get_object_or_404(StockDocument.objects.select_related(
        "vendor", "customer", "reverses", "from_batch", "to_batch"), pk=pk)
    user = request.user
    owed = []
    if doc.kind in ledger.OPENABLE and doc.status == Status.OPEN:
        owed = ledger.owed_by_document([doc]).get(doc.pk, [])
    outstanding = [mask(user, {"pk": p.pk, "ref": p.ref, "pouch": str(p), "countable": p.countable,
                               "pcs": pcs if p.countable else None, "ct": ct,
                               "pouch_value": ct * p.rate if p.rate is not None else None})
                   for p, pcs, ct in owed]
    header = mask(user, {**ledger.party(doc), **({"cost_amount": doc.landed_extras} if doc.kind == Kind.PURCHASE else {})})
    may = user.has_perm(ledger.RIGHT_FOR_KIND[doc.kind])
    today = timezone.localdate()
    return _page(
        request, "inventory/document.html", _everything(request), tab="recent", doc=doc, header=header,
        tone=TONE[doc.status], moves=_moves(user, doc), outstanding=outstanding,
        out_ct=sum((o["ct"] for o in outstanding), ledger.ZERO),
        overdue=doc.status == Status.OPEN and doc.expected_back is not None and doc.expected_back < today,
        can_settle=may and bool(outstanding), choices=SETTLE_CHOICES.get(doc.kind, []),
        can_reverse=may and doc.status != Status.REVERSED and not doc.reverses_id,
        reversed_by=StockDocument.objects.filter(reverses=doc).first(), today=today.isoformat(),
    )


def _back(pk):
    return redirect("inventory:document", pk=pk)


@login_required
@require_POST
def document_settle(request, pk):
    if _client(request):
        return redirect("inventory:shelf")
    doc = get_object_or_404(StockDocument, pk=pk)
    raw = request.POST.get("pouch") or ""
    pouch = Pouch.objects.filter(pk=raw).first() if raw.isdigit() else None
    settle = ledger_jobs.settle_job_work if doc.kind == Kind.JOB_WORK else ledger_jobs.settle_memo
    try:
        if pouch is None:
            raise ServiceError("Choose the pouch to settle.")
        settle(request.user, doc, pouch, request.POST.get("how", ""), inputs.whole(request.POST.get("pcs"), "Pieces"),
               inputs.decimal(request.POST.get("ct"), "Weight"), inputs.day(request.POST.get("occurred_on")),
               (request.POST.get("note") or "").strip())
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
    else:
        messages.success(request, "Posted.")
    return _back(pk)


@login_required
@require_POST
def document_undo(request, pk):
    if _client(request):
        return redirect("inventory:shelf")
    doc = get_object_or_404(StockDocument, pk=pk)
    try:
        move = ledger.undo_last(request.user, doc)
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
    else:
        messages.success(request, f"Undone: {move.reason}.")
    return _back(pk)


@login_required
@require_POST
def document_reverse(request, pk):
    if _client(request):
        return redirect("inventory:shelf")
    doc = get_object_or_404(StockDocument, pk=pk)
    try:
        reversal = ledger.reverse_document(request.user, doc, (request.POST.get("note") or "").strip())
    except ServiceError as refused:
        messages.error(request, refused.messages[0])
    else:
        messages.success(request, f"Reversed by {reversal.number}.")
    return _back(pk)
```

- [ ] **Step 4: Write `inventory/templates/inventory/document.html`**

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}{{ doc }}{% endblock %}
{% block crumb %}Stock control &nbsp;›&nbsp; <a href="{% url 'inventory:recent' %}">Movements</a> &nbsp;›&nbsp; <b class="mono">{{ doc.number }}</b>{% endblock %}
{% block content %}
<div class="head">
  <div><div class="k1">{{ doc.get_kind_display }} {{ doc.number }}</div>
    <div class="k2">{% if 'karigar_name' in header %}Karigar · {{ header.karigar_name }}{% elif 'customer_name' in header %}Customer · {{ header.customer_name }}{% elif 'vendor_name' in header %}Supplier · {{ header.vendor_name }}{% else %}{{ doc.get_kind_display }}{% endif %}</div>
    <div class="meta">
      <span class="chip {{ tone }}"><span class="dot"></span>{{ doc.get_status_display }}</span>
      <span class="chip">{{ doc.occurred_on|date:"d M Y" }}</span>
      {% if doc.expected_back %}<span class="chip{% if overdue %} crit{% endif %}">expected back {{ doc.expected_back|date:"d M Y" }}{% if overdue %} · overdue{% endif %}</span>{% endif %}
      {% if outstanding %}<span class="chip warn"><span class="dot"></span>{{ out_ct|ct }} ct outstanding</span>{% endif %}
      {% if doc.kind == 'purchase' %}<span class="chip">{{ doc.currency }}{% if doc.fx_rate %} @ {{ doc.fx_rate }}{% endif %}</span>
        {% if 'cost_amount' in header %}<span class="chip">landed extras {{ header.cost_amount|rupees }}</span>{% endif %}{% endif %}
      {% if doc.kind == 'transfer' %}<span class="chip mono">{{ doc.from_batch.code }} · {{ doc.from_pouch_no|default:"?" }} → {{ doc.to_batch.code }} · {{ doc.to_pouch_no }}</span>{% endif %}
      {% if doc.reverses %}<a class="chip" href="{% url 'inventory:document' doc.reverses_id %}">reverses {{ doc.reverses.number }}</a>{% endif %}
      {% if reversed_by %}<a class="chip crit" href="{% url 'inventory:document' reversed_by.pk %}">reversed by {{ reversed_by.number }}</a>{% endif %}
    </div></div>
  <div class="head-act">
    {% if can_settle %}<form method="post" action="{% url 'inventory:document_undo' doc.pk %}" class="inline">{% csrf_token %}
      <button class="btn gho" onclick="return confirm('Undo the last entry on {{ doc.number|escapejs }}?')">↺ Undo last entry</button></form>{% endif %}
    {% if can_reverse %}<form method="post" action="{% url 'inventory:document_reverse' doc.pk %}" class="inline">{% csrf_token %}
      <button class="btn" onclick="return confirm('Reverse every movement on {{ doc.number|escapejs }}?')">Reverse document</button></form>{% endif %}
  </div>
</div>
{% if doc.note %}<p class="hint" style="margin-bottom:12px">{{ doc.note }}</p>{% endif %}

{% if outstanding %}
<div class="card" style="margin-bottom:14px;overflow:hidden"><div class="card-h"><span class="card-t">Outstanding</span></div>
  <div style="overflow:auto"><table class="led">
    <thead><tr><th>Pouch</th><th class="r">Pcs</th><th class="r">Carats</th>{% if 'pouch_value' in outstanding.0 %}<th class="r">Value</th>{% endif %}{% if can_settle %}<th>Settle</th>{% endif %}</tr></thead>
    <tbody>{% for o in outstanding %}<tr>
      <td class="mono"><a href="{% url 'inventory:movements' o.ref %}">{{ o.pouch }}</a></td>
      <td class="r">{{ o.pcs|default_if_none:"—" }}</td><td class="r">{{ o.ct|ct }}</td>
      {% if 'pouch_value' in o %}<td class="r">{{ o.pouch_value|rupees }}</td>{% endif %}
      {% if can_settle %}<td><form method="post" action="{% url 'inventory:document_settle' doc.pk %}" class="ctrow">{% csrf_token %}
        <input type="hidden" name="pouch" value="{{ o.pk }}">
        <select class="inp" name="how" style="width:140px">{% for value, label in choices %}<option value="{{ value }}">{{ label }}</option>{% endfor %}</select>
        <input class="inp tnum" name="pcs" placeholder="pcs" inputmode="numeric" style="width:70px"{% if not o.countable %} disabled{% endif %}>
        <input class="inp tnum" name="ct" placeholder="ct" inputmode="decimal" style="width:80px">
        <input class="inp" type="date" name="occurred_on" value="{{ today }}" style="width:150px">
        <button class="btn sm pri">Post</button></form></td>{% endif %}
    </tr>{% endfor %}</tbody></table></div></div>
{% endif %}

<div class="card" style="overflow:hidden"><div class="card-h"><span class="card-t">Movements</span><span class="spacer"></span><span class="hint">{{ moves|length }}</span></div>
  <div style="overflow:auto"><table class="led">
    <thead><tr><th>Date</th><th>Pouch</th><th>Reason</th><th>Dir</th><th class="r">Pcs</th><th class="r">Carats</th>
      {% if moves and 'purchase_rate' in moves.0 %}<th class="r">Cost / ct</th>{% endif %}<th>By</th></tr></thead>
    <tbody>{% for m in moves %}<tr>
      <td>{{ m.when|date:"d M Y" }}<div class="hint">{{ m.when|date:"H:i" }}</div></td>
      <td class="mono"><a href="{% url 'inventory:movements' m.ref %}">{{ m.pouch }}</a></td>
      <td><span class="chip">{{ m.reason }}</span>{% if m.reversal %}<div class="hint">↺ reversal</div>{% endif %}{% if m.note %}<div class="hint">{{ m.note }}</div>{% endif %}</td>
      <td class="dir {{ m.cls }}">{{ m.sym }}</td>
      <td class="r">{{ m.pcs|default_if_none:"—" }}</td><td class="r">{{ m.ct|ct }}</td>
      {% if 'purchase_rate' in m %}<td class="r">{{ m.purchase_rate|rupees }}</td>{% endif %}
      <td class="hint">{{ m.by }}</td></tr>
    {% empty %}<tr><td colspan="8" class="hint">No movements.</td></tr>{% endfor %}</tbody></table></div></div>
{% endblock %}
```

- [ ] **Step 5: Run the tests**

Run: `POSTGRES_DB=ledger_t10 .venv/bin/pytest inventory -p no:warnings`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add inventory/views_documents.py inventory/templates/inventory/document.html inventory/tests/test_document_view.py
git commit -m "$(cat <<'EOF'
A page per document: what moved, what is still out, settle, undo the last entry, reverse

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Job work out, Memo out, the rail's Movements, and the shelf's "Out" figure

**Files:**
- Replace: `inventory/views_lists.py` (the Task 2 stub)
- Create: `inventory/templates/inventory/out_list.html`, `inventory/templates/inventory/recent.html`, `inventory/tests/test_ledger_lists.py`
- Modify: `inventory/rows.py` (`out_tile`), `inventory/views.py` (one line in `shelf`), `inventory/templates/inventory/_totals.html`, `inventory/templates/inventory/_rail.html`

**Interfaces:**
- Consumes: `ledger.party/owed_by_document/out_summary/ZERO`; `views._client/_everything/_page`; URL names from Task 2.
- Produces: `views_lists.job_work_list(request)` (inv_job), `views_lists.memo_list(request)` (inv_move) — open by default, `?closed=1` shows closed and reversed; `views_lists.recent(request)` (every internal login; `?kind=`); `rows.out_tile(user) -> {"out_ct", "documents", "pouch_value"?}`; rail links for Purchases, Movements, Job work out, Memo out.

- [ ] **Step 1: Write the failing tests**

`inventory/tests/test_ledger_lists.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from inventory import ledger_jobs, ledger_single
from inventory.models import Movement
from inventory.tests.conftest import CUSTOMER, KARIGAR

pytestmark = pytest.mark.django_db
D = Decimal


def _get(client, user, name, query=""):
    client.force_login(user)
    return client.get(reverse(name) + query)


def test_job_work_out_lists_open_challans_with_an_overdue_chip(client, accounts_user, shelf, parties):
    today = date.today()
    ledger_jobs.job_work_out(accounts_user, shelf["onyx"], parties["karigar"], "2026/0417", 6, D("4"),
                             occurred_on=today - timedelta(days=10), expected_back=today - timedelta(days=3))
    done = ledger_jobs.job_work_out(accounts_user, shelf["ruby"], parties["karigar"], "2026/0418", None, D("5"))
    ledger_jobs.settle_job_work(accounts_user, done, shelf["ruby"], "in", None, D("5"))
    body = _get(client, accounts_user, "inventory:job_work_list").content.decode()
    assert "Job work out" in body and "Challan no." in body and "2026/0417" in body and KARIGAR in body
    assert "overdue" in body and "₹31,676" in body and "2026/0418" not in body       # 4 ct × ₹7,919 still out
    closed = _get(client, accounts_user, "inventory:job_work_list", "?closed=1").content.decode()
    assert "2026/0418" in closed and "Closed" in closed


def test_the_job_work_list_is_for_those_who_post_job_work(client, sales_user, production_user, shelf):
    assert _get(client, sales_user, "inventory:job_work_list").status_code == 403
    assert _get(client, production_user, "inventory:job_work_list").status_code == 200


def test_production_sees_karigars_but_no_value(client, admin_user_, production_user, shelf, parties):
    ledger_jobs.job_work_out(admin_user_, shelf["onyx"], parties["karigar"], "2026/0417", 6, D("4"))
    body = _get(client, production_user, "inventory:job_work_list").content.decode()
    assert KARIGAR in body and "31,676" not in body and "Value</th>" not in body


def test_memo_out_is_for_those_who_record_movements(client, accounts_user, karigar_user, shelf, parties):
    ledger_jobs.memo_out(accounts_user, shelf["ruby"], parties["customer"], "MEMO-0088", None, D("5"))
    body = _get(client, accounts_user, "inventory:memo_list").content.decode()
    assert "Memo out" in body and "Memo no." in body and "MEMO-0088" in body and CUSTOMER in body
    assert _get(client, karigar_user, "inventory:memo_list").status_code == 403


def test_recent_lists_documents_newest_first_and_filters_by_kind(client, accounts_user, shelf, parties):
    ledger_jobs.job_work_out(accounts_user, shelf["onyx"], parties["karigar"], "2026/0431", 1, D("1"))
    ledger_single.post_single(accounts_user, shelf["ruby"], Movement.Reason.BREAKAGE, None, D("1"))
    body = _get(client, accounts_user, "inventory:recent").content.decode()
    assert body.index("MOV-000001") < body.index("2026/0431")
    only = _get(client, accounts_user, "inventory:recent", "?kind=job_work").content.decode()
    assert "2026/0431" in only and "MOV-000001" not in only


def test_the_shelf_shows_what_is_out(client, accounts_user, sales_user, shelf, parties):
    ledger_jobs.job_work_out(accounts_user, shelf["onyx"], parties["karigar"], "2026/0431", 6, D("4"))
    body = _get(client, accounts_user, "inventory:shelf").content.decode()
    assert "Out on job work / memo" in body and "₹31,676" in body and "4.00 ct on 1 open document" in body
    body = _get(client, sales_user, "inventory:shelf").content.decode()
    assert "Out on job work / memo" in body and "4.00 ct on 1 open document" in body and "31,676" not in body


def test_the_rail_opens_the_ledger_screens_by_right(client, accounts_user, karigar_user, shelf):
    urls = {name: reverse(f"inventory:{name}") for name in ("purchase", "recent", "job_work_list", "memo_list")}
    body = _get(client, accounts_user, "inventory:shelf").content.decode()
    assert all(f'href="{url}"' in body for url in urls.values())
    assert 'Stock takes<span class="ct">🔒' in body and 'Transfers<span class="ct">🔒' in body
    body = _get(client, karigar_user, "inventory:shelf").content.decode()
    assert f'href="{urls["job_work_list"]}"' in body and f'href="{urls["recent"]}"' in body
    assert f'href="{urls["memo_list"]}"' not in body and f'href="{urls["purchase"]}"' not in body


def test_client_view_reaches_no_list(client, admin_user_, shelf):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    for name in ("inventory:job_work_list", "inventory:memo_list", "inventory:recent"):
        assert client.get(reverse(name)).status_code == 302, name
```

- [ ] **Step 2: Run them to see them fail**

Run: `POSTGRES_DB=ledger_t11 .venv/bin/pytest inventory/tests/test_ledger_lists.py -p no:warnings`
Expected: FAIL — the routes answer 404 (the stubs) and the shelf has no "Out" tile.

- [ ] **Step 3: Write `inventory/views_lists.py`** (replacing the stub)

```python
"""The rail's ledger lists: what is out on job work, what is out on memo, and recent documents."""
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import redirect
from django.utils import timezone

from accounts.capabilities import INV_JOB, INV_MOVE
from stock.masking import mask
from stock.services import require

from . import ledger
from .models import Movement, StockDocument
from .views import _client, _everything, _page

Kind, Status = StockDocument.Kind, StockDocument.Status
TONE = {Status.OPEN: "warn", Status.CLOSED: "good", Status.REVERSED: "crit"}
RECENT_CAP = 100


def _out_rows(user, documents):
    """One masked row per document: what went out, what is still out, and what that is worth."""
    documents = list(documents.select_related("vendor", "customer").prefetch_related("movements"))
    owed = ledger.owed_by_document(documents)
    today = timezone.localdate()
    rows = []
    for d in documents:
        sent_pcs, sent_ct = 0, ledger.ZERO
        for m in d.movements.all():
            if m.direction == Movement.OUT:
                sign = -1 if m.reverses_id else 1
                sent_pcs += sign * (m.pcs or 0)
                sent_ct += sign * (m.ct or 0)
        lines = owed.get(d.pk, []) if d.status == Status.OPEN else []
        rows.append(mask(user, {
            "pk": d.pk, "number": d.number, **ledger.party(d), "occurred_on": d.occurred_on,
            "expected_back": d.expected_back, "status": d.get_status_display(), "tone": TONE[d.status],
            "open": d.status == Status.OPEN,
            "overdue": d.status == Status.OPEN and d.expected_back is not None and d.expected_back < today,
            "sent_pcs": sent_pcs, "sent_ct": sent_ct,
            "owed_pcs": sum(pcs for _, pcs, _ in lines), "owed_ct": sum((ct for _, _, ct in lines), ledger.ZERO),
            "pouch_value": sum((ct * p.rate for p, _, ct in lines if p.rate is not None), ledger.ZERO),
        }))
    return rows


def _out_list(request, kind, right, title, party_label, number_label, tab):
    if _client(request):
        return redirect("inventory:shelf")
    require(request.user, right, f"The {title} list is not yours to see.")
    closed = request.GET.get("closed") == "1"
    documents = StockDocument.objects.filter(kind=kind, reverses__isnull=True).order_by("-occurred_on", "-pk")
    if not closed:
        documents = documents.filter(status=Status.OPEN)
    return _page(request, "inventory/out_list.html", _everything(request), tab=tab, title=title,
                 party_label=party_label, number_label=number_label, closed=closed,
                 rows=_out_rows(request.user, documents), money=mask(request.user, {"pouch_value": None}))


@login_required
def job_work_list(request):
    return _out_list(request, Kind.JOB_WORK, INV_JOB, "Job work out", "Karigar", "Challan no.", "job_work")


@login_required
def memo_list(request):
    return _out_list(request, Kind.MEMO, INV_MOVE, "Memo out", "Customer", "Memo no.", "memo")


@login_required
def recent(request):
    """Recent documents across every pouch, newest first.

    ponytail: the newest 100; page through when someone asks for more.
    """
    if _client(request):
        return redirect("inventory:shelf")
    kind = request.GET.get("kind", "")
    documents = StockDocument.objects.select_related("vendor", "customer").annotate(lines=Count("movements"))
    if kind in Kind.values:
        documents = documents.filter(kind=kind)
    rows = [mask(request.user, {"pk": d.pk, "number": d.number, "kind": d.get_kind_display(), **ledger.party(d),
                                "occurred_on": d.occurred_on, "status": d.get_status_display(),
                                "tone": TONE[d.status], "lines": d.lines})
            for d in documents.order_by("-created_at", "-pk")[:RECENT_CAP]]
    return _page(request, "inventory/recent.html", _everything(request), tab="recent", rows=rows, kind=kind,
                 kinds=Kind.choices)
```

- [ ] **Step 4: Write `inventory/templates/inventory/out_list.html`**

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}{{ title }}{% endblock %}
{% block crumb %}Stock control &nbsp;›&nbsp; <b>{{ title }}</b>{% endblock %}
{% block content %}
<div class="shelfbar"><h1>{{ title }}</h1><span class="spacer"></span>
  {% if closed %}<a class="chip" href="?">Open only</a>{% else %}<a class="chip" href="?closed=1">Show closed</a>{% endif %}</div>
<div class="card" style="overflow:hidden"><div style="overflow:auto"><table class="led">
  <thead><tr><th>{{ number_label }}</th><th>{{ party_label }}</th><th>Date</th><th>Expected back</th>
    <th class="r">Pcs out</th><th class="r">Carats out</th><th class="r">Outstanding</th>
    {% if 'pouch_value' in money %}<th class="r">Value</th>{% endif %}<th>Status</th></tr></thead>
  <tbody>{% for d in rows %}<tr>
    <td class="mono"><a href="{% url 'inventory:document' d.pk %}"><b>{{ d.number }}</b></a></td>
    <td>{% if 'karigar_name' in d %}{{ d.karigar_name }}{% elif 'customer_name' in d %}{{ d.customer_name }}{% else %}<span class="hint">—</span>{% endif %}</td>
    <td>{{ d.occurred_on|date:"d M Y" }}</td>
    <td>{{ d.expected_back|date:"d M Y"|default:"—" }}{% if d.overdue %} <span class="chip crit"><span class="dot"></span>overdue</span>{% endif %}</td>
    <td class="r">{{ d.sent_pcs|default:"—" }}</td><td class="r">{{ d.sent_ct|ct }}</td>
    <td class="r">{% if d.open %}{{ d.owed_ct|ct }} ct{% if d.owed_pcs %}<div class="hint">{{ d.owed_pcs }} pcs</div>{% endif %}{% else %}—{% endif %}</td>
    {% if 'pouch_value' in d %}<td class="r">{% if d.open %}{{ d.pouch_value|rupees }}{% else %}—{% endif %}</td>{% endif %}
    <td><span class="chip {{ d.tone }}"><span class="dot"></span>{{ d.status }}</span></td></tr>
  {% empty %}<tr><td colspan="9" class="hint">Nothing {% if closed %}here{% else %}out{% endif %}.</td></tr>{% endfor %}</tbody></table></div></div>
{% endblock %}
```

- [ ] **Step 5: Write `inventory/templates/inventory/recent.html`**

```django
{% extends "inventory_base.html" %}{% load inventory_extras %}
{% block title %}Movements{% endblock %}
{% block crumb %}Stock control &nbsp;›&nbsp; <b>Movements</b>{% endblock %}
{% block content %}
<div class="shelfbar"><h1>Movements</h1><span class="spacer"></span>
  <form method="get"><select class="chip" name="kind" onchange="this.form.submit()"><option value="">All kinds ▾</option>
    {% for value, label in kinds %}<option value="{{ value }}"{% if value == kind %} selected{% endif %}>{{ label }}</option>{% endfor %}</select></form></div>
<div class="card" style="overflow:hidden"><div style="overflow:auto"><table class="led">
  <thead><tr><th>Date</th><th>Document</th><th>Kind</th><th>Counterparty</th><th class="r">Lines</th><th>Status</th></tr></thead>
  <tbody>{% for d in rows %}<tr>
    <td>{{ d.occurred_on|date:"d M Y" }}</td>
    <td class="mono"><a href="{% url 'inventory:document' d.pk %}"><b>{{ d.number }}</b></a></td>
    <td>{{ d.kind }}</td>
    <td>{% if 'karigar_name' in d %}{{ d.karigar_name }}{% elif 'customer_name' in d %}{{ d.customer_name }}{% elif 'vendor_name' in d %}{{ d.vendor_name }}{% else %}<span class="hint">—</span>{% endif %}</td>
    <td class="r">{{ d.lines }}</td>
    <td><span class="chip {{ d.tone }}"><span class="dot"></span>{{ d.status }}</span></td></tr>
  {% empty %}<tr><td colspan="6" class="hint">No documents yet.</td></tr>{% endfor %}</tbody></table></div></div>
{% endblock %}
```

- [ ] **Step 6: The shelf's "Out on job work / memo" figure**

`inventory/rows.py` — import the ledger and add `out_tile`:

```python
from . import ledger, rules, services
```

```python
def out_tile(user):
    """The shelf's "Out on job work / memo": carats on open documents, and their value
    under the stock value's own gate."""
    summary = ledger.out_summary()
    return mask(user, {"out_ct": summary["ct"], "documents": summary["documents"], "pouch_value": summary["value"]})
```

`inventory/views.py`, `shelf` — only the return line changes:

```python
    return _page(request, "inventory/shelf.html", everything, tab="shelf", colours=rows.by_colour(everything),
                 out=None if _client(request) else rows.out_tile(request.user))
```

`inventory/templates/inventory/_totals.html` — the strip lets a fifth tile fit, and the tile sits beside Stock value:

```django
{% load inventory_extras %}{% if not client_view %}
<div class="totstrip" style="grid-template-columns:repeat(auto-fit,minmax(170px,1fr))">
  {% if 'value' in rail %}<div class="tot heroTot"><div class="l">Stock value</div><div class="v">{{ rail.value|rupees }}</div><div class="f">weight in carats × rate</div></div>{% endif %}
  {% if out %}<div class="tot"><div class="l">Out on job work / memo</div>
    <div class="v">{% if 'pouch_value' in out %}{{ out.pouch_value|rupees }}{% else %}{{ out.out_ct|ct }} ct{% endif %}</div>
    <div class="f">{{ out.out_ct|ct }} ct on {{ out.documents }} open document{{ out.documents|pluralize }}</div></div>{% endif %}
  <div class="tot"><div class="l">Total weight</div><div class="v">{{ rail.ct|ct }} ct</div><div class="f">{{ rail.ct|kg }} kg</div></div>
  <div class="tot"><div class="l">Pouches</div><div class="v">{{ rail.pouches|grouped }}</div><div class="f">{{ rail.batches|grouped }} batches · {{ rail.colours }} box colours</div></div>
  {% if 'unpriced' in rail %}<div class="tot"><div class="l">Not yet valued</div><div class="v">{{ rail.unpriced|grouped }}</div><div class="f">no weight or no rate</div></div>{% endif %}
</div>
{% if rail.no_pouch_no or rail.no_size %}
<div class="banner warn"><div class="banner-ic">!</div><div>
  <h4>{{ rail.no_pouch_no|grouped }} pouches have no pouch number, and {{ rail.no_size|grouped }} have no size in mm</h4>
  <p>Batch + pouch number keys {{ rail.keyed|grouped }} of {{ rail.pouches|grouped }} pouches.</p></div></div>
{% endif %}
{% endif %}
```

(The colour and batch pages include `_totals.html` without `out`, so the tile shows on the shelf only.)

- [ ] **Step 7: Unlock the rail**

`inventory/templates/inventory/_rail.html` — replace the Stock control `<nav>` with:

```django
<nav class="nav">
  {% if caps.inv_masters %}<a class="{% if tab == 'import' %}on{% endif %}" href="{% url 'inventory:import_home' %}"><span class="ic">⇅</span>Import stones</a>{% endif %}
  {% if caps.inv_purchase %}<a class="{% if tab == 'purchase' %}on{% endif %}" href="{% url 'inventory:purchase' %}"><span class="ic">＋</span>Purchases</a>
  {% else %}<span class="locked"><span class="ic">＋</span>Purchases<span class="ct">🔒</span></span>{% endif %}
  <a class="{% if tab == 'recent' %}on{% endif %}" href="{% url 'inventory:recent' %}"><span class="ic">⇄</span>Movements</a>
  {% if caps.inv_job %}<a class="{% if tab == 'job_work' %}on{% endif %}" href="{% url 'inventory:job_work_list' %}"><span class="ic">↗</span>Job work out</a>
  {% else %}<span class="locked"><span class="ic">↗</span>Job work out<span class="ct">🔒</span></span>{% endif %}
  {% if caps.inv_move %}<a class="{% if tab == 'memo' %}on{% endif %}" href="{% url 'inventory:memo_list' %}"><span class="ic">↘</span>Memo out</a>
  {% else %}<span class="locked"><span class="ic">↘</span>Memo out<span class="ct">🔒</span></span>{% endif %}
  <span class="locked"><span class="ic">⊙</span>Stock takes<span class="ct">🔒</span></span>
  <span class="locked"><span class="ic">⤴</span>Splits &amp; merges<span class="ct">🔒</span></span>
  <span class="locked"><span class="ic">⇉</span>Transfers<span class="ct">🔒</span></span>
</nav>
```

- [ ] **Step 8: Run the tests**

Run: `POSTGRES_DB=ledger_t11 .venv/bin/pytest inventory -p no:warnings`
Expected: PASS — including `test_views.py` (the shelf's totals) and the client-view walk (the tile is inside `{% if not client_view %}`).

- [ ] **Step 9: Commit**

```bash
git add inventory/views_lists.py inventory/rows.py inventory/views.py inventory/templates/inventory/out_list.html \
  inventory/templates/inventory/recent.html inventory/templates/inventory/_totals.html \
  inventory/templates/inventory/_rail.html inventory/tests/test_ledger_lists.py
git commit -m "$(cat <<'EOF'
Job work out and Memo out lists, the rail's Movements, and what is out on the shelf

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---
### Task 12: The masking walk covers every ledger screen and write, and the spec records the plan's decisions

**Files:**
- Modify: `inventory/tests/test_masking.py`, `inventory/tests/conftest.py`, `docs/superpowers/specs/2026-10-01-inventory-stones-ledger-design.md`

**Interfaces:**
- Consumes: every `inventory:` ledger URL name; `ledger_jobs.job_work_out/memo_out`; `ledger_purchase.post_purchase/PurchaseHeader/PurchaseLine`; fixtures `shelf`, `parties`.
- Produces: fixture `ledger_docs` → `shelf | parties | {"job", "memo", "purchase", "bought"}`; constant `PURCHASE_COST = "4,321"`; `PENDING` is gone.

- [ ] **Step 1: A document of each kind a name or a cost can leak from**

Append to `inventory/tests/conftest.py`:

```python
#: the purchase's cost per carat, findable in a body and nowhere else
PURCHASE_COST = "4,321"


@pytest.fixture
def ledger_docs(admin_user_, shelf, parties):
    """A job work (karigar), a memo (customer) and a purchase (supplier, cost) on the shelf."""
    from datetime import date

    from inventory import ledger_jobs
    from inventory.ledger_purchase import PurchaseHeader, PurchaseLine, post_purchase

    job = ledger_jobs.job_work_out(admin_user_, shelf["onyx"], parties["karigar"], "2026/0431", 2, Decimal("1"))
    memo = ledger_jobs.memo_out(admin_user_, shelf["ruby"], parties["customer"], "MEMO-0088", None, Decimal("5"))
    purchase = post_purchase(
        admin_user_, PurchaseHeader(supplier=shelf["supplier"], occurred_on=date(2026, 8, 7), invoice_no="2026/0442"),
        [PurchaseLine(batch=shelf["batch"], pouch_no="3", stone_name="Tanzanite", shape="Oval", colour="Blue",
                      pcs=6, ct=Decimal("3"), cost_per_ct=Decimal("4321"))],
    )
    return {**shelf, **parties, "job": job, "memo": memo, "purchase": purchase,
            "bought": purchase.movements.get().pouch}
```

- [ ] **Step 2: Extend the walk**

In `inventory/tests/test_masking.py`:

1. The imports:

```python
from inventory.models import Movement
from inventory.tests.conftest import (
    CUSTOMER, DIA_COST, DIA_COST_VALUE, DIA_SALE, DIA_SALE_VALUE, DIA_SUPPLIER, KARIGAR, PURCHASE_COST, SUPPLIER, VALUE,
)
```

2. Add to `EXEMPT`:

```python
    # ledger writes: POST-only; each refuses a login without its right (403), asserted in
    # test_the_ledger_writes_refuse_a_login_without_the_right below
    "inventory:movement_post", "inventory:document_settle", "inventory:document_undo", "inventory:document_reverse",
```

3. Delete `PENDING`, and in `test_every_inventory_screen_is_walked`:

```python
    covered = {name for name, _, _ in SCREENS} | {name for name, _ in DIAMOND_SCREENS} | LEDGER_SCREENS
```

```python
    missing = named - covered - EXEMPT
```

4. Add the ledger walk:

```python
#: the ledger's screens, walked by test_no_ledger_screen_shows_a_login_what_it_may_not_see
LEDGER_SCREENS = {"inventory:document", "inventory:job_work_list", "inventory:memo_list", "inventory:recent",
                  "inventory:purchase", "inventory:split", "inventory:transfer"}


def _ledger_urls(d):
    """Every ledger screen, plus the shelf, pouch and movements pages the documents now show on."""
    return [
        reverse("inventory:movements", args=[d["onyx"].ref]), reverse("inventory:movements", args=[d["ruby"].ref]),
        reverse("inventory:movements", args=[d["bought"].ref]),
        reverse("inventory:document", args=[d["job"].pk]), reverse("inventory:document", args=[d["memo"].pk]),
        reverse("inventory:document", args=[d["purchase"].pk]),
        reverse("inventory:job_work_list"), reverse("inventory:job_work_list") + "?closed=1",
        reverse("inventory:memo_list"), reverse("inventory:memo_list") + "?closed=1",
        reverse("inventory:recent"), reverse("inventory:recent") + "?kind=job_work",
        reverse("inventory:purchase"),
        reverse("inventory:split", args=[d["onyx"].ref]), reverse("inventory:transfer", args=[d["onyx"].ref]),
        reverse("inventory:shelf"), reverse("inventory:pouch", args=[d["bought"].ref]),
    ]


@pytest.mark.parametrize("fixture, secrets", [
    ("sales_user", ("7,919", PURCHASE_COST, SUPPLIER, KARIGAR)),
    ("karigar_user", ("7,919", PURCHASE_COST, SUPPLIER, CUSTOMER)),
    ("production_user", ("7,919", PURCHASE_COST, CUSTOMER)),
    ("graphic_user", ("7,919", PURCHASE_COST, SUPPLIER, KARIGAR, CUSTOMER)),
])
def test_no_ledger_screen_shows_a_login_what_it_may_not_see(client, ledger_docs, request, fixture, secrets):
    client.force_login(request.getfixturevalue(fixture))
    for url in _ledger_urls(ledger_docs):
        response = client.get(url)
        assert response.status_code in (200, 403), f"{url} returned {response.status_code}"
        body = response.content.decode()
        for secret in secrets:
            assert secret not in body, f"{url} leaked {secret!r} to {fixture}"


def test_each_name_and_cost_reaches_those_who_may_see_it(client, ledger_docs, accounts_user, karigar_user, sales_user):
    def body(user, doc):
        client.force_login(user)
        return client.get(reverse("inventory:document", args=[ledger_docs[doc].pk])).content.decode()

    assert KARIGAR in body(karigar_user, "job")
    assert CUSTOMER in body(sales_user, "memo")
    assert KARIGAR in body(accounts_user, "job") and "₹7,919" in body(accounts_user, "job")
    assert CUSTOMER in body(accounts_user, "memo")
    purchase = body(accounts_user, "purchase")
    assert PURCHASE_COST in purchase and SUPPLIER in purchase
    assert "Out on job work / memo" in client.get(reverse("inventory:shelf")).content.decode()


def test_client_view_reaches_no_ledger_screen_or_write(client, admin_user_, ledger_docs):
    client.force_login(admin_user_)
    client.post(reverse("inventory:set_view"), {"view": "client"})
    d = ledger_docs
    client_screens = {reverse("inventory:shelf"), reverse("inventory:pouch", args=[d["bought"].ref])}
    for url in _ledger_urls(d):
        if url not in client_screens:
            assert client.get(url).status_code == 302, url
    for url in (reverse("inventory:movement_post", args=[d["onyx"].ref]),
                reverse("inventory:document_settle", args=[d["job"].pk]),
                reverse("inventory:document_undo", args=[d["job"].pk]),
                reverse("inventory:document_reverse", args=[d["job"].pk])):
        assert client.post(url, {"reason": "Sale", "ct": "1"}).status_code == 302, url
    for url in client_screens:
        body = client.get(url).content.decode()
        for secret in (KARIGAR, CUSTOMER, SUPPLIER, "2026/0431", "MEMO-0088", "2026/0442"):
            assert secret not in body, f"{url} sent {secret!r} in client view"


def test_the_ledger_writes_refuse_a_login_without_the_right(client, sales_user, ledger_docs):
    d = ledger_docs
    client.force_login(sales_user)
    before = Movement.objects.count()
    for url, data in [
        (reverse("inventory:movement_post", args=[d["onyx"].ref]), {"reason": "Sale", "ct": "1"}),
        (reverse("inventory:document_settle", args=[d["job"].pk]), {"pouch": d["onyx"].pk, "how": "in", "ct": "1"}),
        (reverse("inventory:document_undo", args=[d["job"].pk]), {}),
        (reverse("inventory:document_reverse", args=[d["purchase"].pk]), {}),
        (reverse("inventory:purchase"), {"supplier": d["supplier"].pk}),
        (reverse("inventory:split", args=[d["onyx"].ref]), {"out_ct": "1", "pouch_no": "9", "ct": "1"}),
        (reverse("inventory:transfer", args=[d["onyx"].ref]), {"batch": "SL01G", "pouch_no": "9"}),
    ]:
        assert client.post(url, data).status_code == 403, url
    assert Movement.objects.count() == before
```

- [ ] **Step 3: Run the walk**

Run: `POSTGRES_DB=ledger_t12 .venv/bin/pytest inventory/tests/test_masking.py -p no:warnings`
Expected: PASS. A leak names the screen and the value: fix it with a key test in the template or a `mask()` in the row, never a capability test.

- [ ] **Step 4: Record the planning decisions in the spec**

Append to `docs/superpowers/specs/2026-10-01-inventory-stones-ledger-design.md`:

```markdown
## Changed while planning

- **Single documents are numbered `MOV-…`.** A sale's invoice no. (and a return's reference) stays on the movement, because one invoice may cover several pouches and a document's number is unique per kind. A purchase with no invoice no. is numbered `PUR-…`.
- **A reversal is its own document** — the same kind, numbered `REV-…`, `reverses` set, closed when posted; the original becomes Reversed and its number is free again. A reversal cannot itself be reversed. **Undo last entry** posts its reversing movement on the same open document.
- **A split takes an explicit "Take out" quantity** (the whole balance by default); the parent keeps the rest. The loss posts as a Wastage / Loss in Process out on the parent; the Split out carries only what went into new pouches. New pouches also copy category, treatment, origin, purchase date and countability.
- **A transfer keeps its from and to on the document** (`from_batch`, `from_pouch_no`, `to_batch`, `to_pouch_no`), so reversing it files the pouch back — refused if it has been re-filed since or its old number is taken. An empty pouch cannot be transferred.
- **A purchase files into an existing batch** and needs the purchase right with sight of cost and suppliers; "＋ New supplier…" uses Settings' supplier save (Edit settings right). Landed valuation = cost per ct in INR + extras ÷ the purchase's total carats, both rows dated the purchase date.
- **A document's customer is SET_NULL**, as `stock.Sale`'s is, so the CRM can still delete a customer.
- **Karigar names are gated as `karigar_name` (inv_job), customer names as `customer_name` (view_sale).** A login without sight of suppliers is offered as karigars only those already named on a challan, so the Karigar desk never sees a supplier list.
- **The document page and the rail's Movements are readable by every internal login, masked;** the Job work out list needs Job cards, the Memo out list needs Record stock movements.
- **On Record movement**, Consumed in Production and Wastage / Loss in Process settle a chosen challan (Job cards right), else post from the shelf (Record stock movements right); Sale settles a chosen memo, else is a direct sale. Recount Adjustment there needs Record stock movements; the importer's recount keeps Edit settings, and both share one difference rule.
- **A back-dated movement is stamped noon of its day;** expected back may not precede the date.
- **Undoing the only entry of a job work or memo leaves it closed at zero.**
- **Values out on documents** (shelf tile, lists) sum the valued pouches, as Stock value does.
```

- [ ] **Step 5: Run the whole suite**

Run: `POSTGRES_DB=ledger_t12 .venv/bin/pytest -p no:warnings` — Expected: only the known pre-existing S3 failure; the stones parity/golden tests unchanged.
Run: `POSTGRES_DB=ledger_t12 .venv/bin/python manage.py makemigrations --check --dry-run` — Expected: `No changes detected`.

- [ ] **Step 6: Commit**

```bash
git add inventory/tests/test_masking.py inventory/tests/conftest.py docs/superpowers/specs/2026-10-01-inventory-stones-ledger-design.md
git commit -m "$(cat <<'EOF'
Walk every ledger screen and write as every role and in client view, and record the plan's decisions

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Decided while planning

The spec did not pin these down; Task 12 records them in the spec.

1. **Single documents are numbered `MOV-000001`**, not by invoice no.: one invoice may cover several pouches and a document's number is unique per kind, so a sale's invoice no. (or a return's reference) is kept on the movement's `ref`. A purchase with a blank invoice no. is `PUR-000001`.
2. **A reversal is a new document** of the same kind, numbered `REV-000001`, with `reverses` set and closed on post; the original becomes Reversed (freeing its number). A reversal cannot itself be reversed. **Undo last entry** posts its reversing movement on the same open document; undoing the only entry leaves the document closed at zero.
3. **Split has a "Take out" quantity** (pieces and carats, defaulting to the whole balance) as the assortment's debit; the parent keeps the rest. The loss is a Wastage / Loss in Process out on the parent; the Split out carries what went into new pouches. New pouches also copy category, treatment, origin, purchase date and countability (beyond the spec's seven); size and remarks are typed per row (size prefilled from the parent).
4. **Transfers store `from_batch`, `from_pouch_no`, `to_batch`, `to_pouch_no` on the document**, so a reversal can re-file the pouch (refused if re-filed since or the old number is taken). The Transfer movement's note carries `SL01G · 1 → SP14B · 3`. An empty pouch is not transferable (the movement needs a quantity).
5. **Purchase lines file into existing batches only** (new batches still come from the importer). The screen needs `inv_purchase` + `view_cost` + `view_vendor` (`PURCHASE_RIGHTS`); the service enforces `inv_purchase` + `view_cost` as the spec says. "＋ New supplier…" calls `dia_services.save_supplier` (needs `inv_masters`) inside the purchase's transaction.
6. **Landed valuation** = cost per ct × fx (INR) + landed extras ÷ total carats of the purchase, rounded to 4 places; purchase and valuation rows are dated the purchase date. USD with no rate, or any rate ≤ 0, is refused.
7. **`StockDocument.customer` is `SET_NULL`** (as `stock.Sale.customer`), so the CRM's customer delete is never blocked by a memo; `vendor` is `PROTECT` like the existing vendor links.
8. **Masking keys:** `karigar_name` → `inv_job`, `customer_name` → `view_sale`, added to `stock/masking.py`; landed extras use `cost_amount`, values out use `pouch_value`, a purchase's cost uses `purchase_rate`. The karigar dropdown shows every supplier only to a login with `view_vendor`; otherwise only vendors already named on a challan, so the Karigar desk never sees a supplier list.
9. **Who reads what:** the document page and the rail's Movements are readable by every internal login (masked; actions gated by the kind's right); Job work out needs `inv_job`, Memo out needs `inv_move` (the spec's table).
10. **Record movement routing:** Consumed in Production and Wastage / Loss in Process settle a chosen open challan (`inv_job`), else post from the shelf (`inv_move`); Sale settles a chosen open memo, else is a direct sale. Purchase is offered only with all of `PURCHASE_RIGHTS`; Transfer with `inv_assort`. A reason not offered is a 403 on POST.
11. **Recount Adjustment on the form needs `inv_move`** (the spec's table) and posts on a Single document; the importer's `services.recount` keeps `inv_masters` and no document. Both use one `services.recount_deltas`.
12. **Time of a movement:** now when dated today, else noon of the date given; settle entries take their own date, not the document's. Expected back may not precede the date.
13. **Number uniqueness** is a partial unique index on `(kind, number)` excluding reversed documents, plus a friendly service check; automatic numbers are read-the-max under the transaction (the existing `NRN-` approach).
14. **Values out** (shelf tile, list rows, document page) sum ct × current valuation rate over valued pouches; an unvalued pouch adds nothing (as Stock value does). The shelf tile shows on the shelf only, not on colour or batch pages.
15. **Parallel build:** Task 2 routes every ledger URL to `Http404` stubs in the modules wave 4 fills and lists them as `PENDING` in the every-screen check (Task 12 removes it), so screens link to each other while built in parallel and no wave-4 task edits `urls.py`.
16. **No rail counts** for Purchases, Movements, Job work out or Memo out (the prototype's badges); the rail links by right and stays padlocked otherwise.
