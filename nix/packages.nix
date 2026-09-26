# Everything this repo builds, from whatever nixpkgs the caller brings. The
# modules call this with the host's own pkgs, so importing them does not pull a
# second nixpkgs onto the box.
{ callPackage, python3 }:

rec {
  panel = callPackage ./panel.nix { variant = "wall"; };
  panel-public = callPackage ./panel.nix { variant = "public"; };
  backend = python3.pkgs.callPackage ./backend.nix { };
  openwakeword = python3.pkgs.callPackage ./pkgs/openwakeword.nix { };

  # The public service needs nothing beyond the backend's own dependencies.
  python = python3.withPackages (_: [ backend ]);

  # The voice service: wake word on ONNX Runtime. openwakeword is not in
  # nixpkgs; pkgs/openwakeword.nix says why that is a formality.
  python-voice = python3.withPackages (ps: [ backend ps.numpy ps.onnxruntime openwakeword ]);
}
