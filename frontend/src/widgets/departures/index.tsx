/**
 * The departure board — the panel's dominant instrument.
 *
 * Countdowns are computed here from absolute timestamps, never taken from the
 * server. That's what lets them FREEZE when the tile expires offline: a
 * countdown still ticking down on data we can no longer refresh is actively
 * wrong, and a wall display that lies about your tram is worse than one that
 * admits it doesn't know.
 *
 * Boards stack: the stop you walk to, then the connection you change onto.
 * Reading down the tile is reading the journey in order.
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

interface Board {
  name: string
  stop: string
  toward: string
  walk_minutes: number
  departures: Departure[]
  warnings: string[]
}

interface Data {
  boards: Board[]
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

function Row({
  departure,
  walkMinutes,
  expired,
  nowMs,
}: {
  departure: Departure
  walkMinutes: number
  expired: boolean
  nowMs: number
}) {
  const minutes = minutesUntil(departure.when ?? departure.planned, nowMs)
  // Derived here, not read off the server's flag, for the same reason the
  // countdown is: the Pi computed `catchable` when it fetched, and a tram that
  // was reachable then stops being reachable while the tile sits on the wall.
  // Trusting the stale flag leaves a departure lit up as catchable minutes
  // after it stopped being so.
  const catchable =
    !departure.cancelled && minutes !== null && minutes >= walkMinutes

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

function BoardBlock({
  board,
  rows,
  expired,
  nowMs,
}: {
  board: Board
  rows: number
  expired: boolean
  nowMs: number
}) {
  return (
    <div class="dep-board">
      <div class="spread dep-board-head">
        <span class="label">
          {board.name}
          {board.toward && <span class="dep-toward"> → {board.toward}</span>}
        </span>
        <span class="stamp">{board.walk_minutes} min walk</span>
      </div>

      {board.departures.length === 0 ? (
        <div class="dep-none label">nothing scheduled</div>
      ) : (
        <ul class="dep-list">
          {board.departures.slice(0, rows).map((departure) => (
            <Row
              key={departure.trip_id}
              departure={departure}
              walkMinutes={board.walk_minutes}
              expired={expired}
              nowMs={nowMs}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

function Card({ slice, expired }: WidgetProps<Data>) {
  const data = slice.data
  const nowMs = now.value

  // `boards` is defaulted rather than assumed. A panel is deployed as static
  // files and the backend is deployed separately, so the two can be a version
  // apart for a minute or two; reading .map off an older payload's missing key
  // would take down the whole panel, not just this tile.
  const boards = data?.boards ?? []

  if (!data || boards.length === 0) {
    return <div class="void">{slice.error ? 'no departures' : 'waiting for data'}</div>
  }

  // The tile height is fixed, so rows are divided between boards rather than
  // added. Two boards of three beats one board of six that pushes the second
  // stop off the bottom edge.
  const rows = boards.length > 1 ? 3 : 6

  return (
    <div class="stack fill">
      <div class="dep-boards fill" data-boards={boards.length}>
        {boards.map((board) => (
          <BoardBlock
            key={board.name || board.stop}
            board={board}
            rows={rows}
            expired={expired}
            nowMs={nowMs}
          />
        ))}
      </div>

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
  const boards = data?.boards ?? []
  if (!data || boards.length === 0) return <div class="void">no departures</div>

  return (
    <div class="stack fill">
      <div class="dep-boards dep-boards-full fill" data-boards={boards.length}>
        {boards.map((board) => (
          <BoardBlock
            key={board.name || board.stop}
            board={board}
            rows={99}
            expired={expired}
            nowMs={nowMs}
          />
        ))}
      </div>

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
