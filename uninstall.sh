#!/usr/bin/env bash
# Remove idle-poweroff. Leaves /etc/idle-poweroff (your config) in place.
set -euo pipefail
sudo systemctl disable --now idle-poweroff.timer 2>/dev/null || true
sudo rm -f /etc/systemd/system/idle-poweroff.service /etc/systemd/system/idle-poweroff.timer /usr/local/sbin/idle-poweroff
sudo rm -rf /var/lib/idle-poweroff
sudo systemctl daemon-reload
echo "removed; config kept in /etc/idle-poweroff"
