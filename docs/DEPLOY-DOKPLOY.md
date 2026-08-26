# Deploying on Dokploy

One VPS, one Dokploy Compose service, one public hostname. Roughly 40 minutes
the first time, most of it waiting for DNS.

Everything below assumes the repo is pushed and Dokploy can reach it.

---

## 1. The VPS

Any 2 GB / 2 vCPU box will carry five users comfortably. Install Dokploy:

```sh
curl -sSL https://dokploy.com/install.sh | sh
```

Open `http://<server-ip>:3000`, create the admin account, and **turn off public
registration** immediately (Settings → Users).

Point your DNS at the box before going further — an `A` record for
`nornament.yourdomain.com` → the server IP. Traefik cannot issue a certificate
until that resolves, and the wait is the long pole in this whole process.

## 2. Create the application

Dokploy → **Create Service → Compose**.

| Field | Value |
|---|---|
| Provider | GitHub (authorise the app) or Git with a deploy key |
| Repository | `sparkdeath324/nornament-app` |
| Branch | `main` |
| Compose path | `deploy/docker-compose.yml` |

The compose path is relative to the repository root, and Dokploy clones the
repo to `/etc/dokploy/compose/<app>/code` before running it. Everything the
compose file references — `deploy/Dockerfile`, `deploy/entrypoint.sh`,
`deploy/backup.sh` — is committed, so those relative paths resolve.

## 3. Environment

**Environment** tab. Paste this and fill in the blanks — do not create a `.env`
file in the repo, and do not bind-mount one (see the gotchas below).

```
DJANGO_SECRET_KEY=<64 random characters>
DJANGO_ALLOWED_HOSTS=nornament.yourdomain.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://nornament.yourdomain.com

POSTGRES_DB=nornament
POSTGRES_USER=nornament
POSTGRES_PASSWORD=<a long random password>

MEDIA_BUCKET=nornamentbucket
MEDIA_ENDPOINT_URL=https://eu2.contabostorage.com
MEDIA_ACCESS_KEY=<contabo key>
MEDIA_SECRET_KEY=<contabo secret>
MEDIA_ADDRESSING_STYLE=path
MEDIA_DIRECT_UPLOAD=true

BACKUP_BUCKET=nornament-backups
BACKUP_AT=02:30
HEALTHCHECK_PING_URL=<healthchecks.io ping url>
```

Generate the secret key with:

```sh
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

`MEDIA_DIRECT_UPLOAD=false` is the fallback if a browser PUT to Contabo fails
CORS — uploads then proxy through Django. Decide it with the Phase 0 smoke
test; changing it later is one variable and a redeploy.

## 4. Domain

**Domains** tab → Add Domain:

| Field | Value |
|---|---|
| Host | `nornament.yourdomain.com` |
| Service | `web` |
| Port | `8000` |
| HTTPS | on |
| Certificate | Let's Encrypt |

Then **Deploy**. The first build takes a few minutes: it installs the Python
dependencies, fetches htmx, then the entrypoint migrates and runs
collectstatic before gunicorn starts.

## 5. First login

Once the deploy is green, from Dokploy's terminal for the `web` container:

```sh
python manage.py createsuperuser
```

Sign in at `https://nornament.yourdomain.com/admin/` and create the real users:
one role group each (`ADMIN`, `ACCOUNTS`, `SALES`, `GRAPHIC`, `PRODUCTION`), a
home location if they should only see one branch, `must_change_password` left
on.

Reference data — metals, purities, material categories, locations, categories,
the two pricing scenarios — is seeded by the migrations, so the app is usable
before any import.

## 6. Migrating the real data

The entrypoint automates the import. Upload the artifacts to the backup
bucket (any S3 client, or the Contabo panel):

```sh
aws s3 cp supabase.dump s3://nornament-backups/supabase.dump --endpoint-url $MEDIA_ENDPOINT_URL
aws s3 cp logins.csv    s3://nornament-backups/logins.csv    --endpoint-url $MEDIA_ENDPOINT_URL
```

then add to the Environment tab and deploy:

```
LEGACY_DB_NAME=legacy
LEGACY_DUMP_KEY=supabase.dump
LOGINS_KEY=logins.csv
```

Every deploy while those are set re-restores the dump and re-runs
`load_legacy` (wipe-and-reload, so idempotent) and `import_logins` — the
runbook's "run it nightly until cutover", but on push. `parity_check` runs
last and prints its verdict in the deploy log without blocking boot: a
mismatch means do not cut over, not do not boot.

Device backups stay manual — from the `web` container's terminal:

```sh
python manage.py import_device_backup /tmp/backups/*.json
```

`docs/RUNBOOK.md` has the full sequence including the golden gate. **At
cutover, remove `LEGACY_DUMP_KEY`, `LOGINS_KEY` and `LEGACY_DB_NAME` from the
Environment tab and delete `logins.csv` from the bucket** — a later deploy
with the flags still set would overwrite live data with the old dump.

## 7. Backups

The `backup` service runs on its own inside the stack: nightly `pg_dump -Fc` to
Contabo at `BACKUP_AT`, last 14 kept, then a ping to `HEALTHCHECK_PING_URL`.

Set up the dead-man switch at healthchecks.io (free) with a period of one day
and a grace of a few hours. The ping is the point — a backup that silently
stops running is the failure you find out about when you need it.

**Rehearse one restore before trusting any of it:**

```sh
deploy/restore.sh nornament-20260824T210000Z.dump nornament_restore_test
```

Point an uptime monitor at `https://nornament.yourdomain.com/healthz`.

---

## The gotchas that cost a day

**Never bind-mount `.env`.** Docker creates a *directory* at a missing host
path, then fails to mount it over a file target — `not a directory`. Every
value goes in the Environment tab and is referenced as `${VAR}` under
`environment:`. The compose file here already does that.

**A Traefik 404 with no certificate means the container is not on
`dokploy-network`.** It needs both `networks: [default, dokploy-network]` on
the service and `dokploy-network: {external: true}` at the top level. The
compose file has both, on `web` only — `db` and `backup` stay private.

**Pick one routing mechanism.** Dokploy's Domain tab generates its own Traefik
labels. Hand-written labels alongside them produce two equal-priority routers
on the same host and non-deterministic matching. This compose file writes no
labels at all: use the Domain tab and nothing else.

**A named volume for the database, never a host bind.** Some redeploy paths
wipe host paths under `/etc/dokploy/`. `nornament-db` is a named volume — and
back it up off-box regardless.

**The healthcheck must be able to reach the app.** It hits gunicorn directly on
`127.0.0.1` over plain HTTP, so `ALLOWED_HOSTS` includes loopback and
`/healthz` is exempt from the https redirect. Both are in `config/settings.py`
with tests in `stock/tests/test_deployment.py`; if you change either, that
suite tells you before Traefik does.

**Deploy to a staging subdomain a week before cutover** and rehearse the whole
import against it. The first Traefik certificate, the first `load_legacy`, and
the first restore are all things you want to have already done once.

---

## Redeploying

Push to `main`. Dokploy rebuilds and restarts; the entrypoint runs `migrate`
before gunicorn, so a deploy that cannot migrate never serves a half-migrated
schema. Watch it in the Deployments tab — the log ends with gunicorn's
`Listening at: http://0.0.0.0:8000`.

Rolling back is redeploying an older commit from the same tab. If a migration
has run in between, roll the data back from the nightly dump first.
