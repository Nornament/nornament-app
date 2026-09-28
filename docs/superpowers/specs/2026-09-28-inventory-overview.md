# Raw-material inventory (stones + diamonds) — overview

**Date:** 2026-09-28
**Status:** decisions agreed; part 1 designed in `2026-09-28-inventory-stones-design.md`
**Source this was designed against:** `../Nornament_Inventory/` — the prototype
(`01-prototype/nornament-ui-mockup.html`, generated from `04-source-scripts/_head.html` +
`_script.html`), the schema spec v1.1 and its addendum (`03-spec/`), the build scripts, and the
stones fix workbook.

## Why

The business holds loose stones (2,916 pouches, ₹1.72 cr) and diamonds (348 lines, 673.90 ct) in
spreadsheets. A prototype was built showing how they should be browsed and controlled. It is a
clickable mockup: every screen renders from data baked into the page, and every Post / Save / Split /
Add button is inert. This work makes it real inside nornament-app.

## What the prototype is

- **Stones:** Shelf by box colour → batch (`SR01Y`) → pouch (1, 2, 3…), image-led with shape
  silhouettes painted the recorded colour; pouch detail; movements; purchase; an Internal ↔ Client
  preview toggle.
- **Diamonds (internal only):** Search stock with cascading bubble filters, Job cards and
  Assortments (debit/credit carat ledgers that must balance), Purchases, Settings (rights matrix,
  suppliers, masters, range → grade expansion). A role switcher removes cost/sale/margin columns.
- **Named but never built:** Job work out, Memo out, Stock takes, Splits & merges, Transfers, stone
  Suppliers, Client lookbook, Rate card, Price lists, the data-quality filters, search, the Stock take
  tab; no job-card creation, no Close, no karigar master.

## Decisions

| Question | Decision |
|---|---|
| What "replicate as is, miss nothing" means | Every screen the prototype renders is reproduced exactly and every control on it works. Items the prototype only names appear padlocked and become later sub-projects. |
| Fidelity | Same look, fixed behaviour. Fix: the client-view leak, the ungated top-bar Purchase tab, the Search "0 of 348" batch leak, swapped diamond codes, stale title / double-underlined tabs, positional `NRN-` refs, round stones drawn as ellipses. Add the app's dark mode and phone layout. |
| Explanatory prose | Stripped, as the rest of the app was in `da85ac7`. Layout, numbers and functional warnings stay. |
| Terminology | **Box colour → Batch (`SR01Y`) → Pouch (1, 2, 3)** — the prototype's words. Source columns: `New Gati Code` = batch, `Batch No.` = pouch no. |
| Source data | The owner supplies the originals (`Nornament_Stones_Stock_Chetna_202627.xlsx`, `DIAMOND 31.xlsx`); an upload → review → commit importer reads them. The prototype's embedded JSON is test fixture only. |
| Roles | Map onto the existing groups: Owner → ADMIN, Manager → ACCOUNTS, Sales → SALES, Stock staff → PRODUCTION, plus a new **KARIGAR** group. Cost/sale/margin reuse `view_cost`/`view_sale`/`view_margin`; new capabilities `inv_masters`, `inv_purchase`, `inv_job`, `inv_assort`. The prototype's "Viewing as" switcher becomes an admin-only preview. |
| Client view | Staff-only toggle to show stock on screen to a customer, rendered server-side so hidden fields never reach the browser. Shareable links / client logins are a later sub-project. |
| Diamond pricing | Cost per line, from its purchase. Sale from a rate card keyed on shape + quality + size, seeded from the IVY export's sale rates; existing lines take cost from IVY rates where the code matches, else "not set". |
| Link to finished pieces | Later. Leave the hook: job cards may reference a stock Piece/JobCard; a nullable lot link on `BomLine` comes in a later sub-project. |
| Architecture | A new Django app `inventory` with its own shell (`inventory_base.html`) and stylesheet (`inventory.css`, lifted verbatim from the prototype), HTMX for the live parts, reusing `Vendor`, `Location`, `MaterialCategory`, `mediahub`, `ActivityLog`, `masking.py`, `ROLE_TABS` and the importer flow. |
| Open business questions (README's 11) | Do not block the build. Unresolved codes (box colours F/RG/RC/CM/C/BY, diamond LC/LB/PI…) load as unconfirmed master values with the prototype's "? unresolved" chips, correctable in Settings. |

## Build order

Each part gets its own design → plan → build.

1. **Foundation + stones read screens** — app, shell, CSS, models, stones importer, Shelf ×3,
   Pouch detail (Save, Add price, photos), read-only Movements, client view, roles, masking.
   *Designed: `2026-09-28-inventory-stones-design.md`.*
2. **Stones ledger** — Record movement, Purchase, Split pouch, Transfer.
3. **Diamond stock** — diamond importer with a hand-confirmed code table, Search with bubble filters,
   Settings (masters, suppliers, editable rights matrix, range → grade expansion), rate card seeded
   from IVY.
4. **Diamond ledgers** — Job cards (create, post, close), Assortments (post only when balanced;
   cost carried pro-rata by weight), Purchases.
5. **Later** — the padlocked items, the client lookbook link, the `BomLine` → lot link.

## Facts established during the deep dive

- **Diamond shape codes:** the IVY export's own Shape/ShapeName columns say **PC = Princess,
  PR = Pear, PI = Pie Cut, RSC = Rose Cut, TB = Tapper Buguette**. The prototype's decoder has PC/PR
  swapped and reads RSC as Round Single Cut. Part 3 decodes through a confirmed lookup table, never
  the prototype's parser.
- **Diamond prices:** the diamond file has none; every rupee on the prototype's diamond screens comes
  from a placeholder formula. `nornament stock.xlsx` carries real cost and sale rates per item code and
  size; 34 of its codes and 50 of its batches appear in DIAMOND 31.
- **Totals reconcile:** stones 2,916 pouches · 697 batches · 19 box colours · ₹1,72,49,719 ·
  1,056,315.10 ct (the README's 698 / ₹1,72,49,717 / 1,058,182 ct include one unparseable "Broken"
  row). Diamonds 348 lines · 673.90 ct · 270 batches · 84 item codes.
- **The key is not yet unique:** 10 batch + pouch no. pairs are duplicated (21 pouches) and 210
  pouches have no number.
- **Spec vs prototype:** the spec's stone-type catalogue, price-kind history beyond what part 1 uses,
  draft → verified → published gate, stock take, fx and HSN/GST are not in the prototype and are not
  in scope. The prototype's job-card, assortment and purchase ledgers are not in the spec; parts 2–4
  design their tables.
- **Name collision:** `stock.JobCard` already exists and means one priced job sent to a vendor. The
  inventory's carat-ledger job card is a separate model in the `inventory` app.
