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

import { useEffect, useState } from 'preact/hooks'

import { connection, expanded, now, state } from '../signals'
import { isExpired } from '../expiry'
import type { Customise, Slice, Widget } from '../types'
import departures from '../widgets/departures'
import rain from '../widgets/rain'
import weather from '../widgets/weather'
import { hide, place, kiosk, show } from './place'
import { Clock } from './clock'
import { Settings } from './settings'
import '../styles/interior.css'

/**
 * The tiles, and what to call them.
 *
 * The wall labels a detail view with the widget's slug, which is fine for the
 * one household that chose the slugs. Here the names are written out, and this
 * is the place for them: the list of which widgets the public page shows is
 * already hardcoded three lines down, so a title beside each one is not a
 * second copy of anything.
 */
interface Tile {
  widget: Widget
  title: string
}

const TILES: Tile[] = [
  { widget: departures, title: 'Departures' },
  { widget: rain, title: 'What to take' },
  { widget: weather, title: 'Weather' },
]

/** All three have one today. Checked rather than assumed, so a widget that
 *  loses its Detail loses the affordance rather than offering an empty sheet. */
const opens = (widget: Widget) => widget.Detail !== undefined

/**
 * Who to credit, per source.
 *
 * Read off the response rather than hardcoded, because the footer used to name
 * BVG unconditionally and the page can now be served entirely by the fallback
 * — crediting an API that answered nothing, while the one that did goes
 * unnamed, is a small lie in the one place on the page whose whole job is
 * saying where this came from.
 */
const CREDITS: Record<string, { label: string; href: string }> = {
  bvg: { label: 'v6.bvg.transport.rest', href: 'https://v6.bvg.transport.rest' },
  transitous: { label: 'transitous.org', href: 'https://transitous.org' },
}

/** Nothing here writes; the wall's touch actions have no counterpart. */
const noAction = async () => {}

function emptySlice(): Slice {
  return { data: null, fetched_at: null, stale: true, error: null, useful_for: 0 }
}

/**
 * The opened tile.
 *
 * The wall has one of these and it is deliberately not reused. There it
 * replaces the whole screen, is dismissed by tapping anywhere, and closes
 * itself on an idle timer, because a wall is a shared surface and the next
 * person past it should not find someone else's timetable open. A phone is held
 * by the one person who opened it: this stays put until it is closed, and says
 * how.
 *
 * It is where the departures tile's "2 disruptions" finally says what they are.
 * A count with nowhere to go is a worse tile than no count at all.
 */
function Sheet({
  tile,
  slice,
  expired,
  offline,
  nowMs,
  onClose,
}: {
  tile: Tile
  slice: Slice
  expired: boolean
  offline: boolean
  nowMs: number
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)

    // The page behind holds still. Without this a scroll aimed at a long
    // timetable that has already reached its end carries on into the dashboard
    // underneath, which slides around behind a sheet that does not move — and
    // on a phone it is not obvious that two things are scrolling at all.
    const scrolled = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = scrolled
    }
  }, [onClose])

  const Body = tile.widget.Detail as NonNullable<Widget['Detail']>
  // Not on a kiosk, which is a screen someone cast and nobody is holding — the
  // same reason it has no settings button.
  const customise: Customise | undefined = kiosk.value ? undefined : { hide, show }

  return (
    <div class="sheet-scrim" onClick={onClose}>
      <div
        class="sheet instrument"
        role="dialog"
        aria-modal="true"
        aria-label={tile.title}
        onClick={(event) => event.stopPropagation()}
      >
        <div class="spread sheet-head">
          <span class="label">{tile.title}</span>
          <button type="button" class="sheet-close" onClick={onClose}>
            Close
          </button>
        </div>
        <Body
          slice={slice}
          expired={expired}
          offline={offline}
          act={noAction}
          customise={customise}
        />
        {/* The wall stamps freshness on every tile; here it belongs to the view
            you opened to read carefully, where "these numbers are from twelve
            minutes ago" changes what you do with them. */}
        {slice.fetched_at !== null && (
          <div class="stamp sheet-foot">updated {ago(slice.fetched_at, nowMs)}</div>
        )}
      </div>
    </div>
  )
}

function ago(fetchedAt: number, nowMs: number): string {
  const minutes = Math.floor(Math.max(0, nowMs / 1000 - fetchedAt) / 60)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  return `${Math.floor(minutes / 60)}h ago`
}

export function Dashboard() {
  const [settingsOpen, setSettings] = useState(false)
  const panelState = state.value
  const nowMs = now.value
  const offline = connection.value === 'offline'
  const open = TILES.find(({ widget }) => widget.slug === expanded.value && opens(widget)) ?? null

  // Falls back to the primary's credit when nothing has loaded yet, and on an
  // older backend that sends no `sources` because it only ever had one.
  const answered: string[] = (panelState.departures?.data as any)?.sources ?? []
  const credited = (answered.length > 0 ? answered : ['bvg'])
    .map((name) => CREDITS[name])
    .filter(Boolean)

  const sliceOf = (slug: string) => panelState[slug] ?? emptySlice()
  const expiredFor = (slice: Slice) => isExpired(slice.fetched_at, slice.useful_for, nowMs)

  return (
    <div class="site">
      <header class="site-head">
        <Clock />
        <div class="spread site-where">
          <span class="label">{place.value?.name}</span>
          {!kiosk.value && (
            <button
              type="button"
              class="site-gear"
              aria-expanded={settingsOpen}
              onClick={() => {
                // One overlay at a time. Settings sliding in behind an open
                // sheet leaves two Close buttons and no way to tell which is
                // which.
                expanded.value = null
                setSettings((wasOpen) => !wasOpen)
              }}
            >
              {settingsOpen ? 'Close' : 'Settings'}
            </button>
          )}
        </div>
      </header>

      {settingsOpen && <Settings onClose={() => setSettings(false)} />}

      <main class="site-grid">
        {TILES.map(({ widget, title }) => {
          const slice = sliceOf(widget.slug)
          // The honesty rule, unchanged from the wall: past its useful_for the
          // tile goes quiet rather than showing a number that is no longer
          // true. For departures that means the countdowns stop counting and
          // only the scheduled clock times remain.
          const expired = expiredFor(slice)
          const detailed = opens(widget)
          const openThis = () => {
            if (!detailed) return
            setSettings(false)
            expanded.value = widget.slug
          }

          return (
            <section
              key={widget.slug}
              class={detailed ? 'instrument site-tile' : 'instrument'}
              data-slug={widget.slug}
              data-expired={expired}
              // The whole tile takes the tap, which is what a thumb expects and
              // what the wall already does. The button below is the same action
              // said out loud — for the keyboard, for a screen reader, and for
              // anyone who looked at this page and could not tell there was
              // anything underneath it. There was, and nothing said so.
              onClick={openThis}
            >
              <widget.Card slice={slice} expired={expired} offline={offline} act={noAction} />
              {detailed && (
                <button
                  type="button"
                  class="site-more"
                  aria-haspopup="dialog"
                  // The visible word is the same on all three, because the
                  // tile above it has already said which one this is. The
                  // label spells it out for anyone hearing the page read
                  // aloud, where three identical "Details" buttons are three
                  // identical buttons.
                  aria-label={`${title} — details`}
                  onClick={(event) => {
                    event.stopPropagation()
                    openThis()
                  }}
                >
                  Details <span aria-hidden="true">›</span>
                </button>
              )}
            </section>
          )
        })}
      </main>

      {open && (
        <Sheet
          tile={open}
          slice={sliceOf(open.widget.slug)}
          expired={expiredFor(sliceOf(open.widget.slug))}
          offline={offline}
          nowMs={nowMs}
          onClose={() => (expanded.value = null)}
        />
      )}

      <footer class="site-foot stamp">
        Berlin only, for now · departures from{' '}
        {credited.map((source, index) => (
          <span key={source.href}>
            {index > 0 && ' + '}
            <a href={source.href}>{source.label}</a>
          </span>
        ))}{' '}
        · weather from <a href="https://open-meteo.com">Open-Meteo</a>
        {' · '}
        {/* The page's own source, credited in the line that credits its data.
            GitHub's mark is drawn inline: one icon is not worth the only
            third-party request the page would make. */}
        <a class="site-source" href="https://github.com/anishanilkumar/jarvis">
          <svg class="site-source-mark" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path
              fill="currentColor"
              d="M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z"
            />
          </svg>
          source on GitHub
        </a>
      </footer>
    </div>
  )
}
