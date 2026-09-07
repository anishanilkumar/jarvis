/**
 * The public dashboard.
 *
 * Three widgets from the wall, rendered by the same components against the
 * same slice shape, arranged for a phone instead of a 1920x1200 tablet bolted
 * to a wall. The wall's own layout is untouched and not imported: it is a fixed
 * 4x3 grid, correct for the one screen it was drawn for and wrong for every
 * other.
 *
 * The widget modules are imported one by one rather than through widgets/index,
 * which globs the directory — that would pull in the clock and music widgets,
 * and with them the voice client and the whole microphone pipeline. This page
 * has no audio, and the surest way to keep it that way is for the code never to
 * be in the bundle.
 */

import { useState } from 'preact/hooks'

import { connection, now, state } from '../signals'
import { isExpired } from '../expiry'
import type { Slice } from '../types'
import departures from '../widgets/departures'
import rain from '../widgets/rain'
import weather from '../widgets/weather'
import { place, kiosk } from './place'
import { Settings } from './settings'
import { TimeSun } from './timesun'
import '../styles/interior.css'

const WIDGETS = [departures, rain, weather]

/** Nothing here writes; the wall's touch actions have no counterpart. */
const noAction = async () => {}

function emptySlice(): Slice {
  return { data: null, fetched_at: null, stale: true, error: null, useful_for: 0 }
}

export function Dashboard() {
  const [settingsOpen, setSettings] = useState(false)
  const panelState = state.value
  const nowMs = now.value
  const offline = connection.value === 'offline'
  const sun = (panelState.weather?.data as any)?.today ?? null

  return (
    <div class="site">
      <header class="site-head">
        <TimeSun sun={sun} />
        <div class="spread site-where">
          <span class="label">{place.value?.name}</span>
          {!kiosk.value && (
            <button
              type="button"
              class="site-gear"
              aria-expanded={settingsOpen}
              onClick={() => setSettings((open) => !open)}
            >
              {settingsOpen ? 'Close' : 'Settings'}
            </button>
          )}
        </div>
      </header>

      {settingsOpen && <Settings onClose={() => setSettings(false)} />}

      <main class="site-grid">
        {WIDGETS.map((widget) => {
          const slice = panelState[widget.slug] ?? emptySlice()
          // The honesty rule, unchanged from the wall: past its useful_for the
          // tile goes quiet rather than showing a number that is no longer
          // true. For departures that means the countdowns stop counting and
          // only the scheduled clock times remain.
          const expired = isExpired(slice.fetched_at, slice.useful_for, nowMs)
          return (
            <section
              key={widget.slug}
              class="instrument"
              data-slug={widget.slug}
              data-expired={expired}
            >
              <widget.Card slice={slice} expired={expired} offline={offline} act={noAction} />
            </section>
          )
        })}
      </main>

      <footer class="site-foot stamp">
        Berlin only, for now · departures from{' '}
        <a href="https://v6.bvg.transport.rest">v6.bvg.transport.rest</a> · weather from{' '}
        <a href="https://open-meteo.com">Open-Meteo</a>
      </footer>
    </div>
  )
}
