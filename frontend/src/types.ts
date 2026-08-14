import type { ComponentType } from 'preact'

/** One provider's slice of /api/state. */
export interface Slice<T = any> {
  data: T | null
  fetched_at: number | null
  stale: boolean
  error: string | null
  /** Seconds this data stays meaningful once we lose the Pi. 0 = forever. */
  useful_for: number
}

export type PanelState = Record<string, Slice>

/**
 * live         — stream open, data flowing
 * reconnecting — EventSource is retrying on its own; we still trust the data
 * offline      — retries have failed long enough that the panel says so
 */
export type Connection = 'live' | 'reconnecting' | 'offline'

export interface PanelConfig {
  general: { timezone?: string; locale?: string; idle_return_seconds?: number }
  location: { latitude: number; longitude: number; name?: string }
  stop_name: string
  voice_enabled: boolean
  /** Slugs the Pi actually serves. Absent on an older backend, in which case
   *  the panel falls back to rendering every widget in the bundle. */
  widgets?: string[]
  useful_for: Record<string, number>
}

export interface WidgetProps<T = any> {
  slice: Slice<T>
  /** True once the data has outlived its useful_for while offline. */
  expired: boolean
  /** POST to /api/action/<slug>. Rejects when the Pi is unreachable. */
  act: (payload: Record<string, unknown>) => Promise<void>
}

export interface Widget {
  slug: string
  /** Grid span in the 4x3 instrument panel. */
  size: { w: number; h: number }
  /** Compact, always-visible form. */
  Card: ComponentType<WidgetProps>
  /** Optional full-screen form shown on tap. */
  Detail?: ComponentType<WidgetProps>
}
