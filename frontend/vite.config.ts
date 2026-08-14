import { defineConfig } from 'vite'
import preact from '@preact/preset-vite'

export default defineConfig({
  plugins: [preact()],
  build: {
    // The panel is one screen on one known device; a single bundle beats
    // code-splitting round-trips on a Snapdragon 680 over Wi-Fi.
    target: 'es2020',
    rollupOptions: {
      output: { manualChunks: undefined },
    },
  },
  server: {
    host: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8140', changeOrigin: true },
      '/voice': { target: 'ws://127.0.0.1:8141', ws: true },
    },
  },
})
