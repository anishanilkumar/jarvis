/**
 * Widget auto-registration.
 *
 * Dropping a folder into widgets/ with a default-exported Widget is the entire
 * registration step. This mirrors the backend's provider discovery, so adding
 * a feature really is one provider file plus one widget folder.
 */

import type { Widget } from '../types'

const modules = import.meta.glob<{ default: Widget }>('./*/index.tsx', { eager: true })

/**
 * Panel order. Explicit rather than alphabetical because hierarchy is the
 * design: departures dominates because it's the only time-critical tile, and
 * the quiet strip sits underneath.
 */
const ORDER = ['departures', 'clock', 'weather', 'rain', 'meals', 'shopping', 'music']

export const widgets: Widget[] = Object.values(modules)
  .map((m) => m.default)
  .sort((a, b) => {
    const ai = ORDER.indexOf(a.slug)
    const bi = ORDER.indexOf(b.slug)
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
  })

export const bySlug = new Map(widgets.map((w) => [w.slug, w]))
