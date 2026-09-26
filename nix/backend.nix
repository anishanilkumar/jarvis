# The Python backend, as a package. Both the wall and the public service run
# from it; they differ only in which app uvicorn starts and which config it is
# pointed at.
#
# The voice service's extra dependencies are not here. They are heavy (numpy,
# onnxruntime), only the Pi's voice unit needs them, and the modules add them
# to that one interpreter.
{ lib, buildPythonPackage, setuptools, fastapi, uvicorn, httpx, websockets, pytestCheckHook }:

let
  root = ../backend;
in
buildPythonPackage {
  pname = "jarvis-dashboard";
  version = "0.1.0";
  pyproject = true;

  src = lib.fileset.toSource {
    inherit root;
    # Not the whole directory: a local checkout has .venv/ and an egg-info
    # beside the package, and __pycache__ inside it.
    fileset = lib.fileset.unions [
      (root + "/pyproject.toml")
      (lib.fileset.fileFilter (file: file.hasExt "py") (root + "/jarvis"))
      (lib.fileset.fileFilter (file: file.hasExt "py") (root + "/tests"))
    ];
  };

  build-system = [ setuptools ];
  dependencies = [ fastapi uvicorn httpx websockets ];

  pythonImportsCheck = [ "jarvis.main" "jarvis.public.app" ];

  # The tests run in the build, so a host cannot build — and so cannot deploy —
  # a backend whose tests fail. They touch no network: every upstream is faked.
  nativeCheckInputs = [ pytestCheckHook ];

  meta = {
    description = "Wall display, voice front-end and public departures board";
    homepage = "https://github.com/anishanilkumar/jarvis";
    license = lib.licenses.mit;
  };
}
