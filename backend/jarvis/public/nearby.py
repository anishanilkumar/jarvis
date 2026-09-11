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

from jarvis import sources
from jarvis.providers.departures import (
    merge_warnings,
    product_rank,
    route_order,
    shape_board,
)

#: Modes that get pooled into one block instead of a board per stop. Buses
#: only, and the argument is in `compose_boards`.
POOLED = ("bus",)

#: What the pooled block is called on the tile. Not a stop name, because it
#: isn't one stop.
POOLED_NAME = "Buses"

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


def _modes(stop: dict[str, Any]) -> set[str]:
    """The products a stop serves, as the nearby endpoint reports them.

    An empty set is a real answer and not an error: Transitous has no products
    field at all, so on the fallback path every stop looks mode-less and the
    selection below quietly degrades to plain nearest-first.
    """
    products = stop.get("products")
    if not isinstance(products, dict):
        return set()
    return {name for name, served in products.items() if served}


def choose_stops(stops: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Which of the nearby stops get a board — by mode, then by distance.

    Nearest-first alone is wrong for the question the page is asked. From
    one address the three closest stops are the U-Bahn station and two bus
    stops, and the S-Bahn four hundred metres away — the thing you actually
    leave the neighbourhood on — never gets a board, because two bus stops on
    the way to it got there first.

    So each pass takes the nearest stop that serves a mode nothing chosen yet
    does, and once every mode in reach is covered the remaining slots go to the
    nearest stops left. Berlin has a bus stop on every corner and one S-Bahn
    station per neighbourhood; spending a slot on the second corner rather than
    on the S-Bahn is spending it on the one you could have guessed.

    Nothing here tries to skip a stop for being redundant, and an earlier
    version that did was worse. It read the line list the nearby endpoint
    advertises and dropped any stop whose whole service was already covered —
    which sounds right and cost the shortest walk: from one address it skipped
    Mansteinstr. because the M19 was already listed at Yorckstr., turning a four
    minute walk to that bus into a five minute one. Redundancy is
    `compose_boards`' problem, it is settled on the routes that actually turn up
    rather than on a list HAFAS fills in differently per entrance, and a stop
    that turns out to add nothing costs one upstream call and no space on the
    tile.

    The result goes back into distance order, because the boards are laid out
    nearest-first and the walk is what you scan them by.
    """
    covered: set[str] = set()
    chosen: list[int] = []
    # Nearest-first, and stays that way as picks are removed.
    left = list(range(len(stops)))

    while left and len(chosen) < count:
        # `left` is already nearest-first, so "the first one that adds a mode"
        # is also the nearest one that does.
        pick = next((i for i in left if _modes(stops[i]) - covered), left[0])
        left.remove(pick)
        covered |= _modes(stops[pick])
        chosen.append(pick)

    return [stops[i] for i in sorted(chosen)]


async def stops_near(
    http: httpx.AsyncClient,
    conf: dict[str, Any],
    lat: float,
    lon: float,
    *,
    count: int,
    radius: int,
) -> tuple[str, list[dict[str, Any]]]:
    """Up to `count` stops within `radius` metres, nearest first, from whichever
    source answers.

    The de-duplication below is deliberately on this side of the source layer
    rather than inside it. It is a fact about how stations are named — one
    place reported once per entrance and once per mode — and it is true of
    every source, so writing it twice would be writing the same subtle rule
    twice and getting it wrong once.

    De-duplicating the whole answer before choosing, rather than stopping at
    the first `count`, is what gives `choose_stops` something to choose from:
    truncating first would hand it the three nearest and no S-Bahn.
    """
    name, found = await sources.attempt(
        "nearby", http=http, lat=lat, lon=lon, count=count, radius=radius, conf=conf
    )

    seen: set[str] = set()
    stops: list[dict[str, Any]] = []
    for stop in found:
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
    return name, choose_stops(stops, count)


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


def _route_key(route: dict[str, Any]) -> tuple[str, str]:
    """What makes two strips at two stops the same service.

    Line and destination, not line alone: the U7 north and the U7 south are two
    different answers to "should I leave now", and folding them together would
    drop a whole direction. Case-folded because the two stops shortened the
    same HAFAS direction independently.
    """
    return (
        (route.get("line") or "").casefold(),
        (route.get("destination") or "").casefold(),
    )


def _flatten(routes: list[dict[str, Any]], keep: int) -> list[dict[str, Any]]:
    """The flat departure list a board carries alongside its routes.

    Rebuilt from the routes rather than kept from the stop it came from,
    because a board's routes are no longer all of one stop's routes: leaving
    the original list in place would have the pooled block answering "what is
    the soonest thing here" with a U-Bahn that is on a different board.
    """
    flat = [departure for route in routes for departure in route["departures"]]
    flat.sort(key=lambda departure: departure.get("when") or departure.get("planned") or "")
    return flat[:keep]


def compose_boards(
    shaped: list[dict[str, Any]], conf: dict[str, Any], limit: int | None = None
) -> list[dict[str, Any]]:
    """Stop boards for the rail, one pooled block for the buses.

    Two things are wrong with one-board-per-stop once nobody has hand-picked
    the stops, and both of them show up at the first address you try.

    THE SAME SERVICE APPEARS TWICE. Stops are chosen for being near, and lines
    do not stop at one of them. From one address the U7 is at U Kleistpark
    three minutes away and again at Yorckstr six minutes away, and the M19 is at
    Mansteinstr and at Yorckstr — so a third of the tile went to telling you
    about trains you had already been told about, on a longer walk. Each route
    is kept once now, at the stop with the shortest walk to it, which is the
    only copy that was ever any use.

    THE ORDER FOLLOWS THE WALK RATHER THAN THE PLAN. A board per stop forces
    every row of the nearest stop above every row of the next one, so five bus
    routes off the corner sat above the S-Bahn. What you actually want is rail
    first wherever it is, and the buses after it — so the buses come out of
    their stops and into one block, ordered by whatever leaves soonest across
    all of them, each row carrying its own walk. That is how a bus gets used
    anyway: you take the one that comes, from whichever corner.

    Trams keep a board of their own. A tram is not a bus you catch from
    whichever corner — it runs one route on rails, less often, and further.

    `limit` is how many boards the tile has room for IN TOTAL, the pooled block
    included — the tile's height is fixed, and a limit that counted only the
    stop boards would silently ask it to draw one more than it was measured
    for, which it does by cropping the last row off the bottom.

    It is applied here at the end rather than by fetching fewer stops. Which
    stops are worth a board is a fact about the routes they turn out to run, and
    there is no way to know that before asking: the caller over-fetches
    candidates, everything they run feeds the pooled block, and the ones left
    with nothing of their own to say simply never appear.
    """
    keep = conf.get("results", 12)
    rows = conf.get("rows", 3)
    route_length = conf.get("route_length", 4)

    # Nearest first, so the copy of a route that survives is the short walk.
    by_walk = sorted(shaped, key=lambda board: board["walk_minutes"])

    seen: set[tuple[str, str]] = set()
    boards: list[dict[str, Any]] = []
    pooled: list[dict[str, Any]] = []
    pooled_warnings: list[str] = []

    for board in by_walk:
        own: list[dict[str, Any]] = []
        for route in board.get("routes") or []:
            key = _route_key(route)
            if key in seen:
                continue
            seen.add(key)
            if route.get("product") in POOLED:
                # The walk travels with the route, because on the pooled block
                # it is the only thing left saying which corner this is.
                pooled.append({**route, "walk_minutes": board["walk_minutes"],
                               "stop": board["name"]})
            else:
                own.append(route)

        if any(route.get("product") in POOLED for route in board.get("routes") or []):
            pooled_warnings.extend(board["warnings"])
        if own:
            boards.append({**board, "routes": own, "departures": _flatten(own, keep)})

    # Rail before tram before whatever else, and within a class the shorter
    # walk — which is what puts the U7 above the S-Bahn from one address and
    # would put the S-Bahn first from an address nearer to it.
    boards.sort(
        key=lambda board: (
            min(product_rank(route.get("product")) for route in board["routes"]),
            board["walk_minutes"],
        )
    )
    if limit is not None:
        # The block takes one of the slots, so the stop boards get the rest.
        boards = boards[: max(0, limit - (1 if pooled else 0))]

    if pooled:
        boards.append(
            {
                "name": POOLED_NAME,
                "stop": "",
                # The shortest walk in the block, as the fallback for a panel
                # too old to read the per-route ones. Wrong for every other row,
                # and wrong in the safe direction: it only ever shows a
                # departure you have less time to reach than it claims.
                "walk_minutes": min(route["walk_minutes"] for route in pooled),
                "rows": rows,
                "route_length": route_length,
                # Whatever leaves next, re-sorted by the panel every tick. The
                # block exists because these are alternatives to each other.
                "order": "soonest",
                # The flag that turns on the per-row walk column. A panel that
                # does not know the key renders the block as an ordinary board,
                # which is wrong but not broken.
                "pooled": True,
                "routes": sorted(
                    pooled,
                    key=lambda route: (route["walk_minutes"], *route_order(route)),
                ),
                "departures": _flatten(pooled, keep),
                "warnings": list(dict.fromkeys(pooled_warnings)),
            }
        )

    return boards


#: How many hides one request is read for. They arrive in a query string anyone
#: can write and each costs a pass over the boards; a real visitor has a handful.
MAX_HIDES = 50


def _platform(route: dict[str, Any]) -> str | None:
    """The platform a route leaves from, when the source reports one.

    The most common rather than the first, so one departure moved to the other
    track for engineering works cannot relabel the route. Ties go to the one
    seen first, which keeps the token the same from one poll to the next.
    """
    platforms = [
        departure["platform"]
        for departure in route.get("departures") or []
        if departure.get("platform")
    ]
    if not platforms:
        return None
    return max(dict.fromkeys(platforms), key=platforms.count)


def _annotate(board: dict[str, Any], stop_id: str) -> dict[str, Any]:
    """A shaped board, carrying the tokens the page hands back to hide things.

    Issued here rather than built in the browser, so what a token means lives in
    one place — `apply_hides`, below — and the page treats them as opaque.

    A train is hidden by PLATFORM, a bus by destination. The destination is the
    obvious key and it is wrong for rail: at Yorckstr. the S1 northbound reports
    Frohnau, Oranienburg and Schönholz, three strips for one direction, and
    hiding "Oranienburg" would leave the other two sitting there. The platform
    is what those three have in common, and it is also what a short-turn nobody
    has seen yet will have in common with them. Buses report no platform, so
    they fall back to the destination, and a bus short-turn is its own hide.
    """
    routes = []
    for route in board.get("routes") or []:
        platform = _platform(route)
        token = (
            f"p:{stop_id}:{route['line']}:{platform}"
            if platform
            else f"r:{route['line']}:{route['destination']}"
        )
        routes.append({**route, "platform": platform, "hide": token})
    return {**board, "routes": routes, "stop_id": stop_id, "hide": f"s:{stop_id}"}


def _direction_label(line: str, routes: list[dict[str, Any]]) -> str:
    """"U7 → Rudow, Britz-Süd" — what a hidden direction is called in settings."""
    destinations = dict.fromkeys(route["destination"] for route in routes)
    return f"{line} → {', '.join(destinations)}"


def apply_hides(
    shaped: list[dict[str, Any]], tokens: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """The stops' boards with one visitor's hides taken out, and what was taken.

    Applied BEFORE composing, and that ordering is the reason this runs on the
    server at all. Composing keeps only so many boards and each route only at
    its nearest stop, so hiding afterwards — all the browser could do — would
    leave a hidden stop's slot empty instead of handing it to the next stop out,
    and would take the U7 off the page instead of letting it come back from the
    other station it calls at.

    A hidden direction is gone from every stop, not only the one it was hidden
    at: "I don't go south on the U7" is not a fact about one platform. The
    destinations a token covers are looked up where it was issued, and at every
    other stop the platform carrying any of them goes dark with them — which is
    what catches a short-turn that happens to show up only at the farther stop.

    Tokens that match nothing — a stop near a different address, a bus that is
    not running this hour — are skipped rather than refused, and are left out
    of what comes back, so the page can tell which hides are doing anything.

    Matched by equality against the tokens `_annotate` issued, never parsed.
    Parsing looked safe until the fallback answered: a Transitous stop id is
    `de-VBB_de:11000:900003201`, colons and all, and a split on ":" read the
    line out of the middle of it and quietly hid nothing.
    """
    gone_stops: set[str] = set()
    gone: set[tuple[str, str]] = set()
    hidden: list[dict[str, str]] = []

    for token in dict.fromkeys(tokens[:MAX_HIDES]):
        stop = next((board for board in shaped if board.get("hide") == token), None)
        if stop is not None:
            gone_stops.add(stop["stop_id"])
            hidden.append({"token": token, "kind": "stop", "label": stop["name"]})
            continue
        # A bus token carries no stop, so it matches that route at every stop
        # it was found at; a platform token matches the one stop it came from.
        routes = [
            route
            for board in shaped
            for route in board.get("routes") or []
            if route.get("hide") == token
        ]
        if routes:
            gone.update(_route_key(route) for route in routes)
            hidden.append(
                {
                    "token": token,
                    "kind": "direction",
                    "label": _direction_label(routes[0]["line"], routes),
                }
            )

    kept: list[dict[str, Any]] = []
    for board in shaped:
        if board.get("stop_id") in gone_stops:
            continue
        routes = board.get("routes") or []
        dark = {
            (route["line"], route["platform"])
            for route in routes
            if route.get("platform") and _route_key(route) in gone
        }
        kept.append(
            {
                **board,
                "routes": [
                    route
                    for route in routes
                    if _route_key(route) not in gone
                    and (route["line"], route.get("platform")) not in dark
                ],
            }
        )
    return kept, hidden


async def fetch_boards(
    http: httpx.AsyncClient,
    stops: list[dict[str, Any]],
    conf: dict[str, Any],
    *,
    metres_per_minute: float,
    found_by: str | None = None,
) -> dict[str, Any]:
    """Every nearby stop's board, shaped but not yet composed.

    This is the half worth caching and the half that can be shared: it costs an
    upstream call per stop and depends on nothing but where the stops are.
    Composing depends on who is asking — on what they have hidden — and is pure
    arithmetic over this, so it runs per request in `compose_view`.

    `stops` is deliberately longer than the boards that come out of it. Every
    stop is fetched, and `compose_boards` then throws away the ones whose whole
    service was already listed from somewhere nearer — which cannot be decided
    any earlier, because it is a fact about the routes and nothing before this
    point knows what they are. From one address that is the difference between
    the second and third boards being the same two trams again and them being
    the U-Bahn. It is also the surplus a hidden stop's slot is handed to.

    `found_by` is the source that produced the stops, and it pins the ids: a
    Transitous stop id means nothing to BVG and the reverse is equally true, so
    a board found by one source can only be read by that one. Without this the
    fallback fails in the worst available way — a valid-looking request for an
    id the API has never heard of, answered with an empty list, drawn as a stop
    where nothing runs.
    """
    asked = [board_for(stop, metres_per_minute=metres_per_minute) for stop in stops]

    async def one(board: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        name, raw = await sources.attempt(
            "departures", http=http, board=board, conf=conf, only=found_by
        )
        return name, _annotate(shape_board(raw, board, conf), board["stop_id"])

    results = list(await asyncio.gather(*(one(board) for board in asked)))
    shaped = [board for _, board in results]
    return {
        "shaped": shaped,
        # From the stops rather than from the composed boards. Composing drops
        # duplicate routes and can drop a whole board, and a disruption notice
        # is a fact about the stop that reported it — losing it because its
        # only route was already listed from a nearer platform, or because the
        # visitor hid that stop, would be the quietest possible way to stop
        # mentioning disruptions.
        "warnings": merge_warnings(shaped),
        "sources": sorted({name for name, _ in results}),
    }


def compose_view(
    fetched: dict[str, Any],
    conf: dict[str, Any],
    hides: list[str],
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """The document `Departures.fetch` produces, for one visitor's hides."""
    shaped = fetched.get("shaped") or []
    kept, hidden = apply_hides(shaped, hides)
    applied = {entry["token"] for entry in hidden}

    view: dict[str, Any] = {
        "boards": compose_boards(kept, conf, limit),
        "warnings": fetched.get("warnings") or [],
        "sources": fetched.get("sources") or [],
        # Every stop that was looked at, nearest first and hidden or not. The
        # settings screen lists these rather than the boards, because a stop
        # that never earned a board has no row on the tile to hide it from —
        # and a hidden one has to stay listed to be brought back.
        "stops": [
            {
                "id": board["stop_id"],
                "name": board["name"],
                "walk_minutes": board["walk_minutes"],
                "hide": board["hide"],
                "hidden": board["hide"] in applied,
            }
            for board in sorted(shaped, key=lambda board: board["walk_minutes"])
        ],
        "hidden": hidden,
    }
    if "stale_seconds" in fetched:
        view["stale_seconds"] = fetched["stale_seconds"]
    return view
