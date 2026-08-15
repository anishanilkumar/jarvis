"""The voice service: audio in over WebSocket, speech out.

Runs as its own process (port 8141) rather than inside the dashboard API,
because it is a stateful realtime pipeline with heavy imports, and a crash in
wake-word inference should never take the wall display down with it.

Flow per connection:

    tablet ──16kHz PCM──▶ openWakeWord ──▶ speaker ID ──▶ Gemini ──▶ router
                                                                       │
    tablet ◀──────────── WAV (Piper) ◀─────────────────────────────────┘

Nothing leaves the house until the wake word matches. The tablet has already
gated on local speech detection, so silence never even reaches this process.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from jarvis import config
from jarvis.http import build_client
from jarvis.registry import discover
from jarvis.voice import stt as stt_module
from jarvis.voice.router import Router
from jarvis.voice.tts import PiperTTS
from jarvis.voice.wakeword import FRAME_SAMPLES, SAMPLE_RATE, SpeakerID, WakeWord

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="Jarvis voice", docs_url=None, redoc_url=None)


class Session:
    """One tablet's audio stream and its little state machine."""

    def __init__(self, socket: WebSocket, deps: dict[str, Any]) -> None:
        self.socket = socket
        self.deps = deps
        self.cfg = deps["cfg"]
        self.frames = np.zeros(0, dtype=np.int16)
        self.command: list[np.ndarray] = []
        self.capturing = False
        self.captured_samples = 0
        self.silence_frames = 0

        voice = self.cfg.section("voice")
        self.max_samples = int(voice.get("max_command_seconds", 8)) * SAMPLE_RATE
        # Silence is measured in 80ms frames; the tablet stops sending during
        # true silence, so this mostly bounds the tail after speech ends.
        self.silence_limit = max(1, int(voice.get("silence_timeout_ms", 1200) / 80))

    async def send(self, **message: Any) -> None:
        await self.socket.send_text(json.dumps(message))

    async def feed(self, pcm: bytes) -> None:
        self.frames = np.concatenate([self.frames, np.frombuffer(pcm, dtype=np.int16)])

        while len(self.frames) >= FRAME_SAMPLES:
            frame, self.frames = self.frames[:FRAME_SAMPLES], self.frames[FRAME_SAMPLES:]

            if not self.capturing:
                if self.deps["wake"].detect(frame):
                    await self.begin()
                continue

            self.command.append(frame)
            self.captured_samples += FRAME_SAMPLES
            if self.captured_samples >= self.max_samples:
                await self.finish()

    async def begin(self) -> None:
        self.capturing = True
        self.command = []
        self.captured_samples = 0
        self.silence_frames = 0
        await self.send(type="wake")

    async def on_gap(self) -> None:
        """Called when the tablet stops sending — i.e. the speaker paused."""
        if not self.capturing:
            return
        self.silence_frames += 1
        if self.silence_frames >= self.silence_limit:
            await self.finish()

    async def finish(self) -> None:
        self.capturing = False
        audio = np.concatenate(self.command) if self.command else np.zeros(0, dtype=np.int16)
        self.command = []

        # Anything this short is a door slam or a cough that scored high enough
        # on the wake word. Sending it would burn quota to transcribe nothing.
        if len(audio) < SAMPLE_RATE // 2:
            await self.send(type="idle")
            return

        speaker = self.deps["speakers"].identify(audio)

        # The STT provider is the one part of this pipeline that lives on
        # someone else's computer, and it fails in ways nothing here controls:
        # a model retired out from under the key, a 503 under load, a quota
        # exhausted mid-sentence. Uncaught, that exception unwinds the receive
        # loop and takes the socket down — the panel reconnects a few seconds
        # later and the person at the wall just never gets an answer, which
        # reads exactly like the wake word having missed them.
        try:
            understanding = await self.deps["stt"].understand(
                audio.tobytes(),
                self.deps["router"].catalogue(),
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("speech recognition failed")
            await self.reply(f"Speech recognition failed: {type(exc).__name__}.")
            return

        if understanding is None or not understanding.transcript:
            await self.reply("I didn't catch that.")
            return

        await self.send(type="transcript", text=understanding.transcript)
        log.info(
            "heard %r intent=%s speaker=%s",
            understanding.transcript, understanding.intent, speaker,
        )

        reply = await self.deps["router"].dispatch(
            understanding.intent,
            understanding.transcript,
            understanding.slots,
            speaker,
            understanding.answer,
        )

        await self.reply(reply.text, focus=reply.focus)

    async def reply(self, text: str, focus: str | None = None) -> None:
        """Say it, and show it. Every answer goes out both ways.

        The failure replies used to be text-only, which is the wrong way round:
        you are three metres from the panel and were talking to it, so a reply
        you have to walk over and read is a reply you never receive. Silence
        after the wake chime is indistinguishable from not having been heard,
        and "it didn't hear me" is the one wrong conclusion to leave someone
        with when the truth is that the recogniser is down.
        """
        await self.send(type="reply", text=text, focus=focus)
        if audio_out := await self.deps["tts"].speak(text):
            await self.socket.send_bytes(audio_out)


@app.on_event("startup")
async def startup() -> None:
    cfg = config.load()
    http = build_client(cfg)
    providers = {cls.slug: cls(cfg, http) for cls in discover()}

    app.state.deps = {
        "cfg": cfg,
        "http": http,
        "wake": WakeWord(cfg),
        "speakers": SpeakerID(cfg),
        "stt": stt_module.build(cfg),
        "tts": PiperTTS(cfg),
        "router": Router(cfg, providers, http),
    }
    log.info("voice service ready; intents: %s", sorted(app.state.deps["router"].catalogue()))


@app.get("/health")
async def health() -> dict[str, Any]:
    deps = app.state.deps
    return {
        "ok": True,
        "wake_word": deps["wake"].name,
        # All three are false in exactly one interesting way — a model file that
        # was never fetched — and all three fail silently at runtime rather than
        # loudly at startup. Worth three lines here to make that visible: the
        # whole pipeline now runs on model files sitting in the state directory,
        # and "voice does nothing" should be one curl to diagnose.
        "wake_word_available": deps["wake"].available,
        "stt_available": deps["stt"].available,
        "stt_model": deps["stt"].name,
        "tts_available": deps["tts"].available,
        "enrolled_speakers": sorted(deps["speakers"]._prints),
        "intents": sorted(deps["router"].catalogue()),
    }


@app.websocket("/voice")
async def voice_socket(socket: WebSocket) -> None:
    await socket.accept()
    session = Session(socket, app.state.deps)
    log.info("panel connected")

    try:
        while True:
            try:
                message = await asyncio.wait_for(socket.receive(), timeout=0.08)
            except asyncio.TimeoutError:
                # No audio this tick means the tablet's local gate says silence.
                await session.on_gap()
                continue

            if message["type"] == "websocket.disconnect":
                break
            if data := message.get("bytes"):
                await session.feed(data)
            elif text := message.get("text"):
                if json.loads(text).get("type") == "push_to_talk":
                    # The always-works path when the wake word doesn't hear you
                    # across a noisy kitchen.
                    await session.begin()
    except WebSocketDisconnect:
        pass
    finally:
        log.info("panel disconnected")
