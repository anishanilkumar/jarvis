/**
 * The clock tile IS the reactor dial — the signature instrument doing real
 * work rather than sitting somewhere as ornament.
 *
 * It renders from local time, so it keeps running when everything else has
 * expired. That's deliberate: a live clock is what stops an offline panel from
 * reading as dead hardware.
 *
 * Beneath the dial sits the voice channel. Putting it here rather than in a
 * floating overlay means the tall tile earns its height, and it keeps every
 * signal about "is Jarvis listening / what did it hear" in one place instead
 * of scattering them across the panel.
 */

import { ReactorDial } from '../../components/ReactorDial'
import { voice } from '../../voice'
import { connection } from '../../state'
import type { Widget, WidgetProps } from '../../types'
import './clock.css'

interface Data {
  weekday: string
  date: string
}

function VoiceChannel() {
  const { listening, transcript, reply, supported, error } = voice.value

  if (listening) {
    return (
      <div class="clock-voice">
        <span class="label gold">Listening</span>
        {transcript && <p class="body clock-heard">“{transcript}”</p>}
      </div>
    )
  }

  if (reply) {
    return (
      <div class="clock-voice">
        {transcript && <span class="stamp">“{transcript}”</span>}
        <p class="body arc clock-reply">{reply}</p>
      </div>
    )
  }

  if (!supported && error) {
    return (
      <div class="clock-voice">
        <span class="label clock-mute">Voice offline</span>
        <span class="stamp">{error}</span>
      </div>
    )
  }

  return (
    <div class="clock-voice">
      <span class="stamp clock-idle">
        {connection.value === 'offline' ? 'no link to jarvis' : 'say “hey jarvis”'}
      </span>
    </div>
  )
}

function Card({ slice }: WidgetProps<Data>) {
  // Falls back to the tablet's own clock: this tile must keep reading correctly
  // even when the Pi has never answered.
  const local = new Date()
  const weekday =
    slice.data?.weekday ?? local.toLocaleDateString(undefined, { weekday: 'long' })
  const date =
    slice.data?.date ?? local.toLocaleDateString(undefined, { day: 'numeric', month: 'long' })

  return (
    <div class="clock-stack">
      <div class="clock-dial">
        <ReactorDial listening={voice.value.listening} amplitude={voice.value.amplitude} />
      </div>
      <div class="clock-date">
        <span class="label">{weekday}</span>
        <span class="stamp">{date}</span>
      </div>
      <VoiceChannel />
    </div>
  )
}

export default {
  slug: 'clock',
  size: { w: 1, h: 2 },
  Card,
} satisfies Widget
