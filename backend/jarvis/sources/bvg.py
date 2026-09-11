"""BVG via `v6.bvg.transport.rest` — the primary source.

This is the code that used to sit inline in `providers/departures.py`,
`public/nearby.py` and `public/geocode.py`, moved here unchanged so that the
second source has something to be symmetrical with. The wire format these three
calls return is the interface every source implements; see `sources/__init__`
for why that is BVG's format rather than one of our own.

Primary because of `remarks=true`. HAFAS carries the disruption text — "Tram M2:
Replacement service due to construction works…" — and no GTFS-RT feed we have
access to does. Everything else Transitous matches or betters.
"""

from __future__ import annotations

from typing import Any

import httpx

NAME = "bvg"

DEFAULT_API_BASE = "https://v6.bvg.transport.rest"

#: Every product the API knows. Needed in full because of the filtering gotcha
#: in board_params — you cannot select products by naming only the ones you
#: want.
ALL_PRODUCTS = (
    "suburban",
    "subway",
    "tram",
    "bus",
    "ferry",
    "express",
    "regional",
)


def _setting(board: dict[str, Any], conf: dict[str, Any], key: str, default: Any) -> Any:
    """A board's own value, else the [departures] default, else the fallback."""
    value = board.get(key)
    if value is None:
        value = conf.get(key)
    return default if value is None else value


def _base(conf: dict[str, Any]) -> str:
    return str(conf.get("api_base") or DEFAULT_API_BASE).rstrip("/")


def board_params(board: dict[str, Any], conf: dict[str, Any]) -> dict[str, Any]:
    """Query parameters for one board's /departures call.

    Over-fetches on purpose: the panel decides which routes and which times to
    show, and re-decides every tick, so the board has to arrive with more than
    fits on it.
    """
    keep = _setting(board, conf, "results", 12)
    params: dict[str, Any] = {
        "duration": _setting(board, conf, "duration_minutes", 60),
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
    return params


async def departures(
    http: httpx.AsyncClient, *, board: dict[str, Any], conf: dict[str, Any]
) -> dict[str, Any]:
    """One stop's raw departures document, exactly as the API sends it."""
    response = await http.get(
        f"{_base(conf)}/stops/{board['stop_id']}/departures",
        params=board_params(board, conf),
    )
    response.raise_for_status()
    return response.json()


async def nearby(
    http: httpx.AsyncClient,
    *,
    lat: float,
    lon: float,
    count: int,
    radius: int,
    conf: dict[str, Any],
) -> list[dict[str, Any]]:
    """Stops within `radius` metres, nearest first.

    Note the endpoint is /locations/nearby, not /stops/nearby — the latter
    answers `{"message": "id must be an IBNR"}`, because /stops/:id is a
    different route and `nearby` reads as an id.

    Over-asks: the response includes entries without ids and, at a big
    interchange, several rows for one place. The caller does the de-duplication
    and the truncation, because that logic is the same whichever source
    answered.

    Deliberately does NOT ask for `linesOfStops`. It looks like exactly what a
    caller choosing between stops wants and it cannot be trusted for it: HAFAS
    splits an interchange's lines across its entrances, and reports "S+U
    Yorckstr. (Großgörschenstr.)" as serving the S1 when the stop in fact runs
    the S1, S2, S25, S26 and the U7. Which lines a stop really has is decided
    downstream, from the departures it answers with.
    """
    response = await http.get(
        f"{_base(conf)}/locations/nearby",
        params={
            "latitude": lat,
            "longitude": lon,
            "results": count * 3,
            "distance": radius,
        },
    )
    response.raise_for_status()
    return [stop for stop in response.json() if isinstance(stop, dict)]


async def locations(
    http: httpx.AsyncClient,
    *,
    query: str,
    results: int,
    conf: dict[str, Any],
) -> list[dict[str, Any]]:
    """Address search, for the picker."""
    response = await http.get(
        f"{_base(conf)}/locations",
        params={
            "query": query,
            "addresses": "true",
            "poi": "true",
            # Stops are excluded on purpose. The visitor is telling us where
            # they live so we can find the stops ourselves; offering them a
            # stop to live at makes the walking time meaningless.
            "stops": "false",
            "results": results,
            "fuzzy": "true",
        },
    )
    response.raise_for_status()
    return [hit for hit in response.json() if isinstance(hit, dict)]
