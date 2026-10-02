# Inventory part 5a — lists and finders

**Status:** approved by the owner, 2026-10-02
**Part of:** part 5 (the remaining padlocked items), split by the owner into 5a lists and finders · 5b price lists · 5c merge · 5d stock take · 5e client lookbook · 5f finished-piece link. This is 5a.

## What this is

Read-only screens over data the app already has, removing nine padlocks: the top search box, the four data-quality filters, the Splits & merges and Transfers lists, the diamond Movements tab with a ledger per line, and the stones Suppliers link. No new tables; every screen uses part 1's shell, CSS, dark mode and phone layout, and ends its rows in `stock.masking.mask()` (templates test key presence).

The prototype has no screen for any of these (its search box is a plain div; the filters, lists and tabs have no handlers; its diamond Movements tab wrongly showed the stones pouch ledger), so these follow the app's existing list and ledger pages.

## Screens

1. **Top search box** (`templates/inventory_base.html`, both sides; internal only — in client view it stays padlocked). Submits `q` to a results page:
   - **Stones:** pouch ref (`NRN-…`), batch code, "batch · pouch no." (e.g. `SL01G · 1` or `SL01G 1`), and stone name (contains, case-insensitive).
   - **Diamonds:** line ref (`NRD-…`), item code (canonical, contains), batch no.
   - Results in two groups — Pouches and Diamond lines — up to 50 each, each row linking to the pouch page or the diamond line ledger; no money on the page. An empty or too-short query (under 2 characters) shows nothing found.
2. **Data-quality filters** (stones rail, the four items with live counts: Misfiled colour, No pouch no., Missing photos, No size in mm): each opens the pouches with that problem, in the existing pouch table, each row opening its pouch. Each list's count equals the rail's live count. Internal only.
3. **Splits & merges** (stones rail): every split document, newest first — number, date, source pouch, new pouches, carats out, by — each linking to its document page; reversed ones shown as reversed. Merges join this list when 5c is built.
4. **Transfers** (stones rail): every transfer document, newest first — number, date, pouch, from batch · pouch no. → to batch · pouch no., by — each linking to its document page.
5. **Diamond Movements tab** (`inventory_base.html` diamond tabs):
   - **The list:** recent diamond documents (job cards, assortments, purchases), newest first, filterable by kind, each opening its own screen (job card, assortment, purchase).
   - **A ledger per line** (`/inventory/diamonds/lines/<ref>/`): the line's details (ref, code, category, shape, colour, clarity, size, band, batch, on hand) and every movement — date, reason, document (linked; import openings and recounts show their source row), in / out / settle, carats, running balance, by — using the shared balance rule (settle counts 0, reversals the opposite sign). Value (own cost first, else the rate card) shows only with the cost right. Search stock's line refs link here.
6. **Suppliers** (stones rail): links to the supplier card on diamond Settings (`#suppliers`) for logins holding Edit settings and supplier sight; padlocked for everyone else.

## Rights and masking

- The lists, the diamond Movements tab and the line ledger are readable by every internal role (as the document pages are); the search results too.
- Supplier and karigar names, customers and cost are masked as everywhere else (`vendor_name`, `karigar_name`, `customer_name`, cost keys).
- None of these screens is reachable in client view (each redirects, as the ledger screens do); diamonds have no client view.

## Still padlocked after 5a

Stock takes (5d), Price list — cost / selling (5b), Merge (5c), Client lookbook (5e), and "＋ Add user" (users are managed elsewhere).

## Testing

`inventory/tests/`, earlier parts' conventions: each screen as an allowed login and in client view; the masking walk and every-screen check extended to the new pages; the search matching rules (each kind of match, the 50 cap, the minimum length); each filter's list matches the rail's live count; the line ledger's running balance equals the engine's on-hand; the Movements list's kind filter; the Suppliers link live vs padlocked by right.

## Changed while planning

- **Routes.** `search/`, `quality/<check>/` (misfiled, no_pouch_no, no_photo, no_size), `splits/`, `transfers/`, `diamonds/movements/`, `diamonds/lines/<ref>/`.
- **The search box** is a small form in the top bar on both sides. It is not the shell's `.search` box, which the phone layout hides, so it works on a phone too. In client view it stays padlocked, and the results page redirects to the shelf. On the diamond side, which has no client view, it is always live.
- **Matching.** A pouch ref, a batch code, a line ref and a batch no. match exactly. A stone name and an item code match by "contains". Case never matters. "Batch · pouch no." is read with or without the `·` (`SL01G · 1`, `SL01G 1`, `SL01G·1`). An item code is read the register's way (`drfgh vs si` finds `DRFGH VS-SI`). Each group shows the first 50 and says "first 50 of N". Pouches and lines with nothing on hand are found too.
- **Data-quality filters** share one predicate per check with the rail's counts (`rows.CHECKS`), so a list always holds exactly the rail's count. They use the batch page's pouch table (now one include) with a Batch column in front. Money shows as on the batch page, by the cost right. An unknown check is 404.
- **Splits & merges and Transfers.** A reversal is not listed on its own; the document it undid carries a Reversed chip. "Carats out" includes the split's loss. The pouches are named as they are filed now. Newest first is by when the document was posted.
- **Diamond Movements.** It lists the newest 100 documents and leaves out reversals, as the two stones lists do. A job card opens on Job cards (`?card=`), an assortment on Assortments (`?doc=`, which only the Assort right can read), and a purchase on Purchases, because a purchase has no page of its own. A line's ledger shows its movements newest first, as the pouch ledger does. On that ledger a reversal's number links to the document it reversed. Value is the cost value only (own cost first, else the rate card), shown with the cost right; the sale side is not shown. Diamond pages ignore the stones' Internal / Client flag, as diamond Search does, and carry an admin's "Viewing as".
- **Search stock** gains a Line column: each `NRD-` ref links to its ledger, carrying the preview.
- **Suppliers** is padlocked in client view as well.
- **Three earlier assertions changed.** They checked padlocks this part removes: the stones Transfers item and the diamond Movements tab (twice). They now check the link.
