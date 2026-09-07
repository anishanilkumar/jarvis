/**
 * The public dashboard's entry point.
 *
 * Built separately from the wall panel (vite.public.config.ts), which is what
 * guarantees the two cannot interfere. Sharing one build would let a change to
 * the public site alter the hash of a chunk the wall's self-update check reads,
 * and would put both sites in one dist/ that deploy.sh rsyncs to the Pi with
 * --delete.
 *
 * Three things the wall does that are deliberately absent here: no service
 * worker (a public page quietly serving a cached dashboard is the exact
 * dishonesty the freezing rules exist to prevent), no self-update loop (a
 * visitor gets a fresh document every visit; the kiosk does not), and no voice
 * — not disabled, not present.
 */

// tokens.css FIRST, so site.css below can override the root font size and the
// type scale. Vite emits CSS in import order and the last rule wins: with the
// tokens imported at the bottom, as the wall does it, the wall's
// viewport-derived root size (max(8px, min(0.8333vw, 1.3333vh))) survives and
// pins a phone to its 8px floor — the whole page at half size.
import '../styles/tokens.css'

import { render } from 'preact'
import { effect } from '@preact/signals'
import { useEffect, useState } from 'preact/hooks'

import { connection } from '../signals'
import { Dashboard } from './app'
import { boot, place, savePlace } from './place'
import { Setup, lookup, placeOf, unambiguous } from './setup'
import { startPolling } from './poll'
import './site.css'

/** The offline palette swap, carried over verbatim from the wall: a phone that
 *  loses signal desaturates the same way, and no component has to know. */
effect(() => {
  document.documentElement.dataset.connection = connection.value
})

const { query } = boot()

function App() {
  const here = place.value
  const [prefill, setPrefill] = useState(query ?? '')
  const [resolving, setResolving] = useState(!!query)

  // ?q=<address>. An unambiguous Berlin match goes straight through; anything
  // else opens the picker with the text already in it, because guessing between
  // two real streets is how you show someone the wrong tram.
  useEffect(() => {
    if (!query) return
    let live = true
    void (async () => {
      try {
        const hits = await lookup(query)
        const only = unambiguous(query, hits)
        if (live && only) savePlace(placeOf(only))
      } catch {
        setPrefill(query)
      } finally {
        if (live) setResolving(false)
      }
    })()
    return () => {
      live = false
    }
  }, [])

  useEffect(() => {
    if (!here) return
    return startPolling(here)
  }, [here?.lat, here?.lon])

  if (resolving) return <div class="site-booting label">Finding that address…</div>
  return here ? <Dashboard /> : <Setup initial={prefill} />
}

render(<App />, document.getElementById('site')!)
