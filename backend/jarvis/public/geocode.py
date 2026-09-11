"""Turning a typed Berlin address into coordinates.

Uses the transport API's own location search rather than a general geocoder,
for three reasons: it is the same upstream the departures already come from, so
the page has one dependency instead of two; it is native to the region, so it
knows Berlin street names and the way people abbreviate them; and it has no
usage policy to breach on a public page.

What it is *not* is Berlin-only. VBB covers Brandenburg too, so a search for a
Berlin-sounding street returns Oranienburg and Borkwalde alongside it. Hence
the filtering here, which is the honest half of "within Berlin for now".
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from jarvis import sources

#: "10245 Berlin-Friedrichshain, Boxhagener Str. 1", and the plainer
#: "10117 Berlin, Unter den Linden 1". Both shapes appear; anything else is
#: left alone.
_ADDRESS = re.compile(r"^(\d{5})\s+Berlin(?:-([^,]+))?,\s*(.+)$")


def shape_hit(hit: dict[str, Any]) -> dict[str, Any] | None:
    """One search result, as the picker wants to show it.

    Splitting the district off the street is what lets the list distinguish the
    four Berlin streets that share a name without printing a postcode at the
    front of every row, where it is the least useful thing on the line.
    """
    lat, lon = hit.get("latitude"), hit.get("longitude")
    if lat is None or lon is None:
        return None

    address = hit.get("address") or ""
    match = _ADDRESS.match(address)
    if match:
        postcode, district, street = match.groups()
        return {
            "name": street,
            "district": district or "Berlin",
            "postcode": postcode,
            "lat": lat,
            "lon": lon,
        }

    # A point of interest, or an address the API spells some other way. Keep it
    # if it is in Berlin at all — the bounding box decides that, not this.
    name = hit.get("name") or address
    if not name:
        return None
    return {"name": name, "district": "", "postcode": "", "lat": lat, "lon": lon}


def looks_berlin(hit: dict[str, Any]) -> bool:
    """Whether the API itself calls this a Berlin address.

    Belt and braces with the bounding box: the box catches coordinates, this
    catches the handful of Brandenburg addresses that sit inside a rectangle
    drawn around a city with a ragged border.
    """
    address = hit.get("address") or ""
    if not address:
        return True  # A POI with no address; leave it to the box.
    return bool(_ADDRESS.match(address))


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
        "locations", http=http, query=query, results=results, conf=conf
    )
