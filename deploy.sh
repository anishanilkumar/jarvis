#!/usr/bin/env bash
# Deploy Jarvis to the Pi.
#
# The frontend is built HERE and rsynced, rather than built on the Pi: that
# keeps Node off a box that is already busy, and a Vite build on a Pi 4 is
# minutes rather than seconds.
#
# The backend is a git clone on the Pi, so this just pulls and restarts. The
# NixOS units and the Caddy vhost live in the pinix repo and are deployed with
# `nixos-rebuild`, not by this script.
set -euo pipefail

HOST="${JARVIS_HOST:?set JARVIS_HOST, e.g. pi@raspberrypi.local}"
WEB_ROOT="/var/www/jarvis"
# Left unexpanded on purpose: $HOME is resolved by the *remote* shell below.
REPO='${JARVIS_REPO:-$HOME/jarvis}'

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

echo "==> building panel"
(cd frontend && npm ci --silent && npm run build)

echo "==> shipping panel to $HOST:$WEB_ROOT"
# --delete so a renamed content-hashed asset doesn't accumulate forever on an
# SD card. index.html is excluded from compression concerns; it's tiny.
rsync -az --delete frontend/dist/ "$HOST:$WEB_ROOT/"

echo "==> updating backend on $HOST"
ssh "$HOST" "cd $REPO && git pull --ff-only"

echo "==> restarting services"
# The voice unit is restarted separately and allowed to fail: it only starts if
# its venv exists, and a box without the voice venv should still get a working
# display rather than a failed deploy.
ssh "$HOST" "sudo systemctl restart jarvis-dashboard"
ssh "$HOST" "sudo systemctl restart jarvis-voice || echo '   (voice not running — see README: voice venv)'"

echo "==> health"
ssh "$HOST" "curl -sS localhost:8140/api/health" && echo
echo "done"
