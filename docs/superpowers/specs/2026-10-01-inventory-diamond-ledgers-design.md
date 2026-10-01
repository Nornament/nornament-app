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
- **Controller rulings made during the build (2026-10-01, Task 10's walk).** Clarity may be left blank only for a Fancy colour — in `code_for`'s lookup and creation, in a purchase line's required fields, and in an assortment destination's required fields — because the owner's file holds many fancy lots (DFY, DFO, …) whose codes carry no clarity. Job cards are numbered `JC-000001` and upward, matching assortments' `AS-000001` and purchases' `DP-000001` under part 2's `ledger.next_number`.

## Owner rulings and review fixes (2026-10-02)

- **A re-import leaves a line the ledgers have moved alone (owner).** Once a line has any movement on a job card, an assortment or a diamond purchase (a line a purchase or an assortment created always has), the register no longer counts it the way the app does: carats may be out on a card or taken by an assortment. When the file's carats differ from what such a line holds, the review screen shows it under "Lines the ledgers have moved" with the choice "moved in the app since — leave as is" (the default) or "recount to the file"; only an explicit "recount to the file" posts a recount. Such a line missing from the file defaults to "leave as is" and is labelled "moved in the app since". New lines in the file still come in, and a line no ledger has touched recounts exactly as before.
- **A blank destination size keeps the source's sizing.** An assortment destination left at the source's size takes the source's size, band and carat range as they stand, so a line banded by weight per stone keeps its band rather than reading as "?".
- **A destination in the source's grade is refused.** A destination whose item code and size are the source's own is refused: weight that stays in grade stays on the source.
- **The engine checks owner against kind.** A pouch moves only on a stones document and a diamond line only on a diamond one; anything else is refused before a movement is written.
- **No future dates.** A job card's opening date, a job-card entry, an assortment and a diamond purchase cannot be dated after today ("A date can't be in the future.").
- **Costs too large to keep are refused.** A purchase's landed cost per carat (cost × rate + extras) or an assortment's carried cost per carat of ₹10,00,00,00,000 or more is refused rather than overflowing the column.
- **Reversing a diamond purchase** needs every purchase right (record purchases, sight of cost, sight of suppliers), as recording one does.
- **The stones pouch ledger's reason filter** lists stones reasons only, never Returned Unused, Assort Out or Assort In.
- **Known limit.** A purchase size that fits no band and has no pieces to divide by lands in band "?", as an imported line does; it is corrected in Settings.
