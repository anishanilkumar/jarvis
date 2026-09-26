# The public dashboard

The same two answers the wall gives — what the weather is doing and what you
can catch — for anyone in Germany, with no login and no household. Live at
[abfahrt.anishsheela.com](https://abfahrt.anishsheela.com).

A visitor types their address once; the page finds the stops around it and
shows the weather, a jacket-or-umbrella call and departure boards for each one.
The address lives in that browser and nowhere else.

```
backend/jarvis/public/    FastAPI, 127.0.0.1:8768, stateless
frontend/src/public/      a second Vite entry (site.html -> dist-public/)
jarvis-public.toml        committed, because it holds nothing private
nix/public.nix            services.jarvis-public, the NixOS module
deploy                    push to main: CI tests, deploys, checks /api/health/deep
```

```bash
# backend
cd backend && JARVIS_CONFIG=../jarvis-public.toml \
  .venv/bin/uvicorn jarvis.public.app:app --port 8768 --reload

# panel (proxies /api to :8768), then open /site.html
cd frontend && npm run dev:site
```

It shares the code that took the longest to get right — how a HAFAS direction
string becomes a destination you would say out loud, how departures fold into
route strips, which hours a jacket decision is actually about — and the widget
components that draw them. It shares none of the machinery: no provider
registry, no scheduler, no SSE, no cache on disk, no secrets and no voice.

**Where the boards come from.** There is no configured stop, because there is
no configured household. `GET /locations/nearby` gives the three closest stops
with their distance in metres, and each becomes a synthetic
`[[departures.boards]]` table with every filter empty and the walk derived from
that distance. Tested against an address whose four boards had been hand-picked
in `jarvis.toml`, the automatic version returns three of the same four — which
is the evidence it is good enough to hand a stranger. The one setting that is
not empty is `order = "line"`: it is the only ordering that can place a
terminus no `groups` table has ever named, and here that is every terminus.

**Where the jacket threshold is applied — not on the server.** `/api/weather`
returns the forecast *facts*: the coldest apparent temperature in the hours you
have left, the wettest, and when. The browser turns those into "take a jacket".
That falls out of caching — the response is keyed on coordinates rounded to
about 110m and shared by everyone near that rounding, so it cannot carry one
person's idea of cold. The payoff is that dragging the slider re-answers with
no network at all. The cost is that `decide()` exists twice, in
`providers/weather.py` and `frontend/src/public/advice.ts`, and the two must
agree.

**Where hides are applied — on the server, the other way round.** A visitor can
hide a stop, or one direction of a line, from the opened departures tile. The
jacket's argument would put that in the browser too, and there it breaks. The
server looks at five stops, composes three boards, and keeps each route only at
the nearest stop that gets a board. Hide a stop after that and its slot sits
empty instead of going to the next stop out. Its U7 also vanishes, even though the station beyond
runs it too. So the cache holds every stop's shaped board, still keyed on
rounded coordinates and shared. Composing runs per request with the visitor's
`hide=` tokens, which is pure arithmetic over a warm cache. Trains hide by
platform, not destination: the S1 northbound at Yorckstr. is three destinations
and one platform. Buses report no platform and hide by destination. The API
issues the tokens, the page never parses them, and shared links carry them.

**Germany, from two sources.** Inside Berlin and Brandenburg the stops and
departures come from BVG first, because only BVG carries the disruption
notices; everywhere else, and in Berlin whenever BVG is down, from Transitous,
which reads Germany's national timetable (DELFI) and whatever live data each
region publishes. Live delays are good where the regional network sends them —
Munich, Köln, the Nuremberg area — and patchy where it doesn't, which in
September 2026 included Hamburg. Transitous has no disruption notices anywhere,
and the tile says which source it is on for that reason.

Transitous needed more translating than a second source for Berlin did. Its
nearby-stop search answers with five stops, so stops come from its map index
instead — every platform in the radius, with the modes that serve it — grouped
back into stations, which is what lets the stop choice prefer the S-Bahn over a
fifth bus stop outside Berlin too. Stops from neighbouring countries' feeds and
from a carpooling feed are dropped; long-distance coaches are dropped; a train
carried by two feeds is kept once. The town is taken off the front of stop
names and destinations ("Fürth Rathaus" is "Rathaus" on a page about Fürth),
and train numbers off line names ("RE19 (4913)", "ICE 1518").

The address search goes to Transitous first for the same reason in reverse:
BVG's knows only Berlin and Brandenburg, and answers a Fürth street with a
Potsdam one.

**Villages.** The board was built for a city, where the question is which of
several trams to run for, and three things about it are wrong in the
countryside:

- *A 45-minute window empties the board.* A stop with nothing inside it now
  shows its next few departures anyway, up to 60 hours out, and the panel
  draws anything an hour or more away as a time of day — "16:51", "Mon 13:22"
  — instead of a countdown nobody wants to do arithmetic on. BVG will not look
  more than about a day ahead in one query, so for a Brandenburg village the
  horizon is walked a day at a time.
- *900 metres misses the station.* With no train inside the radius, the stop
  search looks again at 2.5 km and then 6 km for the nearest station, which
  then competes for a board like any other stop, with its honest walk — 39
  minutes from Niedermirsberg to Ebermannstadt — and only its trains: its
  buses would be rows nobody can reach. Stops are cached for an hour, apart from
  the 30-second departures, because that search is the expensive half.
- *Some buses come only if you rang.* Rufbus and AST (Anruf-Sammel-Taxi) runs
  are in the national timetable, marked nowhere but in the line's name — "221
  Rufbus", "224 AST"; the pickup and reservation fields say NORMAL and NONE for
  every one of them across Landkreis Forchheim. So the name is read, the line
  shows as "221" with a CALL mark, and its booked-only runs keep a row of their
  own rather than folding into the timetabled 221's. Where the headsign is only
  "Anrufsammeltaxi", the trip's last stop stands in as its destination.

**What each row admits to.** A time off live data and a time off the timetable
count down the same way, so the ones that are only the timetable are dotted
and the tile's status line says what the dots mean ("timetable only", or
"dotted = timetable" when it is mixed); Berlin on BVG, all live, looks as it
always did. Every stop shows the walk and, beside it, the same distance by bike
(200 straight-line metres a minute) — the walk stays the threshold the
countdown uses. Trains show their track in the expanded view ("Gl. 6"), from
the track field where the feed has one, since a description like "Gleis 6+8"
names the island rather than the track. A departure marked step-free gets the
wheelchair mark; one marked "not accessible" gets nothing, because outside
Berlin every feed checked says that for every trip, Munich's U-Bahn included,
which can only mean "unknown".

**How the board knows it is working.** `/api/health` says the process is up.
`/api/health/deep` runs the real pipeline for Berlin Hbf (BVG's path) and
Fürth Rathaus (Transitous's) and answers 503, naming which, if either has no
boards or has been served from the last-good cache for over five minutes —
the one to point an uptime monitor at.

**Why coverage is enforced twice.** Search results are filtered to Germany,
*and* every coordinate reaching the API is bounding-box checked. The second
check is the real one: the URL parameters take lat/lon directly, and without it
this would be a free worldwide proxy for APIs that are somebody else's to pay
for. A per-IP rate limit and a cap on concurrent upstream calls sit alongside
it.

**Links carry the whole view.** `?lat=&lon=&name=&jacket=` opens straight onto
a dashboard with no lookup; `?q=<address>` is geocoded on load and goes
straight through when the first hit *is* what was typed, stopping at the picker
otherwise — guessing between two real streets is how you show someone the wrong
tram. `?kiosk=1` hides the settings for casting to a screen. A link never
overwrites the visitor's own saved address: they opened your view, they did not
adopt it.

**Two builds, not two entries in one.** `vite.public.config.ts` is separate
from `vite.config.ts` on purpose. Sharing a build would let two entries share
chunks, and `update.ts` decides whether the wall is running current code by
comparing its own module URL against the first `<script src>` in a freshly
fetched `/index.html` — a change that moved only a shared chunk's hash would
leave that check saying "current" while the wall ran old code. It would lie,
quietly, forever. Two builds also keep the wall's web root — one directory,
served whole — from carrying this entire site to the Pi.

**No audio, by absence.** The public entry never imports `voice.ts`, so
`getUserMedia` and the WebSocket client are not in the bundle — `grep` the
built assets and there is nothing to disable. That is also why it does not
reuse the wall's clock widget, which pulls the voice client in for its reactor
dial.
