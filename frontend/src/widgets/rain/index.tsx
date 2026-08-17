/**
 * What to take with you.
 *
 * The tile used to show a probability strip, which handed you the raw forecast
 * and left you to work out what it meant while putting your shoes on. It now
 * shows the conclusion: an icon appears only when the answer is yes, so the
 * tile is read by counting the marks on it, not by reading it at all.
 *
 * The empty case earns its own line. A tile that goes blank when there is
 * nothing to take is indistinguishable from a tile that has crashed.
 */

import type { JSX } from 'preact'

import type { Widget, WidgetProps } from '../../types'
import { JacketGlyph, UmbrellaGlyph } from './glyphs'
import './rain.css'

interface Advice {
  needed: boolean
  at: string | null
}

interface Data {
  jacket: Advice & { apparent: number | null; below: number }
  umbrella: Advice & { probability: number; threshold: number }
  headline: string
  through: string | null
  spans_tomorrow: boolean
}

const hhmm = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : ''

function Card({ slice }: WidgetProps<Data>) {
  const data = slice.data
  if (!data) return <div class="void">{slice.error ? 'no forecast' : 'waiting'}</div>

  const { jacket, umbrella } = data
  const nothing = !jacket.needed && !umbrella.needed

  return (
    <div class="stack fill">
      <span class="label">{data.spans_tomorrow ? 'Next few hours' : 'Today'}</span>

      <div class="take fill" data-empty={nothing}>
        {jacket.needed && (
          <div class="take-item">
            <JacketGlyph size={104} />
            <span class="take-name">Jacket</span>
          </div>
        )}
        {umbrella.needed && (
          <div class="take-item">
            <UmbrellaGlyph size={104} />
            <span class="take-name">Umbrella</span>
          </div>
        )}
        {nothing && <span class="take-none">Nothing to take</span>}
      </div>

      <div class="spread">
        <span class="stamp">{jacket.apparent !== null ? `feels ${jacket.apparent}°` : ''}</span>
        <span class="stamp">rain {umbrella.probability}%</span>
      </div>
    </div>
  )
}

/**
 * One line of the detail view — why the icon is or isn't showing. The verdict
 * is the bare noun rather than "take a jacket": the headline above has already
 * said that, and repeating it twice on one screen makes the rows read as
 * instructions rather than as the reasoning behind one.
 */
function Line({
  glyph,
  name,
  needed,
  because,
}: {
  glyph: JSX.Element
  name: string
  needed: boolean
  because: string
}) {
  return (
    <li class="take-row" data-needed={needed}>
      {glyph}
      <div class="stack">
        <span class="readout">{needed ? name : `No ${name.toLowerCase()}`}</span>
        <span class="body muted">{because}</span>
      </div>
    </li>
  )
}

function Detail({ slice }: WidgetProps<Data>) {
  const data = slice.data
  if (!data) return <div class="void">no forecast</div>

  const { jacket, umbrella } = data

  return (
    <div class="stack fill">
      <div class="readout">{data.headline}</div>

      <ul class="take-rows fill">
        <Line
          glyph={<JacketGlyph size={56} />}
          name="Jacket"
          needed={jacket.needed}
          because={
            jacket.apparent === null
              ? 'no temperature forecast'
              : jacket.needed
                ? `feels like ${jacket.apparent}° by ${hhmm(jacket.at)}, below ${jacket.below}°`
                : `stays at ${jacket.apparent}° or warmer, above ${jacket.below}°`
          }
        />
        <Line
          glyph={<UmbrellaGlyph size={56} />}
          name="Umbrella"
          needed={umbrella.needed}
          because={
            umbrella.needed
              ? `${umbrella.probability}% chance around ${hhmm(umbrella.at)}`
              : `peaks at ${umbrella.probability}%, under ${umbrella.threshold}%`
          }
        />
      </ul>

      {/* Which hours the advice actually covers. Without it "no jacket" at
          nine in the evening is ambiguous about whether it means tonight. */}
      <span class="stamp muted">
        {data.spans_tomorrow ? 'through tomorrow morning' : 'through the rest of today'}
        {data.through ? `, to ${hhmm(data.through)}` : ''}
      </span>
    </div>
  )
}

export default {
  slug: 'rain',
  size: { w: 1, h: 1 },
  Card,
  Detail,
} satisfies Widget
