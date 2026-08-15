"""Wake word and speaker identification — the two things that run on the Pi
before anything leaves the house.

openWakeWord ships a pretrained "hey jarvis" model, which is exactly the phrase
this system wants, and it is cheap enough that a Pi 3 runs 15-20 models at once.
On a Pi 4 already busy with Jellyfin it is not a meaningful load.

The three ONNX files it needs are fetched by hand into the state directory and
passed in by path. Left to itself openWakeWord downloads them on first use into
its own package directory, which is read-only when the interpreter comes from
the nix store — the download fails, and it fails at the first frame of audio
rather than at startup. Explicit paths also mean a missing model is a log line
and a deaf panel, not a stack trace per 80ms frame.

Speaker ID runs on ONNX Runtime rather than PyTorch. openWakeWord already pulls
onnxruntime in, and installing torch on aarch64 for one embedding model would
be absurd.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
#: openWakeWord expects 80ms frames at 16kHz.
FRAME_SAMPLES = 1280


class WakeWord:
    def __init__(self, cfg: Any) -> None:
        voice = cfg.section("voice")
        self.name = voice.get("wake_word", "hey_jarvis")
        self.threshold = float(voice.get("wake_threshold", 0.55))
        self.dir = cfg.state_dir / "openwakeword"
        self._model: Any = None
        self._tried = False

    def _paths(self) -> tuple[Path, Path, Path] | None:
        """The wake-word model and the two shared feature models, or None.

        Globbed rather than named, because the pretrained file carries a version
        in its name (`hey_jarvis_v0.1.onnx`) and a model you train yourself
        won't.
        """
        melspec = self.dir / "melspectrogram.onnx"
        embedding = self.dir / "embedding_model.onnx"
        found = sorted(self.dir.glob(f"{self.name}*.onnx"))
        if not found or not melspec.exists() or not embedding.exists():
            return None
        return found[0], melspec, embedding

    @property
    def available(self) -> bool:
        return self._paths() is not None

    def _lazy_model(self) -> Any | None:
        if self._model is None and not self._tried:
            # Once, whatever happens. Retrying the load per frame would print
            # the same failure twelve times a second forever.
            self._tried = True
            paths = self._paths()
            if paths is None:
                log.error(
                    "no wake-word models in %s; the panel will hear nothing. "
                    "Fetch %s*.onnx, melspectrogram.onnx and embedding_model.onnx "
                    "from the openWakeWord releases.",
                    self.dir, self.name,
                )
                return None

            wakeword, melspec, embedding = paths
            from openwakeword.model import Model

            self._model = Model(
                wakeword_models=[str(wakeword)],
                melspec_model_path=str(melspec),
                embedding_model_path=str(embedding),
                inference_framework="onnx",
            )
            log.info("wake word %s loaded from %s", self.name, wakeword.name)
        return self._model

    def detect(self, frame: np.ndarray) -> bool:
        """One 80ms frame in, "did they say it" out."""
        model = self._lazy_model()
        if model is None:
            return False

        scores = model.predict(frame)
        score = max(scores.values()) if scores else 0.0
        if score >= self.threshold:
            log.info("wake word %s at %.2f", self.name, score)
            self.reset()
            return True
        return False

    def reset(self) -> None:
        """Clear the model's internal buffer after a detection, or the same
        utterance keeps re-triggering for the next second."""
        if self._model is not None:
            self._model.reset()


class SpeakerID:
    """Identify which enrolled household member is speaking.

    Be clear about what this is: identification among a small enrolled set, not
    security. A recording of you defeats it. It is used to personalise replies
    and to attribute writes ("Anish added rice") — never to authorise anything
    that spends money or unlocks a door.
    """

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg
        self.threshold = float(cfg.section("voice").get("speaker_match_threshold", 0.65))
        self.dir = cfg.state_dir / "speakers"
        self._session: Any = None
        self._prints: dict[str, np.ndarray] = {}
        self._load()

    def _load(self) -> None:
        if not self.dir.exists():
            return
        for path in self.dir.glob("*.npy"):
            self._prints[path.stem] = np.load(path)
        if self._prints:
            log.info("loaded voiceprints: %s", ", ".join(sorted(self._prints)))

    @property
    def model_path(self) -> Path:
        return self.cfg.state_dir / "models" / "speaker-embedding.onnx"

    def _lazy_session(self) -> Any | None:
        if self._session is None:
            if not self.model_path.exists():
                return None
            import onnxruntime

            self._session = onnxruntime.InferenceSession(
                str(self.model_path), providers=["CPUExecutionProvider"]
            )
        return self._session

    def embed(self, pcm: np.ndarray) -> np.ndarray | None:
        session = self._lazy_session()
        if session is None:
            return None
        audio = (pcm.astype(np.float32) / 32768.0)[np.newaxis, :]
        outputs = session.run(None, {session.get_inputs()[0].name: audio})
        vector = np.asarray(outputs[0]).squeeze()
        norm = np.linalg.norm(vector)
        return vector / norm if norm else None

    def identify(self, pcm: np.ndarray) -> str | None:
        """Best match above threshold, or None. None is a perfectly good
        answer — an unrecognised voice still gets served, just not by name."""
        if not self._prints:
            return None
        vector = self.embed(pcm)
        if vector is None:
            return None

        best, best_score = None, -1.0
        for name, reference in self._prints.items():
            score = float(np.dot(vector, reference))
            if score > best_score:
                best, best_score = name, score

        if best_score < self.threshold:
            log.debug("no speaker match (best %.2f < %.2f)", best_score, self.threshold)
            return None
        return best

    def enroll(self, name: str, samples: list[np.ndarray]) -> bool:
        """Average several utterances into one voiceprint. Ten short phrases
        recorded in the room it will be used in beats one clean studio take."""
        vectors = [v for v in (self.embed(s) for s in samples) if v is not None]
        if not vectors:
            return False
        mean = np.mean(vectors, axis=0)
        mean = mean / np.linalg.norm(mean)
        self.dir.mkdir(parents=True, exist_ok=True)
        np.save(self.dir / f"{name}.npy", mean)
        self._prints[name] = mean
        return True
