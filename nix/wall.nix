# services.jarvis — the wall display, and optionally its voice front-end.
#
#   services.jarvis = {
#     enable = true;
#     address = "Invalidenstraße 50, Berlin";
#     stops = [
#       "S+U Berlin Hauptbahnhof"
#       { name = "Invalidenpark"; products = [ "bus" ]; order = "soonest"; }
#     ];
#   };
#
# The address and the stop names are looked up at startup (backend/jarvis/
# resolve.py) and remembered in /var/lib/jarvis, so the numbers never have to be
# written here. Everything else jarvis.example.toml documents goes in
# `settings`, in the same shape as the TOML.
#
# This serves the API only. The panel is a static web root at
# `config.services.jarvis.panel`; point the reverse proxy's root at it and
# send /api/ to `port` (and /voice/ to `voice.port`).
{ config, lib, pkgs, ... }:

let
  cfg = config.services.jarvis;
  toml = pkgs.formats.toml { };
  packages = pkgs.callPackage ./packages.nix { };

  # The committed template is the default, so an empty `settings` is a working
  # wall on Berlin Hbf rather than a unit that will not start.
  example = builtins.fromTOML (builtins.readFile ../jarvis.example.toml);

  # A stop is a name, or a name plus whatever a [[departures.boards]] table
  # takes. `name` is what gets looked up; `label` is the heading on the wall
  # (it defaults to the stop's own name); `id` skips the lookup.
  board = stop:
    if builtins.isString stop then { stop = stop; }
    else
      builtins.removeAttrs stop [ "name" "label" "id" ]
      // { stop = stop.name; }
      // lib.optionalAttrs (stop ? label) { name = stop.label; }
      // lib.optionalAttrs (stop ? id) { stop_id = stop.id; };

  derived =
    # The panel shows its talk button from this, so it follows the unit.
    { voice.enabled = cfg.voice.enable; }
    // lib.optionalAttrs (cfg.address != null) {
      # Replaces the template's location outright: its coordinates would
      # otherwise survive the merge and the address would never be looked up.
      location = { address = cfg.address; };
    }
    // lib.optionalAttrs (cfg.stops != [ ]) {
      departures.boards = map board cfg.stops;
    };

  base = example // lib.optionalAttrs (cfg.address != null) { location = { }; };
  settings = lib.recursiveUpdate (lib.recursiveUpdate base derived) cfg.settings;

  stopType = lib.types.either lib.types.str (lib.types.submodule {
    freeformType = toml.type;
    options = {
      name = lib.mkOption {
        type = lib.types.str;
        description = "The stop to look up, as BVG names it.";
        example = "S+U Berlin Hauptbahnhof";
      };
    };
  });

  common = {
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
  };

  serviceConfig = {
    Type = "simple";
    User = cfg.user;
    Group = cfg.group;
    Environment = [ "JARVIS_CONFIG=${cfg.configFile}" "PYTHONUNBUFFERED=1" ];
    EnvironmentFile = lib.mkIf (cfg.environmentFile != null) cfg.environmentFile;
    # cache.json (the last good value of every tile — the wall must never come
    # back blank), resolved.json (the looked-up address and stops), and the
    # voice models and voiceprints.
    StateDirectory = "jarvis";
    WorkingDirectory = "/var/lib/jarvis";
    NoNewPrivileges = true;
    PrivateTmp = true;
    ProtectSystem = "strict";
    ProtectHome = "read-only";
  };
in
{
  options.services.jarvis = {
    enable = lib.mkEnableOption "the Jarvis wall display";

    address = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Where the wall hangs, as you would type it into the BVG app. Looked up
        once and remembered. Null keeps `settings.location`'s coordinates.
      '';
      example = "Invalidenstraße 50, Berlin";
    };

    stops = lib.mkOption {
      type = lib.types.listOf stopType;
      default = [ ];
      description = ''
        One departures board per entry, in the order they appear. A string is a
        stop name; an attrset takes `name` plus anything a
        `[[departures.boards]]` table does (products, lines, directions,
        walk_minutes, rows, order, groups…), with `label` for the heading and
        `id` to pin the stop. The walk is worked out from `address` unless
        given. Empty keeps `settings.departures.boards`.
      '';
      example = lib.literalExpression ''
        [
          "S+U Berlin Hauptbahnhof"
          { name = "Invalidenpark"; products = [ "bus" ]; order = "soonest"; }
        ]
      '';
    };

    settings = lib.mkOption {
      type = toml.type;
      default = { };
      description = ''
        Anything else, in jarvis.example.toml's shape, merged over it. Secrets
        do not go here — they end up in the Nix store; use `environmentFile`.
      '';
    };

    configFile = lib.mkOption {
      type = lib.types.path;
      readOnly = true;
      default = toml.generate "jarvis.toml" settings;
      description = "The generated jarvis.toml.";
    };

    environmentFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = "GROCY_API_KEY, HA_TOKEN and the like, from outside the store.";
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "jarvis";
      description = "Created when left as the default.";
    };

    group = lib.mkOption {
      type = lib.types.str;
      default = "jarvis";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8140;
    };

    voice = {
      enable = lib.mkEnableOption ''"hey jarvis" — wake word, speaker ID, local STT and TTS'';
      port = lib.mkOption {
        type = lib.types.port;
        default = 8141;
      };
    };

    panel = lib.mkOption {
      type = lib.types.package;
      readOnly = true;
      default = packages.panel;
      description = "The built wall panel: the reverse proxy's web root.";
    };
  };

  config = lib.mkIf cfg.enable {
    users.users = lib.mkIf (cfg.user == "jarvis") {
      jarvis = {
        isSystemUser = true;
        group = cfg.group;
        # The voice unit reads the microphone and plays replies.
        extraGroups = lib.optional cfg.voice.enable "audio";
      };
    };
    users.groups = lib.mkIf (cfg.group == "jarvis") { jarvis = { }; };

    systemd.services.jarvis-dashboard = common // {
      description = "Jarvis wall dashboard API";
      # A change to the settings is a change to the unit, so a rebuild restarts
      # it; the store path in Environment= already does that, this says so.
      restartTriggers = [ cfg.configFile ];
      serviceConfig = serviceConfig // {
        ExecStart = "${packages.python}/bin/uvicorn jarvis.main:app --host 127.0.0.1 --port ${toString cfg.port}";
        Restart = "always";
        RestartSec = 5;
        ProtectKernelTunables = true;
        ProtectControlGroups = true;
        RestrictNamespaces = true;
      };
    };

    systemd.services.jarvis-voice = lib.mkIf cfg.voice.enable (common // {
      description = "Jarvis voice pipeline (wake word, speaker ID, STT, TTS)";
      after = common.after ++ [ "jarvis-dashboard.service" ];
      restartTriggers = [ cfg.configFile ];
      # Found with shutil.which. A systemd unit does not get the system profile
      # on its PATH, and without this the pipeline hears nothing and answers
      # silently while its logs look healthy.
      path = [ pkgs.piper-tts pkgs.whisper-cpp ];
      serviceConfig = serviceConfig // {
        ExecStart = "${packages.python-voice}/bin/uvicorn jarvis.voice.ws:app --host 127.0.0.1 --port ${toString cfg.voice.port}";
        Restart = "always";
        # Wake-word inference is the likeliest thing here to wedge; a separate
        # unit keeps it from ever taking the wall down with it.
        RestartSec = 10;
      };
    });

    environment.systemPackages = lib.mkIf cfg.voice.enable [
      # Running whisper-cli by hand is how you debug a misheard command.
      pkgs.piper-tts
      pkgs.whisper-cpp
    ];
  };
}
