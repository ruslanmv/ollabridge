import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  base: './',        // CRITICAL: Ensures assets link correctly on GitHub Pages
  build: {
    outDir: 'dist',  // Standard build folder
  }
})