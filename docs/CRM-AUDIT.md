# CRM audit — legacy (`legacy/CRM/nornament-crm.html`) vs. deployed Django `crm/`

Method: full read of the 8,552-line legacy React app (55 components), its
`DESIGN.md` and its 845-line standalone quote calculator, against `crm/`
(views, models, forms, services, 32 templates), `templates/crm_base.html`,
`static/css/crm.css` and `static/js/crm-upload.js`. No code changed.

Headline: the **shell, visual language and data model are faithful**. The gaps
are (a) capture-time affordances — photos and bulk import — that the legacy app
did inside its modals, (b) the quote calculator, which is a stub next to the
original, and (c) mobile, which regressed from card layouts to scrolling tables.

---

## 1. Already faithful — no work needed

| Area | Evidence |
|---|---|
| Stylesheet | `static/css/crm.css` lines 5–224 are byte-identical to legacy lines 19–302, including both media queries. |
| Shell | Sidebar sections (Dashboard / CLIENTS / PIPELINE / NETWORK / TOOLS), page header + subheader, badge counts, mobile bottom nav, "More" bottom sheet. |
| Customer profile | All 12 tabs present and in legacy order: Overview, Timeline, Purchases, Outreach, Orders, Enquiries, Client Mat., Repairs, Gifting, Occasions, FoN, Docs. |
| Pipeline detail | Stage strip, "Lost/Cancelled" red state, status-update form, status timeline, media panel — field-for-field with `EnquiryDetail`/`OrderDetail`/`RepairDetail`/`ClientMatDetail`. |
| Conversions | Enquiry→Order (same `status == 'Order Confirmed'` gate), Material→Order, Material→Repair, each writing a `StatusEvent`. |
| Code generation | `NOR-`/`ENQ-`/`ORD-`/`REP-`/`CM-` + zero-padded counter, same as legacy `gc/gEnq/gOrd/gRep/gCM`. |
| Lead-gap engine | `services.lead_gaps` reproduces `leadGaps` — overdue / no-follow-up / stuck >21d / stale >45d, same labels, same badge colours. |
| Computed temperature | `services.computed_temp` + the "Engine suggests…" chip = legacy `computedTemp` + `SuggestTemp`. |
| Dashboard | Superset. Gaps panel, 5 temp counters, value/revenue tiles, four module strips, per-kind reminder horizons (30/30/60/90d) and "Wish on WhatsApp". |
| Reports | Superset. Adds all/stock/CRM revenue split, margin, orders-by-status, open pipeline. |
| FoN | Superset. Three-level tree, slab table, monthly payout breakdown, plus an orphan ("unparented member") report the legacy silently allowed. |
| Search | `services.search` indexes customers, enquiries, orders, repairs, materials, with HTMX live results. |
| Quick actions | WhatsApp deep-link + `tel:` on customer, gaps rows and reminders. |

---

## 2. Deliberate divergences — confirm, do not "fix"

1. Purchases are `stock.Sale` rows (`source='CRM'`), not `customer.data.purchases[]`. One ledger — the stated point of the rewrite.
2. The quote calculator reads live `MetalPurity`/`Metal` rates, so 925 silver prices off silver. The legacy hardcoded table was the bug.
3. The customer form's six tabs were flattened to one scrolling page (documented: tabs hide validation errors on tabs you are not looking at).
4. Kanban moves a card with ‹ › buttons instead of drag-and-drop.
5. Money is masked by capability (`view_sale`, `view_cost`, `view_vendor`). The legacy CRM had no masking at all.
6. A STOCK section was added to the sidebar — the CRM is no longer a separate deployment.

---

## 3. The task list — status

All items below were implemented on 31 Aug 2026 except where marked. Full suite green (226 tests, 24 new).

| # | Item | Status | Where |
|---|---|---|---|
| T1 | Settings unreachable | done | `templates/crm_base.html` — sidebar ADMIN + More sheet; Django admin moved to its own entry |
| T2 | No photos on create/edit forms | done | `mediahub/services.attach_uploads`; forms post `multipart/form-data`, files land after the row saves |
| T3 | Purchase lost remarks/photos/edit | done | `Sale.remarks` (migration `stock.0006`), `crm:edit_purchase`, photos on both purchase forms |
| T4 | No FY filter on Purchases | done | `_financial_years` / `_financial_year_bounds`; Apr–Mar chips on the tab |
| T5 | Invoice OCR import | done | `static/js/crm-invoice.js` — pdf.js for PDFs, tesseract.js on demand for photos, legacy regexes ported verbatim |
| T6 | Mass customer upload | done | `crm/imports.py` + `crm/templates/crm/import.html` |
| T7 | Bulk purchase upload | done | same, with the legacy's fuzzy header aliases and `catFromStr` category inference |
| T8 | Documents & KYC | done | `MediaKind.DOCUMENT`, widened `accept`, the `.doc-grid` the stylesheet already carried |
| T9 | Quote calculator was a stub | done | `static/js/crm-quote.js` + `crm/quote.stone_rates` — multi-item, multi-component, back-solve, print, letterhead, Gati import, attach-to-enquiry |
| T10 | Export thinner than legacy | done | 28 columns (31 with money); `creditLimit`/`outstandingBalance`/`tier` read from `extra` — **still no column of their own, see below** |
| T11 | PWA gone | done | manifest + service worker + share target; **offline write queue deliberately skipped** |
| T12 | Search not global | done | moved into the page header, `/` shortcut |
| T13 | Mobile lists were scrolling tables | done | `_mobile_customers.html`, `_mobile_pipeline.html` — the `.mob-card` / `.stage-bar` CSS finally has markup |
| T14 | Login screen | **not done, deliberately** | see below |
| T15 | Reports lost its bars | done | `.bar-track` / `.bar-fill`, peaks computed in the view |
| T16 | Pipeline forms a flat grid | done | `paired_fields` filter — textareas full width, short fields two-up |
| T17 | Related people only after saving | done | inline rows on the create form, `_save_inline_people` |
| T18 | No quick-add customer | done | `crm:quick_customer`, returns to the form with the new customer selected |

### T14 — left alone on purpose

The audit called the login "the stock app's, not the CRM's". Looking at it
running: the shared gate is already a dark screen with the Nornament wordmark
and the gold button — the legacy CRM's aesthetic, on the one login this app
has. Forking it into a second CRM-only login would add a screen to maintain and
a second place for auth to go wrong, to change colours that are already right.
Not worth it. Say so if you disagree and want the legacy gradient exactly.

### Still open

- **`creditLimit` and `outstandingBalance` have no column.** The export now
  reads them out of `Customer.extra`, so the data is not lost and the sheet is
  complete. Promoting them to real columns is a data decision (are they still
  maintained?) rather than a port gap — flagging, not guessing.
- **The offline write queue is not rebuilt.** The legacy queued writes in
  localStorage and replayed them on reconnect. Against server-rendered pages
  that means reimplementing every form as a client-side mutation with conflict
  handling — a large, risky surface for a shop with wifi. The PWA installs and
  receives shares; it does not pretend to work offline.
- **Per-item photos on a quote.** The legacy attached an image to a quote line
  for the printed sheet. The quote is a scratchpad with no server row to hang
  media on, so this went out of scope with the rest of the persistence.

### Notes on the new code

- `pdf.js` joins htmx as a **vendored, uncommitted** asset — `manage.py
  vendor_assets` fetches both, the Dockerfile runs it at build. Nothing
  third-party is in the repo.
- The import preview posts the CSV text back on confirm rather than parking it
  in a session, so what gets written is exactly what was on screen.
- The share target needs the service worker: a share POST arrives cross-site,
  so `SameSite=Lax` withholds the session cookie and the request would reach
  Django logged out. The worker stashes the files and 303s to a GET.
- Two bugs found while testing and fixed: the CSV BOM survived the confirm
  round-trip, and on mobile the desktop status toolbar rendered alongside the
  new stage bar.
