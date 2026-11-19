import { execFileSync } from 'node:child_process'
import { basename, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

export function assertMacUpdaterArchive(archive, appName) {
  // BSD tar hides AppleDouble entries when listing; inspect the raw members instead.
  const python = process.env.VINOTE_PYTHON || 'python3'
  const checker = fileURLToPath(new URL('./check_macos_updater_archive.py', import.meta.url))
  try {
    execFileSync(python, [checker, archive, appName], { stdio: ['ignore', 'pipe', 'pipe'] })
  } catch (error) {
    throw new Error(`Invalid macOS updater archive: ${error.stderr?.toString().trim() || error.message}`)
  }
}

export function createMacUpdaterArchive(app, archive) {
  const appName = basename(app)
  if (!appName.endsWith('.app')) throw new Error('Expected a macOS application bundle')
  execFileSync('/usr/bin/tar', ['-czf', archive, '-C', dirname(app), appName], {
    env: { ...process.env, COPYFILE_DISABLE: '1' },
  })
  assertMacUpdaterArchive(archive, appName)
}
