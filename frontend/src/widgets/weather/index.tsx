import type { Widget, WidgetProps } from '../../types'
import { WeatherGlyph } from './glyph'
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

      <div class="spread wx-foot">
        {/* Apparent temperature is what you dress for; it earns the space more
            than humidity does. */}
        <span class="stamp">feels {data.apparent}°</span>
        <span class="stamp">
          {data.today.low}° / {data.today.high}°
        </span>
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
          <span class="stamp">
            sunrise {time(data.today.sunrise)} · sunset {time(data.today.sunset)}
          </span>
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
