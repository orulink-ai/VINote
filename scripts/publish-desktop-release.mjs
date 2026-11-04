import { spawnSync } from 'node:child_process'
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { parseArgs } from 'node:util'
import { readRelease, releasePlan, RELEASE_REPOSITORIES, sha256 } from './ota-release.mjs'

function gh(args, options = {}) {
  const result = spawnSync('gh', args, { encoding: 'utf8', windowsHide: true, maxBuffer: 32 * 1024 * 1024, ...options })
  if (result.error || result.status !== 0) throw new Error(`GitHub operation failed: ${args.slice(0, 3).join(' ')}: ${result.stderr || result.error?.message}`)
  return result.stdout
}

// All repositories must finish upload and digest verification before either
// becomes visible. GitHub has no cross-repository atomic publish operation.
export async function publishRelease(plan, { api, upload, writeMetadata }, { publish = false } = {}) {
  const releases = []
  const merged = await api('GET', `repos/orulink-ai/VINote/compare/${plan.commit}...dev`)
  if (!['ahead', 'identical'].includes(merged.status)) throw new Error('Release source commit must be merged into origin/dev')
  const tags = await api('GET', `repos/orulink-ai/VINote/git/matching-refs/tags/${plan.tag}`)
  if (tags.some(tag => tag.ref === `refs/tags/${plan.tag}`)) {
    const tagged = await api('GET', `repos/orulink-ai/VINote/compare/${plan.tag}...${plan.commit}`)
    if (tagged.status !== 'identical') throw new Error('Existing source tag points to a different commit')
  }
  // Preflight all repositories before creating or uploading anything.
  for (const repo of RELEASE_REPOSITORIES) {
    const existing = await api('GET', `repos/${repo}/releases?per_page=100`)
    const release = existing.find(item => item.tag_name === plan.tag)
    if (release && !release.draft) throw new Error(`Refusing to overwrite published ${repo} ${plan.tag}`)
    releases.push({ repo, release })
  }
  for (const item of releases) {
    if (!item.release) item.release = await api('POST', `repos/${item.repo}/releases`, {
      tag_name: plan.tag, name: `VINote ${plan.version}`, body: plan.latest.notes, draft: true, prerelease: false,
      ...(item.repo === 'orulink-ai/VINote' ? { target_commitish: plan.commit } : {}),
    })
    const expected = [...plan.assets]
    // manifest.json is a public aggregate checksum receipt, without local paths.
    const metadata = await writeMetadata(plan)
    expected.push(metadata.manifest)
    for (const asset of expected) await upload(item.repo, plan.tag, asset)
    await verifyAssets(api, item, expected, ['latest.json'])
    // Expose OTA metadata only after every referenced package has been verified.
    await upload(item.repo, plan.tag, metadata.latest)
    await verifyAssets(api, item, [...expected, metadata.latest])
  }
  if (publish) {
    // Public endpoint last: its manifest never points at an unfinished mirror.
    for (const item of releases) await api('PATCH', `repos/${item.repo}/releases/${item.release.id}`, { draft: false, make_latest: 'true' })
  }
  return releases.map(({ repo, release }) => ({ repo, id: release.id, published: publish }))
}

async function verifyAssets(api, item, expected, allowed = []) {
  const remote = await api('GET', `repos/${item.repo}/releases/${item.release.id}/assets?per_page=100`)
  if (remote.some(asset => !allowed.includes(asset.name) && !expected.some(file => file.name === asset.name))) throw new Error(`Unexpected release asset in ${item.repo}; inspect draft manually`)
  for (const file of expected) {
    const asset = remote.find(candidate => candidate.name === file.name)
    if (!asset || asset.state !== 'uploaded' || asset.digest !== `sha256:${file.sha256}`) throw new Error(`GitHub asset digest mismatch: ${item.repo}/${file.name}`)
  }
}

async function main() {
  const { values, positionals } = parseArgs({ allowPositionals: true, options: {
    publish: { type: 'boolean', default: false }, plan: { type: 'boolean', default: false },
    notes: { type: 'string' }, output: { type: 'string', default: '.desktop-build/release' }, 'public-key': { type: 'string' },
  } })
  const configured = JSON.parse(readFileSync(new URL('../config/desktop-updater-public.json', import.meta.url), 'utf8')).pubkey
  const publicKey = values['public-key'] ? readFileSync(values['public-key'], 'utf8').trim() : process.env.VINOTE_UPDATER_PUBLIC_KEY || configured
  if (!publicKey) throw new Error('Supply VINOTE_UPDATER_PUBLIC_KEY or --public-key path')
  const plan = releasePlan(positionals.map(path => readRelease(resolve(path), publicKey)), values.notes ? readFileSync(values.notes, 'utf8') : '')
  if (values.plan) { console.log(JSON.stringify(plan, null, 2)); return }
  const output = resolve(values.output, plan.tag)
  mkdirSync(output, { recursive: true })
  const result = await publishRelease(plan, {
    api: (method, path, body) => JSON.parse(gh(['api', '--method', method, path, ...(body ? ['--input', '-'] : [])], body ? { input: JSON.stringify(body) } : {})),
    upload: (repo, tag, asset) => gh(['release', 'upload', tag, asset.path, '--repo', repo, '--clobber']),
    writeMetadata: () => {
      const write = (name, data) => { const path = join(output, name); writeFileSync(path, JSON.stringify(data, null, 2) + '\n'); return { name, path, sha256: sha256(readFileSync(path)) } }
      return {
        manifest: write('manifest.json', { version: plan.version, commit: plan.commit, channel: 'release', files: plan.assets.map(({ name, sha256 }) => ({ name, sha256 })) }),
        latest: write('latest.json', plan.latest),
      }
    },
  }, { publish: values.publish })
  console.log(JSON.stringify(result, null, 2))
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) main().catch(error => { console.error(error.message); process.exitCode = 1 })
