# Runbook

Everything an operator needs after the code is written: how to run it, how to
migrate onto it, what to check, and what to do when something breaks.

The plan is in [`PLAN.md`](../PLAN.md). Getting it onto a VPS in the first
place is [`DEPLOY-DOKPLOY.md`](DEPLOY-DOKPLOY.md). This file is the operational
half.

---

## Running it locally

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

createdb nornament
export DJANGO_SECRET_KEY=dev-only DJANGO_DEBUG=1
export POSTGRES_DB=nornament POSTGRES_USER=$USER POSTGRES_HOST=127.0.0.1

python manage.py migrate          # includes the reference seed
python manage.py createsuperuser
python manage.py vendor_assets    # fetches htmx; optional, the app degrades without it
python manage.py runserver
```

`pytest` runs the whole suite. It needs a Postgres it can create a test database
on — partial unique indexes and the generated `margin_amt` column are part of
what is being tested, so SQLite is not an option.

## Environment

| Variable | What it does |
|---|---|
| `DJANGO_SECRET_KEY` | Required in production. |
| `DJANGO_ALLOWED_HOSTS` | Comma separated. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma separated, with scheme. |
| `POSTGRES_*` | `DB`, `USER`, `PASSWORD`, `HOST`, `PORT`. |
| `LEGACY_DB_NAME` | Set only while migrating. Its presence adds the `legacy` alias. |
| `MEDIA_*` | Contabo S3: `BUCKET`, `ENDPOINT_URL`, `ACCESS_KEY`, `SECRET_KEY`. |
| `MEDIA_DIRECT_UPLOAD` | `false` routes uploads through Django when browser PUT fails CORS. |
| `BACKUP_BUCKET`, `HEALTHCHECK_PING_URL` | Nightly dump and its dead-man switch. |

Secrets live in Dokploy's Environment tab. Never bind-mount a `.env` file:
Docker creates it as a directory and the app boots without its settings.

---

## The migration, in order

### Phase 0 — before anything else (laptop, not an agent)

1. **`backupDevice()` on every machine that has ever opened the CRM.** The
   base64 photos in `localStorage['nornament_media_v4']` are origin-scoped and
   exist nowhere else; iOS Safari evicts after seven days unvisited. Keep the
   JSON files — `import_device_backup` reads exactly them.
2. The four SQL checks against live Supabase:
   ```sql
   SELECT left(encrypted_password, 7), count(*) FROM auth.users GROUP BY 1;  -- expect $2a$10$
   SELECT count(*) FROM auth.users WHERE encrypted_password IS NULL;
   SELECT count(*) FROM app.sale;
   SELECT count(*) FROM public.orders o
    WHERE o.customer_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM public.customers c WHERE c.id = o.customer_id);
   ```
3. **Contabo smoke test**: a presigned PUT from a browser (CORS), a GET with
   `ResponseContentType`, path-style addressing. If the browser PUT fails, set
   `MEDIA_DIRECT_UPLOAD=false` — uploads then proxy through Django. One flag.
4. `rclone copy r2:nornament-media contabo:nornamentbucket` — idempotent, re-run
   at cutover. Source and destination bucket names differ; keys do not.
5. Export `logins.csv` — the header row is required, `import_logins` reads by
   column name, and the `AS email` matters (`lower(email)`'s default column
   name is `lower`):
   ```sh
   psql -c "\copy (SELECT id, lower(email) AS email, encrypted_password FROM auth.users) TO 'logins.csv' CSV HEADER"
   ```
   Encrypt at rest, move over ssh, shred after import.

### Restoring the dump beside the new database

```sh
createdb legacy
pg_restore --dbname legacy --no-owner supabase.dump
export LEGACY_DB_NAME=legacy
```

The name must contain `legacy` — `golden_export --shim` refuses to disable
capability checks in any database that does not.

### Loading

```sh
python manage.py load_legacy            # users, stock, crm — one transaction
python manage.py load_legacy --dry-run  # counts, then rolls back
python manage.py import_logins logins.csv
python manage.py import_device_backup backups/*.json
python manage.py push_inline_media      # CRM photos -> the bucket
python manage.py audit_media            # and prove none went missing
```

**Run `push_inline_media` after every `load_legacy`.** The stock app kept its
media in R2 and `app.media_asset` points at the keys, so those come across as
references. The CRM never used object storage at all — its photos are base64
data URIs inside the `data` JSONB, under five different keys (`media[].data`,
`photos[]`, `photo`, `beforePhoto`, `afterPhoto`). `load_legacy` decodes them
onto the row, and `push_inline_media` moves them into the bucket and clears the
column. Because the load is wipe-and-reload, a re-run puts them back on the row
and the push has to follow it.

`audit_media` is the gate: it counts the images in each legacy blob, compares
that with the `MediaAsset` rows the record ended up with, and HEADs every
object it claims is in the bucket. Nonzero exit if anything is short, so a
clean run is the evidence that no CRM record lost a picture.

`load_legacy` is wipe-and-reload, so it is idempotent by construction. Run it
nightly until cutover; the final run should be boring.

Primary keys are preserved for every table except users — Django assigns those
— and every column pointing at a user is remapped through that mapping.

### The gates

```sh
python manage.py parity_check                          # nonzero exit on any mismatch
python manage.py golden_export --shim --out golden/    # unmasked legacy figures
GOLDEN_DB=$POSTGRES_DB pytest -m golden                # SQL vs Python, to the paisa
pytest                                                 # the whole suite
```

`parity_check` compares row counts, the sum of every money column and the
min/max of every timestamp, table by table, plus the one thing that has no
like-for-like counterpart: the `purchases[]` arrays against the CRM-sourced
`sale` rows.

`golden_export --shim` replaces `app.has_cap()` with a function returning true
**in the legacy database only**, so the `api` views emit real costs and margins
rather than the nulls a masked view would give. The parameter keeps its name
(`p_cap`) — Postgres will not rename an input parameter through
`CREATE OR REPLACE`, and dropping the function would cascade to every view.

Rehearse all of it without the real dump using `etl/fixtures/`.

### Cutover

1. Freeze. **CRM devices first**: every device online, old CRM open,
   `OfflineBar` count 0 — the `Q_SK` queue holds writes that exist nowhere
   else. Then confirm every device's `backupDevice()` JSON is imported and the
   media count matches.
2. Final `pg_dump` from Supabase → restore into `legacy` → `load_legacy` +
   `parity_check` + the golden suite. All green or no-go.
3. Final `rclone` re-sync R2 → Contabo.
4. DNS to the VPS.
5. **Do not touch the Supabase project for 30 days** — no pause, no key rotation.

Rollback until DNS: nothing to do, Supabase was never written to. After DNS:
`pg_dump` the new database first, then point DNS back — the old apps still
speak Supabase.

---

## Operating it

### Backups

`deploy/backup.sh` runs nightly: `pg_dump -Fc` to Contabo, last 14 kept, then a
ping to `HEALTHCHECK_PING_URL`. The ping is the point — a backup that silently
stops running is the failure mode, so silence pages you.

**Rehearse a restore before cutover**, and after any change to the schema:

```sh
deploy/restore.sh nornament-20260824T210000Z.dump nornament_restore_test
```

A backup that has never been restored is a hypothesis.

### Health

`/healthz` does a `SELECT 1`. Point the uptime monitor at it.

### Users

Django admin: create the user, put them in exactly one role group (`ADMIN`,
`ACCOUNTS`, `SALES`, `GRAPHIC`, `PRODUCTION`), set a home location if they
should only see one, and leave `must_change_password` on. They cannot reach any
other screen until they change it.

An empty home location means **every** location is visible — that is the rule
`app.visible_locations()` had, kept deliberately.

### Metal rates

Rates → Set. A move of more than three times is refused; if it is real, set it
in two steps. Changing a rate reprices every live sale price and every quote
immediately; frozen BOM costs do not move, which is the difference between
"what it did cost" and "what it would cost today".

---

## When something breaks

**A SALES login can see a cost.** That is the one regression the test suite
exists to prevent — `pytest stock/tests/test_masking.py`. If it passes and the
leak is real, the screen is building its row somewhere other than
`stock.masking.piece_row`; that is the bug.

**`parity_check` fails after a load.** Read the mismatch lines: they name the
table, the column and both values. A money sum that differs by a few rupees is
a rounding change; a row count that differs is a load that silently dropped
something. Neither is a cutover.

**The golden suite fails.** A figure in `stock/services.py` no longer matches
the SQL it replaced. The message gives the jewel code, the field and the size
of the drift.

**A count says a piece is `ELSEWHERE`.** The books place it somewhere else.
That is information, not an error — the count records it and the variance list
carries it to whoever reconciles.

**An upload fails with a CORS error.** Set `MEDIA_DIRECT_UPLOAD=false` and
redeploy; uploads proxy through Django. Same keys, same rows, one more hop.

**`import_device_backup` reports unmatched items.** The entities are not loaded
yet. Run `load_legacy --only crm` first, then re-run it — it is idempotent on
the content hash, so nothing imports twice.
