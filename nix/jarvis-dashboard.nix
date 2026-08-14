{ config, pkgs, lib, ... }:
let
  # The dashboard's dependencies are all in nixpkgs, so it gets a fully
  # declarative interpreter. The *voice* service does not: openWakeWord and
  # google-genai aren't packaged, so it uses a venv on the box — the same
  # split the VPS already makes for applyquest (see a second host).
  dashboardPython = pkgs.python3.withPackages (ps: with ps; [
    fastapi
    uvicorn
    httpx
    websockets
  ]);

  repo = "/home/pi/jarvis";
  voiceVenv = "/home/pi/.venv/jarvis-voice";
in
{
  # Jarvis — the household wall display and its voice front-end.
  #
  #   jarvis-dashboard  127.0.0.1:8140  providers, SSE stream, touch actions
  #   jarvis-voice      127.0.0.1:8141  wake word -> speaker id -> STT -> intent
  #
  # Both bind loopback and are reached through Caddy (your reverse-proxy module),
  # so no firewall change is needed.
  #
  # The code is NOT vendored here: it's a git clone at ${repo}, like
  # a sibling service on another host. This repo owns the units and the vhost;
  # the app iterates without a nixos-rebuild.

  age.secrets.jarvis-env = {
    file = ../secrets/jarvis-env.age;
    # Both units run as the service user, so the decrypted env must be readable by them.
    owner = "pi";
    mode = "0400";
  };

  systemd.tmpfiles.rules = [
    "d /var/www/jarvis 0755 pi users -"
  ];

  systemd.services.jarvis-dashboard = {
    description = "Jarvis wall dashboard API";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];

    serviceConfig = {
      Type = "simple";
      User = "pi";
      WorkingDirectory = "${repo}/backend";
      EnvironmentFile = config.age.secrets.jarvis-env.path;
      Environment = [ "PYTHONPATH=${repo}/backend" "PYTHONUNBUFFERED=1" ];
      # Holds cache.json (last-good provider values), the speaker voiceprints
      # and the Piper model. Surviving a restart is the whole point of the
      # cache — the wall must never come back blank.
      StateDirectory = "jarvis";
      ExecStart = "${dashboardPython}/bin/uvicorn jarvis.main:app --host 127.0.0.1 --port 8140";
      Restart = "always";
      RestartSec = 5;

      # This talks to the internet and writes one small JSON file; it has no
      # business anywhere else on a box that also runs Jellyfin and Samba.
      NoNewPrivileges = true;
      PrivateTmp = true;
      ProtectSystem = "strict";
      ProtectHome = "read-only";
      ProtectKernelTunables = true;
      ProtectControlGroups = true;
      RestrictNamespaces = true;
    };
  };

  systemd.services.jarvis-voice = {
    description = "Jarvis voice pipeline (wake word, speaker ID, STT, TTS)";
    after = [ "network-online.target" "jarvis-dashboard.service" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];

    serviceConfig = {
      Type = "simple";
      User = "pi";
      WorkingDirectory = "${repo}/backend";
      EnvironmentFile = config.age.secrets.jarvis-env.path;
      Environment = [ "PYTHONPATH=${repo}/backend" "PYTHONUNBUFFERED=1" ];
      StateDirectory = "jarvis";
      ExecStart = "${voiceVenv}/bin/uvicorn jarvis.voice.ws:app --host 127.0.0.1 --port 8141";
      Restart = "always";
      RestartSec = 10;

      # Deliberately a separate unit from the dashboard: wake-word inference is
      # the most likely thing here to crash or wedge, and it must never be able
      # to take the wall display down with it.
      NoNewPrivileges = true;
      PrivateTmp = true;
      ProtectSystem = "strict";
      ProtectHome = "read-only";
    };

    # Fail loudly at start rather than crash-looping opaquely if the venv was
    # never created. See the runbook in CLAUDE.md.
    unitConfig.ConditionPathExists = "${voiceVenv}/bin/uvicorn";
  };

  environment.systemPackages = with pkgs; [
    piper-tts   # local TTS for the voice replies
  ];
}
