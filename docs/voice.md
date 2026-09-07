# Voice

openWakeWord listens, whisper.cpp transcribes, the intent is matched locally
against the providers' own declared phrasings, and Piper speaks the answer. All
of it on the Pi. No key, no quota, no account, and nothing said in this house is
ever transmitted anywhere.

Getting the model files onto the Pi is in [wall.md](wall.md).

## How an utterance becomes an answer

The wake word fires on the tablet's microphone; the segment goes up the
WebSocket; whisper transcribes it; `backend/jarvis/voice/intent.py` matches the
text against every `intents` list the providers declare, weighting each word by
how few providers use it. So the routing table is not a file anyone maintains —
it is the phrasings each widget ships with, which is why a new tile is speakable
the moment it says how people would ask for it.

An utterance matching no widget is told so, rather than guessed at.

## That was not the original design

Voice used to route through Gemini, which did transcription, intent and a
general-knowledge fallback in one call, chosen because it was the only free
option that handled a second language. Reality settled it: in a single evening
of testing, the pinned model was retired for new API keys and returned 404, its
replacement returned 503 under load, a third silently translated English into
German, and the best case that did work took about nine seconds to answer. A
wall panel cannot route around any of those, and each one arrives as "voice is
broken" with nothing to point at.

What going local costs, plainly:

- **English only.** The `.en` models are better at English for their size
  because they gave up every other language. A multilingual whisper build is a
  config change and a slower, weaker transcription.
- **No general-knowledge answers.** The cloud call used to catch the long tail —
  "how tall is the Eiffel Tower". Nothing local can, so an utterance matching no
  widget is told so rather than guessed at.

Both were acceptable trades here. Neither is irreversible: `[voice.stt]` still
has a `provider` key, and `backend/jarvis/voice/stt.py` is the only file that
would need a second branch.

## Tuning it

- `wake_threshold` — raise toward 0.7 if it triggers off the TV, lower toward
  0.4 if it misses you.
- `silence_timeout_ms` — how long a gap ends a command. It is elapsed time since
  audio last arrived, not a count of polling ticks; see the first of the
  [deployment notes](deployment-notes.md) for why that distinction cost an
  evening.
- `model` under `[voice.stt]` — `tiny.en` by default, `base.en` if it mishears
  you. The measurements are in [wall.md](wall.md).
- `audio_context` — how much of whisper's thirty-second window it actually
  encodes, and the single biggest lever on how fast an answer comes back. It is
  not monotonic: lower is not always faster. See the second
  [deployment note](deployment-notes.md).
- `threads` — three of the Pi's four cores. The fourth is left for the wall.
- `tts_voice` — any Piper voice you have fetched.
