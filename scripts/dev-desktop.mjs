import { root, python, loadEnv, run, healthy } from './runtime.mjs'
import { createConnection } from 'node:net'
import { fileURLToPath } from 'node:url'
import { bootstrap } from './bootstrap-dev.mjs'
import { existsSync, readFileSync, writeFileSync, unlinkSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { parseArgs } from 'node:util'
import { resolveDesktopDevProfile } from './desktop-dev-profile.mjs'
const { values } = parseArgs({ options: {
  channel: { type: 'string', default: 'test' },
  plan: { type: 'boolean', default: false },
  'setup-only': { type: 'boolean', default: false },
} })
loadEnv()
const baseConfig = JSON.parse(readFileSync(join(root, 'frontend/src-tauri/tauri.conf.json'), 'utf8'))
const profile = resolveDesktopDevProfile({ channel: values.channel, env: process.env, version: baseConfig.version })
if (values.plan) {
  console.log(JSON.stringify({ ...profile, backend: 'http://127.0.0.1:8900', frontend: 'http://127.0.0.1:3100' }, null, 2))
  process.exit(0)
}
if (values['setup-only']) {
  bootstrap()
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
  if (running) { console.error('VINote 开发实例已运行。切换渠道前，请在原终端按 Ctrl+C 退出；当前实例未被修改。'); process.exit(1) }
  unlinkSync(lock)
}
writeFileSync(lock, String(process.pid), { flag: 'wx' })
process.on('exit', () => {
  try { if (readFileSync(lock, 'utf8') === String(process.pid)) unlinkSync(lock) } catch {}
})
process.env.VILAB_SERVER_URL = profile.server
process.env.LANGFUSE_TRACING_ENVIRONMENT = profile.tracingEnvironment
process.env.LANGFUSE_RELEASE = profile.release
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
  bootstrap()
  loadEnv() // First checkout may have created .env during bootstrap.
  // Never reuse an unknown backend: it may belong to the other dev channel.
  {
    const occupied = await new Promise(resolve => {
      const s = createConnection({ host: '127.0.0.1', port: 8900 })
      s.on('connect', () => { s.destroy(); resolve(true) })
      s.on('error', () => resolve(false))
    })
    if (occupied) throw new Error('端口 8900 已被占用，无法确认其服务配置。请先退出已有 VINote 后端，再启动当前渠道；不会自动结束其他进程。')
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
    console.log(`[${profile.productName}] 界面热更新: http://127.0.0.1:3100; VINote API: http://127.0.0.1:8900; 模型服务: ${profile.server}; Langfuse: ${profile.tracingEnvironment}`)
    const config = { productName: profile.productName, identifier: profile.identifier,
      app: { windows: baseConfig.app.windows.map(window => ({ ...window, title: profile.productName })) } }
    start(process.execPath, [fileURLToPath(new URL('../frontend/node_modules/@tauri-apps/cli/tauri.js', import.meta.url)), 'dev', '--config', JSON.stringify(config)], { cwd: `${root}/frontend` })
  }
} catch (error) { console.error(error.message); shutdown(1) }
