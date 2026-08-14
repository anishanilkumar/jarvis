"""Play YouTube Music on the tablet, via Home Assistant.

The Pi can't launch an Android app directly, so the chain is:
Jarvis -> HA notify -> Companion App on the tablet -> `command_activity` ->
the real YouTube Music app with a search-and-play intent.

Using the signed-in app is what makes this work at all: the existing Premium
subscription applies, playback is ad-free, and there are no cookie or token
workarounds to maintain. Android keeps the audio going once the kiosk returns
to the foreground.

This provider never polls — it holds only what we last asked for. It does not
claim to know what is *actually* playing; the tablet's media session isn't
visible from here, and inventing a now-playing display that silently goes wrong
would be worse than showing nothing.
"""

from __future__ import annotations

import time
from typing import Any

from jarvis.registry import Provider, Speech


class Music(Provider):
    slug = "music"
    polls = False
    intents = ["play", "play some music", "put on", "play music"]

    def __init__(self, cfg: Any, http: Any) -> None:
        super().__init__(cfg, http)
        self._last: dict[str, Any] | None = None

    async def fetch(self) -> dict[str, Any]:
        return {"last_request": self._last}

    async def _notify_tablet(self, query: str) -> None:
        conf = self.cfg.section("homeassistant")
        if not self.cfg.ha_token:
            raise RuntimeError("HA_TOKEN is not set")

        response = await self.http.post(
            f"{conf['api_base'].rstrip('/')}/services/{conf['notify_service'].strip('/')}",
            headers={"Authorization": f"Bearer {self.cfg.ha_token}"},
            json={
                "message": "command_activity",
                "data": {
                    "intent_action": conf["music_intent_action"],
                    "intent_package_name": conf["music_package"],
                    "intent_extras": f"query:{query}",
                },
            },
        )
        response.raise_for_status()

    async def action(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        query = (payload.get("query") or "").strip()
        if not query:
            raise ValueError("nothing to play")
        await self._notify_tablet(query)
        self._last = {"query": query, "at": time.time()}
        return self._last

    async def handle_intent(
        self, utterance: str, slots: dict[str, Any], speaker: str | None
    ) -> Speech:
        query = (slots.get("query") or "").strip()
        if not query:
            return Speech(text="What would you like me to play?")
        await self.action({"query": query})
        return Speech(text=f"Playing {query}.", focus="music")
