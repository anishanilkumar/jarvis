"""BVG departures for the stops this household actually leaves from.

The tile answers one question — "can I still make it?" — so it carries absolute
departure timestamps rather than a countdown. The panel derives minutes from
those itself, which is what lets it *freeze* the countdowns when it loses the Pi
instead of ticking down on data it can no longer refresh.

A *board* is one stop filtered to one direction of travel. A wall display that
shows both directions of a line is showing you, at best, half useful rows: you
leave the house heading one way. Boards are configured in jarvis.toml and
fetched concurrently, so adding one costs no wall-clock time.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from jarvis.registry import Provider, Speech

#: Every product the API knows. Needed in full because of the filtering gotcha
#: below — you cannot select products by naming only the ones you want.
ALL_PRODUCTS = (
    "suburban",
    "subway",
    "tram",
    "bus",
    "ferry",
    "express",
    "regional",
)


def _minutes_until(when: str | None, now: datetime) -> int | None:
    if not when:
        return None
    return round((datetime.fromisoformat(when) - now).total_seconds() / 60)


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _direction_allowed(
    direction: str, include: list[str], exclude: list[str]
) -> bool:
    """Substring matching, deliberately, not equality.

    Terminus names are not stable enough to match exactly: lines short-turn,
    and a timetable change can rename the far end of a route you don't care
    about. Matching a distinctive fragment survives both.

    It does NOT paper over spelling: "Hermannstr." will not match a configured
    "Hermannstraße". Copy the patterns from what the API actually reports —
    the jarvis.toml comment has the one-liner that prints them.
    """
    haystack = _norm(direction)
    if any(_norm(pattern) in haystack for pattern in exclude):
        return False
    if not include:
        return True
    return any(_norm(pattern) in haystack for pattern in include)


class Departures(Provider):
    slug = "departures"
    intents = [
        "when is the next tram",
        "when's the next tram",
        "next tram",
        "when is the next bus",
        "when is the next u-bahn",
        "next train",
        "can I catch the tram",
        "tram times",
    ]

    async def fetch(self) -> dict[str, Any]:
        conf = self.cfg.section("departures")
        boards = conf.get("boards") or []

        results = await asyncio.gather(
            *(self._fetch_board(conf, board) for board in boards)
        )

        # Warnings are collected across boards and de-duplicated: one disruption
        # frequently lands on every stop it touches, and the tile has room to
        # say "2 notices", not to say the same notice twice.
        warnings: list[str] = []
        for board in results:
            for warning in board["warnings"]:
                if warning not in warnings:
                    warnings.append(warning)

        return {"boards": results, "warnings": warnings}

    async def _fetch_board(
        self, conf: dict[str, Any], board: dict[str, Any]
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "duration": board.get("duration_minutes", conf.get("duration_minutes", 60)),
            "results": board.get("results", conf.get("results", 12)),
            "remarks": "true",
        }

        # THE GOTCHA: these are opt-*out* flags that all default to true.
        # Passing tram=true alone does nothing — every other product is still
        # true and a "tram" board quietly fills with buses. Each unwanted
        # product has to be named false explicitly.
        wanted = {product.lower() for product in board.get("products") or []}
        for product in ALL_PRODUCTS:
            params[product] = "true" if (not wanted or product in wanted) else "false"

        response = await self.http.get(
            f"{conf['api_base'].rstrip('/')}/stops/{board['stop_id']}/departures",
            params=params,
        )
        response.raise_for_status()
        raw = response.json()

        now = datetime.now(timezone.utc)
        walk = board.get("walk_minutes", conf.get("walk_minutes", 4))
        only_lines = {line.upper() for line in board.get("lines") or []}
        include = board.get("directions") or []
        exclude = board.get("exclude_directions") or []

        departures: list[dict[str, Any]] = []
        for item in raw.get("departures", []):
            line = (item.get("line") or {}).get("name") or "?"
            if only_lines and line.upper() not in only_lines:
                continue
            if not _direction_allowed(item.get("direction") or "", include, exclude):
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
            "name": board.get("name") or board.get("stop_name", ""),
            "stop": board.get("stop_name", ""),
            "toward": board.get("toward", ""),
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

        # Spoken mode words pick a board, so "when's the next u-bahn" doesn't
        # answer with a tram just because the tram board is listed first.
        products: set[str] = set()
        if "bus" in spoken:
            products = {"bus"}
        elif "tram" in spoken:
            products = {"tram"}
        elif "bahn" in spoken or "train" in spoken or "metro" in spoken:
            products = {"subway", "suburban"}

        candidates = [
            departure
            for board in data["boards"]
            for departure in board["departures"]
            if departure["catchable"]
        ]
        if wanted:
            candidates = [d for d in candidates if d["line"].upper() == wanted]
        elif products:
            candidates = [d for d in candidates if d["product"] in products]

        candidates.sort(key=lambda d: d["minutes"])

        if not candidates:
            return Speech(
                text="Nothing you can still catch right now.",
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
