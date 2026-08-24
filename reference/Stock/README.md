# Nornament — finished-goods stock

The stock system for Nornament's finished jewellery: every piece, its bill of
materials, what it cost, what it costs *today* at the current metal rate, what
it should sell for, and where it physically is.

It is one HTML file talking to Postgres. There is no build step, no bundler and
no framework. You edit `app/nornament.html`, upload it, and that is the deploy.

---

## What is in here

| Path | What it is |
|---|---|
| `app/nornament.html` | **The whole application.** One self-contained file — markup, styles and logic. This is what gets uploaded. |
| `supabase/migrations/` | Every schema change, in order, exactly as applied to the live database. This is the source of truth for the backend. |
| `supabase/functions/` | Three Deno edge functions: `media-url` (signed R2 uploads and views), `admin-user` (creating logins), `deploy-site` (optional one-click publish). |
| `docs/` | Setting up R2 and its CORS rules, how users and permissions work, how automatic deployment would work. |
| `import/` | The bulk-upload spreadsheet and the script that turns it into SQL. |
| `design/` | Design artboards for the pricing screens — reference only, not shipped. |

`supabase/migrations/_pre-nornament/` holds eight migrations from the earlier
raw-material IMS work. They live in the same database but a different schema
(`public`) and are unrelated to this app. They are kept so the migration
history is complete, not because Nornament uses them.

---

## How it fits together

```
  browser  ──►  app/nornament.html          served as a static file
                      │
                      ├──►  Supabase Postgres      via PostgREST, schema `api`
                      │       schemas: app (private) · api (what the browser sees)
                      │
                      ├──►  Supabase edge functions
                      │       media-url · admin-user · deploy-site
                      │
                      └──►  Cloudflare R2           photos and videos,
                              nornament-media       reached only through signed
                                                    URLs the edge function mints
```

**The browser never touches the `app` schema.** It sees only `api`, which is a
set of views and `SECURITY DEFINER` functions with the row filters written by
hand inside them. What a role can see — cost prices, margins, vendors, which
locations — is decided there, on the server, not in the page.

R2 credentials never reach the browser either. The page asks `media-url` for a
short-lived signed URL and uses that.

---

## Deploying

**The app.** Upload `app/nornament.html` as the site root. It is currently on
Cloudflare Pages (project `nornament-stock`) behind a CNAME.

**The database.** Migrations were applied through the Supabase MCP tooling, so
they are already in `supabase_migrations.schema_migrations`. To rebuild the
schema somewhere new:

```bash
supabase link --project-ref <ref>
supabase db push
```

**The edge functions.**

```bash
supabase functions deploy media-url
supabase functions deploy admin-user
```

`media-url` needs `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`
and `R2_BUCKET` in the Supabase secret store. `admin-user` uses the
service-role key Supabase injects for you. `deploy-site` is deployed but inert
until the Cloudflare secrets in `docs/AUTO_DEPLOY.md` are set; without them it
returns 503 rather than pretending.

---

## About the key in the HTML

`app/nornament.html` contains the Supabase project URL and its **publishable**
key. That is not a leak. A publishable key is designed to sit in client code —
it identifies the project and nothing more, and it is already public in the
file served at the live domain. Every actual permission is enforced by row
level security and by the capability checks inside the `api` functions.

What must **never** land in this repo: the service-role key, the database
password, R2 access keys, and Cloudflare API tokens. Those live in the Supabase
secret store. `.gitignore` covers `.env`, but the real defence is not putting
them in a file in the first place.

---

## Known gaps

- **Every piece is still `NOT_RECEIVED` with no location.** Until stock is
  received into locations, the stock count expects nothing, and the
  location-based parts of the dashboard and reports stay empty.
- **Design names are style codes.** `ER00409` is showing where a real design
  name should be.
- **One piece has a date in its remarks** (`25P00084` — "May 6 2025 12:00AM").
- **The Retail rate chart disagrees with stored piece rates** — it prices
  polki at ₹63,000/ct where `25P00084` was actually done at ₹30,000/ct, about
  19% apart. One of the two is wrong and it is worth deciding which.
- **The scheduled price revision is not built.** The mechanism is designed —
  revise on a date or on a ±5% metal move, whichever comes first — but it needs
  a monthly overhead figure before it can be honest about margin.
