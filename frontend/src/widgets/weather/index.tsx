import type { Widget, WidgetProps } from '../../types'
import { SunEventGlyph, WeatherGlyph } from './glyph'
import './weather.css'

interface Condition {
  label: string
  icon: string
}

interface Data {
  temperature: number
  apparent: number
  humidity: number | null
  wind: number
  is_day: boolean
  condition: Condition
  today: { high: number; low: number; sunrise: string; sunset: string }
  forecast: Array<{
    date: string
    high: number
    low: number
    rain_chance: number
    condition: Condition
  }>
}

const time = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

/**
 * The two ends of the day.
 *
 * These used to sit in the public dashboard's header as ↑ 06:34 / ↓ 19:52, and
 * an arrow on its own only reads if you already hold the convention — which a
 * page anyone can open a link to cannot assume. The mark carries it instead.
 *
 * Both marks are the same sun on the same horizon, and BRIGHTNESS is what
 * separates them: sunrise lit, sunset dim. Not a symbol for the difference,
 * the difference itself. Which also means neither timestamp needs a caption
 * and the pair reads left to right the way the day runs.
 *
 * It is deliberately a fact about which end of the day this is, not about the
 * current hour — an earlier version lit whichever one you were heading
 * towards, so the same glyph meant "sunrise" in the morning and "the one
 * that's next" in the evening, and it was never possible to learn which.
 */
function SunTimes({ today }: { today: Data['today'] }) {
  // A backend a version behind, or a polar edge case where the sun does
  // neither. Silence beats "sunrise Invalid Date".
  if (Number.isNaN(new Date(today?.sunrise ?? '').getTime())) return null
  if (Number.isNaN(new Date(today?.sunset ?? '').getTime())) return null

  return (
    <div class="spread wx-sun">
      <span class="stamp" data-event="rise">
        <SunEventGlyph event="rise" />
        {time(today.sunrise)}
      </span>
      <span class="stamp" data-event="set">
        <SunEventGlyph event="set" />
        {time(today.sunset)}
      </span>
    </div>
  )
}

function Card({ slice }: WidgetProps<Data>) {
  const data = slice.data
  if (!data) return <div class="void">{slice.error ? 'no weather' : 'waiting'}</div>

  return (
    <div class="stack fill">
      <div class="spread">
        <span class="label">{data.condition.label}</span>
        <WeatherGlyph icon={data.condition.icon} day={data.is_day} />
      </div>

      <div class="wx-temp">
        <span class="hero">{data.temperature}</span>
        <span class="wx-deg">°</span>
      </div>

      <div class="wx-foot">
        <div class="spread">
          {/* Apparent temperature is what you dress for; it earns the space more
              than humidity does. */}
          <span class="stamp">feels {data.apparent}°</span>
          <span class="stamp">
            {data.today.low}° / {data.today.high}°
          </span>
        </div>
        <SunTimes today={data.today} />
      </div>
    </div>
  )
}

function Detail({ slice }: WidgetProps<Data>) {
  const data = slice.data
  if (!data) return <div class="void">no weather</div>

  return (
    <div class="stack fill">
      <div class="row">
        <span class="hero">{data.temperature}°</span>
        <div class="stack">
          <span class="readout">{data.condition.label}</span>
          <span class="body muted">
            feels {data.apparent}° · wind {data.wind} km/h
            {data.humidity !== null ? ` · ${data.humidity}% humidity` : ''}
          </span>
          <SunTimes today={data.today} />
        </div>
      </div>

      <ul class="wx-week fill">
        {data.forecast.map((day, index) => (
          <li key={day.date} class="wx-day">
            <span class="label">
              {index === 0
                ? 'Today'
                : new Date(day.date).toLocaleDateString(undefined, { weekday: 'short' })}
            </span>
            <WeatherGlyph icon={day.condition.icon} day />
            <span class="wx-chance stamp" data-wet={day.rain_chance >= 40}>
              {day.rain_chance}%
            </span>
            <span class="wx-range readout">
              <span class="muted">{day.low}°</span> {day.high}°
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default {
  slug: 'weather',
  size: { w: 1, h: 1 },
  Card,
  Detail,
} satisfies Widget
