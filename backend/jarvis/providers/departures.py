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

from jarvis import sources
from jarvis.registry import Provider, Speech

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


def _natural_line(name: str) -> tuple[tuple[int, Any], ...]:
    """Sort key that reads a line name the way a person does.

    Plain string order puts M13 before M4 and S25 before S2, because it compares
    "1" against "4" and never sees the numbers. Splitting into digit and
    non-digit runs and comparing the digits numerically gives S1, S2, S25, S26
    and 106, 187, M48, M85 — which is the order these appear in on every sign in
    the city.

    Digits sort ahead of letters, so a numbered bus lands above a metro line
    rather than interleaving with it.
    """
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.findall(r"\d+|\D+", name)
    )


#: What a mode is worth a row for, and the reason the U-Bahn is on the wall at
#: all.
#:
#: Sorting a mixed stop purely by line name is quietly disastrous. U Kleistpark
#: serves the U7 and five bus routes, and "106, 187, 204, M48" sorts ahead of
#: "U7" on every reading of the name — so the four rows the tile has room for
#: went to buses and the station's entire reason for existing never appeared.
#: The stop is called U Kleistpark.
#:
#: U-Bahn and S-Bahn share a rank on purpose. Neither outranks the other as a
#: mode: which one you want is a fact about where you are standing, so the
#: nearer stop wins and two of them at one stop fall back to line order — S1,
#: S2, S25, U7, which is how the platform signs read anyway.
#:
#: RE and RB sit BELOW them. A regional train is the rarest thing at a Berlin
#: stop and missing one is expensive, which argues for the top row, but at a
#: local station it is far more often passing through than going anywhere you
#: were headed. Trams then buses: both stop on the street every few hundred
#: metres, and the tram is the one that comes less often and goes further.
_PRODUCT_RANK = {
    "subway": 0,
    "suburban": 0,
    "express": 1,
    "regional": 1,
    "tram": 2,
    "ferry": 3,
    "bus": 4,
}

#: Anything the map has never heard of. Last, rather than first: an unknown
#: product is not evidence of importance.
_UNRANKED = max(_PRODUCT_RANK.values()) + 1


def product_rank(product: str | None) -> int:
    """Where a mode sorts against the other modes at the same stop."""
    return _PRODUCT_RANK.get(product or "", _UNRANKED)


def route_order(route: dict[str, Any]) -> tuple[Any, ...]:
    """The order route strips sit in: mode, then line, then destination.

    Public because the ordering has to be the same in two places — inside a
    board here, and across the pooled board the public dashboard builds out of
    several stops' routes. Two copies of this would drift.
    """
    return (
        product_rank(route.get("product")),
        _natural_line(route.get("line") or ""),
        route.get("destination") or "",
    )


def _group_label(
    line: str, direction: str, groups: dict[str, list[str]]
) -> str | None:
    """The configured name for this heading, if the board declares one.

    This is what folds short-turns back into the service they belong to. The U7
    reports five northbound termini — Rathaus Spandau and four points short of
    it — and five strips for one direction of one line is exactly the noise the
    route grouping exists to remove. Substring matching, and first match wins,
    so order the table with the specific patterns above the general ones.

    A pattern may be scoped to one line as "S1:Potsdamer Platz". Termini are not
    unique to a line — the S1 turns short at the platform the S26 terminates on
    — so an unscoped "Potsdamer Platz" folded into the S1's northbound heading
    would quietly relabel the S26's own service as an S1 destination. Scope a
    pattern whenever the place, not the line, is what you are naming.
    """
    haystack = _norm(direction)
    for label, patterns in groups.items():
        for pattern in patterns:
            want_line, _, text = pattern.rpartition(":")
            if want_line and _norm(want_line) != _norm(line):
                continue
            if _norm(text) in haystack:
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


def _setting(board: dict[str, Any], conf: dict[str, Any], key: str, default: Any) -> Any:
    """This board's own value, then the [departures] default, then the built-in.

    The two-level lookup is what lets a caller with no config at all pass
    ``conf={}`` and still get sensible numbers out: it hands over a board dict
    carrying the few values it cares about and lets the built-ins supply the
    rest. That is the whole reason the shaping below is reusable — the public
    dashboard has no [departures] table to draw defaults from, because it has
    no configured stops in the first place.
    """
    return board.get(key, conf.get(key, default))


def shape_board(
    raw: dict[str, Any],
    board: dict[str, Any],
    conf: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One stop's raw /departures JSON, shaped into the board the panel renders.

    Pure: no Config, no Provider, no HTTP, and no clock beyond `now`. Everything
    it reads comes out of `board`, with `conf` only as a fallback layer, so the
    wall passes its whole [departures] table and a stateless caller passes
    nothing at all.

    `now` must be timezone-aware. BVG timestamps carry an offset, and comparing
    them against a naive datetime raises rather than quietly going wrong, which
    is the good outcome but still an outcome to avoid.
    """
    conf = conf or {}
    now = now or datetime.now(timezone.utc)

    keep = _setting(board, conf, "results", 12)
    # The one threshold: leave now and you are on the platform in this many
    # minutes. Anything sooner is gone. There is no grace window — a margin
    # that quietly redefines "too late" makes the board disagree with the
    # walk it prints in its own header.
    walk = _setting(board, conf, "walk_minutes", 4)

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
    warnings: list[str] = []
    for item in raw.get("departures", []):
        for remark in item.get("remarks") or []:
            if remark.get("type") == "warning":
                text = _notice(remark.get("text") or remark.get("summary") or "")
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
    depth = _setting(board, conf, "route_length", 4)

    routes: dict[tuple[str, str], dict[str, Any]] = {}
    for departure in departures:
        destination = (
            _group_label(departure["line"], departure["direction"], groups)
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

    # "line" sorts by mode, then line, then destination, and is the ordering to
    # reach for when a stop serves several lines going to genuinely different
    # places.
    # It is also the only one that survives a terminus the config has never
    # seen: the declared order below can't place a short-turn it doesn't
    # know about, and two lines can share a terminus name — the S1 turns
    # short at the same platform the S26 terminates on — which is enough to
    # scatter a declared order across lines.
    if _setting(board, conf, "order", "listed") == "line":
        key = route_order
    else:
        key = lambda route: (route["order"], route["line"])
    ordered = sorted(routes.values(), key=key)

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
        "rows": _setting(board, conf, "rows", 3),
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
        "order": _setting(board, conf, "order", "listed"),
        "routes": ordered,
        # Kept flat as well. The panel reads only `routes` now, but the
        # spoken answer picks the single soonest departure across every
        # board, and grouping is the wrong shape for that question.
        "departures": departures[:keep],
        "warnings": warnings,
        "updated_at": raw.get("realtimeDataUpdatedAt"),
    }


#: A real HTML tag, which requires a letter after the "<". Deliberately not
#: `<[^>]*>`: BVG writes "platform U8 <> intermediate level" and means an
#: arrow, and a looser pattern eats it.
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")

#: The "read more" anchor BVG appends to longer notices, taken out whole rather
#: than unwrapped. Every other tag keeps its text — a <b> around a station name
#: still says the station — but a link label with no link left to follow is a
#: stray "[MEHR/MORE]" at the end of a sentence that was already complete.
_LINK = re.compile(r"<a\b[^>]*>.*?</a>", re.IGNORECASE | re.DOTALL)


def _notice(text: str) -> str:
    """One disruption remark, as a sentence a person can read.

    BVG sends these HTML-escaped, and unescaping is not optional: without it
    the panel shows a literal "&#60;&#62;" mid sentence where the notice meant
    an arrow. But the same escaping hides real markup — the longer notices
    carry an <a> to the disruption page — and once unescaped that markup lands
    in a text node and is displayed verbatim, tag and href and all.

    So: unescape, then take the tags back out. The alternative — rendering the
    notice as markup so the link stays a link — means handing upstream HTML
    straight to the DOM of a public page, which is a far larger promise than
    "the disruption is readable" needs anyone to make.
    """
    plain = _TAG.sub("", _LINK.sub("", html.unescape(text)))
    # Removing an element mid-sentence leaves the spaces that surrounded it.
    return re.sub(r"\s+", " ", plain).strip()


def merge_warnings(boards: list[dict[str, Any]]) -> list[str]:
    """Warnings across every board, de-duplicated.

    One disruption frequently lands on every stop it touches, and the tile has
    room to say "2 notices", not to say the same notice twice.
    """
    warnings: list[str] = []
    for board in boards:
        for warning in board["warnings"]:
            if warning not in warnings:
                warnings.append(warning)
    return warnings


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

        shaped = [board for _, board in results]
        return {
            "boards": shaped,
            "warnings": merge_warnings(shaped),
            # Which upstreams actually answered. The panel needs it because the
            # fallback carries no disruption remarks, so an empty `warnings` on
            # the primary means "nothing wrong" and on the fallback means
            # "nobody told us" — two very different claims to make from one
            # empty list.
            "sources": sorted({name for name, _ in results}),
        }

    async def _fetch_board(
        self, conf: dict[str, Any], board: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        name, raw = await sources.attempt(
            "departures", http=self.http, board=board, conf=conf
        )
        return name, shape_board(raw, board, conf)


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
