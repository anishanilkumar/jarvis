/**
 * Time, date and the ends of the day.
 *
 * Not the wall's clock widget, which imports the voice client for its reactor
 * dial — reusing it would pull the whole microphone pipeline into a bundle
 * that must not have one. This is the same information without that.
 *
 * The clock earns its place on a page of countdowns: "in 4 minutes" is only
 * checkable against a time the page also shows, and a frozen board is much
 * easier to spot beside a second hand that is still moving.
 */

import { now } from '../signals'
import './timesun.css'

interface Sun {
  sunrise: string
  sunset: string
}

const clock = (date: Date) =>
  date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })

export function TimeSun({ sun }: { sun: Sun | null }) {
  const at = new Date(now.value)
  const rise = sun ? new Date(sun.sunrise) : null
  const set = sun ? new Date(sun.sunset) : null
  const dark = !!(rise && set) && (at < rise || at > set)

  return (
    <div class="timesun">
      <div class="timesun-clock">
        <span class="readout">{clock(at)}</span>
        <span class="label muted">
          {at.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })}
        </span>
      </div>
      {sun && (
        <div class="timesun-sun">
          {/* The next one first: before dawn and after dusk the useful number
              is sunrise, and in between it is sunset. */}
          <span class="stamp" data-next={!dark || undefined}>
            ↑ {clock(rise!)}
          </span>
          <span class="stamp" data-next={dark || undefined}>
            ↓ {clock(set!)}
          </span>
        </div>
      )}
    </div>
  )
}
