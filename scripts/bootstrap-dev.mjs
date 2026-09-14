import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { randomBytes, createHash } from 'node:crypto'
import { root } from './runtime.mjs'

function exec(command, args) {
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit', windowsHide: true })
  if (result.error || result.status !== 0) throw new Error(`Setup failed: ${command}. Check network/toolchain and retry yarn client:dev.`)
}

export function bootstrap() {
  if (Number(process.versions.node.split('.')[0]) < 22) throw new Error('Node.js 22 or newer is required.')
  if (spawnSync('cargo', ['--version'], { windowsHide: true }).status !== 0) throw new Error('Install Rust and platform build tools first (Windows C++ Build Tools / macOS Xcode Command Line Tools).')
  if (!existsSync(join(root, 'frontend/node_modules/@tauri-apps/cli/tauri.js'))) {
    console.log('[setup] Installing frontend dependencies...')
    // Yarn invokes Node with its own executable path on Windows and macOS.
    const npm = [join(dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js'),
      join(dirname(process.execPath), '../lib/node_modules/npm/bin/npm-cli.js')].find(existsSync)
    if (npm) exec(process.execPath, [npm, 'ci', '--prefix', join(root, 'frontend')])
    else {
      const yarn = process.env.npm_execpath
      if (!yarn) throw new Error('Run yarn client:dev to install missing frontend dependencies automatically.')
      exec(process.execPath, [yarn, '--cwd', join(root, 'frontend'), 'install'])
    }
  }
  const py = process.env.VINOTE_PYTHON || join(root, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python')
  if (!process.env.VINOTE_PYTHON && !existsSync(py)) {
    const candidates = process.platform === 'win32' ? [['py', '-3'], ['python'], ['python3']] : [['python3'], ['python']]
    const found = candidates.find(([command, ...args]) => spawnSync(command, [...args, '-c', 'import sys; assert sys.version_info >= (3,10)'], { windowsHide: true }).status === 0)
    if (!found) throw new Error('Install Python 3.10+ first, then retry yarn client:dev.')
    console.log('[setup] Creating .venv...')
    exec(found[0], [...found.slice(1), '-m', 'venv', join(root, '.venv')])
  }
  const hash = createHash('sha256').update(readFileSync(join(root, 'requirements.txt'))).digest('hex')
  const marker = join(root, '.venv/.vinote-requirements')
  if (!existsSync(marker) || readFileSync(marker, 'utf8') !== hash || spawnSync(py, ['-c', 'import fastapi, uvicorn, sqlalchemy, cryptography'], { windowsHide: true }).status !== 0) {
    console.log('[setup] Installing backend dependencies...')
    exec(py, ['-m', 'pip', 'install', '-r', join(root, 'requirements.txt')])
    if (existsSync(join(root, '.venv'))) writeFileSync(marker, hash)
  }
  process.env.VINOTE_PYTHON = py
  const config = join(root, '.env')
  if (!existsSync(config)) {
    const publicConfig = JSON.parse(readFileSync(join(root, 'config/desktop-public.json'), 'utf8'))
    const initial = {
      ...publicConfig, VILAB_SERVER_URL: 'http://127.0.0.1:9878',
      APP_JWT_SECRET: randomBytes(48).toString('hex'),
      MODEL_PROFILE_ENCRYPTION_KEY: randomBytes(32).toString('base64url') + '=',
    }
    writeFileSync(config, Object.entries(initial).map(([key, value]) => `${key}=${value}`).join('\n') + '\n', { flag: 'wx', mode: 0o600 })
    console.log('[setup] Created local .env with unique installation secrets (not tracked by Git).')
  }
  const speakerSetup = join(root, 'scripts/setup_diarization.py')
  if (spawnSync(py, [speakerSetup, '--check'], { cwd: root, stdio: 'ignore', windowsHide: true }).status !== 0) {
    console.log('[setup] Preparing local speaker recognition runtime and models...')
    exec(py, [speakerSetup])
  }
}
