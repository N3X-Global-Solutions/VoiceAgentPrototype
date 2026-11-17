import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

// The backend (FastAPI + Pipecat) runs on :7860. Proxying keeps the browser on one
// origin, so the session cookie works and no secrets reach the frontend.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    proxy: {
      '/api': 'http://localhost:7860',
    },
  },
})
