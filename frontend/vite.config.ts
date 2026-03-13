import { defineConfig, type ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const API_TARGET = 'http://localhost:11435'

/** Shared proxy options — silences noisy errors when backend is down. */
const proxyOpts: ProxyOptions = {
  target: API_TARGET,
  changeOrigin: true,
  configure: (proxy) => {
    proxy.on('error', (_err, _req, res) => {
      // Return a clean 502 instead of letting Vite log the ECONNREFUSED
      if (res && 'writeHead' in res && !res.headersSent) {
        (res as import('http').ServerResponse).writeHead(502, { 'Content-Type': 'application/json' })
        ;(res as import('http').ServerResponse).end(JSON.stringify({ error: 'Backend offline' }))
      }
    })
  },
}

export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss()],
  // In production the SPA is served at /ui/ by the backend
  base: command === 'build' ? '/ui/' : '/',
  server: {
    port: 3000,
    proxy: {
      '/health': proxyOpts,
      '/v1': proxyOpts,
      '/admin': proxyOpts,
      '/pair': proxyOpts,
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
}))
