# Bundled fonts

Self-hosted rather than fetched from a CDN: a wall panel that loses its typeface
when the internet drops is not offline-capable. Only the Latin subsets of the
Latin faces are here, which is why those total ~68 KB.

All are licensed under the **SIL Open Font License 1.1**, which permits
redistribution alongside this project. None is covered by the repository's
MIT licence.

| File | Family | Source | Licence |
|---|---|---|---|
| `archivo-var.woff2` | Archivo (variable, 400–700) | https://fonts.google.com/specimen/Archivo | OFL-1.1 |
| `plexmono-400.woff2`, `plexmono-500.woff2` | IBM Plex Mono | https://fonts.google.com/specimen/IBM+Plex+Mono | OFL-1.1 |
| `Manjari-Regular.woff2`, `Manjari-Bold.woff2` | Manjari 2.200 | https://gitlab.com/smc/fonts/manjari | OFL-1.1 |

## Adding a script

Manjari — by [Swathanthra Malayalam Computing](https://smc.org.in) — is here
because the headlines feed is Malayalam, and Latin faces have no glyphs for that
script at all: without it the tile renders rows of tofu, not a worse-looking
headline. The upstream project publishes woff2 builds directly, so these are its
own files, not a re-render.

The two Manjari files are ~185 KB together, which is more than everything else
combined. They are declared in `tokens.css` with a `unicode-range` covering the
Malayalam block, so a panel showing no Malayalam never downloads them. Do the
same for any script you add — the range is what keeps the cost off panels that
don't need it.

Full licence text: https://openfontlicense.org/
