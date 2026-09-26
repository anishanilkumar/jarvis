/**
 * How far a stop is, on foot and by bike, and whether a departure is step-free.
 *
 * Drawn in the same engraved language as the mode marks beside them — stroked
 * geometry on a 20-unit grid in currentColor — so the header reads as part of
 * the instrument rather than a row of emoji.
 */

function Glyph({ children, label }: { children: preact.ComponentChildren; label: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      stroke-width="1.75"
      stroke-linecap="round"
      stroke-linejoin="round"
      class="reach-glyph"
      role="img"
      aria-label={label}
    >
      {children}
    </svg>
  )
}

export function WalkGlyph() {
  return (
    <Glyph label="on foot">
      <circle cx="11" cy="3.2" r="1.7" />
      <path d="M10.5 6.5 8.5 12l-3 5.5" />
      <path d="m8.5 12 3.5 2 1 4" />
      <path d="M10.5 6.5 14 9.5l2.5 0.5" />
      <path d="M10.5 6.5 6.5 8.5 5 11.5" />
    </Glyph>
  )
}

export function BikeGlyph() {
  return (
    <Glyph label="by bike">
      <circle cx="4.5" cy="13.5" r="3.5" />
      <circle cx="15.5" cy="13.5" r="3.5" />
      <path d="M4.5 13.5 8 7h6l1.5 6.5" />
      <path d="M8 7 10.5 13.5h-6" />
      <path d="M10.5 13.5 14 7" />
      <path d="M7 5h2.5" />
      <path d="M13 4.5h2" />
    </Glyph>
  )
}

/** The international symbol, as a stroke: head, seat, wheel. */
export function StepFreeGlyph() {
  return (
    <Glyph label="step-free">
      <circle cx="8" cy="2.8" r="1.6" />
      <path d="M8 5.5v5.5h5l2.5 5" />
      <path d="M8 8h4.5" />
      <path d="M5.5 9.2a5 5 0 1 0 6.7 6.3" />
    </Glyph>
  )
}

/**
 * "🚶 39  🚲 12", without the emoji. The walk is always there; the bike only
 * where the distance is known, which is every public-board stop and any wall
 * board whose stop was looked up by name rather than pinned by id.
 */
export function Reach({ walk, cycle }: { walk: number; cycle?: number | null }) {
  return (
    <span class="reach stamp">
      <span class="reach-leg">
        <WalkGlyph />
        {walk}
      </span>
      {cycle != null && (
        <span class="reach-leg">
          <BikeGlyph />
          {cycle}
        </span>
      )}
      <span class="reach-unit">min</span>
    </span>
  )
}
