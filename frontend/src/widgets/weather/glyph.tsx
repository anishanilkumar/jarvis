/**
 * Weather glyphs drawn as instrument marks — stroked geometry on the panel's
 * own grid, not a downloaded icon set or emoji. Emoji would drag a second
 * visual language (glossy, full-colour, vendor-specific) onto a panel whose
 * whole argument is engraved consistency.
 */

interface Props {
  icon: string
  day?: boolean
  size?: number
}

export function WeatherGlyph({ icon, day = true, size = 44 }: Props) {
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
      class="wx-glyph"
      data-icon={icon}
      aria-hidden="true"
    >
      {shape(icon, day)}
    </svg>
  )
}

const sun = (cx = 24, cy = 24, r = 8) => (
  <>
    <circle cx={cx} cy={cy} r={r} />
    {Array.from({ length: 8 }, (_, i) => {
      const angle = (i / 8) * Math.PI * 2
      return (
        <line
          key={i}
          x1={cx + Math.cos(angle) * (r + 4)}
          y1={cy + Math.sin(angle) * (r + 4)}
          x2={cx + Math.cos(angle) * (r + 9)}
          y2={cy + Math.sin(angle) * (r + 9)}
        />
      )
    })}
  </>
)

const moon = <path d="M30 8a14 14 0 1 0 10 24A16 16 0 0 1 30 8Z" />

const cloud = <path d="M14 34h20a7 7 0 0 0 0-14 10 10 0 0 0-19 3 6 6 0 0 0-1 11Z" />

const drops = (n: number) => (
  <>
    {Array.from({ length: n }, (_, i) => (
      <line key={i} x1={16 + i * 7} y1={38} x2={13 + i * 7} y2={44} />
    ))}
  </>
)

function shape(icon: string, day: boolean) {
  switch (icon) {
    case 'clear':
      return day ? sun() : moon
    case 'partly':
      return (
        <>
          {day ? sun(32, 16, 6) : moon}
          {cloud}
        </>
      )
    case 'cloudy':
      return cloud
    case 'fog':
      return (
        <>
          {cloud}
          <line x1="12" y1="40" x2="36" y2="40" />
          <line x1="16" y1="44" x2="32" y2="44" />
        </>
      )
    case 'drizzle':
      return (
        <>
          {cloud}
          {drops(2)}
        </>
      )
    case 'rain':
    case 'showers':
      return (
        <>
          {cloud}
          {drops(3)}
        </>
      )
    case 'sleet':
    case 'snow':
      return (
        <>
          {cloud}
          <line x1="17" y1="38" x2="17" y2="44" />
          <line x1="14" y1="41" x2="20" y2="41" />
          <line x1="31" y1="38" x2="31" y2="44" />
          <line x1="28" y1="41" x2="34" y2="41" />
        </>
      )
    case 'storm':
      return (
        <>
          {cloud}
          <path d="M26 36l-7 6h6l-3 6" />
        </>
      )
    default:
      return <circle cx="24" cy="24" r="10" stroke-dasharray="4 5" />
  }
}

/**
 * Sunrise and sunset, as one mark each.
 *
 * The public dashboard's header used to carry these as a bare ↑ and ↓ beside
 * the times, which only works if you already hold the convention — and a page
 * anyone can open a link to cannot assume that. The first replacement kept an
 * arrow and added a horizon under it, which was two marks arguing: at this
 * size the arrow was the loudest thing in the glyph and it still said nothing
 * a sun on a horizon does not.
 *
 * So: ONE mark, drawn identically for both ends of the day, and lit
 * differently. Sunrise is bright and sunset is dim, which is the thing itself
 * rather than a symbol for it — light arriving and light going. The strokes
 * are currentColor, so the whole discrimination lives in one CSS declaration
 * and the SVG has no idea which one it is.
 *
 * The grid is 22x20 rather than the 48 square above. SMALL, because this sits
 * inline against a timestamp at a fraction of a tile glyph's size, and a
 * 48-unit grid's 2.5 stroke lands under a pixel there and greys out. Halving
 * the grid doubles the effective weight for free.
 */
export function SunEventGlyph({ event }: { event: 'rise' | 'set' }) {
  return (
    <svg
      viewBox="0 0 22 20"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      class="wx-sun-glyph"
      // Named, not hidden. The two marks are the same shape and differ only in
      // brightness, so to a screen reader — and to anyone who cannot pick that
      // difference up — this is the only thing saying which end of the day the
      // time belongs to.
      role="img"
    >
      <title>{event === 'rise' ? 'Sunrise' : 'Sunset'}</title>

      {/* Half a sun standing on the ground. Three rays, not eight: at this size
          each one is about two pixels long, and the ring of them the tile glyph
          can afford closes up into a solid blob. */}
      <path d="M1.5 16.5h19" />
      <path d="M5.75 16.5a5.25 5.25 0 0 1 10.5 0" />
      <path d="M11 8V5" />
      <path d="M5.4 10.4 3.5 8.5" />
      <path d="M16.6 10.4 18.5 8.5" />
    </svg>
  )
}
