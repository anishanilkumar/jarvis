"""BVG departures for the home stop.

The tile answers one question — "can I still make it?" — so it carries absolute
departure timestamps rather than a countdown. The panel derives minutes from
those itself, which is what lets it *freeze* the countdowns when it loses the Pi
instead of ticking down on data it can no longer refresh.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from jarvis.registry import Provider, Speech


def _minutes_until(when: str | None, now: datetime) -> int | None:
    if not when:
        return None
    return round((datetime.fromisoformat(when) - now).total_seconds() / 60)


class Departures(Provider):
    slug = "departures"
    intents = [
        "when is the next tram",
        "when's the next tram",
        "next tram",
        "when is the next bus",
        "can I catch the tram",
        "tram times",
    ]

    async def fetch(self) -> dict[str, Any]:
        conf = self.cfg.section("departures")
        params: dict[str, Any] = {
            "duration": conf.get("duration_minutes", 60),
            "results": conf.get("results", 12),
            "remarks": "true",
        }
        # The API takes one boolean query param per product; listing only the
        # ones we want keeps regional trains off a tram-and-bus stop tile.
        for product in conf.get("products") or []:
            params[product] = "true"

        response = await self.http.get(
            f"{conf['api_base'].rstrip('/')}/stops/{conf['stop_id']}/departures",
            params=params,
        )
        response.raise_for_status()
        raw = response.json()

        now = datetime.now(timezone.utc)
        walk = conf.get("walk_minutes", 4)
        only_lines = {line.upper() for line in conf.get("lines") or []}

        departures: list[dict[str, Any]] = []
        for item in raw.get("departures", []):
            line = (item.get("line") or {}).get("name") or "?"
            if only_lines and line.upper() not in only_lines:
                continue

            when = item.get("when")
            planned = item.get("plannedWhen")
            cancelled = bool(item.get("cancelled"))
            minutes = _minutes_until(when or planned, now)

            departures.append(
                {
                    "trip_id": item.get("tripId"),
                    "line": line,
                    "product": (item.get("line") or {}).get("product"),
                    "direction": item.get("direction") or "",
                    # Absolute times: the panel formats and counts down from
                    # these, so it can stop counting when it goes offline.
                    "when": when,
                    "planned": planned,
                    # HAFAS reports delay in seconds; minutes is what a person
                    # reads off a wall.
                    "delay_minutes": round((item.get("delay") or 0) / 60),
                    "cancelled": cancelled,
                    "minutes": minutes,
                    # Dimmed rather than hidden — knowing you just missed one is
                    # itself useful information.
                    "catchable": (not cancelled) and minutes is not None and minutes >= walk,
                    "platform": item.get("platform") or item.get("plannedPlatform"),
                }
            )

        # Warnings only. Every stop carries permanent "hint" remarks (lift out
        # of service, ticket info) that would drown the real disruptions.
        warnings: list[str] = []
        for item in raw.get("departures", []):
            for remark in item.get("remarks") or []:
                if remark.get("type") == "warning":
                    text = (remark.get("text") or remark.get("summary") or "").strip()
                    if text and text not in warnings:
                        warnings.append(text)

        return {
            "stop": conf.get("stop_name", ""),
            "walk_minutes": walk,
            "departures": departures,
            "warnings": warnings,
            "updated_at": raw.get("realtimeDataUpdatedAt"),
        }

    async def handle_intent(
        self, utterance: str, slots: dict[str, Any], speaker: str | None
    ) -> Speech:
        data = await self.fetch()
        wanted = (slots.get("line") or "").upper()
        spoken = utterance.lower()

        candidates = [d for d in data["departures"] if d["catchable"]]
        if wanted:
            candidates = [d for d in candidates if d["line"].upper() == wanted]
        elif "bus" in spoken:
            candidates = [d for d in candidates if d["product"] == "bus"]
        elif "tram" in spoken:
            candidates = [d for d in candidates if d["product"] == "tram"]

        if not candidates:
            return Speech(
                text=f"Nothing you can still catch from {data['stop']} right now.",
                focus="departures",
            )

        first = candidates[0]
        parts = [
            f"{first['line']} to {first['direction']} in {first['minutes']} minutes",
        ]
        if first["delay_minutes"] > 0:
            parts.append(f"running {first['delay_minutes']} minutes late")
        if len(candidates) > 1:
            second = candidates[1]
            parts.append(f"then the {second['line']} in {second['minutes']}")

        return Speech(text=", ".join(parts) + ".", focus="departures")
