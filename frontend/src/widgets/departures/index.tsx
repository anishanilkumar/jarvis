/**
 * The departure board — the panel's dominant instrument.
 *
 * Countdowns are computed here from absolute timestamps, never taken from the
 * server. That's what lets them FREEZE when the tile expires offline: a
 * countdown still ticking down on data we can no longer refresh is actively
 * wrong, and a wall display that lies about your tram is worse than one that
 * admits it doesn't know.
 *
 * Which rows to show is decided here for the same reason, and re-decided on
 * every tick. The board is one missed departure followed by the ones you can
 * still make, and "still make" is a fact about the current minute — as the walk
 * clock runs down, the top of the board falls off and the whole list shifts up
 * on its own. Doing that server-side would freeze it at the last fetch.
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
  /** Catchable rows this board is worth on the ambient tile. */
  rows: number
  departures: Departure[]
  warnings: string[]
}

interface Data {
  boards: Board[]
  warnings: string[]
}

/** Fallback when the backend is a version behind and sends no per-board count. */
const DEFAULT_ROWS = 3

function minutesUntil(iso: string | null, nowMs: number): number | null {
  if (!iso) return null
  return Math.round((new Date(iso).getTime() - nowMs) / 60000)
}

function clockTime(iso: string | null): string {
  if (!iso) return '--:--'
  const when = new Date(iso)
  return `${String(when.getHours()).padStart(2, '0')}:${String(when.getMinutes()).padStart(2, '0')}`
}

/**
 * One departure you've missed, then the ones you haven't.
 *
 * The missed row is the point of the pattern rather than an accident of it: a
 * board that only shows what you can catch gives you no way to tell "the next
 * one is in eleven minutes because they're every eleven minutes" from "the next
 * one is in eleven minutes because you missed one by ninety seconds". One
 * greyed row answers that, and more than one is just a list of trams that were
 * never yours.
 *
 * A cancelled service can never be the missed row — it isn't a near miss, it's
 * a warning — but it does hold its place among the upcoming ones, because the
 * tram you were planning on being cancelled is exactly what you walked over to
 * find out.
 */
function visibleRows(
  departures: Departure[],
  walkMinutes: number,
  nowMs: number,
  rows: number,
  expired: boolean,
): Departure[] {
  // Frozen, so the sorting stops too. Past its useful_for the tile has already
  // given up the countdowns and shows scheduled clock times instead; carrying
  // on quietly dropping rows off the top would empty the board over the
  // evening and leave it reading "nothing scheduled", which is a claim about
  // the timetable when the truth is that we lost the Pi.
  if (expired) return departures.slice(0, rows + 1)

  const missed: Departure[] = []
  const upcoming: Departure[] = []

  for (const departure of departures) {
    const minutes = minutesUntil(departure.when ?? departure.planned, nowMs)
    if (minutes === null) continue
    if (minutes >= walkMinutes) upcoming.push(departure)
    else if (!departure.cancelled) missed.push(departure)
  }

  // The last one out of reach, not the first: the near miss is the one that
  // just slipped past the walk, not one from twenty minutes ago.
  const nearMiss = missed.length > 0 ? [missed[missed.length - 1]] : []
  return [...nearMiss, ...upcoming.slice(0, rows)]
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
  const catchable = !departure.cancelled && minutes !== null && minutes >= walkMinutes

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
  departures,
  expired,
  nowMs,
  weight,
}: {
  board: Board
  departures: Departure[]
  expired: boolean
  nowMs: number
  /** Share of the tile's height, so boards of unequal length get equal rows. */
  weight: number
}) {
  return (
    <div class="dep-board" style={{ flexGrow: weight }}>
      <div class="spread dep-board-head">
        <span class="label">
          {board.name}
          {board.toward && <span class="dep-toward"> → {board.toward}</span>}
        </span>
        <span class="stamp">{board.walk_minutes} min walk</span>
      </div>

      {departures.length === 0 ? (
        <div class="dep-none label">nothing scheduled</div>
      ) : (
        <ul class="dep-list">
          {departures.map((departure) => (
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

  const shown = boards.map((board) => ({
    board,
    rows: visibleRows(
      board.departures,
      board.walk_minutes,
      nowMs,
      board.rows ?? DEFAULT_ROWS,
      expired,
    ),
  }))

  return (
    <div class="stack fill">
      <div class="dep-boards fill" data-boards={boards.length}>
        {shown.map(({ board, rows }) => (
          <BoardBlock
            key={board.name || board.stop}
            board={board}
            departures={rows}
            expired={expired}
            nowMs={nowMs}
            // The tile's height is fixed and the boards are not the same
            // length, so they take height in proportion to the rows they
            // carry. Splitting it evenly instead would set the four tram rows
            // at half the size of the two U-Bahn ones.
            weight={Math.max(1, rows.length)}
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

/**
 * Tapped: the timetable, unfiltered.
 *
 * The card is an answer to "should I leave now", so it hides what it would be
 * dishonest to offer. Standing in front of the panel you're asking a different
 * question — when do these actually run — and the walk you can't make in the
 * next four minutes has no bearing on it. Every departure the stop reported,
 * greyed where it's out of reach but never dropped.
 */
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
            departures={board.departures}
            expired={expired}
            nowMs={nowMs}
            weight={Math.max(1, board.departures.length)}
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
