# IVY stock importer — design

**Date:** 2026-09-01
**Status:** approved, ready for planning
**Source file this was designed against:** `nornament stock.xlsx` (992 rows, 373 products, 367 embedded images)

## Why

The client hands over stock as an IVY Karigar ERP export. Today the only way in is
`manage.py load_legacy`, which reads the restored Supabase dump — it cannot read a
workbook, and it wipe-and-reloads, so it is the wrong tool for a periodic top-up.
We need a browser-driven import where a human sees what is about to happen and
decides the ambiguous parts before anything is written.

## Scope

**In:** the IVY export shape specifically. Upload, parse, review, commit, images,
progress. **Out:** a generic column mapper for arbitrary workbooks. If IVY changes
their export, we edit one constants block.

## The file shape

One sheet, `Sheet1`, 992 rows x 78 columns (A→BZ).

```
Row 1      'IVY Karigar Private Limited'          (merged banner)
Row 2      empty — the band group labels were lost in export
Row 3      column headers
Rows 4–990 data
Row 991    blank
Row 992    '[admin] : 27:07:2026 11:18'           (export footer)
```

Products are **blocks**, not rows. A block starts wherever `C Style No` is filled
and runs until the next such row. 373 products across 987 data rows; block sizes
range 1–26 rows.

Columns form five **independent material bands** laid side by side. Each band has
its own line list, and a block is as tall as its *longest* band — so row 7 of a
block can carry a stone line while the diamond band ran out at row 3. Bands must
be read down independently; they are not aligned to each other.

| Cols | Band | Present on |
|---|---|---|
| A–T | piece header (Style No, JewelCode, Category, Collection, Vendor, dates) | parent row only |
| U–AJ | Diamond / Polki lines | any row in block |
| AK–AU | Metal lines | any row in block |
| AV–BD | Stone lines | any row in block |
| BE–BH | product totals (Cost Price, Sale Price, Cost Making, Sale Making) | parent row only |
| BI–BR | other materials — Lakh / Alloy / Thread / GUM, **name only, no item code** | any row in block |
| BS–BZ | charges — EC Extra Charges, PC Purai Charges, RH100 | any row in block |

The totals roll up: verified on product `24P00111` that `BE Cost Price` 84,438 =
diamond 38,918 + gold 35,537 + gold-chakri 1,425 + making 8,558.

367 JPEGs are anchored in column A on parent rows (6 products have none).

Dead columns, ignored: `G Location Name`, `AC Setting`, `BK Quality`, `BL ToneCode`
(all empty in every row). Near-empty and ignored: `L`, `N`, `R`.

### Field mapping

| Sheet | Model field |
|---|---|
| `D JewelCode` | `Piece.jewel_code` (373, all unique) |
| `C Style No` | `Style.style_code` (351 distinct; 17 styles carry 2 pieces) |
| `E Category` | `Style.category` → `Category` |
| `F Sub Category` | `Piece.sub_category` |
| `M Collection` | `Style.collection` |
| `K Manuf. Name` | `Piece.vendor` |
| `Q Misc Remarks` (a date, mislabelled by the export) | `Piece.fg_date` |
| `H Inw Date` | `Piece.received_on`, **only if a location is chosen** |
| `BI G Qly` | `Piece.metal_purity` |
| `Y Quality` | `Piece.diamond_quality` |
| `P Stock Type` | `Piece.stock_type`, upper-cased and underscored: the sheet says `Finish Goods`, the model expects `FINISH_GOODS` |
| `B Sr No` | `Piece.src_ref` |
| `BE Cost Price` | `Piece.src_cost_price` |
| `BF Sale Price` | `Piece.src_sale_price` |
| `AN Net Wt` | `Piece.src_net_wt_gm` |
| — | `Piece.src_system = 'IVY'` |

## Architecture

Four steps on the existing `stock:data` Import/Export page. No new nav entry.

```
Upload .xlsx  →  Parse & analyse  →  Review decisions  →  Commit  →  Images
   (POST)          (pure fns)          (one page)        (one txn)  (chunked)
```

`stock/views.py` is already 1932 lines. All import logic lives in a new package,
`stock/importers/`, and the views are thin.

### `stock/importers/ivy.py` — the parser

```python
parse(fileobj) -> list[ParsedPiece]
```

Knows the IVY shape by heart via a `BANDS` constants block mapping band name →
column letters. Walks rows 4→991, opens a new `ParsedPiece` at every row where
`C` is filled, and reads each band down the block independently.

`ParsedPiece` is a dataclass: header fields, `lines: list[ParsedLine]` (each
tagged with its band), `image: bytes | None`, and `row_no` for error messages.

Pure and side-effect free. Takes a file object, touches no database.

### `stock/importers/analyse.py` — the diff

```python
analyse(pieces: list[ParsedPiece]) -> Plan
```

Diffs the parse against the database and returns resolution rows for every
reference set. Writes nothing. Called fresh on each review-screen load.

Against the database as it stands today:

| Set | In sheet | Already present | New |
|---|---|---|---|
| Materials | 224 | 97 | 127 |
| Styles | 351 | 186 | 165 |
| Pieces | 373 | 193 | 180 |
| Categories | 9 | 6 by fuzzy name | 3 |
| Collections | 8 | 7 | 1 |
| Vendors | 2 | 2 | 0 |

### `stock/importers/commit.py` — the write

```python
commit(pieces, decisions, user) -> Result
```

One `transaction.atomic` in dependency order: MetalPurity → Material →
Collection / Category / Vendor → Style → Piece → BomVersion → BomLine.
Images are explicitly **not** in this transaction (see below).

## Guessing new materials

127 new materials is too many to hand-fill, so `analyse` pre-fills each from the
band it appeared in plus its code, and the reviewer corrects the exceptions.

| Band | → `MaterialCategory` | Other fields |
|---|---|---|
| U–AJ, code starts `FPL` or `PL` | `POLKI` | `default_uom=CT` |
| U–AJ otherwise | `DIAMOND` | `default_uom=CT` |
| AK–AU | `METAL` | `metal` = Gold/Silver from `G`/`S` code prefix; `purity_factor` from the karat in `AL Item Name`, looked up in `MetalPurity` |
| AV–BD | `SETTING` | `default_uom=CT` |
| BI–BR (no code in sheet) | `OTHER` | code minted from the name: `OTH-LAKH`, `OTH-ALLOY`, `OTH-THREAD`, `OTH-GUM` |
| BS–BZ | `LABOUR` | `basis=BY_PIECE` |

**Unguessable rows block commit.** They render red at the top of the materials
section with a one-line reason, and the Commit button stays disabled until each is
resolved. `Material.needs_review` is *not* used as an escape hatch here — the
whole point of the review step is that nothing ambiguous slips through unseen.

Known blockers in this specific file: `MetalPurity` currently holds
24K / 22K / 18K / 14K / 999 / 925, but the sheet carries `G12K`, `S995` and
`G18%`. Those three purities do not exist and the reviewer must either create
them (karat + `true_fineness` + `sale_factor`) or re-point the material at an
existing purity. `CJ (Customer Jewelry999)` is a fourth oddity in the metal band
and will surface the same way.

## Review screen

One page. Sections collapsed with a count in each header, everything pre-filled
with its guess so a reviewer can read down and commit without typing.

- **Materials (224)** — 97 matched, 127 new. Each new row shows code, name and the
  guessed category / uom / metal, all editable inline. A datalist lets you instead
  re-point the code at an existing material.
- **Categories (9)** — six pre-matched by fuzzy name: `Earring→Earrings`,
  `Ring→Rings`, `Pendant→Pendant Sets`, `Necklace→Necklaces`, and both `Bangle`
  and `Bracelet` onto the single existing `Bangles / Bracelets`. That 2:1 collapse
  is shown explicitly, because it is the kind of thing a reviewer should agree to
  rather than discover afterwards. `Idol`, `Cufflink`, `String` default to
  *create new*.
- **Collections (8)** — 7 matched. `String` defaults to *skip*: it is a category
  value that leaked into the collection column on one row.
- **Pieces (373)** — 180 new, checked. 193 existing, shown as a field-level diff
  and **unchecked by default**, with a select-all. Checking one writes a new
  `BomVersion` with `reason=CORRECTION`; the previous version is retained and
  `is_current` flips to the new one. Nothing is ever edited in place.
- **Receive into** — a single `Location` dropdown. Left blank, new pieces land in
  `NOT_RECEIVED` with no location, which is what the `live_piece_has_location`
  check constraint requires. Choosing a location sets `received_on` from
  `H Inw Date`, moves the piece to `IN_STOCK`, and writes a `RECEIPT`
  `StockMovement` so the ledger stays truthful.

Gated with `@login_required` + `@tab_required("admin")`, matching the settings
screen — this writes reference data, not just stock.

## Staging

One new model, `stock.ImportBatch`:

| Field | Purpose |
|---|---|
| `batch_id` | pk |
| `media` FK → `MediaAsset` | the uploaded workbook, in the bucket |
| `decisions` JSONField | the reviewer's choices, default `{}` |
| `status` | `UPLOADED` / `REVIEWING` / `COMMITTING` / `IMAGES` / `DONE` / `FAILED` |
| `images_done`, `images_total` | drives the progress bar |
| `result` JSONField | counts written, and anything refused |
| `created_by`, `created_at`, `finished_at` | audit |

The review screen **re-parses the workbook on each load** rather than caching the
parse. 992 rows is roughly two seconds; materialising 987 parsed rows into staging
tables would be three models and a migration for data thrown away at commit. The
batch row survives a closed tab and gives an import history for free.

## Progress

Two phases are slow enough to need feedback, and they are slow for different
reasons, so they are reported differently.

**Commit (the DB transaction).** 373 pieces and 1,845 BOM lines (728 diamond, 502 metal, 468 stone, 109 other, 38 charges) in one
transaction takes a few seconds. It is atomic and cannot be meaningfully
subdivided — a progress bar over it would be a lie. It gets a spinner and a
"writing 373 pieces…" label, and the POST returns when the transaction commits.

**Images (367 uploads to S3).** This is the genuinely long phase — minutes, not
seconds — and it is the one that gets a real bar.

The mechanism is **browser-driven chunking**, which needs no new infrastructure:

1. The commit response renders the progress page with a bar at 0 / 367.
2. That page carries `hx-post` to `stock:import_images` with
   `hx-trigger="load delay:100ms"`.
3. Each request uploads the next 10 images, bumps `images_done` on the batch, and
   returns the bar partial — which itself carries the trigger for the next chunk.
4. When `images_done == images_total` the partial returns the finished summary
   with no trigger, and polling stops.

The bar is honest because every increment is work that actually completed and was
committed. There is no Celery, no RQ, no background thread inside a gunicorn sync
worker, and no in-memory progress counter that a worker restart would erase. A
closed tab leaves the batch at `IMAGES` with a recorded `images_done`, and
reopening it resumes from exactly there.

`stock/templates/stock/_import_progress.html` is the partial; it renders a native
`<progress>` element with a text fallback, so there is no new CSS or JS.

## Images

`mediahub.services.attach_uploads(files, scope, entity_id, user, kind)` already
does presign, put, checksum and `MediaAsset` creation. The importer reuses it by
wrapping each image's bytes in a `SimpleUploadedFile` — openpyxl gives both the
bytes and the anchor row, and the anchor row maps to exactly one JewelCode. No new
S3 code is written.

Images run **after** the database transaction has committed, deliberately. S3 is
not transactional; if uploads were inside the transaction, one refused file would
roll back the whole catalogue. An orphaned object in the bucket is harmless. A
half-imported catalogue that nobody can describe is not. Refusals are collected
into `ImportBatch.result` and shown in the summary, never silently dropped —
matching the contract `attach_uploads` already documents.

## Errors

- **Wrong workbook.** Row 3 headers are checked against the expected IVY set
  before anything else. A mismatch rejects the upload with the offending header,
  rather than importing nonsense.
- **Unresolvable decision.** Blocks commit, red, with a reason. Not bypassable.
- **Failure mid-transaction.** The transaction rolls back, the batch goes to
  `FAILED` with the exception in `result`, and the database is exactly as it was.
- **Failure mid-images.** The catalogue is already safely committed. The batch
  stays at `IMAGES` with `images_done` recorded, and the next chunk request
  resumes from there.

## Testing

One module, `stock/tests/test_import_ivy.py`, against a small fixture workbook
generated in-test (three products, so the fixture stays readable):

1. a single-row product with one diamond line and one metal line;
2. a multi-band product whose bands have unequal lengths — this is the parse rule
   most likely to break, and the one that would silently corrupt BOMs if it did;
3. a product whose JewelCode already exists in the database.

Assertions: block boundaries land on the right rows; bands read independently and
do not bleed into each other; the material guesser assigns the right
`MaterialCategory` per band; an unguessable metal purity is flagged rather than
invented; and a collision produces `BomVersion` v2 with `is_current` flipped while
v1 survives untouched.

Plus one test that image chunking is resumable: run one chunk, assert
`images_done == 10`, run the rest, assert every image landed exactly once.

## Dependency

`openpyxl` is added to `requirements.txt`. Nothing in the stack reads xlsx today.
It is the standard library for this and reading the zip/XML by hand to avoid a
dependency would be strictly worse code.

## Deliberately not built

- A generic column mapper. The band layout — parent/child blocks, five independent
  material bands — cannot be expressed as a flat column map, so a generic mapper
  would need the IVY logic as a special case anyway.
- A task queue. Browser-driven chunking covers the one long phase without adding
  infrastructure to deploy, monitor and restart.
- Undo. The BOM versioning already makes piece changes reversible, and skipped
  pieces are untouched by construction.
