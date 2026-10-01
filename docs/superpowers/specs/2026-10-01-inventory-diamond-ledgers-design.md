# Inventory part 4 — the diamond ledgers

**Status:** approved by the owner, 2026-10-01
**Builds on:** `2026-09-30-inventory-diamonds-design.md` (part 3: diamond lines, codes, rate card, Search, Settings) and `2026-10-01-inventory-stones-ledger-design.md` (part 2: `StockDocument`, the ledger engine, settle and reversing movements)

## What this part is

Part 3 made diamond stock searchable; nothing in the app can move a diamond except the importer's recount. This part adds the three diamond ledgers the prototype draws: **Job cards**, **Assortments** and **Purchases**. On the prototype every one of these screens renders and not one control works (`_script.html` `diaJob`, `diaAssort`, `diaPurchase`), so this part makes them work as drawn, on part 2's document and ledger engine.

## Decisions (owner, 2026-10-01)

- **Line cost:** a diamond line can carry its **own cost per carat** (set by its purchase, carried by weight through an assortment). Every cost and value reads the line's own cost first, then the rate card (per code + size, as now), then "not set". The imported lines have no own cost and keep the rate card.
- **Job cards close by a Close button, only at zero.** A card stays open (more can be issued to it) until someone closes it; Close is allowed only when it balances. A closed card takes nothing more; Undo last entry can reopen it.
- **Assortment destinations become new lines**; weight that stays in grade simply stays on the source line.
- **No assortment drafts:** one screen with a live balance line; it posts only when it balances.
- **Purchase lines are described, not coded:** category, shape, colour, clarity and size; the item code is found, or created and confirmed, from shape + colour + clarity.
- **Approach:** extend part 2's ledger engine so a movement's owner is a pouch **or** a diamond line, and add three diamond document kinds. No parallel diamond ledger.

## Data

- **`StockDocument.kind`** gains `dia_job`, `dia_assort`, `dia_purchase` (numbers `JC-…`, `AS-…` automatic; a purchase's number is the supplier's invoice no. or automatic `DP-…`). Stones lists and screens filter to stones kinds, so the two never mix.
- **`DiamondLineCost`** (new, `inv_dia_line_cost`): `line`, `cost_rate` (per ct, INR, 4 places), `effective_from`, `set_by`, `document` (the purchase or assortment that set it, null for a manual change). Latest wins. `dia_services.price(line, …)` returns the line's own latest cost when there is one, else the rate card's (exact size, then any size); sale stays on the rate card.
- **`Movement.Reason`** gains `Returned Unused`, `Assort Out`, `Assort In`.
- **The ledger engine** (`inventory/ledger.py`) is generalised from pouches to "pouch or diamond line": its line, checks (balance not below zero; for diamonds carats are the quantity, pieces optional and unchecked), locking, outstanding, reversal and undo work for either owner. Stones behaviour is unchanged — part 2's tests are the proof.

## Rules

1. **Job card** (`dia_job`, karigar from the shared supplier list or blank for **In-house**, opened date, note):
   - **Issue to job card** — out from a stocked line (reason Job Work Out).
   - **Received loose** — in to the line (Job Work In); **Returned unused** — in to the line (Returned Unused).
   - **Consumed / set** (Consumed in Production), **Loss in process** (Wastage / Loss in Process), **Breakage** (Breakage) — settle: they settle what is out without returning it.
   - Each entry has its own date and challan / reference, so one card spans several challans.
   - Outstanding is per line (a credit can't settle another line's carats); the card shows the total.
   - **Close** is allowed only at zero outstanding; a closed card refuses entries; Undo last entry works on an open or closed card and reopens it when something is outstanding again.
2. **Assortment** (`dia_assort`, date, reason note):
   - One source line and the carats taken out of it (Assort Out).
   - Destination rows (shape, colour, clarity → code found or created; size; carats; optional cost per ct override), each becoming a **new line** (Assort In) with the source's category and batch no.
   - Sorting loss — written off on the source (Wastage / Loss in Process, out).
   - Must balance: taken out = destinations + loss, to 4 places.
   - **Cost:** the parcel's cost is kept whole — each destination's cost per ct = source cost per ct × taken out ÷ (taken out − loss), unless overridden; written as `DiamondLineCost` rows. A source with no cost at all gives destinations no own cost (they fall back to the rate card).
3. **Purchase** (`dia_purchase`, supplier, date, invoice no., currency INR/USD with rate for USD, landed extras in INR):
   - Each line: category, shape, colour, clarity, size, optional pieces, carats, cost per ct, optional batch no.
   - The code is found or created (confirmed) from shape + colour + clarity; the band from the size (part 3's rules).
   - Each line becomes a **new diamond line**: an in movement (Purchase) and its own cost per ct = cost × rate + extras spread by weight.
   - Never sets a sale price; never writes the rate card.
4. **Corrections:** Reverse works on every diamond document (refused if any balance would go negative, or, for a purchase or assortment, once a line it created has moved since); Undo last entry works on job cards.
5. **Checks on every post** (each a plain message on its form): no line below zero; credits on a job card can't exceed what that line has outstanding on it; Close only at zero; nothing posts to a closed or reversed card; an assortment must balance and every destination needs carats; a purchase line needs category, shape, colour, clarity and size; USD needs a rate; at most 4 decimal places; lengths within their columns; the right for the action. One transaction per post.

## Screens

Each follows the prototype's layout (`diaJob`, `diaAssort`, `diaPurchase`), prose stripped as in parts 1–3, every control working; part 1's shell, CSS, dark mode and phone layout.

1. **Job cards** (rail, diamond sub-nav, "⚒ Job card" on Search): card picker (open by default, switch to include closed), karigar, opened, status chip ("balanced — can close" / "{x} ct outstanding"); the ledger (Date · Stock control · Line · Ref · Debit (ct) · Credit (ct) · Balance · By, Totals); "Post an entry" (the six stock-control options; a line picker — any stocked line for an issue, the card's outstanding lines for credits; carats; date; challan / ref; Post); "＋ New job card"; Close (only at zero); Undo last entry; Reverse.
2. **Assortments** (rail, sub-nav, "⇅ Assort"): picker of posted assortments and each ledger (Code · Movement — Assort out / Assort in / Sorting loss · Note · Debit · Credit · Running, Totals); "＋ New assortment": source line and carats out, destination rows with "＋ Add destination", sorting loss, the live balance line ("{x} ct unaccounted — cannot post" / balanced), Post assortment.
3. **Purchases** (rail, sub-nav, "＋ Purchase", and the diamond **Purchase** tab): supplier (from the list; "＋ New supplier" for Edit settings + supplier-sight holders, as on stones), date, invoice no., currency (+ rate), lines (Category · Shape · Colour · Clarity · Size · Pieces · Carats · Cost / ct · Cost, "＋ Add line"), landed extras, "What posting will do", Post purchase, and "Recent purchases".
4. Rail counts become real (open job cards; assortments posted); Settings' supplier "Purchases" counts purchase documents. The diamond **Movements** and **Stock take** tabs stay padlocked.

## Rights and masking

| | Right |
|---|---|
| See job cards | every internal role (read-only without the right; the prototype's "read only for Sales") |
| Post / close / undo / reverse a job card | Job cards (`inv_job`) |
| See and post assortments | Assort (`inv_assort`); others see "Not permitted for {role}" |
| Purchases | Record purchases (`inv_purchase`) + `view_cost` + `view_vendor` |

- Karigar names (`karigar_name`) need `inv_job`; supplier names need `view_vendor`; any cost or value (the assortment's override column, purchase costs, line values) needs `view_cost`. Job cards show no money. Templates test key presence.
- **"Viewing as":** the pages render as the previewed role (read-only or "Not permitted"); forms are hidden while previewing; posting always acts as the real user.
- Diamonds have no client view.

## Testing

`inventory/tests/`, earlier parts' conventions:
- Services, per rule: job card (issue, partial return, returned unused, consumed, loss, breakage; per-line outstanding; can't close early; close; refuses after close; undo reopens; reverse); assortment (balances; new lines; stays in grade; loss; cost carried with loss absorbed; override; no-cost source; refused unbalanced; reversal refused once a new line moved); purchase (new lines; code found or created; INR and USD cost with extras; rate card untouched; sale untouched).
- Line cost: own cost wins over the rate card, rate card as fallback, "not set" otherwise — on Search, values and margin.
- The ledger engine: every part 2 stones test still passes unchanged; the ledger invariant extended to diamond lines.
- The masking walk covers every new screen and write, per role and in the "Viewing as" preview.
- Still green: the real diamond file (281 lines, 546.96 ct, cost ₹1,47,98,794) and the prototype parity test.

## Out of scope

The diamond Movements and Stock take tabs, price lists, part 5's items, and linking job cards to finished pieces in the stock app (the standalone rule keeps that for later).
