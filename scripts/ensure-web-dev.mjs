import { spawn } from 'node:child_process'
import { createConnection } from 'node:net'
import { fileURLToPath } from 'node:url'

const frontendDir = fileURLToPath(new URL('../frontend/', import.meta.url))
const viteEntry = fileURLToPath(new URL('../frontend/node_modules/vite/bin/vite.js', import.meta.url))
const origin = 'http://127.0.0.1:3100'

async function isViteRunning() {
  try {
    const response = await fetch(`${origin}/@vite/client`, {
      signal: AbortSignal.timeout(2000),
    })
    return response.ok && (await response.text()).includes('createHotContext')
  } catch {
    return false
  }
}

function isPortInUse() {
  return new Promise((resolve) => {
    const socket = createConnection({ host: '127.0.0.1', port: 3100 })
    const finish = (inUse) => {
      socket.destroy()
      resolve(inUse)
    }
    socket.setTimeout(2000)
    socket.once('connect', () => finish(true))
    socket.once('error', () => finish(false))
    socket.once('timeout', () => finish(true))
  })
}

if (await isViteRunning()) {
  console.log(`[INFO] Reusing existing Vite dev server at ${origin}`)
} else if (await isPortInUse()) {
  console.error('[ERROR] Port 3100 is occupied by a non-Vite service. Free the port and retry.')
  process.exitCode = 1
} else {
  const child = spawn(process.execPath, [viteEntry, '--host', '127.0.0.1', '--port', '3100'], {
    cwd: frontendDir,
    stdio: 'inherit',
    windowsHide: true,
  })
  child.once('error', (error) => {
    console.error(`[ERROR] Could not start Vite: ${error.message}`)
    process.exitCode = 1
  })
  child.once('exit', (code) => { process.exitCode = code ?? 1 })
  for (const signal of ['SIGINT', 'SIGTERM']) {
    process.once(signal, () => child.kill(signal))
  }
}
