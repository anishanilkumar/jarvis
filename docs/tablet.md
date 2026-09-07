# The tablet

Stock Android throughout — every step here is app configuration. No root, no
custom ROM, nothing a factory reset can't undo.

## 1. Kiosk browser

**Webview Kiosk** — F-Droid, `uk.nktnet.webviewkiosk`, AGPL-3.0. Set the start
URL to your `dash.` host, then:

- **Lock Task Mode (pin)** so the home screen, status bar and other apps are
  unreachable from the wall.
- **Set it as the default launcher.** A reboot then lands straight back on the
  dashboard with no human involved.
- **Protect its settings** with a password or biometrics. Otherwise the first
  guest to prod the wall out of curiosity leaves it on a settings screen.
- **Microphone: only once `[voice] enabled = true`.** With voice off the panel
  never calls `getUserMedia`, so the grant is dead weight. Screen wake comes
  from the wake word, so the camera is never needed either way.
- **Check it reloads after a network drop.** It holds `ACCESS_NETWORK_STATE`
  for exactly this, and the panel's own reconnect logic covers the rest.

Overnight screen blanking is *not* evidently one of its settings — verify
before relying on it, and fall back to Android's bedtime mode if it isn't there.

> Earlier versions of these notes recommended **WallPanel**. That was wrong on
> two counts: it is not on F-Droid (it shipped via Play and GitHub releases),
> and upstream — `thecowan/wallpanel-android`, which `thanksmister/` forks —
> has had no commits since October 2021. Use it only if you already have it
> running.

## 2. Home Assistant Companion

Needed for one thing: receiving `command_activity` to launch YouTube Music.
Skip it entirely if you don't want the music tile.

F-Droid ships the **minimal** flavour,
`io.homeassistant.companion.android.minimal` — no Play Services, therefore no
FCM, so notifications arrive over Home Assistant's local websocket push
instead. For a tablet that never leaves the LAN that's the better build anyway,
but **confirm `command_activity` actually arrives** before wiring the music
tile to it.

Once the tablet registers, read the real notify service name off HA and put it
in `[homeassistant] notify_service`. The value in `jarvis.example.toml` is a
guess at what HA will name your device, and a mismatch makes the music tile
silently do nothing rather than show an error.

## 3. Vendor settings

- **MagicOS 8 will fight you — this is the step people miss.** Settings →
  Battery → *App launch* → set both apps to Manual and enable all three
  (auto-launch, secondary launch, run in background); disable battery
  optimisation. Skip this and the kiosk dies overnight with no error.
- Developer options → *Stay awake while charging*; lock screen off;
  auto-rotate off; auto-update off.
- **Battery:** holding the cell at 100% forever degrades and eventually swells
  it. Put the charger on a timer, and mount it so the back still opens.
