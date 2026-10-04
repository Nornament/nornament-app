# Inventory client lookbook (part 5e) — design

Part 5e of the Nornament inventory: curated selections of stones shared with a
client by a private link. Branched from part 5d (`feat/inventory-stock-take`).

## Where this comes from

The prototype's **Client lookbook** is an inert rail item
(`nornament-ui-mockup.html:501`). Its client experience is the **👁 Client
preview** over the shelf and pouch pages — already built here, server-side
(`rows.CLIENT_HIDDEN`, `views._client`). The prototype never shows a client a
price, only "Available — enquire for price" and **✉ Enquire**; it gives the
client "an opaque reference instead of your batch code — quoting it would
publish your shelf layout" (`:841-845`). Nothing in the prototype or its spec
describes sharing, links or curated sets.

Owner's rulings (2026-10-04):

- **Curated lookbooks with a share link** — staff build named selections of
  pouches; each has a private link a client opens without a login.
- **Enquire by WhatsApp or email** — no public write, no new CRM tie.

## Staff side

The stones rail's **Client lookbook** comes off its padlock (internal view; in
client view it stays padlocked as today) and opens `/inventory/lookbooks/`
(`inventory:lookbooks`): every lookbook, newest first — title, stones, link
On / Off, last changed. **＋ New lookbook** (title) for `view_sale` holders.

A lookbook — `/inventory/lookbooks/<pk>/` (`inventory:lookbook`):

- Title and **note to the client** (editable), **Link: On / Off** switch,
  the link itself with **Copy link** (a button that copies the absolute URL;
  plain JS, no dialog).
- Its stones in order: photo thumbnail, NRN ref, `batch · pouch no.` (staff
  see it here), stone, size, ct, Available / No longer available, **↑ ↓** and
  **Remove**.
- **Add stones**: one box taking NRN refs or `batch · pouch no.` (several,
  separated by commas or new lines); unknown ones are reported by name, a stone
  already in the lookbook is skipped.
- **Delete lookbook** behind a second press.

On the pouch page, **＋ Lookbook** (for `view_sale` holders, never in client
view) opens a small form choosing a lookbook to add this pouch to.

Rights: every write needs `VIEW_SALE` (403); every internal role may read.
Client view (the staff toggle): every staff lookbook URL redirects to the shelf.
Masking: staff rows go through `mask()`; no money is shown on these pages.

## The client's page

`/lookbook/<token>/` (`lookbook_public`, outside `/inventory/`, no login, GET
only). A standalone template — not the staff shell — reusing
`static/css/inventory.css` classes, phone first: "Nornament", the lookbook
title and note, then a grid of cards in the lookbook's order:

- the first photo (via the token photo route) or a "no photo yet" tile;
- stone name, colour, shape, cut, size, carats, pieces (or "uncountable");
- **Ref NRN-…** (never the batch code or pouch no.);
- **Available** when the pouch has stock, else **No longer available**;
- **Enquire** — `https://wa.me/<LOOKBOOK_WHATSAPP>?text=…` or
  `mailto:<LOOKBOOK_EMAIL>?subject=…`, the text "Lookbook ‹title› — NRN-…"
  URL-encoded. WhatsApp wins when both are set; neither set hides it.

Rows are built with `rows.pouch_row(AnonymousUser(), pouch, client=True)` — the
client preview's own rule — so `CLIENT_HIDDEN` and every gated key are gone
before the template sees them. No price, cost, supplier, box, carton, batch,
pouch no., remarks, source row or stock-control flag ever reaches the page.

A link that is Off, or a token that matches nothing, answers 404 with a plain
"This lookbook is no longer shared." page (the same page for both, so a guess
learns nothing). The page carries `<meta name="robots" content="noindex">` and
an `X-Robots-Tag: noindex` header.

### Photos

`/lookbook/<token>/photo/<media_id>/` (`lookbook_photo`): serves (as the staff
`photo` view does — a presigned redirect named by the NRN ref) only a live
pouch photo whose pouch is in that lookbook and only while the link is On;
anything else is the same 404.

## Settings

`LOOKBOOK_WHATSAPP` (digits, country code first, e.g. `919800000000`) and
`LOOKBOOK_EMAIL`, read from the environment in `config/settings.py`, default
empty.

## Data

- `Lookbook`: `title` (120), `note` (text), `token` (unique, 32,
  `secrets.token_urlsafe(16)` at creation, never shown in lists other than the
  lookbook's own page), `shared` (bool, default True), `created_by`,
  `created_at`, `updated_at`.
- `LookbookStone`: `lookbook` (FK, cascade), `pouch` (FK, protect), `position`
  (int); unique (lookbook, pouch); ordered by position.
- One migration. No stock or CRM coupling.

## Out of scope

Prices to clients, client accounts or logins, a public enquiry form, view
tracking, link expiry dates, diamonds in lookbooks (diamonds have no client
view), lookbook PDFs.

## Tests

- Build: create, add by NRN ref and by `batch · pouch no.` (unknown reported,
  duplicate skipped), reorder, remove, edit title / note, switch the link, delete.
- Rights (403 without `view_sale`), client view redirects, ＋ Lookbook on the
  pouch page only for `view_sale` and never in client view, rail padlock off.
- The public page with a pouch whose every hidden field holds a distinctive
  value (batch, pouch no., carton, remarks, src, valuation, list price,
  supplier): none of them appears; ref, stone and ct do; no login needed.
- Off and unknown links answer the same 404 page; noindex present.
- The photo route serves a lookbook pouch's photo (with storage mocked or its
  "not configured" 503 accepted) and 404s a photo from outside the lookbook or
  with the link Off.
- The Enquire link: WhatsApp text, email fallback, hidden when neither is set.
- The masking walk covers every new URL.
