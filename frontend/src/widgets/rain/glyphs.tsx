/**
 * The two things you might pick up on the way out, drawn in the same stroked
 * instrument language as the weather glyphs next door — same 48-unit grid, same
 * 2.5 stroke, same `currentColor`. A jacket lifted from an icon set would be a
 * filled, rounded, slightly cartoon object sitting on a panel of engraved
 * marks, and that difference reads from across the hallway.
 */

import type { ComponentChildren } from 'preact'

interface Props {
  size?: number
}

function Frame({ size = 44, children }: Props & { children: ComponentChildren }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      stroke="currentColor"
      stroke-width="2.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      class="take-glyph"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

export function JacketGlyph(props: Props) {
  return (
    <Frame {...props}>
      {/* One closed silhouette traced clockwise from the left collar point:
          neck, right collar, shoulder, down the outer sleeve seam, cuff, back
          up to the armpit, down the body to the hem, and the mirror of all of
          it. Single path so the corners miter instead of stacking two round
          caps at every joint. Sleeves hang well below the armpit on purpose —
          shortened to stubs the shape stops reading as a coat and starts
          reading as a cardigan. */}
      <path d="M18 9 L24 15 L30 9 L35 12 L41 34 L35 36 L32 22 L34 43 L14 43 L16 22 L13 36 L7 34 L13 12 Z" />
      <path d="M24 15 V43" />
    </Frame>
  )
}

export function UmbrellaGlyph(props: Props) {
  return (
    <Frame {...props}>
      <path d="M8 26 A16 16 0 0 1 40 26" />
      {/* Scalloped hem. Without it the canopy is a plain half-disc, which at
          tile size is indistinguishable from a cloud. */}
      <path d="M8 26 q4 5 8 0 q4 5 8 0 q4 5 8 0 q4 5 8 0" />
      <path d="M24 26 V38" />
      <path d="M24 38 a4 4 0 1 1 -8 0" />
    </Frame>
  )
}
