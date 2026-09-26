#!/usr/bin/env bash
# One-time setup of the production extras on this box. It installs no
# deploy timer: production only changes when someone runs deploy.sh.
#
#   deploy/prod/install.sh        write .env if missing, install the nightly backup timer
#
# - copies backup.sh to ~/.local/share/holt-prod/bin/ (the timer runs that
#   copy, so it keeps working when worktrees come and go; re-run install.sh
#   after editing it)
# - writes the systemd --user units holt-prod-backup.service / .timer
#   (03:30 UTC daily; dumps to ~/backups/holt, keeps 14 days)
# No sudo. Needs linger so the timer runs while logged out
# (`loginctl show-user $USER -p Linger`).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
STATE="${HOLT_PROD_HOME:-$HOME/.local/share/holt-prod}"
UNITS="$HOME/.config/systemd/user"

mkdir -p "$STATE/bin" "$UNITS" "$HOME/backups/holt"
"$here/make-env.sh"
install -m 755 "$here/backup.sh" "$STATE/bin/backup.sh"

cat > "$UNITS/holt-prod-backup.service" <<UNIT
[Unit]
Description=Holt production: nightly pg_dump to ~/backups/holt
After=docker.service

[Service]
Type=oneshot
ExecStart=$STATE/bin/backup.sh
Nice=10
IOSchedulingClass=idle
UNIT

cat > "$UNITS/holt-prod-backup.timer" <<UNIT
[Unit]
Description=Holt production database backup, nightly

[Timer]
OnCalendar=*-*-* 03:30:00 UTC
RandomizedDelaySec=10min
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now holt-prod-backup.timer
systemctl --user list-timers holt-prod-backup.timer --no-pager
