import { root, python, loadEnv, run, healthy } from './runtime.mjs'
import { createConnection } from 'node:net'
import { fileURLToPath } from 'node:url'
import { bootstrap } from './bootstrap-dev.mjs'
import { existsSync, readFileSync, writeFileSync, unlinkSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { parseArgs } from 'node:util'
import { resolveDesktopDevProfile } from './desktop-dev-profile.mjs'
import { assertProjectVersion } from './project-version.mjs'
const { values } = parseArgs({ options: {
  target: { type: 'string', default: 'desktop' },
  environment: { type: 'string', default: 'lan' },
  plan: { type: 'boolean', default: false },
  'setup-only': { type: 'boolean', default: false },
} })
if (!['desktop', 'web'].includes(values.target)) throw new Error('Target must be desktop or web')
const desktop = values.target === 'desktop'
loadEnv()
assertProjectVersion()
const baseConfig = JSON.parse(readFileSync(join(root, 'frontend/src-tauri/tauri.conf.json'), 'utf8'))
const profile = resolveDesktopDevProfile({ environment: values.environment, version: baseConfig.version })
if (values.plan) {
  console.log(JSON.stringify({ ...profile,
    ...(!desktop ? { productName: 'VINote Web Dev', identifier: undefined, tracingEnvironment: null } : {}),
    target: values.target, backend: 'http://127.0.0.1:8900', frontend: 'http://127.0.0.1:3100' }, null, 2))
  process.exit(0)
}
if (values['setup-only']) {
  bootstrap({ desktop })
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
  if (running) { console.error('VINote 桌面或网页开发实例已运行。切换渠道前，请在原终端按 Ctrl+C 退出；当前实例未被修改。'); process.exit(1) }
  unlinkSync(lock)
}
writeFileSync(lock, String(process.pid), { flag: 'wx' })
process.on('exit', () => {
  try { if (readFileSync(lock, 'utf8') === String(process.pid)) unlinkSync(lock) } catch {}
})
process.env.VILAB_SERVER_URL = profile.server
process.env.LANGFUSE_TRACING_ENVIRONMENT = profile.tracingEnvironment
process.env.LANGFUSE_RELEASE = profile.release
process.env.VINOTE_DESKTOP_RUNTIME = String(desktop)
process.env.VITE_API_BASE_URL = ''
process.env.TAURI_DEV_HOST = '127.0.0.1'
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
  // Windows UI tooling shares the invoking terminal. Only the backend needs
  // an isolated console, created hidden by windows-backend-dev.py below.
  const child = run(command, args, { detached: process.platform !== 'win32', ...options })
  children.push(child)
  child.on('exit', code => shutdown(code ?? 1))
  child.on('error', () => shutdown(1))
  return child
}
process.on('SIGINT', () => shutdown())
process.on('SIGTERM', () => shutdown())
try {
  // Both ports must belong to this launcher; never reuse another mode's services.
  for (const port of [8900, 3100]) {
    const occupied = await new Promise(resolve => {
      const socket = createConnection({ host: '127.0.0.1', port })
      const finish = occupied => { socket.destroy(); resolve(occupied) }
      socket.setTimeout(2000)
      socket.once('connect', () => finish(true))
      socket.once('error', () => finish(false))
      socket.once('timeout', () => finish(true))
    })
    if (occupied) throw new Error(`端口 ${port} 已被占用，请先退出已有服务；不会复用或结束其他进程。`)
  }
  bootstrap({ desktop })
  loadEnv() // First checkout may have created .env during bootstrap.
  {
    const backendArgs = ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8900', '--reload']
    if (process.platform === 'win32') backendArgs.unshift(join(root, 'scripts/windows-backend-dev.py'))
    start(python(), backendArgs)
    for (let i = 0; i < 60 && !closing; i++) {
      if (await healthy('http://127.0.0.1:8900/healthz')) break
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    if (!await healthy('http://127.0.0.1:8900/healthz')) throw new Error('VINote backend did not start; check the error above.')
  }
  if (!closing) {
    console.log(`[${values.target}/${profile.environment}] 界面: http://127.0.0.1:3100; VINote API: http://127.0.0.1:8900; VILab: ${profile.server}; Langfuse: ${desktop ? profile.tracingEnvironment : 'disabled'}`)
    const viteArgs = [join(root, 'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', '3100', '--strictPort']
    if (!desktop) viteArgs.push('--open')
    start(process.execPath, viteArgs, { cwd: join(root, 'frontend') })
    for (let i = 0; i < 60 && !closing; i++) {
      if (await healthy('http://127.0.0.1:3100/@vite/client')) break
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    if (!closing && !await healthy('http://127.0.0.1:3100/@vite/client')) throw new Error('VINote frontend did not start; check the error above.')
    if (desktop && !closing) {
      // Vite is owned by this launcher; suppress Tauri's separate dev-server hook.
      const config = { productName: profile.productName, identifier: profile.identifier,
        build: { beforeDevCommand: '' },
        app: { windows: baseConfig.app.windows.map(window => ({ ...window, title: profile.productName })) } }
      start(process.execPath, [fileURLToPath(new URL('../frontend/node_modules/@tauri-apps/cli/tauri.js', import.meta.url)), 'dev', '--config', JSON.stringify(config)], { cwd: join(root, 'frontend') })
    }
  }
} catch (error) { console.error(error.message); shutdown(1) }
