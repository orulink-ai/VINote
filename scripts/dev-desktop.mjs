import { root, python, loadEnv, run, healthy } from './runtime.mjs'
import { createConnection } from 'node:net'
import { fileURLToPath } from 'node:url'
import { bootstrap } from './bootstrap-dev.mjs'
import { existsSync, readFileSync, writeFileSync, unlinkSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
bootstrap()
loadEnv()
if (process.argv.includes('--setup-only')) {
  console.log('VINote first-run setup is ready.')
  process.exit(0)
}
mkdirSync(join(root, 'data'), { recursive: true })
const lock = join(root, 'data/desktop-dev.pid')
if (existsSync(lock)) {
  const previous = Number(readFileSync(lock, 'utf8'))
  let running = false
  if (Number.isInteger(previous) && previous > 0) {
    try { process.kill(previous, 0); running = true } catch {}
  }
  if (running) { console.log('VINote desktop development is already running. Use the existing window.'); process.exit(0) }
  unlinkSync(lock)
}
writeFileSync(lock, String(process.pid), { flag: 'wx' })
process.on('exit', () => {
  try { if (readFileSync(lock, 'utf8') === String(process.pid)) unlinkSync(lock) } catch {}
})
process.env.VILAB_SERVER_URL ||= 'http://192.168.1.143:9876'
process.env.VINOTE_DESKTOP_RUNTIME = 'true'
const children = []
let closing = false
function shutdown(code = 0) {
  if (closing) return
  closing = true
  process.exitCode = code
  for (const child of children) {
    if (child.exitCode !== null || !child.pid) continue
    if (process.platform === 'win32') run('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'])
    else { try { process.kill(-child.pid, 'SIGTERM') } catch {} }
  }
}
function start(command, args, options = {}) {
  // Isolate Windows consoles too: Uvicorn reload sends a console control event
  // that must not terminate the sibling Tauri desktop process.
  const child = run(command, args, { detached: true, ...options })
  children.push(child)
  child.on('exit', code => shutdown(code ?? 1))
  child.on('error', () => shutdown(1))
  return child
}
process.on('SIGINT', () => shutdown())
process.on('SIGTERM', () => shutdown())
try {
  if (!await healthy('http://127.0.0.1:8900/healthz')) {
    const occupied = await new Promise(resolve => {
      const s = createConnection({ host: '127.0.0.1', port: 8900 })
      s.on('connect', () => { s.destroy(); resolve(true) })
      s.on('error', () => resolve(false))
    })
    if (occupied) throw new Error('Port 8900 is occupied by an unhealthy service. Stop it before retrying.')
    start(python(), ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8900', '--reload'])
    for (let i = 0; i < 60 && !closing; i++) {
      if (await healthy('http://127.0.0.1:8900/healthz')) break
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    if (!await healthy('http://127.0.0.1:8900/healthz')) throw new Error('VINote backend did not start; check the error above.')
  }
  if (!closing) {
    console.log(`VINote backend: http://127.0.0.1:8900; configured cloud: ${process.env.VILAB_SERVER_URL}`)
    start(process.execPath, [fileURLToPath(new URL('../frontend/node_modules/@tauri-apps/cli/tauri.js', import.meta.url)), 'dev'], { cwd: `${root}/frontend` })
  }
} catch (error) { console.error(error.message); shutdown(1) }
