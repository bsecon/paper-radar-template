#!/usr/bin/env bash
# Linux counterpart of install-launchd.sh: a crontab entry that runs bin/daily.sh every morning,
# plus a retry slot that only runs when work is pending.
#   bin/install-cron.sh [HOUR] [MINUTE] [RETRY_HOUR]     defaults 7 30 13
#   bin/install-cron.sh --print                           show the lines without installing
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRINT=0; [ "${1:-}" = "--print" ] && { PRINT=1; shift; }
HOUR="${1:-7}"; MINUTE="${2:-30}"; RETRY_HOUR="${3:-13}"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/paper-radar"
MARK="# paper-radar"
LINES="$MINUTE $HOUR * * * /usr/bin/env bash -lc '$ROOT/bin/daily.sh' >> $LOG_DIR/daily.log 2>&1 $MARK
0 $RETRY_HOUR * * * /usr/bin/env bash -lc '$ROOT/bin/daily.sh --if-pending' >> $LOG_DIR/daily.log 2>&1 $MARK"
if [ "$PRINT" = 1 ]; then echo "$LINES"; exit 0; fi
mkdir -p "$LOG_DIR"
{ crontab -l 2>/dev/null | grep -v "$MARK" || true; echo "$LINES"; } | crontab -
echo "installed: daily at $(printf '%02d:%02d' "$HOUR" "$MINUTE"), retry at $(printf '%02d:00' "$RETRY_HOUR") if work is pending; log: $LOG_DIR/daily.log"
echo "run now:   $ROOT/bin/daily.sh"
echo "remove:    crontab -l | grep -v '$MARK' | crontab -"
