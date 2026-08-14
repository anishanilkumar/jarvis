/**
 * The instrument panel.
 *
 * A 4x3 grid rather than equal cards, because hierarchy is information:
 * departures dominates (it's the only tile you act on within seconds), the
 * reactor and the sky sit beside it, and the household strip runs quietly
 * underneath.
 *
 * Navigation is one piece of state — `expanded` — and an idle timer.
 */

import { useEffect } from 'preact/hooks'
import { act, config, connection, expanded, now, state } from './state'
import { isExpired } from './offline'
import { widgets, bySlug } from './widgets'
import type { Slice } from './types'
import './layout.css'

const DEFAULT_IDLE_RETURN = 60

/** A widget whose provider hasn't reported yet still renders, saying so. */
function emptySlice(): Slice {
  return { data: null, fetched_at: null, stale: true, error: null, useful_for: 0 }
}

function ago(fetchedAt: number | null, nowMs: number): string {
  if (fetchedAt === null) return 'no data'
  const seconds = Math.max(0, Math.floor(nowMs / 1000 - fetchedAt))
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  return `${Math.floor(minutes / 60)}h ago`
}

export function Panel() {
  const offline = connection.value === 'offline'
  const panelState = state.value
  const nowMs = now.value

  // Return to the ambient grid after inactivity, so the panel is never left
  // showing someone else's expanded detail view.
  useEffect(() => {
    if (expanded.value === null) return
    const seconds = config.value?.general?.idle_return_seconds ?? DEFAULT_IDLE_RETURN
    const timer = setTimeout(() => (expanded.value = null), seconds * 1000)
    return () => clearTimeout(timer)
  }, [expanded.value, nowMs > 0])

  const focused = expanded.value ? bySlug.get(expanded.value) : undefined

  if (focused?.Detail) {
    const slice = panelState[focused.slug] ?? emptySlice()
    return (
      <div class="detail-wrap" onClick={() => (expanded.value = null)}>
        <div class="detail instrument">
          <header class="detail-head">
            <span class="label">{focused.slug}</span>
            <span class="stamp">
              {offline ? `signal lost · last sync ${ago(slice.fetched_at, nowMs)}` : 'live'}
            </span>
          </header>
          <focused.Detail
            slice={slice}
            expired={isExpired(slice.fetched_at, slice.useful_for, nowMs)}
            act={(payload) => act(focused.slug, payload)}
          />
        </div>
      </div>
    )
  }

  return (
    <div class="panel">
      {widgets.map((widget) => {
        const slice = panelState[widget.slug] ?? emptySlice()
        // Expiry only bites while we're offline. When the Pi is reachable, its
        // own `stale` flag is the authority and the data is as fresh as it gets.
        const expired = offline && isExpired(slice.fetched_at, slice.useful_for, nowMs)

        return (
          <section
            key={widget.slug}
            class="instrument"
            data-slug={widget.slug}
            data-expired={expired}
            style={{ gridArea: `span ${widget.size.h} / span ${widget.size.w}` }}
            onClick={() => widget.Detail && (expanded.value = widget.slug)}
          >
            <widget.Card
              slice={slice}
              expired={expired}
              act={(payload) => act(widget.slug, payload)}
            />
            {(offline || slice.stale) && slice.fetched_at !== null && (
              <div class="tile-stamp stamp">last sync {ago(slice.fetched_at, nowMs)}</div>
            )}
          </section>
        )
      })}
    </div>
  )
}
