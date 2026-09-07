"""The stops around an address, as departure boards.

The wall's boards are hand-tuned: one direction, a named terminus for every
short-turn, and a walk somebody measured on foot. None of that exists for a
stop found by looking around an address typed a second ago, so this builds the
loosest possible board and leans on the shaping to stay readable — which it
does, because `order = "line"` was written for exactly this case.
"""

from __future__ import annotations

import asyncio
import math
import re
from typing import Any

import httpx

from jarvis.providers.departures import board_params, merge_warnings, shape_board

#: The API suffixes every stop in the city with " (Berlin)", which on a
#: Berlin-only page is the one word on the line carrying no information. The
#: rest of the name is left exactly as reported: unlike a destination, a stop
#: name earns its prefixes — "S+U Yorckstr." tells you which platforms are
#: there, and shortening it would cost the reader that.
#: Not anchored to the end: the API writes "U Alexanderplatz (Berlin) [Tram]",
#: so a $-anchored version left the city name sitting in the middle of the
#: heading with the mode after it.
_CITY = re.compile(r"\s*\(Berlin\)\s*")

#: The entrance a stop id belongs to, as HAFAS spells it: "S+U Alexanderplatz
#: Bhf/Dircksenstr." is one set of platforms at the station "S+U Alexanderplatz
#: Bhf", and the station itself is listed separately a few metres further on.
#: Both report the same lines going the same places, so a board for each spends
#: a third of the tile saying everything twice.
_ENTRANCE = re.compile(r"/[^/]*$")


def clean_stop_name(name: str) -> str:
    return " ".join(_CITY.sub(" ", name).split())


def _same_place(name: str) -> str:
    """The key two entrances of one station agree on.

    Only the trailing "/<entrance>" is dropped, and deliberately nothing else.
    Stripping the bracketed qualifiers too would fold "U Alexanderplatz [Tram]"
    into "[Bus]" — plausible at an interchange, and wrong the moment it reaches
    "S+U Yorckstr." and "S+U Yorckstr. (Großgörschenstr.)", which share a name,
    sit four hundred metres apart, and are two different walks.
    """
    return _ENTRANCE.sub("", name).casefold().strip()


async def stops_near(
    http: httpx.AsyncClient,
    api_base: str,
    lat: float,
    lon: float,
    *,
    count: int,
    radius: int,
) -> list[dict[str, Any]]:
    """Stops within `radius` metres, nearest first.

    Note the endpoint is /locations/nearby, not /stops/nearby — the latter
    answers `{"message": "id must be an IBNR"}`, because /stops/:id is a
    different route and `nearby` reads as an id.
    """
    response = await http.get(
        f"{api_base.rstrip('/')}/locations/nearby",
        params={
            "latitude": lat,
            "longitude": lon,
            # Over-ask slightly: the response includes entries without ids and,
            # at a big interchange, several rows for one place.
            "results": count * 3,
            "distance": radius,
        },
    )
    response.raise_for_status()

    seen: set[str] = set()
    stops: list[dict[str, Any]] = []
    for stop in response.json():
        if not isinstance(stop, dict) or not stop.get("id") or not stop.get("name"):
            continue
        # One place, one board. A big interchange reports each entrance and
        # each mode as its own stop — Alexanderplatz answers with nine inside
        # 250m — and without this the first two boards were the same station
        # under two names, listing the same four routes at the same times.
        key = _same_place(clean_stop_name(stop["name"]))
        if key in seen:
            continue
        seen.add(key)
        stops.append(stop)
        if len(stops) >= count:
            break
    return stops


def board_for(stop: dict[str, Any], *, metres_per_minute: float) -> dict[str, Any]:
    """A [[departures.boards]] table for a stop nobody configured.

    Every filter is empty, which the shaping already handles: no products means
    every product the stop serves, no directions means both ways, and no groups
    table means each terminus keeps the API's own name, shortened.

    `order = "line"` is the only ordering that survives this. "listed" orders by
    a groups table that does not exist, and "soonest" would let one direction of
    a line push the other off the board entirely.
    """
    name = clean_stop_name(stop.get("name") or "")
    distance = stop.get("distance") or 0
    return {
        "stop_id": stop["id"],
        # Equal on purpose: the panel prints `stop` after `name` only when they
        # differ, so this gives the board one clean header line instead of the
        # same words twice with a separator between them.
        "name": name,
        "stop_name": name,
        # Rounded up, and from a straight-line distance that is already
        # optimistic. Erring the other way would list a tram you cannot reach.
        "walk_minutes": max(1, math.ceil(distance / metres_per_minute)),
        "order": "line",
    }


async def departure_boards(
    http: httpx.AsyncClient,
    api_base: str,
    stops: list[dict[str, Any]],
    conf: dict[str, Any],
    *,
    metres_per_minute: float,
) -> dict[str, Any]:
    """The same document `Departures.fetch` produces, for unconfigured stops."""
    boards = [board_for(stop, metres_per_minute=metres_per_minute) for stop in stops]

    async def one(board: dict[str, Any]) -> dict[str, Any]:
        response = await http.get(
            f"{api_base.rstrip('/')}/stops/{board['stop_id']}/departures",
            params=board_params(board, conf),
        )
        response.raise_for_status()
        return shape_board(response.json(), board, conf)

    shaped = list(await asyncio.gather(*(one(board) for board in boards)))
    return {"boards": shaped, "warnings": merge_warnings(shaped)}
