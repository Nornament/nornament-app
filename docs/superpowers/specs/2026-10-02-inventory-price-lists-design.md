# Inventory price lists (part 5b) — design

Part 5b of the Nornament inventory. Unlocks the two padlocked Commercial rail
items, **Price list — cost** and **Price list — selling**, on the stones side.

## Where this comes from

The prototype never draws a price-list screen: both rail items route to the
Purchase screen, whose "Price list" card only explains the idea — cost and
selling are different numbers with different owners, kept as dated rows so a
revaluation never overwrites what was paid (`nornament-ui-mockup.html:1845-1863`).
The app already stores exactly that: `PriceEntry` (valuation / purchase / list,
per carat, dated, `set_by`), one pouch at a time from the pouch's price card
(`views.pouch_price` → `services.add_price`). What is missing is a screen to
see and set prices across many pouches at once. The owner chose:

- **List + set by group** — a filterable pouch table; one per-carat price set
  for the whole filtered group, each pouch getting its own dated row.
- **Stones only** — diamonds keep their rate card in diamond Settings
  (`#rates`); each price list links to it. No diamond section.

## Screens

One view, two modes, sharing filters and paging:
`/inventory/prices/cost/` and `/inventory/prices/selling/`
(URL names `inventory:prices_cost`, `inventory:prices_selling`). Both render
through the stones shell (`_page`, the rail, its counts) with the rail item
highlighted.

### Filters (both modes, GET)

- **Stone** — text, case-insensitive *contains* on `stone_name`.
- **Colour, Shape, Quality, Size** — selects of the distinct non-blank values
  of `colour`, `shape`, `quality`, `size_text` across all pouches, exact match.
- **Batch** — text, case-insensitive *starts with* on the batch code.
- **Box colour** — select of box colours, exact match.
- **In stock only** — checkbox, on by default (`on_ct > 0` or `on_pcs > 0`).
  Unticked shows every pouch, including empty ones.

Rows come from `services.stocked()` (which already carries `on_pcs`, `on_ct`
and `rate`, the latest valuation), filtered in the database, in its order
(batch code, then arrival). **200 rows a page** (Django `Paginator`, `?page=`),
filters kept across pages. The foot shows the filtered count and, where the
viewer may see it, the filtered total value.

### Cost list (`mode = cost`)

Columns: **Pouch** (NRN ref linking to the pouch page, then `batch · pouch no.`),
**Stone**, **Size**, **Ct on hand**, **Purchase /ct** (latest purchase price),
**Valuation /ct** with its effective date (latest valuation), **Value**
(ct on hand × valuation, blank when either is missing — never zero).
Foot: count, total value of the filtered set.

Group form (only for those who may set, see Rights):
"**Set valuation** ₹/ct ___ effective from [date, default today] — **Set for N pouches**".

### Selling list (`mode = selling`)

Columns: **Pouch**, **Stone**, **Size**, **Ct on hand**, **List /ct** with its
effective date (latest list price), **List value** (ct × list /ct), and
**Margin** — `(list − valuation) / valuation × 100`, one decimal and a `%` —
blank when either rate is missing or valuation is zero.
Foot: count, total list value of the filtered set.

Group form: "**Set list price** ₹/ct ___ effective from [date] — **Set for N pouches**".

### Diamonds

Each mode's header carries a link, **"Diamonds price by the rate card →"**, to
`inventory:dia_settings` `#rates`. Nothing on the diamond side changes.

## Rights, masking, client view

| | open the list | set by group |
|---|---|---|
| Cost list | `view_cost` | `inv_masters` + `view_cost` |
| Selling list | `view_sale` | `inv_masters` + `view_sale` |

These are the rights `services.add_price` already demands for one pouch.

- A viewer without the right sees the rail item padlocked; the URL is refused
  by `require()` (403), as the stones Purchase screen does.
- **Client view**: both rail items are padlocked (cost stays hidden as today)
  and both URLs redirect to the shelf before reading anything. A client never
  sees a price, as in the prototype ("enquire for price").
- Every row passes through `stock.masking.mask()`, templates test key
  presence. Keys, all already in the masking table: `purchase_rate`,
  `valuation_rate`, `pouch_value` (cost), `list_rate` (sale), `margin`
  (`view_margin`). **List value** is computed after masking, only when
  `list_rate` survived, so the masking table is not touched. The Margin column
  shows only to a viewer holding `view_margin`; it also needs the valuation,
  so it is blank for a viewer without `view_cost`.
- The masking walk (`inventory/tests/test_masking.py`) covers both new URLs.

## Setting a price for a group

`services.set_group_price(user, pouches, kind, rate, effective_from)`:

- Same rights as `add_price` for the kind; `kind` is `valuation` (cost list)
  or `list` (selling list) — purchase prices come only from purchases.
- Refuses: a rate that is not a positive number, at most ten digits before the
  point (zero is refused, unlike one-pouch entry, since a group at zero is
  almost certainly a slip); a future effective date (the latest dated row is
  the current price, so a future date would take effect at once); an empty
  group ("No pouch matches these filters.").
- Writes one `PriceEntry` per pouch in the filtered set — all pages, not just
  the one shown — with `bulk_create`, in one transaction, `set_by` the user.
  Nothing is overwritten.
- One activity-log entry for the group, e.g.
  `"list 1250/ct on 438 pouches (stone ~ 'ruby', in stock)"`.
- The POST carries the filters; the view rebuilds the same filtered queryset
  from them, and the confirmed count posted with the form must equal the
  rebuilt count, else nothing is written and the page says the stock changed
  ("The group changed since the page loaded — check the count and set again.").
- Success redirects back to the same filtered list with a message
  ("List price set on 438 pouches.").

`add_price` and the pouch price card are unchanged.

## Out of scope

Adjusting prices by a percentage, export, a client-visible list price,
per-piece pricing, any diamond-side change, any new table.

## Tests

- Filters narrow correctly (each filter; in-stock default; paging keeps filters).
- A group set writes exactly N dated rows across pages, one log entry, and the
  pouch price card then shows the new price.
- Refusals: no right, zero / negative / huge rate, future date, empty group,
  count mismatch — each writes nothing.
- Rights: rail live vs padlocked per role; denied page without the right;
  the set form hidden without `inv_masters`.
- Client view: both padlocked, both URLs redirect.
- Masking walk covers both URLs (purchase / valuation / list / margin values
  absent for roles without the right, present for one with it).
