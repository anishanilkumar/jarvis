#!/usr/bin/env bash
# Deploy Jarvis to the Pi.
#
# The frontend is built HERE and rsynced, rather than built on the Pi: that
# keeps Node off a box that is already busy, and a Vite build on a Pi 4 is
# minutes rather than seconds.
#
# The backend is rsynced too. An earlier version of this script did `git pull`
# on the Pi instead, which quietly assumed the deploy target was a clone; on a
# box where it isn't, the pull failed *after* the panel had already shipped and
# left a new frontend talking to an old backend. Rsync makes the deploy work
# the same way regardless of how the Pi's copy got there.
#
# The NixOS units and the Caddy vhost live in the pinix repo and are deployed
# with `nixos-rebuild`, not by this script.
set -euo pipefail

HOST="${JARVIS_HOST:?set JARVIS_HOST, e.g. you@yourpi}"
WEB_ROOT="${JARVIS_WEB_ROOT:-/var/www/jarvis}"
REPO="${JARVIS_REPO:-jarvis}"          # relative to the remote user's $HOME
SERVICE_WAIT="${JARVIS_SERVICE_WAIT:-4}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

echo "==> building panel"
(cd frontend && npm ci --silent && npm run build)

echo "==> shipping panel to $HOST:$WEB_ROOT"
# --delete so a renamed content-hashed asset doesn't accumulate forever on an
# SD card. index.html is excluded from compression concerns; it's tiny.
rsync -az --delete frontend/dist/ "$HOST:$WEB_ROOT/"

echo "==> shipping backend to $HOST:~/$REPO/backend"
rsync -az --delete \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.venv' \
  backend/jarvis/ "$HOST:$REPO/backend/jarvis/"

# jarvis.toml is gitignored, so it reaches the Pi only if something copies it.
# Leaving that to "you'll remember" is how you deploy a feature's code and then
# spend an evening wondering why the feature isn't on. A timestamped backup
# stays on the Pi so a bad config is one `mv` from being undone.
if [[ "${JARVIS_SKIP_CONFIG:-0}" == "1" ]]; then
  echo "==> skipping config (JARVIS_SKIP_CONFIG=1)"
elif [[ -f jarvis.toml ]]; then
  echo "==> shipping jarvis.toml"
  ssh "$HOST" "test -f $REPO/jarvis.toml && cp $REPO/jarvis.toml $REPO/jarvis.toml.bak-\$(date +%Y%m%d-%H%M%S) || true"
  rsync -az jarvis.toml "$HOST:$REPO/jarvis.toml"
else
  echo "==> no local jarvis.toml; leaving the Pi's config alone"
fi

echo "==> restarting services"
# The voice unit is restarted separately and allowed to fail: it only starts if
# its venv exists, and a box without the voice venv should still get a working
# display rather than a failed deploy.
ssh "$HOST" "sudo systemctl restart jarvis-dashboard"
ssh "$HOST" "sudo systemctl restart jarvis-voice || echo '   (voice not running — see README: voice venv)'"

echo "==> health"
sleep "$SERVICE_WAIT"
# Fail the deploy on an unhealthy backend. Exiting 0 after shipping a broken
# build is how a wall display stays broken until somebody walks past it.
ssh "$HOST" "systemctl is-active --quiet jarvis-dashboard" || {
  echo "!! jarvis-dashboard is not active — check: ssh $HOST journalctl -u jarvis-dashboard -n 50" >&2
  exit 1
}
ssh "$HOST" "curl -sS --fail localhost:8140/api/health" && echo
echo "done"
