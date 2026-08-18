#!/usr/bin/env bash
# Nightly backup of the shopping list. See README.md § Backups.
# Cron: 15 3 * * * $HOME/shopping-agent/backup.sh
#
# Uses SQLite's online-backup API (safe while the app is running) via the app
# container's Python, so the host needs no sqlite3 install. Off-server copy
# happens only if an rclone remote named "backup" is configured; otherwise you
# still get a local, timestamped snapshot. Retention on both: 14 days.
set -euo pipefail
cd "$(dirname "$0")"

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/shopping-agent}"
STAMP="$(date +%F)"
RETENTION_DAYS=14

mkdir -p "$BACKUP_DIR"

docker compose exec -T app python - <<'PY'
import sqlite3

src = sqlite3.connect("/app/data/shopping.db")
dst = sqlite3.connect("/app/data/shopping-backup.db")
with dst:
    src.backup(dst)
dst.close()
src.close()
PY

mv app/data/shopping-backup.db "$BACKUP_DIR/shopping-$STAMP.db"

# Off-server copy + remote retention (optional; see README.md § Backups).
if command -v rclone >/dev/null && rclone listremotes | grep -q '^backup:'; then
    rclone copy "$BACKUP_DIR/shopping-$STAMP.db" backup:shopping-agent/
    rclone delete --min-age "${RETENTION_DAYS}d" backup:shopping-agent/ || true
fi

# Local retention.
find "$BACKUP_DIR" -name 'shopping-*.db' -mtime "+$RETENTION_DAYS" -delete

echo "backup ok: $BACKUP_DIR/shopping-$STAMP.db"
