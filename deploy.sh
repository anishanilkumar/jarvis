#!/usr/bin/env bash
# Deploy the wall: move the Pi's NixOS flake to this commit and rebuild.
#
# The Pi's config takes this repo as a flake input (`inputs.jarvis`) and gets
# the panel, the backend and both units from nix/wall.nix. The address, the
# stops and every other setting live in that config as `services.jarvis`, not
# in a jarvis.toml here. So a deploy is: update the input's lock to this
# commit, commit and push the lock, and have the Pi pull and rebuild. That is
# also why a deploy needs this commit on GitHub first — the Pi fetches it from
# there.
#
# The panel is built on the Pi, once per change. It used to be built here and
# rsynced to keep Node off a busy box; with Nix the build is a derivation, done
# once and then cached, and the rsync is what made the panel and the backend
# able to disagree.
set -euo pipefail

HOST="${JARVIS_HOST:?set JARVIS_HOST, e.g. you@yourpi}"
# The Pi's config flake: a local clone here, and the same repo cloned on the Pi.
CONFIG="${JARVIS_CONFIG_REPO:?set JARVIS_CONFIG_REPO to your local clone of the Pi config flake}"
REMOTE_CONFIG="${JARVIS_REMOTE_CONFIG:-$(basename "$CONFIG")}"   # relative to the remote $HOME
ATTR="${JARVIS_FLAKE_ATTR:-$(ssh "$HOST" hostname)}"
SERVICE_WAIT="${JARVIS_SERVICE_WAIT:-4}"
SOURCE="${JARVIS_SOURCE:-github:anishanilkumar/jarvis}"   # the flake ref the config's input points at

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "!! uncommitted changes — the Pi builds from GitHub, so commit and push first" >&2
  exit 1
fi
git fetch -q origin
rev="$(git rev-parse HEAD)"
if ! git merge-base --is-ancestor "$rev" origin/main; then
  echo "!! $rev is not on origin/main — push it first" >&2
  exit 1
fi

echo "==> locking $CONFIG to jarvis ${rev:0:7}"
# The exact commit, not "whatever main is now": what was checked above is what
# ships.
nix flake lock "$CONFIG" --override-input jarvis "$SOURCE/$rev"
if [[ -n "$(git -C "$CONFIG" status --porcelain -- flake.lock)" ]]; then
  # Only the lock: the config repo may have other work in progress.
  git -C "$CONFIG" commit -q -m "jarvis: deploy ${rev:0:7}" -- flake.lock
  git -C "$CONFIG" push -q
else
  echo "   already there"
fi

echo "==> rebuilding $HOST"
ssh "$HOST" "cd $REMOTE_CONFIG && git pull -q --ff-only && sudo nixos-rebuild switch --flake .#$ATTR"

echo "==> health"
# Poll rather than sleep-then-check-once.
#
# A fixed wait was measured wrong on the real Pi. The dashboard holds an SSE
# stream open to the wall tablet, and that stream keeps the old process alive
# through SIGTERM — systemd waits out its stop timeout and then SIGKILLs, so the
# restart takes twenty-odd seconds rather than one. A four second wait landed in
# the middle of that window and reported "connection refused" on a deploy that
# was completely fine, which is worse than no check: a health gate you learn to
# ignore is not a health gate.
#
# Still fails the deploy on a backend that is genuinely down. Exiting 0 after
# shipping a broken build is how a wall display stays broken until somebody
# walks past it.
deadline=$(( SECONDS + ${JARVIS_HEALTH_TIMEOUT:-90} ))
health=""
until [[ -n "$health" ]]; do
  health="$(ssh "$HOST" "curl -sS --fail --max-time 5 localhost:8140/api/health" 2>/dev/null || true)"
  [[ -n "$health" ]] && break
  if (( SECONDS >= deadline )); then
    echo "!! jarvis-dashboard never answered — check: ssh $HOST journalctl -u jarvis-dashboard -n 50" >&2
    exit 1
  fi
  sleep "$SERVICE_WAIT"
done
echo "$health"
echo "done"
