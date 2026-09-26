#!/bin/sh
# Apply web/drizzle/*.sql to $PGDATABASE, each file once, in name order.
# (drizzle-kit is a dev dependency and not in the web image.)
set -eu
psql -v ON_ERROR_STOP=1 -qc 'CREATE TABLE IF NOT EXISTS _web_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())'
for f in /migrations/*.sql; do
  [ -e "$f" ] || continue
  n=$(basename "$f")
  if [ -n "$(psql -tAc "SELECT 1 FROM _web_migrations WHERE name = '$n'")" ]; then continue; fi
  echo "applying $n"
  psql -v ON_ERROR_STOP=1 -q -1 -f "$f" -c "INSERT INTO _web_migrations (name) VALUES ('$n')"
done
echo "web migrations up to date"
