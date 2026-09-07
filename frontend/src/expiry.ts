/**
 * The honesty rule, on its own.
 *
 * Lives apart from offline.ts because it has nothing to do with IndexedDB, and
 * because the public dashboard needs the rule without wanting a database.
 */

/**
 * Whether a slice has outlived its usefulness.
 *
 * `useful_for: 0` means never expires (the local clock, a shopping list).
 * Everything else goes quiet rather than showing a number that is no longer
 * true — most sharply the departure board, where a countdown still ticking
 * down on unrefreshable data is actively wrong. A display that lies about your
 * tram is worse than one that admits it doesn't know.
 *
 * `fetchedAt` is in SECONDS, matching /api/state; `now` is in milliseconds.
 */
export function isExpired(fetchedAt: number | null, usefulFor: number, now: number): boolean {
  if (usefulFor <= 0) return false
  if (fetchedAt === null) return true
  return now / 1000 - fetchedAt > usefulFor
}
