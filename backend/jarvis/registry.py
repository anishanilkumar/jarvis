"""The provider contract, and the auto-discovery that makes adding one free.

A new feature is one file in providers/. Dropping it in is the whole
registration step — nothing here or anywhere else needs editing.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class Speech:
    """What voice says back, and optionally what the panel should do about it.

    `focus` asks the display to expand a widget, so "when's the next tram" both
    answers aloud and puts the board on screen.
    """

    text: str
    focus: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class Provider:
    """One source of data on the panel.

    Subclasses set `slug` and implement `fetch`. Everything else is optional:

      action()        makes the widget writable from touch
      handle_intent() makes it reachable by voice
      intents         the phrasings that should route here

    Scheduling (ttl / stale_after / useful_for) is *not* set here — it lives in
    jarvis.toml so it can be tuned without a deploy.
    """

    slug: str = ""
    #: Example phrasings. Passed to the STT model as the candidate label set, so
    #: listing a new one immediately extends what voice understands.
    intents: list[str] = []
    #: Set False for providers that only respond to events (e.g. music).
    polls: bool = True

    def __init__(self, cfg: Any, http: httpx.AsyncClient) -> None:
        self.cfg = cfg
        self.http = http

    async def fetch(self) -> dict[str, Any]:
        """Return this widget's payload. Raise to signal an upstream failure —
        the scheduler keeps the last good value and backs off."""
        raise NotImplementedError

    async def action(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Handle a touch write. Return a dict to merge into state, or None to
        just trigger a refresh."""
        raise NotImplementedError(f"{self.slug} has no touch actions")

    async def handle_intent(
        self, utterance: str, slots: dict[str, Any], speaker: str | None
    ) -> Speech:
        """Answer a voice command routed here."""
        raise NotImplementedError(f"{self.slug} has no voice intents")

    # -- capability probes, used by main.py to build the API surface ----------

    @classmethod
    def supports_action(cls) -> bool:
        return cls.action is not Provider.action

    @classmethod
    def supports_voice(cls) -> bool:
        return cls.handle_intent is not Provider.handle_intent


def discover() -> list[type[Provider]]:
    """Every Provider subclass under providers/, in a stable order.

    Sorted by slug so the panel's tile order and the API's key order don't
    depend on filesystem iteration order.
    """
    from jarvis import providers

    found: list[type[Provider]] = []
    for mod_info in pkgutil.iter_modules(providers.__path__):
        module = importlib.import_module(f"jarvis.providers.{mod_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Provider) and obj is not Provider and obj.slug:
                if obj not in found:
                    found.append(obj)
    return sorted(found, key=lambda p: p.slug)
