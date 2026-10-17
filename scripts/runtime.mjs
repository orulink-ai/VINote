import { spawn, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
export const root = fileURLToPath(new URL('../', import.meta.url))
export function python() {
  const candidates = process.env.VINOTE_PYTHON ? [process.env.VINOTE_PYTHON] :
    [fileURLToPath(new URL(process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python', import.meta.url)), 'python3', 'python']
  for (const candidate of candidates) {
    if (spawnSync(candidate, ['-c', 'import fastapi, uvicorn, sqlalchemy, cryptography'], { windowsHide: true }).status === 0) return candidate
  }
  throw new Error('Install requirements.txt in .venv, or set VINOTE_PYTHON to a Python executable with backend dependencies.')
}
export function loadEnv() {
  if (existsSync(new URL('../.env', import.meta.url))) process.loadEnvFile(new URL('../.env', import.meta.url))
}
export function run(command, args, options = {}) {
  const child = spawn(command, args, { cwd: root, stdio: 'inherit', windowsHide: true, ...options })
  child.on('error', error => { console.error(error.message); process.exitCode = 1 })
  return child
}
export async function healthy(url) {
  try { const r = await fetch(url, { signal: AbortSignal.timeout(1500) }); return r.ok } catch { return false }
}
