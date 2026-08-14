/**
 * Headlines, one at a time.
 *
 * Deliberately not a ticker. Moving text has to be chased to be read, which is
 * the wrong ask for a display you glance at from three metres, and continuous
 * animation is the one thing this panel refuses — it's tiring at 11pm and it
 * heats the tablet all night for nothing. Each headline holds still, then
 * crossfades. The only motion is the change itself, so movement means
 * something arrived.
 */

import { useEffect, useState } from 'preact/hooks'
import type { Widget, WidgetProps } from '../../types'
import './news.css'

interface Headline {
  title: string
  link: string
  published: string | null
}

interface Data {
  source: string
  rotate_seconds: number
  headlines: Headline[]
}

const DEFAULT_ROTATE_SECONDS = 30

function Card({ slice, expired }: WidgetProps<Data>) {
  const data = slice.data
  const headlines = data?.headlines ?? []
  const rotateSeconds = data?.rotate_seconds || DEFAULT_ROTATE_SECONDS
  const [index, setIndex] = useState(0)

  useEffect(() => {
    if (headlines.length <= 1) return
    const timer = setInterval(() => setIndex((n) => n + 1), rotateSeconds * 1000)
    return () => clearInterval(timer)
  }, [headlines.length, rotateSeconds])

  if (!data || headlines.length === 0) {
    return <div class="void">{slice.error ? 'no headlines' : 'waiting for data'}</div>
  }

  // Modulo at read time rather than resetting the counter, so a refresh that
  // returns a different number of headlines can't leave the index out of range
  // for a frame.
  const position = index % headlines.length
  const current = headlines[position]

  // Whether the source name is written in a non-Latin script. The shared
  // .label style uppercases and tracks out to 0.16em, which is right for a
  // Latin word and wrong for Malayalam — tracking pulls apart the conjuncts a
  // reader matches on, and case doesn't exist. Rather than permanently opting
  // this one label out, ask what the string actually is: Latin sources keep
  // the instrument look every other tile has.
  const nativeScript = /[^\u0000-\u024F]/.test(data.source || '')

  return (
    <div class="stack fill">
      <div class="spread">
        <span class="label news-source" data-native={nativeScript}>
          {data.source || 'headlines'}
        </span>
        {/* Position, not a countdown: it says "there are more" without adding
            a second moving thing to the tile. */}
        <span class="news-ticks">
          {headlines.map((headline, i) => (
            <span key={headline.link || i} class="news-tick" data-on={i === position} />
          ))}
        </span>
      </div>

      {/* Keyed on the headline so Preact replaces the node and the fade
          animation restarts. Without the key it would mutate text in place and
          the change would happen with no transition at all. */}
      <p key={current.link || position} class="news-headline fill" data-expired={expired}>
        {current.title}
      </p>
    </div>
  )
}

function Detail({ slice }: WidgetProps<Data>) {
  const data = slice.data
  const headlines = data?.headlines ?? []
  if (!data || headlines.length === 0) return <div class="void">no headlines</div>

  return (
    <div class="stack fill news-all">
      {headlines.map((headline) => (
        <p key={headline.link || headline.title} class="news-headline-small">
          {headline.title}
        </p>
      ))}
    </div>
  )
}

export default {
  slug: 'news',
  size: { w: 2, h: 1 },
  Card,
  Detail,
} satisfies Widget
