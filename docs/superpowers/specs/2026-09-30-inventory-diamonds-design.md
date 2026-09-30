# Inventory part 3: diamond stock — design

**Date:** 2026-09-30
**Status:** approved, ready for planning
**Overview and earlier decisions:** `2026-09-28-inventory-overview.md`; part 1 (stones) is `2026-09-28-inventory-stones-design.md`
**Designed against:** the prototype `../Nornament_Inventory/04-source-scripts/_script.html` (diamond section: `ROLES`/`can()`, `dMatch`/`dRows`, `colBucket`, `bubbles()`, `diaSearch`, `diaSettings`), `build_dia.py` (the un-pivot and item-code grammar), and the IVY export `nornament stock.xlsx` (Shape/ShapeName and diamond cost/sale rates). The source workbook `DIAMOND 31.xlsx` is not yet on this machine — see *Dependency* below.

## Why

The business holds 348 diamond lines (673.90 ct) in a pivot spreadsheet with no prices. The prototype shows how they should be searched and administered; part 1 built the stones half. This part makes diamond stock real: an importer, the Search stock screen, and Settings. Job cards, assortments and purchases are part 4.

## Scope

**In:** diamond models; the diamond importer (first import and periodic re-import); Search stock with cascading bubble filters; Settings — editable user-rights matrix, suppliers, master lists, item codes, rate card, range → grade expansion; the "Viewing as" role preview; the add-only role-group sync.

**Out (padlocked, part 4):** Job cards, Assortments, Purchases, the ⚒ Job card / ⇅ Assort / ＋ Purchase buttons, and the Movements / Purchase / Stock take tabs on the diamond side.

## Standalone rule

The inventory shares only user permissions (`accounts/`: logins, roles, capabilities) with the stock and CRM apps; integration with them is a later, separate step. Part 1's existing ties (suppliers in `stock.Vendor`, imports in `stock.ImportBatch`, `stock.ActivityLog`, mediahub photos, `stock/masking.py`, sidebar links) stay as they are. **This part adds no new dependency on stock or CRM data**: in particular, diamond prices come from an inventory-owned rate card, never from the stock app's Standard rate chart. Reusing part 1's patterns is fine.

## Data model

```
DiamondTerm   kind (category|shape|colour|clarity|band) · value · sort · expands_to
              UNIQUE(kind, value)
DiamondCode   item_code PK ("DRFGH VS-SI") · category/shape/colour/clarity → DiamondTerm (nullable)
              · confirmed · note
DiamondLine   ref NRD-000001 (unique, immutable, from a sequence at creation)
              · code → DiamondCode · batch_no (blank allowed) · size_text (as typed)
              · band → DiamondTerm · ct_lo · ct_hi (carat-banded sizes only)
              · src ("Sheet!47") · import_batch → stock.ImportBatch (as part 1)
DiamondRate   code → DiamondCode · size_text ("" = any size) · cost_rate · sale_rate
              · effective_from · set_by
Movement      pouch → Pouch becomes nullable; + diamond → DiamondLine (nullable)
              CHECK exactly one of (pouch, diamond)
```

- **Master lists are `DiamondTerm` rows.** Seeded: the five prototype categories (Natural Diamond, HPHT Lab Grown, Lab Grown (CVD?), Solitaire, Foil Polki); the colour ladder D…Z (`D E F G H I J K L M N O P Q-R S-T U-V W-X Y-Z`) and clarity ladder `FL IF VVS1 VVS2 VS1 VS2 SI1 SI2 SI3 I1 I2 I3` in `sort` order; colour ranges `D-E-F E-F F-G-H G-H I-J K-L M-N` and clarity ranges `VVS-VS VS-SI SI-I I1-I2` with `expands_to` (e.g. `F-G-H` → `F G H`, `SI-I` → `SI1 SI2 SI3 I1`); fancy colours (`Fancy Yellow`, `Fancy Pink`, `Fancy Orange`, `Fancy Green`, `Fancy Blue`, `Fancy Brown`, `Fancy Black`, `Fancy Grey`); size bands in order `-2 · +2-6 · +6-11 · 11-20 · 20+ · carat band`. Shapes are not seeded: they are created as codes are decoded, named as the IVY export names them (Round, Princess, Pear, Marquise, Oval, Emerald, Asscher, Heart, Trillion, Tapered Baguette, Rose Cut, Pie Cut …).
- **A line's category, shape, colour and clarity come from its `DiamondCode`.** Correcting a code once corrects every line on it; renaming a term renames it everywhere.
- **Carats on hand** are the sum of the line's movements (the part 1 rule). Diamonds carry no piece count.
- **Price** of a line: the latest `DiamondRate` for (its code, its `size_text`), else the latest for (its code, `""`), else "not set". Cost value = ct × cost_rate; sale value = ct × sale_rate; margin = (sale − cost) / cost. Part 4 adds a line's own purchase cost, which will take precedence over the rate card's cost.
- **Rates are seeded from the IVY export file**, not the stock app: "Load rates from IVY export" reads `nornament stock.xlsx`'s diamond Item Code, Item Size, cost-rate and sale-rate columns and writes `DiamondRate` rows for codes that exist, dated the load day; later rows win.

## Importer

`/inventory/diamonds/import/` — upload → review → commit, the part 1 flow, with part 1's hardening (blocked items stop the commit; one transaction; the batch is claimed before committing so a double submit cannot run twice).

**Parse** — a port of `build_dia.py`: sheet `Sheet`, columns A category · B batch · C item code · D (unused) · E size · F weight; header rows skipped (A = "Raw Material" or B = "Batch No"); rows containing "Total" in A–D skipped; **rows with A–E all blank skipped** (the unlabelled grand totals behind the phantom 1,350 ct); A–C and E carry down from the row above; a line is emitted only when F is a number. Category names map as the prototype's `CATNAME` (Diamond → Natural Diamond, HPHT Diamond → HPHT Lab Grown, Lab Grown → Lab Grown (CVD?), Solitare → Solitaire, Foil Polki).

**Decode new item codes** — the prototype's grammar (clarity suffix, origin prefix, shape, fancy letters, colour token), with these corrections taken from the IVY export's Shape/ShapeName: **PC = Princess, PR = Pear, PI = Pie Cut (a modifier before a shape), RSC = Rose Cut**, TB = Tapered Baguette. A token that does not resolve becomes a `?`-prefixed term (`? LC`, `? LB`, `? RD8` …) and the code is unconfirmed. Codes already in the table are never re-decoded.

**Size → band** — the prototype rule: sub-sieve sizes (`0-1`, `00-0`, `000-00`, `0000-000`), `+1` and anything starting `-2` → `-2`; `+N` and `+lo-hi` by the lower number: < 6 → `+2-6`, < 11 → `+6-11`, < 20 → `11-20`, else `20+`; `XX lo-hi` → `carat band` with `ct_lo`/`ct_hi` (and the shape from the prefix when the code has none); anything else → `?`.

**Review** shows: new codes with their proposed decoding (accept or edit, confirm); rows needing a decision; recounts; lines missing from the file.

**Re-import** (the file is re-exported and re-imported periodically):

| Case | Behaviour |
|---|---|
| Row matches one existing line by batch + item code + size_text | update; a weight change becomes a Recount Adjustment movement, listed before it posts |
| That key is not unique | fall back to the sheet row (`src`); still ambiguous → review with *map to line / new line / skip* |
| No match | new line with an Opening Balance movement |
| Line in the app but not in the file | listed; *leave as is* (default) or *recount to 0* |

## Screens

**Shell** — the part 1 inventory shell. The ◇ Diamonds switch is live and goes to `/inventory/diamonds/`. On diamond pages the rail shows the prototype's diamond sections: *Diamonds — internal*: Search stock (live count), Job cards 🔒, Assortments 🔒, Purchases 🔒; *Settings — you define these*: User rights, Suppliers, Categories, Shapes, Colour grades, Clarity grades, Size bands — each an anchor to its card on the Settings page, with correct counts. Tabs: Diamond stock active; Movements, Purchase, Stock take 🔒. The Internal / Client preview toggle is hidden (diamonds are internal only). The `.dsub` sub-tab bar: Search stock · Job cards 🔒 · Assortments 🔒 · Purchases 🔒 · Settings.

**Search stock** — `/inventory/diamonds/`, the prototype's layout:
- Role bar: "Viewing as", the ✓/✕ cost · sale · margin pills, the chip "Diamonds are internal only — no client view". Admins can pick a role to preview; everyone else sees their own role, fixed.
- Bubble rows: Category (big, "start here", with the "All" bubble always showing the global total), Shape, Colour, Clarity, Size; then the Carats from/to row with Clear all and the live "{n} lines · {ct} ct" counter. Semantics as the prototype: AND across rows, OR within; each row's bubbles are computed from every filter except its own; a range grade counts under each grade it expands to; colour buckets include "(no colour stated)", "? unresolved token", "? misread from the item code" and fancy colours; clarity has "(no clarity stated)"; bubble order — ladder then alphabetical for colour and clarity, carats descending for shape and category, band order for size; picking a category clears shape, colour, clarity, size and batch but not the carat range; the carat filter is an overlap test and excludes lines that are not carat-banded; when a category is selected, the blue strip "Showing only what {cat} actually holds — {N} shapes."
- Filters are GET parameters (bookmarkable); each bubble is a link. A **Batch** filter is added (the prototype's code supported it but had no control).
- Tiles: Quantity in view (hero) · Cost value · Sale value · Margin; money tiles show "Hidden for {role}" when masked.
- Stock table: Category · Shape · Colour · Clarity · Size (band, raw size under it) · Batch (or red "none") · Carats · [Cost/ct · Cost value] · [Sale/ct · Sale value] · [Margin] · Item code · Read (✓ clean, or the code's note, amber). Sorted by carats descending, first 300, "Showing the 300 heaviest of {n}." Money columns are removed, not blanked, when masked.
- ⚒ Job card, ⇅ Assort, ＋ Purchase shown padlocked.
- The red "illustrative prices" banner is not ported (prices are real or "not set"; prose stripped).

**Settings** — `/inventory/diamonds/settings/`, one page of anchored cards:
- **User rights** — roles ADMIN, ACCOUNTS, SALES, GRAPHIC, PRODUCTION, KARIGAR × See cost · See sale · See margin · Post purchase · Job cards · Assort · Edit settings (`view_cost`, `view_sale`, `view_margin`, `inv_purchase`, `inv_job`, `inv_assort`, `inv_masters`). Checkboxes, admin only; the ADMIN row is always full and locked; the viewer's row carries a "you" chip. These rights are shared app-wide, so changing one here changes it in stock and CRM too.
- **Suppliers** — Supplier · City · Terms · Purchases (count of Purchase movements with that counterparty; 0 until part 4) · Edit; ＋ Add supplier. Suppliers are part 1's list (`stock.Vendor`) with a new `terms` field.
- **Categories · Shapes · Colour grades · Clarity grades · Size bands** — Value · In use ("{n} lines") · Carats · Rename · Delete (only when unused, else "in use"); `?`/`(` values as amber chips; ＋ Add.
- **Item codes** — all codes: code · category · shape · colour · clarity · confirmed · lines; Edit; unconfirmed flagged.
- **Rate card** — code · size · cost/ct · sale/ct · effective from; inline edit; "Load rates from IVY export".
- **Range → grade expansion** — each colour and clarity range with its grades, editable; unresolved tokens (`? LC`, `? LB`) flagged red.

## Roles, masking, editable rights

- Search stock: any login; money masked per role. Settings: `inv_masters` — without it, the prototype's red "Not permitted for {role}" banner, and saves are refused with 403. The rights matrix: admin only, even for a holder of `inv_masters`. Importer and rate-card writes: `inv_masters`, checked in the service; loading or editing cost needs `view_cost`, editing sale needs `view_sale`.
- Diamond rows are built by one row builder ending in `stock.masking.mask()` (as part 1). Cost, sale and margin use the existing gated names `cost_rate`, `cost_amount`, `sale_rate`, `sale_amount`, `margin`. The table drops a column whose key was masked.
- "Viewing as" (admins): the page is rendered for a stand-in user holding exactly that role's permissions — the real masking, not a style change — without touching the admin's own session.
- **Add-only group sync.** `accounts.models.sync_role_groups` changes so that a role group created for the first time gets its full default rights, and a permission created for the first time is granted to the groups that list it by default; an existing permission's grants are never reset. An admin's untick therefore survives every deploy and migration. Each matrix change is written to the audit log (who, role, right, on/off).
- The Karigar gate from part 1 is unchanged: Diamond Search is visible to a Karigar login, with no money and no Settings.

## Errors

Service rules raise `ServiceError`, shown as a message: missing right; a blocked item code; deleting a term in use; renaming a term to an existing value; a negative, non-finite or out-of-range rate; a duplicate supplier code. The importer cannot commit while anything is blocked, commits in one transaction, and claims its batch first. The rights matrix refuses non-admins and ignores edits to the ADMIN row.

## Testing

`inventory/tests/`, part 1 conventions (only database tests carry `django_db`; real role fixtures):
- Code decoding — every token rule; PC = Princess, PR = Pear, PI modifier, RSC = Rose Cut; `? LC`/`? LB`; FPL.
- Size → band — `+2`→`+2-6`, `+6`→`+6-11`, `0000-000`→`-2`, `+80-100`→`20+`, carat bands with ct_lo/ct_hi.
- Range → grade expansion.
- Importer — total rows skipped (no phantom 1,350 ct), carry-down, new codes to review, re-import matching (unique key, src fallback, ambiguous to review), recounts, lines missing from the file.
- Search — each row ignores its own filter, category reset, carat overlap, batch filter, the 300 cap, colour/clarity buckets.
- Pricing — exact size, any-size fallback, "not set"; the IVY rate loader.
- Rights — add-only sync keeps an untick through a re-sync; only admins edit the matrix; the preview masks as the chosen role.
- Masking walk — the diamond screens join `inventory/tests/test_masking.py`'s walk (SALES, KARIGAR, GRAPHIC never see cost, sale, margin or supplier), and its every-screen check covers them.
- Parity — the prototype's embedded diamond data (`const DD` in `nornament-ui-mockup.html`, read from beside the repo and skipped if absent), rebuilt into a workbook and imported through the real importer: 348 lines, 673.90 ct, 270 batches, 84 item codes, and the prototype's category totals (Natural Diamond 329 / 563.20 ct, Foil Polki 10 / 105.58, HPHT Lab Grown 5 / 2.81, Solitaire 3 / 2.26, Lab Grown (CVD?) 1 / 0.05) and band totals.

## Dependency

`DIAMOND 31.xlsx` is not available. Decision (2026-09-30): build the parse step to the layout `build_dia.py` documents, test it against a workbook rebuilt from the prototype's embedded diamond data, and correct the parse step when the real file arrives. If the real layout differs, only `inventory/importers/diamonds.py`'s parse and its fixture change.

## Changed while planning

- **Category belongs to the line.** The prototype takes each line's category from column A of its row, so `DiamondLine.category` holds it; `DiamondCode` holds shape, colour and clarity.
- **A line can carry a shape override** (`DiamondLine.shape_override`): when a code names no shape and the size is a carat band with a shape prefix (`TR 0.20-0.24`), the shape comes from the size, as in the prototype.
- **Carat-band size prefixes read the IVY way too:** `PR` = Pear, `PC` = Princess.
- **A single leftover ladder letter is a colour grade** (`DTBG` → colour G, `SOMG` → Marquise G), as the prototype read it, but the code stays unconfirmed.
- **Setting a rate needs both `view_cost` and `view_sale`**, because one rate row carries both.
- **The band list is seeded with `?`** for a size that fits no band.
- **Diamond parity** is `inventory/tests/test_dia_parity.py` (marked `golden`): the prototype's `const DD` rebuilt in file order and imported must give 348 lines, 673.90 ct, 270 batches, 84 codes and the prototype's category and band totals.

## The real diamond file (2026-09-30)

The owner supplied `Dia_Stock_Nitesh.xlsx` in place of `DIAMOND 31.xlsx`. It is not the pivot `build_dia.py` documents: four flat sheets, one row per line, header in row 1. Decisions, approved by the owner the same day:

- **Sheets.** `FANCY FINAL`, `Round_LB_LC` and `Round_RW` are read; `FANCY` (the same 117 lines in another order, two rates swapped) is ignored. Header rows (repeated mid-sheet in `Round_LB_LC`), `Total=` rows and the unlabelled total rows (no weight) are skipped.
- **Columns.** Item code = `Gati Code` (whitespace collapsed). `Round_RW` has none, so it is built as `DR{colour} {clarity}` (RW1 EF VVS VS → `DREF VVS VS`, the prototype's naming). `Code` is a carat band when it reads as one (`M0.10-0.15`, `EM0.16-019` is not one) and the batch number otherwise (`FCD.1`, `TB1.1`, `LB1.01`, `RW1`); blank means neither and is never carried down. Size = `Seive/Size` or `Seive`; a bare number there is a sieve (`10` → `+10`). Shape, colour, clarity and pieces come from their columns. An optional `Category` column is honoured; without it every line is Natural Diamond. The Foil Polki, HPHT, Solitaire and Lab Grown stock will come from another file later, through the same importer.
- **Vocabulary.** File values are mapped onto the master lists: colour `EF`→`E-F`, `GH`→`G-H`, `FGH`→`F-G-H`, `IJ`→`I-J`, `KL`→`K-L`, `MN`→`M-N`; **`LB` is colour M-N and `LC` is K-L** (owner, 2026-09-30), in the file and in item codes; clarity separators are made hyphens (`SI  I`, `SI I`, `SI-I` → `SI-I`; `VS SI` → `VS-SI`); a row whose clarity is `Fancy` has colour `Fancy <colour>` and no clarity; shapes `ASSCHER`→Asscher, `Tapers Buggutte`→Tapered Baguette, `Triangle`→Trillion, `Piecut (EM/OV/Pear/Star)`→Pie Cut Emerald/Oval/Pear/Star, `Mix Shapes`→Mix. Unknown values become new terms, editable in Settings.
- **Item codes.** A new code takes its shape, colour and clarity from the file's columns, falling back to decoding the code where a column is blank. It is confirmed when the columns give all three (shape and colour for a fancy colour) and nothing disagrees with the decoded code; otherwise it stays unconfirmed with a note naming the disagreement (including two rows of one code that disagree).
- **Pieces** go into the opening balance with the carats.
- **Zero-carat rows** open nothing; if one matches a line already held, that line is recounted to zero.
- **Cost.** The file's per-carat rate is the **cost** rate. `Round_LB_LC` has its `Amount` and `PRICE` headers swapped, so the rate is whichever of the two money columns, times the weight, gives the other; failing that, the column headed `Rate`. On commit, and only for a login with `view_cost`, each line's cost rate goes to the rate card for its item code and size when it differs from the current one; without `view_cost` the stock is imported and the page says the prices were skipped. Sale prices still come from the rate card (the IVY loader or Settings).
- **Rate lookup, per field.** Cost and sale each resolve to the latest row that sets them (exact size, then any size), so a cost-only row never hides an earlier sale rate.
- **Real-file check.** `inventory/tests/test_dia_real_file.py` imports `Dia_Stock_Nitesh.xlsx` from beside the repo (skipped if absent): 320 rows read, 281 lines opened (39 zero-carat rows open nothing), 546.96 ct, nothing blocked, and a cost value of ₹1,47,98,794 give or take ₹10 (the file's own sheet totals).
- **Parity** still runs: the prototype's `const DD`, rebuilt as a `FANCY FINAL` sheet with the Category column and the columns it has, must still give 348 lines, 673.90 ct, 270 batches, 84 codes and the same category and band totals.
