# openWakeWord — the "hey jarvis" detector, not in nixpkgs.
#
# It is pure Python over ONNX Runtime, so packaging it is a formality. The one
# wrinkle is `tflite-runtime`, which upstream marks as a hard dependency on
# Linux and which nobody has managed to package for nixpkgs. It is only ever
# imported inside the `inference_framework == "tflite"` branch, and jarvis asks
# for `"onnx"`, so the dependency is dropped rather than satisfied.
#
# The pretrained models are NOT here. Upstream downloads them at first use into
# its own package directory, which is read-only in the store — so jarvis fetches
# them to /var/lib/jarvis/openwakeword and passes explicit paths instead. See
# backend/jarvis/voice/wakeword.py.
{ lib
, buildPythonPackage
, fetchPypi
, setuptools
, numpy
, onnxruntime
, requests
, scikit-learn
, scipy
, tqdm
}:

buildPythonPackage rec {
  pname = "openwakeword";
  version = "0.6.0";
  pyproject = true;

  src = fetchPypi {
    inherit pname version;
    hash = "sha256-NoWNkPEYPjB0hVl6kSpOPDOEsU6pkj+D/q/658FWVWU=";
  };

  build-system = [ setuptools ];

  pythonRemoveDeps = [ "tflite-runtime" ];

  # scipy and scikit-learn look like training-only weight, but openwakeword's
  # __init__ imports vad and custom_verifier_model unconditionally, so they are
  # needed to `import openwakeword` at all.
  dependencies = [
    numpy
    onnxruntime
    requests
    scikit-learn
    scipy
    tqdm
  ];

  # The test suite downloads models from GitHub releases at collection time.
  doCheck = false;

  pythonImportsCheck = [ "openwakeword" "openwakeword.model" ];

  meta = {
    description = "Open-source audio wake word (or phrase) detection framework";
    homepage = "https://github.com/dscripka/openWakeWord";
    license = lib.licenses.asl20;
  };
}
