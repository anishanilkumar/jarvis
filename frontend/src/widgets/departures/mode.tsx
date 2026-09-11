/**
 * What kind of thing this line is, as one mark per row.
 *
 * The line number alone does not say. "U7" and "S1" carry their mode in the
 * name and everything else does not: M19 is a bus, M10 is a tram, 106 is a
 * bus, RE4 is a regional train, and the only way to tell from the board was to
 * already know. That mattered more once the boards stopped being hand-written
 * — a stop somebody configured is a stop they know, but the public dashboard
 * points at three stops around an address typed a second ago, and "M19 in 4"
 * is a different plan depending on whether you are looking for a bus stop or a
 * tram stop.
 *
 * BERLIN'S OWN MARKS, not a neutral icon set. The U in its square and the S in
 * its circle are on every station entrance in the city and read instantly to
 * anyone who lives here; a train pictogram in their place would be a worse
 * version of something the reader already knows by heart. Where the street has
 * no letter — a bus, a tram — the street uses a picture of the vehicle, and so
 * does this. Mixing the two is not an inconsistency, it is the convention.
 *
 * Stroked geometry on a 20-unit grid in currentColor, like the weather glyphs,
 * so these sit in the same engraved language as the rest of the panel and take
 * their colour from the row rather than carrying BVG's own blue and green onto
 * a dark instrument face.
 */

/** BVG's product names, which every source translates itself into. */
export type Product = string | null

function shape(product: Product) {
  switch (product) {
    // U in a square, S in a circle. Both are drawn from exact geometry rather
    // than a traced outline: the S is two circular arcs meeting at the centre,
    // which is what an S is, and a hand-tuned bezier version of it wobbled.
    case 'subway':
      return (
        <>
          <rect x="2" y="2" width="16" height="16" rx="3.5" />
          <path d="M7 6v4.5a3 3 0 0 0 6 0V6" />
        </>
      )
    case 'suburban':
      return (
        <>
          <circle cx="10" cy="10" r="8" />
          <path d="M12.3 6.2A2.6 2.6 0 1 0 10 10a2.6 2.6 0 1 1-2.3 3.8" />
        </>
      )

    // The three that have to be told apart from each other rather than from a
    // letter, so each one keeps whatever holds it up: a bus has wheels, a tram
    // hangs off a wire, a train has a nose. Same body underneath — at twenty
    // units the body is a box whatever you do to it, and arguing with that
    // just produces a smaller box.
    case 'bus':
      return (
        <>
          <rect x="2.5" y="1.5" width="15" height="11.5" rx="2.5" />
          <path d="M2.5 6.5h15" />
          <circle cx="6.5" cy="16" r="1.6" />
          <circle cx="13.5" cy="16" r="1.6" />
        </>
      )
    case 'tram':
      return (
        <>
          <path d="M2 1.5h16" />
          <path d="m10 6 3-4.5" />
          <rect x="3.5" y="6" width="13" height="9" rx="2.5" />
          <path d="M3.5 10h13" />
          <path d="M2 17.5h16" />
        </>
      )
    case 'regional':
    case 'express':
      return (
        <>
          <path d="M4.5 15V7a9 9 0 0 1 11 0v8Z" />
          <path d="M6 10.5h8" />
          <path d="M6.5 13h1.5" />
          <path d="M13 13h1.5" />
          <path d="M2.5 18h15" />
        </>
      )

    case 'ferry':
      return (
        <>
          <path d="M3 13.5h14l-2.5 4.5h-9Z" />
          <path d="M10 13.5V3" />
          <path d="M10 4.5h5l-5 3.5" />
        </>
      )

    // A product nobody taught this about. Nothing is better than a wrong
    // vehicle: the row still has its line number, and a blank keeps the column
    // aligned without claiming the M19 is a ferry.
    default:
      return null
  }
}

export function ModeGlyph({ product }: { product: Product }) {
  const mark = shape(product)
  if (!mark) return null

  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      stroke-width="1.75"
      stroke-linecap="round"
      stroke-linejoin="round"
      class="route-mode"
      data-product={product}
      // Decorative. The row already says "U7 to Rudow", so a screen reader
      // announcing "U-Bahn" before it would only be reading the 7 twice.
      aria-hidden="true"
    >
      {mark}
    </svg>
  )
}
