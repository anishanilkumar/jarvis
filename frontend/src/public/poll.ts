/**
 * The public dashboard's transport: two intervals and a fetch.
 *
 * The wall uses SSE because one Pi pushes to one tablet on one LAN and the
 * stream is cheap to hold open. Here the server is stateless and every visitor
 * is a stranger, so polling is both simpler and the thing the server-side cache
 * was built for — three visitors on one street share one upstream call whether
 * they poll together or not.
 *
 * What is preserved from the wall, deliberately, is the shape of the data. Each
 * response is written into the same per-slug slice the widgets already read, so
 * the honesty rules come along for free: `useful_for` still freezes the
 * countdowns once the numbers can no longer be refreshed, and a failed poll
 * still leaves the last good value in place with an error beside it rather than
 * blanking the tile.
 */

import { effect } from '@preact/signals'

import { connection, state } from '../signals'
import type { Slice } from '../types'
import { decide, type AdviceFacts } from './advice'
import { prefs, type Place } from './place'

/**
 * The wall gets these from /api/config. A stateless server has no config to
 * serve, so they are compiled in — the same values as the [providers.*] blocks
 * in jarvis.example.toml, and the departures one is the load-bearing number:
 * past ten minutes the countdowns freeze and only clock times remain.
 */
const USEFUL_FOR: Record<string, number> = {
  departures: 600,
  weather: 10800,
  rain: 3600,
}

const PERIOD_MS: Record<string, number> = {
  departures: 30_000,
  weather: 600_000,
}

interface WeatherBody {
  weather: unknown
  advice: AdviceFacts
  jacket_below: number
  rain_threshold: number
}

/** The last weather response, kept so the jacket slider can re-decide without
 *  going back to the network. */
let facts: AdviceFacts | null = null

function put(slug: string, data: unknown): void {
  // peek, not .value — this runs inside an effect below, and reading the signal
  // it writes would subscribe the effect to its own output.
  state.value = {
    ...state.peek(),
    [slug]: {
      data,
      // SECONDS, matching /api/state. isExpired, the widgets' `since()` and the
      // staleness stamps all compute `now / 1000 - fetched_at`; milliseconds
      // here would read as data from the year 57000 and nothing would ever
      // expire.
      fetched_at: Date.now() / 1000,
      stale: false,
      error: null,
      failures: 0,
      useful_for: USEFUL_FOR[slug] ?? 0,
    } satisfies Slice,
  }
}

function fail(slug: string, error: string): void {
  const previous = state.peek()[slug]
  state.value = {
    ...state.peek(),
    [slug]: {
      // A failure never removes data. The tile shows the last good value with a
      // timestamp, and goes quiet on its own once that value expires.
      data: previous?.data ?? null,
      fetched_at: previous?.fetched_at ?? null,
      stale: true,
      error,
      failures: (previous?.failures ?? 0) + 1,
      useful_for: USEFUL_FOR[slug] ?? 0,
    },
  }
}

async function get(path: string, place: Place): Promise<any> {
  const query = new URLSearchParams({ lat: String(place.lat), lon: String(place.lon) })
  const response = await fetch(`${path}?${query}`)
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail || `${response.status}`)
  }
  return response.json()
}

export function startPolling(here: Place): () => void {
  let alive = true
  let failures = 0

  const ok = () => {
    failures = 0
    connection.value = 'live'
  }
  const bad = () => {
    failures += 1
    // One blip is a tunnel; two is a genuine outage. Same rule as the wall.
    connection.value = failures >= 2 ? 'offline' : 'reconnecting'
  }

  async function departures(): Promise<void> {
    try {
      put('departures', await get('/api/departures', here))
      ok()
    } catch (error) {
      fail('departures', String((error as Error).message))
      bad()
    }
  }

  async function weather(): Promise<void> {
    try {
      const body: WeatherBody = await get('/api/weather', here)
      put('weather', body.weather)
      facts = body.advice
      // The server's thresholds are defaults, adopted only where the visitor
      // has not expressed a preference of their own.
      put('rain', decide(facts, prefs.value.jacketBelow, prefs.value.rainThreshold))
      ok()
    } catch (error) {
      fail('weather', String((error as Error).message))
      fail('rain', String((error as Error).message))
      bad()
    }
  }

  // Re-decide, no network, whenever the jacket temperature moves.
  const stopEffect = effect(() => {
    const { jacketBelow, rainThreshold } = prefs.value
    if (facts) put('rain', decide(facts, jacketBelow, rainThreshold))
  })

  void departures()
  void weather()
  const timers = [
    self.setInterval(() => alive && void departures(), PERIOD_MS.departures),
    self.setInterval(() => alive && void weather(), PERIOD_MS.weather),
  ]

  // A backgrounded tab does not fire its intervals reliably, and a phone coming
  // back out of a pocket to a frozen board is the exact failure the freezing
  // rule exists to make visible — better to just refresh it.
  const onVisible = () => {
    if (document.visibilityState === 'visible') void departures()
  }
  document.addEventListener('visibilitychange', onVisible)

  return () => {
    alive = false
    timers.forEach((timer) => self.clearInterval(timer))
    document.removeEventListener('visibilitychange', onVisible)
    stopEffect()
    facts = null
  }
}
