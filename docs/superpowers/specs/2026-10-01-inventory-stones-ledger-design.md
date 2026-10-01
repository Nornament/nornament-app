# Inventory part 2 — the stones ledger

**Status:** approved by the owner, 2026-10-01
**Builds on:** `2026-09-28-inventory-overview.md` (build order), `2026-09-28-inventory-stones-design.md` (part 1)

## What this part is

Part 1 made the stones register readable: shelf, batches, pouches, prices, a read-only movement history. Nothing in the app can change a stone's quantity except the importer. This part adds the ways stock really moves: purchases, job work, memos, sales and losses, splitting a pouch, and re-filing a pouch into another batch — plus the two lists that say what is out with karigars and clients.

The prototype draws only two of these screens (the pouch's **Movements** page with its **Record movement** form, and **Record a purchase**), and on the stones side not one of their controls does anything. Split and Transfer exist only as buttons; Job work out, Memo out, Stock takes, Splits & merges and Transfers have no screen at all. So this part makes the drawn screens work exactly as drawn, and designs the rest on the prototype's one working precedent — the diamond job card and assortment (a card cannot close while non-zero; a split must balance).

## Scope

**In:** Record movement (every reason a person posts), Purchase, Split pouch, Transfer to another batch, a document page for each, the **Job work out** and **Memo out** lists, the rail's **Movements** (recent documents), an "Out on job work / memo" figure on the shelf, document reversal.

**Out (stay padlocked):** Stock takes, Merge, the Splits & merges and Transfers lists, Price list — cost / selling, Suppliers, Client lookbook, loading the "Copy of Inward Form" sheet as history (its SKU codes do not map onto pouches yet), and the diamond ledgers (part 4, which reuses this part's document header).

## Decisions (owner, 2026-10-01)

- **Scope:** the four actions plus the Job work out and Memo out lists.
- **Counterparties:** karigars and suppliers come from the shared supplier list (`stock.Vendor`, as part 1); **customers come from the CRM** (`crm.Customer`). This is a deliberate exception to the rule that the inventory shares nothing but permissions with stock and CRM; no other new coupling.
- **Rights:** Job work out/in, consumed and loss → the Job cards right (`inv_job`); Purchase → Record purchases (`inv_purchase`); Split and Transfer → Assort / split and merge (`inv_assort`); everything else → a new right **Record stock movements** (`inv_move`), given to Admin and Accounts by default. All editable in the rights matrix.
- **Goods out:** while goods are out with a karigar or a client they are off the pouch (its balance drops — they are not in the box) and the shelf shows them as **Out on job work / memo**, so what is owned = on shelf + out.
- **Approach:** one document header (`StockDocument`) for every kind, with movements attached.

## Data

### `StockDocument` (new, `inv_document`)

| Field | |
|---|---|
| `kind` | Purchase · Job work · Memo · Split · Transfer · Single |
| `number` | challan no. (job work), memo no. (memo), invoice/bill no. (purchase, sale), or automatic (`SPL-000001`, `TRF-000001`, `MOV-000001`) |
| `status` | Open · Closed · Reversed (Purchase, Split, Transfer and Single are Closed when posted; Job work and Memo open until settled) |
| `vendor` | `stock.Vendor`, null — supplier (purchase, purchase return) or karigar (job work) |
| `customer` | `crm.Customer`, null — memo, sale, sales return |
| `occurred_on`, `expected_back` | dates; `expected_back` for job work and memo |
| `note` | free text |
| `currency`, `fx_rate`, `landed_extras` | purchase only: INR or USD, rate to INR (required for USD), extras in INR |
| `reverses` | null, or the document this one reverses |
| `created_by`, `created_at` | |

`number` is unique per kind among open-or-closed documents of that kind; a reversed document's number may be reused.

### Changes to existing tables

- **`Movement.document`** — null FK to `StockDocument`. Opening balances and import recounts keep it null.
- **`Movement.direction`** gains **`settle`**: recorded against a document, counted against what it has outstanding, never added to a pouch's balance. Used when goods already out are consumed, lost or sold.
- **`Movement.reverses`** — null FK to the movement this one cancels. A reversing movement repeats the original's pouch, direction and quantities; every balance and outstanding sum (stones and diamonds, which share the table) counts it with the opposite sign. One rule covers in, out and settle alike.
- **`Pouch.parent`** — null FK to the pouch a split took it from.
- The `inv_move` capability ("Record stock movements"), added through the add-only role sync (Admin, Accounts).

### What is outstanding

For a Job work or Memo document, per pouch: carats (and pieces) **out** − **in** − **settle**. A document closes itself when every pouch's outstanding is zero, and cannot be closed while any is not. The shelf's "Out on job work / memo" figure is the outstanding carats on open documents, valued at each pouch's current valuation rate (masked like any value).

## Rules, by action

1. **Job work out** — karigar, challan no. (required), date, expected back, pieces/carats from one pouch. Out movement (reason Job Work Out); opens the document. A challan may later take more pouches (another Job Work Out with the same open challan).
2. **Settling job work** — choose the open challan: **Job Work In** (in, back into the pouch), **Consumed in Production** or **Wastage / Loss in Process** (settle). Settling cannot exceed what is outstanding for that pouch on that challan.
3. **Memo out** — customer (CRM), memo no. (required), date, expected back. Out movement; opens the document. Settled by **Memo In** (in) or **Sale** against the memo (settle).
4. **Purchase** — supplier (or "＋ New"), date, invoice no., currency (+ rate for USD), landed extras. Each line: batch, pouch no. (next free suggested), stone name, shape, colour, pieces (blank = uncountable), carats, cost per carat. Posting, per line: creates a **new** pouch (supplier and purchase date set), an in movement (reason Purchase), a `purchase` price row (cost per carat in INR), and a `valuation` row at landed cost per carat (cost + extras spread by weight). Selling price is not set here. A line on an existing batch + pouch no. is refused — give it a new number (known limit).
5. **Split pouch** — from one pouch into one or more **new** pouches in the same batch (pouch no. suggested, editable; size and remarks editable; stone, shape, colour, cut, quality, carton and supplier copied). Optional loss row (Wastage / Loss in Process). Must balance: carats out = carats into new pouches + loss; pieces likewise when countable. New pouches carry the parent's current valuation rate and `parent`. Movements: Split out on the parent, Split in on each new pouch, all on one document.
6. **Transfer to another batch** — re-files the whole pouch: new batch (must already exist) and pouch no. there (suggested). Quantity unchanged; the pouch keeps its `NRN-` reference; the document records from-batch/pouch and to-batch/pouch; one Transfer movement (direction settle, quantity = the balance moved, for the record).
7. **Single movements** (document kind Single, closed on post):
   - **Sale** (from the shelf) — customer, invoice no.; out. **Sales Return** — customer, invoice ref; in.
   - **Purchase Return** — supplier, ref; out.
   - **Breakage**, **Wastage / Loss in Process** (from the shelf), **Sample**, **Consumed in Production** (from the shelf) — note; out.
   - **Recount Adjustment** — the counted pieces and carats; posts the difference (the existing `recount` service), in or out.
8. **Checks on every post** (each a plain message):
   - no pouch balance below zero, in pieces or carats;
   - an uncountable pouch moves by weight only — pieces are refused;
   - challan / memo no. required when goods leave without a sale;
   - settling cannot exceed what is outstanding;
   - a split must balance;
   - a new pouch number must be free in its batch;
   - USD needs a rate; a rate or weight must be positive;
   - the right for the action.
   Every post is one transaction: all of a document's movements, or none.
9. **Corrections** — nothing is edited.
   - **Reverse document** (any kind) posts a reversing movement for every movement on it not already reversed, and marks it Reversed. Refused if any balance would go negative, or if a pouch it created (purchase, split) has moved since. A purchase's or split's new pouches remain, at zero.
   - **Undo last entry** on an open job work or memo reverses its most recent un-reversed entry (a mistaken return, consumption, loss or sale), so one wrong line does not mean reversing the whole challan.
     Also on a challan or memo its settlements closed; undoing reopens it when something is outstanding again (owner, 2026-10-01).

## Screens

Every screen uses the part 1 shell, CSS, dark mode and phone layout. Explanatory prose from the prototype is left out, as in parts 1 and 3.

1. **Pouch → Movements** (exists; unlocked). "＋ Record movement" is the prototype's card, working:
   - **Reason** select: the prototype's 12 (Job Work Out, Job Work In, Sale, Sales Return, Memo Out, Memo In, Purchase, Consumed in Production, Wastage / Loss in Process, Breakage, Transfer to another batch, Recount Adjustment) plus Purchase Return and Sample. Opening Balance, Split and Merge are never offered. "Purchase" and "Transfer to another batch" open those screens.
   - Fields follow the reason (the prototype's labels where it has them: "Pieces out", "Weight out", "Karigar", "Delivery challan no. *", "Date", "Expected back"; "in" for returns; customer for memo and sale; open challan or memo to settle against).
   - "Checks that will run" lists the checks for the chosen reason; the server enforces them.
   - "⤴ Split" and "⇄ Transfer to another batch" work; each ledger row links to its document.
   - A reason the viewer has no right for is not offered.
2. **Purchase** (rail "＋ Purchases", tab "Purchase"): the prototype's header and "Lines in this purchase" table with inputs (plus a Pieces column), "＋ Add line", "What posting will do" totalled live, "Post purchase", and the Price list and Stock control cards.
3. **Split pouch** (from pouch detail "⤴ Split pouch" and Movements "⤴ Split"): source pouch and its balance; destination rows (pouch no., pieces, carats, size, remarks) with "＋ Add pouch"; a loss row; the diamond assortment's balance line ("{x} ct unaccounted — cannot post" / balanced); "Post split".
4. **Transfer to another batch**: target batch, pouch no. (suggested), note, "Post transfer".
5. **Document page**: header (kind, number, counterparty, dates, status chip, outstanding), its movements, outstanding per pouch, actions for open job work (Received back / Consumed / Loss) and memo (Returned / Sold), and "Reverse document".
6. **Job work out** and **Memo out** (rail): open documents — number, karigar or customer, date, expected back, an "overdue" chip after expected back, pieces and carats out, outstanding, value (masked); a switch to show closed.
7. **Movements** (rail): recent documents across all pouches, newest first, filterable by kind.
8. **Shelf**: an "Out on job work / memo" tile beside Stock value.

## Rights and masking

| | Right |
|---|---|
| Job work out / in, consumed, loss; the Job work out list | Job cards (`inv_job`) |
| Purchase | Record purchases (`inv_purchase`) |
| Split, Transfer | Assort / split and merge (`inv_assort`) |
| Sale, sales return, memo out / in, breakage, wastage, sample, consumed, recount, purchase return; the Memo out list | Record stock movements (`inv_move`) |
| Reverse a document | the right for its kind |

- Cost (cost per carat, values) needs `view_cost`, as now; the purchase screen will not post for a login without it.
- Supplier names need `view_vendor`, as now.
- **Karigar names** on job-work documents and the Job work out list are shown to anyone holding `inv_job` — the Karigar desk needs them and has no `view_vendor`.
- **Customer names** need `view_sale` (Admin, Accounts, Sales see them; Production, Karigar desk, Graphic do not).
- **Client view** never shows a counterparty or a reference (the prototype leaks the challan no. there; this does not), and none of these screens is reachable in client view.
- Templates test key presence, never capabilities (part 1's rule).

## Errors

Each refusal in "Checks on every post" is a `ServiceError` shown as a message on the form; a missing right is also a 403 on the page. A closed or reversed document refuses further posts and a second reversal.

## Testing

`inventory/tests/`, part 1 conventions (only database tests carry `django_db`; real role fixtures):
- Services, per rule: job work out → partial in → consumed and loss settle → closes at zero, and cannot close early; memo out → returned → sold settles; purchase (new pouches, cost row, landed valuation, USD rate, refused on an existing pouch no.); split (balances, carries the rate, sets `parent`, refuses unbalanced); transfer (re-files, quantity unchanged, ref kept); every single reason; recount; reversal and its refusals; every check above.
- **Ledger invariant:** after any sequence of posts and reversals, on-shelf + outstanding-out = opening + purchases + returns − everything that left for good.
- **Masking walk:** every new screen joins `test_masking.py`'s walk (cost, supplier, karigar and customer per role; client view) and its every-screen check.
- **Views:** each form as an allowed and a refused role; the reason list offers only what the viewer may post.
- The real stones register still imports unchanged (existing golden test).

## Changed while planning

- **Single documents are numbered `MOV-…`.** A sale's invoice no. (and a return's reference) stays on the movement, because one invoice may cover several pouches and a document's number is unique per kind. A purchase with no invoice no. is numbered `PUR-…`.
- **A reversal is its own document** — the same kind, numbered `REV-…`, `reverses` set, closed when posted; the original becomes Reversed and its number is free again. A reversal cannot itself be reversed. **Undo last entry** posts its reversing movement on the same open document.
- **A split takes an explicit "Take out" quantity** (the whole balance by default); the parent keeps the rest. The loss posts as a Wastage / Loss in Process out on the parent; the Split out carries only what went into new pouches. New pouches also copy category, treatment, origin, purchase date and countability.
- **A transfer keeps its from and to on the document** (`from_batch`, `from_pouch_no`, `to_batch`, `to_pouch_no`), so reversing it files the pouch back — refused if it has been re-filed since or its old number is taken. An empty pouch cannot be transferred.
- **A purchase files into an existing batch, or creates a new one** when the code reads as family · class · number · box colour (owner, 2026-10-01), and needs the purchase right with sight of cost and suppliers; "＋ New supplier…" uses Settings' supplier save (Edit settings right). Landed valuation = cost per ct in INR + extras ÷ the purchase's total carats, both rows dated the purchase date.
- **A document's customer is SET_NULL**, as `stock.Sale`'s is, so the CRM can still delete a customer.
- **Karigar names are gated as `karigar_name` (inv_job), customer names as `customer_name` (view_sale).** A login without sight of suppliers is offered as karigars only those already named on a challan, so the Karigar desk never sees a supplier list.
- **The document page and the rail's Movements are readable by every internal login, masked;** the Job work out list needs Job cards, the Memo out list needs Record stock movements.
- **On Record movement**, Consumed in Production and Wastage / Loss in Process settle a chosen challan (Job cards right), else post from the shelf (Record stock movements right); Sale settles a chosen memo, else is a direct sale. Recount Adjustment there needs Record stock movements; the importer's recount keeps Edit settings, and both share one difference rule.
- **A back-dated movement is stamped noon of its day;** expected back may not precede the date.
- **Undoing the only entry of a job work or memo leaves it closed at zero.**
- **Values out on documents** (shelf tile, lists) sum the valued pouches, as Stock value does.

## Owner rulings and review fixes (2026-10-01)

- A purchase may create a new batch when its code reads as family · class · number · box colour.
- "Undo last entry" works on an open or closed (settled) job work or memo and reopens it when something is outstanding again.
- Refusal messages print carats with up to 4 places, trailing zeros trimmed; an empty post is refused.
- A creating document can be reversed once its later movements are reversed.
- Consumed and Wastage posted from the shelf need Record stock movements; posted against a challan they need Job cards — the form offers only the path the viewer may use.
- A login without `view_vendor` can only name karigars already on a challan, so the Karigar desk cannot start a challan with a brand-new karigar — Admin/Accounts name it first.
- The split screen's live balance line checks pieces too, not only carats.
- Every post locks and re-reads its document first (document, then pouches), so a stale copy cannot settle a document reversed or closed a moment earlier, and two settles of one challan cannot leave it Open at zero.
- Typed quantities take at most 4 decimal places (more is refused, never rounded); numbers, pouch nos. and pouch fields longer than their column are refused in words, and the inputs carry `maxlength`.
- Record movement offers the prototype's "＋ New" karigar on Job Work Out to logins holding Edit settings and supplier sight; it is created in the same transaction as the challan, so a refused post leaves no vendor.
- Invoice and challan numbers are unique per document kind across all suppliers and karigars: two suppliers' "Inv 1" collide, and the second must be typed differently (known limit).
