/**
 * The things worth tuning, and the link that reproduces this view.
 *
 * The jacket temperature is the interesting one. It is applied in the browser,
 * not on the server — the API returns the coldest hour you have left today and
 * this decides what that means — so dragging it re-answers immediately, with no
 * request and no wait, and it keeps working with the network off.
 */

import { useState } from 'preact/hooks'

import { state } from '../signals'
import type { Data as DepartureData } from '../widgets/departures'
import { forget, fromLink, hide, place, prefs, savePlace, savePrefs, shareUrl, show } from './place'
import './settings.css'

/**
 * What is hidden from the departures tile, and the way back.
 *
 * Directions are hidden from the opened tile, on the row itself, because that
 * is where you are looking when one turns out to be useless. This is the other
 * half: the full list, including stops that never earned a board and so have no
 * row there to tap.
 */
function DepartureHides() {
  const data = state.value.departures?.data as DepartureData | null | undefined
  const hides = prefs.value.hides
  if (!data) return null

  const stops = data.stops ?? []
  const hidden = data.hidden ?? []
  if (stops.length === 0 && hides.length === 0) return null

  // Hides this address answers with nothing: a stop near somewhere else, or a
  // bus that is not running this hour. A token the current data issued is not
  // one of them — it was hidden a moment ago and the refetch is on its way.
  //
  // Only counted on the primary source. The fallback's stop ids are different
  // ones, so there every hide looks idle, and offering to forget them would be
  // offering to lose them all.
  const applied = new Set(hidden.map((entry) => entry.token))
  const issued = new Set([
    ...stops.map((stop) => stop.hide),
    ...data.boards.flatMap((board) => (board.routes ?? []).map((route) => route.hide)),
  ])
  const primary = (data.sources ?? []).every((name) => name === 'bvg')
  const idle = primary
    ? hides.filter((token) => !applied.has(token) && !issued.has(token))
    : []

  return (
    <div class="settings-row">
      <span class="settings-label">
        Departures
        <span class="settings-hint">
          Tap a stop to hide it, and the next one out takes its place. Hide a
          direction from the opened departures tile, under Customise.
        </span>
      </span>
      <div class="settings-hides">
        {stops.length > 0 && (
          <div class="settings-chips">
            {stops.map((stop) => (
              <button
                key={stop.id}
                type="button"
                class="settings-chip"
                aria-pressed={!stop.hidden}
                aria-label={`Show ${stop.name} on the board`}
                onClick={() => (stop.hidden ? show(stop.hide) : hide(stop.hide))}
              >
                {stop.name}
                <span class="settings-chip-walk">{stop.walk_minutes} min</span>
              </button>
            ))}
          </div>
        )}
        {hidden
          .filter((entry) => entry.kind === 'direction')
          .map((entry) => (
            <div key={entry.token} class="settings-hidden">
              <span>{entry.label}</span>
              <button type="button" onClick={() => show(entry.token)}>
                Show
              </button>
            </div>
          ))}
        {idle.length > 0 && (
          <div class="settings-hidden">
            <span class="settings-hint">
              {idle.length} more hidden, matching nothing near here right now
            </span>
            <button type="button" onClick={() => show(...idle)}>
              Forget
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export function Settings({ onClose }: { onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const current = prefs.value

  async function copy() {
    try {
      await navigator.clipboard.writeText(shareUrl())
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      // No clipboard permission, or an insecure context. The input below holds
      // the same text and can be selected by hand.
    }
  }

  return (
    <div class="settings">
      <div class="spread settings-head">
        <span class="label">Settings</span>
        <button type="button" class="settings-close" onClick={onClose}>
          Done
        </button>
      </div>

      <label class="settings-row">
        <span class="settings-label">
          Jacket below
          <span class="settings-hint">
            Apparent temperature — it already accounts for wind and humidity,
            which is what a jacket answers.
          </span>
        </span>
        <span class="settings-control">
          <input
            type="range"
            min={5}
            max={25}
            step={1}
            value={current.jacketBelow}
            onInput={(event) =>
              savePrefs({
                ...current,
                jacketBelow: Number((event.target as HTMLInputElement).value),
              })
            }
          />
          <output class="settings-value">{current.jacketBelow}°</output>
        </span>
      </label>

      <label class="settings-row">
        <span class="settings-label">
          Umbrella at
          <span class="settings-hint">Chance of rain in the hours you have left today.</span>
        </span>
        <span class="settings-control">
          <input
            type="range"
            min={10}
            max={90}
            step={5}
            value={current.rainThreshold}
            onInput={(event) =>
              savePrefs({
                ...current,
                rainThreshold: Number((event.target as HTMLInputElement).value),
              })
            }
          />
          <output class="settings-value">{current.rainThreshold}%</output>
        </span>
      </label>

      <DepartureHides />

      <div class="settings-row">
        <span class="settings-label">
          This view
          <span class="settings-hint">
            Everything is in the link, so it opens straight onto this dashboard
            on any device.
          </span>
        </span>
        <span class="settings-control settings-share">
          <input class="settings-url" readOnly value={shareUrl()} onFocus={(e) => (e.target as HTMLInputElement).select()} />
          <button type="button" onClick={copy}>
            {copied ? 'Copied' : 'Copy'}
          </button>
        </span>
      </div>

      <div class="settings-row settings-place">
        <span class="settings-label">
          {place.value?.name}
          {fromLink.value && (
            <span class="settings-hint">
              Opened from a link. Your own saved address, if you have one, is
              untouched.
            </span>
          )}
        </span>
        <span class="settings-control">
          {fromLink.value && place.value && (
            <button type="button" onClick={() => savePlace(place.value!)}>
              Save as mine
            </button>
          )}
          <button type="button" onClick={forget}>
            Change address
          </button>
        </span>
      </div>
    </div>
  )
}
