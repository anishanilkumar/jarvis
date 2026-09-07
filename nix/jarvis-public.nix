{ config, pkgs, lib, ... }:
let
  # A string, not a path literal: a path would be copied into the Nix store at
  # build time, and the point of this shape is that the app iterates with
  # `git pull && systemctl restart` rather than a nixos-rebuild.
  repo = "/home/you/jarvis";

  # Three packages, and that is the entire dependency list. The public service
  # shares the wall's shaping code but none of its integrations: no Grocy, no
  # Home Assistant, no voice, and — because Open-Meteo and the BVG API both
  # want no key — no secrets at all. There is no EnvironmentFile below for the
  # same reason, which is what makes this one safe to put on the open internet.
  python = pkgs.python3.withPackages (ps: with ps; [ fastapi uvicorn httpx ]);
in
{
  # The public Berlin dashboard.
  #
  #   jarvis-public  127.0.0.1:8768  geocode, weather, nearby departures
  #
  # Binds loopback and is reached through nginx, so no firewall change is
  # needed. Copy this into the VPS's NixOS config (apps.nix), together with a
  # vhost that serves the built panel from /var/www and proxies /api/ here.

  systemd.services.jarvis-public = {
    description = "Public Berlin departures and weather dashboard";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];

    serviceConfig = {
      Type = "simple";
      User = "you";
      WorkingDirectory = "${repo}/backend";
      Environment = [
        "PYTHONPATH=${repo}/backend"
        # Named explicitly. config.py falls back to the wall's jarvis.toml when
        # this is unset, which would bring up a public service on the
        # household's own coordinates with no [public] block — looking fine.
        "JARVIS_CONFIG=${repo}/jarvis-public.toml"
        "PYTHONUNBUFFERED=1"
      ];
      ExecStart = "${python}/bin/python3 -m uvicorn jarvis.public.app:app --host 127.0.0.1 --port 8768";
      Restart = "always";
      RestartSec = "5s";

      # No StateDirectory: the caches are in memory and losing them on restart
      # is correct. Nothing here is worth persisting, and nothing here is worth
      # backing up.
      NoNewPrivileges = true;
      PrivateTmp = true;
      ProtectSystem = "strict";
      ProtectHome = "read-only";
      ProtectKernelTunables = true;
      ProtectControlGroups = true;
      RestrictNamespaces = true;
    };
  };
}
