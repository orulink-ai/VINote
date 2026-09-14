import test from 'node:test'
import assert from 'node:assert/strict'
import { resolveDesktopProfile } from './desktop-build-profile.mjs'

const input = { version: '0.5.0', buildId: '20260914T180000Z', publicConfig: {
  VINOTE_SUPABASE_URL: 'https://example.supabase.co', VINOTE_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_test',
} }

test('test and release packages use separate identities but the same deployed origin', () => {
  const release = resolveDesktopProfile(input)
  const testing = resolveDesktopProfile({ ...input, channel: 'test' })
  assert.equal(release.version, '0.5.0')
  assert.equal(testing.version, '0.5.0-test')
  assert.notEqual(release.identifier, testing.identifier)
  assert.notEqual(release.binaryName, testing.binaryName)
  assert.notEqual(release.backendName, testing.backendName)
  assert.equal(release.config.VILAB_SERVER_URL, 'http://192.168.1.143:9876')
  assert.equal(testing.config.VILAB_SERVER_URL, release.config.VILAB_SERVER_URL)
  assert.equal(testing.config.MEETING_REVIEW_MODEL, 'gpt-6-astra')
  assert.equal(release.config.MEETING_REVIEW_MODEL, testing.config.MEETING_REVIEW_MODEL)
})

test('review model preference can explicitly reuse the primary model', () => {
  const profile = resolveDesktopProfile({ ...input, env: { MEETING_REVIEW_MODEL: '' } })
  assert.equal(profile.config.MEETING_REVIEW_MODEL, '')
})

test('channel-specific overrides do not leak source dev URL or credentials', () => {
  const profile = resolveDesktopProfile({ ...input, env: {
    VILAB_SERVER_URL: 'http://localhost:1111', VILAB_API_KEY: 'private', APP_JWT_SECRET: 'private',
    VINOTE_RELEASE_VILAB_SERVER_URL: 'https://api.example.com/',
  } })
  assert.equal(profile.config.VILAB_SERVER_URL, 'https://api.example.com')
  assert.equal(profile.config.VILAB_API_KEY, undefined)
  assert.equal(profile.config.APP_JWT_SECRET, undefined)
})

test('invalid channel, file identifiers and bundled secret keys fail early', () => {
  assert.throws(() => resolveDesktopProfile({ ...input, channel: 'other' }))
  assert.throws(() => resolveDesktopProfile({ ...input, buildId: '../escape' }))
  assert.throws(() => resolveDesktopProfile({ ...input, env: { VINOTE_SUPABASE_PUBLISHABLE_KEY: 'sb_secret_bad' } }))
  assert.throws(() => resolveDesktopProfile({ ...input, env: { VINOTE_RELEASE_VILAB_SERVER_URL: 'https://key@host' } }))
})
