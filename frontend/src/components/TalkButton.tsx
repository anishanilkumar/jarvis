/**
 * Tap-to-talk, and the panel's voice feedback surface.
 *
 * The wake word is best-effort — the HONOR Pad's built-in microphone is
 * reliable at about a metre and degrades in a noisy kitchen. This button is
 * the path that always works, and it's why the panel doesn't need a mic array
 * to be usable.
 */

import { client, voice } from '../voice'
import './talk.css'

export function TalkButton() {
  const { listening, transcript, reply, error, supported } = voice.value

  return (
    <>
      {(transcript || reply) && (
        <div class="voice-caption">
          {transcript && <div class="voice-heard stamp">“{transcript}”</div>}
          {reply && <div class="voice-reply body">{reply}</div>}
        </div>
      )}

      <button
        class="talk"
        data-listening={listening}
        data-broken={!supported}
        onClick={(event) => {
          event.stopPropagation()
          client.push()
        }}
        aria-label={listening ? 'Listening' : 'Tap to talk'}
        title={error ?? undefined}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <rect x="9" y="2" width="6" height="12" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0" stroke-linecap="round" />
          <line x1="12" y1="18" x2="12" y2="22" stroke-linecap="round" />
        </svg>
      </button>
    </>
  )
}
