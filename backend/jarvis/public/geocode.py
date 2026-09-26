"""Turning a typed German address into coordinates.

Transitous first, BVG second. Transitous geocodes all of Germany from
OpenStreetMap, with house numbers where OSM has them; BVG's search knows only
Berlin and Brandenburg, and answers a street it does not have with a
similarly named one it does — a Fürth street with a Potsdam one — which is
worse than no answer. BVG stays as the fallback: for a Berlin address it is as
good, and the picker going down with one upstream is what turns an outage into
"this site does not work".

What the search is not is German-only. Transitous geocodes the planet, so
results are filtered here on the country and, in the app, on the bounding box.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from jarvis import sources

#: How BVG writes an address: "10245 Berlin-Friedrichshain, Boxhagener Str. 1",
#: "14467 Potsdam, Friedrich-Ebert-Str. 4". Only BVG's answers are taken apart;
#: Transitous sends the parts as fields.
_ADDRESS = re.compile(r"^(\d{5})\s+([^,]+),\s*(.+)$")


def shape_hit(hit: dict[str, Any]) -> dict[str, Any] | None:
    """One search result, as the picker wants to show it.

    Splitting the district off the street is what lets the list tell apart the
    four streets that share a name without printing a postcode at the front of
    every row, where it is the least useful thing on the line. Outside Berlin
    the "district" is the town.
    """
    lat, lon = hit.get("latitude"), hit.get("longitude")
    if lat is None or lon is None:
        return None

    if "street" in hit:
        name = hit.get("street") or hit.get("name") or ""
        if not name:
            return None
        return {
            "name": name,
            "district": hit.get("district") or "",
            "postcode": hit.get("postcode") or "",
            "lat": lat,
            "lon": lon,
            "kind": hit.get("kind") or "address",
        }

    address = hit.get("address") or ""
    match = _ADDRESS.match(address)
    if match:
        postcode, place, street = match.groups()
        # Only Berlin writes its districts after a hyphen. Elsewhere a hyphen
        # is part of the town's name.
        district = place[len("Berlin-"):] if place.startswith("Berlin-") else place
        return {"name": street, "district": district, "postcode": postcode, "lat": lat, "lon": lon,
                "kind": "address"}

    # A point of interest, or an address spelled some other way. The bounding
    # box decides whether it is in scope, not this.
    name = hit.get("name") or address
    if not name:
        return None
    return {"name": name, "district": "", "postcode": "", "lat": lat, "lon": lon, "kind": "place"}


def ranked(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Addresses first, then named places, each merged with its near-twins.

    The geocoder mixes them in its own relevance order, so "Marktplatz,
    Heiligenstadt" came back with a hiking route and a snack bar between the
    square and the town. Somebody typing where they live means an address; a
    place stays listed after them, since a landmark is sometimes the easiest
    name for a spot. Twins — one building's entrances, the same route mapped
    twice — are merged on the name as a reader sees it: case and spacing aside.
    """
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for hit in sorted(hits, key=lambda hit: hit.get("kind") != "address"):
        key = (
            " ".join(hit["name"].split()).casefold(),
            hit["district"].casefold(),
            hit["postcode"],
        )
        unique.setdefault(key, hit)
    return [{k: v for k, v in hit.items() if k != "kind"} for hit in unique.values()]


def in_germany(hit: dict[str, Any]) -> bool:
    """Whether the source itself puts this in Germany.

    Belt and braces with the bounding box, which is a rectangle round a
    country with a ragged border: it takes in Basel, Strasbourg and Salzburg.
    BVG's answers carry no country and are all Berlin or Brandenburg.
    """
    country = hit.get("country")
    return country is None or country == "DE"


async def search(
    http: httpx.AsyncClient, conf: dict[str, Any], query: str, *, results: int = 8
) -> tuple[str, list[dict[str, Any]]]:
    """Address candidates, from whichever source answers.

    Worth having a fallback for in its own right. Through the September outage
    the picker went down with the board, so a first-time visitor could not even
    set the page up — the failure was not "no departures today", it was "this
    site does not work".
    """
    return await sources.attempt(
        "locations", http=http, query=query, results=results, conf=conf,
        prefer="transitous",
    )
