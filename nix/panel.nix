# The panel, built by Nix instead of on the Mac and rsynced.
#
# `variant` picks which of the two builds: "wall" is the tablet panel, "public"
# is abfahrt. They are two Vite configs over one source tree and must stay two
# outputs — see frontend/vite.public.config.ts for why they cannot share one.
#
# importNpmLock reads package-lock.json directly, so there is no npmDepsHash to
# keep in step with the lock: a dependency change is a lock change and nothing
# else.
{ lib, buildNpmPackage, importNpmLock, variant ? "wall" }:

let
  root = ../frontend;
  src = lib.fileset.toSource {
    inherit root;
    # Named rather than "everything but node_modules": a local checkout has
    # dist/, dist-public/ and node_modules/ sitting next to the source, and none
    # of them may leak into a build that is meant to be the same everywhere.
    fileset = lib.fileset.unions [
      (root + "/package.json")
      (root + "/package-lock.json")
      (root + "/index.html")
      (root + "/site.html")
      (root + "/tsconfig.json")
      (root + "/vite.config.ts")
      (root + "/vite.public.config.ts")
      (root + "/public")
      (root + "/src")
    ];
  };
  public = variant == "public";
in
buildNpmPackage {
  pname = if public then "jarvis-panel-public" else "jarvis-panel";
  version = "0.1.0";
  inherit src;

  npmDeps = importNpmLock { npmRoot = src; };
  npmConfigHook = importNpmLock.npmConfigHook;
  npmBuildScript = if public then "build:site" else "build";

  # The output is a web root, not an npm package.
  installPhase = if public then ''
    runHook preInstall
    cp -r dist-public $out
    # Vite names the entry site.html so the two builds' entries can live in one
    # tree; the web server wants index.html.
    mv $out/site.html $out/index.html
    runHook postInstall
  '' else ''
    runHook preInstall
    cp -r dist $out
    runHook postInstall
  '';
}
