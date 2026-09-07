/**
 * Where the dashboard thinks you are, and how that survives a reload.
 *
 * Three sources, in this order: the URL, then the browser, then the setup
 * screen. The order matters more than it looks.
 *
 * A link someone sends you drives that one page load and is NOT written to
 * storage. Sending a friend your street should not silently move their
 * dashboard to it — they opened your view, they didn't adopt it. Storage is
 * written only when the visitor picks an address or changes a setting
 * themselves, which is also what the "save this view" button in settings is
 * for.
 */

import { signal } from '@preact/signals'

export interface Place {
  lat: number
  lon: number
  name: string
}

export interface Prefs {
  jacketBelow: number
  rainThreshold: number
}

const PLACE_KEY = 'jarvis.public.place'
const PREFS_KEY = 'jarvis.public.prefs'

/** Server-side defaults, replaced by the first weather response. */
export const DEFAULT_PREFS: Prefs = { jacketBelow: 14, rainThreshold: 40 }

export const place = signal<Place | null>(null)
export const prefs = signal<Prefs>(DEFAULT_PREFS)
/** True when the view came from a link rather than from this browser. */
export const fromLink = signal(false)
export const kiosk = signal(false)

function read<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    // A private window, or storage switched off. The page still works; it just
    // asks for the address again next time.
    return null
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* see above */
  }
}

export function savePlace(next: Place): void {
  place.value = next
  fromLink.value = false
  write(PLACE_KEY, next)
}

export function savePrefs(next: Prefs): void {
  prefs.value = next
  write(PREFS_KEY, next)
}

export function forget(): void {
  place.value = null
  fromLink.value = false
  try {
    localStorage.removeItem(PLACE_KEY)
  } catch {
    /* see above */
  }
}

/** The link that reproduces exactly what is on screen. */
export function shareUrl(): string {
  const here = place.value
  const url = new URL(window.location.href)
  url.search = ''
  url.hash = ''
  if (!here) return url.toString()
  const params = new URLSearchParams({
    lat: here.lat.toFixed(5),
    lon: here.lon.toFixed(5),
    name: here.name,
    jacket: String(prefs.value.jacketBelow),
  })
  return `${url.toString()}?${params.toString()}`
}

/**
 * Resolve the opening view.
 *
 * Returns the free-text query when the URL carried `?q=` instead of
 * coordinates, so the caller can geocode it and decide whether it was
 * unambiguous enough to skip the picker.
 */
export function boot(): { query: string | null } {
  const params = new URLSearchParams(window.location.search)
  kiosk.value = params.get('kiosk') === '1'

  const stored = read<Prefs>(PREFS_KEY)
  if (stored) prefs.value = { ...DEFAULT_PREFS, ...stored }

  const jacket = Number(params.get('jacket'))
  if (Number.isFinite(jacket) && jacket !== 0) {
    prefs.value = { ...prefs.value, jacketBelow: jacket }
  }

  const lat = Number(params.get('lat'))
  const lon = Number(params.get('lon'))
  if (Number.isFinite(lat) && Number.isFinite(lon) && lat !== 0 && lon !== 0) {
    place.value = { lat, lon, name: params.get('name') || 'Berlin' }
    fromLink.value = true
    return { query: null }
  }

  const query = params.get('q')
  if (query) return { query }

  place.value = read<Place>(PLACE_KEY)
  return { query: null }
}
