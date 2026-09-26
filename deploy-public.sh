#!/usr/bin/env bash
# Deploy the public dashboard: point the VPS's NixOS config at this commit and
# rebuild.
#
# The VPS no longer holds a copy of this repo. Its config imports nix/public.nix
# from GitHub at the rev in a one-line file beside it (`jarvis-rev`), and Nix
# builds the panel and the backend from that. So a deploy is: write this
# commit's rev there, commit and push the config, and have the VPS pull and
# rebuild. That is also why a deploy needs this commit on GitHub first — the
# VPS fetches it from there, and a rev that only exists here is one it cannot.
#
# The config is not a flake (it lives at /etc/nixos as a clone), which is the
# only reason this is a rev file rather than a flake input.
set -euo pipefail

HOST="${JARVIS_PUBLIC_HOST:?set JARVIS_PUBLIC_HOST, e.g. you@yourvps}"
# The VPS's config repo: a local clone here, and the same repo cloned on the box.
CONFIG="${JARVIS_PUBLIC_CONFIG:?set JARVIS_PUBLIC_CONFIG to your local clone of the VPS config}"
REMOTE_CONFIG="${JARVIS_PUBLIC_REMOTE_CONFIG:-$(basename "$CONFIG")}"   # relative to the remote $HOME
REV_FILE="${JARVIS_PUBLIC_REV_FILE:-jarvis-rev}"
URL="${JARVIS_PUBLIC_URL:-}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "!! uncommitted changes — the VPS builds from GitHub, so commit and push first" >&2
  exit 1
fi
git fetch -q origin
rev="$(git rev-parse HEAD)"
if ! git merge-base --is-ancestor "$rev" origin/main; then
  echo "!! $rev is not on origin/main — push it first" >&2
  exit 1
fi

echo "==> pointing $CONFIG/$REV_FILE at ${rev:0:7}"
echo "$rev" > "$CONFIG/$REV_FILE"
if [[ -n "$(git -C "$CONFIG" status --porcelain -- "$REV_FILE")" ]]; then
  git -C "$CONFIG" add -- "$REV_FILE"
  # Only the rev file: the config repo may have other work in progress.
  git -C "$CONFIG" commit -q -m "jarvis: deploy ${rev:0:7}" -- "$REV_FILE"
  git -C "$CONFIG" push -q
else
  echo "   already there"
fi

echo "==> rebuilding $HOST"
ssh "$HOST" "cd $REMOTE_CONFIG && git pull -q --ff-only && sudo nixos-rebuild switch"

echo "==> health"
# The unit restarts during the switch; give it a moment rather than failing on
# the first refused connection.
deadline=$(( SECONDS + 60 ))
until health="$(ssh "$HOST" "curl -sS --fail --max-time 5 localhost:8768/api/health" 2>/dev/null)"; do
  if (( SECONDS >= deadline )); then
    echo "!! jarvis-public never answered — check: ssh $HOST journalctl -u jarvis-public -n 50" >&2
    exit 1
  fi
  sleep 2
done
echo "$health"
if [[ -n "$URL" ]]; then
  # Through nginx too: a healthy backend behind a vhost still pointing at the
  # old web root is a page that loads nothing.
  curl -sS --fail --max-time 10 -o /dev/null "$URL/" && echo "$URL/ answers"
fi
echo "done"
