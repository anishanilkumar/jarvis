/**
 * "Add to home screen", where the browser lets a page offer it.
 *
 * Chrome (Android and desktop) fires `beforeinstallprompt` when the page is
 * installable and hands over an event that can show the prompt later; this
 * keeps it until the reader asks. Safari has no such event — on an iPhone the
 * way in is Share, then Add to Home Screen — so there the link never appears,
 * rather than appearing and doing nothing.
 */

import { signal } from '@preact/signals'

interface InstallPrompt extends Event {
  prompt(): Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

export const installable = signal<InstallPrompt | null>(null)

window.addEventListener('beforeinstallprompt', (event) => {
  // Without this Chrome may show its own mini-infobar on top of the page.
  event.preventDefault()
  installable.value = event as InstallPrompt
})

window.addEventListener('appinstalled', () => {
  installable.value = null
})

export async function install(): Promise<void> {
  const prompt = installable.value
  if (!prompt) return
  await prompt.prompt()
  // One use per event; Chrome sends a fresh one if it is dismissed and the page
  // stays installable.
  installable.value = null
}
