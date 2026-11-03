#!/bin/zsh
# Daily run, invoked by launchd. Pulls, runs the pipeline, commits state, pushes.
set -uo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
cd "$(dirname "$0")/.." || exit 1
echo "=== $(date '+%F %T') start"
git pull --rebase --autostash -q origin main || echo "pull failed, continuing offline"
OUT="$(uv run radar run "$@" 2>&1)"; echo "$OUT"
echo "$OUT" | grep -q "nothing pending" && { echo "=== $(date '+%F %T') done (nothing pending)"; exit 0; }
ISSUE="$(echo "$OUT" | grep -o 'https://github.com/[^" ]*/issues/[0-9]*' | tail -1)"
if [ -n "$ISSUE" ]; then
  osascript -e "display notification \"$ISSUE\" with title \"paper-radar\" subtitle \"Digest ready\"" 2>/dev/null || true
fi
git add data digests library/radar.bib library/index.md
if ! git diff --cached --quiet; then
  git commit -qm "radar: $(date +%F)"
  git push -q origin main || echo "push failed; will retry tomorrow"
fi
echo "=== $(date '+%F %T') done"
