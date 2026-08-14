/**
 * The departure board — the panel's dominant instrument.
 *
 * Countdowns are computed here from absolute timestamps, never taken from the
 * server. That's what lets them FREEZE when the tile expires offline: a
 * countdown still ticking down on data we can no longer refresh is actively
 * wrong, and a wall display that lies about your tram is worse than one that
 * admits it doesn't know.
 */

import { now } from '../../state'
import type { Widget, WidgetProps } from '../../types'
import './departures.css'

interface Departure {
  trip_id: string
  line: string
  product: string
  direction: string
  when: string | null
  planned: string | null
  delay_minutes: number
  cancelled: boolean
  catchable: boolean
  platform: string | null
}

interface Data {
  stop: string
  walk_minutes: number
  departures: Departure[]
  warnings: string[]
}

function minutesUntil(iso: string | null, nowMs: number): number | null {
  if (!iso) return null
  return Math.round((new Date(iso).getTime() - nowMs) / 60000)
}

function clockTime(iso: string | null): string {
  if (!iso) return '--:--'
  const when = new Date(iso)
  return `${String(when.getHours()).padStart(2, '0')}:${String(when.getMinutes()).padStart(2, '0')}`
}

function Row({ departure, expired, nowMs }: { departure: Departure; expired: boolean; nowMs: number }) {
  const minutes = minutesUntil(departure.when ?? departure.planned, nowMs)
  const gone = minutes !== null && minutes < 0
  const catchable = departure.catchable && !gone

  return (
    <li
      class="dep"
      data-cancelled={departure.cancelled}
      data-catchable={catchable}
      data-product={departure.product}
    >
      <span class="dep-line">{departure.line}</span>
      <span class="dep-dir">{departure.direction}</span>

      {departure.delay_minutes > 0 && !departure.cancelled && (
        <span class="dep-delay">+{departure.delay_minutes}</span>
      )}

      {departure.cancelled ? (
        <span class="dep-when cancelled">cancelled</span>
      ) : expired || minutes === null ? (
        /* Frozen: the scheduled time is still true, the countdown isn't. */
        <span class="dep-when frozen">{clockTime(departure.when ?? departure.planned)}</span>
      ) : (
        <span class="dep-when">
          <span class="dep-min">{Math.max(0, minutes)}</span>
          <span class="dep-unit">min</span>
        </span>
      )}
    </li>
  )
}

function Card({ slice, expired }: WidgetProps<Data>) {
  const data = slice.data
  const nowMs = now.value

  if (!data) {
    return <div class="void">{slice.error ? 'no departures' : 'waiting for data'}</div>
  }

  return (
    <div class="stack fill">
      <div class="spread">
        <span class="label">{data.stop}</span>
        <span class="stamp">{data.walk_minutes} min walk</span>
      </div>

      <ul class="dep-list fill">
        {data.departures.slice(0, 6).map((departure) => (
          <Row key={departure.trip_id} departure={departure} expired={expired} nowMs={nowMs} />
        ))}
      </ul>

      {expired && <div class="label frozen-note">No live data · times are scheduled</div>}
      {!expired && data.warnings.length > 0 && (
        <div class="dep-warning label">{data.warnings.length} disruption notice(s)</div>
      )}
    </div>
  )
}

function Detail({ slice, expired }: WidgetProps<Data>) {
  const data = slice.data
  const nowMs = now.value
  if (!data) return <div class="void">no departures</div>

  return (
    <div class="stack fill">
      <ul class="dep-list dep-list-full fill">
        {data.departures.map((departure) => (
          <Row key={departure.trip_id} departure={departure} expired={expired} nowMs={nowMs} />
        ))}
      </ul>

      {data.warnings.length > 0 && (
        <div class="dep-warnings">
          <div class="label">Disruptions</div>
          {data.warnings.map((warning) => (
            <p key={warning} class="body muted">
              {warning}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

export default {
  slug: 'departures',
  size: { w: 2, h: 2 },
  Card,
  Detail,
} satisfies Widget
