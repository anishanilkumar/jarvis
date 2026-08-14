/**
 * Rain in the next two hours.
 *
 * The headline is the tile, not the chart. Standing in a hallway on the way
 * out you want "do I take a jacket", answered in one line; the 15-minute bars
 * underneath are there to be glanced at, not studied.
 */

import type { Widget, WidgetProps } from '../../types'
import './rain.css'

interface Bucket {
  time: string
  probability: number
  mm: number
}

interface Data {
  headline: string
  rain_expected: boolean
  threshold: number
  series: Bucket[]
  peak: number
}

const hhmm = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

function Bars({ series, threshold }: { series: Bucket[]; threshold: number }) {
  return (
    <div class="rain-bars">
      {series.map((bucket) => (
        <div key={bucket.time} class="rain-col">
          {/* A percentage floor collapses to invisible slivers on a dry day,
              which reads as a broken tile. A fixed 10px minimum keeps a dry
              forecast looking like a row of engraved index marks — clearly
              "measured and zero" rather than "nothing here". */}
          <div
            class="rain-bar"
            data-wet={bucket.probability >= threshold}
            style={{ height: `max(10px, ${bucket.probability}%)` }}
          />
        </div>
      ))}
    </div>
  )
}

function Card({ slice }: WidgetProps<Data>) {
  const data = slice.data
  if (!data) return <div class="void">{slice.error ? 'no forecast' : 'waiting'}</div>

  return (
    <div class="stack fill">
      <span class="label">Next 2 hours</span>
      <div class="rain-headline body" data-wet={data.rain_expected}>
        {data.headline}
      </div>
      <Bars series={data.series} threshold={data.threshold} />
      <div class="spread">
        <span class="stamp">{data.series[0] ? hhmm(data.series[0].time) : ''}</span>
        <span class="stamp">peak {data.peak}%</span>
      </div>
    </div>
  )
}

function Detail({ slice }: WidgetProps<Data>) {
  const data = slice.data
  if (!data) return <div class="void">no forecast</div>

  return (
    <div class="stack fill">
      <div class="readout" data-wet={data.rain_expected}>
        {data.headline}
      </div>
      <ul class="rain-rows fill">
        {data.series.map((bucket) => (
          <li key={bucket.time} class="rain-row">
            <span class="stamp">{hhmm(bucket.time)}</span>
            <div class="rain-track">
              <div
                class="rain-fill"
                data-wet={bucket.probability >= data.threshold}
                style={{ width: `${bucket.probability}%` }}
              />
            </div>
            <span class="rain-pct">{bucket.probability}%</span>
            <span class="stamp muted">{bucket.mm > 0 ? `${bucket.mm} mm` : ''}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default {
  slug: 'rain',
  size: { w: 1, h: 1 },
  Card,
  Detail,
} satisfies Widget
