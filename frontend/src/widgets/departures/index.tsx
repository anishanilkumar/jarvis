/**
 * The departure board — the panel's dominant instrument.
 *
 * Countdowns are computed here from absolute timestamps, never taken from the
 * server. That's what lets them FREEZE when the tile expires offline: a
 * countdown still ticking down on data we can no longer refresh is actively
 * wrong, and a wall display that lies about your tram is worse than one that
 * admits it doesn't know.
 *
 * The unit is a ROUTE — one line heading one way — laid out as a strip: line,
 * destination, then the next several countdowns along the row. A board that
 * spends one row per departure spends two of its four columns repeating a line
 * number and a destination you read once, and at a stop with a dozen routes it
 * takes twelve rows to tell you about three of them. Four numbers on one row
 * say when the next one goes AND how often they run, which is most of what you
 * came to the wall to find out.
 *
 * Which routes and which numbers is decided here, and re-decided on every tick.
 * A departure you can no longer walk to is not a departure, and "can no longer"
 * is a fact about the current minute — as the walk clock runs down the leading
 * number greys out and the strip shifts left on its own. Doing that server-side
 * would freeze it at the last fetch.
 */

import { now } from '../../signals'
import type { Widget, WidgetProps } from '../../types'
import './departures.css'

interface Departure {
  trip_id: string
  line: string
  product: string
  direction: string
  /** The direction cut to wall length by the provider. */
  destination: string
  when: string | null
  planned: string | null
  delay_minutes: number
  cancelled: boolean
  catchable: boolean
  platform: string | null
}

interface Route {
  line: string
  product: string
  destination: string
  departures: Departure[]
}

interface Board {
  name: string
  stop: string
  walk_minutes: number
  /** Route strips this board is worth on the ambient tile. */
  rows: number
  /** Countdowns along each strip. */
  route_length: number
  /** How the provider ordered `routes`, and how to pick when more than `rows`. */
  order: 'listed' | 'soonest' | 'line'
  routes?: Route[]
  departures: Departure[]
  warnings: string[]
}

interface Data {
  boards: Board[]
  warnings: string[]
}

/** Fallbacks for when the backend is a version behind and omits a field. */
const DEFAULT_ROWS = 3
const DEFAULT_ROUTE_LENGTH = 3

function minutesUntil(iso: string | null, nowMs: number): number | null {
  if (!iso) return null
  return Math.round((new Date(iso).getTime() - nowMs) / 60000)
}

function departureMinutes(departure: Departure, nowMs: number): number | null {
  return minutesUntil(departure.when ?? departure.planned, nowMs)
}

function clockTime(iso: string | null): string {
  if (!iso) return '--:--'
  const when = new Date(iso)
  return `${String(when.getHours()).padStart(2, '0')}:${String(when.getMinutes()).padStart(2, '0')}`
}

/**
 * One departure you've missed, then the ones you haven't.
 *
 * The missed one is the point of the pattern rather than an accident of it: a
 * strip that only counts what you can catch gives you no way to tell "the next
 * one is in eleven minutes because they're every eleven minutes" from "the next
 * one is in eleven minutes because you missed one by ninety seconds". One
 * greyed number answers that, and more than one is just a list of trains that
 * were never yours.
 *
 * A cancelled service can never be the missed one — it isn't a near miss, it's
 * a warning — but it does hold its place among the upcoming ones, because the
 * train you were planning on being cancelled is exactly what you walked over to
 * find out.
 */
function stripTimes(
  route: Route,
  board: Board,
  nowMs: number,
  expired: boolean,
): { missed: Departure | null; upcoming: Departure[] } {
  const length = board.route_length ?? DEFAULT_ROUTE_LENGTH

  // Frozen, so the filtering stops too. Past its useful_for the tile has
  // already given up the countdowns and shows scheduled clock times instead;
  // carrying on quietly dropping numbers off the left would empty the strip
  // over the evening and leave the row reading "nothing scheduled", which is a
  // claim about the timetable when the truth is that we lost the Pi.
  if (expired) return { missed: null, upcoming: route.departures.slice(0, length) }

  const missed: Departure[] = []
  const upcoming: Departure[] = []

  for (const departure of route.departures) {
    const minutes = departureMinutes(departure, nowMs)
    if (minutes === null) continue
    if (minutes >= board.walk_minutes) upcoming.push(departure)
    else if (!departure.cancelled) missed.push(departure)
  }

  return {
    // The last one out of reach, not the first: the near miss is the one that
    // just slipped past the walk, not one from twenty minutes ago.
    missed: missed.length > 0 ? missed[missed.length - 1] : null,
    upcoming: upcoming.slice(0, length),
  }
}

/** Minutes to the first one you can still make; Infinity if there isn't one. */
function nextCatchable(route: Route, board: Board, nowMs: number): number {
  for (const departure of route.departures) {
    const minutes = departureMinutes(departure, nowMs)
    if (minutes !== null && minutes >= board.walk_minutes && !departure.cancelled) {
      return minutes
    }
  }
  return Infinity
}

/**
 * The routes that fit, and in what order.
 *
 * "listed" and "line" both arrive already ordered by the provider and are taken
 * as they come — for a stop whose lines go to genuinely different places, where
 * sorting by departure time silently drops a whole direction the moment its
 * train is a few minutes further out. "soonest" is for a stop whose lines are
 * alternatives to each other, like five bus routes off one corner, where the
 * row is worth giving to whatever leaves next; that one is re-sorted here on
 * every tick, because which route leaves next is a fact about this minute.
 */
function visibleRoutes(board: Board, nowMs: number, expired: boolean): Route[] {
  const routes = board.routes ?? []
  const rows = board.rows ?? DEFAULT_ROWS
  if (board.order !== 'soonest' || expired) return routes.slice(0, rows)

  return [...routes]
    .sort((a, b) => nextCatchable(a, board, nowMs) - nextCatchable(b, board, nowMs))
    .slice(0, rows)
}

function Time({
  departure,
  lead,
  missed,
  expired,
  nowMs,
}: {
  departure: Departure
  /** The first one you can make: the number the row exists to show. */
  lead: boolean
  missed: boolean
  expired: boolean
  nowMs: number
}) {
  const minutes = departureMinutes(departure, nowMs)

  if (departure.cancelled) {
    return <li class="rt rt-cancelled">{expired ? clockTime(departure.when ?? departure.planned) : minutes}</li>
  }
  if (expired || minutes === null) {
    /* Frozen: the scheduled time is still true, the countdown isn't. */
    return <li class="rt rt-frozen">{clockTime(departure.when ?? departure.planned)}</li>
  }
  return (
    <li class="rt" data-lead={lead} data-missed={missed} data-late={departure.delay_minutes > 0}>
      {Math.max(0, minutes)}
    </li>
  )
}

function RouteStrip({
  route,
  board,
  expired,
  nowMs,
}: {
  route: Route
  board: Board
  expired: boolean
  nowMs: number
}) {
  const { missed, upcoming } = stripTimes(route, board, nowMs, expired)

  return (
    <li class="route" data-product={route.product}>
      <span class="route-line">{route.line}</span>
      <span class="route-dest">{route.destination}</span>
      <ol class="route-times">
        {missed && (
          <Time departure={missed} lead={false} missed expired={expired} nowMs={nowMs} />
        )}
        {upcoming.map((departure, index) => (
          <Time
            key={departure.trip_id}
            departure={departure}
            lead={index === 0}
            missed={false}
            expired={expired}
            nowMs={nowMs}
          />
        ))}
        {/* The route runs, but not within the hour we asked about. Said, not
            hidden: an empty southbound is itself the answer to "should I go
            now", and a row that vanishes looks like a stop that closed. */}
        {!missed && upcoming.length === 0 && <li class="rt rt-none">—</li>}
      </ol>
    </li>
  )
}

function BoardBlock({
  board,
  routes,
  expired,
  nowMs,
  weight,
}: {
  board: Board
  routes: Route[]
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
          {board.stop && board.stop !== board.name && (
            <span class="dep-stop"> · {board.stop}</span>
          )}
        </span>
        <span class="stamp">{board.walk_minutes} min walk</span>
      </div>

      {routes.length === 0 ? (
        <div class="dep-none label">nothing scheduled</div>
      ) : (
        <ul class="route-list">
          {routes.map((route) => (
            <RouteStrip
              key={`${route.line}/${route.destination}`}
              route={route}
              board={board}
              expired={expired}
              nowMs={nowMs}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

function since(fetchedAt: number | null, nowMs: number): string {
  if (fetchedAt === null) return 'never'
  const minutes = Math.floor(Math.max(0, nowMs / 1000 - fetchedAt) / 60)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min`
  return `${Math.floor(minutes / 60)}h`
}

/**
 * Whether the numbers above can be believed, and whose fault it is if not.
 *
 * The panel has two upstreams and they fail independently: the tablet reaching
 * the Pi, and the Pi reaching BVG. Both used to surface as the same quiet "last
 * sync 15 minutes ago", which tells you something is wrong and nothing about
 * what — and the second is far the more common, since a public transit API goes
 * down more often than the Wi-Fi in one flat.
 *
 * A live feed says so rather than showing nothing, because "no news" and "the
 * status line is broken too" look identical when the only signal is absence.
 */
type FeedState = 'live' | 'degraded' | 'frozen' | 'offline'

/**
 * How bad it is, which is what decides how loudly the strip below says it.
 *
 * One missed poll on a 30-second tile is noise, so "live" holds until the
 * failures are consistent enough to mean something. Defaulting an absent count
 * to 2 is the version-skew case: a backend predating the counter sends none at
 * all, and reading that as a single blip would leave the tile claiming "live"
 * through an outage it can plainly see an error for.
 */
function feedState(
  slice: WidgetProps<Data>['slice'],
  expired: boolean,
  offline: boolean,
): FeedState {
  if (offline) return 'offline'
  if (expired) return 'frozen'
  return slice.error !== null && (slice.failures ?? 2) >= 2 ? 'degraded' : 'live'
}

function FeedStatus({
  slice,
  expired,
  offline,
  nowMs,
}: {
  slice: WidgetProps<Data>['slice']
  expired: boolean
  offline: boolean
  nowMs: number
}) {
  const state = feedState(slice, expired, offline)

  // Offline names the Pi rather than BVG. With the Pi unreachable, whatever we
  // last heard about its upstream is itself stale, so saying anything about the
  // feed would be guessing — and the palette has already desaturated the whole
  // panel, which is the standing signal that this is the link and not the data.
  if (state === 'offline') {
    return (
      <span class="label dep-feed" data-state="offline">
        <span class="dep-dot" />
        no link to jarvis · {since(slice.fetched_at, nowMs)} · times are scheduled
      </span>
    )
  }

  if (state === 'live') {
    return (
      <span class="label dep-feed" data-state="live">
        <span class="dep-dot" />
        bvg live
      </span>
    )
  }

  // Carrying its own age, unlike the quiet states. This line is meant to be the
  // one thing you read when the board stops making sense, and a self-contained
  // sentence beats making you find the small print underneath it.
  return (
    <span class="label dep-feed" data-state={state}>
      <span class="dep-dot" />
      bvg not answering · {since(slice.fetched_at, nowMs)}
      {state === 'frozen' && ' · times are scheduled'}
    </span>
  )
}

function Card({ slice, expired, offline = false }: WidgetProps<Data>) {
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
    routes: visibleRoutes(board, nowMs, expired),
  }))

  return (
    <div class="stack fill">
      <div class="dep-boards fill" data-boards={boards.length}>
        {shown.map(({ board, routes }) => (
          <BoardBlock
            key={board.name || board.stop}
            board={board}
            routes={routes}
            expired={expired}
            nowMs={nowMs}
            // The tile's height is fixed and the boards are not the same
            // length, so they take height in proportion to the rows they
            // carry. Splitting it evenly instead would set an eight-route
            // board's rows at the size of a two-route board's.
            //
            // The +1 is the board's own header, and leaving it out is not a
            // rounding error: a board's share was sized for its rows and then
            // asked to fit a header too, so the shortest board — where the
            // header is the largest fraction — lost its last row off the
            // bottom. Counting the header as a row's worth makes one row the
            // same height on every board, which is what this was always for.
            weight={routes.length + 1}
          />
        ))}
      </div>

      <div class="spread dep-status" data-state={feedState(slice, expired, offline)}>
        <FeedStatus slice={slice} expired={expired} offline={offline} nowMs={nowMs} />
        {data.warnings.length > 0 && (
          <span class="dep-warning label">{data.warnings.length} disruption notice(s)</span>
        )}
      </div>
    </div>
  )
}

/**
 * Tapped: the timetable, unfiltered.
 *
 * The card is an answer to "should I leave now", so it hides what it would be
 * dishonest to offer — the routes that didn't fit, and the departures you can't
 * walk to. Standing in front of the panel you're asking a different question —
 * when do these actually run — and every route the stop reported is here, at
 * full depth, with the ones out of reach greyed rather than dropped.
 */
function Detail({ slice, expired }: WidgetProps<Data>) {
  const data = slice.data
  const nowMs = now.value
  const boards = data?.boards ?? []
  if (!data || boards.length === 0) return <div class="void">no departures</div>

  return (
    <div class="stack fill">
      <div class="dep-boards dep-boards-full fill" data-boards={boards.length}>
        {boards.map((board) => {
          const routes = board.routes ?? []
          return (
            <BoardBlock
              key={board.name || board.stop}
              // Every number the provider kept, not the handful the wall shows.
              board={{ ...board, route_length: 99, rows: routes.length }}
              routes={routes}
              expired={expired}
              nowMs={nowMs}
              weight={routes.length + 1}
            />
          )
        })}
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
  // Half the wall. The headline tile took the two cells this grew into: on a
  // panel you read in glances, four stops' worth of live countdowns earn that
  // space and a rotating news excerpt did not.
  size: { w: 2, h: 3 },
  Card,
  Detail,
} satisfies Widget
