# Nornament

One application for Nornament's jewellery operation: finished-goods stock,
costing and margin, plus the customer CRM — Django on self-hosted Postgres,
deployed to a VPS with Dokploy.

## Read this first

**[`PLAN.md`](PLAN.md)** — what is being built and why.
**[`docs/DEPLOY-DOKPLOY.md`](docs/DEPLOY-DOKPLOY.md)** — getting it onto a VPS.
**[`docs/RUNBOOK.md`](docs/RUNBOOK.md)** — how to run it, migrate onto it, and
operate it.

```sh
pip install -r requirements-dev.txt
createdb nornament
export DJANGO_SECRET_KEY=dev-only DJANGO_DEBUG=1 POSTGRES_DB=nornament POSTGRES_USER=$USER POSTGRES_HOST=127.0.0.1
python manage.py migrate && python manage.py createsuperuser && python manage.py runserver
pytest
```

## Layout

| Path | What it is |
|---|---|
| `config/` | Settings (env-driven), URLs, WSGI. |
| `accounts/` | The user, the eight capabilities as permissions, location scoping, the imported bcrypt hashes. |
| `stock/` | The `app` schema mirrored as models, the ported business logic in `services.py`, the masking rule in `masking.py`, screens. |
| `crm/` | The JSONB blobs as real models, FoN commission off the sale ledger, the quote calculator, and the legacy CRM's own screens and actions. |
| `mediahub/` | `MediaAsset`, presigned uploads, `import_device_backup`. |
| `etl/` | `load_legacy`, `parity_check`, `golden_export`, `import_logins`, and a rehearsal fixture. |
| `deploy/` | Dockerfile, compose, backup and restore scripts. |
| `legacy/` | The two old apps and the 53 SQL migrations, read-only. The functional and visual spec. |

## The three things this rewrite exists to fix

**One revenue number.** FoN commission used to be paid off a hand-typed
`purchases[]` array while the stock app reported its own figure. Both now read
one `stock.Sale` ledger; a CRM purchase is a row in it with `source='CRM'` and
no cost, so margin reporting filters on `source='STOCK'` rather than inventing
a margin it does not have.

**Silver prices off silver.** `app.metal_purity` used to multiply every purity
by the pure *gold* rate, so 925 silver was priced at 0.925 × gold. A purity now
belongs to a metal and reads that metal's rate — in the app, in the quote
calculator, everywhere.

**The security model is tested.** 45 RLS policies and 111 inline capability
gates became permissions plus service-layer checks, and for the first time
there is a test that logs in as a SALES user, renders every screen and the CSV
export, and asserts no cost, vendor or margin value appears anywhere. It runs
on every commit.

## Rules

**Never commit:** the Supabase connection string, Contabo keys, `logins.csv`,
or any `.dump`. `.gitignore` covers the obvious shapes; the real defence is not
putting them in a file. Secrets live in Dokploy's Environment tab.

**All writes go through services.** `stock/services.py` and `crm/services.py`
hold the rules the SQL functions used to. Admin write access to ledger-touching
models is switched off for that reason.

**Masking is decided in one place.** `stock/masking.py`. A screen that builds
its own row dict is how a cost reaches a showroom login.

**Port-as-is.** The screens are the old screens. A visual refresh is
post-cutover work; doing it during the port turns every difference into a
question of whether it was deliberate.

The two old apps did not look alike, so neither do their halves here, and each
has its own shell. `stock/` renders through `templates/base.html` and
`static/css/app.css`, lifted from `legacy/Stock` — the same four nav groups,
the same icons, the same padlock on a tab the role cannot open, the same
editable metal-rate ticker in the top bar. `crm/` renders through
`templates/crm_base.html` and `static/css/crm.css`, lifted from `legacy/CRM` —
its own sidebar, page header, badges, kanban, stage pipeline and mobile bottom
nav. A CRM screen does not load `app.css` and a stock screen does not load
`crm.css`; two stylesheets that both define `.card` and `.btn` would fight over
every page.

Which stock screens a role may open is `accounts.capabilities.ROLE_TABS`, the
legacy `ROLES[role].tabs` list copied across. The nav renders the padlock; the
`tab_required` decorator is what refuses — the legacy said it plainly, the gate
belongs where "a bug in the UI cannot let it through".
