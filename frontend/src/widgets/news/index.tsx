/**
 * Headlines, one story at a time.
 *
 * Deliberately not a ticker. Moving text has to be chased to be read, which is
 * the wrong ask for a display you glance at from three metres, and continuous
 * animation is the one thing this panel refuses — it's tiring at 11pm and it
 * heats the tablet all night for nothing. Each story holds still, then
 * crossfades. The only motion is the change itself, so movement means
 * something arrived.
 *
 * A story is headline, excerpt and picture, and the last two are optional at
 * every level: feeds disagree about where they keep them and some carry
 * neither. The tile re-lays itself out around what actually arrived rather than
 * holding an empty frame open — a grey rectangle where a photo should be is
 * worse than a headline that simply uses the whole width.
 */

import { useEffect, useState } from 'preact/hooks'
import type { Widget, WidgetProps } from '../../types'
import './news.css'

interface Headline {
  title: string
  excerpt: string
  /** Empty string when the feed carries no picture for this story. */
  image: string
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
  // Pictures come from the publisher, not from the Pi, so they are the one
  // part of this tile that can fail on its own — a dead CDN, a tablet with no
  // route to the internet, a hotlink the site refuses. Remembering which URLs
  // failed lets the story fall back to text instead of holding a broken frame
  // open, and it survives the rotation coming back around to it.
  const [broken, setBroken] = useState<Record<string, true>>({})

  useEffect(() => {
    if (headlines.length <= 1) return
    const timer = setInterval(() => setIndex((n) => n + 1), rotateSeconds * 1000)
    return () => clearInterval(timer)
  }, [headlines.length, rotateSeconds])

  // Modulo at read time rather than resetting the counter, so a refresh that
  // returns a different number of headlines can't leave the index out of range
  // for a frame.
  const position = headlines.length > 0 ? index % headlines.length : 0

  // Fetch the next picture during the thirty seconds this one is up, so the
  // crossfade lands on a complete story rather than on text with a photo
  // arriving underneath it a moment later. One image ahead, not all eight: the
  // rest may never be reached before the feed refreshes.
  useEffect(() => {
    if (headlines.length <= 1) return
    const next = headlines[(position + 1) % headlines.length]
    if (!next?.image || broken[next.image]) return
    const preload = new Image()
    preload.src = next.image
  }, [headlines, position])

  if (!data || headlines.length === 0) {
    return <div class="void">{slice.error ? 'no headlines' : 'waiting for data'}</div>
  }

  const current = headlines[position]
  const image = current.image && !broken[current.image] ? current.image : ''

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

      {/* Keyed on the story so Preact replaces the node and the fade animation
          restarts. Without the key it would mutate text in place and the change
          would happen with no transition at all. */}
      <div key={current.link || position} class="news-story fill" data-expired={expired}>
        {image && (
          <img
            class="news-image"
            src={image}
            alt=""
            onError={() => setBroken((seen) => ({ ...seen, [current.image]: true }))}
          />
        )}
        <div class="news-text">
          <p class="news-headline">{current.title}</p>
          {current.excerpt && <p class="news-excerpt">{current.excerpt}</p>}
        </div>
      </div>
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
        <article key={headline.link || headline.title} class="news-item">
          {headline.image && <img class="news-thumb" src={headline.image} alt="" />}
          <div class="news-text">
            <p class="news-headline-small">{headline.title}</p>
            {headline.excerpt && <p class="news-excerpt-small">{headline.excerpt}</p>}
          </div>
        </article>
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
