"""Local time. The one tile that keeps working no matter what is down.

It matters more than it looks: when the Pi is unreachable and every other tile
has expired, a live clock is what keeps the panel from reading as dead hardware.
The frontend ticks it locally between refreshes; this provider exists so the
panel agrees with the Pi about the date and the timezone.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.registry import Provider, Speech


class Clock(Provider):
    slug = "clock"
    intents = ["what time is it", "what's the date", "what day is it"]

    def _now(self) -> datetime:
        return datetime.now(ZoneInfo(self.cfg.timezone))

    async def fetch(self) -> dict[str, Any]:
        now = self._now()
        return {
            "iso": now.isoformat(),
            "timezone": self.cfg.timezone,
            # Pre-formatted so the panel doesn't ship a locale library it would
            # otherwise need only for this.
            "weekday": now.strftime("%A"),
            "date": now.strftime("%-d %B %Y"),
        }

    async def handle_intent(
        self, utterance: str, slots: dict[str, Any], speaker: str | None
    ) -> Speech:
        now = self._now()
        if "date" in utterance.lower() or "day" in utterance.lower():
            return Speech(text=f"It's {now.strftime('%A, %-d %B')}.")
        return Speech(text=f"It's {now.strftime('%-I:%M %p').lstrip('0')}.")
