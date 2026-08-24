# Rewrite Stock + CRM as one Django app on self-hosted Postgres

Supersedes: `PLAN-v1-postgrest.md` (PostgREST + FastAPI sidecar migration). Decision 2026-08-24:
complete Django rewrite instead. The old plan's Phase 0 safety work and cutover mechanics are
carried forward — they were stack-independent all along.

## Context

Two apps, one Supabase project (`uygvzdgdtohqlsaiawxs`):

- **Stock** (`Stock/app/nornament.html`, 6k lines vanilla JS) — server-authoritative. The real
  asset is ~5,900 lines of business SQL: 42 tables in schema `app`, 35 `api.*` functions,
  22 views, 45 RLS policies, a 7-capability model (`sale, cost, vendor, materials, margin,
  adjust, melt`), column masking (a SALES login receives `null` where cost would be).
- **CRM** (`CRM/nornament-crm.html`, 8.5k lines React UMD) — client-authoritative. 6 `public`
  tables shaped `{id, code, customer_id, data JSONB}`, no FKs. Runs locally; photos are base64
  in `localStorage` and exist nowhere else.

Problems being fixed (unchanged from v1): two disagreeing revenue numbers (FoN commission is
paid off a hand-typed `purchases[]` array instead of real sales), and Supabase as a
cost-curve dependency.

## Decisions (made — build within these)

| | Choice |
|---|---|
| Stack | Django 5.2 LTS · Python 3.12 · Postgres 17 · gunicorn + WhiteNoise |
| Frontend | Django templates + HTMX. No SPA, no build step, no DRF |
| Stock schema | **Mirror** the existing `app` schema near-1:1 as Django models |
| CRM schema | **Normalize** the JSONB blobs into real models (the v1 "Phase 7 spine", done natively) |
| Offline | **Dropped.** It was a Supabase-egress workaround, not a requirement |
| Business logic | Moves from SQL functions into Django services, guarded by golden parity tests |
| Media | Contabo S3, boto3 presigned URLs, keys unchanged from R2 |
| Hosting | VPS + Dokploy (Docker Compose + Traefik), one public service |
| Old apps | Archived read-only in `legacy/` as the functional + visual spec |

**What is deliberately discarded:** PostgREST, supabase-js, the FastAPI sidecar design, the
hand-rolled JWT/refresh-token scheme (Django sessions replace all of it), RLS policies and
SECURITY DEFINER functions (their *rules* move to Python, testably), the service worker and
8-hour cache TTL.

**What must survive intact:** every data row, every media object, every password, and the
*behavior* of the security model — masking, capability gates, location scoping. In SQL these
were enforced by 45 policies and 218 `RAISE EXCEPTION` guards; in Django they become
permissions + service-layer validation, and for the first time they get a test suite.

---

## Target architecture

```
            Traefik (Dokploy) ── one hostname, one router
                     │
                     ▼
            web  (gunicorn, Django 5.2, port 8000)
             ├── django.contrib.auth   session cookie, bcrypt hashes imported
             ├── django.contrib.admin  user mgmt, reference data, back-office CRUD
             ├── stock/   pieces · BOM · costing · movements · counts · repairs · melt
             ├── crm/     customers · enquiries · orders · repairs · FoN · reports · quote calc
             ├── mediahub/ presign · confirm · device-backup import
             └── etl/      load_legacy · parity_check   (management commands)
                     │
            postgres 17 ── one database; `legacy` database alongside until cutover
                     │
            Contabo S3 ── media objects (keys unchanged from R2) + nightly pg_dump backups
```

No tokens in JavaScript, no refresh rotation, no cross-tab races: the browser holds one
HttpOnly session cookie and Django middleware does the rest. This deletes the single most
intricate subsystem of the v1 plan.

`ponytail: one Django process, no celery/redis/cache tier. Add a worker queue only if a real
async job ever appears — at five users none does.`

## Repo layout

```
nornament/
  manage.py
  config/            settings.py (env-driven), urls.py, wsgi.py
  accounts/          User, capabilities→permissions, location scoping, must_change_password
  stock/             models.py (mirrors app schema) · services.py · views.py · templates/
  crm/               models.py (normalized) · services.py (incl. FoN slabs) · views.py · templates/
  mediahub/          MediaAsset + presign endpoints + import_device_backup command
  etl/               load_legacy.py · parity_check.py · golden_export.py
  deploy/            docker-compose.yml · Dockerfile · backup.sh
  legacy/            Stock/ and CRM/ HTML apps + old SQL migrations, read-only reference
  docs/              this file, RUNBOOK.md
```

---

## Phase 0 — Pre-flight (unchanged from v1; do first, laptop-only)

These decide the schedule and one of them prevents permanent data loss:

1. **`backupDevice()` on every machine that has ever opened the CRM — today, before anything
   else.** The base64 photos in `localStorage['nornament_media_v4']` are origin-scoped and
   exist nowhere else; iOS Safari evicts after 7 days unvisited. Keep the JSON files. (Snippet
   in `PLAN-v1-postgrest.md` Phase 0.)
2. The four SQL checks against live Supabase: password-hash variant (expect `$2a$10$`), users
   with NULL passwords, `app.sale` row count, CRM orphan `customer_id`s.
3. **Contabo smoke test**: presigned PUT from a browser (CORS), `ResponseContentType` on GET,
   path-style addressing. If browser PUT fails, uploads proxy through Django — a view change,
   not a redesign.
4. Start `rclone copy r2:nornament-media contabo:<bucket>` — idempotent, re-run at cutover.
5. Export `logins.csv` (`id, lower(email), encrypted_password` from `auth.users`). Credential
   file: encrypt at rest, move over ssh, shred after import.

## Phase 1 — Project skeleton + accounts

- `django-admin startproject`, the five apps, pytest-django wired from the first commit.
  Dependencies: `django psycopg[binary] gunicorn whitenoise boto3 bcrypt pytest-django`.
- **Custom `accounts.User`** (username, email, `must_change_password`, `is_active`,
  `legacy_auth_uid`). Password import: write `bcrypt$` + the GoTrue `$2a$10$...` hash into
  `password`, keep `BCryptPasswordHasher` in `PASSWORD_HASHERS` *after* the modern default —
  everyone keeps their password, and Django transparently re-hashes to the stronger default on
  each user's first successful login. Reject >72-byte passwords at the form.
- **Capabilities → permissions.** Seven custom permissions (`view_sale, view_cost, view_vendor,
  manage_materials, view_margin, adjust_stock, melt`) + Groups mirroring `app.role`. Location
  scoping: `User.locations` M2M and a queryset helper `Piece.objects.visible_to(user)` — the
  RLS `visible_locations()` rule, in one place.
- **Masking rule, stated once:** any template or export that renders cost/vendor/margin fields
  gates them on the permission; services never return masked data structures — views decide
  what to show. The permanent regression test (Phase 3) enforces this.
- Django admin registered for reference data (metals, purities, categories, locations, rate
  charts) and user management — this replaces the v1 plan's entire `/admin/*` sidecar surface
  and the `pending_logins` machinery.

## Phase 2 — Stock models + ETL + parity gate

- Models mirror the 42 `app` tables near-1:1 (`jewel_code`, `bom_version`,
  `jewel_material_line`, `stock_movement`, `sale`, `repair_job`, `media_asset`,
  `stock_count`…). Start from `inspectdb` against a restored dump, clean into managed models,
  one initial migration. Money is `DecimalField` everywhere. Keep DB-level guarantees the SQL
  had: FKs, CHECKs, and the partial unique `sale.jewel_code` `WHERE jewel_code IS NOT NULL`
  (v1 risk #8: without it a piece can be sold twice and surfaces weeks later as a phantom).
- **ETL shape:** `pg_restore` the Supabase dump into a *separate database* `legacy` on the same
  cluster; add it as a second `DATABASES` entry. `manage.py load_legacy` reads legacy via
  cursor, writes through the ORM **preserving original PKs**, then resets sequences.
  Wipe-and-reload idempotent — run it nightly until cutover so the final run is boring.
- **`manage.py parity_check` — the go/no-go gate, automated:** per-table row counts, sums of
  every money column, min/max of timestamps, legacy-vs-new. Nonzero exit on any mismatch.
  Replaces v1's hand-run gate queries.

## Phase 3 — Stock services + golden parity tests (the heart of "safely")

Port the logic of the 35 `api.*` functions and the `apply_movement` trigger into
`stock/services.py`: receive/scan/unscan piece, movement ledger (transactional,
`select_for_update`), BOM versioning + `refresh_bom_rates`, costing, sale, melt, the
stock-count engine, repairs. All writes go through services; admin write access to
ledger-touching models is disabled.

**Golden parity tests** are what make rewriting untested logic safe:

1. In the throwaway `legacy` DB, shim the masking off:
   `CREATE OR REPLACE FUNCTION app.has_cap(text) RETURNS boolean AS $$ SELECT true $$ LANGUAGE sql;`
   — one line, and all 22 `api` views now emit *unmasked* golden output.
2. `manage.py golden_export` dumps each legacy view (piece costing, margins, stock positions,
   count states) to CSV.
3. pytest recomputes the same figures through the new services against the ETL'd data and
   diffs to the paisa. Any drift is a bug in the port, caught in seconds instead of weeks.

**Permanent security regression test** (replaces v1's curl deploy-gate): log in as a
SALES-group user in the test client, render piece detail / piece list / exports, assert no
cost, vendor, or margin value appears in the response body; attempt `delete_piece` and user
management, assert 403. This is the 0013-class guard, as a test that runs on every commit.

## Phase 4 — Stock UI (templates + HTMX)

Base template + nav (Dashboard, Pieces, BOM, Materials, Locations, Media, Repairs, Admin →
Django admin). Port screen-by-screen using `legacy/Stock/app/nornament.html` as the spec —
**port behavior as-is, redesign later**; visual drift is scope creep. HTMX covers the live
bits: piece search/filter, inline rate edits, the barcode scan flow (`scan_piece` as an HTMX
POST returning a row partial), count screens. Media: presigned PUT direct from browser
(Phase 0 decides; fallback = proxy upload view), `get_many` resolved server-side in one query
at render time.

## Phase 5 — CRM models + ETL (the spine, natively)

- Real models: `Customer` (promoted columns + `extra JSONB` overflow so no un-promoted key is
  dropped, `legacy_id` preserved), `Enquiry`, `Order`, `Repair`, `ClientMaterial`, `Referral`.
- `customer.data.purchases[]` unnests into `stock.Sale` rows with `source='CRM'`,
  `customer` FK set. **One revenue ledger** — the original problem #1 dies here. CRM-source
  sales have no cost, so margin is `None`; margin reports filter `source='STOCK'` explicitly.
- Orphan `customer_id`s (Phase 0 check 4): nullable FK + an exceptions report, not silent drops.
- **Device media import:** `manage.py import_device_backup <backup.json>` parses the Phase 0
  `backupDevice()` files — base64 → S3 under `crm/<scope>/<entity>/<item>` → `MediaAsset`
  rows. Server-side command beats the v1 in-browser drainer: fewer moving parts, and the
  backups already exist. Run once per device file; idempotent on storage key.

## Phase 6 — CRM UI + quote calculator + FoN

Views: dashboard, customers (+profile), enquiries, orders, repairs, FoN, reports, settings —
same port-as-is rule. FoN commission slabs computed in `crm/services.py` **off `Sale` rows**.
Quote calculator becomes a server-rendered form reading `metal_purity` rates from the DB —
deleting the hardcoded `PURITY` table that migration `0032b` exists to warn about (925 silver
priced off the gold rate).

## Phase 7 — Deploy, backups, staging soak

- `docker-compose.yml`: `db` (postgres:17-alpine, **named volume**), `web` (entrypoint:
  migrate → collectstatic → gunicorn). One service on `dokploy-network`, Domain tab only, no
  hand-written Traefik labels. Env via Dokploy's Environment tab — never bind-mount `.env`
  (Docker directory-over-file failure). All v1 Dokploy gotchas apply verbatim.
- **Backups are a deliverable, not a footnote** (gap in v1): `deploy/backup.sh` = nightly
  `pg_dump -Fc` shipped to Contabo S3 + last-14 retention + a dead-man ping
  (healthchecks.io-style) so a *silent* backup failure pages you. Rehearse one restore from a
  backup file before cutover. Uptime monitor on `/healthz` (a view: `SELECT 1`).
- Staging subdomain a week early; full ETL rehearsal + golden suite green against staging.

## Phase 8 — Cutover

1. Freeze. **CRM devices first**: every device online, old CRM open, `OfflineBar` count 0 —
   the `Q_SK` queue holds writes that exist nowhere else. Then confirm every device's
   `backupDevice()` JSON is imported (Phase 5 command) — media count matches.
2. Final `pg_dump` from Supabase → restore into `legacy` → final `load_legacy` +
   `parity_check` + golden suite. All green or no-go.
3. Final `rclone` re-sync R2 → Contabo.
4. DNS to the VPS. Old apps stay in `legacy/`, dark.
5. **Do not touch the Supabase project for 30 days** — no pause, no key rotation.

Rollback until DNS: nothing, Supabase was never written to. After DNS: `pg_dump` the new DB
first, then point DNS back — the old apps still speak Supabase. Same clean property as v1.

---

## Verification (all automated except the last)

- `pytest` — services, masking regression, auth import, ETL edge cases. Runs on every commit.
- `manage.py parity_check` — nonzero exit gates the cutover.
- Golden suite — legacy SQL views (has_cap-shimmed) vs Django services, to the paisa.
- Manual on staging: login with a real imported password; SALES login sees no costs anywhere;
  scan a piece through a count; upload a HEIC and see the derivative; create a customer, add
  a purchase, run the FoN payout and cross-check the number against the ledger; idle 35
  minutes and act (session survives — Django default 2-week cookie).

## Timeline

| Phase | Effort |
|---|---|
| 0 — pre-flight + device backups | 1 d |
| 1 — skeleton + accounts + auth import | 2–3 d |
| 2 — stock models + ETL + parity gate | 3–4 d |
| 3 — stock services + golden tests | 4–5 d |
| 4 — stock UI | 4–5 d |
| 5 — CRM models + ETL + media import | 2–3 d |
| 6 — CRM UI + calculator + FoN | 3–4 d |
| 7 — deploy + backups + soak | 2 d |
| 8 — cutover | 1 d |
| **Total** | **22–28 working days, ~5–8 weeks calendar** |

~3× the v1 plan, bought deliberately: one boring stack you operate everywhere else, logic
that is tested for the first time, and the CRM data model fixed instead of deferred. The
long poles are Phases 3–4; the golden suite is what keeps Phase 3 honest.

## Risks, ranked

1. **Logic-port drift** — costing/margin math silently wrong in Python. → golden parity suite
   (the `has_cap` shim trick makes goldens complete), Decimal everywhere, ETL re-run nightly.
2. **CRM device media/queue loss** — certain, not conditional, if devices are skipped.
   → Phase 0 `backupDevice()` now; per-device checklist at cutover; import command idempotent.
3. **Masking regression** — a SALES login seeing cost. → the permanent pytest gate; masking
   decided in views/templates only, never ad-hoc per screen.
4. **Scope creep in the rewrite** — "while we're here" redesigns. → port-as-is rule; visual
   refresh is post-cutover work.
5. **ETL orphans/FK failures** — CRM orphan customer_ids, dupes. → Phase 0 check 4, nullable
   FK + exceptions report, nightly re-runs surface issues early.
6. **Contabo isn't R2** — browser CORS on presigned PUT. → Phase 0 smoke; fallback is a proxy
   upload view, contained change.
7. **Password import surprises** — non-bcrypt variants, NULLs. → Phase 0 checks 1–2;
   `must_change_password` + admin reset path for stragglers.
8. **Sold-twice** — partial unique constraint ships in the initial migration, not later.
9. **Dokploy routing/volumes** — known gotchas, all recoverable; staging a week early.
10. **Timeline optimism** — 14.5k lines of UI re-verified by hand in Phases 4/6. The golden
    suite compresses backend risk; UI porting is the honest long pole.

## NOT in scope

- Offline mode (dropped by decision — was an egress workaround)
- DRF / public API, mobile apps (add DRF later if a real consumer appears)
- Visual redesign of either app (post-cutover)
- Multi-tenancy, realtime, task queue (no current need)
- PostgREST-compatible URLs (nothing external ever consumed them)
