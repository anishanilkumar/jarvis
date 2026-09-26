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
import math
from pathlib import Path
from typing import Any

import httpx

from jarvis.config import Config
from jarvis.sources.bvg import _base
from jarvis.sources.transitous import _haversine

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


async def _search(
    http: httpx.AsyncClient, conf: dict[str, Any], query: str, *, stops: bool
) -> list[dict[str, Any]]:
    """BVG's location search, for either addresses or stops.

    BVG only, with no fallback to Transitous: a `stop_id` is a BVG id, and the
    fallback source maps from one rather than issuing its own. An id from
    anywhere else would be a board that never answers.
    """
    response = await http.get(
        f"{_base(conf)}/locations",
        params={
            "query": query,
            "addresses": "false" if stops else "true",
            "poi": "false",
            "stops": "true" if stops else "false",
            "results": 5,
            "fuzzy": "true",
        },
    )
    response.raise_for_status()
    return [hit for hit in response.json() if isinstance(hit, dict)]


async def _address(http: httpx.AsyncClient, conf: dict[str, Any], query: str) -> dict[str, Any]:
    hits = [hit for hit in await _search(http, conf, query, stops=False)
            if hit.get("latitude") is not None and hit.get("longitude") is not None]
    if not hits:
        raise Unresolved(f"no address matches {query!r}")
    hit = hits[0]
    # "10115 Berlin-Mitte, Invalidenstraße 49" -> "Mitte", the name the
    # clock tile has always shown.
    place = (hit.get("address") or "").split(",")[0]
    district = place.split("-", 1)[1] if "-" in place else ""
    return {
        "latitude": hit["latitude"],
        "longitude": hit["longitude"],
        "name": district,
        "found": hit.get("address") or hit.get("name") or query,
    }


async def _stop(http: httpx.AsyncClient, conf: dict[str, Any], query: str) -> dict[str, Any]:
    hits = [hit for hit in await _search(http, conf, query, stops=True)
            if hit.get("id") and hit.get("name")]
    if not hits:
        raise Unresolved(f"no stop matches {query!r}")
    # The name as written if it is there, else the search's own first choice.
    # Not the nearest to home: "U Rosenthaler Platz" also finds U Rosa-
    # Luxemburg-Platz, which from some addresses is closer and is not what was
    # asked for.
    wanted = query.casefold()
    hit = next((h for h in hits if _clean(h["name"]).casefold() == wanted), hits[0])
    location = hit.get("location") or {}
    return {
        "stop_id": str(hit["id"]),
        "stop_name": _clean(hit["name"]),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
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
            found = await (_address if kind == "address" else _stop)(http, conf, query)
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
        if board.get("stop_id"):
            # Pinned, so not looked up — but the name it was pinned under is
            # still the best heading there is.
            board.setdefault("stop_name", query)
            board.setdefault("name", query)
            continue
        found = await lookup("stop", query)
        board["stop_id"] = found["stop_id"]
        board.setdefault("stop_name", found["stop_name"])
        board.setdefault("name", found["stop_name"])
        if "walk_minutes" not in board and found["latitude"] is not None \
                and "latitude" in location:
            metres = _haversine(location["latitude"], location["longitude"],
                                found["latitude"], found["longitude"])
            # Rounded up, as the public board does: erring the other way lists
            # a tram you cannot reach.
            board["walk_minutes"] = max(1, math.ceil(metres / METRES_PER_MINUTE))
        log.info("stop %r is %s (%s), %s min walk", query, found["stop_name"],
                 found["stop_id"], board.get("walk_minutes", "default"))

    if changed:
        _save(path, remembered)
