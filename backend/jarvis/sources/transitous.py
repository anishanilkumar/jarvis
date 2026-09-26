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

import asyncio
import math
import re
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


#: Administrative levels in the areas MOTIS attaches to a place, as OSM numbers
#: them for Germany: 4 is the Land (and the whole city in Berlin and Hamburg), 6
#: a kreisfreie Stadt or a Landkreis, 8 a Gemeinde, 9 and 10 the parts of a
#: city.
_LAND, _KREIS, _GEMEINDE = 4, 6, 8


def _area(areas: list[dict[str, Any]], level: int) -> str | None:
    for area in areas:
        if area.get("adminLevel") == level and area.get("name"):
            return str(area["name"])
    return None


def city_of(areas: list[dict[str, Any]]) -> str | None:
    """The town a place is in, as its own stops and signs would name it.

    The Gemeinde if there is one — Hirschaid, not Landkreis Bamberg — else the
    kreisfreie Stadt (Fürth), else the Land for the city-states, where Berlin
    and Hamburg are all three at once.
    """
    kreis = _area(areas, _KREIS)
    if kreis and kreis.startswith("Landkreis"):
        kreis = None
    return _area(areas, _GEMEINDE) or kreis or _area(areas, _LAND)


def district_of(areas: list[dict[str, Any]]) -> str | None:
    """What the address picker prints beside a street, to tell four apart.

    Inside a city-state that is the Ortsteil, as BVG's own answers have it —
    "Mitte", "Friedrichshain". Anywhere else it is the town: a Fürth street is
    told apart from a Bamberg one by the town, and the town's own parts are
    names nobody from elsewhere would recognise.
    """
    if _area(areas, _GEMEINDE) or _area(areas, _KREIS):
        return city_of(areas)
    return _area(areas, 10) or _area(areas, 9) or _area(areas, _LAND)


def without_city(name: str, city: str | None) -> str:
    """ "Fürth Rathaus" -> "Rathaus", "Köln Niehl Sebastianstr." -> "Niehl
    Sebastianstr.", "Berlin, Brunnenstr." -> "Brunnenstr."

    The German feeds put the town in front of every stop and many destinations,
    which on a page already about that town is the one word carrying nothing —
    the same argument as dropping BVG's " (Berlin)". Only a leading town, and
    only when something is left after it: "Wesseling Wesseling" keeps one.

    A town with a qualifier in its official name is matched on the name alone:
    OSM calls it "Heiligenstadt i. OFr." and its stops "Heiligenstadt
    Raiffeisenstr." or "Heiligenstadt (i.OFr.) Schulen".
    """
    if not city:
        return name
    bases = {city, re.split(r"\s+(?:i\.|a\.|an der|am|im|\()", city)[0].strip()}
    for base in sorted(bases, key=len, reverse=True):
        match = re.match(rf"{re.escape(base)}(?:\s*\([^)]*\))?(?:,\s*|\s+)(?=\S)", name)
        if match:
            return name[match.end():].strip()
    return name


#: "RE19 (4913)" and "ICE 1518": the line and the number of this one train. The
#: number is a fact about one run, and on a row that stands for every run of the
#: line it splits one route into as many rows as there are trains — every ICE
#: through Frankfurt its own line. Long-distance trains have no line number to
#: keep, so they fold to their class and are told apart by destination.
_TRAIN_NUMBER = re.compile(r"^(ICE|IC|EC|ECE|EN|NJ|RJ|RJX|FLX|TGV)\s+\d+$|\s*\(\d+\)$")


def _line_name(name: str) -> str:
    return _TRAIN_NUMBER.sub(lambda match: match.group(1) or "", name).strip()


#: How the feeds mark a bus that only runs if someone has phoned for it: in the
#: line's name, and nowhere else. pickupType and reservation both say NORMAL
#: and NONE for "221 Rufbus", checked across 1,300 departures in Landkreis
#: Forchheim. Rufbus, AST (Anruf-Sammel-Taxi), ALT (Anruf-Linien-Taxi) and
#: the rest, as a suffix or on their own.
_ON_DEMAND = re.compile(
    r"\s*\b(?:Rufbus|Anrufbus|AST|ALT|Anruf-?Sammel-?Taxi|Anruf-?Linien-?Taxi|Rufbus-?Linie"
    r"|Flexibus|Bedarfsverkehr)\b\s*",
    re.IGNORECASE,
)


def _on_demand(name: str) -> tuple[str, bool]:
    """("221 Rufbus") -> ("221", True). A name that is only the marker keeps it."""
    stripped = _ON_DEMAND.sub(" ", name).strip()
    if stripped == name.strip():
        return name, False
    return (stripped or name.strip()), True

#: Coaches share stations with local buses — BlaBlaCar and Flix at the Hbf — and
#: are not what a doorstep board is for: booked in advance, once a day, to
#: another city.
_SKIP_MODES = {"COACH"}


def _german_transit(stop_id: str) -> bool:
    """Whether a stop comes from a German public-transport feed.

    Transitous merges every feed it has, so the stops around Köln Hbf include the
    Belgian railway's copy of it, and around Marienplatz a carpooling feed's
    (amarillo) — offers of a lift, which on a departure board would read as a
    bus that may or may not exist. Both are dropped where a German feed has the
    place covered.
    """
    return stop_id.startswith("de-") and "amarillo" not in stop_id


async def _stops_in_box(
    http: httpx.AsyncClient, conf: dict[str, Any], lat: float, lon: float, radius: int
) -> list[dict[str, Any]]:
    dlat = radius / 111_320
    dlon = radius / (111_320 * max(math.cos(math.radians(lat)), 0.01))
    response = await http.get(
        f"{_base(conf)}/map/stops",
        params={"min": f"{lat - dlat},{lon - dlon}", "max": f"{lat + dlat},{lon + dlon}"},
    )
    response.raise_for_status()
    rows = response.json()
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


async def _areas_at(
    http: httpx.AsyncClient, conf: dict[str, Any], lat: float, lon: float
) -> list[dict[str, Any]]:
    """The administrative areas at a point, for the town's name. Best-effort:
    without it the stop names simply keep their town prefix."""
    try:
        response = await http.get(
            f"{_base(conf)}/reverse-geocode", params={"place": f"{lat},{lon}", "type": "STOP"}
        )
        response.raise_for_status()
        rows = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("areas"):
            return row["areas"]
    return []


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

    From the map's stop index rather than reverse geocoding, which answers with
    the five best-scored stops and no more: around Fürth Rathaus that is five
    bus stops, and the one that should get a board — the S-Bahn six hundred
    metres out — never comes up. The index returns every platform in the box,
    each with the modes that serve it, so they are grouped back into stations
    here and carry `products` the way BVG's do. That is what lets the choice of
    stops go by mode outside Berlin too, instead of nearest-first.

    Any platform's id does for the station: MOTIS answers a departures query for
    one platform with the whole station's.
    """
    rows, areas = await asyncio.gather(
        _stops_in_box(http, conf, lat, lon, radius), _areas_at(http, conf, lat, lon)
    )
    city = city_of(areas)

    german = [row for row in rows if _german_transit(str(row.get("stopId") or ""))]
    rows = german or rows

    stations: dict[str, dict[str, Any]] = {}
    for row in rows:
        stop_id, name = row.get("stopId"), row.get("name")
        if not stop_id or not name or row.get("lat") is None or row.get("lon") is None:
            continue
        distance = _haversine(lat, lon, row["lat"], row["lon"])
        if distance > radius:
            continue
        products = {
            _PRODUCTS[mode]
            for mode in row.get("modes") or []
            if mode in _PRODUCTS
        }
        key = " ".join(str(name).split()).casefold()
        station = stations.get(key)
        if station is None:
            stations[key] = {
                "id": row.get("parentId") or stop_id,
                "name": without_city(str(name), city),
                "distance": round(distance),
                "location": {"latitude": row["lat"], "longitude": row["lon"]},
                "products": {product: True for product in products},
                "city": city,
            }
            continue
        station["products"].update({product: True for product in products})
        if row.get("parentId"):
            station["id"] = row["parentId"]
        if distance < station["distance"]:
            station["distance"] = round(distance)
            station["location"] = {"latitude": row["lat"], "longitude": row["lon"]}

    found = sorted(stations.values(), key=lambda stop: stop["distance"])
    return found[: count * 3]


#: What some feeds put where a platform goes. It names the mode, not a place to
#: stand, and read as a platform it would fold both directions of every bus at
#: a stop into one — so hiding one direction would hide the other.
_NOT_PLATFORMS = {"bus", "u-bahn", "s-bahn", "tram", "straßenbahn", "zug", "bahn"}


def _platform(place: dict[str, Any]) -> str | None:
    """The track where there is a short one, else a description that names a
    place to stand.

    The track first: at Bamberg the description is "Gleis 6+8", the island
    between two tracks, and the track says which of them — "6" — which is the
    answer to "where do I go". Descriptions are the fallback for feeds without
    tracks, and for bus stops, where "Steig 4" is all there is.
    """
    for key in ("track", "scheduledTrack"):
        text = str(place.get(key) or "").strip()
        if text and len(text) <= 4 and text.casefold() not in _NOT_PLATFORMS:
            return text
    text = str(place.get("description") or "").strip()
    if text and text.casefold() not in _NOT_PLATFORMS:
        return text
    return None


def _departure(row: dict[str, Any], city: str | None = None) -> dict[str, Any] | None:
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

    line, on_demand = _on_demand(_line_name(row.get("routeShortName") or "") or "?")
    headsign = row.get("headsign") or ""
    # An on-demand trip's headsign is often the service, not the place:
    # "Anrufsammeltaxi", "Rufbus". Where it is, the trip's last stop says
    # where it goes, and the headsign says how.
    if headsign and not _ON_DEMAND.sub(" ", headsign).strip(" -–"):
        on_demand = True
        headsign = ((row.get("tripTo") or {}).get("name")) or headsign
    elif _on_demand(headsign)[1]:
        on_demand = True
    return {
        "tripId": row.get("tripId"),
        "line": {
            "name": line,
            "product": _PRODUCTS.get(str(row.get("mode") or "").upper()),
        },
        # Not a HAFAS field; BVG's answers simply lack it. The row still shows
        # when it would leave, and says it has to be booked.
        "onDemand": on_demand,
        # Positive only; see the shaping's step_free for why a "not" is dropped.
        "stepFree": row.get("wheelchairAccessible") == "ACCESSIBLE",
        # "Köln Niehl Sebastianstr." from a Köln stop: the town is where you
        # already are.
        "direction": without_city(headsign, city),
        "when": when,
        "plannedWhen": planned,
        # None, not 0, without live data — HAFAS's own convention, which the
        # shaping reads as "timetable only". A 0 would claim it is on time.
        "delay": delay if row.get("realTime") else None,
        # A cancelled trip cancels this stop of it; the panel draws either the
        # same way.
        "cancelled": bool(row.get("cancelled") or row.get("tripCancelled")),
        # MOTIS gives a human description ("S-Bahnsteig Gleis 3") where HAFAS
        # gives a bare platform number. Passed through as-is: the panel prints
        # whatever it is told, and the description is the more useful of the two
        # on foot.
        "platform": _platform(place),
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
    # Already one of ours: a stop this source found itself. BVG's ids are all
    # digits; Transitous's carry their feed ("de-DELFI_de:09563:2164"). Looking
    # one up again by name is not merely a wasted call — a name is not unique
    # across Germany, and "Rathaus" found Stuttgart's for a Hamburg board.
    if key and not key.isdigit():
        return key
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

    raw = [row for row in response.json().get("stopTimes") or [] if isinstance(row, dict)]
    # German feeds first, so where a neighbour's feed carries the same train —
    # the Austrian railway's copy of an ICE through Frankfurt — the German one
    # is the copy kept below.
    raw.sort(key=lambda row: "_de-" not in str(row.get("tripId") or ""))

    rows: list[dict[str, Any]] = []
    later: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for row in raw:
        if str(row.get("mode") or "").upper() in _SKIP_MODES:
            continue
        departure = _departure(row, board.get("city"))
        if departure is None:
            continue
        # Applied here rather than on the wire, which MOTIS does not offer.
        if wanted and (departure["line"]["product"] or "") not in wanted:
            continue
        # One train, two feeds: same line, same timetabled minute.
        key = (departure["line"]["name"], departure["plannedWhen"] or departure["when"])
        if key in seen:
            continue
        seen.add(key)
        at = _parse(departure["when"] or departure["plannedWhen"])
        if at is not None and at > cutoff:
            later.append(departure)
            continue
        rows.append(departure)

    rows = rows or lookahead(later, board, conf)
    rows.sort(key=lambda d: d["when"] or d["plannedWhen"] or "")
    return {"departures": rows}


def lookahead(
    later: list[dict[str, Any]], board: dict[str, Any], conf: dict[str, Any]
) -> list[dict[str, Any]]:
    """The next few departures past the window, for a stop with none inside it.

    The window is right for a city, where the question is "which of these do I
    run for", and wrong for a village, where the bus is three times a day and
    the question is "when is the next one". An empty board there says "nothing
    runs", which is false; the next bus at 15:07, or on Monday at 06:33, is the
    answer. The panel shows these as clock times, not countdowns.

    Off unless `lookahead_hours` is set — the wall's boards are hand-picked city
    stops and keep their window.
    """
    hours = board.get("lookahead_hours") or conf.get("lookahead_hours") or 0
    if not hours:
        return []
    keep = board.get("lookahead_results") or conf.get("lookahead_results") or 4
    horizon = datetime.now(timezone.utc) + timedelta(hours=float(hours))
    within = [
        departure for departure in later
        if (at := _parse(departure["when"] or departure["plannedWhen"])) is None or at <= horizon
    ]
    within.sort(key=lambda d: d["when"] or d["plannedWhen"] or "")
    return within[: int(keep)]


async def locations(
    http: httpx.AsyncClient,
    *,
    query: str,
    results: int,
    conf: dict[str, Any],
) -> list[dict[str, Any]]:
    """Address search, shaped as BVG's /locations answers, plus the parts.

    BVG hands back one string ("10115 Berlin-Mitte, Invalidenstr. 49") that the
    picker takes apart again; MOTIS has the parts, so they travel as fields —
    `street`, `postcode`, `district`, `country` — and the picker uses them
    as they are. Taking a formatted string apart is how "Garmisch-Partenkirchen"
    becomes the Partenkirchen district of Garmisch.

    MOTIS geocodes the whole planet from one text box. Nothing is filtered for
    that here beyond dropping stops, which the picker excludes on purpose; the
    country and the bounding box are the public app's rule. The search leans
    towards Berlin, where most of the page's visitors are, which only ranks —
    "Königstraße 20, Fürth" still finds Fürth.
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
        areas = hit.get("areas") or []
        street = hit.get("street") or hit.get("name") or ""
        number = hit.get("houseNumber")
        if number and not street.endswith(str(number)):
            street = f"{street} {number}"
        hits.append(
            {
                "type": "location",
                "name": hit.get("name"),
                "latitude": hit["lat"],
                "longitude": hit["lon"],
                "street": street,
                "postcode": hit.get("zip") or "",
                "district": district_of(areas) or "",
                "country": hit.get("country") or "",
                # A street address, or a place with a name — a café, a hiking
                # route. The picker lists addresses first.
                "kind": "address" if hit.get("type") == "ADDRESS" else "place",
            }
        )
        if len(hits) >= results:
            break
    return hits
