/**
 * The panel's connection to the Pi.
 *
 * Three channels, deliberately different:
 *   GET  /api/state          first paint, and the fallback when the stream dies
 *   GET  /api/stream         SSE — every data update, pushed
 *   POST /api/action/<slug>  touch writes
 *
 * Updates use SSE rather than a WebSocket because they are strictly
 * one-directional and EventSource reconnects by itself after a Wi-Fi drop or a
 * Pi restart. That reconnect logic is the part people hand-write and get
 * subtly wrong; here it's the platform's problem.
 */

import { signal, computed } from '@preact/signals'
import { loadState, saveState } from './offline'
import type { Connection, PanelConfig, PanelState } from './types'

export const state = signal<PanelState>({})
export const config = signal<PanelConfig | null>(null)
export const connection = signal<Connection>('reconnecting')
export const expanded = signal<string | null>(null)

/** Ticks once a second so countdowns and staleness stamps recompute. */
export const now = signal<number>(Date.now())
setInterval(() => (now.value = Date.now()), 1000)

export const isOffline = computed(() => connection.value === 'offline')

/**
 * Reconnection is ours to own, not the browser's.
 *
 * Two failure modes were measured against a stopped backend, and neither is
 * handled by EventSource on its own:
 *
 *   1. When the server answers with a non-2xx — exactly what a dead Pi behind
 *      a reverse proxy produces — the spec says the browser *fails the
 *      connection permanently*. readyState goes to CLOSED (2) and it never
 *      retries. A panel relying on built-in retry stays frozen forever.
 *   2. A proxy can hold the socket open after the origin dies. The stream
 *      looks connected while no data arrives, so the wall keeps showing stale
 *      departure times as though they were live — the worst outcome of all.
 *
 * So: explicit reconnect with backoff for (1), and a watchdog on server pings
 * for (2).
 */
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30000
/** No traffic for this long means the link is dead, whatever readyState says.
 *  The server pings every 10s, so this is three missed beats. */
const SILENCE_LIMIT_MS = 32000
const WATCHDOG_TICK_MS = 4000

let failures = 0
let source: EventSource | null = null
let reconnectTimer: number | undefined
let lastMessageAt = 0

function merge(partial: PanelState): void {
  state.value = { ...state.value, ...partial }
  void saveState(state.value)
}

/** Paint from the last known state before the network is even consulted. */
export async function hydrate(): Promise<void> {
  const cached = await loadState()
  if (cached && Object.keys(state.value).length === 0) {
    state.value = cached
  }
}

async function fetchConfig(): Promise<void> {
  try {
    const response = await fetch('/api/config')
    if (response.ok) config.value = await response.json()
  } catch {
    // Config is cached by the service worker; an old copy beats no panel.
  }
}

/** First paint, racing the stream.
 *
 * The stream does send a full snapshot on connect, so this is redundant on a
 * good day. It is not redundant the first time a device runs a new bundle:
 * there is no cached state to hydrate from, and until that first SSE event
 * lands every tile reads "waiting for data". Anything that delays it — a
 * proxy buffering the response, a WebView holding the first chunk — leaves
 * the wall blank with a perfectly healthy Pi three metres away.
 *
 * Whichever arrives first wins; `merge` makes the loser a no-op.
 */
async function fetchState(): Promise<void> {
  try {
    const response = await fetch('/api/state')
    if (response.ok) merge(await response.json())
  } catch {
    // The stream is the primary path. If both fail we're genuinely offline,
    // which the watchdog and the error handler already say out loud.
  }
}

function alive(): void {
  lastMessageAt = Date.now()
  failures = 0
  connection.value = 'live'
}

function scheduleReconnect(): void {
  if (reconnectTimer !== undefined) return
  const delay = Math.min(RECONNECT_BASE_MS * 2 ** failures, RECONNECT_MAX_MS)
  reconnectTimer = self.setTimeout(() => {
    reconnectTimer = undefined
    connect()
  }, delay)
}

export function connect(): void {
  source?.close()
  lastMessageAt = Date.now()
  // Snapshot now, stream from here on. Also covers the reconnect case: after a
  // dropped connection the tiles are as stale as the outage was long, and
  // waiting for the next push to correct them shows old times for no reason.
  void fetchState()
  source = new EventSource('/api/stream')

  source.addEventListener('open', alive)
  source.addEventListener('ping', alive)

  source.addEventListener('state', (event) => {
    alive()
    merge(JSON.parse((event as MessageEvent).data))
  })

  source.addEventListener('error', () => {
    failures += 1
    // A single blip during a Pi restart shouldn't make the wall announce a
    // failure; a second one means it's really gone.
    connection.value = failures >= 2 ? 'offline' : 'reconnecting'
    if (source?.readyState === EventSource.CLOSED) scheduleReconnect()
  })
}

/** Catches the silent-but-open case the error handler never hears about. */
function startWatchdog(): void {
  self.setInterval(() => {
    if (Date.now() - lastMessageAt <= SILENCE_LIMIT_MS) return
    failures += 1
    connection.value = 'offline'
    source?.close()
    scheduleReconnect()
  }, WATCHDOG_TICK_MS)
}

/** A touch write. Deliberately not optimistic: on a shared wall panel, showing
 *  a change that silently failed is worse than a moment's latency. */
export async function act(slug: string, payload: Record<string, unknown>): Promise<void> {
  const response = await fetch(`/api/action/${slug}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(`${slug} action failed: ${response.status}`)
}

export async function start(): Promise<void> {
  await hydrate()
  void fetchConfig()
  connect()
  startWatchdog()
}
