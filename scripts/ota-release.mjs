import { createHash, createPublicKey, verify } from 'node:crypto'
import { readFileSync, statSync } from 'node:fs'
import { join, basename } from 'node:path'

export const PUBLIC_REPOSITORY = 'Ro-In-AI/Vinote-public'
export const RELEASE_REPOSITORIES = ['orulink-ai/VINote', PUBLIC_REPOSITORY]
export const UPDATE_ENDPOINT = `https://github.com/${PUBLIC_REPOSITORY}/releases/latest/download/latest.json`
export const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')

export function updaterBuildConfig(channel, env, baseUpdater = {}) {
  if (channel === 'test') return { bundle: { createUpdaterArtifacts: false }, plugins: { updater: { ...baseUpdater, endpoints: [] } } }
  if (channel !== 'release') throw new Error('Unsupported release channel')
  if (!env.TAURI_SIGNING_PRIVATE_KEY?.trim()) throw new Error('Release requires TAURI_SIGNING_PRIVATE_KEY')
  const pubkey = env.VINOTE_UPDATER_PUBLIC_KEY?.trim() || baseUpdater.pubkey
  if (!pubkey) throw new Error('Release requires VINOTE_UPDATER_PUBLIC_KEY or configured updater pubkey')
  return { bundle: { createUpdaterArtifacts: true }, plugins: { updater: { ...baseUpdater, pubkey, endpoints: [UPDATE_ENDPOINT] } } }
}

// Tauri wraps the standard minisign text in base64. Verify both the artifact
// signature and trusted-comment signature, matching minisign-verify's format.
export function verifyUpdaterSignature(bytes, encodedSignature, encodedPublicKey) {
  const keyLines = Buffer.from(encodedPublicKey.trim(), 'base64').toString('utf8').trim().split(/\r?\n/)
  const sigLines = Buffer.from(encodedSignature.trim(), 'base64').toString('utf8').trim().split(/\r?\n/)
  const key = Buffer.from(keyLines[1] || '', 'base64')
  const sig = Buffer.from(sigLines[1] || '', 'base64')
  const global = Buffer.from(sigLines[3] || '', 'base64')
  if (key.length !== 42 || sig.length !== 74 || global.length !== 64 || key.subarray(0, 2).toString() !== 'Ed'
      || !['Ed', 'ED'].includes(sig.subarray(0, 2).toString()) || !key.subarray(2, 10).equals(sig.subarray(2, 10))
      || !sigLines[2]?.startsWith('trusted comment: ')) throw new Error('Invalid updater signature/key format')
  const publicKey = createPublicKey({ key: Buffer.concat([Buffer.from('302a300506032b6570032100', 'hex'), key.subarray(10)]), format: 'der', type: 'spki' })
  const payload = sig.subarray(0, 2).toString() === 'ED' ? createHash('blake2b512').update(bytes).digest() : bytes
  if (!verify(null, payload, publicKey, sig.subarray(10))
      || !verify(null, Buffer.concat([sig.subarray(10), Buffer.from(sigLines[2].slice(17))]), publicKey, global)) {
    throw new Error('Updater signature verification failed')
  }
}

export function readRelease(directory, publicKey) {
  const manifest = JSON.parse(readFileSync(join(directory, 'manifest.json'), 'utf8'))
  if (manifest.channel !== 'release' || !/^\d+\.\d+\.\d+$/.test(manifest.version)) throw new Error('Only stable release artifacts may be published')
  if (manifest.dirty || !/^[a-f0-9]{40}$/.test(manifest.commit || '')) throw new Error('Release must come from a clean committed source tree')
  const names = new Set()
  const files = manifest.files.filter(file => file.sha256 !== null).map(file => {
    if (!file.name || basename(file.name) !== file.name || /[\\/]/.test(file.name) || names.has(file.name)) throw new Error('Invalid or duplicate artifact name')
    names.add(file.name)
    const path = join(directory, file.name)
    if (!statSync(path).isFile() || sha256(readFileSync(path)) !== file.sha256) throw new Error(`Artifact checksum mismatch: ${file.name}`)
    return { ...file, path }
  })
  const updaterExtension = manifest.platform === 'win32' ? '.exe' : manifest.platform === 'darwin' ? '.app.tar.gz' : null
  const updater = files.filter(file => updaterExtension && file.name.endsWith(updaterExtension))
  if (updater.length !== 1) throw new Error('Exactly one supported signed updater artifact is required per build')
  const signature = files.find(file => file.name === updater[0].name + '.sig')
  if (!signature) throw new Error('Updater signature file is missing')
  if (manifest.platform === 'darwin' && !files.some(file => file.name.endsWith('.dmg'))) throw new Error('macOS DMG installer is missing')
  verifyUpdaterSignature(readFileSync(updater[0].path), readFileSync(signature.path, 'utf8'), publicKey)
  const arch = { x64: 'x86_64', arm64: 'aarch64' }[manifest.arch]
  if (!arch) throw new Error('Unsupported updater architecture')
  return { manifest, files, platform: `${manifest.platform === 'win32' ? 'windows' : 'darwin'}-${arch}`, updater: updater[0], signature: readFileSync(signature.path, 'utf8').trim() }
}

export function releasePlan(builds, notes = '', now = new Date().toISOString()) {
  if (!builds.length) throw new Error('At least one verified release build is required')
  const { version, commit } = builds[0].manifest
  const platforms = {}, assets = new Map()
  for (const build of builds) {
    if (build.manifest.version !== version || build.manifest.commit !== commit) throw new Error('Release builds must share version and source commit')
    if (platforms[build.platform]) throw new Error('Duplicate release platform')
    platforms[build.platform] = { signature: build.signature, url: `https://github.com/${PUBLIC_REPOSITORY}/releases/download/v${version}/${encodeURIComponent(build.updater.name)}` }
    for (const file of build.files) {
      if (assets.has(file.name)) throw new Error(`Duplicate release asset: ${file.name}`)
      assets.set(file.name, file)
    }
  }
  return { version, commit, tag: `v${version}`, assets: [...assets.values()], latest: { version, notes, pub_date: now, platforms } }
}
