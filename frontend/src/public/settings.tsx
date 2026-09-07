/**
 * The two things worth tuning, and the link that reproduces this view.
 *
 * The jacket temperature is the interesting one. It is applied in the browser,
 * not on the server — the API returns the coldest hour you have left today and
 * this decides what that means — so dragging it re-answers immediately, with no
 * request and no wait, and it keeps working with the network off.
 */

import { useState } from 'preact/hooks'

import { forget, place, prefs, savePlace, savePrefs, shareUrl, fromLink } from './place'
import './settings.css'

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
