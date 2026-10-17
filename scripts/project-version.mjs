import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { root } from './runtime.mjs'

// Every source mode and package channel shares this base version.
export function assertProjectVersion(directory = root) {
  const read = file => readFileSync(join(directory, file), 'utf8')
  const json = file => JSON.parse(read(file))
  const version = json('package.json').version
  if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error('Project version must be major.minor.patch')
  const versions = {
    'frontend/package.json': json('frontend/package.json').version,
    'frontend/package-lock.json': json('frontend/package-lock.json').version,
    'frontend/package-lock.json root package': json('frontend/package-lock.json').packages[''].version,
    'frontend/src-tauri/tauri.conf.json': json('frontend/src-tauri/tauri.conf.json').version,
    'frontend/src-tauri/Cargo.toml': read('frontend/src-tauri/Cargo.toml').match(/^version\s*=\s*"([^"]+)"/m)?.[1],
    'frontend/src-tauri/Cargo.lock': read('frontend/src-tauri/Cargo.lock').match(/name = "vinote"\r?\nversion = "([^"]+)"/)?.[1],
    'app/__init__.py': read('app/__init__.py').match(/\bversion="([^"]+)"/)?.[1],
  }
  const mismatches = Object.entries(versions).filter(([, value]) => value !== version)
  if (mismatches.length) throw new Error(`Version mismatch (expected ${version}): ${mismatches.map(([file, value]) => `${file}=${value}`).join(', ')}`)
  return version
}
