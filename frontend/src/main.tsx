import { render } from 'preact'
import { effect } from '@preact/signals'
import { Panel } from './layout'
import { config, connection, start } from './state'
import { client, voice } from './voice'
import { TalkButton } from './components/TalkButton'
import './styles/tokens.css'

/**
 * Connection state is published to the document root so the offline palette
 * swap in tokens.css applies everywhere at once — no component needs to know
 * it is rendering an offline state.
 */
effect(() => {
  document.documentElement.dataset.connection = connection.value
})

/** Voice starts only once the Pi says it's enabled, so a panel with the voice
 *  service switched off never prompts for the microphone. */
effect(() => {
  if (config.value?.voice_enabled && !voice.value.supported && !voice.value.error) {
    void client.start()
  }
})

function App() {
  return (
    <>
      <Panel />
      {config.value?.voice_enabled && <TalkButton />}
    </>
  )
}

void start()
render(<App />, document.getElementById('panel')!)

// Registered last: the panel must be interactive before we worry about making
// it survive a reboot.
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js')
  })
}
