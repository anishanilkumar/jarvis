# Notes from actually deploying it

Eight things that only showed up on real hardware, kept here because they cost
hours and would cost anyone else the same.

**A silence timeout counted in ticks is a timeout on the speaker.** Voice
truncated every command at about two seconds, and it presented as the recogniser
failing on an Indian accent — the transcripts were "what is the", "How hard",
and once just the wake word itself. Neither the model nor the accent was
involved. The server polled the socket with an 80ms timeout and treated each
expiry as a frame of silence, but the tablet's `ScriptProcessor(2048)` at 16kHz
sends a chunk only every 128ms, so *every ordinary gap between chunks* scored as
silence — and nothing reset the counter when audio arrived. It reached its limit
mid-sentence no matter how continuously you spoke. Silence is now elapsed time
since audio last arrived, which is both correct and immune to the buffer size
changing. The general lesson is worth more than the fix: when a pipeline ends in
a model, a plumbing bug upstream will be blamed on the model, and "it does not
understand me" is a claim to verify against the raw input before believing.

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
