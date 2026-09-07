#!/usr/bin/env bash
# Deploy the public dashboard to the VPS.
#
# Same shape as deploy.sh and for the same reasons — panel built here, backend
# rsynced rather than pulled — but a different machine, a different web root
# and a different unit. Kept separate rather than parameterised because the two
# targets have nothing in common: the Pi runs the wall behind Caddy with agenix
# secrets, the VPS runs this behind nginx with none.
#
# The nginx vhost and the systemd unit live in the nixos-config repo and are
# deployed with `nixos-rebuild switch`, not by this script.
set -euo pipefail

HOST="${JARVIS_PUBLIC_HOST:?set JARVIS_PUBLIC_HOST, e.g. you@yourvps}"
WEB_ROOT="${JARVIS_PUBLIC_WEB_ROOT:-/var/www/jarvis-public}"
REPO="${JARVIS_PUBLIC_REPO:-jarvis}"     # relative to the remote user's $HOME

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

echo "==> building the public panel"
(cd frontend && npm ci --silent && npm run build:site)

# Vite emits site.html, because the entry has to be distinguishable from the
# wall's index.html inside one source tree. nginx wants index.html at the web
# root, so the rename happens here rather than teaching the vhost a second name.
echo "==> shipping panel to $HOST:$WEB_ROOT"
rm -rf frontend/dist-public/index.html
cp frontend/dist-public/site.html frontend/dist-public/index.html
rm frontend/dist-public/site.html
# --delete so content-hashed assets don't accumulate forever.
rsync -az --delete frontend/dist-public/ "$HOST:$WEB_ROOT/"

echo "==> shipping backend to $HOST:~/$REPO"
rsync -az --delete \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.venv' \
  backend/jarvis/ "$HOST:$REPO/backend/jarvis/"
# Unlike jarvis.toml this one is committed and holds no secrets, so shipping it
# every time is safe and means a threshold change is one deploy.
rsync -az jarvis-public.toml "$HOST:$REPO/jarvis-public.toml"

echo "==> restarting jarvis-public"
ssh "$HOST" "sudo systemctl restart jarvis-public"

echo "==> health"
# Poll rather than sleep-then-check-once: see the long note in deploy.sh about
# a fixed wait landing in the middle of a slow restart and failing a deploy
# that was completely fine.
deadline=$(( SECONDS + ${JARVIS_HEALTH_TIMEOUT:-60} ))
health=""
until [[ -n "$health" ]]; do
  health="$(ssh "$HOST" "curl -sS --fail --max-time 5 localhost:8768/api/health" 2>/dev/null || true)"
  [[ -n "$health" ]] && break
  if (( SECONDS >= deadline )); then
    echo "!! jarvis-public never answered — check: ssh $HOST journalctl -u jarvis-public -n 50" >&2
    exit 1
  fi
  sleep 3
done
echo "$health"
echo "done"
