import test from 'node:test'
import assert from 'node:assert/strict'
import { generateKeyPairSync, sign, createHash } from 'node:crypto'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { updaterBuildConfig, verifyUpdaterSignature, readRelease, releasePlan, sha256, UPDATE_ENDPOINT } from './ota-release.mjs'
import { publishRelease } from './publish-desktop-release.mjs'

function signed(bytes, prehash = true) {
  const { publicKey, privateKey } = generateKeyPairSync('ed25519')
  const keyId = Buffer.from('12345678')
  const raw = publicKey.export({ format: 'der', type: 'spki' }).subarray(-32)
  const key = Buffer.concat([Buffer.from('Ed'), keyId, raw])
  const payload = prehash ? createHash('blake2b512').update(bytes).digest() : bytes
  const signature = sign(null, payload, privateKey)
  const packet = Buffer.concat([Buffer.from(prehash ? 'ED' : 'Ed'), keyId, signature])
  const comment = 'timestamp:12345 file:vinote.exe'
  const global = sign(null, Buffer.concat([signature, Buffer.from(comment)]), privateKey)
  return {
    publicKey: Buffer.from(`untrusted comment: public key\n${key.toString('base64')}\n`).toString('base64'),
    signature: Buffer.from(`untrusted comment: signature\n${packet.toString('base64')}\ntrusted comment: ${comment}\n${global.toString('base64')}\n`).toString('base64'),
  }
}

test('stable builds fail closed; test builds have no stable updater endpoint', () => {
  assert.throws(() => updaterBuildConfig('release', {}), /PRIVATE_KEY/)
  assert.throws(() => updaterBuildConfig('release', { TAURI_SIGNING_PRIVATE_KEY: 'secret' }), /PUBLIC_KEY/)
  const release = updaterBuildConfig('release', { TAURI_SIGNING_PRIVATE_KEY: 'secret', VINOTE_UPDATER_PUBLIC_KEY: 'public' })
  assert.equal(release.bundle.createUpdaterArtifacts, true)
  assert.deepEqual(release.plugins.updater.endpoints, [UPDATE_ENDPOINT])
  const testing = updaterBuildConfig('test', {}, release.plugins.updater)
  assert.deepEqual(testing.plugins.updater.endpoints, [])
  assert.equal(testing.bundle.createUpdaterArtifacts, false)
})

test('minisign verifies direct and prehashed signatures and rejects tampering/wrong key', () => {
  for (const prehash of [true, false]) {
    const bytes = Buffer.from('installer bytes'), fixture = signed(bytes, prehash)
    verifyUpdaterSignature(bytes, fixture.signature, fixture.publicKey)
    assert.throws(() => verifyUpdaterSignature(Buffer.from('tampered'), fixture.signature, fixture.publicKey), /verification failed/)
    assert.throws(() => verifyUpdaterSignature(bytes, fixture.signature, signed(bytes).publicKey), /verification failed/)
    const text = Buffer.from(fixture.signature, 'base64').toString().replace('timestamp:12345', 'timestamp:54321')
    assert.throws(() => verifyUpdaterSignature(bytes, Buffer.from(text).toString('base64'), fixture.publicKey), /verification failed/)
  }
})

test('verifies upstream minisign-verify prehashed interoperability vector', () => {
  const key = Buffer.from('untrusted comment: public key\nRWQf6LRCGA9i53mlYecO4IzT51TGPpvWucNSCh1CBM0QTaLn73Y7GFO3\n').toString('base64')
  const sig = Buffer.from('untrusted comment: signature from minisign secret key\nRUQf6LRCGA9i559r3g7V1qNyJDApGip8MfqcadIgT9CuhV3EMhHoN1mGTkUidF/z7SrlQgXdy8ofjb7bNJJylDOocrCo8KLzZwo=\ntrusted comment: timestamp:1556193335\tfile:test\ny/rUw2y8/hOUYjZU71eHp/Wo1KZ40fGy2VJEDl34XMJM+TX48Ss/17u3IvIfbVR1FkZZSNCisQbuQY+bHwhEBg==\n').toString('base64')
  verifyUpdaterSignature(Buffer.from('test'), sig, key)
})

test('release receipt validates hashes, signatures, channel, clean commit and creates public URLs', () => {
  const dir = mkdtempSync(join(tmpdir(), 'vinote-ota-'))
  try {
    const bytes = Buffer.from('installer bytes'), fixture = signed(bytes)
    const files = [{ name: 'VINote.exe', sha256: sha256(bytes) }, { name: 'VINote.exe.sig', sha256: sha256(fixture.signature) }]
    const manifest = { channel: 'release', version: '1.2.3', commit: 'a'.repeat(40), dirty: false, platform: 'win32', arch: 'x64', files }
    const save = () => writeFileSync(join(dir, 'manifest.json'), JSON.stringify(manifest))
    writeFileSync(join(dir, 'VINote.exe'), bytes); writeFileSync(join(dir, 'VINote.exe.sig'), fixture.signature); save()
    const build = readRelease(dir, fixture.publicKey), plan = releasePlan([build])
    assert.match(plan.latest.platforms['windows-x86_64'].url, /Ro-In-AI\/Vinote-public\/releases\/download\/v1.2.3\/VINote.exe$/)
    assert.throws(() => releasePlan([build, build]), /Duplicate release platform/)
    manifest.dirty = true; save(); assert.throws(() => readRelease(dir, fixture.publicKey), /clean committed/)
    manifest.dirty = false; manifest.channel = 'test'; save(); assert.throws(() => readRelease(dir, fixture.publicKey), /stable release/)
    manifest.channel = 'release'; save(); writeFileSync(join(dir, 'VINote.exe'), 'changed')
    assert.throws(() => readRelease(dir, fixture.publicKey), /checksum mismatch/)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

function fakeGitHub({ corrupt = false, released = false } = {}) {
  const events = [], assets = new Map()
  return { events, api: async (method, path, body) => {
    events.push({ method, path, body })
    if (path.includes('/compare/')) return { status: 'identical' }
    if (path.includes('/matching-refs/')) return []
    if (method === 'GET' && path.endsWith('releases?per_page=100')) return released ? [{ tag_name: 'v1.2.3', draft: false }] : []
    if (method === 'POST') return { id: events.length }
    if (method === 'GET') return (assets.get(path.split('/releases/')[0]) || []).map(file => ({ name: file.name, state: 'uploaded', digest: `sha256:${corrupt ? 'bad' : file.sha256}` }))
    return {}
  }, upload: async (repo, tag, asset) => { events.push({ upload: asset.name, repo }); const key = `repos/${repo}`; assets.set(key, [...(assets.get(key) || []).filter(file => file.name !== asset.name), asset]) },
  writeMetadata: async () => ({ manifest: { name: 'manifest.json', sha256: 'manifest' }, latest: { name: 'latest.json', sha256: 'latest' } }) }
}
const plan = { tag: 'v1.2.3', version: '1.2.3', commit: 'a'.repeat(40), assets: [{ name: 'VINote.exe', sha256: 'installer' }], latest: { notes: 'Release' } }

test('publishing waits for both verified uploads and writes latest metadata last', async () => {
  const fake = fakeGitHub(); await publishRelease(plan, fake, { publish: true })
  const patches = fake.events.filter(event => event.method === 'PATCH')
  assert.equal(patches.length, 2)
  assert.match(patches[1].path, /Ro-In-AI/)
  const firstPatch = fake.events.findIndex(event => event.method === 'PATCH')
  assert.equal(fake.events.slice(firstPatch).some(event => event.upload), false)
  for (const repo of ['orulink-ai/VINote', 'Ro-In-AI/Vinote-public']) assert.equal(fake.events.filter(event => event.repo === repo).at(-1).upload, 'latest.json')
})

test('drafts default, corrupt remote uploads and existing public versions never publish', async () => {
  const fake = fakeGitHub(); await publishRelease(plan, fake)
  assert.equal(fake.events.some(event => event.method === 'PATCH'), false)
  const corrupt = fakeGitHub({ corrupt: true })
  await assert.rejects(publishRelease(plan, corrupt, { publish: true }), /digest mismatch/)
  assert.equal(corrupt.events.some(event => event.method === 'PATCH'), false)
  const existing = fakeGitHub({ released: true })
  await assert.rejects(publishRelease(plan, existing, { publish: true }), /Refusing to overwrite/)
  assert.equal(existing.events.some(event => event.method === 'POST' || event.upload), false)
})

test('unmerged release commits fail before any GitHub mutation', async () => {
  const fake = fakeGitHub(), original = fake.api
  fake.api = (method, path, body) => path.includes('/compare/') ? { status: 'diverged' } : original(method, path, body)
  await assert.rejects(publishRelease(plan, fake, { publish: true }), /merged into origin\/dev/)
  assert.equal(fake.events.length, 0)
})
