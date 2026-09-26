"""Turns an address and stop names into the coordinates and ids the wall runs on.

The config can say `[location] address = "…"` instead of a latitude and a
longitude, and a board can say `stop = "U Rosenthaler Platz"` instead of a
`stop_id`. Both are what a person knows about where they live; the numbers are
what the providers need. This runs once at startup, before any provider is
registered, and writes the numbers into the config in place — so nothing
downstream learns that a name was ever involved.

Anything already given is left alone. A board with a `stop_id` is not looked up,
and neither is a location with coordinates, which is also the way out when the
search picks the wrong stop: write the id in.

Every answer is kept in the state directory. The wall must come back after a
power cut even if the router is slower to boot than the Pi, and a lookup that
needs the network to start the process would turn "BVG is down" into "the wall
is blank". With the file there, the network is needed once, ever — and again
only when the address or a stop name changes, since the query is the key.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from jarvis.config import Config
from jarvis.public import geocode
from jarvis.public.limits import VBB
from jarvis.public.nearby import CYCLE_METRES_PER_MINUTE, minutes_for
from jarvis.sources import transitous
from jarvis.sources.bvg import _base, _timeout
from jarvis.sources.transitous import _haversine, city_of, without_city

log = logging.getLogger(__name__)

#: How fast the walk to a looked-up stop is assumed to be, when the board does
#: not say. The public board's figure, for the same reason: straight-line
#: distance is already optimistic, so the pace is not.
METRES_PER_MINUTE = 80.0


class Unresolved(RuntimeError):
    """A name could not be turned into a place, and nothing was remembered.

    Raised rather than skipped. A wall missing a board it was configured with
    looks exactly like a stop with nothing running, which is the lie this whole
    project exists not to tell; a unit that fails to start says it in the log,
    and systemd tries again.
    """


def _clean(name: str) -> str:
    return name.replace(" (Berlin)", "").strip()


async def _bvg_stops(
    http: httpx.AsyncClient, conf: dict[str, Any], query: str
) -> list[dict[str, Any]]:
    """BVG's stop search. Only asked inside Berlin and Brandenburg: elsewhere it
    answers a name it does not have with a similar one it does."""
    response = await http.get(
        f"{_base(conf)}/locations",
        params={
            "query": query,
            "addresses": "false",
            "poi": "false",
            "stops": "true",
            "results": 5,
            "fuzzy": "true",
        },
        timeout=_timeout(conf),
    )
    response.raise_for_status()
    return [hit for hit in response.json() if isinstance(hit, dict) and hit.get("id")]


async def _address(http: httpx.AsyncClient, conf: dict[str, Any], query: str) -> dict[str, Any]:
    """An address, from the same search the public board's picker uses:
    Transitous first, since it covers the whole country, BVG if it is down."""
    _, hits = await geocode.search(http, conf, query, results=5)
    for hit in hits:
        if not geocode.in_germany(hit):
            continue
        shaped = geocode.shape_hit(hit)
        if shaped:
            return {
                "latitude": shaped["lat"],
                "longitude": shaped["lon"],
                # "Mitte", "Fürth" — what the clock tile has always shown.
                "name": shaped["district"],
                "found": f"{shaped['name']}, {shaped['district']} {shaped['postcode']}".strip(),
            }
    raise Unresolved(f"no address in Germany matches {query!r}")


#: How far from home a stop found by name may be. A stop name is not unique
#: across the country — "Rathaus" is in every town — and the nearest one that
#: matches is still the wrong one if it is in the next city.
NEAR_ENOUGH_M = 25_000


def _matches(name: str, query: str, city: str | None) -> bool:
    wanted = query.casefold()
    return _clean(name).casefold() == wanted or without_city(name, city).casefold() == wanted


async def _stop(
    http: httpx.AsyncClient,
    conf: dict[str, Any],
    query: str,
    home: tuple[float, float] | None,
) -> dict[str, Any]:
    """A stop by name: a BVG id where BVG has the stop, a Transitous id where not.

    BVG is asked first inside Berlin and Brandenburg, because only its ids get
    the disruption notices. Anywhere else, or while BVG is down, Transitous —
    whose ids the departures then go to directly. Either way the name as written
    wins over the search's own first choice: "U Rosenthaler Platz" also finds U
    Rosa-Luxemburg-Platz, which from some addresses is closer.
    """
    if home is None or VBB.contains(*home):
        try:
            hits = await _bvg_stops(http, conf, query)
        except httpx.HTTPError as err:
            log.warning("BVG stop search for %r failed (%s); trying Transitous", query, err)
            hits = []
        if hits:
            hit = next((h for h in hits if _matches(h["name"], query, "Berlin")), hits[0])
            location = hit.get("location") or {}
            return {
                "stop_id": str(hit["id"]),
                "stop_name": _clean(hit["name"]),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
            }

    params: dict[str, Any] = {"text": query, "type": "STOP"}
    if home is not None:
        params["place"] = f"{home[0]},{home[1]}"
    response = await http.get(f"{transitous._base(conf)}/geocode", params=params)
    response.raise_for_status()
    hits = [
        hit for hit in response.json()
        if isinstance(hit, dict) and hit.get("id") and hit.get("lat") is not None
        and (home is None or _haversine(*home, hit["lat"], hit["lon"]) <= NEAR_ENOUGH_M)
    ]
    if not hits:
        raise Unresolved(f"no stop near home matches {query!r}")
    hit = next(
        (h for h in hits if _matches(h["name"], query, city_of(h.get("areas") or []))),
        hits[0],
    )
    return {
        "transitous_stop_id": str(hit["id"]),
        "stop_name": without_city(_clean(hit["name"]), city_of(hit.get("areas") or [])),
        "latitude": hit["lat"],
        "longitude": hit["lon"],
    }


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _save(path: Path, remembered: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(remembered, indent=2, ensure_ascii=False))
        tmp.replace(path)
    except OSError as err:
        # Not fatal: this start has what it needs, and the next one looks it up
        # again.
        log.warning("could not remember resolved places in %s: %s", path, err)


async def apply(cfg: Config, http: httpx.AsyncClient) -> None:
    """Fill in coordinates and stop ids wherever the config gave a name instead."""
    path = cfg.state_dir / "resolved.json"
    remembered = _load(path)
    changed = False
    conf = cfg.section("departures")

    async def lookup(kind: str, query: str) -> dict[str, Any]:
        nonlocal changed
        key = f"{kind}:{query}"
        try:
            if kind == "address":
                found = await _address(http, conf, query)
            else:
                home = (location["latitude"], location["longitude"]) \
                    if "latitude" in location and "longitude" in location else None
                found = await _stop(http, conf, query, home)
        except (httpx.HTTPError, Unresolved) as err:
            if key in remembered:
                log.warning("looking up %s %r failed (%s); using the remembered answer",
                            kind, query, err)
                return remembered[key]
            raise Unresolved(f"could not look up {kind} {query!r}: {err}") from err
        if remembered.get(key) != found:
            remembered[key] = found
            changed = True
        return found

    location = cfg.section("location")
    address = location.get("address")
    if address and ("latitude" not in location or "longitude" not in location):
        found = await lookup("address", address)
        location["latitude"] = found["latitude"]
        location["longitude"] = found["longitude"]
        location.setdefault("name", found["name"])
        log.info("address %r is %s (%.5f, %.5f)", address, found["found"],
                 found["latitude"], found["longitude"])

    for board in conf.get("boards") or []:
        query = board.get("stop")
        if not query:
            continue
        if board.get("stop_id") or board.get("transitous_stop_id"):
            # Pinned, so not looked up — but the name it was pinned under is
            # still the best heading there is.
            board.setdefault("stop_name", query)
            board.setdefault("name", query)
            continue
        found = await lookup("stop", query)
        # One or the other: a board with only a Transitous id is skipped by
        # BVG without counting against it (see sources.NotHere).
        for key in ("stop_id", "transitous_stop_id"):
            if found.get(key):
                board[key] = found[key]
        board.setdefault("stop_name", found["stop_name"])
        board.setdefault("name", found["stop_name"])
        if found["latitude"] is not None and "latitude" in location:
            metres = _haversine(location["latitude"], location["longitude"],
                                found["latitude"], found["longitude"])
            # Rounded up, as the public board does: erring the other way lists
            # a tram you cannot reach. A measured walk_minutes in the config
            # wins; the bike is shown beside it either way.
            board.setdefault("walk_minutes", minutes_for(metres, METRES_PER_MINUTE))
            board.setdefault("cycle_minutes", minutes_for(metres, CYCLE_METRES_PER_MINUTE))
        log.info("stop %r is %s (%s), %s min walk", query, found["stop_name"],
                 found.get("stop_id") or found.get("transitous_stop_id"),
                 board.get("walk_minutes", "default"))

    if changed:
        _save(path, remembered)
