import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend (FastAPI + Pipecat) runs on :7860. Proxying keeps the browser on one
// origin, so no CORS or secrets in the frontend.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:7860',
    },
  },
})
