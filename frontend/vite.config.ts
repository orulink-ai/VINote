import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { captureDiagnosticsPlugin } from './captureDiagnosticsPlugin'

const host = process.env.TAURI_DEV_HOST

export default defineConfig({
  base: process.env.VINOTE_DESKTOP_BUILD ? './' : '/',
  clearScreen: false,
  envPrefix: ['VITE_', 'TAURI_ENV_*'],
  plugins: [react(), captureDiagnosticsPlugin()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (
            id.includes('react-syntax-highlighter') ||
            id.includes('/refractor/') ||
            id.includes('/highlight.js/')
          ) {
            return 'syntax-highlighter'
          }

          if (
            id.includes('react-markdown') ||
            id.includes('/remark-') ||
            id.includes('/mdast-') ||
            id.includes('/micromark') ||
            id.includes('/unist-') ||
            id.includes('/hast-')
          ) {
            return 'markdown'
          }

          return undefined
        },
      },
    },
  },
  server: {
    port: 3100,
    strictPort: true,
    host: host || '127.0.0.1',
    hmr: host
      ? {
          protocol: 'ws',
          host,
          port: 3100,
        }
      : undefined,
    watch: {
      ignored: ['**/src-tauri/**'],
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8900',
        changeOrigin: true,
      },
    },
  },
})
