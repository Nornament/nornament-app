# Merge Stock + CRM into one app on self-hosted Postgres

## Context

Nornament runs two separate apps against one Supabase project (`uygvzdgdtohqlsaiawxs`):

- **Stock** (`Stock/app/nornament.html`, 6k lines vanilla JS) — finished-goods inventory, BOM, costing, margin. Server-authoritative: 41 tables in schema `app`, 22 views + 35 functions in schema `api`, 45 RLS policies, a role/capability model. Zero supabase-js — it hand-rolls `fetch` to PostgREST.
- **CRM** (`CRM/nornament-crm.html`, 8.5k lines React 18 UMD) — customers, enquiries, orders, repairs, client materials, FoN referrals. Client-authoritative: 6 `public` tables shaped `{id, code, customer_id, data JSONB}`, no FKs, no roles, one blanket `authenticated` RLS policy. Runs locally today.

Two problems this fixes:

1. **Two disagreeing revenue numbers.** CRM computes every rupee figure — dashboard, reports, and the FoN commission slabs — from a hand-typed `customer.data.purchases[]` array. Stock has real `sale` rows with real costs. Commission is currently paid off the hand-typed one.
2. **Supabase is a dependency with a cost curve.** The CRM's entire offline design (full localStorage mirror, 8-hour cache-first TTL, base64 photos never uploaded) exists to dodge Supabase egress billing. That is a workaround, not a feature.

**What must survive this migration intact** (counted in `Stock/supabase/migrations/`) — none of it is optional, and all of it is easy to wreck by accident:

- 45 RLS policies · 109 `SECURITY DEFINER` functions, 150 with `search_path` pinned (`0006` exists solely to close search-path hijacking)
- 111 `has_cap()` gates · 218 `RAISE EXCEPTION` refusals
- Column-level masking: 21 `CASE WHEN has_cap('sale')`, 16 `'cost'`, 12 `'vendor'`, 5 `'margin'` — a SALES login receives `null` where cost price would be
- `0013_fix_privilege_escalation.sql` — a `current_user` vs `session_user` confusion under SECURITY DEFINER, found and fixed in-house. **Risk #1 below is re-shipping this exact bug.**

The good news, established by exploring the SQL: **the vendor lock-in is shallow.** Zero extensions, zero realtime, zero Supabase Storage in the live path. The whole coupling is `auth.uid()` (11 call sites), `auth.users` (4 refs), and the role names `anon`/`authenticated` in GRANTs. Every mutation already goes through a uniform `api.<verb>(p jsonb)` wrapper — which is exactly what PostgREST serves. So ~5,900 lines of business SQL move unchanged.

**Target:** one monorepo, one origin, one login, one Postgres, deployed by Dokploy on a VPS; media on Contabo S3 via boto3 presigned URLs.

---

## Decisions (already made — build within these)

| | Choice |
|---|---|
| Hosting | VPS + Dokploy (Docker Compose + Traefik) |
| API layer | PostgREST + a small Python (FastAPI) sidecar |
| Media | Contabo S3, boto3 presigned URLs |
| Data merge | Spine-first: promote `customer` to a real table, collapse the duplicate revenue ledger; leave orders/repairs/enquiries/client_materials as JSONB |
| Frontend | One shell, two panes, one login; port screens later |
| Repo | One new monorepo; archive `Nornament/Stock` and `Nornament/CRM` |
| CRM offline | Unchanged through cutover; revisit after |

---

## Target architecture

```
                   Traefik (Dokploy)  ──  one hostname, one router
                            │
                            ▼
                  api  (FastAPI, port 8000)
                   ├── /                → static: shell + both panes
                   ├── /auth/*          → login · refresh · logout
                   ├── /admin/*         → user create/adopt/reset   (was admin-user)
                   ├── /media/*         → presign · confirm · get   (was media-url)
                   └── /rest/v1/*       → reverse-proxy to PostgREST
                            │
                   postgrest ── schemas: api (Stock) · crm (CRM)
                            │
                    postgres 17 ── app · api · crm
                            │
                    Contabo S3  ── media objects (keys unchanged from R2)
```

Only one container is publicly routed. PostgREST never touches the public network — that removes three Traefik routers, the stripprefix middleware, and an entire class of Dokploy routing bugs. Cost: one localhost hop and ~15 lines of httpx proxy.

`ponytail: one Python process fronts everything. Split out nginx + direct PostgREST only if request volume ever justifies it — at five users it does not.`

---

## Repo layout

```
nornament/
  web/
    index.html          shell: nav rail, login screen, <iframe> panes
    session.js          the ONLY auth code — token, refresh single-flight, authedFetch
    stock.html          from Stock/app/nornament.html
    crm.html            from CRM/nornament-crm.html
    quote.html          from CRM/jewellery_quote_calculator.html
    sw.js, manifest.json, icons
  api/
    main.py             ~350 lines: auth + admin + media + rest proxy + static
    requirements.txt    fastapi uvicorn psycopg[binary] httpx boto3 bcrypt pyjwt
    Dockerfile
  db/migrations/        the 53 existing files, verbatim + 0039, 0040, 0041
  deploy/
    docker-compose.yml
    migrate.sh
    00_pre_restore.sql
    02_post_restore.sql
  docs/                 Stock/docs/* + a new RUNBOOK.md
```

Migrations and `deploy/` **must be committed** — Dokploy resolves relative volume paths against the cloned repo at `/etc/dokploy/compose/<app>/code`.

---

## Phase 0 — Pre-flight (do these first; each can invalidate later work)

Run against live Supabase and a throwaway Contabo bucket. Results decide the schedule.

```sql
-- 1. Are all passwords bcrypt? Expect exactly one row: $2a$10$
SELECT left(encrypted_password,7) AS variant, count(*) FROM auth.users GROUP BY 1;
-- 2. Who has no password and will need a reset on day one?
SELECT count(*) FROM auth.users WHERE encrypted_password IS NULL;
-- 3. Is app.sale empty? (No RPC writes to it — grep for record_sale finds nothing.)
--    If 0, Phase 7 is a greenfield insert, not a merge, and several risks vanish.
SELECT count(*) FROM app.sale;
-- 4. Orphan app_users — adopt these on the OLD app before cutover.
SELECT count(*) FROM app.app_user WHERE auth_uid IS NULL AND is_active;
-- 5. CRM orphan FKs — decides whether Phase 7's FK can be validated.
SELECT count(*) FROM public.orders o
 WHERE o.customer_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM public.customers c WHERE c.id = o.customer_id);
```

**Contabo smoke test — this one can force a redesign, so do it before writing any media code:**

- Presigned `PUT` **from a browser** (CORS on direct upload). If this fails, uploads must proxy through FastAPI and the whole media contract changes.
- Presigned `GET` honouring `ResponseContentType` / `ResponseContentDisposition`. `media-url/index.ts` has an `EXT_MIME` table specifically because without these a HEIC downloads instead of displaying.
- Path-style addressing (`s3={"addressing_style":"path"}`); virtual-host style 404s on Contabo.
- Whether the bucket name needs a `<tenantId>:<bucket>` prefix.

**Copy media early:** `rclone copy r2:nornament-media contabo:<bucket>`. Keys are unchanged, so `app.media_asset.storage_key` needs no rewrite. Idempotent — re-run at cutover.

**Ship the device backup into the CRM you run today, at its current local origin.** The CRM's photos are base64 in `localStorage['nornament_media_v4']` and exist nowhere else; that store is origin-scoped and the origin is about to change. Five lines, no server needed:

```js
function backupDevice(){
  const blob = new Blob([JSON.stringify({v:1, at:new Date().toISOString(), ua:navigator.userAgent,
    media: localStorage.getItem(MEDIA_SK), data: localStorage.getItem(SK),
    queue: localStorage.getItem(Q_SK)})], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `nornament-device-backup-${Date.now()}.json`;
  a.click();
}
```

Run it on every machine/browser profile that has ever had the CRM open. Keep the JSON files. The proper uploader comes in Phase 3; this backup is the insurance and must not slip.

---

## Phase 1 — Monorepo skeleton

Create the repo, copy both apps in unmodified, copy `Stock/supabase/migrations/*.sql` into `db/migrations/` (**not** `_pre-nornament/` — 8 dead legacy files, and they are more Supabase-coupled than anything current). Delete `supabase/functions/deploy-site/` — never called from any client; `wrangler`/Dokploy replaces it.

Everything still points at Supabase at the end of this phase. Nothing is broken yet.

---

## Phase 1a — Get the work off the laptop

Cloud agents operate on a **GitHub repo**, not local disk. Today: `Nornament/Stock` and `Nornament/CRM` are separate repos (1 and 2 commits respectively), `gh` is not authenticated locally, and this plan lives outside any repo.

1. `gh auth login`
2. Create and push `Nornament/nornament` (this is Phase 1 — do them together)
3. Commit this file as `docs/PLAN.md` so cloud sessions can read the spec
4. Open the monorepo at [claude.ai/code](https://claude.ai/code) and hand it `docs/PLAN.md`

**What runs in the cloud vs stays local — this split is not negotiable:**

| | Cloud | Why |
|---|---|---|
| Phases 1–5, and authoring `0041` | ✅ | pure repo work; no live system, no secret |
| **Phase 0 pre-flight** | ❌ | needs the Supabase direct connection string and a Contabo bucket |
| **Phase 6 dump / restore / cutover** | ❌ | needs Supabase creds, ssh to the VPS, Contabo keys, and physical browser access to each device |

Never commit the Supabase direct URL, Contabo keys, or `logins.csv`. Phase 6 is a laptop-and-VPS job by design; the 30-day "don't touch Supabase" rule is what makes that safe.

---

## Phase 2 — Database: the auth shim

Two new migrations. The insight that makes this small: **`auth.uid()` is a function, so recreate it rather than rewriting its 11 callers and 45 policies.**

### `db/migrations/0039_selfhost_auth_shim.sql`

```sql
CREATE SCHEMA IF NOT EXISTS auth;

-- The only line in the system that knows where identity comes from.
-- PostgREST verifies the JWT and publishes claims as a transaction-local GUC.
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('request.jwt.claims', true)::json ->> 'sub','')::uuid
$$;
GRANT USAGE ON SCHEMA auth TO authenticated;
GRANT EXECUTE ON FUNCTION auth.uid() TO authenticated;
```

`current_setting(...,true)` returns NULL outside a request, so `auth.uid()` is NULL in psql and `app.is_admin()` returns false there — identical to today. `app.current_user_id()`, `app.has_cap()`, `app.visible_locations()` and `app.is_admin()` in `0002_auth_capabilities_rls.sql` change **zero lines**, and so do all 45 policies.

**The `session_user` escape hatch — read `20260812181533_nornament_0013_fix_privilege_escalation.sql` before touching this.** `app.is_privileged()` contains `session_user IN ('postgres','supabase_admin')`, echoed at `0016:26`, `0017:9`, `0024:9`, `0028b:13`. That logic is still correct on plain Postgres — but only if PostgREST does **not** connect as `postgres`. A copy-pasted `PGRST_DB_URI=postgres://postgres:...` makes it true for every authenticated REST request, which hands a SALES login the ability to delete pieces and edit BOMs. Two guards, both in 0039:

```sql
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticator' AND rolsuper) THEN
    RAISE EXCEPTION 'authenticator must not be a superuser';
  END IF;
END $$;

-- Name-independent: PostgREST sets request GUCs on every request; psql sets none.
CREATE OR REPLACE FUNCTION app.is_console() RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT coalesce(current_setting('request.headers', true), '') = ''
     AND session_user IN ('postgres','supabase_admin');
$$;
GRANT EXECUTE ON FUNCTION app.is_console() TO authenticated;
```

Then substitute `app.is_console()` for the `session_user IN (...)` clause inside `app.is_privileged()`, `app.can_upload_media()`, `app.delete_piece` and `app.set_user_locations`. `request.headers` is the right GUC to test — `app.log()` already depends on it, so it is proven in this codebase, and PostgREST overwrites it per transaction so a client cannot forge it. `is_console()` is STABLE and reads only GUCs and `session_user`, never `current_user` — that is what keeps the 0013 fix intact.

### `db/migrations/0040_selfhost_user_admin.sql`

Retires `auth.users`. `app.app_user.password_hash` and `must_change_password` were never dropped (`0002` only made the hash nullable), so the credential moves back onto the row it belongs to.

- **`api.pending_logins`** inverts meaning: it stops listing "logins with no user" (structurally impossible now) and lists people who cannot sign in — `WHERE app.is_admin() AND u.password_hash IS NULL AND u.email IS NOT NULL`, selecting `email, created_at, true AS confirmed`. Same column shape, so `drawUsers()` in the client needs no change.
- **`app.upsert_app_user`** (current version in `0029c_no_self_disable.sql:98`): delete the `SELECT id INTO v_auth FROM auth.users WHERE lower(email)=...` line and mint instead — `gen_random_uuid()` on insert, `coalesce(auth_uid, gen_random_uuid())` on update. Drop `auth` from its `SET search_path`. `linked_login` becomes `password_hash IS NOT NULL`. Everything else in `0029c` (self-demote guard, last-admin guard, `app.log` calls, the `is_admin()` gate) is untouched. `gen_random_uuid()` is core in PG13+ — no pgcrypto, so "zero extensions" survives.
- **`api.set_user_password(p jsonb)`** — new, admin-gated, with a `^\$2[aby]\$[0-9]{2}\$` regex guard so "the sidecar sent plaintext" is a loud failure rather than a password sitting in `pg_stat_statements`.
- **`app.login_lookup(text)`** — the one function the sidecar needs before a token exists. `SECURITY DEFINER`, returns `(user_id, auth_uid, username, password_hash, must_change_password)` matching username-or-email where `is_active`. `REVOKE ALL FROM PUBLIC, anon, authenticated; GRANT EXECUTE TO nornament_auth`.
- **`app.session`** — `(token_sha256 PK, user_id FK, issued_at, expires_at, last_seen_at, user_agent)`, granted only to `nornament_auth`. No RLS (RLS with zero policies would lock out the sidecar too; grants are the correct control here). Expired rows are deleted inline in the refresh handler — no pg_cron.

### Roles

Keep the names `anon` and `authenticated` — renaming means a sed across 53 files plus surgery on the dump's ACLs and buys nothing. `anon` must **exist** (the migrations contain literal `GRANT ... TO anon` that must parse) but must never be **reachable**:

```sql
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
CREATE ROLE service_role NOLOGIN;                    -- the dump's ACLs may name it
CREATE ROLE authenticator LOGIN NOINHERIT PASSWORD :'authpw';
CREATE ROLE nornament_auth LOGIN PASSWORD :'svcpw';
GRANT authenticated TO authenticator;                -- deliberately NOT anon
```

Plus **omit `PGRST_DB_ANON_ROLE` entirely**. Three independent locks then guard the pre-existing `GRANT EXECUTE ON api.upsert_app_user TO anon` problem: no anon role configured ⇒ unauthenticated requests are rejected; `anon` not granted to `authenticator` ⇒ a forged `"role":"anon"` token fails at `SET ROLE`; and `app.is_admin()` still returns false on a null uid.

### Schema move for the CRM

```sql
CREATE SCHEMA crm;
ALTER TABLE public.customers SET SCHEMA crm;   -- and orders, repairs, enquiries,
                                                --     client_materials, settings
GRANT USAGE ON SCHEMA crm TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA crm TO authenticated;
```

Out of `public` (where accidental exposure happens) and into a namespace that gives Phase 7 somewhere to land: `crm.customers` can later become a view over `app.customer` with the identical `{id, customer_code, data}` shape, and the CRM client won't notice.

**Note and decide explicitly:** this means any Stock login — SALES, GRAPHIC — can read every customer's phone number via `Accept-Profile: crm`. That is already true today through the anon key, so it is not a regression, but "one login, two panes" turns it from a curl into two clicks. Recommendation: ship as-is at cutover (one variable at a time), then add six RLS policies gated on a new `can_view_crm` capability as a follow-up.

---

## Phase 3 — The Python sidecar

FastAPI: pydantic gives typed validation at the one trust boundary that handles passwords and signs URLs, and plain `def` handlers are auto-offloaded to a threadpool — which is what bcrypt-at-cost-10 (~80 ms CPU) and boto3 need without writing async plumbing.

**Preserve the property the edge functions were built around: the sidecar never decides permission.** `media-url` and `admin-user` both forward the caller's JWT to PostgREST and let the database refuse. Keep that verbatim — on `/media/*` and `/admin/*` the sidecar checks only that an `Authorization: Bearer` header exists and forwards it untouched. It mints or verifies a JWT in exactly two places, `/auth/login` and `/auth/refresh`. **After migration there is no service-role credential anywhere in the system** — a strict improvement over today.

| Endpoint | Replaces | Notes |
|---|---|---|
| `POST /auth/login` `{ident, password}` | `/auth/v1/token?grant_type=password` | `app.login_lookup` on its own `nornament_auth` connection; `bcrypt.checkpw`; run a dummy checkpw when the user is absent so wrong-user and wrong-password take the same wall time. Returns access token + sets refresh cookie. |
| `POST /auth/refresh` (cookie only) | supabase-js autoRefresh; **new** for Stock | Rotate: delete old row, insert new, one transaction. Reuse of a rotated token ⇒ delete all that user's sessions and 401. |
| `POST /auth/logout` | `sb.auth.signOut()` | Delete row, expire cookie. |
| `POST /admin/user` `{action: create\|adopt\|reset_password}` | `/functions/v1/admin-user` | Keep the response shapes verbatim so Stock's callers change only a URL. Port the gemstone wordlist password generator as-is — readable-over-the-phone passwords are a feature. **Order flips:** the `app_user` row is created first (it now mints `auth_uid`), then the password is attached, so a credential without a user is structurally impossible. |
| `POST /media/url` `{action: upload\|confirm\|get\|get_many\|download}` | `media-url` edge fn | boto3 presign. `get_many` becomes ONE `?storage_key=in.(...)` query then local HMAC signing — today's version does up to 400 sequential HTTP round trips. Drop `set_cors`/`get_cors`: bucket CORS is one-time setup, not an app feature. |
| `POST /media/crm-import` | — | One-time-use: drains device localStorage base64 into S3. Delete after cutover. |
| `ANY /rest/v1/{path}` | Traefik route | httpx proxy to `http://postgrest:3000`, forwarding `Authorization`, `Accept-Profile`, `Content-Profile`, `Prefer` and the `Content-Range` response header. |
| `GET /healthz` | — | PostgREST `/ready` + `SELECT 1`. |

Static files mount **last** so they don't shadow API routes: `app.mount("/", StaticFiles(directory="/srv/web", html=True))`.

**Token design:**

| | |
|---|---|
| Access token | HS256 JWT, 30 min, held in memory only |
| Claims | `sub` = `app_user.auth_uid`, `role` = `"authenticated"` (mandatory — PostgREST does `SET LOCAL ROLE` from it), plus `uid`/`username` for convenience. No `aud`. **No capability flags** — they would go stale for the token's whole TTL, and the DB resolves them per-statement anyway. |
| Secret | ≥32 chars for HS256; generate 48+. Shared by `PGRST_JWT_SECRET` and the sidecar. |
| Refresh token | 32-byte opaque `secrets.token_urlsafe`, 30 days, rotated on every use, stored as sha256 in `app.session` |
| Cookie | `HttpOnly; Secure; SameSite=Lax; Path=/auth` — `Path=/auth` means it is never attached to `/rest/*` or `/media/*` |

Both apps are single HTML files with inline script, so XSS is not exotic; a refresh token in localStorage would be permanent account takeover, an httpOnly cookie is not.

**Password migration works.** GoTrue hashes with Go's bcrypt at cost 10, emitting `$2a$10$…`; Python's `bcrypt.checkpw` accepts `$2a$`/`$2b$`/`$2y$`. Everyone keeps their password. Three catches: confirm the variant in Phase 0 (some deployments use argon2id); use the `bcrypt` package directly, **not passlib** (unmaintained, breaks against `bcrypt>=4.1`, and silently truncates >72-byte passwords instead of erroring); reject `len(pw.encode()) > 72` explicitly at the boundary. Export the hashes with `\copy (SELECT id, lower(email), encrypted_password FROM auth.users WHERE email IS NOT NULL) TO 'logins.csv' WITH CSV` — that file is a credential database, so encrypt at rest, move over ssh, `shred` after import.

---

## Phase 4 — Frontend: one shell, two panes, one login

`web/index.html` is the shell: brand header, unified nav rail (Stock's 9 modules + CRM's 10 views), a single login screen, and a `#pane` holding **two same-origin iframes** — `stock.html` and `crm.html` — with the inactive one hidden.

Iframes rather than one merged document, because Stock's ~15 module-level globals (`DB`, `role`, `page`, `sel`, `TOKEN`, …) and its full-document `innerHTML` re-render would collide with React's root, and the two apps carry two complete and different design systems whose CSS would bleed into each other. Same-origin iframes give isolation for free, keep both panes alive across switches, and let Phase 5+ move screens from one iframe into the other one at a time. The quote calculator is already an iframe inside the CRM — the precedent exists.

**`web/session.js` is the only auth code in the frontend**, loaded by the shell and reached from each pane as `parent.SESSION`:

```js
let TOKEN = null, REFRESHING = null;
async function refresh(){
  REFRESHING = REFRESHING || fetch('/auth/refresh',{method:'POST',credentials:'include'})
    .then(r => r.ok ? r.json() : Promise.reject(new Error('signed out')))
    .then(d => { TOKEN = d.access_token; return TOKEN; })
    .finally(() => { REFRESHING = null; });        // one flight, not one per pending call
  return REFRESHING;
}
async function authedFetch(url, opts={}, retried=false){
  const h = new Headers(opts.headers || {});
  if (TOKEN) h.set('Authorization', 'Bearer ' + TOKEN);
  h.delete('apikey');
  const r = await fetch(url, {...opts, headers: h});
  if (r.status === 401 && !retried && TOKEN) { await refresh(); return authedFetch(url, opts, true); }
  return r;
}
```

The `REFRESHING` single-flight is **not optional**. `liveLoad()` fires several parallel `sbFetch` calls and `loadMedia()` adds a `get_many`; one expiry mid-load without it sends N simultaneous refreshes, and under rotation-reuse-means-compromise the losers nuke the session and log the user out mid-load.

Boot: `POST /auth/refresh` with `credentials:'include'`. 200 ⇒ signed in, proceed. 401 ⇒ login screen. One call, and "refresh the page = logged out" (Stock's behaviour today, `nornament.html:863`) dies.

**`web/stock.html` changes — four functions collapse into one.** `sbFetch` (line 865), `sbSignIn` (881), `mediaFn` (1155) and `sbFn` (2011) each rebuild the same three headers; point all of them at `parent.SESSION.authedFetch` with same-origin relative paths. The `SUPA` const (859–863) and the `apikey` header disappear everywhere. `sbFetch` keeps its `Accept-Profile: api` / `Content-Profile: api` headers and its body/error handling; `mediaFn` → `/media/url`; `sbFn` → `/admin/user`. **All 28 RPC names, all 19 view reads, and every PostgREST query string stay exactly as they are.** Keep `reachability()` (895) pointed at `/healthz`.

**`web/crm.html` changes.** supabase-js's `.from()` is just a PostgREST client and works fine against plain PostgREST; `.auth` and `.storage` do not and must go:

```js
const sb = supabase.createClient(location.origin, 'unused', {
  db:     { schema: 'crm' },                    // sets Accept-Profile AND Content-Profile
  auth:   { persistSession:false, autoRefreshToken:false, detectSessionInUrl:false },
  global: { fetch: parent.SESSION.authedFetch },
});
```

Delete `sb.auth.signInWithPassword` (7286), `getSession` (7489), `onAuthStateChange` (7495), `signOut` (8039) — the shell owns all of that; `onAuthStateChange` becomes a plain module callback. Replace the three `sb.storage.from('customer-docs')` calls (6493 upload, 6498 `getPublicUrl`, 6506 remove) with `/media/url`. **6498 is a real behaviour change, not a config change:** it uses a *public* bucket, so the URL stored in `customer.data.documents[].url` is permanent. Contabo presigned URLs expire — store `doc.path` (already stored) and resolve it to a fresh signed URL at render time.

Keep supabase-js for the cutover — dropping it means hand-rolling ~60 lines across `dbSaveCustomer`…`loadFromDB` (363–470), which is a bigger diff today. Drop it during the screen-porting work, not now.

**CRM offline stays exactly as it is** through cutover — one variable at a time.

**`web/crm.html` also gains the device-media drain** (idempotent, resumable, records progress after every single item so a mid-run failure loses nothing):

```js
async function exportDeviceMedia(onProgress){
  const store = loadMediaLocal();                              // {type_id: [{id,type,data,name},…]}
  const done  = JSON.parse(localStorage.getItem('nornament_media_exported') || '{}');
  const items = [];
  for (const [k, list] of Object.entries(store))
    for (const m of (list||[])) if (!done[k+'/'+m.id]) items.push([k, m]);
  let n = 0;
  for (const [k, m] of items){
    const [scope, ...rest] = k.split('_');
    const r = await parent.SESSION.authedFetch('/media/crm-import', {method:'POST',
      body: JSON.stringify({ scope, entity_id: rest.join('_'), item_id: m.id,
        name: m.name || (m.id + (m.type==='video' ? '.mp4' : '.jpg')),
        mime: m.type==='video' ? 'video/mp4' : 'image/jpeg', data_url: m.data })});
    if (!r.ok) throw new Error(`Upload stopped at ${n} of ${items.length}. Try again.`);
    done[k+'/'+m.id] = (await r.json()).storage_key;
    localStorage.setItem('nornament_media_exported', JSON.stringify(done));
    onProgress(++n, items.length);
  }
  return done;
}
```

Objects land under `crm/<scope>/<entity_id>/<item_id>`; a server pass then rewrites each entity's `data.media[]` from `{data:"data:image/jpeg;base64,…"}` to `{storage_key}`, and the render path resolves keys through `/media/url {action:'get_many'}` — the same batching Stock already uses. No schema change needed at cutover; normalising into `app.media_asset` waits for Phase 7. Gate it behind a banner that cannot be dismissed until the count reaches zero on that device — the banner is the enforcement mechanism, a wiki page is not.

---

## Phase 5 — Deploy on Dokploy

`deploy/docker-compose.yml`: `db` (postgres:17-alpine, **named** volume `pgdata`), `migrate` (run-once, `depends_on: db service_healthy`), `postgrest` (`depends_on: migrate service_completed_successfully`), `api` (the only service on `dokploy-network`).

```yaml
postgrest:
  image: postgrest/postgrest:v12.2.3
  environment:
    PGRST_DB_URI: postgres://authenticator:${AUTHENTICATOR_PASSWORD}@db:5432/nornament
    PGRST_DB_SCHEMAS: "api,crm"        # api first = default; Stock's Accept-Profile still works
    PGRST_JWT_SECRET: ${JWT_SECRET}
    PGRST_OPENAPI_MODE: "disabled"
    # PGRST_DB_ANON_ROLE deliberately unset
```

`deploy/migrate.sh` — a ledger loop, no Flyway/Atlas/sqlx:

```sh
#!/bin/sh
set -e
psql -v ON_ERROR_STOP=1 -qc "
  CREATE SCHEMA IF NOT EXISTS app;
  CREATE TABLE IF NOT EXISTS app.schema_migrations (
    name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now());"
for f in /migrations/*.sql; do
  n=$(basename "$f")
  psql -qtAc "SELECT 1 FROM app.schema_migrations WHERE name='$n'" | grep -q 1 && continue
  echo "applying $n"
  psql -v ON_ERROR_STOP=1 --single-transaction -f "$f" \
       -c "INSERT INTO app.schema_migrations(name) VALUES ('$n')"
done
```

`--single-transaction` with `-f` then `-c` runs both in one transaction, so a failing migration leaves no ledger row.

**Dokploy gotchas** (the `.env` and network ones are confirmed by `~/.claude/skills/dokploy-django/SKILL.md`; read its `references/routing.md` when wiring the domain):

- **Never bind-mount `.env`.** Docker creates a *directory* at a missing host path, then fails to mount it over a file target — `not a directory`. Put values in Dokploy's Environment tab, reference as `${VAR}` under `environment:`.
- **Traefik 404 with no SSL** = the container isn't on `dokploy-network`. Needs both `networks: [internal, dokploy-network]` on the service and `dokploy-network: {external: true}` at the top level.
- **Pick one routing mechanism.** Dokploy's Domain tab generates its own labels; mixing them with hand-written labels produces two equal-priority routers on the same host and non-deterministic matching. Because everything collapses to one service on port 8000 at path `/`, the UI alone is sufficient — write no labels at all.
- **Relative volume paths** resolve inside the cloned repo. `db/migrations/`, `deploy/`, `web/` must be committed.
- **Named volume for `pgdata`**, not a host bind — some redeploy paths wipe host paths under `/etc/dokploy/`. Either way, schedule off-box `pg_dump` backups before trusting it.
- **No healthcheck on the postgrest container** — that image has no shell, no curl, no wget. Use `service_started` and let the Python `/healthz` be the real readiness signal.

Deploy the whole stack to a **staging subdomain a week early** and rehearse the full restore against a throwaway database at least once.

---

## Phase 6 — Data migration and cutover

**Dump and restore, not replay.** Replaying the 53 migrations reproduces the schema but not the data, and a data-only load hits FK ordering plus the `apply_movement` trigger on `stock_movement`. One `pg_dump -Fc` carries schema, data, views, functions, policies and grants in the correct order.

```bash
pg_dump "$SUPABASE_DIRECT_URL" -Fc \
  --schema=app --schema=api --schema=public \
  --exclude-schema='auth|storage|realtime|vault|graphql*|extensions|supabase*|_analytics|_realtime|pgsodium*|net|cron' \
  --no-owner -f nornament.dump

# sanity-grep before restoring
pg_restore -f - nornament.dump | grep -nE 'CREATE EXTENSION|auth\.|storage\.|supabase_|service_role' | head -50
```

Use the **direct** connection, not the transaction pooler (pg_dump needs session mode). Keep `--no-owner`, but **keep privileges** — the `GRANT ... TO authenticated` lines are load-bearing.

**The restore-order landmine:** `pg_restore` parses *view* DDL at restore time, and `api.pending_logins` selects from `auth.users`. Function bodies are opaque strings and restore fine; views do not. Discovered mid-window, this looks like a corrupt dump. So `deploy/00_pre_restore.sql` runs on the empty database **first**: the five roles, `CREATE SCHEMA auth`, `auth.uid()`, and a throwaway `auth.users` stub `(id uuid PK, email text, created_at timestamptz, email_confirmed_at timestamptz)` that exists only so the view definition parses.

Then `pg_restore -d nornament --no-owner --clean --if-exists -j2 nornament.dump`, then `deploy/02_post_restore.sql`:

1. Import `logins.csv` — match on `auth_uid` first, fall back to lowercased email.
2. Apply 0039 + 0040 (the definitions that no longer reference `auth.users`).
3. `DROP TABLE auth.users` — now dependency-free.
4. Move the six CRM tables into schema `crm`.
5. Verify and drop any `storage.objects` policy the dump carried (`0007_storage_buckets.sql` has been dead since media moved to R2 in `0023`).
6. Seed the ledger with all 53 filenames plus 0039/0040 so `migrate.sh` never replays history. They stay in `db/migrations/` for future fresh installs.

**Go/no-go gate — must all pass before DNS moves:**

```sql
SELECT count(*) FROM app.jewel_code;                                         -- matches Supabase
SELECT count(*) FROM app.media_asset;
SELECT count(*) FROM crm.customers;
SELECT count(*) FROM pg_policies WHERE schemaname='app';                     -- expect 45
SELECT count(*) FROM information_schema.routines WHERE routine_schema='api'; -- expect 35 + 2
SELECT username FROM app.app_user WHERE is_active AND password_hash IS NULL; -- expect EMPTY
SELECT auth.uid() IS NULL;                                                   -- expect t
```

**Cutover order:**

1. Freeze. **CRM devices first** — every device online long enough for `OFFLINE.flush()` to drain `Q_SK`; confirm the `OfflineBar` count is 0 on each. That queue holds writes that exist nowhere else, and swapping the HTML drops them on the floor.
2. Every device runs `exportDeviceMedia()` to completion (and has a `backupDevice()` JSON on file from Phase 0).
3. Final `pg_dump` + `logins.csv` delta.
4. Restore per above on the real box.
5. Re-sync `rclone copy r2: contabo:`.
6. Deploy the merged web bundle.
7. Point DNS at the VPS.
8. **Do not touch the Supabase project for 30 days** — don't pause it, don't delete it, don't rotate keys.

**Rollback** is clean: both apps are static HTML with hardcoded endpoints, so redeploy the previous files and Supabase is still authoritative and untouched. Take a `pg_dump` of the *new* database before rolling back so writes made during the window can be replayed by hand. Keep the window short. The one thing rollback cannot undo is the device-media export — hence it runs before, not during.

---

## Phase 7 — The customer spine (a week after cutover, as `0041`)

Deliberately **not** during the migration: a data-model change concurrent with a platform change means you can't tell which one broke it.

`app.sale` cannot hold CRM purchases as it stands — `20260812121050_..._0001b_...sql:94` declares `jewel_code_id INT NOT NULL UNIQUE`, which forbids both a purchase with no piece and a customer with two purchases. It also has `bom_version_at_sale`, `location_id` and `cost_at_sale` NOT NULL. So:

1. `CREATE TABLE app.customer` — `customer_id BIGSERIAL`, `crm_id TEXT UNIQUE` (the permanent join key), `customer_code`, `name`, `phone`, `email`, timestamps, `data JSONB` for everything not yet promoted. Populate from `crm.customers`, with `data - 'purchases'`.
2. Widen `app.sale` — four `DROP NOT NULL`s; add `customer_id`, `source TEXT CHECK (source IN ('STOCK','CRM'))`, `crm_purchase_id`. **Replace the dropped `sale_jewel_code_id_key` with `CREATE UNIQUE INDEX sale_jewel_once ON app.sale (jewel_code_id) WHERE jewel_code_id IS NOT NULL`** — dropping it without the partial replacement silently permits selling one piece twice, which surfaces weeks later as a phantom item.
3. Lateral-unnest `data->'purchases'` into `app.sale` rows with `source='CRM'`.
4. Replace `crm.customers` with a view over `app.customer` that re-synthesises `data.purchases` from the ledger — the CRM client keeps its shape and doesn't notice.
5. **Ship an `INSTEAD OF INSERT OR UPDATE` trigger on that view in the same migration**, splitting `data.purchases` back out into `app.sale`. A view is not upsertable, and the CRM writes the whole blob through `sb.from('customers').upsert()` (`nornament-crm.html:367`, plus purchase mutators at 6603/6608/6613/7662/7925). Without the trigger, every customer save — including offline-queue replays — errors the moment the view lands. ~30 lines of plpgsql, and it is the only thing standing between "spine-first" and "rewrite the CRM's data layer".
6. Add `crm.orders/repairs/enquiries/client_materials.customer_id` FKs to `app.customer(crm_id)`. Expect failures on orphans (no FK exists today); use `NOT VALID` if Phase 0 step 5 found any.

Two consequences to plan for: `margin_amt` is `GENERATED ALWAYS AS (sold_price - discount_amt - cost_at_sale)`, so it is **NULL for every CRM row** — margin reports must filter `WHERE source='STOCK'` or they silently under-report. And the `sale_read` RLS policy is `USING (app.has_cap('sale'))`, so CRM users without that capability would see zero purchases; the `crm.customers` view is `security_invoker = false` and bypasses it deliberately, matching the CRM's current model. Confirm that is wanted.

**Follow-ups after the spine, in order:** delete the quote calculator's hardcoded `PURITY` table and read `api.metal_purity` instead (it already exposes `sale_rate`/`cost_rate` per karat, and migration `0032b` exists precisely because someone priced 925 silver off the gold rate — the calculator is making that exact mistake today); normalise CRM media into `app.media_asset`; six `crm` RLS policies; drop the CRM's 8-hour TTL; drop supabase-js; port screens between panes.

---

## Verification

**After Phase 2 (local Postgres, no app):**
```sql
SELECT auth.uid() IS NULL AS ok, app.is_admin() = false AS ok2;   -- both t, no error
```

**After Phase 3+5, against staging, with a real user's real password:**
```bash
T=$(curl -sX POST https://staging/auth/login -d '{"ident":"preet","password":"…"}' | jq -r .access_token)
curl -s https://staging/rest/v1/me     -H "Authorization: Bearer $T" -H 'Accept-Profile: api'
curl -s https://staging/rest/v1/jewel  -H "Authorization: Bearer $T" -H 'Accept-Profile: api' | jq length
curl -s https://staging/rest/v1/customers -H "Authorization: Bearer $T" -H 'Accept-Profile: crm' | jq length
curl -s https://staging/rest/v1/jewel                              # expect 401, NOT 200
```

**The privilege regression test — non-optional, and the whole point of Phase 2's `is_console()`.** Sign in as a SALES user:
```bash
curl -s https://staging/rest/v1/rpc/delete_piece -H "Authorization: Bearer $SALES_T" \
  -H 'Content-Profile: api' -d '{"p":{"jewel_code":"…"}}'      # expect a refusal
curl -s https://staging/rest/v1/rpc/upsert_app_user -H "Authorization: Bearer $SALES_T" \
  -H 'Content-Profile: api' -d '{"p":{"username":"x"}}'        # expect "Only an admin"
```
If either succeeds, PostgREST is connecting as `postgres` and the 0013 privilege escalation has been re-shipped. Make this a deploy gate.

**Manual, in the merged app on staging:** log in once at the shell → both panes populate without a second login; hard-refresh → still signed in (the thing Stock cannot do today); Stock pane: open a piece, see BOM + movements, edit a rate, upload a HEIC and confirm the derivative JPEG displays; CRM pane: create a customer, add a purchase, run the FoN payout, upload a KYC doc and re-open it after 2 hours (catches the expiring-presigned-URL trap); open a stock count and scan a piece; leave a tab idle 35 minutes then act — expect a silent refresh, not a logout.

---

## Timeline

Neither repo has a single test, so every check is a human clicking through screens. That asymmetry — fast writing, slow verifying — is what sets the schedule.

| Phase | Effort | Note |
|---|---|---|
| 0 — pre-flight | 0.5–1 d | SQL checks are 10 min; the Contabo smoke test is the work |
| 1 + 1a — monorepo & cloud setup | 0.5 d | |
| 2 — `0039`/`0040` SQL | 1 d | ~200 lines, security-critical across 5 functions |
| 3 — Python sidecar | 1.5–2 d | ~350 lines matching two edge-function contracts exactly |
| 4 — frontend merge | **3–5 d** | the long pole: 9 Stock modules + 10 CRM views, all verified by hand |
| 5 — Dokploy deploy | 1–2 d | first-time Traefik costs a day |
| 6 — rehearsal + cutover | 1.5 d | one full restore rehearsal, then a ~half-day window |
| **To cutover** | **9–13 working days** | |
| 7 — customer spine | +2–3 d | a week later, deliberately |

**Calendar: ~4–5 weeks**, because several things are waiting rather than working — the rclone R2→Contabo copy (unsized; no credentials to check the bucket), the deliberate staging soak week, coordinating every device through its offline-queue drain and media export, and the intentional gap before Phase 7.

**What blows the estimate:** Contabo rejecting browser CORS on presigned PUT (**+2–3 d**, redesigns Phase 3 — which is why it is Phase 0 step 5); passwords not being bcrypt (**+1 d** plus reaching every user); CRM pane regressions, since 8.5k untested lines are having auth, schema routing and storage changed at once.

---

## Risks, ranked

1. **PostgREST connecting as `postgres`** re-opens the 0013 privilege escalation across four functions, giving a SALES login the ability to delete pieces and edit BOMs. The default image plus a copy-pasted `PGRST_DB_URI` is the natural way to arrive here. → dedicated `authenticator` role + the `rolsuper` assertion + `is_console()` + the SALES regression test as a gate.
2. **CRM device media.** Base64 photos in `localStorage['nornament_media_v4']`, origin-scoped, existing nowhere else, and the origin is changing (the CRM runs locally today, so this is certain, not conditional). iOS Safari also evicts localStorage for origins unvisited 7 days — some may already be gone. → `backupDevice()` shipped in Phase 0 on every machine; `exportDeviceMedia()` gated before cutover.
3. **`pg_restore` fails on `api.pending_logins`** because view DDL is parsed at restore time and schema `auth` won't exist. → `00_pre_restore.sql`; rehearse the restore at least once.
4. **Contabo isn't R2.** Browser CORS on direct presigned PUT, and `ResponseContentType`/`ResponseContentDisposition` overrides. If CORS fails, uploads must proxy through FastAPI and Phase 3's media design changes. → Phase 0, before any code.
5. **Refresh-token stampede on boot** logging users out mid-load. → the `REFRESHING` single-flight; four lines.
6. **Passwords aren't bcrypt, or are NULL.** Discovered at cutover this means nobody can log in. → Phase 0 steps 1–2, days ahead.
7. **The CRM offline queue dropped on the floor.** `Q_SK` holds writes existing only in that browser, and flush runs only while the tab is open. → per-device checklist item verified via the `OfflineBar` count, before the HTML changes.
8. **Phase 7's `sale_jewel_code_id_key`** dropped without the partial unique replacement → a piece can be sold twice; surfaces weeks later as a phantom item.
9. **`crm.customers` becoming a view** without the `INSTEAD OF` trigger → every CRM customer save errors the moment `0041` lands.
10. **Dokploy routing** — `.env` bind mounts, relative volume paths, missing `dokploy-network`, UI labels fighting hand-written ones. All recoverable, all burn cutover minutes. → one public service on one port; deploy to staging a week early.
11. **CRM data readable by any Stock login** via `Accept-Profile: crm`. Not a regression, but newly discoverable. → decide explicitly; six RLS policies if the answer is no.
