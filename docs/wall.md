# Setting up the wall

One-time work on the Pi. The panel itself needs none of it — weather and
departures come up with no credentials at all — so do this in the order below
and stop wherever you have enough.

## Clone and configure

```bash
git clone git@github.com:<you>/jarvis.git ~/jarvis
cp jarvis.example.toml jarvis.toml   # then edit: stop id, coordinates, hosts
```

Find a stop id with:

```bash
curl 'https://v6.bvg.transport.rest/locations?query=<name>'
```

## Secrets

Placeholders are committed; the real keys go in the environment, never in
`jarvis.toml`:

```
GROCY_API_KEY=...  HA_TOKEN=...
```

On NixOS, agenix. Anywhere else, a root-owned `EnvironmentFile`. Voice needs no
key — speech recognition runs on this machine.

## The voice service

On NixOS both services are declarative and there is nothing to do here:
`nix/jarvis-dashboard.nix` builds it, including the one package missing from
nixpkgs (`nix/pkgs/openwakeword.nix`). Do **not** reach for a venv on NixOS —
without `programs.nix-ld` there is no dynamic loader at `/lib`, so pip's
manylinux wheels for numpy and onnxruntime cannot execute at all.

Anywhere else, the venv is the normal path:

```bash
python -m venv ~/.venv/jarvis-voice
~/.venv/jarvis-voice/bin/pip install -e ~/jarvis/backend[voice]
```

## Model files

Three sets, none of which download themselves usefully.

**Wake word.** openWakeWord fetches these itself on first use, into its own
package directory — which is read-only when the interpreter comes from the nix
store, and which fails at the first frame of audio rather than at startup.
Fetch them by hand and Jarvis passes them in by path.

```bash
mkdir -p /var/lib/jarvis/openwakeword && cd /var/lib/jarvis/openwakeword
oww=https://github.com/dscripka/openWakeWord/releases/download/v0.5.1
curl -LO $oww/melspectrogram.onnx
curl -LO $oww/embedding_model.onnx
curl -LO $oww/hey_jarvis_v0.1.onnx      # or your own model, named hey_jarvis*
```

**Piper voice**, for text to speech:

```bash
mkdir -p /var/lib/jarvis/piper && cd /var/lib/jarvis/piper
voice=https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium
curl -LO $voice/en_GB-alba-medium.onnx
curl -LO $voice/en_GB-alba-medium.onnx.json
```

**whisper.cpp**, for speech to text. `tiny.en` is the default: measured on a Pi
4 it answers a spoken command in 2.9s against `base.en`'s 6.2s, and the errors
it does make are the kind the intent matcher survives. Fetch `base.en` instead
— and set `model` in `jarvis.toml` — if it mishears you too often.

```bash
mkdir -p /var/lib/jarvis/whisper && cd /var/lib/jarvis/whisper
curl -LO https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin
```

Then flip `[voice] enabled = true` in `jarvis.toml` and deploy. The panel only
asks for the microphone once the Pi reports voice as on, so the tablet's
permission prompt appears on the first reload after that — grant it there.

## Check it came up, before going to the wall

```bash
curl -s localhost:8141/health
```

`wake_word_available`, `stt_available` and `tts_available` must all be true.
Any one false is a model file that isn't where the service is looking, and none
of the three is loud at runtime: a false wake word never fires, a false STT
hears nothing, and a false TTS answers in text with silence.

## Speaker ID is not wired up yet

The panel works without it — an unrecognised voice is served, just not by name.
Two things are missing rather than one:
`/var/lib/jarvis/models/speaker-embedding.onnx`, and a mel front-end for it.
Every ONNX embedding export in the wild (sherpa-onnx's WeSpeaker builds,
pyannote's) takes fbank features, while `SpeakerID.embed()` feeds a raw
waveform.

Note also that `jarvis.voice.enroll` records through `arecord` on the Pi, which
is the wrong machine — the microphone is on the tablet — so enrolment goes
through its `--from-dir` flag with WAVs recorded elsewhere.

Speaker ID is identification among a small enrolled set, not security. A
recording defeats it, so nothing that spends money or unlocks a door is ever
gated on it.

## DNS, and why HTTPS is load-bearing

Point `dash.example.com` at the Pi's **LAN** address. Publishing an RFC1918
address in public DNS resolves usefully only inside the house, and a DNS-01
challenge issues the certificate regardless of public reachability. (If you use
a VPN mesh, note the tablet is a LAN device and may not be able to route to it.)

HTTPS here is not cosmetic: `getUserMedia` only works in a secure context, so
over plain `http://` the tablet's microphone is denied with no useful error and
voice is simply dead.

## Deploy options

```bash
JARVIS_HOST=you@yourpi ./deploy.sh
```

The previous config is kept on the Pi as `jarvis.toml.bak-<timestamp>`. Set
`JARVIS_SKIP_CONFIG=1` to leave the Pi's config alone; `JARVIS_REPO` and
`JARVIS_WEB_ROOT` override the paths.
