/**
 * The one question the dashboard asks.
 *
 * Address, not stop. Nobody knows the id of the tram stop on their corner, and
 * asking for a stop pushes the walking time — which is the whole basis of "can
 * you still make it" — onto someone who has no way to measure it. An address
 * the server can find stops around answers both.
 *
 * Berlin-only is enforced on the server, on coordinates, so this screen's job
 * is to say so kindly rather than to be the check.
 */

import { useEffect, useRef, useState } from 'preact/hooks'

import { savePlace, type Place } from './place'
import './setup.css'

interface Hit {
  name: string
  district: string
  postcode: string
  lat: number
  lon: number
}

const DEBOUNCE_MS = 250

/** Why a lookup failed, to the extent we actually know.
 *
 *  'upstream'  the server reached the address service and it did not answer
 *  'throttled' we asked too fast; ours to fix, not theirs
 *  'unknown'   the request never got an answer at all — could be anything,
 *              most likely the reader's own connection
 */
export type Failure = 'upstream' | 'throttled' | 'unknown'

export class LookupError extends Error {
  constructor(readonly why: Failure) {
    super(why)
  }
}

export async function lookup(query: string): Promise<Hit[]> {
  let response: Response
  try {
    response = await fetch(`/api/geocode?q=${encodeURIComponent(query)}`)
  } catch {
    // fetch itself rejected: no response, so nothing is known about the far end.
    throw new LookupError('unknown')
  }
  if (response.status === 429) throw new LookupError('throttled')
  if (response.status === 502) throw new LookupError('upstream')
  if (!response.ok) throw new LookupError('unknown')
  const body = await response.json()
  return body.results as Hit[]
}

const normalise = (text: string) =>
  text.toLowerCase().replace(/[.,]/g, '').replace(/\s+/g, ' ').trim()

/**
 * Whether a `?q=` link can go straight to the dashboard.
 *
 * A single hit obviously qualifies. So does a first hit whose name IS what was
 * typed — the search is fuzzy, so "Boxhagener Str. 1" comes back with four
 * unrelated streets ending in 1 behind it, and making that ambiguous would
 * mean a shared `?q=` link always stops at a picker and the shortcut never
 * fires.
 *
 * Anything short of a literal match still stops. Guessing between two real
 * streets is how someone gets shown the wrong tram.
 */
export function unambiguous(query: string, hits: Hit[]): Hit | null {
  if (hits.length === 1) return hits[0]
  if (hits.length && normalise(hits[0].name) === normalise(query)) return hits[0]
  return null
}

export function placeOf(hit: Hit): Place {
  return {
    lat: hit.lat,
    lon: hit.lon,
    name: hit.district ? `${hit.name}, ${hit.district}` : hit.name,
  }
}

export function Setup({ initial = '' }: { initial?: string }) {
  const [query, setQuery] = useState(initial)
  const [hits, setHits] = useState<Hit[]>([])
  const [cursor, setCursor] = useState(0)
  const [status, setStatus] = useState<'idle' | 'searching' | 'empty' | Failure>('idle')
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => input.current?.focus(), [])

  useEffect(() => {
    const text = query.trim()
    if (text.length < 3) {
      setHits([])
      setStatus('idle')
      return
    }
    setStatus('searching')
    // Debounced because this types a character at a time into somebody else's
    // API. The server caches on the query string, so the repeats a fast typist
    // generates cost nothing after the first.
    const timer = setTimeout(async () => {
      try {
        const found = await lookup(text)
        setHits(found)
        setCursor(0)
        setStatus(found.length ? 'idle' : 'empty')
      } catch (error) {
        setHits([])
        setStatus(error instanceof LookupError ? error.why : 'unknown')
      }
    }, DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [query])

  function keys(event: KeyboardEvent) {
    if (!hits.length) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setCursor((c) => Math.min(hits.length - 1, c + 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setCursor((c) => Math.max(0, c - 1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      savePlace(placeOf(hits[cursor]))
    }
  }

  return (
    <div class="setup">
      <div class="setup-card">
        <h1 class="setup-title">Berlin, from your doorstep</h1>
        <p class="setup-blurb">
          The weather, whether to take a jacket or an umbrella, and the next
          departures from the stops nearest you. Type your address — it stays in
          this browser and is never sent anywhere but the lookup.
        </p>

        <input
          ref={input}
          class="setup-input"
          type="text"
          autocomplete="off"
          spellcheck={false}
          placeholder="Street and number"
          value={query}
          onInput={(event) => setQuery((event.target as HTMLInputElement).value)}
          onKeyDown={keys}
        />

        {status === 'searching' && <p class="setup-note">Looking…</p>}
        {status === 'empty' && (
          <p class="setup-note">
            Nothing in Berlin matches that. Berlin only, for now.
          </p>
        )}
        {/* Each of these says what was observed and stops there. The earlier
            version of this message named BVG and told the reader the outage was
            almost certainly not our fault — a cause the page had not
            established, since the catch discarded the status code before
            guessing at it, and an excuse nobody waiting for a tram asked for. */}
        {status === 'upstream' && (
          <p class="setup-note">The address service isn't answering. Try again in a few minutes.</p>
        )}
        {status === 'throttled' && (
          <p class="setup-note">Too many lookups just now. Give it a moment.</p>
        )}
        {status === 'unknown' && (
          <p class="setup-note">Couldn't reach the address lookup.</p>
        )}

        {hits.length > 0 && (
          <ul class="setup-hits" role="listbox">
            {hits.map((hit, index) => (
              <li key={`${hit.lat},${hit.lon}`}>
                <button
                  type="button"
                  class="setup-hit"
                  data-active={index === cursor || undefined}
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => savePlace(placeOf(hit))}
                >
                  <span class="setup-hit-name">{hit.name}</span>
                  <span class="setup-hit-where">
                    {hit.district} {hit.postcode}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
