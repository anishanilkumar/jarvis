# Jarvis

A wall-mounted household display and voice front-end. Runs on a Raspberry Pi,
shown on a cheap Android tablet bolted to the wall.

Weather, rain, live BVG tram/bus departures for your stop, a Grocy meal plan and
shopping list, and music — driven by touch and by "hey jarvis".

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

## Development

```bash
# backend
cd backend
python -m venv .venv && .venv/bin/pip install -e .
STATE_DIRECTORY=/tmp/jarvis .venv/bin/uvicorn jarvis.main:app --port 8140 --reload

# panel (proxies /api to :8140)
cd frontend && npm install && npm run dev
```

Weather and departures work with no credentials at all. Grocy, voice and music
need keys — each missing one degrades exactly one tile to a visible error.

## Deploying

```bash
JARVIS_HOST=you@yourpi ./deploy.sh
```

Builds the panel here, rsyncs panel + backend + `jarvis.toml`, restarts the
units, and fails loudly if the backend doesn't come back healthy.

`jarvis.toml` is gitignored, so a deploy is the only thing that carries config
to the Pi — worth knowing, because a config that never arrives looks exactly
like a feature that doesn't work. The previous copy is kept on the Pi as
`jarvis.toml.bak-<timestamp>`. Set `JARVIS_SKIP_CONFIG=1` to leave the Pi's
config alone; `JARVIS_REPO` and `JARVIS_WEB_ROOT` override the paths.

The systemd units, the reverse-proxy vhost and the secrets live in a separate
NixOS config repo. `nix/` here has both modules to copy in; on a non-NixOS box
they translate directly to two systemd units and an nginx/Caddy vhost.

### One-time setup on the Pi

```bash
git clone git@github.com:<you>/jarvis.git ~/jarvis
cp jarvis.example.toml jarvis.toml   # then edit: stop id, coordinates, hosts

# Secrets. Placeholders are committed; put the real keys in:
#   GROCY_API_KEY=...  HA_TOKEN=...
# On NixOS, agenix. Anywhere else, a root-owned EnvironmentFile.
# Voice needs no key: speech recognition runs on this machine.

# Voice interpreter. On NixOS both services are declarative and there is
# nothing to do here — nix/jarvis-dashboard.nix builds it, including the one
# package missing from nixpkgs (nix/pkgs/openwakeword.nix). Do NOT reach for a
# venv on NixOS: without programs.nix-ld there is no dynamic loader at /lib, so
# pip's manylinux wheels for numpy and onnxruntime cannot execute at all.
# Anywhere else, the venv is the normal path:
python -m venv ~/.venv/jarvis-voice
~/.venv/jarvis-voice/bin/pip install -e ~/jarvis/backend[voice]

# Wake word models. openWakeWord fetches these itself on first use, into its
# own package directory — which is read-only when the interpreter comes from
# the nix store, and which fails at the first frame of audio rather than at
# startup. Fetch them by hand and jarvis passes them in by path.
mkdir -p /var/lib/jarvis/openwakeword && cd /var/lib/jarvis/openwakeword
oww=https://github.com/dscripka/openWakeWord/releases/download/v0.5.1
curl -LO $oww/melspectrogram.onnx
curl -LO $oww/embedding_model.onnx
curl -LO $oww/hey_jarvis_v0.1.onnx      # or your own model, named hey_jarvis*

# Piper voice model for TTS
mkdir -p /var/lib/jarvis/piper && cd /var/lib/jarvis/piper
voice=https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium
curl -LO $voice/en_GB-alba-medium.onnx
curl -LO $voice/en_GB-alba-medium.onnx.json

# whisper.cpp model for STT. tiny.en is the default: measured on a Pi 4 it
# answers a spoken command in 2.9s against base.en's 6.2s, and the errors it
# does make are the kind the intent matcher survives. Fetch base.en instead —
# and set model in jarvis.toml — if it mishears you too often.
mkdir -p /var/lib/jarvis/whisper && cd /var/lib/jarvis/whisper
curl -LO https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin
```

Then flip `[voice] enabled = true` in `jarvis.toml` and deploy. The panel only
asks for the microphone once the Pi reports voice as on, so the tablet's
permission prompt appears on the first reload after that — grant it there.

Check it came up before going to the wall:

```bash
curl -s localhost:8141/health
# wake_word_available, stt_available and tts_available must all be true. Any one
# false is a model file that isn't where the service is looking, and none of the
# three is loud at runtime: a false wake word never fires, a false STT hears
# nothing, and a false TTS answers in text with silence.
```

**Speaker ID is not wired up yet**, and the panel works without it — an
unrecognised voice is served, just not by name. Two things are missing rather
than one: `/var/lib/jarvis/models/speaker-embedding.onnx`, and a mel front-end
for it. Every ONNX embedding export in the wild (sherpa-onnx's WeSpeaker
builds, pyannote's) takes fbank features, while `SpeakerID.embed()` feeds a raw
waveform. Note also that `jarvis.voice.enroll` records through `arecord` on the
Pi, which is the wrong machine — the microphone is on the tablet — so
enrolment goes through its `--from-dir` flag with WAVs recorded elsewhere.

### DNS

Point `dash.example.com` at the Pi's **LAN** address. Publishing an RFC1918
address in public DNS resolves usefully only inside the house, and a DNS-01
challenge issues the certificate regardless of public reachability. (If you use
a VPN mesh, note the tablet is a LAN device and may not be able to route to it.)

HTTPS here is load-bearing, not cosmetic: `getUserMedia` only works in a secure
context, so over plain `http://` the tablet's microphone is denied with no
useful error and voice is simply dead.

## Tablet setup

Stock Android throughout — every step below is app configuration. No root, no
custom ROM, nothing that a factory reset can't undo.

### 1. Kiosk browser

**Webview Kiosk** — F-Droid, `uk.nktnet.webviewkiosk`, AGPL-3.0. Set the start
URL to your `dash.` host, then:

- **Lock Task Mode (pin)** so the home screen, status bar and other apps are
  unreachable from the wall.
- **Set it as the default launcher.** A reboot then lands straight back on the
  dashboard with no human involved.
- **Protect its settings** with a password or biometrics. Otherwise the first
  guest to prod the wall out of curiosity leaves it on a settings screen.
- **Microphone: only once `[voice] enabled = true`.** With voice off the panel
  never calls `getUserMedia`, so the grant is dead weight. Screen wake comes
  from the wake word, so the camera is never needed either way.
- **Check it reloads after a network drop.** It holds `ACCESS_NETWORK_STATE`
  for exactly this, and the panel's own reconnect logic covers the rest.

Overnight screen blanking is *not* evidently one of its settings — verify before
relying on it, and fall back to Android's bedtime mode if it isn't there.

> Earlier versions of these notes recommended **WallPanel**. That was wrong on
> two counts: it is not on F-Droid (it shipped via Play and GitHub releases),
> and upstream — `thecowan/wallpanel-android`, which `thanksmister/` forks — has
> had no commits since October 2021. Use it only if you already have it running.

### 2. Home Assistant Companion

Needed for one thing: receiving `command_activity` to launch YouTube Music. Skip
it entirely if you don't want the music tile.

F-Droid ships the **minimal** flavour, `io.homeassistant.companion.android.minimal`
— no Play Services, therefore no FCM, so notifications arrive over Home
Assistant's local websocket push instead. For a tablet that never leaves the LAN
that's the better build anyway, but **confirm `command_activity` actually
arrives** before wiring the music tile to it.

Once the tablet registers, read the real notify service name off HA and put it in
`[homeassistant] notify_service`. The value in `jarvis.example.toml` is a guess
at what HA will name your device, and a mismatch makes the music tile silently do
nothing rather than show an error.

### 3. Vendor settings

- **MagicOS 8 will fight you — this is the step people miss.** Settings →
  Battery → *App launch* → set both apps to Manual and enable all three
  (auto-launch, secondary launch, run in background); disable battery
  optimisation. Skip this and the kiosk dies overnight with no error.
- Developer options → *Stay awake while charging*; lock screen off; auto-rotate
  off; auto-update off.
- **Battery:** holding the cell at 100% forever degrades and eventually swells
  it. Put the charger on a timer, and mount it so the back still opens.

## No proprietary dependencies

Everything here is open source: NixOS, Caddy, Home Assistant, openWakeWord, ONNX
Runtime, whisper.cpp, Piper, FastAPI, Preact, SQLite, Grocy, Jellyfin.
Open-Meteo's server is AGPL on open DWD/ECMWF data, and `v6.bvg.transport.rest`
is derhuerst's ISC-licensed `hafas-rest-api`.

**Voice runs entirely on the Pi.** openWakeWord listens, whisper.cpp transcribes,
the intent is matched locally against the providers' own declared phrasings, and
Piper speaks the answer. No key, no quota, no account, and nothing said in this
house is ever transmitted anywhere.

That was not the original design. Voice used to route through Gemini, which did
transcription, intent and a general-knowledge fallback in one call, chosen
because it was the only free option that handled a second language. Reality
settled it: in a single evening of testing, the pinned model was retired for new
API keys and returned 404, its replacement returned 503 under load, a third
silently translated English into German, and the best case that did work took
about nine seconds to answer. A wall panel cannot route around any of those, and
each one arrives as "voice is broken" with nothing to point at.

What that costs, plainly:

- **English only.** The `.en` models are better at English for their size
  because they gave up every other language. A multilingual whisper build is a
  config change and a slower, weaker transcription.
- **No general-knowledge answers.** The cloud call used to catch the long tail —
  "how tall is the Eiffel Tower". Nothing local can, so an utterance matching no
  widget is told so rather than guessed at.

Both were acceptable trades here. Neither is irreversible: `[voice.stt]` still
has a `provider` key, and `backend/jarvis/voice/stt.py` is the only file that
would need a second branch.

## Notes from actually deploying it

Seven things that only showed up on real hardware, kept here because they cost
hours and would cost anyone else the same.

**whisper pads every clip to thirty seconds.** The encoder runs over that whole
window regardless of how much of it holds speech, so "next tram" costs exactly
what half a minute of speech costs: 9s on tiny.en and 27s on base.en, for a
one-second command, on a Pi 4. That alone makes local transcription look
impossible on this hardware, and it is the reason to reach for `--audio-ctx`,
which trims the window — the same 9s drops to 2.9s. Two things surprised me:
the flag is **not** monotonic (384 was *slower* than 512, because too little
context leaves the decoder rambling), and the transcription errors that remain
are ones the intent matcher shrugs off. tiny.en heard "we'll let rain this
evening" and base.en heard "one is the next tram" — both still route correctly,
because the word that carries the routing ("rain", "tram") is the word that
survives.

**A model can be retired out from under a working config.** `gemini-2.5-flash`
was the pinned default and it answers 404 for keys issued after its cutoff —
*"no longer available to new users"* — so voice failed on the very first thing
said to it, on a config that had never been wrong. Worse, the model still
appears in `ListModels`; only `generateContent` refuses. Measured from the Pi,
three calls each on a free key: `3.5-flash` worked but transcribed English into
German, `3.7-flash` returned 503 "high demand" on three of four calls, and
`gemini-flash-latest` — the obvious hedge against retirement — was the least
available of all. Pin a model, and treat "voice stopped working" as a question
about the model before it is a question about the microphone.

**A systemd service does not inherit your shell's PATH.** Piper was installed,
`piper` ran fine over SSH, and the unit still could not find it — services get
systemd's own minimal PATH, not `/run/current-system/sw/bin`. `shutil.which`
returned None, `tts.py` logged one warning and answered in text forever after.
The failure is quiet by design (a missing voice should degrade, not crash), and
quiet is exactly what makes it expensive. Hence `path = [ pkgs.piper-tts ]` on
the unit, and `tts_available` in `/health` so the answer is one curl away.

**EventSource does not always reconnect.** When the server answers non-2xx —
what a dead backend behind a reverse proxy produces — the spec says the browser
fails the connection *permanently*: `readyState` 2, no retry, ever. A panel
relying on built-in retry stays frozen until someone reloads it. Reconnection
here is explicit, with backoff.

**A proxy can hold a dead socket open.** The stream looks connected while
nothing arrives, so the wall keeps showing stale departure times as though they
were live — the worst failure of all, because it looks fine. There's a client
watchdog on server pings. Note the pings must be a real named SSE event: an SSE
*comment* fires nothing in the browser and cannot drive a watchdog.

**IPv6 will bite you on a host that disabled it.** `v6.bvg.transport.rest`
publishes an AAAA record; the Pi had IPv6 off at the kernel. asyncio walks
`getaddrinfo` in order and sat on the unreachable address until the connect
timeout, so exactly one tile failed forever while `curl` to the same URL
returned in 0.3s — curl falls back via Happy Eyeballs, asyncio does not. Hence
`general.force_ipv4`.

**Back-off can outlive the data it's fetching.** A tile with a 30s refresh hit a
600s back-off ceiling that was also its expiry window, so it went dark waiting
to retry long after the network recovered. Back-off is now capped per provider
relative to its own `useful_for`.

## Licence

MIT — see `LICENSE`. The bundled fonts are not MIT: Archivo and IBM Plex Mono
are both SIL Open Font License 1.1, see `frontend/public/fonts/README.md`.
