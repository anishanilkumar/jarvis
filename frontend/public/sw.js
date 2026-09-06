/* Service worker: make the panel survive the Pi being down.
 *
 * Two jobs, and deliberately no more:
 *   1. Precache the app shell so the panel boots with no network at all —
 *      including the case where the *tablet* power-cycles while the Pi is off.
 *   2. Serve /api/config from cache when it can't be fetched, so a cold boot
 *      still knows its own settings.
 *
 * It deliberately does NOT cache /api/state. Panel data comes from IndexedDB,
 * which is stamped with fetched_at and expired per widget. A second cached
 * copy with no age attached is exactly how a display ends up confidently
 * showing yesterday's tram times.
 */

// Bumping this is the eviction mechanism: `activate` deletes every cache whose
// key isn't the current VERSION, so a bump wipes the previous one wholesale.
//
// Bumped to v3 on 2026-09-06 to evict a v2 cache that had gone bad on the wall
// tablet. It held an index.html from before the network-first rule below
// existed, so it kept answering navigations with a document naming a bundle
// that had since been deleted from the Pi — and answering the requests for that
// bundle too, out of the same cache. The panel rendered perfectly, from files
// the server no longer had, and no amount of refreshing could reach past it.
const VERSION = 'jarvis-v3'
const SHELL = ['/', '/index.html', '/manifest.webmanifest']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(VERSION)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  // The SSE stream must never be intercepted — a cached or buffered response
  // would leave the panel looking connected while receiving nothing.
  if (url.pathname === '/api/stream' || url.pathname === '/voice') return

  if (url.pathname === '/api/config') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone()
          void caches.open(VERSION).then((cache) => cache.put(request, copy))
          return response
        })
        .catch(() => caches.match(request).then((hit) => hit ?? Response.error())),
    )
    return
  }

  if (url.pathname.startsWith('/api/')) return

  // The document is network-first, and this is not a preference.
  //
  // The cache-first rule below is justified by content hashing, which is true
  // of everything Vite emits and false of index.html — the one file that names
  // those hashes. Precached cache-first, it pins a client to whatever build it
  // first saw: new assets ship, the stale document never asks for them, and the
  // panel renders the old bundle forever. sw.js itself is byte-identical across
  // deploys, so nothing prompts an update either. Observed on the wall tablet,
  // which sat two builds behind while the Pi served the current one.
  //
  // Cache is still the fallback, so a cold boot with the Pi down still paints.
  if (request.mode === 'navigate' || url.pathname === '/' || url.pathname === '/index.html') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone()
            void caches.open(VERSION).then((cache) => cache.put('/index.html', copy))
          }
          return response
        })
        .catch(() => caches.match('/index.html').then((hit) => hit ?? Response.error())),
    )
    return
  }

  // Static assets: cache first. They're content-hashed by Vite, so a stale hit
  // is impossible — a changed build produces a different URL.
  event.respondWith(
    caches.match(request).then((hit) => {
      // ...unless what we cached isn't what we asked for. See below.
      if (hit && mistyped(request, hit)) {
        void caches.open(VERSION).then((cache) => cache.delete(request))
        return fetchAsset(request)
      }
      return hit ?? fetchAsset(request)
    }),
  )
})

function fetchAsset(request) {
  return fetch(request).then((response) => {
    // `response.ok` is not enough, and this is the trap that took the wall
    // down. Caddy serves the panel with `try_files {path} /index.html`, so a
    // bundle that no longer exists — every deploy deletes the previous one —
    // comes back as 200 text/html rather than 404. The browser asked for a
    // module script, got a document, refused to execute it, and rendered
    // nothing. Cached on `ok` alone, that document then sat in front of the
    // real URL forever and no reload could dislodge it.
    if (response.ok && !mistyped(request, response)) {
      const copy = response.clone()
      void caches.open(VERSION).then((cache) => cache.put(request, copy))
    }
    return response
  })
}

/**
 * A document where a script or a stylesheet was asked for.
 *
 * Always a server telling us the file is gone in the least useful way it
 * could. Never cache it, never serve it from cache: a wrong answer that
 * persists is much worse than one that fails again on the next request.
 */
function mistyped(request, response) {
  const wanted = request.destination
  if (wanted !== 'script' && wanted !== 'style') return false
  return (response.headers.get('Content-Type') || '').includes('text/html')
}
