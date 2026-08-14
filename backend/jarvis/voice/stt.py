"""Speech to text and intent, in one call.

This is the single proprietary dependency in the whole system, and it is
isolated here on purpose: swapping `provider = "whisper"` in jarvis.toml goes
fully local and offline, at the cost of much weaker Malayalam.

One Gemini call does transcription, intent classification and the
general-knowledge fallback together. That collapses what would otherwise be
three services into one, and it means the candidate intent list — assembled
from the providers' own `intents` — is applied *during* recognition rather than
by pattern-matching a transcript afterwards.

The honest cost: on the free tier Google's terms allow prompts and audio to be
used to improve their models, including human review. The consumer Gemini
subscription does not change that; API billing is separate. Nothing leaves the
house until the wake word fires, so this covers deliberate commands rather than
ambient room audio — but it is a trade, not a free lunch.
"""

from __future__ import annotations

import json
import logging
import struct
from dataclasses import dataclass
from datetime import date
from typing import Any

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


@dataclass
class Understanding:
    transcript: str
    """Provider slug the utterance routes to, or None for a general question."""
    intent: str | None
    slots: dict[str, Any]
    """Set when the model answered a general question directly."""
    answer: str | None = None


def wav_bytes(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV header.

    Gemini needs a container, and writing 44 bytes here avoids depending on
    ffmpeg being present on the Pi for a job this small.
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


SCHEMA = {
    "type": "object",
    "properties": {
        "transcript": {"type": "string"},
        "intent": {"type": "string"},
        "slots": {
            "type": "object",
            "properties": {
                "item": {"type": "string"},
                "query": {"type": "string"},
                "line": {"type": "string"},
                "amount": {"type": "number"},
            },
        },
        "answer": {"type": "string"},
    },
    "required": ["transcript", "intent"],
}


def build_prompt(catalogue: dict[str, list[str]], members: list[str]) -> str:
    lines = [
        "You are the speech front-end of a household wall display in Berlin.",
        "Transcribe the audio, then route it.",
        "",
        "Available intents and example phrasings:",
    ]
    for slug, examples in sorted(catalogue.items()):
        lines.append(f"  {slug}: {'; '.join(examples)}")
    lines += [
        "  home_assistant: turning devices/lights/switches on or off",
        "  none: anything else",
        "",
        "Rules:",
        "- Transcribe verbatim in the language spoken (English or Malayalam).",
        "- Pick exactly one intent from the list above.",
        "- Fill slots when present: `item` for things to add to a list, `query`"
        "  for music to play, `line` for a specific tram or bus line, `amount`"
        "  for quantities.",
        "- If the intent is `none`, answer the question yourself in `answer`,"
        "  in at most two spoken sentences. Reply in English even when asked in"
        "  Malayalam: the panel's text-to-speech has no Malayalam voice.",
        "- Never invent departure times, weather or shopping contents. Those come"
        "  from live data, so route them to the right intent instead of guessing.",
        f"- Today is {date.today().isoformat()}. Household members: {', '.join(members) or 'unknown'}.",
    ]
    return "\n".join(lines)


class GeminiSTT:
    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg
        stt = cfg.section("voice").get("stt", {})
        self.model = stt.get("model", "gemini-2.5-flash")
        self.daily_budget = int(stt.get("daily_budget", 400))
        self._client: Any = None
        self._spent = 0
        self._spent_on = date.today()

    def _budget_ok(self) -> bool:
        """Free tier allows 1500/day. A household lands near 50; hitting this
        ceiling means something is retrying in a loop, and the right response is
        to stop rather than to burn the quota silently."""
        if self._spent_on != date.today():
            self._spent_on, self._spent = date.today(), 0
        return self._spent < self.daily_budget

    def _lazy_client(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.cfg.gemini_api_key)
        return self._client

    async def understand(
        self, pcm: bytes, catalogue: dict[str, list[str]], members: list[str]
    ) -> Understanding | None:
        if not self.cfg.gemini_api_key:
            log.error("GEMINI_API_KEY is not set; voice cannot transcribe")
            return None
        if not self._budget_ok():
            log.error("daily STT budget of %d exhausted; refusing", self.daily_budget)
            return None

        from google.genai import types

        self._spent += 1
        response = await self._lazy_client().aio.models.generate_content(
            model=self.model,
            contents=[
                build_prompt(catalogue, members),
                types.Part.from_bytes(data=wav_bytes(pcm), mime_type="audio/wav"),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SCHEMA,
                temperature=0.0,
            ),
        )

        try:
            parsed = json.loads(response.text)
        except (json.JSONDecodeError, TypeError, AttributeError):
            log.warning("unparseable STT response: %r", getattr(response, "text", None))
            return None

        intent = parsed.get("intent")
        return Understanding(
            transcript=parsed.get("transcript", "").strip(),
            intent=None if intent in (None, "", "none") else intent,
            slots=parsed.get("slots") or {},
            answer=(parsed.get("answer") or "").strip() or None,
        )


def build(cfg: Any) -> GeminiSTT:
    """Chosen by jarvis.toml. A local whisper backend slots in here."""
    provider = cfg.section("voice").get("stt", {}).get("provider", "gemini")
    if provider != "gemini":
        raise NotImplementedError(
            f"stt provider {provider!r} is not built yet — only 'gemini' exists today"
        )
    return GeminiSTT(cfg)
