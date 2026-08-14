/**
 * The signature instrument.
 *
 * One element carrying three real signals rather than three decorations:
 *   - the outer engraved ring is the clock (60 minute ticks, a sweep index)
 *   - the inner ring answers the microphone while voice is listening
 *   - the ring's *continuity* is the connection: solid when live, broken into
 *     dashes and desaturated when the Pi is unreachable
 *
 * Because the dial is the only thing that moves at rest, movement anywhere on
 * this panel means something.
 */

import { connection, now } from '../state'
import './reactor.css'

interface Props {
  listening: boolean
  /** 0..1 microphone level, only meaningful while listening. */
  amplitude: number
}

const TICKS = 60

export function ReactorDial({ listening, amplitude }: Props) {
  const moment = new Date(now.value)
  const minute = moment.getMinutes()
  const second = moment.getSeconds()
  const offline = connection.value === 'offline'

  const hh = String(moment.getHours()).padStart(2, '0')
  const mm = String(minute).padStart(2, '0')

  // The voice ring grows with level but never collapses to nothing while
  // listening — a ring that vanishes on a quiet syllable reads as "it stopped
  // hearing me", which is the opposite of the feedback this is for.
  const voiceRadius = 52 + amplitude * 10
  const voiceWidth = 2 + amplitude * 6

  return (
    <div class="reactor" data-listening={listening} data-offline={offline}>
      <svg viewBox="0 0 200 200" class="reactor-svg" aria-hidden="true">
        {/* Engraved minute ticks. Every fifth is longer and brighter — the
            index marks you actually read position against. */}
        <g class="ticks">
          {Array.from({ length: TICKS }, (_, i) => {
            const major = i % 5 === 0
            const angle = (i / TICKS) * 360 - 90
            const rad = (angle * Math.PI) / 180
            const outer = 94
            const inner = major ? 84 : 89
            return (
              <line
                key={i}
                x1={100 + Math.cos(rad) * inner}
                y1={100 + Math.sin(rad) * inner}
                x2={100 + Math.cos(rad) * outer}
                y2={100 + Math.sin(rad) * outer}
                class={major ? 'tick major' : 'tick'}
                data-passed={i <= minute}
              />
            )
          })}
        </g>

        {/* The connection ring. Its dash pattern is the state — nothing else
            on the panel needs to announce "offline" in words. */}
        <circle cx="100" cy="100" r="74" class="ring" />

        {/* Sweep index: the only idle motion on the whole panel. */}
        <line
          x1="100"
          y1="100"
          x2="100"
          y2="32"
          class="sweep"
          style={{ transform: `rotate(${(second / 60) * 360}deg)` }}
        />

        <circle
          cx="100"
          cy="100"
          r={voiceRadius}
          class="voice-ring"
          style={{ strokeWidth: voiceWidth }}
        />
      </svg>

      <div class="reactor-face">
        <div class="reactor-time">
          {hh}
          <span class="colon" data-tick={second % 2 === 0}>
            :
          </span>
          {mm}
        </div>
        {/* Status only. The date lives outside the ring — at this dial size a
            full date string is wider than the inner circle and would cross the
            ring, which reads as a rendering bug rather than a design. */}
        {listening && <div class="reactor-status label">Listening</div>}
        {offline && !listening && <div class="reactor-status label offline">Signal lost</div>}
      </div>
    </div>
  )
}
