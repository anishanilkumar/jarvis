/**
 * What you might pick up on the way out, drawn in the same stroked instrument
 * language as the weather glyphs next door — same 48-unit grid, same 2.5
 * stroke, same `currentColor`. A jacket lifted from an icon set would be a
 * filled, rounded, slightly cartoon object sitting on a panel of engraved
 * marks, and that difference reads from across the hallway.
 *
 * Four glyphs, in two opposed pairs: jacket/t-shirt and open/folded umbrella.
 * The tile always shows one of each pair, so "no" is a drawn answer rather than
 * an absent one — a greyed t-shirt states that the cold was considered, where
 * an empty half-tile only says nothing is there.
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

export function TShirtGlyph(props: Props) {
  return (
    <Frame {...props}>
      {/* The jacket's silhouette with the sleeves cut to the elbow and the
          collar opened into a crew neck — deliberately the same construction,
          so the pair reads as one garment changing rather than two unrelated
          drawings swapping places. */}
      <path d="M18 10 q6 6 12 0 L37 13 L43 25 L36 28 L33 23 L34 42 L14 42 L15 23 L12 28 L5 25 L11 13 Z" />
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

export function FoldedUmbrellaGlyph(props: Props) {
  return (
    <Frame {...props}>
      {/* Furled canopy: a narrow spindle rather than a scaled-down dome. The
          width is the whole distinction at a glance — an open umbrella is wide
          and a folded one is tall, and that difference survives being greyed
          out and read from across the room. */}
      <path d="M24 3 C17 13 17 27 20 32 L28 32 C31 27 31 13 24 3 Z" />
      {/* The two ties. They stop the spindle reading as a leaf or a feather. */}
      <path d="M18.6 18 h10.8" />
      <path d="M19.8 26 h8.4" />
      {/* Shaft and hook are longer than the open umbrella's, not equal to them:
          a furled canopy is slim, and at matched proportions this glyph carried
          visibly less weight than the other three and read as half-drawn. */}
      <path d="M24 32 V40" />
      <path d="M24 40 a5 5 0 1 1 -10 0" />
    </Frame>
  )
}
