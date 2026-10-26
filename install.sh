#!/usr/bin/env bash
# Install idle-poweroff. Safe to re-run; never overwrites an existing config.
#   ./install.sh [path/to/idle-poweroff.conf]    # optional config to seed on first install
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
seed=${1:-$here/etc/idle-poweroff.conf}

sudo install -m 0755 "$here/bin/idle-poweroff" /usr/local/sbin/idle-poweroff
sudo install -d -m 0755 /etc/idle-poweroff /var/lib/idle-poweroff
[ -e /etc/idle-poweroff/idle-poweroff.conf ] || sudo install -m 0644 "$seed" /etc/idle-poweroff/idle-poweroff.conf
sudo install -m 0644 "$here"/systemd/idle-poweroff.service "$here"/systemd/idle-poweroff.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now idle-poweroff.timer

echo
sudo /usr/local/sbin/idle-poweroff status
echo
systemctl list-timers idle-poweroff.timer --no-pager
