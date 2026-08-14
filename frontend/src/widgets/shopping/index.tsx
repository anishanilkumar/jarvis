/**
 * The shopping list — and the panel's write path.
 *
 * Touch (tap to tick off) and voice ("add rice to the shopping list") both land
 * on POST /api/action/shopping, so there is exactly one code path that writes
 * to Grocy. Every future interactive widget copies this shape.
 */

import { useState } from 'preact/hooks'
import { connection } from '../../state'
import type { Widget, WidgetProps } from '../../types'
import './shopping.css'

interface Item {
  id: number
  name: string
  amount: number | null
  done: boolean
}

interface Data {
  items: Item[]
  outstanding: number
}

function useToggle(act: WidgetProps['act']) {
  const [pending, setPending] = useState<number | null>(null)
  const [failed, setFailed] = useState<number | null>(null)

  const toggle = async (item: Item) => {
    setPending(item.id)
    setFailed(null)
    try {
      await act({ op: 'toggle', id: item.id, done: !item.done })
    } catch {
      // Not optimistic on purpose: on a shared wall panel, showing an item as
      // bought when the write failed is how someone comes home without milk.
      setFailed(item.id)
    } finally {
      setPending(null)
    }
  }

  return { toggle, pending, failed }
}

function List({ items, act, compact }: { items: Item[]; act: WidgetProps['act']; compact: boolean }) {
  const { toggle, pending, failed } = useToggle(act)
  const offline = connection.value === 'offline'

  return (
    <ul class="shop-list fill">
      {items.map((item) => (
        <li
          key={item.id}
          class="shop-item"
          data-done={item.done}
          data-pending={pending === item.id}
          data-failed={failed === item.id}
          onClick={(event) => {
            event.stopPropagation()
            if (!offline) void toggle(item)
          }}
        >
          <span class="shop-box" />
          <span class="shop-name">{item.name}</span>
          {item.amount !== null && item.amount > 1 && (
            <span class="shop-amount stamp">×{item.amount}</span>
          )}
          {failed === item.id && !compact && <span class="shop-failed label">not saved</span>}
        </li>
      ))}
    </ul>
  )
}

function Card({ slice, act }: WidgetProps<Data>) {
  const data = slice.data
  if (!data) {
    return (
      <div class="void">
        {slice.error?.includes('GROCY_API_KEY') ? 'grocy key not set' : slice.error ? 'grocy unreachable' : 'waiting'}
      </div>
    )
  }

  const outstanding = data.items.filter((item) => !item.done)
  if (outstanding.length === 0) return <div class="void">list clear</div>

  return (
    <div class="stack fill">
      <div class="spread">
        <span class="label">Shopping</span>
        <span class="stamp">{outstanding.length}</span>
      </div>
      <List items={outstanding.slice(0, 6)} act={act} compact />
    </div>
  )
}

function Detail({ slice, act }: WidgetProps<Data>) {
  const data = slice.data
  if (!data) return <div class="void">grocy unreachable</div>
  if (data.items.length === 0) return <div class="void">list is empty</div>

  return <List items={data.items} act={act} compact={false} />
}

export default {
  slug: 'shopping',
  size: { w: 1, h: 1 },
  Card,
  Detail,
} satisfies Widget
