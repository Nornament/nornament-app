# Inventory merge (part 5c) — design

Part 5c of the Nornament inventory: merging stone pouches, the counterpart of
the split (part 2). Branched from part 5b (`feat/inventory-price-lists`).

## Where this comes from

The prototype never draws a merge screen. Its schema spec makes it a
requirement: "Split and merge are not optional … Without `parent_lot_id` and
Split/Merge movements, staff will edit quantities by hand and the audit trail
dies in week one" (`03-spec/Nornament_Schema_Spec_v1.1.md:200`). The app has
the reason `Movement.Reason.MERGE` and nothing else; the Splits & merges list
says "Merges join this list when they are built (5c)" (`views_lists.splits`).
The pattern to mirror is `ledger_assort.split_pouch` and `views_assort.split`.

Owner's rulings (2026-10-04):

- **Destination — either, chosen each time:** one of the merged pouches, or a
  new pouch.
- **Eligibility — same batch, same stone:** same batch, and the same
  `stone_name`, `colour`, `shape` and `quality` as typed. Size may differ.
- **Whole pouches, weighted rate:** every source is emptied completely (split
  it first to take part of one); the merged pouch's valuation is the
  carat-weighted average.

## Screen

**⤵ Merge** button beside **⤴ Split** on the pouch page and its Movements tab,
for `inv_assort` holders, never in client view. It opens
`/inventory/pouches/<ref>/merge/` (URL name `inventory:merge`), in the stones
shell with the Movements tab highlighted, like the split.

The form:

- **Candidates table**: the opening pouch and every other pouch that may join
  it — same batch, same stone name, colour, shape and quality, something on
  hand (`on_ct > 0` or `on_pcs > 0`). Columns: tick box, pouch
  (`batch · pouch no.`, NRN ref), pcs (or "uncountable"), carats, size, and
  valuation /ct for `view_cost` holders only. The opening pouch is ticked by
  default; the others are not.
- **Merge into**: a radio per candidate ("this pouch") plus **A new pouch**
  with a pouch-no. box, prefilled with `ledger.next_pouch_no(batch)`.
  Default: the opening pouch.
- **Size of the merged pouch** (text, prefilled with the opening pouch's size).
- **Loss**: pcs and carats, optional. **Note**, optional.
- Button **Post merge**. A posted merge redirects to its document page with
  "Merge posted as MRG-…".
- A refusal re-renders the form with the error and the ticks kept.

If the opening pouch has no other candidate, the page says
"No other pouch in this batch holds the same stone." and shows no form.

## Ledger

New `StockDocument.Kind.MERGE = "merge", "Merge"` (migration: the kind's
choices), numbered `MRG-`, right `INV_ASSORT`, added to `STONE_KINDS` and
`RIGHT_FOR_KIND`; `Reason.MERGE` added to `ledger.CREATING` so a reversal finds
a pouch the merge created.

`ledger_assort.merge_pouches(user, pouches, into, new_pouch_no="", size_text="", loss_pcs=None, loss_ct=None, note="")`:

- `pouches` are the ticked pouches; `into` is one of them or `None` for a new
  pouch.
- Posts, on one Merge document:
  - for each source that is not the target, **Merge OUT** of its whole on-hand
    balance (pcs only when counted);
  - **Merge IN** on the target of the sum of those;
  - when a loss is given, **Wastage OUT** on the target ("Loss in the merge").
- A new target is made with `ledger.new_pouch` in the batch, under the given
  number, copying `split`'s `COPIED` fields from the first source, with the
  entered size; `parent` stays empty (a merge has many parents; its document
  names them).
- An existing target keeps its NRN ref, photos, prices and history; its size
  becomes the entered size if one is given.
- Emptied pouches stay on record at zero.

### Valuation

After posting, the target gets a new dated `PriceEntry` of kind valuation, at
the carat-weighted average rate of everything now in it **before the loss**:
Σ(ct × rate) / Σ ct over the sources and, for an existing target, its own
stock — rounded to 4 places. When any of those carries weight but no valuation,
no row is written and the success message adds
"— no valuation set: one of the pouches had none." List prices are not carried:
a new pouch has none; an existing target keeps its own.

### Refusals (each writes nothing; `ServiceError` message shown on the form)

- fewer than two pouches ticked — "Tick at least two pouches to merge.";
- pouches from more than one batch, or differing in stone name, colour, shape
  or quality — "Only pouches of the same stone in the same batch merge.";
- a ticked pouch with nothing on hand — "<pouch> is empty.";
- counted and uncounted pouches together — "Count <pouch> first: counted and
  uncounted pouches do not merge.";
- a ticked pouch with stone still out on an open job work or memo
  (`ledger.owed_by_document` over open `OPENABLE` documents) — "Settle <doc>
  first: <pouch> still has stone out on it.";
- `into` not among the ticked pouches;
- a new pouch number blank or taken in the batch (split's wording);
- a loss larger than the total being merged, or negative.

Rights: `require(INV_ASSORT)` → 403. Client view: the URL redirects to the
shelf before reading anything, GET or POST.

## Reversal

The document page's existing **Reverse** works on a merge through
`ledger.reverse_document`: refused when the merged pouch (if new) has moved
since; otherwise the emptied pouches get their stock back and the target loses
it. Reversing a merge whose target was an **existing** pouch also writes a
valuation row on the target at its rate from before the merge (the latest
valuation created before the merge document), so the average does not linger.
A merge into a new pouch leaves the new pouch at zero with its valuation, as a
reversed split leaves its children.

## Splits & merges list

`/inventory/splits/` lists merges too, newest first, with a **Kind** column
(Split / Merge). For a merge, **Out of** lists the sources emptied and **Into**
the target; the carats column is what went in (the sources' total). A reversed
merge reads Reversed. The docstring's "(5c)" note goes.

## Out of scope

Partial merges, merging across batches or stones, carrying list prices, an
undo-last for merges (reverse the document instead), any diamond change.

## Tests

- Merge into an existing pouch and into a new pouch: quantities, NRN refs,
  copied fields, size, emptied pouches at zero, one document, `MRG-` number.
- Weighted valuation (including the target's own stock, before the loss); no
  row when one pouch is unvalued; loss posted as Wastage on the target.
- Every refusal writes nothing.
- Rights (403), client view (redirect), the button shown only to `inv_assort`
  and never in client view; the masking walk covers `inventory:merge`
  (valuation hidden from roles without `view_cost`).
- Reversal: stock back on the sources; the target's prior valuation restored
  for an existing target; refused when a new target has moved since.
- The Splits & merges list shows both kinds; the Recent movements kind filter
  offers Merge.
