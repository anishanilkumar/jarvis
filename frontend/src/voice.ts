/**
 * Microphone capture on the tablet.
 *
 * Why this exists at all: `SpeechRecognition` does not exist in Android
 * WebView — it's a Chrome-app feature — so the browser cannot transcribe for
 * us. What the WebView *can* do is `getUserMedia`, so we capture raw audio,
 * gate it locally, and let the Pi run the pipeline.
 *
 * The local gate matters: only speech segments leave the tablet, and nothing
 * leaves the house until the Pi matches "hey jarvis". Silence is never
 * transmitted.
 *
 * getUserMedia requires a secure context. Over plain http:// on the LAN the
 * microphone is denied with no useful error, which is why the panel is served
 * over HTTPS with a real certificate.
 */

import { signal } from '@preact/signals'

export interface VoiceState {
  supported: boolean
  listening: boolean
  /** 0..1, drives the reactor's inner ring. */
  amplitude: number
  transcript: string | null
  reply: string | null
  error: string | null
}

export const voice = signal<VoiceState>({
  supported: false,
  listening: false,
  amplitude: 0,
  transcript: null,
  reply: null,
  error: null,
})

const SAMPLE_RATE = 16000
/** Speech below this RMS is treated as room tone and not transmitted. */
const SPEECH_FLOOR = 0.012
/** Keep streaming this long after speech stops, so trailing words survive. */
const HANGOVER_MS = 700

function patch(next: Partial<VoiceState>): void {
  voice.value = { ...voice.value, ...next }
}

function downsample(input: Float32Array, from: number, to: number): Int16Array {
  const ratio = from / to
  const out = new Int16Array(Math.floor(input.length / ratio))
  for (let i = 0; i < out.length; i++) {
    const sample = input[Math.floor(i * ratio)]
    // Clamp before scaling: a clipped sample wrapping to full-negative is an
    // audible click, and openWakeWord sees it as a transient.
    out[i] = Math.max(-1, Math.min(1, sample)) * 0x7fff
  }
  return out
}

export class VoiceClient {
  private socket: WebSocket | null = null
  private context: AudioContext | null = null
  private stream: MediaStream | null = null
  private lastSpeech = 0
  private muted = false

  async start(): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) {
      patch({ supported: false, error: 'no microphone API (is this a secure context?)' })
      return
    }

    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
    } catch (error) {
      patch({ supported: false, error: `microphone denied: ${String(error)}` })
      return
    }

    patch({ supported: true, error: null })
    this.openSocket()

    this.context = new AudioContext({ sampleRate: SAMPLE_RATE })
    const source = this.context.createMediaStreamSource(this.stream)

    // ScriptProcessor is deprecated but universally present in Android
    // WebView; AudioWorklet needs a separate module fetch that the service
    // worker would also have to cache. Deliberate trade for a fixed device.
    const node = this.context.createScriptProcessor(2048, 1, 1)
    source.connect(node)
    node.connect(this.context.destination)

    node.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0)

      let sum = 0
      for (let i = 0; i < input.length; i++) sum += input[i] * input[i]
      const rms = Math.sqrt(sum / input.length)

      patch({ amplitude: Math.min(1, rms * 12) })

      // The tablet has no acoustic echo cancellation against its own speaker,
      // so while Jarvis is talking we stop listening rather than hear ourselves.
      if (this.muted) return

      const now = Date.now()
      if (rms > SPEECH_FLOOR) this.lastSpeech = now
      const speaking = now - this.lastSpeech < HANGOVER_MS
      if (!speaking) return

      if (this.socket?.readyState === WebSocket.OPEN) {
        this.socket.send(downsample(input, this.context!.sampleRate, SAMPLE_RATE).buffer as ArrayBuffer)
      }
    }
  }

  private openSocket(): void {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
    const socket = new WebSocket(`${scheme}://${location.host}/voice`)
    socket.binaryType = 'arraybuffer'

    socket.addEventListener('message', (event) => {
      if (typeof event.data !== 'string') {
        void this.play(event.data as ArrayBuffer)
        return
      }
      const message = JSON.parse(event.data)
      switch (message.type) {
        case 'wake':
          patch({ listening: true, transcript: null, reply: null })
          break
        case 'transcript':
          patch({ transcript: message.text })
          break
        case 'reply':
          patch({ listening: false, reply: message.text })
          break
        case 'idle':
          patch({ listening: false })
          break
      }
    })

    // Unlike EventSource, a WebSocket does not reconnect itself. On a panel
    // meant to run for months untouched, that has to be handled explicitly.
    socket.addEventListener('close', () => {
      this.socket = null
      patch({ listening: false })
      setTimeout(() => this.openSocket(), 3000)
    })

    this.socket = socket
  }

  private async play(audio: ArrayBuffer): Promise<void> {
    if (!this.context) return
    this.muted = true
    try {
      const buffer = await this.context.decodeAudioData(audio.slice(0))
      const source = this.context.createBufferSource()
      source.buffer = buffer
      source.connect(this.context.destination)
      source.onended = () => {
        this.muted = false
        this.lastSpeech = 0
      }
      source.start()
    } catch {
      this.muted = false
    }
  }

  /** Tap-to-talk: the always-works path when the wake word doesn't hear you. */
  push(): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: 'push_to_talk' }))
      patch({ listening: true })
    }
  }
}

export const client = new VoiceClient()
