import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server is loopback-only for the same reason server.py binds 127.0.0.1:
// it proxies /api, which serves locally indexed Esports Foundation PDFs.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.{js,jsx}'],
  },
})
