/**
 * Last-known state, held on the tablet.
 *
 * The panel must survive the Pi rebooting, the LAN blipping, or the tablet
 * itself power-cycling while the Pi is still down. IndexedDB (not
 * localStorage) because writes are off the main thread — this runs every time
 * a provider updates, and a synchronous write would jank the departure board.
 */

import type { PanelState } from './types'

const DB = 'jarvis'
const STORE = 'state'
const KEY = 'last'

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 1)
    request.onupgradeneeded = () => request.result.createObjectStore(STORE)
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

export async function saveState(state: PanelState): Promise<void> {
  try {
    const db = await open()
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).put(state, KEY)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
    db.close()
  } catch {
    // Persistence is an optimisation, never a requirement. A tablet with a
    // full or blocked IndexedDB should still show live data.
  }
}

export async function loadState(): Promise<PanelState | null> {
  try {
    const db = await open()
    const state = await new Promise<PanelState | null>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly')
      const request = tx.objectStore(STORE).get(KEY)
      request.onsuccess = () => resolve(request.result ?? null)
      request.onerror = () => reject(request.error)
    })
    db.close()
    return state
  } catch {
    return null
  }
}

// The rule itself lives in expiry.ts — it is three lines of arithmetic with
// nothing to do with IndexedDB, and the public dashboard needs it without
// wanting a database. Re-exported here so its import sites do not move.
export { isExpired } from './expiry'
