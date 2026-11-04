#!/usr/bin/env bash
# Re-authenticate the headless Claude Code used by the radar.
# Creates a long-lived token (about a year) with `claude setup-token` and stores it where the radar
# reads it: the macOS keychain ("paper-radar-claude-token"), or ~/.config/paper-radar/token on Linux.
set -uo pipefail
SERVICE="paper-radar-claude-token"
TOKEN_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/paper-radar/token"
CL="${RADAR_CLAUDE_BIN:-}"
if [ -z "$CL" ]; then
  for c in "$(command -v claude 2>/dev/null)" "$HOME/.local/bin/claude" "$HOME/.local/bin/claude.exe"; do
    [ -n "$c" ] && [ -x "$c" ] && { CL="$c"; break; }
  done
fi
if [ -z "$CL" ]; then  # the macOS desktop app bundle
  CL="$(ls -d "$HOME/Library/Application Support/Claude/claude-code/"*/claude.app/Contents/MacOS/claude 2>/dev/null | sort -V | tail -1)"
fi
[ -x "$CL" ] || { echo "Claude Code binary not found: curl -fsSL https://claude.ai/install.sh | bash"; exit 1; }
echo "Using $CL"
echo "A browser window will open; approve the login. The token is captured and stored, not shown."
# Show the login progress live, with the token masked; the unmasked copy only goes into $OUT.
OUT="$(env -u CLAUDECODE "$CL" setup-token 2>&1 | tee >(while IFS= read -r l || [ -n "$l" ]; do printf '%s\n' "${l//sk-ant-oat*/[token hidden]}" >&2; done))"
TOKEN="$(echo "$OUT" | grep -o 'sk-ant-oat[A-Za-z0-9_-]*' | tail -1)"
if [ -z "$TOKEN" ]; then
  echo
  echo "Could not capture the token automatically. Paste it here (input hidden):"
  read -rs TOKEN
fi
[ -n "$TOKEN" ] || { echo "no token"; exit 1; }
if [ "$(uname)" = "Darwin" ]; then
  security delete-generic-password -s "$SERVICE" >/dev/null 2>&1 || true
  security add-generic-password -s "$SERVICE" -a "$USER" -w "$TOKEN" -U
  echo "Stored in keychain as $SERVICE. Testing..."
else
  mkdir -p "$(dirname "$TOKEN_FILE")"
  (umask 077; printf '%s\n' "$TOKEN" > "$TOKEN_FILE")
  echo "Stored in $TOKEN_FILE (mode 600). Testing..."
fi
cd "$(dirname "$0")/.." && uv run python -c "
from radar.config import load_config; from radar import llm
cfg = load_config()
print(llm.generate(cfg, model='claude-sonnet-5', system='Reply with JSON.', user='Return {\"ok\": true}', schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}, effort='low'))"
