"""Speech out, via Piper.

Piper runs locally on the Pi, is MIT-licensed and costs nothing. It is fast
enough on a Pi 4 for a short sentence to start playing in well under a second.

Known gap, stated rather than hidden: Piper has no Malayalam voice. Replies go
out in English regardless of the language of the question. Spoken Malayalam
would need a cloud TTS, which would reintroduce a paid dependency.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any

log = logging.getLogger(__name__)


class PiperTTS:
    def __init__(self, cfg: Any) -> None:
        self.voice = cfg.section("voice").get("tts_voice", "en_GB-alba-medium")
        self.model = cfg.state_dir / "piper" / f"{self.voice}.onnx"
        self.binary = shutil.which("piper")

    @property
    def available(self) -> bool:
        return bool(self.binary) and self.model.exists()

    async def speak(self, text: str) -> bytes | None:
        """Return a WAV of `text`, or None if Piper isn't installed.

        None is not fatal: the panel still shows the reply as text, so a missing
        voice degrades to a silent-but-working assistant rather than a broken one.
        """
        if not self.available:
            log.warning("piper unavailable (binary=%s model=%s)", self.binary, self.model)
            return None

        process = await asyncio.create_subprocess_exec(
            self.binary,
            "--model",
            str(self.model),
            "--output_file",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(text.encode())
        if process.returncode != 0:
            log.error("piper failed: %s", stderr.decode()[:200])
            return None
        return stdout
