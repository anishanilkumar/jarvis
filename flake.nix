{
  description = "Jarvis: a wall display with voice, and a public Berlin departures board";

  # Only for `nix build` here. The modules build with the importing host's own
  # pkgs, so a host can set `inputs.jarvis.inputs.nixpkgs.follows = "nixpkgs"`
  # and carry one package set.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";

  outputs = { self, nixpkgs }:
    let
      systems = [ "aarch64-linux" "x86_64-linux" "aarch64-darwin" "x86_64-darwin" ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAll (pkgs:
        let built = pkgs.callPackage ./nix/packages.nix { };
        in {
          inherit (built) panel panel-public backend;
          default = built.panel;
        });

      nixosModules = {
        wall = ./nix/wall.nix;
        public = ./nix/public.nix;
        home-assistant = ./nix/home-assistant.nix;
        default = self.nixosModules.wall;
      };
    };
}
