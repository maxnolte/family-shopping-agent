#!/usr/bin/env bash
# Copy a fresh, consistent snapshot of the production SQLite file into
# data/shopping.db for dbt. Same online-backup approach as ../backup.sh, so
# it is safe while the app is running. Read-only for production.
#
#   ./pull.sh                  # server alias "vps" (see README), repo at ~/shopping-agent
#   HOST=myserver REMOTE_DIR=apps/shopping-agent ./pull.sh
set -euo pipefail
cd "$(dirname "$0")"

HOST="${HOST:-vps}"
REMOTE_DIR="${REMOTE_DIR:-shopping-agent}"
SNAPSHOT=app/data/analytics-export.db

ssh "$HOST" "cd $REMOTE_DIR && docker compose exec -T app python -" <<'PY'
import sqlite3

src = sqlite3.connect("/app/data/shopping.db")
dst = sqlite3.connect("/app/data/analytics-export.db")
with dst:
    src.backup(dst)
dst.close()
src.close()
PY

mkdir -p data
scp -q "$HOST:$REMOTE_DIR/$SNAPSHOT" data/shopping.db
ssh "$HOST" "rm -f $REMOTE_DIR/$SNAPSHOT"

[ -f seeds/members.csv ] || cp members.example.csv seeds/members.csv
echo "pulled: data/shopping.db ($(du -h data/shopping.db | cut -f1))"
