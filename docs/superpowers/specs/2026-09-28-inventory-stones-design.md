# Inventory part 1: foundation + stones screens — design

**Date:** 2026-09-28
**Status:** design agreed section by section; awaiting review of this document
**Overview and decisions:** `2026-09-28-inventory-overview.md`
**Source this was designed against:** `../Nornament_Inventory/04-source-scripts/_head.html` (markup +
CSS), `_script.html` lines 1–613 (stones logic), `build_ui.py` (loader), and the owner's stones
register `Nornament_Stones_Stock_Chetna_202627.xlsx` (sheets SP, PR, Mix, SR, SL; Googri and Jadau
excluded).

## Scope

**In:** the `inventory` app and its shell; box colour / batch / pouch models; the movement ledger
and price history; the stones importer; Shelf at three levels; Pouch detail with working Save, Add
price and photos; read-only Movements; the client view; roles, capabilities and masking.

**Out (padlocked, later parts):** the Diamonds switch; Record movement, Purchase, Split, Transfer
(part 2); Job work out, Memo out, Stock takes, Splits & merges, Price lists, Suppliers, Client
lookbook, the data-quality filters, the top search box, the Stock take tab (part 5).

## Data model

```
BoxColour   code PK (G, R, SB, F, RG…) · label · swatch hex · confirmed
CodePart    kind (family|class) · code (S/P/C, L/P/R/S/Z) · label · confirmed
Batch       code unique (SR01Y) · box_colour FK · family · cls · seq   ← parsed from the code
Pouch       ref unique, immutable (NRN-000001, assigned at creation)
            batch FK · pouch_no (text, nullable) · carton (Box No)
            category · stone_name · colour · shape · cut · quality     ← raw text, as typed
            size_text · size_kind (lw|dia|multi|free|none) · length_mm · width_mm
            countable · remarks · src ("SP!104") · import_batch FK
            treatment · origin · purchase_date · supplier → stock.Vendor
            UNIQUE(batch, pouch_no) WHERE pouch_no IS NOT NULL
Movement    pouch FK · occurred_at · reason · direction in|out
            pcs (null if uncountable) · ct · counterparty → stock.Vendor · challan_no · ref · note
            recorded_by · recorded_at                                   ← append-only
PriceEntry  pouch FK · kind (valuation|purchase|list) · rate per ct · effective_from · set_by
```

- Batch code grammar: `^([A-Z])([A-Z])(\d+)([A-Z]+)$` → family, class, sequence, box colour.
  Seeded labels: family S Stone, P Pearl, C CZ; class L Lab/Man-made, P Semi-Precious, R Real,
  S unconfirmed, Z Zirconia; box colours G R Y W M B T O P SB BK PR BR confirmed, BY F RG RC CM C
  unconfirmed.
- Movement reasons are the spec's 17 (`03-spec` §3.4 `MOVEMENT_REASON`). Part 1 writes only
  Opening Balance and Recount Adjustment.
- **On hand** pieces and carats are sums over the pouch's movements, annotated in the query.
  A pouch with `countable = false` moves by weight only; its pcs stay null.
- **Value** = carats on hand × the latest `valuation` rate. The sheet's `Price Per Carat / Pc` is
  written as the first valuation row, dated the import day, and displayed as "Rate on file".
  Add price appends a row; nothing is overwritten.
- `NRN-` refs come from a sequence at creation, never from row position.
- Reused, not duplicated: `stock.Vendor` (suppliers, counterparties), `mediahub.MediaAsset` with
  `scope="pouch"` and `scope_id=<pouch pk>` (filtered by scope, never by key prefix),
  `stock.ActivityLog` for every write, `stock.ImportBatch` with `source="STONES"`.

## Importer

`/inventory/import/`, the IVY importer's shape: `inventory/importers/stones.py` parses (a port of
`build_ui.py`'s loader, keeping every raw string), an analyse step builds a plan that writes
nothing, the review screen shows it, and commit runs in one transaction.

| Case in the sheet | Review behaviour |
|---|---|
| Duplicate batch + pouch no. (10 pairs today) | Blocks commit until a new pouch no. is typed |
| Batch code that does not parse (1 row, "Broken") | Blocks until corrected or skipped |
| No pouch no. (210) | Suggests the next free number in the batch (above the highest numeric pouch no.); accept or leave blank |
| No weight or no rate (48) | Imported; pouch shows "Cannot be valued" |
| Box colour code not in the table | Created unconfirmed |
| Blank Pcs | `countable = false` |

On commit each new pouch gets an Opening Balance movement (its pcs and ct) and a valuation row.

**Re-import** of an updated register matches pouches by batch + pouch no. Descriptive fields update;
a change in weight or pieces becomes a Recount Adjustment movement, listed in the review before it
posts. The sheet never overwrites a balance.

## Screens

Shell: `templates/inventory_base.html` + `static/css/inventory.css`, the CSS lifted verbatim from
`_head.html` and loaded only by inventory screens. Added on top: dark-mode tokens, the phone nav
drawer from `base.html`, and fixes for `.cons b{display:block}`, `<button>` cards centring their
content, and `.rt` inheriting a border. Rail, ◆/◇ switch, top bar and tab strip keep the prototype's
markup. The stock and CRM sidebars gain an "Inventory" link; this rail links back.

| URL | Screen |
|---|---|
| `/inventory/` | Shelf by box colour — 4 total tiles, gap banner, 19 colour cards sorted by value |
| `/inventory/stones/<colour>/` | Batch cards (silhouette, top stone names, family · class, value, ct, boxes, mismatch chip); first 40, `?all=1` shows all |
| `/inventory/stones/<colour>/<batch>/` | Batch-code strip, then pouches as grid or table (`?view=table`, with the Check column: colour → no pouch no. → unpriced → ok) |
| `/inventory/pouches/<ref>/` | Pouch detail |
| `/inventory/pouches/<ref>/movements/` | Balance panel, "where this pouch sits", the real ledger (read-only) |
| `/inventory/import/` | Upload → review → commit |

- The page title and the active tab follow the URL.
- Silhouettes: `_script.html`'s `shapeSVG` ported to a template tag. Round and mani shapes draw as
  circles (the prototype's first rule never matched plain "Round").
- Colour families: the prototype's ordered substring match (`fam()`), so "Pink Red" is Red. A pouch
  is misfiled when its family and its box colour are both known and differ; Blue ↔ Sea Blue agree;
  an unconfirmed box colour is never flagged.
- Pouch detail: value panel (share of batch 0 dp, of box colour 1 dp, of all stock 2 dp; "—%" at
  zero) or "Cannot be valued"; KPIs (weight, rate, size, pieces with average ct); Media card with
  silhouette placeholder and photo drop; batch-code card; The Record grouped as Where it lives /
  What it is / Size / Quantity & price / Treatment, origin, purchase date, supplier / Notes /
  Source row; Price history (Rate on file, pouch value, purchase, current valuation, list).
- Actions: **Save** (treatment, origin, purchase date, supplier), **＋ Add price** (kind, rate,
  date), **Drop photos here** (existing presigned upload, filed as `{batch}-{pouchNo|X}-01.jpg`),
  **⇄ Movements**. **⤴ Split pouch** padlocked until part 2.
- Treatment and origin options: `vocab.py`'s `TREATMENT` list and the prototype's origin list.
- Nav counts are live: box colours, batches, pouches, boxes, misfiled, no pouch no., unreadable
  code, missing photos, no size in mm.
- Formats: `₹` + whole rupees in Indian grouping; carats to 2 dp; kg = ct × 0.2 / 1000.
- Prose stripped. The gap banner keeps its facts only; functional warnings stay ("Cannot be
  valued", "Colour mismatch — check filing", the mismatch line on the batch-code card).

## Roles, masking, client view

- New capabilities in `accounts/capabilities.py`: `inv_masters` (save pouch fields, add price,
  import) used now; `inv_purchase`, `inv_job`, `inv_assort` declared for parts 2–4.
- New group **KARIGAR** ("Karigar desk"): `inv_job` only, no stock or CRM tabs.
- ADMIN all; ACCOUNTS all four; PRODUCTION `inv_job`; SALES and GRAPHIC none of the new ones.
- Tab `inv_stones` added to every role's `ROLE_TABS`; every inventory view uses `tab_required`, and
  every write checks its capability in the service (`ServiceError`).
- `GATED_FIELDS` gains `stone_rate`, `pouch_value`, `valuation_rate`, `purchase_rate` → `view_cost`;
  `list_rate` → `view_sale`; `supplier_name` → `view_vendor`. `inventory/rows.py` builds colour,
  batch and pouch rows and ends in `mask()`; templates render only surviving keys.
- **Client view:** the Internal / Client preview buttons POST a session flag (staff only; persists
  across navigation). In client mode the row builders also drop batch code, pouch no., carton, box
  colour, remarks, src, all rates and values, supplier and data-quality flags. The pouch shows its
  `NRN-` ref, "Available — enquire for price", and ✉ Enquire, which opens a new CRM enquiry carrying
  the ref (hook confirmed during planning).

## Errors

Service rules raise `ServiceError`, shown as a message: missing capability, duplicate batch +
pouch no., negative balance, rate ≤ 0. A blocked import cannot commit; commit is one transaction.
Photo uploads sit outside the transaction, as in the stock app.

## Testing

`inventory/tests/`, with the repo conventions (`pytestmark = django_db`, real role groups):

- `test_importer.py` — in-memory workbook with a duplicate key, a broken batch code, a missing pouch
  no., an uncountable pouch, a missing rate and a Googri sheet; review output, commit writes, and a
  re-import turning a weight change into a Recount Adjustment.
- `test_rules.py` — batch-code parsing, colour families (Blue ↔ Sea Blue), size kinds,
  value = ct × latest valuation.
- `test_views.py` — each screen for each role; Save and Add price refused without `inv_masters`.
- Masking — inventory screens added to the SALES walk in `stock/tests/test_masking.py`; no rate,
  value or supplier in any response.
- Client view — no batch code, carton, remarks, rate or `src` string in any client-mode response.
- Parity — a fixture rebuilt from the prototype's embedded data reproduces 2,916 pouches,
  ₹1,72,49,719 and 127 misfiled.
