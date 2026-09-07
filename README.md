# Jarvis

A wall-mounted household display and voice front-end. Runs on a Raspberry Pi,
shown on a cheap Android tablet bolted to the wall.

Weather, a jacket-or-umbrella call for the day, live BVG tram and bus
departures, headlines, a Grocy meal plan and shopping list, and music — driven
by touch and by "hey jarvis". Voice runs entirely on the Pi: no key, no quota,
no account, and nothing said in the house is transmitted anywhere.

The tablet is stock Android running a kiosk browser. **No custom ROM.** All the
logic lives on the Pi, so features get added on a real machine and the tablet is
never touched again.

```
Tablet (Webview Kiosk + HA Companion App)
  │  https://dash.example.com
  │  ├── SSE      /api/stream       state pushed down
  │  ├── POST     /api/action/*     touch writes
  │  └── WSS      /voice            speech segments up
  ▼
Raspberry Pi
  ├── jarvis-dashboard  :8140   providers, intent registry
  ├── jarvis-voice      :8141   wake word → speaker ID → STT → intent → TTS
  └── home-assistant    :8123   devices, and the relay that launches YT Music
```

## On the wall

Eight tiles. Each is one provider on the Pi and one widget in the bundle, and
each is independently switchable in config.

| Tile | What it answers | Needs |
| --- | --- | --- |
| clock | Time and date, on the dial that doubles as the talk button | nothing |
| weather | Today's temperature, and the week | Open-Meteo, no key |
| rain | Whether you need an umbrella in the next two hours | Open-Meteo, no key |
| departures | The trams and buses you can still catch, per stop | `v6.bvg.transport.rest`, no key |
| meals | What is for dinner today and tomorrow | Grocy |
| shopping | The list, addable by voice | Grocy |
| news | Headlines with pictures, from any RSS feed | the feed you choose |
| music | What is playing, and "hey jarvis, play…" | Home Assistant |

Weather and departures work with no credentials at all. Grocy, voice and music
need keys — and each missing one degrades exactly one tile to a visible error,
never the panel.

## Two ideas the whole thing rests on

**Nothing ever blanks.** Every provider keeps its last good value in memory and
on disk. An upstream failure shows stale data with a timestamp, never an empty
tile, and recovers unattended.

**Nothing ever lies.** `useful_for` is the second half of that. When the tablet
loses the Pi, each tile shows cached data only as long as it remains true, then
goes quiet. Most sharply for departures: past ten minutes the **countdowns
freeze** and only scheduled clock times remain. A countdown ticking down on data
that can't be refreshed is actively wrong, and a display that lies about your
tram is worse than one that admits it doesn't know.

## Adding a feature

One provider file, one widget folder, one config block. Nothing central to edit
— both sides auto-discover.

**1. `backend/jarvis/providers/<slug>.py`**

```python
class Chores(Provider):
    slug = "chores"
    intents = ["what are my chores", "mark the bathroom done"]

    async def fetch(self) -> dict: ...
    async def action(self, payload) -> dict: ...              # touch writes
    async def handle_intent(self, utterance, slots, speaker): ...  # voice
```

**2. `frontend/src/widgets/<slug>/index.tsx`**

```tsx
export default { slug: 'chores', size: { w: 1, h: 1 }, Card, Detail } satisfies Widget
```

**3. `jarvis.toml`**

```toml
[providers.chores]
ttl = 300           # how often the Pi refreshes
stale_after = 900   # Pi has data but it's old -> tile marked stale
useful_for = 86400  # tablet lost the Pi -> show cached data this long, then go dark
```

Declaring `intents` is all that voice needs. Those example phrasings *are* the
routing table: `backend/jarvis/voice/intent.py` weights each word by how few
providers use it, so a new widget is speakable the moment it declares how people
would ask for it. Give it the words someone would actually say, and prefer ones
no other widget would claim.

## Running it

```bash
# backend
cd backend
python -m venv .venv && .venv/bin/pip install -e .
STATE_DIRECTORY=/tmp/jarvis .venv/bin/uvicorn jarvis.main:app --port 8140 --reload

# panel (proxies /api to :8140)
cd frontend && npm install && npm run dev
```

Copy `jarvis.example.toml` to `jarvis.toml` and edit the stop id, the
coordinates and the hosts. It is gitignored, which is why the example is the
committed one; every comment in it is there to be read.

Deploying is one script:

```bash
JARVIS_HOST=you@yourpi ./deploy.sh
```

It builds the panel here, rsyncs panel + backend + `jarvis.toml`, restarts the
units and fails loudly if the backend doesn't come back healthy. Because
`jarvis.toml` is gitignored, a deploy is the only thing that carries config to
the Pi — worth knowing, because a config that never arrives looks exactly like a
feature that doesn't work.

Standing the wall up the rest of the way — voice models, secrets, the health
check that tells you whether it worked, DNS and HTTPS — is
[docs/wall.md](docs/wall.md); the tablet is [docs/tablet.md](docs/tablet.md).

## A second front end: the public dashboard

The same two answers, for anyone in Berlin, at
**[abfahrt.anishsheela.com](https://abfahrt.anishsheela.com)**. A visitor types
their address once; the page finds the stops around it and shows the weather, a
jacket-or-umbrella call and departure boards for each one. The address lives in
that browser and nowhere else.

It is a second front end to this repo, not a second project. Both halves share
the code that took the longest to get right — how a HAFAS direction string
becomes a destination you would say out loud, how departures fold into route
strips, which hours a jacket decision is actually about. What they do not share
is machinery: the public side has no provider registry, no scheduler, no SSE, no
cache on disk, no secrets and no voice.

How it picks stops for an address nobody configured, where the jacket threshold
is applied and why Berlin-only is enforced twice:
[docs/public-dashboard.md](docs/public-dashboard.md).

## Voice, and no proprietary dependencies

openWakeWord listens, whisper.cpp transcribes, the intent is matched locally
against the providers' own declared phrasings, and Piper speaks the answer. That
is the whole pipeline, and all of it runs on the Pi.

It used to route through a cloud model, and the swap cost two things worth
knowing about before you build on it — English only, and no general-knowledge
answers. Both, and the evening of API failures that settled it:
[docs/voice.md](docs/voice.md).

Everything here is open source: NixOS, Caddy, Home Assistant, openWakeWord, ONNX
Runtime, whisper.cpp, Piper, FastAPI, Preact, SQLite and Grocy. Open-Meteo's
server is AGPL on open DWD/ECMWF data, and `v6.bvg.transport.rest` is
derhuerst's ISC-licensed `hafas-rest-api`.

## Documentation

- [docs/wall.md](docs/wall.md) — one-time setup on the Pi: config, secrets,
  voice models, the health check, DNS and why HTTPS is load-bearing.
- [docs/tablet.md](docs/tablet.md) — kiosk browser, Companion App, and the
  vendor battery settings that otherwise kill the panel overnight.
- [docs/public-dashboard.md](docs/public-dashboard.md) — the public Berlin
  dashboard, and the decisions behind it.
- [docs/voice.md](docs/voice.md) — the local voice stack, what leaving the cloud
  cost, and how to go back if you want to.
- [docs/deployment-notes.md](docs/deployment-notes.md) — eight things that only
  showed up on real hardware, kept because they cost hours.

## Licence

MIT — see `LICENSE`. The bundled fonts are not MIT: Archivo and IBM Plex Mono
are both SIL Open Font License 1.1, see `frontend/public/fonts/README.md`.
