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

import { computed, effect } from '@preact/signals'

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
  /** Set only when every upstream failed and the server fell back to its
   *  last good answer. Seconds. */
  stale_seconds?: number
}

/** The last weather response, kept so the jacket slider can re-decide without
 *  going back to the network. */
let facts: AdviceFacts | null = null

/**
 * `age` is how old the server admitted the payload already was.
 *
 * The server serves its last good answer when every upstream is down, and says
 * how stale it is. Backdating `fetched_at` by that much is the whole of the
 * handling: every honesty rule the panel has is computed from that one number,
 * so the countdowns freeze on time and the staleness stamps read true without
 * a single widget learning that server-side staleness exists.
 */
function put(slug: string, data: unknown, age = 0): void {
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
      fetched_at: Date.now() / 1000 - age,
      stale: age > 0,
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

/**
 * The server answered, and the answer was an error.
 *
 * Worth its own type because it is the opposite of being offline, and the two
 * were being counted as the same thing. `/api/departures` returns 502 with a
 * reason when the dashboard is up and BVG is not — an answer, delivered over a
 * working connection — and treating that as a lost link put the whole page
 * into the offline palette and had the departures tile reporting "no
 * connection" to a phone whose connection was fine and whose weather was
 * arriving on time.
 */
class Upstream extends Error {}

async function get(path: string, place: Place, hides: string[] = []): Promise<any> {
  const query = new URLSearchParams({ lat: String(place.lat), lon: String(place.lon) })
  for (const token of hides) query.append('hide', token)
  // A fetch that never lands throws on its own, and that throw is the only
  // real offline signal here.
  const response = await fetch(`${path}?${query}`)
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Upstream(detail?.detail || `${response.status}`)
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

  /**
   * What a failed poll says about the LINK, which is not what it says about
   * the data. An answered request proves the link even when the answer is a
   * 502, so the connection counts as good and the failure stays where it
   * belongs — on the one slice, as `slice.error`, which is what the tile reads
   * to say "bvg not answering" instead of blaming the reader's phone.
   */
  const noted = (error: unknown) => (error instanceof Upstream ? ok() : bad())

  /** Bumped per departures request. An answer overtaken by a newer request —
   *  one asked with the hide just tapped — is dropped rather than drawn over
   *  it, which would bring the hidden row back until the next poll. */
  let asked = 0

  async function departures(): Promise<void> {
    const mine = ++asked
    try {
      const body = await get('/api/departures', here, prefs.peek().hides)
      if (mine !== asked) return
      put('departures', body, Number(body?.stale_seconds) || 0)
      ok()
    } catch (error) {
      if (mine !== asked) return
      fail('departures', String((error as Error).message))
      noted(error)
    }
  }

  async function weather(): Promise<void> {
    try {
      const body: WeatherBody = await get('/api/weather', here)
      const age = Number(body.stale_seconds) || 0
      put('weather', body.weather, age)
      facts = body.advice
      // The server's thresholds are defaults, adopted only where the visitor
      // has not expressed a preference of their own.
      put('rain', decide(facts, prefs.value.jacketBelow, prefs.value.rainThreshold), age)
      ok()
    } catch (error) {
      fail('weather', String((error as Error).message))
      fail('rain', String((error as Error).message))
      noted(error)
    }
  }

  // Re-decide, no network, whenever the jacket temperature moves — and only
  // then. Reading the whole of prefs would re-run this on every hide too, and
  // each run re-stamps the rain tile as just fetched: tapping Hide would quietly
  // un-freeze advice from a weather feed that has been down for hours.
  const thresholds = computed(() => `${prefs.value.jacketBelow}/${prefs.value.rainThreshold}`)
  const stopEffect = effect(() => {
    void thresholds.value
    const { jacketBelow, rainThreshold } = prefs.peek()
    if (facts) put('rain', decide(facts, jacketBelow, rainThreshold))
  })

  // Hides change what the server composes, so a changed one is a new request —
  // against a warm cache, so it lands about as fast as a re-render would. The
  // effect's first run is the subscription rather than a change; the initial
  // fetch below already carries the hides.
  const hideKey = computed(() => prefs.value.hides.join('\n'))
  let lastHides = hideKey.peek()
  const stopHides = effect(() => {
    const key = hideKey.value
    if (key === lastHides) return
    lastHides = key
    void departures()
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
    stopHides()
    facts = null
  }
}
