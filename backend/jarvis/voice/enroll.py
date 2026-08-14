"""Record voiceprints, so Jarvis can tell who is speaking.

    python -m jarvis.voice.enroll anish

Records ten short phrases and averages them into one embedding. Record them
where the tablet actually hangs, in normal speaking voice — a studio-clean
sample enrolled at a desk matches poorly against a kitchen at breakfast.

Again, plainly: this identifies among a handful of enrolled people. It is not
authentication, and a recording defeats it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

from jarvis import config
from jarvis.voice.wakeword import SAMPLE_RATE, SpeakerID

PHRASES = [
    "when is the next tram",
    "what's the weather like today",
    "add milk to the shopping list",
    "what's for dinner tonight",
    "play something quiet",
    "will it rain this evening",
    "how cold is it outside",
    "what's on the shopping list",
    "hey jarvis, what time is it",
    "turn the kitchen light off",
]


def record(seconds: float, device: str | None) -> np.ndarray:
    """Capture via `arecord`, which is already on any NixOS box with ALSA."""
    command = ["arecord", "-q", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1",
               "-d", str(seconds), "-t", "wav"]
    if device:
        command += ["-D", device]
    raw = subprocess.run(command, capture_output=True, check=True).stdout

    import io

    with wave.open(io.BytesIO(raw)) as handle:
        return np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="household member, as listed in jarvis.toml")
    parser.add_argument("--device", help="ALSA device, e.g. plughw:1,0")
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--from-dir", type=Path, help="use existing .wav files instead of recording")
    args = parser.parse_args()

    cfg = config.load()
    speakers = SpeakerID(cfg)

    if not speakers.model_path.exists():
        print(f"No embedding model at {speakers.model_path}.", file=sys.stderr)
        print("Fetch a WeSpeaker/ECAPA ONNX export there first.", file=sys.stderr)
        return 1

    samples: list[np.ndarray] = []
    if args.from_dir:
        for path in sorted(args.from_dir.glob("*.wav")):
            with wave.open(str(path)) as handle:
                samples.append(np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16))
        print(f"loaded {len(samples)} samples from {args.from_dir}")
    else:
        print(f"Recording {len(PHRASES)} phrases for {args.name}. Speak normally.\n")
        for index, phrase in enumerate(PHRASES, 1):
            input(f"  [{index}/{len(PHRASES)}] press enter, then say: “{phrase}” ")
            samples.append(record(args.seconds, args.device))

    if not speakers.enroll(args.name, samples):
        print("Enrollment failed — no usable embeddings.", file=sys.stderr)
        return 1

    print(f"\nEnrolled {args.name}. Voiceprint written to {speakers.dir / (args.name + '.npy')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
