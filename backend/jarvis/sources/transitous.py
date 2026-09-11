"""Transitous — the fallback source, translated into BVG's wire format.

A community MOTIS instance aggregating GTFS and GTFS-RT feeds, free and
keyless, run by different people on different infrastructure from
`transport.rest` and reading a different data pipeline. That independence is
the entire reason it is here: the vbb and db instances of the primary are the
same box under different names and went down with it, so they are redundancy in
name only.

Everything in this module is translation. Transitous speaks a MOTIS API with its
own field names, its own mode vocabulary and its own stop ids; the rest of the
codebase speaks HAFAS because that is what it grew up on. Rather than teach the
shaping two dialects, the whole difference is absorbed here, once.

Three things it cannot do, all of them known and none of them fatal:

  * **No disruption remarks.** There is no alerts field in the response — every
    key was checked. `warnings` therefore comes back empty and the panel says
    which source it is on, because a board silently missing its notices is
    worse than one that admits it has none.
  * **No product opt-out on the wire.** BVG filters server-side via its
    opt-out flags; here the board's `products` filter is applied after the
    fact, which costs a little bandwidth and nothing else.
  * **Stop ids are not derivable.** `de-VBB_de:11000:<bvg id>` resolves most
    Berlin stops and silently returns nothing for others — Mansteinstr. is
    a `de-VBB_000…` id, and one of its platforms wants a `::1` suffix.
    Guessing produces an empty board, which reads as "no trams tonight". So ids
    are never computed, only ever resolved: `nearby()` returns them directly,
    and a configured board carries `transitous_stop_id` or is looked up by
    position.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

NAME = "transitous"

API_BASE = "https://api.transitous.org/api/v1"

#: MOTIS mode -> the HAFAS product name the panel colours its rows by. METRO is
#: the S-Bahn and SUBWAY the U-Bahn, which is the one pairing worth reading
#: twice; getting it backwards swaps the green and blue rows on the wall.
_PRODUCTS = {
    "METRO": "suburban",
    "SUBURBAN": "suburban",
    "SUBWAY": "subway",
    "TRAM": "tram",
    "BUS": "bus",
    "COACH": "bus",
    "FERRY": "ferry",
    "REGIONAL_RAIL": "regional",
    "REGIONAL_FAST_RAIL": "regional",
    "NIGHT_RAIL": "regional",
    "RAIL": "regional",
    "HIGHSPEED_RAIL": "express",
    "LONG_DISTANCE": "express",
}


def _base(conf: dict[str, Any]) -> str:
    return str(conf.get("transitous_api_base") or API_BASE).rstrip("/")


def _moment(value: str | None) -> str | None:
    """A MOTIS timestamp as an offset-bearing ISO string.

    MOTIS answers in UTC with a "Z", which `datetime.fromisoformat` only learned
    to read in 3.11. The Pi is not guaranteed to be newer than the laptop this
    was written on, and a provider that raises on every timestamp is a worse
    failure than the outage it exists to cover.
    """
    if not value:
        return None
    return value[:-1] + "+00:00" if value.endswith("Z") else value


def _parse(value: str | None) -> datetime | None:
    moment = _moment(value)
    if not moment:
        return None
    try:
        return datetime.fromisoformat(moment)
    except ValueError:
        return None


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Metres between two points.

    Computed here because MOTIS reports no distance, and the walk time on every
    board header is derived from it. Straight-line, matching what BVG reports,
    so the two sources produce the same walk for the same stop rather than the
    board's header changing when the source does.
    """
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


async def nearby(
    http: httpx.AsyncClient,
    *,
    lat: float,
    lon: float,
    count: int,
    radius: int,
    conf: dict[str, Any],
) -> list[dict[str, Any]]:
    """Stops near a point, shaped as BVG's /locations/nearby answers.

    This is also what makes the fallback usable at all on the public side:
    the ids come back resolved, so there is no mapping to get wrong.
    """
    response = await http.get(
        f"{_base(conf)}/reverse-geocode",
        params={"place": f"{lat},{lon}", "type": "STOP"},
    )
    response.raise_for_status()

    payload = response.json()
    rows = payload if isinstance(payload, list) else payload.get("places") or []

    stops: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("id") or not row.get("name"):
            continue
        if row.get("lat") is None or row.get("lon") is None:
            continue
        distance = _haversine(lat, lon, row["lat"], row["lon"])
        if distance > radius:
            continue
        stops.append(
            {
                "id": row["id"],
                "name": row["name"],
                "distance": round(distance),
                "location": {"latitude": row["lat"], "longitude": row["lon"]},
            }
        )

    # MOTIS orders by its own relevance score, not by distance, and the boards
    # are laid out nearest-first.
    stops.sort(key=lambda stop: stop["distance"])
    return stops[: count * 3]


def _departure(row: dict[str, Any]) -> dict[str, Any] | None:
    """One MOTIS stopTime as the HAFAS departure the shaping expects."""
    place = row.get("place") or {}
    when = _moment(place.get("departure"))
    planned = _moment(place.get("scheduledDeparture"))
    if not (when or planned):
        return None

    actual_at, planned_at = _parse(place.get("departure")), _parse(
        place.get("scheduledDeparture")
    )
    # HAFAS reports delay in SECONDS and the shaping divides by 60. MOTIS
    # reports two timestamps and leaves the arithmetic to the reader.
    delay = (
        round((actual_at - planned_at).total_seconds())
        if actual_at and planned_at
        else 0
    )

    return {
        "tripId": row.get("tripId"),
        "line": {
            "name": row.get("routeShortName") or "?",
            "product": _PRODUCTS.get(str(row.get("mode") or "").upper()),
        },
        "direction": row.get("headsign") or "",
        "when": when,
        "plannedWhen": planned,
        "delay": delay,
        # A cancelled trip cancels this stop of it; the panel draws either the
        # same way.
        "cancelled": bool(row.get("cancelled") or row.get("tripCancelled")),
        # MOTIS gives a human description ("S-Bahnsteig Gleis 3") where HAFAS
        # gives a bare platform number. Passed through as-is: the panel prints
        # whatever it is told, and the description is the more useful of the two
        # on foot.
        "platform": place.get("description"),
        # Nothing to put here. See the module docstring — this is the one thing
        # the fallback genuinely cannot supply.
        "remarks": [],
    }


#: BVG stop id -> Transitous stop id, resolved once per process. Small, bounded
#: by the number of stops a household configures, and worth keeping because the
#: lookup is a whole extra round trip on a path taken only when the primary is
#: already slow or dead.
_resolved: dict[str, str] = {}


def _match_key(name: str) -> str:
    """A stop name reduced to what two sources can be expected to agree on."""
    return " ".join(name.replace("(Berlin)", " ").split()).casefold()


async def resolve_stop(
    http: httpx.AsyncClient, board: dict[str, Any], conf: dict[str, Any]
) -> str:
    """This board's stop, as an id Transitous will accept.

    Never computed. `de-VBB_de:11000:<bvg id>` looks like it should work and
    does for most Berlin stops, which is exactly what makes it dangerous — the
    ones it misses come back as an empty departure list rather than an error,
    and an empty list is drawn as a stop where nothing runs. Mansteinstr. is
    a `de-VBB_000…` id; one of its platforms wants a `::1` suffix.

    So the id is looked up by name and accepted only on an exact match once
    both sides are normalised. A near miss raises: no board at all is a state
    the panel says out loud, and the wrong stop's departures is not.

    A board can skip all of this by declaring `transitous_stop_id` itself.
    """
    declared = board.get("transitous_stop_id")
    if declared:
        return str(declared)

    key = str(board.get("stop_id") or "")
    if key in _resolved:
        return _resolved[key]

    wanted = board.get("stop_name") or board.get("name") or ""
    if not wanted:
        raise LookupError("board has no stop name to resolve")

    response = await http.get(
        f"{_base(conf)}/geocode", params={"text": wanted, "place": "52.52,13.405"}
    )
    response.raise_for_status()

    target = _match_key(wanted)
    for hit in response.json():
        if not isinstance(hit, dict) or hit.get("type") != "STOP" or not hit.get("id"):
            continue
        if _match_key(str(hit.get("name") or "")) == target:
            if key:
                _resolved[key] = hit["id"]
            return str(hit["id"])

    raise LookupError(f"no transitous stop matches {wanted!r}")


async def departures(
    http: httpx.AsyncClient, *, board: dict[str, Any], conf: dict[str, Any]
) -> dict[str, Any]:
    """One stop's departures, shaped as BVG's /stops/:id/departures answers."""
    stop_id = await resolve_stop(http, board, conf)
    keep = board.get("results") or conf.get("results") or 12
    minutes = board.get("duration_minutes") or conf.get("duration_minutes") or 60

    response = await http.get(
        f"{_base(conf)}/stoptimes",
        # Over-asked for the same reason BVG is: the product filter and the
        # time window below both throw rows away, and the panel then picks
        # from what survives.
        params={"stopId": stop_id, "n": max(int(keep) * 6, 60)},
    )
    response.raise_for_status()

    wanted = {product.lower() for product in board.get("products") or []}
    cutoff = datetime.now(timezone.utc) + timedelta(minutes=int(minutes))

    rows: list[dict[str, Any]] = []
    for row in response.json().get("stopTimes") or []:
        if not isinstance(row, dict):
            continue
        departure = _departure(row)
        if departure is None:
            continue
        # Applied here rather than on the wire, which MOTIS does not offer.
        if wanted and (departure["line"]["product"] or "") not in wanted:
            continue
        at = _parse(departure["when"] or departure["plannedWhen"])
        if at is not None and at > cutoff:
            continue
        rows.append(departure)

    rows.sort(key=lambda d: d["when"] or d["plannedWhen"] or "")
    return {"departures": rows}


def _berlin_address(hit: dict[str, Any]) -> str | None:
    """A MOTIS address as HAFAS spells one, or None to leave it as a POI.

    The picker's parser reads "10245 Berlin-Friedrichshain, Boxhagener Str. 1"
    and splits the district off the street; MOTIS delivers the same facts as
    separate fields plus a list of administrative areas. Level 4 is the city,
    10 the Ortsteil that BVG names, 9 the Bezirk it falls back to.
    """
    areas = hit.get("areas") or []

    def named(level: int) -> str | None:
        for area in areas:
            if area.get("adminLevel") == level:
                return area.get("name")
        return None

    if named(4) != "Berlin":
        return None

    postcode, street = hit.get("zip"), hit.get("street") or hit.get("name") or ""
    if not postcode or not street:
        return None

    number = hit.get("houseNumber")
    line = f"{street} {number}".strip() if number else street
    district = named(10) or named(9)
    return f"{postcode} Berlin-{district}, {line}" if district else f"{postcode} Berlin, {line}"


async def locations(
    http: httpx.AsyncClient,
    *,
    query: str,
    results: int,
    conf: dict[str, Any],
) -> list[dict[str, Any]]:
    """Address search, shaped as BVG's /locations answers.

    MOTIS geocodes the whole planet from one text box, so "Berlin" alone finds
    a bar in Cotonou. Nothing is filtered out for that here — the bounding box
    in the public app is the rule and this is not the place to duplicate it —
    beyond dropping stops, which the picker excludes on purpose.
    """
    response = await http.get(
        f"{_base(conf)}/geocode",
        params={"text": query, "place": "52.52,13.405"},
    )
    response.raise_for_status()

    hits: list[dict[str, Any]] = []
    for hit in response.json():
        if not isinstance(hit, dict) or hit.get("type") == "STOP":
            continue
        if hit.get("lat") is None or hit.get("lon") is None:
            continue
        hits.append(
            {
                "type": "location",
                "name": hit.get("name"),
                "address": _berlin_address(hit),
                "latitude": hit["lat"],
                "longitude": hit["lon"],
            }
        )
        if len(hits) >= results:
            break
    return hits
