#!/bin/sh
# Nightly backup. A backup nobody checks is not a backup, so this pings a
# dead-man switch on success — silence is what pages you.
set -eu

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
FILE="/tmp/nornament-${STAMP}.dump"
KEY="backups/nornament-${STAMP}.dump"

pg_dump --format=custom --no-owner --file "$FILE"

aws --endpoint-url "$BACKUP_ENDPOINT_URL" s3 cp "$FILE" "s3://${BACKUP_BUCKET}/${KEY}"
rm -f "$FILE"

# keep the last 14
aws --endpoint-url "$BACKUP_ENDPOINT_URL" s3 ls "s3://${BACKUP_BUCKET}/backups/" \
  | awk '{print $4}' | sort | head -n -14 \
  | while read -r old; do
      [ -n "$old" ] && aws --endpoint-url "$BACKUP_ENDPOINT_URL" s3 rm "s3://${BACKUP_BUCKET}/backups/${old}"
    done

if [ -n "${HEALTHCHECK_PING_URL:-}" ]; then
  curl -fsS -m 10 --retry 3 "$HEALTHCHECK_PING_URL" >/dev/null
fi

echo "backed up ${KEY}"
