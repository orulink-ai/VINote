import { spawnSync } from 'node:child_process'
import { mkdirSync, writeFileSync, copyFileSync, existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { root, python, loadEnv } from './runtime.mjs'
import { bootstrap } from './bootstrap-dev.mjs'
bootstrap()
loadEnv()
if (!['win32', 'darwin'].includes(process.platform)) throw new Error('Build Windows installers on Windows, macOS installers on macOS.')
const py = python()
// venvs created from Conda need its DLL directory during dependency analysis.
if (process.platform === 'win32') {
  const base = spawnSync(py, ['-c', 'import sys; print(sys.base_prefix)'], { encoding: 'utf8', windowsHide: true }).stdout.trim()
  const dlls = join(base, 'Library/bin')
  if (existsSync(dlls)) process.env.PATH = `${dlls};${process.env.PATH}`
}
function exec(command, args, options = {}) {
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit', windowsHide: true, ...options })
  if (result.error || result.status !== 0) throw new Error(`${command} failed (${result.status}): ${result.error?.message || 'see output above'}`)
}
if (spawnSync(py, ['-c', 'import PyInstaller'], { stdio: 'ignore' }).status !== 0) {
  exec(py, ['-m', 'pip', 'install', '-r', join(root, 'requirements.desktop-build.txt')])
}
const staging = join(root, '.desktop-build')
mkdirSync(join(staging, 'bin'), { recursive: true })
const publicConfig = JSON.parse(readFileSync(join(root, 'config/desktop-public.json'), 'utf8'))
const config = {
  VILAB_SERVER_URL: process.env.VINOTE_RELEASE_VILAB_SERVER_URL || 'http://192.168.1.143:9876',
  VINOTE_SUPABASE_URL: process.env.VINOTE_SUPABASE_URL || publicConfig.VINOTE_SUPABASE_URL,
  VINOTE_SUPABASE_PUBLISHABLE_KEY: process.env.VINOTE_SUPABASE_PUBLISHABLE_KEY || publicConfig.VINOTE_SUPABASE_PUBLISHABLE_KEY,
}
if (!config.VINOTE_SUPABASE_URL || !config.VINOTE_SUPABASE_PUBLISHABLE_KEY) throw new Error('Set VINOTE_SUPABASE_URL and VINOTE_SUPABASE_PUBLISHABLE_KEY for email accounts. Never use a service-role key.')
if (!config.VINOTE_SUPABASE_PUBLISHABLE_KEY.startsWith('sb_publishable_')) throw new Error('A Supabase publishable key is required; secret keys cannot be bundled.')
writeFileSync(join(staging, 'desktop-config.json'), JSON.stringify(config, null, 2))
for (const tool of ['ffmpeg', 'ffprobe']) {
  const command = process.platform === 'win32' ? 'where.exe' : 'which'
  const found = process.env[`VINOTE_${tool.toUpperCase()}_PATH`] || spawnSync(command, [tool], { encoding: 'utf8', windowsHide: true }).stdout?.trim().split(/\r?\n/)[0]
  if (!found) throw new Error(`Install ${tool} or set VINOTE_${tool.toUpperCase()}_PATH`)
  copyFileSync(found, join(staging, 'bin', tool + (process.platform === 'win32' ? '.exe' : '')))
}
exec(process.execPath, [join(root, 'frontend/node_modules/typescript/bin/tsc')], { cwd: join(root, 'frontend') })
exec(process.execPath, [join(root, 'frontend/node_modules/vite/bin/vite.js'), 'build'], {
  cwd: join(root, 'frontend'), env: { ...process.env, VINOTE_DESKTOP_BUILD: 'true', VITE_API_BASE_URL: '' },
})
const sep = process.platform === 'win32' ? ';' : ':'
exec(py, ['-m', 'PyInstaller', '--noconfirm', '--onedir', '--name', 'vinote-backend',
  '--distpath', join(staging, 'dist'), '--workpath', join(staging, 'work'), '--specpath', staging,
  '--paths', root, '--collect-submodules', 'app', '--collect-all', 'yt_dlp', '--collect-all', 'uvicorn',
  '--hidden-import', 'sqlalchemy.dialects.sqlite', '--hidden-import', 'bcrypt', '--collect-all', 'passlib',
  '--collect-all', 'langfuse', '--collect-submodules', 'opentelemetry',
  '--copy-metadata', 'opentelemetry-api', '--copy-metadata', 'opentelemetry-sdk',
  '--add-data', `${join(staging, 'desktop-config.json')}${sep}.`,
  '--add-data', `${join(root, 'frontend/dist')}${sep}frontend`, '--add-binary', `${join(staging, 'bin/*')}${sep}bin`,
  join(root, 'scripts/desktop_backend.py')])
exec(join(staging, 'dist/vinote-backend', process.platform === 'win32' ? 'vinote-backend.exe' : 'vinote-backend'), ['--smoke-test'], {
  cwd: staging, env: { ...process.env, VINOTE_DESKTOP_DATA: join(staging, 'smoke-data'), PORT: '0' },
})
const tauriConfig = join(staging, 'tauri-package.json')
writeFileSync(tauriConfig, JSON.stringify({
  build: { beforeBuildCommand: '' },
  bundle: { targets: process.platform === 'win32' ? ['nsis'] : ['app', 'dmg'],
    ...(process.platform === 'win32' ? { windows: { nsis: { installerHooks: join(root, 'frontend/src-tauri/installer-hooks.nsh') } } } : {}),
    resources: { [join(staging, 'dist/vinote-backend/')]: 'backend/' } },
}))
exec(process.execPath, [join(root, 'frontend/node_modules/@tauri-apps/cli/tauri.js'), 'build', '--config', tauriConfig], { cwd: join(root, 'frontend') })
