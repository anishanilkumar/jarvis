"""Wake word and speaker identification — the two things that run on the Pi
before anything leaves the house.

openWakeWord ships a pretrained "hey jarvis" model, which is exactly the phrase
this system wants, and it is cheap enough that a Pi 3 runs 15-20 models at once.
On a Pi 4 already busy with Jellyfin it is not a meaningful load.

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
        self._model: Any = None

    def _lazy_model(self) -> Any:
        if self._model is None:
            from openwakeword.model import Model

            self._model = Model(wakeword_models=[self.name], inference_framework="onnx")
        return self._model

    def detect(self, frame: np.ndarray) -> bool:
        """One 80ms frame in, "did they say it" out."""
        scores = self._lazy_model().predict(frame)
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
