#!/bin/zsh
# Installs (or reinstalls) the launchd job that runs bin/daily.sh every morning.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="${RADAR_LAUNCHD_LABEL:-com.paper-radar}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
HOUR="${1:-7}"; MINUTE="${2:-30}"; RETRY_HOUR="${3:-13}"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/zsh</string><string>-lc</string><string>$ROOT/bin/daily.sh</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/paper-radar.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/paper-radar.log</string>
  <key>WorkingDirectory</key><string>$ROOT</string>
</dict>
</plist>
PL
RETRY_PLIST="$HOME/Library/LaunchAgents/$LABEL.retry.plist"
cat > "$RETRY_PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL.retry</string>
  <key>ProgramArguments</key>
  <array><string>/bin/zsh</string><string>-lc</string><string>$ROOT/bin/daily.sh --if-pending</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$RETRY_HOUR</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/paper-radar.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/paper-radar.log</string>
  <key>WorkingDirectory</key><string>$ROOT</string>
</dict>
</plist>
PL
# migrate from the label used before the template split
for OLD in com.bsecon.paper-radar com.bsecon.paper-radar.retry; do
  launchctl bootout "gui/$(id -u)/$OLD" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$OLD.plist"
done
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootout "gui/$(id -u)/$LABEL.retry" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl bootstrap "gui/$(id -u)" "$RETRY_PLIST"
echo "installed $LABEL: runs daily at $(printf '%02d:%02d' "$HOUR" "$MINUTE"), retry slot at $(printf '%02d:00' "$RETRY_HOUR") if work is pending; log: ~/Library/Logs/paper-radar.log"
echo "run now:   launchctl kickstart gui/$(id -u)/$LABEL"
echo "remove:    launchctl bootout gui/$(id -u)/$LABEL && rm $PLIST"
