import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      // Tailwind/shadcn convention. Only the dashboard feature uses it; the
      // rest of the app keeps its relative imports.
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  optimizeDeps: {
    // maplibre-gl loads its own worker via `new Worker(new URL(...))`, which
    // the dep optimizer can't rewrite — it pre-bundles maplibre-gl.mjs into
    // .vite/deps but never emits the sibling maplibre-gl-worker.mjs the
    // bundled copy still references, so the worker 404s at runtime. Ship
    // maplibre-gl unbundled (it's already ESM) so the worker URL it
    // constructs points at the real file in node_modules.
    exclude: ['maplibre-gl'],
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
