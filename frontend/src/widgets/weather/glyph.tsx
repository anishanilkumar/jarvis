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
