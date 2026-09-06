"""BVG departures for the stops this household actually leaves from.

The tile answers one question — "can I still make it?" — so it carries absolute
departure timestamps rather than a countdown. The panel derives minutes from
those itself, which is what lets it *freeze* the countdowns when it loses the Pi
instead of ticking down on data it can no longer refresh.

A *board* is one stop filtered to one direction of travel. A wall display that
shows both directions of a line is showing you, at best, half useful rows: you
leave the house heading one way. Boards are configured in jarvis.toml and
fetched concurrently, so adding one costs no wall-clock time.

Every departure the stop reports in the configured window is sent, including
the ones already out of reach on foot. What to *show* is the panel's decision
and it changes minute by minute as the walk clock runs down — a board trimmed
here would be trimmed as of the last fetch, and the expanded view could never
show the full timetable at all.

Departures are also grouped into *routes* — one line heading one way, carrying
its next several times. That grouping is the compact form the wall wants: a
board listing departures one per row spends two of its four columns repeating
the line and the destination, and at a stop with ten routes you read ten rows
to learn about three of them. One row per route, several numbers along it,
says the same thing in a third of the height.
"""

from __future__ import annotations

import asyncio
import html
import re
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


#: Station-class prefixes HAFAS puts on a destination. On a wall you already
#: know an S1 terminates at an S-Bahn station; the letters are pure noise.
_CLASS_PREFIXES = ("S+U ", "U+S ", "S ", "U ")


def _destination(direction: str) -> str:
    """A HAFAS direction string, cut down to the words you actually read.

    HAFAS destinations carry a lot that is true but not worth wall space:
    "S+U Rathaus Steglitz -> 285 Richtung Andrezeile" is a terminus plus an
    onward connection, "S Wannsee Bhf (Berlin)" is three words of disambiguation
    around one word of destination, and "Zehlendorf, Busseallee" is a district
    followed by the street the bus happens to stop in.

    The district is kept over the street, because a district is where you are
    going and a street is where the driver parks. Where that reads badly for a
    particular stop, the board's [groups] table overrides this entirely.
    """
    text = direction.split(" -> ")[0]          # onward connection, not our trip
    text = re.split(r"\s+via\s+", text)[0]     # "Lindenhof via S Südkreuz"
    text = re.sub(r"\s*\([^)]*\)", "", text)   # "(Berlin)", "(TF)"
    text = text.split(",")[0]                  # "Zehlendorf, Busseallee"
    text = " ".join(text.split())

    for prefix in _CLASS_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    if text.endswith(" Bhf"):
        text = text[: -len(" Bhf")]

    # Only as a suffix. "Hermannstraße" is one word and everyone reads
    # "Hermannstr.", but "Straße des 17. Juni" is a name that starts with the
    # word and abbreviating that one just looks broken.
    text = re.sub(r"(?i)(?<=\w)stra(?:ß|ss)e\b", "str.", text)
    return text.strip() or direction


def _group_label(direction: str, groups: dict[str, list[str]]) -> str | None:
    """The configured name for this heading, if the board declares one.

    This is what folds short-turns back into the service they belong to. The U7
    reports five northbound termini — Rathaus Spandau and four points short of
    it — and five strips for one direction of one line is exactly the noise the
    route grouping exists to remove. Substring matching, and first match wins,
    so order the table with the specific patterns above the general ones.
    """
    haystack = _norm(direction)
    for label, patterns in groups.items():
        if any(_norm(pattern) in haystack for pattern in patterns):
            return label
    return None


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
        keep = board.get("results", conf.get("results", 12))

        # Ask for far more than we intend to show. `results` is applied upstream,
        # before any of our filtering, so a board that keeps one direction of one
        # line was asking for twelve departures and rendering one — the rest of
        # the tile went blank.
        #
        # Route grouping raises the floor again, and this is the subtle one: a
        # cap that is generous for a board is stingy for a board's *routes*. A
        # busy interchange runs seventy-odd departures an hour across seventeen
        # headings, so twelve rows is one row per route and every strip on the
        # tile shows a single number. The depth has to be there per route, which
        # means fetching most of the hour. Over-fetching costs nothing on a 30s
        # refresh and both the flat list and each strip are trimmed below.
        params: dict[str, Any] = {
            "duration": board.get("duration_minutes", conf.get("duration_minutes", 60)),
            "results": max(keep * 10, 120),
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
        # The one threshold: leave now and you are on the platform in this many
        # minutes. Anything sooner is gone. There is no grace window — a margin
        # that quietly redefines "too late" makes the board disagree with the
        # walk it prints in its own header.
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
                    # The same heading, cut to wall length. Carried per
                    # departure as well as per route so the expanded list and
                    # the spoken answer read the same as the tile does.
                    "destination": _destination(item.get("direction") or ""),
                    # Absolute times: the panel formats and counts down from
                    # these, so it can stop counting when it goes offline.
                    "when": when,
                    "planned": planned,
                    # HAFAS reports delay in seconds; minutes is what a person
                    # reads off a wall.
                    "delay_minutes": round((item.get("delay") or 0) / 60),
                    "cancelled": cancelled,
                    "minutes": minutes,
                    # Only a hint for the voice answer. The panel recomputes it
                    # every second from `when`, because this one was true when
                    # the Pi fetched and stops being true while the tile sits
                    # on the wall.
                    "catchable": (not cancelled) and minutes is not None and minutes >= walk,
                    "platform": item.get("platform") or item.get("plannedPlatform"),
                }
            )

        # Warnings only. Every stop carries permanent "hint" remarks (lift out
        # of service, ticket info) that would drown the real disruptions.
        #
        # Unescaped because BVG's remark text arrives HTML-escaped and lands in
        # a text node, so the panel was showing literal "&#60; &#62;" mid
        # sentence where the notice meant an arrow.
        warnings: list[str] = []
        for item in raw.get("departures", []):
            for remark in item.get("remarks") or []:
                if remark.get("type") == "warning":
                    text = html.unescape(
                        remark.get("text") or remark.get("summary") or ""
                    ).strip()
                    if text and text not in warnings:
                        warnings.append(text)

        # One row per line-and-heading. The panel decides which rows fit and
        # re-decides every tick, so the order here only has to be STABLE: the
        # stop reports departures by time, and grouping them in arrival order
        # would reshuffle the board every time a bus ran early.
        #
        # The groups table is the declared order, and it is ordered on purpose —
        # TOML preserves key order, so the sequence you write the headings in is
        # the sequence they sit in on the wall. Anything ungrouped follows, in
        # the order the stop first mentioned it.
        groups: dict[str, list[str]] = board.get("groups") or {}
        declared = {label: index for index, label in enumerate(groups)}
        depth = board.get("route_length", conf.get("route_length", 4))

        routes: dict[tuple[str, str], dict[str, Any]] = {}
        for departure in departures:
            destination = (
                _group_label(departure["direction"], groups)
                or departure["destination"]
            )
            route = routes.setdefault(
                (departure["line"], destination),
                {
                    "line": departure["line"],
                    "product": departure["product"],
                    "destination": destination,
                    # Position in the declared order; ungrouped routes sort
                    # after every declared one, by when they were first seen.
                    "order": declared.get(destination, len(declared) + len(routes)),
                    "departures": [],
                },
            )
            route["departures"].append(departure)

        ordered = sorted(routes.values(), key=lambda route: (route["order"], route["line"]))

        for route in ordered:
            # Depth is per route and generous rather than exact: the panel drops
            # the ones already out of walking reach, so a strip trimmed to
            # exactly what it displays would empty from the left over the
            # quarter-hour and end up showing nothing at all.
            route["departures"] = route["departures"][: depth * 2]

        return {
            "name": board.get("name") or board.get("stop_name", ""),
            "stop": board.get("stop_name", ""),
            "walk_minutes": walk,
            # How many route strips this board is worth on the ambient tile. A
            # display decision, but it belongs to the board rather than the
            # widget: a U-Bahn platform and the half-dozen bus routes sharing
            # its street do not deserve the same number of rows.
            "rows": board.get("rows", conf.get("rows", 3)),
            # How many countdowns each strip carries. Same argument — a train
            # every four minutes says something with four numbers that a bus
            # every twenty cannot.
            "route_length": depth,
            # How the panel picks which rows fit when there are more routes than
            # rows. "soonest" for a stop whose lines are alternatives — five bus
            # lines off one corner, where the one leaving in three minutes is
            # worth a row and the same line in fifty is not. "listed" for a stop
            # whose lines go to genuinely different places, where sorting by
            # departure time silently drops a whole direction the moment its
            # train is a few minutes further off.
            "order": board.get("order", conf.get("order", "listed")),
            "routes": ordered,
            # Kept flat as well. The panel reads only `routes` now, but the
            # spoken answer picks the single soonest departure across every
            # board, and grouping is the wrong shape for that question.
            "departures": departures[:keep],
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
            f"{first['line']} to {first['destination']} in {first['minutes']} minutes",
        ]
        if first["delay_minutes"] > 0:
            parts.append(f"running {first['delay_minutes']} minutes late")
        if len(candidates) > 1:
            second = candidates[1]
            parts.append(f"then the {second['line']} in {second['minutes']}")

        return Speech(text=", ".join(parts) + ".", focus="departures")
