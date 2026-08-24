#!/bin/sh
# migrate → collectstatic → serve. Migrations run before the first request so a
# deploy that cannot migrate never serves a half-migrated schema.
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
