/**
 * Time and date, at the top of the page.
 *
 * Not the wall's clock widget, which imports the voice client for its reactor
 * dial — reusing it would pull the whole microphone pipeline into a bundle
 * that must not have one. This is the same information without that.
 *
 * The clock earns its place on a page of countdowns: "in 4 minutes" is only
 * checkable against a time the page also shows, and a frozen board is much
 * easier to spot beside a clock that is still moving.
 *
 * Sunrise and sunset used to sit beside it here, as ↑ 06:34 and ↓ 19:52. They
 * live in the weather tile now, spelled out — two bare arrows in a header are a
 * convention you either already know or are left to guess at, and the tile that
 * is already about the sky is where someone would look for them.
 */

import { now } from '../signals'
import './clock.css'

export function Clock() {
  const at = new Date(now.value)

  return (
    <div class="clock">
      <span class="readout">
        {at.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
      </span>
      <span class="label muted">
        {at.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })}
      </span>
    </div>
  )
}
