"""Speech to text, on the Pi.

This used to be a cloud call, and the README used to admit it as the one
proprietary dependency in the house. It is now whisper.cpp on the same Raspberry
Pi that serves the wall, which makes the whole system open source and, more to
the point, makes it *predictable*. The cloud version failed three separate ways
in a single evening of testing: the pinned model was retired for new API keys
and answered 404, its replacement returned 503 under load, and a third
translated English into German. None of those are things a household display can
route around, and all of them arrive as "voice is broken" with no explanation.

What that costs, stated rather than buried:

- **English only.** These are the `.en` models, and they are better at English
  for their size precisely because they gave up everything else.
- **No general-knowledge answers.** The cloud call used to route *and* answer
  the long tail in one go. Now an utterance that matches no widget is told so.
  See `intent.py` — the routing that came free with the transcript now happens
  locally, against the providers' own declared phrasings.

What it buys: no quota, no key, no rate limit, no model retired out from under
a working config, no audio leaving the house, and an answer in a couple of
seconds instead of nine.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import struct
import tempfile
from dataclasses import dataclass, field
from typing import Any

from jarvis.voice.intent import IntentMatcher, slots_for

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


@dataclass
class Understanding:
    transcript: str
    """Provider slug the utterance routes to, or None if nothing matched."""
    intent: str | None
    slots: dict[str, Any] = field(default_factory=dict)
    """Always None now. Kept because the router still offers this tier, and a
    future local model that can answer the long tail would fill it in."""
    answer: str | None = None


def wav_bytes(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV header.

    whisper.cpp reads files, not pipes, and insists on 16 kHz mono — which is
    exactly what the tablet already sends. Writing 44 bytes here avoids
    depending on ffmpeg being present on the Pi for a job this small.
    """
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )


#: Whisper does not return nothing when it hears nothing — it returns its
#: favourite something. These are the ones that actually turn up on room tone
#: and door slams that scored high enough on the wake word. Treated as silence,
#: because acting on "Thank you." is worse than admitting we missed it.
_NOISE = frozenset({"you", "thank you", "thanks for watching", "bye", "oh", "um"})


def _clean(raw: str) -> str:
    """whisper.cpp's stdout, reduced to the words that were actually said."""
    text = " ".join(raw.split()).strip()
    # Non-speech is annotated in brackets: [BLANK_AUDIO], (wind blowing).
    if text.startswith(("[", "(")) and text.endswith(("]", ")")):
        return ""
    if text.strip(" .!?,").lower() in _NOISE:
        return ""
    return text


class WhisperSTT:
    def __init__(self, cfg: Any) -> None:
        stt = cfg.section("voice").get("stt", {})
        self.name = stt.get("model", "base.en")
        self.model = cfg.state_dir / "whisper" / f"ggml-{self.name}.bin"
        self.binary = shutil.which("whisper-cli")
        # The Pi has four cores and also serves the wall, Jellyfin and Samba.
        # Leaving one alone keeps a transcription from making the panel stutter.
        self.threads = int(stt.get("threads", 3))

        # The single most important number here. whisper pads every clip to
        # thirty seconds and runs its encoder over the whole window, so "next
        # tram" costs exactly what half a minute of speech costs — measured on
        # this Pi, 27 seconds for a one-second command. Shrinking the encoder
        # context to the part that actually contains audio is what makes local
        # transcription viable at all on this hardware. 0 keeps the full window.
        self.audio_context = int(stt.get("audio_context", 768))
        self._matcher: IntentMatcher | None = None

    @property
    def available(self) -> bool:
        return bool(self.binary) and self.model.exists()

    async def understand(self, pcm: bytes, catalogue: dict[str, list[str]]) -> Understanding | None:
        if not self.available:
            log.error(
                "whisper unavailable (binary=%s model=%s); fetch ggml-%s.bin into %s",
                self.binary, self.model, self.name, self.model.parent,
            )
            return None

        transcript = await self._transcribe(pcm)
        if transcript is None:
            return None
        if not transcript:
            return Understanding(transcript="", intent=None)

        # Built on first use rather than at startup, so a provider enabled in
        # jarvis.toml after the service came up is still reachable by voice.
        if self._matcher is None:
            self._matcher = IntentMatcher(catalogue)

        intent = self._matcher.match(transcript)
        return Understanding(
            transcript=transcript,
            intent=intent,
            slots=slots_for(intent, transcript),
        )

    async def _transcribe(self, pcm: bytes) -> str | None:
        """Run whisper.cpp over one command. None means it failed outright."""
        handle, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(handle, "wb") as clip:
                clip.write(wav_bytes(pcm))

            command = [
                self.binary,
                "--model", str(self.model),
                "--file", path,
                "--language", "en",
                "--threads", str(self.threads),
                "--no-timestamps",
                "--no-prints",
            ]
            if self.audio_context:
                command += ["--audio-ctx", str(self.audio_context)]

            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
        finally:
            # PrivateTmp puts this in the unit's own namespace, but a wall panel
            # runs for months and a leaked clip per utterance adds up.
            try:
                os.unlink(path)
            except OSError:
                pass

        if process.returncode != 0:
            log.error("whisper failed (rc=%s): %s", process.returncode, stderr.decode()[:200])
            return None

        return _clean(stdout.decode())


def build(cfg: Any) -> WhisperSTT:
    """Chosen by jarvis.toml. Only the local backend exists."""
    provider = cfg.section("voice").get("stt", {}).get("provider", "whisper")
    if provider != "whisper":
        raise NotImplementedError(
            f"stt provider {provider!r} is not built — only local 'whisper' exists. "
            "The cloud backend was removed deliberately; see the module docstring."
        )
    return WhisperSTT(cfg)
