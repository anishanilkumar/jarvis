# On NixOS

The repo is a flake. It builds the panel and the backend, and exports two
NixOS modules that run them: `nixosModules.wall` for the wall display and its
voice front-end, and `nixosModules.public` for the public board. With either
one, where you live and which stops you use are lines in your host's config,
and a deploy is a rebuild.

## The wall

```nix
# flake.nix of the machine the wall runs on
inputs.jarvis.url = "github:anishanilkumar/jarvis";
inputs.jarvis.inputs.nixpkgs.follows = "nixpkgs";

# in its modules
imports = [ inputs.jarvis.nixosModules.wall ];

services.jarvis = {
  enable = true;
  address = "Invalidenstraße 50, Berlin";
  stops = [
    "S+U Berlin Hauptbahnhof"
    { name = "Invalidenpark"; label = "Bus"; products = [ "bus" ]; order = "soonest"; }
  ];
  voice.enable = true;
  environmentFile = config.age.secrets.jarvis-env.path;   # GROCY_API_KEY, HA_TOKEN
  settings = {
    # Anything else from jarvis.example.toml, in the same shape.
    household.members = [ "you" ];
    providers.news.enabled = false;
  };
};
```

**`address`** is what you would type into the BVG app. **`stops`** is one
departures board per entry, top to bottom. A string is a stop's name; an
attrset takes `name` plus anything a `[[departures.boards]]` table does —
`products`, `lines`, `directions`, `rows`, `order`, `groups`, `walk_minutes` —
with `label` for the heading and `id` to pin the stop when the name finds the
wrong one. Without `walk_minutes`, the walk is worked out from the address,
straight-line at 80 m a minute and rounded up.

Both are looked up when the service starts and remembered in
`/var/lib/jarvis/resolved.json`, so the wall comes back after a power cut even
if the router is slower to boot than the Pi. It needs the network once — and
again only when the address or a name changes. A name that cannot be found
stops the service with the reason in the journal, rather than drawing an empty
board that looks like nothing is running.

One difference from writing the TOML by hand: a Nix attrset is always
alphabetical, so a board's `groups` reach the config sorted by key. Under
`order = "listed"` that is the row order. Name the keys so they sort the way you
want to read them, or use `order = "line"`.

`settings` is merged over `jarvis.example.toml`, so leaving it empty still gives
a working wall. Secrets do not belong in it: they would land in the Nix store.

The module serves the API on `127.0.0.1:8140` (voice on `8141`) and builds the
panel as a static web root at `config.services.jarvis.panel`. Point your reverse
proxy's root at that, send `/api/` to the dashboard and `/voice/` to the voice
service. With Caddy:

```nix
root * ${config.services.jarvis.panel}
```

The service runs as a `jarvis` system user unless you set `user`; set it to an
existing account if `/var/lib/jarvis` already belongs to one.

## The public board

```nix
imports = [ inputs.jarvis.nixosModules.public ];
services.jarvis-public.enable = true;
```

It listens on `127.0.0.1:8768`; the web root is
`config.services.jarvis-public.panel`. `settings` is merged over
`jarvis-public.toml`. There is no address and no state: each visitor brings
their own location, and every cache is in memory.

A host whose config is not a flake can import it at a pinned commit:

```nix
let
  jarvis = builtins.fetchGit {
    url = "https://github.com/anishanilkumar/jarvis";
    rev = lib.fileContents ./jarvis-rev;
  };
in {
  imports = [ "${jarvis}/nix/public.nix" ];
}
```

## Deploying

There is nothing to run. A push to `main` is the deploy.

`.github/workflows/ci.yml` builds the backend (which runs the tests) and both
panels (which type-check) on every push and pull request. On `main`, when that
is green, it deploys:

- **The public board** is pushed to. The workflow connects to the VPS as a
  `jarvis-deploy` account whose key can do one thing — name a commit on `main`
  and have the box rebuild to it — then checks `/api/health/deep` until the
  board answers. The VPS records the commit on the box, and its config fetches
  jarvis at that commit with `ref = "main"`, so nothing else evaluates. The
  VPS side of this lives in its own config (`jarvis-deploy.nix`); the key is
  the `JARVIS_DEPLOY_KEY` secret. By hand:
  `ssh jarvis-deploy@<vps> <commit>`, or re-run the workflow.
- **The wall** pulls, because GitHub cannot reach a Pi on a home network. A
  timer on the Pi asks this workflow's API every 15 minutes for the newest
  green run on `main`, pulls the Pi's own config repo, and if either moved
  rebuilds with `inputs.jarvis` overridden to that commit. The override is not
  written to the lock, so rebuild by hand with `jarvis-rebuild`, not plain
  `nixos-rebuild`, or you get the jarvis the lock names. That module lives in
  the Pi's config (`jarvis-autodeploy.nix`), and a push there is deployed the
  same way.

A commit whose tests fail reaches neither machine. Rolling back is a revert
pushed to `main`, or `nixos-rebuild switch --rollback` on the host.

A change to the address, the stops or any setting is a change to the host's
config, not to this repo: edit it and push; the Pi picks it up on its next
check, the VPS on `nixos-rebuild switch`.

## Building here

```bash
nix build .#panel          # the wall's web root
nix build .#panel-public   # abfahrt's
nix build .#backend
```

The panel's npm dependencies are read from `package-lock.json` by
`importNpmLock`, so there is no hash to update when they change.
