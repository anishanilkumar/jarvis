/**
 * Music.
 *
 * This tile shows what we last *asked* for, not what is playing. The tablet's
 * media session isn't visible from the Pi, so a now-playing display would be a
 * guess that silently goes wrong — worse than showing nothing. When the HA
 * Companion App later exposes the media session, this becomes a real
 * now-playing widget without touching anything else.
 */

import { voice } from '../../voice'
import type { Widget, WidgetProps } from '../../types'
import './music.css'

interface Data {
  last_request: { query: string; at: number } | null
}

function since(at: number): string {
  const minutes = Math.floor((Date.now() / 1000 - at) / 60)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  return `${Math.floor(minutes / 60)}h ago`
}

function Card({ slice }: WidgetProps<Data>) {
  const last = slice.data?.last_request

  return (
    <div class="stack fill music">
      <span class="label">Music</span>

      {last ? (
        <div class="stack fill music-last">
          <span class="music-query readout">{last.query}</span>
          <span class="stamp">requested {since(last.at)}</span>
        </div>
      ) : (
        <div class="music-hint fill">
          <span class="body muted">
            Say <span class="arc">“hey jarvis, play…”</span>
          </span>
        </div>
      )}

      {voice.value.listening && <span class="label gold">Listening</span>}
    </div>
  )
}

export default {
  slug: 'music',
  size: { w: 1, h: 1 },
  Card,
} satisfies Widget
