# Inventory stock take (part 5d) — design

Part 5d of the Nornament inventory: counting a section of the shelf (stones) or
a category (diamonds) and posting the differences. Branched from `main` after
parts 5a–5c.

## Where this comes from

The prototype draws only a greyed-out **Stock take** tab and an inert
**Stock takes** rail item; its schema spec names a `stock_take` session that a
**Recount Adjustment** movement points to (`03-spec/…v1.1.md:75-80, 195, 455`).
The app already recounts one pouch at a time (`services.recount_deltas`,
`ledger_single.post_recount`) and one diamond line at a time
(`dia_services.recount_line`). The stock app's `StockCount` (one open count per
location, a result frozen at close) is the pattern; nothing is shared with it
(inventory stays standalone).

Owner's rulings (2026-10-04):

- **Scope — a box colour or a batch** (stones) or **a category** (diamonds).
  Several may be open at once if they do not overlap.
- **Closing posts the recounts**: counts are entered with the variance shown;
  closing posts one Recount Adjustment document for every counted difference
  and freezes the result. Counting and closing need `inv_move`.

## Screens

Both padlocks come off: the stones rail's **Stock takes** and both sides' top
**Stock take** tab.

### List — `/inventory/stock-takes/` (stones), `/inventory/diamonds/stock-takes/` (diamonds)

URL names `inventory:stock_takes`, `inventory:dia_stock_takes`. Open stock
takes first, then closed and cancelled, newest first: number (`ST-000001`),
scope, status chip, started by / on, counted *n* (the sheet shows *n* of *m*), closed by / on.

**Start a stock take** (for `inv_move` holders): stones choose a box colour
**or** a batch (two selects; exactly one); diamonds choose a category. Starting
redirects to the count sheet.

### Count sheet — `/inventory/stock-takes/<pk>/`, `/inventory/diamonds/stock-takes/<pk>/`

URL names `inventory:stock_take`, `inventory:dia_stock_take`.

- One row per pouch in the scope with something on hand, plus any pouch already
  counted in this stock take (diamonds: per line, carats only). Columns:
  pouch (`batch · pouch no.`, NRN ref; diamonds: line ref, code, size), stone
  (diamonds: shape · colour · clarity), book pcs / ct (live), counted pcs / ct
  (inputs; pcs read-only for an uncountable pouch), variance pcs / ct, and
  **variance value** (variance ct × valuation /ct; diamonds × cost /ct, own
  cost first then rate card) for `view_cost` holders only.
- A blank box means **not counted**, never zero; a typed 0 is a count of zero.
- **Save counts** stores every filled row (an emptied box removes that count);
  counting may run over several sessions and people.
- **Close and post** and **Cancel stock take** at the foot, each behind a
  confirm step on the page (a second button press, no browser dialog).
- Foot: counted *n* of *m*; total variance ct; total variance value (cost right).
- A closed or cancelled stock take renders read-only from its frozen result,
  with a link to the posted document (stones: the document page; diamonds: the
  stock take itself carries it) and, for a closed one not yet reversed, a
  **Reverse** button (`inv_move`). Its foot shows no money, only counted *n* of
  *m* and total variance ct — the frozen result never recomputes a value, and
  the day's rate is gone with the live sheet.

## Counting and posting

- Saving a count stores the counted figures **and the book figures at that
  moment**. The variance is counted − book-at-count, so stone sold or moved
  after its pouch was counted is not undone by the recount. Re-saving a row
  with a **changed** count refreshes both; a row saved again unchanged keeps
  the book it was counted against.
- The sheet's Book column shows the book at count for a counted row, the live
  book otherwise.
- **Close** posts one document — kind **Stock take** (`STK-`, stones) or
  **Diamond stock take** (`DST-`, diamonds) — holding a Recount Adjustment line
  for every counted difference: pieces and carats separately, as
  `recount_deltas` does (direction from the sign, quantity the absolute
  difference). No differences: the stock take closes with no document.
- When posting would take a pouch or line below zero (it moved out after it was
  counted), the ledger refuses; the close is refused with that message and the
  stock take stays open.
- Not-counted rows are left alone and listed as such in the frozen result.
- The frozen result (JSON) records, per row: owner ref, label, book, counted,
  variance; and the totals. A closed stock take is never recomputed.
- **Cancel** discards nothing from the ledger (nothing was posted); the stock
  take reads Cancelled with its counts kept for the record.
- **Reverse** reverses the posted document through `ledger.reverse_document`
  (its usual "moved since" rules are not involved: a recount creates nothing),
  marks the stock take Reversed in its chip, and is refused when the document
  is already reversed. Stones may also reverse from the document page.

## Rules

- Overlap: a stones stock take for a box colour overlaps one for any batch in
  that colour, and vice versa; two for the same box colour or batch overlap.
  Diamonds: two for the same category overlap. Starting an overlapping one is
  refused: "{other number} is already counting {scope}; close or cancel it first."
- Rights: start, save, close, cancel and reverse need `INV_MOVE` (403). Anyone
  internal may read the list and the sheets.
- Client view: every stones stock-take URL redirects to the shelf before reading
  anything; the rail item stays hidden there with the rest of Stock control.
  Diamonds have no client view; their pages honour the admin preview `?as=`
  like the diamond Movements tab, masking as the role and hiding every form.
- Masking: rows go through `stock.masking.mask()`; templates test key presence.
  Variance value uses `pouch_value`-style gated keys: `cost_amount` (view_cost).
  The masking walk covers every new URL.

## Data

- `StockTake`: `number` (unique, `ST-000001`), `side` (stones / diamonds),
  `box_colour` (FK, null), `batch` (FK, null), `category` (FK `DiamondTerm`,
  null), `status` (open / closed / cancelled), `started_by`, `started_at`,
  `closed_by`, `closed_at`, `document` (FK `StockDocument`, null), `result`
  (JSON, null), `note`.
- `StockTakeCount`: `stock_take` (FK), `pouch` (FK, null) / `diamond` (FK
  `DiamondLine`, null) — exactly one, `counted_pcs`, `counted_ct`, `book_pcs`,
  `book_ct`, `counted_by`, `counted_at`; unique per (stock take, pouch) and
  (stock take, diamond).
- `StockDocument.Kind`: `STOCK_TAKE = "stock_take", "Stock take"` (in
  `STONE_KINDS`, prefix `STK-`) and `DIA_COUNT = "dia_count",
  "Diamond stock take"` (the kind column holds 12 characters) (in `DIAMOND_KINDS`, prefix `DST-`); both
  `RIGHT_FOR_KIND = INV_MOVE`. The diamond Movements tab opens a diamond stock
  take's document on its stock take.
- One migration.

## Out of scope

Counting by scanning, blind counts (book hidden), stone found that is on no
pouch's books (record it with a movement), a four-eyes approval, photos of the
count, any stock-app change.

## Tests

- Scope: the sheet lists exactly the pouches / lines in scope with stock, plus
  counted ones; overlap refusals both ways.
- Saving: blank vs zero; re-save refreshes book; emptied box removes a count.
- A stale book: count, then sell, then close — the sale stands, only the
  counted difference posts.
- Close posts exactly the differences (pcs and ct separately), freezes the
  result, links the document; no-difference close has no document; a negative
  is refused and the stock take stays open.
- Cancel; reverse (and refused twice).
- Rights (403), client view (redirect), the padlocks come off on both sides,
  the diamond Movements tab opens a diamond stock take, the masking walk
  (variance value only with the cost right; preview masks and hides forms).

## Addendum (build)

- **Recount since refusal**: closing refuses while any counted owner has had a
  Recount Adjustment movement — on any document, or none (a bare diamond
  recount) — recorded after that count's `counted_at` that is not this stock
  take's own. Nothing is written and the take stays open; re-saving that row
  with a changed count, or clearing it, lets the close go through.
- **Concurrent counting**: the sheet renders a hidden field of what it showed
  for each row (pk → [pcs, ct], as strings or null). Only a row whose posted
  value differs from that is sent to `save_counts`, so a stale page's blank
  box can no longer delete another counter's save, and an emptied box still
  removes a count.
- **Out-of-scope counted rows**: a pouch or diamond line counted here and then
  moved out of scope (a transfer, an assortment) stays on the sheet and closes
  normally; `owners()` always includes anything already counted, in or out of
  scope.
- **Form-field limit**: `DATA_UPLOAD_MAX_NUMBER_FIELDS` is raised to 5000, so a
  large box colour's sheet (two fields per row) no longer answers 400 on Save,
  Close or Cancel.
