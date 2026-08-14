/**
 * Today's meal plan, from Grocy.
 *
 * The missing-ingredient count is the reason this belongs on a kitchen wall:
 * it turns "what's for dinner" into "what do I need to buy first".
 */

import type { Widget, WidgetProps } from '../../types'
import './meals.css'

interface Entry {
  day: string
  is_today: boolean
  kind: string
  title: string
  servings: number | null
  missing: number | null
  recipe_id: number | null
  description?: string
}

interface Data {
  entries: Entry[]
  today: string
}

function Missing({ count }: { count: number | null }) {
  if (count === null) return null
  if (count === 0) return <span class="meal-ok label">all in stock</span>
  return (
    <span class="meal-missing label">
      {count} missing
    </span>
  )
}

function Card({ slice }: WidgetProps<Data>) {
  const data = slice.data
  if (!data) {
    return (
      <div class="void">
        {slice.error?.includes('GROCY_API_KEY') ? 'grocy key not set' : slice.error ? 'grocy unreachable' : 'waiting'}
      </div>
    )
  }
  if (data.entries.length === 0) return <div class="void">nothing planned</div>

  const today = data.entries.filter((entry) => entry.is_today)
  const later = data.entries.filter((entry) => !entry.is_today)

  return (
    <div class="stack fill">
      <span class="label">Meal plan</span>

      <div class="stack fill meal-today">
        {today.length === 0 ? (
          <span class="body muted">Nothing planned today</span>
        ) : (
          today.map((entry) => (
            <div key={entry.title} class="meal-entry">
              <span class="readout">{entry.title}</span>
              <Missing count={entry.missing} />
            </div>
          ))
        )}
      </div>

      {later.length > 0 && (
        <div class="meal-later spread">
          <span class="label">Tomorrow</span>
          <span class="body muted">{later.map((entry) => entry.title).join(', ')}</span>
        </div>
      )}
    </div>
  )
}

function Detail({ slice }: WidgetProps<Data>) {
  const data = slice.data
  if (!data || data.entries.length === 0) return <div class="void">nothing planned</div>

  return (
    <div class="stack fill">
      {data.entries.map((entry) => (
        <article key={`${entry.day}-${entry.title}`} class="meal-full">
          <div class="spread">
            <span class="label">
              {entry.is_today
                ? 'Today'
                : new Date(entry.day).toLocaleDateString(undefined, { weekday: 'long' })}
            </span>
            <Missing count={entry.missing} />
          </div>
          <h2 class="readout">{entry.title}</h2>
          {entry.description && <p class="body muted meal-desc">{entry.description}</p>}
        </article>
      ))}
    </div>
  )
}

export default {
  slug: 'meals',
  size: { w: 2, h: 1 },
  Card,
  Detail,
} satisfies Widget
