/**
 * The panel's shared reactive state, and nothing else.
 *
 * Separate from state.ts because the signals are the only part two different
 * front ends agree on. The wall fills them from an SSE stream and an IndexedDB
 * cache; the public dashboard fills them by polling a stateless API. Keeping
 * the declarations here means the widget components — which read a slice and a
 * clock and know nothing about where either came from — work unchanged in
 * both, and that importing one does not drag a transport in behind it.
 */

import { signal, computed } from '@preact/signals'
import type { Connection, PanelConfig, PanelState } from './types'

export const state = signal<PanelState>({})
export const config = signal<PanelConfig | null>(null)
export const connection = signal<Connection>('reconnecting')
export const expanded = signal<string | null>(null)

/** Ticks once a second so countdowns and staleness stamps recompute. */
export const now = signal<number>(Date.now())
setInterval(() => (now.value = Date.now()), 1000)

export const isOffline = computed(() => connection.value === 'offline')
