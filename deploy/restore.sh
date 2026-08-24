#!/bin/sh
# Restore rehearsal. Run this against a scratch database before cutover —
# a backup that has never been restored is a hypothesis.
set -eu

DUMP="${1:?usage: restore.sh <dump-file> [target-db]}"
TARGET="${2:-nornament_restore_test}"

createdb "$TARGET"
pg_restore --dbname "$TARGET" --no-owner --exit-on-error "$DUMP"
psql --dbname "$TARGET" -c "SELECT count(*) AS pieces FROM jewel_code" \
                        -c "SELECT count(*) AS sales FROM sale" \
                        -c "SELECT count(*) AS customers FROM crm_customer"
echo "restored into ${TARGET} — drop it when you are satisfied"
