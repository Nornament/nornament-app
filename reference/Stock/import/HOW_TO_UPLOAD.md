# Uploading stock

Two files, one loop.

1. Fill in **`nornament_bulk_upload.xlsx`** — as much or as little as you know.
2. Open **`nornament_upload.html`** in Chrome, sign in, drag the sheet in.
3. Look at what it says it will do. Press Import.
4. When the rest of the details arrive, put them in a sheet and upload again.

---

## Uploading the same sheet twice is safe

This is the part that matters for how you work.

When a jewel code comes in that the database has never seen, the piece is
created. When a jewel code comes in that already exists, only the **blank**
fields get filled from the sheet. A value already in the database is never
quietly replaced by whatever is in the spreadsheet.

So the second upload does not duplicate anything and does not undo anything.
It just fills gaps.

| Upload | Sheet says | What happens |
|---|---|---|
| 1st | code, design, category | piece created, waiting on karat / weight / materials / location |
| 2nd | + karat, weight, gold, making, MUM | **filled in** — cost and price appear, piece goes into stock |
| 3rd | same sheet again | **unchanged** — nothing to do |
| 4th | someone typed a different weight | **unchanged** — the sheet does not overwrite what you already recorded |

If you genuinely want the sheet to win, tick **"Also replace values already in
the database"** before importing. It then tells you exactly what it changed —
`gross_wt: 12.370 → 11.900` — rather than changing it silently.

---

## Nothing is written until you press Import

Drop the file in and you get a preview: every row, what will happen to it, and
every problem found — checked against your real material master, categories,
locations and karats. Rows that would be refused are marked in red **before**
anything is sent, and they are not sent at all.

A refused row does not stop the others. Fix those rows, upload the sheet again,
and the pieces that already landed are left alone.

### What gets a row refused

| The sheet says | Why it is refused |
|---|---|
| the same jewel code twice | one jewel code is one physical piece |
| `Erings` | not one of your categories |
| `G14K` | your gold codes are **`G`** and **`GC`** — karat lives on the piece, not on the material |
| `9K` | only 14K, 18K, 22K, 24K are set up |
| `Delhi` | your locations are HO, MUM, KOL, WS1 |
| gold in CT | metal is weighed in grams |
| materials for a jewel code that has no row on the pieces sheet | they have nowhere to go |

**A bad material line refuses the whole piece**, not just that line. Entering a
piece with one material silently dropped would give it a wrong cost, which is
worse than not entering it.

---

## Column names

Headings do not have to match the template exactly. `jewel_code`, `jewelcode`,
`Jewel Code`, `sku` and `code` are all read as the jewel code; `bno`, `style`,
`design no` all read as the design. The first sheet with a jewel code column is
read as the pieces, and any sheet named like *BOM* or *materials* is read as the
material lines.

Two columns are worth knowing:

- **`cost_rate`** — leave blank and the rate card is used. Fill it only when
  this particular piece was bought at a rate that is not your standard card.
- **`qty` on a MAKING row** — leave it blank. Making is charged on net metal
  weight, worked out after the gold lines are read. A number here is wrong.

Gold sale rate never comes from the sheet. It is always
`pure 24K rate × sale purity` at the moment someone looks at the piece —
22K 92.5%, 18K 76%, 14K 59%. That is what keeps the price live.

---

## Filling in the rest later

Second tab, **Stock & what's missing**. Every piece carries a chip for each
thing it is still waiting for. Press **Download the gaps as Excel** and you get
a sheet of only the incomplete pieces, with what you already know filled in and
a `STILL_MISSING` column telling you what to type. Fill the blanks, upload it,
done.

Two behaviours to keep in mind:

- **No location means it is not in stock.** A piece keyed in but not physically
  received is deliberately kept out of stock counts and valuations. Put a
  location in the sheet and it becomes stock from that date.
- **Materials are only written if the piece has none.** If a piece already has a
  bill of materials, an upload will not touch it unless you tick the replace
  box — and then it forks a new BOM version rather than editing the old one.
  Your original job card stays readable.

---

## Verified

`ER00123` uploaded through this route comes out at cost **₹1,18,141**, live sale
**₹3,10,970**, net metal **9.850 g**, BOM weight **12.370 g** — the same numbers
as your job card. A Sales login cannot upload: the page turns them away, and so
does the database if they skip the page.
