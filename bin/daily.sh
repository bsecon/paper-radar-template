#!/usr/bin/env bash
# Daily run, invoked by launchd (macOS) or cron (Linux). Pulls, runs the pipeline, commits state, pushes.
set -uo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")/.." || exit 1
echo "=== $(date '+%F %T') start"
git pull --rebase --autostash -q origin main || echo "pull failed, continuing offline"
OUT="$(uv run radar run "$@" 2>&1)"; echo "$OUT"
echo "$OUT" | grep -q "nothing pending" && { echo "=== $(date '+%F %T') done (nothing pending)"; exit 0; }
ISSUE="$(echo "$OUT" | grep -o 'https://github.com/[^" ]*/issues/[0-9]*' | tail -1)"
if [ -n "$ISSUE" ]; then
  if command -v osascript >/dev/null; then
    osascript -e "display notification \"$ISSUE\" with title \"paper-radar\" subtitle \"Digest ready\"" 2>/dev/null || true
  elif command -v notify-send >/dev/null; then
    notify-send "paper-radar: digest ready" "$ISSUE" 2>/dev/null || true
  fi
fi
git add data digests library/radar.bib library/index.md
if ! git diff --cached --quiet; then
  git commit -qm "radar: $(date +%F)"
  git push -q origin main || echo "push failed; will retry tomorrow"
fi
echo "=== $(date '+%F %T') done"
