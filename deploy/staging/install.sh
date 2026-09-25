#!/usr/bin/env bash
# One-time setup of the auto-updating Holt staging preview on this box.
#   deploy/staging/install.sh           install + start the 3-minute timer
#   deploy/staging/install.sh --no-timer  install only (run preview.sh by hand)
#
# - copies preview.sh to ~/.local/share/holt-staging/bin/ (the timer runs that
#   copy, so a PR can't change the loop; re-run install.sh to update it)
# - writes the systemd --user units holt-stage.service / holt-stage.timer
# - routes holt-new.aahil-khan.xyz to the stack's port with stagectl
# No sudo. Needs linger for the timer to run while logged out
# (`loginctl show-user $USER -p Linger`).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
STATE="${HOLT_STAGE_HOME:-$HOME/.local/share/holt-staging}"
PORT="${HOLT_STAGE_PORT:-9110}"
UNITS="$HOME/.config/systemd/user"

mkdir -p "$STATE/bin" "$UNITS"
install -m 755 "$here/preview.sh" "$STATE/bin/preview.sh"

cat > "$UNITS/holt-stage.service" <<UNIT
[Unit]
Description=Holt staging preview: rebuild holt-new.aahil-khan.xyz when origin changes
After=network-online.target docker.service

[Service]
Type=oneshot
ExecStart=$STATE/bin/preview.sh
Nice=10
IOSchedulingClass=idle
TimeoutStartSec=2h
UNIT

cat > "$UNITS/holt-stage.timer" <<UNIT
[Unit]
Description=Check for Holt staging changes every 3 minutes

[Timer]
OnBootSec=2min
OnUnitInactiveSec=3min
AccuracySec=15s

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
"$HOME/staging/bin/stagectl" proxy holt-new "$PORT"
if [[ "${1:-}" != "--no-timer" ]]; then
    systemctl --user enable --now holt-stage.timer
    systemctl --user list-timers holt-stage.timer --no-pager
fi
