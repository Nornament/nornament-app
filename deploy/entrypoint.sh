#!/bin/sh
# migrate → collectstatic → serve. Migrations run before the first request so a
# deploy that cannot migrate never serves a half-migrated schema.
#
# If LEGACY_DUMP_KEY is set, each deploy also re-runs the legacy import first:
# fetch the Supabase dump from BACKUP_BUCKET, restore it into LEGACY_DB_NAME,
# load_legacy (wipe-and-reload — the runbook's "run it nightly until cutover"),
# then import logins. Remove LEGACY_DUMP_KEY, LOGINS_KEY and LEGACY_DB_NAME
# from Dokploy's Environment tab at cutover, or every later deploy will keep
# overwriting live data with the dump.
set -e

s3get() {
    python -c "
import django, sys
django.setup()
from mediahub.storage import client
client().download_file(sys.argv[1], sys.argv[2], sys.argv[3])
print(f's3://{sys.argv[1]}/{sys.argv[2]} -> {sys.argv[3]}')
" "$@"
}

if [ -n "$LEGACY_DUMP_KEY" ]; then
    echo "LEGACY IMPORT ACTIVE: restoring $LEGACY_DUMP_KEY into ${LEGACY_DB_NAME:?set LEGACY_DB_NAME alongside LEGACY_DUMP_KEY}"
    s3get "$BACKUP_BUCKET" "$LEGACY_DUMP_KEY" /tmp/legacy.dump
    export PGHOST="$POSTGRES_HOST" PGUSER="$POSTGRES_USER" PGPASSWORD="$POSTGRES_PASSWORD"
    dropdb --if-exists "$LEGACY_DB_NAME"
    createdb "$LEGACY_DB_NAME"
    # Supabase dumps name roles and extensions this cluster does not have, so
    # pg_restore exits nonzero on noise. load_legacy is the real gate: it fails
    # loudly if the legacy tables did not actually land.
    pg_restore --dbname "$LEGACY_DB_NAME" --no-owner --no-privileges /tmp/legacy.dump \
        || echo "pg_restore reported errors — usually Supabase role/extension noise"
    rm -f /tmp/legacy.dump
fi

python manage.py migrate --noinput

if [ -n "$LEGACY_DUMP_KEY" ]; then
    python manage.py load_legacy
    if [ -n "$LOGINS_KEY" ]; then
        s3get "$BACKUP_BUCKET" "$LOGINS_KEY" /tmp/logins.csv
        python manage.py import_logins /tmp/logins.csv
        rm -f /tmp/logins.csv
    fi
    # Advisory here: a mismatch must block cutover, not the container.
    python manage.py parity_check || echo "PARITY CHECK FAILED — do not cut over; read the mismatch lines above"
fi

python manage.py collectstatic --noinput

exec "$@"
