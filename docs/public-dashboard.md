# The public dashboard

The same two answers the wall gives — what the weather is doing and what you
can catch — for anyone in Berlin, with no login and no household. Live at
[abfahrt.anishsheela.com](https://abfahrt.anishsheela.com).

A visitor types their address once; the page finds the stops around it and
shows the weather, a jacket-or-umbrella call and departure boards for each one.
The address lives in that browser and nowhere else.

```
backend/jarvis/public/    FastAPI, 127.0.0.1:8768, stateless
frontend/src/public/      a second Vite entry (site.html -> dist-public/)
jarvis-public.toml        committed, because it holds nothing private
deploy-public.sh          builds, ships, restarts, polls /api/health
```

```bash
# backend
cd backend && JARVIS_CONFIG=../jarvis-public.toml \
  .venv/bin/uvicorn jarvis.public.app:app --port 8768 --reload

# panel (proxies /api to :8768), then open /site.html
cd frontend && npm run dev:site

JARVIS_PUBLIC_HOST=you@yourvps ./deploy-public.sh
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
its nearest stop. Hide a stop after that and its slot sits empty instead of
going to the next stop out. Its U7 also vanishes, even though the station beyond
runs it too. So the cache holds every stop's shaped board, still keyed on
rounded coordinates and shared. Composing runs per request with the visitor's
`hide=` tokens, which is pure arithmetic over a warm cache. Trains hide by
platform, not destination: the S1 northbound at Yorckstr. is three destinations
and one platform. Buses report no platform and hide by destination. The API
issues the tokens, the page never parses them, and shared links carry them.

**Berlin only, and why that is enforced twice.** The address search is VBB's,
which covers Brandenburg too — searching a Berlin street name returns
Oranienburg and Borkwalde behind it. So results are filtered, *and* every
coordinate reaching the API is bounding-box checked. The second check is the
real one: the URL parameters take lat/lon directly, and without it this would
be a free worldwide proxy for two APIs that are somebody else's to pay for. A
per-IP rate limit and a cap on concurrent upstream calls sit alongside it.

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
quietly, forever. Two builds also keep `deploy.sh`'s `rsync --delete` from
shipping this entire site to the Pi.

**No audio, by absence.** The public entry never imports `voice.ts`, so
`getUserMedia` and the WebSocket client are not in the bundle — `grep` the
built assets and there is nothing to disable. That is also why it does not
reuse the wall's clock widget, which pulls the voice client in for its reactor
dial.
