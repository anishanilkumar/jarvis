/**
 * The public dashboard's build, kept entirely separate from the wall's.
 *
 * Not a second entry in vite.config.ts, for three reasons that all end badly:
 *
 *  - Two entries share chunks. The wall's update.ts decides whether it is
 *    running current code by comparing its own module URL against the first
 *    <script src> in a freshly fetched /index.html; a change that moved only a
 *    shared chunk's hash would leave that check saying "current" while the wall
 *    ran old code. The check would be lying, quietly, forever.
 *  - deploy.sh rsyncs frontend/dist/ to the Pi with --delete. One dist/ would
 *    ship this entire site to the wall on every deploy.
 *  - `manualChunks: undefined` declines to group chunks manually; it does not
 *    disable splitting. The wall's single-bundle property only holds while
 *    there is one input.
 *
 * So: same source tree, same tokens, two builds that cannot touch each other.
 */

import { defineConfig } from 'vite'
import preact from '@preact/preset-vite'

export default defineConfig({
  plugins: [preact()],
  build: {
    target: 'es2020',
    outDir: 'dist-public',
    emptyOutDir: true,
    rollupOptions: {
      input: 'site.html',
      output: { manualChunks: undefined },
    },
  },
  server: {
    port: 5174,
    host: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8768', changeOrigin: true },
    },
  },
})
