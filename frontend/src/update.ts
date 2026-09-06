/**
 * Notice when a new panel build has shipped, and reload into it.
 *
 * The wall tablet is a kiosk browser that opens the page once and then never
 * navigates again. Nothing about a deploy reaches it: the SSE stream reconnects
 * to the new backend within seconds, so *data* and *config* changes land
 * immediately — a tile switched off really does disappear — while the JavaScript
 * rendering it stays whatever was loaded weeks ago. The failure is quiet and
 * looks like a bug in the panel rather than a stale build, which is exactly how
 * this tablet once sat two builds behind the Pi it was talking to.
 *
 * The check is against what the server actually serves rather than a version
 * the backend claims, because the backend does not build the frontend and any
 * number it reported would be a second thing to keep in sync. `index.html`
 * names the content-hashed bundle; this module knows its own URL. If those
 * disagree, the panel is running code the server has stopped serving.
 */

import { effect } from '@preact/signals'
import { connection, expanded } from './state'
import { voice } from './voice'

/** Slow, because the reconnect hook below is what actually catches a deploy. */
const CHECK_INTERVAL_MS = 5 * 60_000

/** Survives the reload it triggers, which is what stops a reload loop. */
const ATTEMPTED_KEY = 'jarvis:update-attempted'

/**
 * This module's own URL. In a production build that is the content-hashed
 * bundle the panel is currently executing, which is precisely the question.
 */
function runningBundle(): string | null {
  try {
    return new URL(import.meta.url).pathname
  } catch {
    return null
  }
}

async function servedBundle(): Promise<string | null> {
  // no-store, or the service worker's own cached copy answers and the panel
  // cheerfully confirms it is running the build it is already running.
  const response = await fetch('/index.html', { cache: 'no-store' })
  if (!response.ok) return null
  const match = /<script[^>]+src="(\/assets\/[^"]+\.js)"/.exec(await response.text())
  return match?.[1] ?? null
}

/**
 * A reload is cheap on an ambient grid and rude in the middle of something.
 * Nothing here is urgent enough to interrupt a person standing at the panel.
 */
function safeToReload(): boolean {
  return expanded.value === null && !voice.value.listening
}

async function check(): Promise<void> {
  if (!safeToReload()) return

  const running = runningBundle()
  let served: string | null = null
  try {
    served = await servedBundle()
  } catch {
    // Pi unreachable. Never reload on a failed check: offline, the service
    // worker would serve the cached shell and we would learn nothing, having
    // thrown away a panel full of still-useful cached data to find out.
    return
  }

  if (!running || !served || running === served) return

  // We already reloaded once aiming at this exact bundle and are somehow still
  // not running it — a cache we can't see past, or a proxy serving two
  // versions. Stop. A wall stuck one build behind is a nuisance; a wall
  // reloading every five minutes forever is unusable.
  if (sessionStorage.getItem(ATTEMPTED_KEY) === served) return

  try {
    sessionStorage.setItem(ATTEMPTED_KEY, served)
  } catch {
    // Private mode or storage disabled: the loop guard is gone, so don't.
    return
  }
  location.reload()
}

export function watchForUpdates(): void {
  // Dev serves an unhashed module and rebuilds in place; HMR is the update
  // mechanism there and this would fight it.
  if (import.meta.env.DEV) return

  // A deploy always restarts the backend, so the stream dropping and coming
  // back is the strongest available hint that the files behind it changed too.
  // This is what makes the wall current within seconds of a deploy rather than
  // within the interval below.
  effect(() => {
    if (connection.value === 'live') void check()
  })

  setInterval(() => void check(), CHECK_INTERVAL_MS)
}
