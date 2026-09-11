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

import { useState } from 'preact/hooks'

import { now } from '../../signals'
import type { Customise, Widget, WidgetProps } from '../../types'
import { ModeGlyph } from './mode'
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
  /** Set only on a pooled board, where each row is a different stop's walk. */
  walk_minutes?: number
  /** The stop this route was pooled from. Shown in the expanded view only. */
  stop?: string
  /** The token that hides this route's direction. Public site only. */
  hide?: string
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
  /** Several stops' routes on one board, each row carrying its own walk. */
  pooled?: boolean
  /** The token that hides this stop. Absent on the pooled block, which is
   *  several stops, and on the wall, which has no hiding. */
  hide?: string
  routes?: Route[]
  departures: Departure[]
  warnings: string[]
}

/** A nearby stop, board or not, as the public settings screen lists it. */
export interface StopChoice {
  id: string
  name: string
  walk_minutes: number
  hide: string
  hidden: boolean
}

/** A hide the server applied, and what to call it. */
export interface Hidden {
  token: string
  kind: 'stop' | 'direction'
  label: string
}

export interface Data {
  boards: Board[]
  warnings: string[]
  /** Which upstreams actually answered. Absent on an older backend, which had
   *  only one and therefore nothing to distinguish. */
  sources?: string[]
  /** Every stop the public site looked at, hidden or not. */
  stops?: StopChoice[]
  /** What this visitor's hides took off the board. Absent on the wall. */
  hidden?: Hidden[]
}

/** Fallbacks for when the backend is a version behind and omits a field. */
const DEFAULT_ROWS = 3
const DEFAULT_ROUTE_LENGTH = 3

/** The source that carries disruption remarks. The other one does not. */
const PRIMARY = 'bvg'

/**
 * Whether this board came from somewhere other than the primary.
 *
 * Worth saying out loud rather than treating as an implementation detail. The
 * fallback has no disruption feed at all, so on it an empty `warnings` means
 * "nobody told us" where on the primary it means "nothing is wrong" — and a
 * board that quietly stops mentioning disruptions, while looking exactly as it
 * always does, is the most expensive silence this panel could keep.
 *
 * An older backend sends no `sources` at all, which is not a fallback: it is a
 * backend from before there was one.
 */
function fallbackSources(data: Data | null): string[] {
  return (data?.sources ?? []).filter((name) => name !== PRIMARY)
}

function minutesUntil(iso: string | null, nowMs: number): number | null {
  if (!iso) return null
  return Math.round((new Date(iso).getTime() - nowMs) / 60000)
}

function departureMinutes(departure: Departure, nowMs: number): number | null {
  return minutesUntil(departure.when ?? departure.planned, nowMs)
}

/**
 * How long it takes to reach THIS route, which is no longer a fact about the
 * board.
 *
 * The pooled bus block is several corners at once, so the walk moved onto the
 * route and the board's own number became a fallback for the rows that haven't
 * got one — an older backend's, or a board that really is one stop. Getting
 * this wrong is not cosmetic: the walk is the threshold that decides which
 * departures are still catchable, so a row using the block's shortest walk
 * would count down to buses you cannot reach.
 */
function routeWalk(route: Route, board: Board): number {
  return route.walk_minutes ?? board.walk_minutes
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

  const walk = routeWalk(route, board)
  for (const departure of route.departures) {
    const minutes = departureMinutes(departure, nowMs)
    if (minutes === null) continue
    if (minutes >= walk) upcoming.push(departure)
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
  const walk = routeWalk(route, board)
  for (const departure of route.departures) {
    const minutes = departureMinutes(departure, nowMs)
    if (minutes !== null && minutes >= walk && !departure.cancelled) {
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
  onHide,
}: {
  route: Route
  board: Board
  expired: boolean
  nowMs: number
  /** Set while customising: the times give their column to a Hide button. */
  onHide?: (token: string) => void
}) {
  const { missed, upcoming } = stripTimes(route, board, nowMs, expired)
  const token = route.hide
  const hideThis = onHide && token ? () => onHide(token) : null

  return (
    <li class="route" data-product={route.product}>
      {/* The mark sits inside the line column rather than getting one of its
          own. It says what the line IS, so it reads as part of the name — and
          a separate column would be a second thing to scan down for a fact you
          want at the moment you read "M19", not two columns earlier. */}
      <span class="route-line">
        <ModeGlyph product={route.product} />
        {route.line}
      </span>
      <span class="route-dest">{route.destination}</span>
      {/* Only on the pooled block, where the rows are different corners and
          the header can no longer say how far away any of them is. Rendered
          from the board's flag rather than from `route.walk_minutes` being
          present, so the column exists on every row or on none — one row
          silently wider than its neighbours is worse than a repeated number. */}
      {board.pooled && (
        <span class="route-walk stamp">
          {route.stop && <span class="route-stop">{route.stop} · </span>}
          {routeWalk(route, board)} min
        </span>
      )}
      {hideThis ? (
        <button
          type="button"
          class="dep-hide"
          aria-label={`Hide ${route.line} towards ${route.destination}`}
          onClick={hideThis}
        >
          Hide
        </button>
      ) : (
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
      )}
    </li>
  )
}

function BoardBlock({
  board,
  routes,
  expired,
  nowMs,
  weight,
  onHide,
}: {
  board: Board
  routes: Route[]
  expired: boolean
  nowMs: number
  /** Share of the tile's height, so boards of unequal length get equal rows. */
  weight: number
  /** Set while customising. */
  onHide?: (token: string) => void
}) {
  const token = board.hide

  return (
    <div class="dep-board" data-pooled={board.pooled || undefined} style={{ flexGrow: weight }}>
      <div class="spread dep-board-head">
        <span class="label">
          {board.name}
          {board.stop && board.stop !== board.name && (
            <span class="dep-stop"> · {board.stop}</span>
          )}
        </span>
        {/* The pooled block has no one walk to print. Its rows carry their own,
            and a single number in the header would be a claim about all of
            them. It has no one stop to hide either: its corners are hidden
            from settings, where every stop is listed. */}
        {!board.pooled &&
          (onHide && token ? (
            <button
              type="button"
              class="dep-hide"
              aria-label={`Hide the stop ${board.name}`}
              onClick={() => onHide(token)}
            >
              Hide stop
            </button>
          ) : (
            <span class="stamp">{board.walk_minutes} min walk</span>
          ))}
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
              onHide={onHide}
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

  // Offline names the link rather than BVG. With the server unreachable,
  // whatever we last heard about its upstream is itself stale, so saying
  // anything about the feed would be guessing — and the palette has already
  // desaturated the whole panel, which is the standing signal that this is the
  // link and not the data.
  //
  // Worded without naming the Pi, because this component also draws on the
  // public dashboard, where "jarvis" means nothing to the reader and the broken
  // link is far more likely to be their own phone's.
  if (state === 'offline') {
    return (
      <span class="label dep-feed" data-state="offline">
        <span class="dep-dot" />
        no connection · {since(slice.fetched_at, nowMs)} · times are scheduled
      </span>
    )
  }

  if (state === 'live') {
    const backup = fallbackSources(slice.data)
    return (
      <span class="label dep-feed" data-state="live" data-backup={backup.length > 0 || undefined}>
        <span class="dep-dot" />
        {backup.length > 0 ? `via ${backup.join(' + ')}` : 'bvg live'}
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

/**
 * The tile with nothing on it, saying which nothing.
 *
 * "No departures" used to cover four unrelated situations and was the wrong
 * sentence for three of them. It reads as a claim about the TIMETABLE — this
 * stop has nothing running — when far more often it means nobody answered when
 * we asked. Through a BVG outage the wall sat quietly telling the household
 * there were no trams, which is the same lie the frozen countdowns exist to
 * prevent, just told in words instead of numbers.
 *
 * The reason is worked out here rather than taken from feedState(), which is
 * written for a board that has times on it and is wrong twice over for a tile
 * that has none: it reports "frozen" for a slice that has simply never been
 * fetched (isExpired treats a null timestamp as expired), and it extends the
 * one-blip grace that stops a populated board crying wolf over a single missed
 * poll — a grace that protects nothing when there is nothing on screen, and
 * would caption an empty tile "bvg live".
 */
function Empty({
  slice,
  offline,
  nowMs,
  /** The server answered and had no stops to give — the one real "nothing". */
  answered,
  hidden = 0,
}: {
  slice: WidgetProps<Data>['slice']
  offline: boolean
  nowMs: number
  answered: boolean
  /** Hides the answer applied. With nothing left on the board, this is the
   *  difference between "no stops nearby" and "you hid them". */
  hidden?: number
}) {
  const reason = offline
    ? 'offline'
    : answered
      ? hidden > 0
        ? 'hidden'
        : 'none'
      : slice.error !== null
        ? 'failing'
        : 'waiting'

  const message = {
    offline: 'no connection',
    failing: 'departure feeds down',
    waiting: 'waiting for departures',
    none: 'no stops nearby',
    hidden: `nothing left nearby · ${hidden} hidden`,
  }[reason]

  // Only where it means something. A successful answer carrying no stops is
  // not stale, and a fetch that has never once landed has no age to report.
  const age =
    (reason === 'failing' || reason === 'offline') && slice.fetched_at !== null
      ? since(slice.fetched_at, nowMs)
      : null

  return (
    <div class="void dep-empty" data-reason={reason}>
      <span class="dep-empty-line">
        <span class="dep-dot" />
        {message}
      </span>
      {age && <span class="stamp">last answer {age} ago</span>}
    </div>
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
    return (
      <Empty
        slice={slice}
        offline={offline}
        nowMs={nowMs}
        answered={!!data}
        hidden={data?.hidden?.length}
      />
    )
  }

  const hidden = data.hidden ?? []

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
        <span class="dep-status-notes">
          {/* Said on the tile itself, not only in settings: a board with rows
              taken off it that looks exactly like the whole board is a board
              lying by omission. */}
          {hidden.length > 0 && <span class="dep-hidden label">{hidden.length} hidden</span>}
          {/* A count, not the text: BVG's notices run to a paragraph and would
              swallow the board. The number is the flag; the tile's detail view
              underneath carries what they actually say, which is the whole
              reason this line is worth drawing at all.

              On the fallback the slot explains its own emptiness instead. A
              board that simply stops showing disruption counts looks like a
              board with no disruptions. */}
          {fallbackSources(data).length > 0 ? (
            <span class="dep-warning label" data-quiet>
              no disruption feed
            </span>
          ) : (
            data.warnings.length > 0 && (
              <span class="dep-warning label">
                {data.warnings.length} disruption{data.warnings.length === 1 ? '' : 's'}
              </span>
            )
          )}
        </span>
      </div>
    </div>
  )
}

/**
 * The switch into hiding things, on the public site's opened tile.
 *
 * A mode rather than a Hide button on every row all the time: the sheet is
 * mostly opened to read a timetable, and a button down the right of every row
 * is a column of numbers that is not there.
 */
function Customising({ editing, onToggle }: { editing: boolean; onToggle: () => void }) {
  return (
    <div class="spread dep-customise">
      <span class="dep-customise-hint">
        {editing
          ? 'A train hides by platform, so its short runs go with it.'
          : 'Hide the stops and directions you never use.'}
      </span>
      <button type="button" aria-pressed={editing} onClick={onToggle}>
        {editing ? 'Done' : 'Customise'}
      </button>
    </div>
  )
}

function HiddenList({ hidden, show }: { hidden: Hidden[]; show: Customise['show'] }) {
  return (
    <div class="dep-hidden-list">
      <div class="label">Hidden</div>
      {hidden.map((entry) => (
        <div key={entry.token} class="spread dep-hidden-item">
          <span class="body">{entry.label}</span>
          <button type="button" class="dep-hide" onClick={() => show(entry.token)}>
            Show
          </button>
        </div>
      ))}
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
 *
 * Unfiltered except by the reader, on the public site, who can hide a stop or a
 * direction from here — and who then finds that list here too, because a
 * hidden row with no visible way back is a row that looks like it stopped
 * running.
 */
function Detail({ slice, expired, offline = false, customise }: WidgetProps<Data>) {
  const [editing, setEditing] = useState(false)
  const data = slice.data
  const nowMs = now.value
  const boards = data?.boards ?? []
  const hidden = data?.hidden ?? []
  // An answer with boards on it: the only shape the timetable below can draw.
  const full = data && boards.length > 0 ? data : null
  const onHide = editing ? customise?.hide : undefined

  // The wall, unchanged: nothing to customise, so nothing to draw around the
  // empty state either.
  if (!full && !customise) {
    return <Empty slice={slice} offline={offline} nowMs={nowMs} answered={!!data} />
  }

  return (
    <div class="stack fill">
      {customise && data && (
        <Customising editing={editing} onToggle={() => setEditing((was) => !was)} />
      )}

      {full ? (
        <div
          class="dep-boards dep-boards-full fill"
          data-boards={boards.length}
          data-customising={onHide ? true : undefined}
        >
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
                onHide={onHide}
              />
            )
          })}
        </div>
      ) : (
        <Empty
          slice={slice}
          offline={offline}
          nowMs={nowMs}
          answered={!!data}
          hidden={hidden.length}
        />
      )}

      {/* The way back, listed wherever it is needed: while customising, and
          whenever the hides have emptied the board outright. */}
      {customise && hidden.length > 0 && (editing || !full) && (
        <HiddenList hidden={hidden} show={customise.show} />
      )}

      {full && fallbackSources(full).length > 0 && (
        <div class="dep-warnings">
          <div class="label">Disruptions</div>
          <p class="body muted">
            Not available from {fallbackSources(full).join(' + ')}, which is
            serving this board while the primary feed is down. Delays and
            cancellations above are live; notices are not published on this
            source at all.
          </p>
        </div>
      )}

      {full && full.warnings.length > 0 && (
        <div class="dep-warnings">
          <div class="label">Disruptions</div>
          {full.warnings.map((warning) => (
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
