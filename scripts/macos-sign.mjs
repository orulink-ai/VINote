import { openSync, readSync, closeSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { pathToFileURL } from 'node:url'
const run = promisify(execFile)
const magics = new Set(['cffaedfe', 'cefaedfe', 'feedfacf', 'feedface', 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca'])

function walk(root, visit) {
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name)
    if (entry.isDirectory()) { walk(path, visit); visit(path, true) }
    else if (entry.isFile()) visit(path, false)
  }
}

export function nativeSignTargets(root) {
  const targets = []
  walk(root, (path, directory) => {
    if (directory) return
    const fd = openSync(path, 'r')
    try {
      const header = Buffer.alloc(4)
      if (readSync(fd, header, 0, 4, 0) === 4 && magics.has(header.toString('hex'))) targets.push(path)
    } finally { closeSync(fd) }
  })
  return targets.sort()
}

export async function signMacBinaries(root, identity) {
  if (!identity?.startsWith('Developer ID Application: ')) throw new Error('Developer ID Application identity is required')
  const sign = async path => {
    for (let attempt = 0; ; attempt++) {
      try {
        await run('codesign', ['--force', '--options', 'runtime', '--timestamp', '--sign', identity, path], { timeout: 120000 })
        return
      } catch (error) {
        if (attempt >= 2 || !/timestamp service is not available/i.test(error.stderr || '')) throw error
      }
    }
  }
  const targets = nativeSignTargets(root)
  for (let start = 0; start < targets.length; start += 4) {
    const batch = await Promise.allSettled(targets.slice(start, start + 4).map(sign))
    const failed = batch.find(result => result.status === 'rejected')
    if (failed) throw failed.reason
  }
  // Nested code containers depend on their already-signed contents.
  const containers = []
  walk(root, (path, directory) => { if (directory && /\.(framework|app)$/.test(path)) containers.push(path) })
  for (const path of containers) await sign(path)
  if (/\.(framework|app)$/.test(root)) await sign(root)
  // Verify seals only after every nested signature and the outer seal are final.
  for (const path of targets) await run('codesign', ['--verify', '--strict', path])
  console.log(`Developer ID signatures verified for ${targets.length} native binaries`)
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  if (!process.argv[2]) throw new Error('Provide the bundle directory')
  await signMacBinaries(resolve(process.argv[2]), process.env.APPLE_SIGNING_IDENTITY)
}
