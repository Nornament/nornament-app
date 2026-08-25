# A legacy slice, for rehearsing the migration without the real dump

`legacy_slice.sql` builds a small but faithful piece of the Supabase schema:
the `app` tables `load_legacy` reads, and the six `public` JSONB tables the CRM
uses. `legacy_api_views.sql` adds the `api` views with their real
`app.has_cap()` masking, so `golden_export --shim` can be exercised end to end.

It is a rehearsal fixture, not a substitute for the real dump — the go/no-go at
cutover is `parity_check` and the golden suite run against the actual restore.

```sh
createdb nornament_legacy
psql -d nornament_legacy -f etl/fixtures/legacy_slice.sql
psql -d nornament_legacy -f etl/fixtures/legacy_api_views.sql

export LEGACY_DB_NAME=nornament_legacy
python manage.py load_legacy
python manage.py parity_check
python manage.py golden_export --shim --out golden/
GOLDEN_DB=$POSTGRES_DB pytest -m golden
```
