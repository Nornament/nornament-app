# Adding stock

**Use `nornament_stock_entry.html`.** Open it in Chrome, sign in with your
Nornament email and password, and add pieces. It writes to the live database.
Everything below is the detail behind it, plus the bulk route for when you
have a filled spreadsheet.

---

## You do not need the full job card to enter a piece

Four things start a piece: **jewel code, design number, category, design name.**
That is it. Karat, weight, materials, location, hallmark, dimensions — all of
it can arrive later.

A piece with gaps is a real record. It sits in the second tab of the entry
screen with an orange chip for each thing it is still waiting for:

> ZZ00123 · *Karat* · *Gross weight* · *Materials (BOM)* · *Not received into any location* · *Photograph*

Click **Fill in**, add whatever you now know, save. The chips disappear one at
a time. When the materials go in, the cost and price appear on their own.

Two rules the database enforces, and you should know why:

- **No location means it is not in stock.** A piece you have keyed in but not
  physically received is deliberately kept out of stock counts and valuations.
  Choose a location — or use Fill in later — and it becomes stock at that moment.
- **Changing materials on a piece that already has them forks a new BOM
  version.** The original stays readable. Nothing is ever overwritten.

---

## What "adding a piece" actually does

It is not one insert. Six things have to happen together or the piece is
half-made and your stock is wrong:

1. the **design** (style) is created, if this is a design you have not made before
2. the **jewel code** is created — one code, one physical piece, forever
3. **BOM version 1** is opened
4. every **material line** is written and priced from your rate cards
5. the piece is **recosted** — net metal weight, BOM weight, cost, making, goods value
6. a **RECEIPT movement** is posted, which is what actually puts it in stock

`app.add_piece()` does all six inside one transaction. If step 5 fails, step 1
is undone too. You will never find a jewel code with no BOM, or a BOM with no
piece.

If you skip step 6 — leave `location` blank — the piece exists but is
`NOT_RECEIVED`. It will not appear in stock counts or valuations. That is
deliberate: something you have keyed in but not physically received is not stock.

---

## Route 1 — Bulk, from the workbook (use this for your 20)

```
pip install openpyxl
python make_import_sql.py nornament_bulk_upload.xlsx
```

It writes `import.sql` next to the workbook and prints a pre-flight check —
pieces with no BOM lines, BOM lines with no piece, material codes that are not
in your master, jewel codes listed twice. **It does not touch the database.**

Then: Supabase → SQL Editor → paste `import.sql` → Run.

You get back a row-by-row report:

```json
{ "added": 18, "rejected": 2,
  "rows": [
    { "ok": true,  "jewel_code": "ER00123", "cost_price": 118141,
      "sale_price": 310970, "net_metal_wt_gm": 9.850, "unpriced_lines": 0 },
    { "ok": false, "jewel_code": "BAD01",
      "error": "Category \"Erings\" not found. Known: Earrings, Necklaces, ..." }
  ] }
```

**A bad row does not kill the batch.** The 18 good pieces are in. Fix the two
rows in the workbook, delete the 18 that succeeded, re-run. A jewel code that
already exists is refused, never duplicated and never silently overwritten — so
re-running the whole sheet by accident cannot corrupt anything.

Watch `unpriced_lines`. Anything above zero means a material had no rate card
entry for that size band, so that line costs nothing and your stock value is
understated. The piece still imports — I would rather you see it than have it
rejected — but it is a number to chase.

### Two columns worth understanding

| Column | Leave blank and… |
|---|---|
| `cost_rate` on sheet 2 | the rate card is used. Fill it only when *this* piece was bought at a rate that is not your standard card. |
| `qty` on a MAKING row | making is charged on **net metal weight**, computed after the gold lines are read. This is the correct behaviour — do not put a number here. |

Gold sale rate is never taken from the sheet. It is always `pure 24K × sale
purity` at the moment anyone looks at the piece. That is what makes the price
live.

---

## Route 2 — One piece, right now, by hand

Supabase → SQL Editor:

```sql
select jsonb_pretty(app.add_piece('{
  "jewel_code":"ER00124", "style_code":"ER00135", "category":"Earrings",
  "design_name":"Emerald floral polki earring",
  "karat":"14K", "colour":"Yellow", "quality":"VS-SI",
  "gross_wt":12.370, "location":"MUM", "received_on":"2026-08-12",
  "lines":[
    {"material":"DRKL SI-I","size_band":"+2","pcs":10,"qty":0.09,"uom":"CT"},
    {"material":"G","qty":9.51,"uom":"GM"},
    {"material":"MAKING","uom":"GM","basis":"BY_NET_METAL_WT"}
  ]}'::jsonb));
```

`style_code` may be a design you already have — that is the normal case, a
second piece of an existing design. `category` is only needed when the design
is new.

---

## Route 3 — The Add Piece screen

`nornament_stock_entry.html`. Double-click it, or drag it into a Chrome tab.
No install, no server, nothing to host.

It is not a mock. Every button calls the same functions as routes 1 and 2,
through your own login, and the permissions are enforced by the database rather
than by the page. A Sales login is turned away at the door — and if someone
skips the page and calls the API directly, all five write functions still
refuse them.

Nothing is stored inside the file. Close the tab and you are signed out.
That is intentional for a machine on a shop floor.

---

## What the database will refuse, and why

Tested, all of these come back as readable English rather than a Postgres error:

| You wrote | It says |
|---|---|
| a jewel code that already exists | *already exists. One piece per jewel code — use a new code.* |
| `Erings` | *Category "Erings" not found. Known: Earrings, Necklaces, Rings, …* |
| `G14K` | *material code "G14K" is not in your material master* |
| `9K` | *Karat "9K" is not set up. Known: 14K, 18K, 22K, 24K* |
| no material lines | *A piece with no materials has no cost and no price.* |
| `Delhi` | *Location "Delhi" not found. Known: HO, KOL, MUM, WS1* |
| gold in carats | *Metal line 1 must be GM, got CT* |

The material master holds **`G`** and **`GC`**, not `G14K`. Gold carries no
karat — the karat lives on the piece. This is what stopped an 18K piece
displaying a 14K rate earlier.

---

## The one thing to do before the other 980

Enter the 20. Read `unpriced_lines` and the sheet-3 weight check. That is the
afternoon that tells you whether your material codes and size bands actually
reconcile — and it is much cheaper to find out at 20 pieces than at 1000.
