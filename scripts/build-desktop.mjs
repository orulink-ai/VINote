import { spawnSync } from 'node:child_process'
import { mkdirSync, writeFileSync, copyFileSync, existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { parseArgs } from 'node:util'
import { resolveDesktopProfile, checksum } from './desktop-build-profile.mjs'
import { root, python, loadEnv } from './runtime.mjs'
import { bootstrap } from './bootstrap-dev.mjs'
const { values } = parseArgs({ options: {
  channel: { type: 'string', default: 'release' },
  'build-id': { type: 'string' }, plan: { type: 'boolean', default: false },
} })
loadEnv()
const baseConfig = JSON.parse(readFileSync(join(root, 'frontend/src-tauri/tauri.conf.json'), 'utf8'))
const profile = resolveDesktopProfile({ channel: values.channel, version: baseConfig.version, env: process.env,
  publicConfig: JSON.parse(readFileSync(join(root, 'config/desktop-public.json'), 'utf8')),
  buildId: values['build-id'] || new Date().toISOString().replace(/[-:.]/g, ''),
})
if (values.plan) {
  console.log(JSON.stringify({ channel: profile.channel, productName: profile.productName, version: profile.version,
    identifier: profile.identifier, server: profile.config.VILAB_SERVER_URL, buildId: profile.buildId }, null, 2))
  process.exit(0)
}
bootstrap()
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
const staging = join(root, '.desktop-build', profile.channel)
mkdirSync(join(staging, 'bin'), { recursive: true })
exec(py, [join(root, 'scripts/setup_diarization.py'), '--models-dir', join(staging, 'models/diarization')])
writeFileSync(join(staging, 'desktop-config.json'), JSON.stringify(profile.config, null, 2))
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
exec(py, ['-m', 'PyInstaller', '--noconfirm', '--onedir', '--name', profile.backendName,
  '--distpath', join(staging, 'dist'), '--workpath', join(staging, 'work'), '--specpath', staging,
  '--paths', root, '--collect-submodules', 'app', '--collect-all', 'yt_dlp', '--collect-all', 'uvicorn',
  '--hidden-import', 'sqlalchemy.dialects.sqlite', '--hidden-import', 'bcrypt', '--collect-submodules', 'passlib.handlers',
  '--collect-all', 'sherpa_onnx', '--hidden-import', 'numpy',
  '--collect-all', 'langfuse', '--collect-submodules', 'opentelemetry',
  '--copy-metadata', 'opentelemetry-api', '--copy-metadata', 'opentelemetry-sdk',
  '--add-data', `${join(staging, 'desktop-config.json')}${sep}.`,
  '--add-data', `${join(staging, 'models')}${sep}models`,
  '--add-data', `${join(root, 'frontend/dist')}${sep}frontend`, '--add-binary', `${join(staging, 'bin/*')}${sep}bin`,
  join(root, 'scripts/desktop_backend.py')])
const backendDir = join(staging, 'dist', profile.backendName)
const smokePath = process.platform === 'win32'
  ? [join(backendDir, '_internal/bin'), join(process.env.SystemRoot || 'C:/Windows', 'System32'), process.env.SystemRoot || 'C:/Windows'].join(';')
  : '/usr/bin:/bin'
exec(join(backendDir, profile.backendName + (process.platform === 'win32' ? '.exe' : '')), ['--smoke-test'], {
  cwd: staging, env: { ...process.env, PATH: smokePath, PYTHONHOME: '', PYTHONPATH: '',
    DIARIZATION_MODEL_DIR: join(backendDir, '_internal/models/diarization'),
    VINOTE_DESKTOP_DATA: join(staging, 'smoke-data'), PORT: '0' },
})
const tauriConfig = join(staging, 'tauri-package.json')
const hooks = join(staging, 'installer-hooks.nsh')
writeFileSync(hooks, `!define VINOTE_MAIN_EXE "${profile.binaryName}.exe"\n!define VINOTE_BACKEND_EXE "${profile.backendName}.exe"\n!define VINOTE_APP_NAME "${profile.productName}"\n!include "${join(root, 'frontend/src-tauri/installer-hooks.nsh')}"\n`)
writeFileSync(tauriConfig, JSON.stringify({
  productName: profile.productName, identifier: profile.identifier, version: profile.version,
  mainBinaryName: profile.binaryName,
  app: { windows: baseConfig.app.windows.map(window => ({ ...window, title: profile.productName })) },
  build: { beforeBuildCommand: '' },
  bundle: { targets: process.platform === 'win32' ? ['nsis'] : ['app', 'dmg'],
    ...(process.platform === 'win32' ? { windows: { nsis: { installerHooks: hooks } } } : {}),
    resources: { [backendDir + '/']: 'backend/' } },
}))
const targetDir = join(staging, 'target')
exec(process.execPath, [join(root, 'frontend/node_modules/@tauri-apps/cli/tauri.js'), 'build', '--config', tauriConfig], {
  cwd: join(root, 'frontend'), env: { ...process.env, CARGO_TARGET_DIR: targetDir },
})
const { readdirSync, cpSync } = await import('node:fs')
const bundleDir = join(targetDir, 'release/bundle')
const artifacts = join(root, '.desktop-build/artifacts', profile.channel, profile.version, profile.buildId)
mkdirSync(artifacts, { recursive: true })
const files = []
for (const type of process.platform === 'win32' ? ['nsis'] : ['macos', 'dmg']) {
  const directory = join(bundleDir, type)
  if (!existsSync(directory)) continue
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (!/\.(exe|dmg|app)$/.test(entry.name)) continue
    const name = `${profile.channel}-${profile.buildId}-${entry.name}`
    cpSync(join(directory, entry.name), join(artifacts, name), { recursive: entry.isDirectory() })
    files.push({ name, sha256: entry.isFile() ? checksum(readFileSync(join(artifacts, name))) : null })
  }
}
if (!files.length) throw new Error('No desktop package artifacts were produced')
const git = (...args) => spawnSync('git', args, { cwd: root, encoding: 'utf8', windowsHide: true }).stdout?.trim()
writeFileSync(join(artifacts, 'manifest.json'), JSON.stringify({ channel: profile.channel, version: profile.version,
  buildId: profile.buildId, identifier: profile.identifier, server: profile.config.VILAB_SERVER_URL,
  platform: process.platform, arch: process.arch, commit: git('rev-parse', 'HEAD'),
  dirty: Boolean(git('status', '--porcelain')), files }, null, 2))
console.log(`Desktop ${profile.channel} artifacts: ${artifacts}`)
