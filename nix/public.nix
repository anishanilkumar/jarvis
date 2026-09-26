# services.jarvis-public — the public Berlin board (abfahrt).
#
#   services.jarvis-public.enable = true;
#
# and a vhost whose root is `config.services.jarvis-public.panel`, with /api/
# proxied to `port`. There is no address here: each visitor brings their own,
# and it never leaves their browser except as a coordinate on a query string.
#
# No secrets and no state — Open-Meteo and the BVG API want no key, and every
# cache is in memory, where losing it on restart is correct. That is what makes
# this one safe to put on the open internet.
{ config, lib, pkgs, ... }:

let
  cfg = config.services.jarvis-public;
  toml = pkgs.formats.toml { };
  packages = pkgs.callPackage ./packages.nix { };
  defaults = builtins.fromTOML (builtins.readFile ../jarvis-public.toml);
in
{
  options.services.jarvis-public = {
    enable = lib.mkEnableOption "the public Berlin departures and weather board";

    settings = lib.mkOption {
      type = toml.type;
      default = { };
      description = ''
        Merged over jarvis-public.toml. The rate limit and the Berlin bounding
        box there are load-bearing: without the box this is a free worldwide
        proxy for two APIs that are somebody else's to pay for.
      '';
    };

    configFile = lib.mkOption {
      type = lib.types.path;
      readOnly = true;
      default = toml.generate "jarvis-public.toml" (lib.recursiveUpdate defaults cfg.settings);
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8768;
    };

    panel = lib.mkOption {
      type = lib.types.package;
      readOnly = true;
      default = packages.panel-public;
      description = "The built public panel: the vhost's web root.";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.jarvis-public = {
      description = "Public Berlin departures and weather dashboard";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];
      restartTriggers = [ cfg.configFile ];
      serviceConfig = {
        Type = "simple";
        DynamicUser = true;
        Environment = [
          # Named explicitly. The loader's own fallback is the wall's config,
          # which would bring a public service up on someone's home.
          "JARVIS_CONFIG=${cfg.configFile}"
          "PYTHONUNBUFFERED=1"
        ];
        ExecStart = "${packages.python}/bin/uvicorn jarvis.public.app:app --host 127.0.0.1 --port ${toString cfg.port}";
        Restart = "always";
        RestartSec = "5s";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        ProtectKernelTunables = true;
        ProtectControlGroups = true;
        RestrictNamespaces = true;
      };
    };
  };
}
