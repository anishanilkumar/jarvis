"""Where an understood utterance goes.

Three tiers, tried in order:
  1. a provider that declared the intent — the widgets answer for themselves
  2. Home Assistant's conversation API — anything device-shaped
  3. the answer Gemini already produced in the same call — the long tail

Tier 1 is why adding a widget extends voice for free: the catalogue below is
built from the providers' own `intents` lists, so a new file is immediately
reachable by speech with nothing central to edit.
"""

from __future__ import annotations

import logging
from typing import Any

from jarvis.registry import Provider, Speech

log = logging.getLogger(__name__)


class Router:
    def __init__(self, cfg: Any, providers: dict[str, Provider], http: Any) -> None:
        self.cfg = cfg
        self.providers = providers
        self.http = http

    def catalogue(self) -> dict[str, list[str]]:
        """Intent labels offered to the STT model as the candidate set."""
        return {
            slug: provider.intents
            for slug, provider in self.providers.items()
            if provider.intents and type(provider).supports_voice()
        }

    async def dispatch(
        self, intent: str | None, transcript: str, slots: dict[str, Any],
        speaker: str | None, fallback: str | None,
    ) -> Speech:
        if intent and intent in self.providers:
            provider = self.providers[intent]
            if type(provider).supports_voice():
                try:
                    return await provider.handle_intent(transcript, slots, speaker)
                except Exception as exc:  # noqa: BLE001
                    log.exception("intent %s failed", intent)
                    # Say what actually went wrong rather than "sorry, I didn't
                    # get that" — the user can tell a broken shopping list from
                    # a misheard word, and only one of those is worth repeating.
                    return Speech(text=f"The {intent} widget failed: {type(exc).__name__}.")

        if intent == "home_assistant":
            return await self._ask_home_assistant(transcript)

        if fallback:
            return Speech(text=fallback)

        # Heard clearly, understood by nobody — which is a different failure
        # from not hearing, and has to sound different. "I didn't catch that"
        # invites you to repeat yourself, and repeating yourself will not help:
        # no widget claims this and there is no longer a general-knowledge tier
        # behind them to catch it. Say so, so the next thing you try is
        # different words rather than the same words louder.
        return Speech(text="I don't know how to help with that.")

    async def _ask_home_assistant(self, transcript: str) -> Speech:
        conf = self.cfg.section("homeassistant")
        if not self.cfg.ha_token:
            return Speech(text="Home Assistant isn't connected yet.")

        try:
            response = await self.http.post(
                f"{conf['api_base'].rstrip('/')}/conversation/process",
                headers={"Authorization": f"Bearer {self.cfg.ha_token}"},
                json={"text": transcript, "language": "en"},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("home assistant conversation failed: %s", exc)
            return Speech(text="Home Assistant didn't answer.")

        spoken = (
            payload.get("response", {})
            .get("speech", {})
            .get("plain", {})
            .get("speech")
        )
        return Speech(text=spoken or "Done.")
