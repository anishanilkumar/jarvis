{ config, pkgs, lib, ... }:
let
  # Both services get a declarative interpreter. Everything the dashboard needs
  # is in nixpkgs directly; the voice service needs one package that isn't
  # (openWakeWord), so pkgs/openwakeword.nix next to this file builds it.
  #
  # It is worth saying why this is not a venv, since the obvious shape for
  # "two packages aren't in nixpkgs" is a venv and pip: NixOS has no dynamic
  # loader at /lib unless you turn on programs.nix-ld, so pip's manylinux
  # wheels for numpy and onnxruntime cannot execute. A venv here does not work
  # badly, it does not work at all.
  dashboardPython = pkgs.python3.withPackages (ps: with ps; [
    fastapi
    uvicorn
    httpx
    websockets
  ]);

  voicePython = pkgs.python3.withPackages (ps: with ps; [
    fastapi
    uvicorn
    httpx
    websockets
    numpy
    onnxruntime
    (ps.callPackage ./pkgs/openwakeword.nix { })
  ]);

  repo = "/home/pi/jarvis";
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
      # Also holds the openWakeWord ONNX models and the Piper voice — see the
      # one-time setup in the README.
      StateDirectory = "jarvis";
      ExecStart = "${voicePython}/bin/uvicorn jarvis.voice.ws:app --host 127.0.0.1 --port 8141";
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

    # Both halves of speech are binaries the Python finds with `shutil.which`,
    # and a systemd service does not get /run/current-system/sw/bin on its
    # PATH. Being in systemPackages below is not enough — without this line
    # `shutil.which` returns None, and the pipeline degrades to a panel that
    # hears nothing and answers silently, with healthy-looking logs.
    path = [ pkgs.piper-tts pkgs.whisper-cpp ];
  };

  environment.systemPackages = with pkgs; [
    piper-tts     # local TTS for the voice replies
    whisper-cpp   # local STT; running `whisper-cli` by hand is how you debug a misheard command
  ];
}
