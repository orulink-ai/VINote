import type { Plugin } from 'vite'
import { appendFileSync, mkdirSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'

/** Receive bounded diagnostic events through the existing local Vite connection. */
export function captureDiagnosticsPlugin(): Plugin {
  return {
    name: 'vinote-capture-diagnostics',
    apply: 'serve',
    configureServer(server) {
      const directory = path.resolve(server.config.root, '../data')
      const filename = path.join(directory, 'desktop-capture.log')
      server.ws.on('vinote:capture-diagnostic', (data) => {
        if (!data || typeof data !== 'object') return
        const entry: Record<string, string | number | boolean> = {}
        for (const key of ['stage', 'time', 'elapsedMs', 'errorName', 'errorMessage', 'audioTracks', 'videoTracks', 'screen', 'systemAudio', 'selectedMicrophone', 'bytes', 'mimeType']) {
          const value = data[key]
          if (typeof value === 'string') entry[key] = value.slice(0, 500)
          else if (typeof value === 'number' || typeof value === 'boolean') entry[key] = value
        }
        if (typeof entry.stage !== 'string') return
        try {
          mkdirSync(directory, { recursive: true })
          try { if (statSync(filename).size > 1024 * 1024) writeFileSync(filename, '') } catch { /* First event. */ }
          appendFileSync(filename, JSON.stringify(entry) + '\n')
        } catch (error) { server.config.logger.warn(`Capture diagnostic log unavailable: ${String(error)}`) }
      })
    },
  }
}
