import test from 'node:test'
import assert from 'node:assert/strict'
import { resolveDesktopProfile, publicTracingReceipt } from './desktop-build-profile.mjs'

const tracing = { LANGFUSE_PUBLIC_KEY: 'pk-test', LANGFUSE_SECRET_KEY: 'sk-test' }
const input = { env: tracing, version: '0.5.0', buildId: '20260914T180000Z', publicConfig: {
  VINOTE_SUPABASE_URL: 'https://example.supabase.co', VINOTE_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_test',
} }

test('test and release packages use separate identities and fixed deployment origins', () => {
  const release = resolveDesktopProfile(input)
  const testing = resolveDesktopProfile({ ...input, channel: 'test' })
  assert.equal(release.version, '0.5.0')
  assert.equal(testing.version, '0.5.0-test')
  assert.notEqual(release.identifier, testing.identifier)
  assert.notEqual(release.binaryName, testing.binaryName)
  assert.notEqual(release.backendName, testing.backendName)
  assert.equal(release.config.VILAB_SERVER_URL, 'https://api.orulink.ai')
  assert.equal(testing.config.VILAB_SERVER_URL, 'http://192.168.1.143:9876')
  assert.equal(testing.config.MEETING_REVIEW_MODEL, 'gpt-6-astra')
  assert.equal(release.config.MEETING_REVIEW_MODEL, testing.config.MEETING_REVIEW_MODEL)
})

test('review model preference can explicitly reuse the primary model', () => {
  const profile = resolveDesktopProfile({ ...input, env: { ...tracing, MEETING_REVIEW_MODEL: '' } })
  assert.equal(profile.config.MEETING_REVIEW_MODEL, '')
})

test('stale URL overrides cannot change the bundled public server or leak credentials', () => {
  const profile = resolveDesktopProfile({ ...input, env: { ...tracing,
    VILAB_SERVER_URL: 'http://localhost:1111', VILAB_API_KEY: 'private', APP_JWT_SECRET: 'private',
    VINOTE_RELEASE_VILAB_SERVER_URL: 'https://api.example.com/',
  } })
  assert.equal(profile.config.VILAB_SERVER_URL, 'https://api.orulink.ai')
  assert.equal(profile.config.VILAB_API_KEY, undefined)
  assert.equal(profile.config.APP_JWT_SECRET, undefined)
})

test('invalid channel, file identifiers and bundled secret keys fail early', () => {
  assert.throws(() => resolveDesktopProfile({ ...input, channel: 'other' }))
  for (const buildId of ['../escape', '.', '..']) assert.throws(() => resolveDesktopProfile({ ...input, buildId }))
  assert.throws(() => resolveDesktopProfile({ ...input, env: { ...tracing, VINOTE_SUPABASE_PUBLISHABLE_KEY: 'sb_secret_bad' } }))
})

for (const channel of ['test', 'release']) {
  test(`${channel} always enables tracing and requires complete project credentials`, () => {
    const profile = resolveDesktopProfile({ ...input, channel, env: { ...tracing, LANGFUSE_ENABLED: 'false' } })
    assert.equal(profile.config.LANGFUSE_ENABLED, 'true')
    assert.equal(profile.config.LANGFUSE_TRACING_ENVIRONMENT, channel === 'test' ? 'test' : 'production')
    assert.equal(profile.config.LANGFUSE_SECRET_KEY, tracing.LANGFUSE_SECRET_KEY)
    assert.throws(() => resolveDesktopProfile({ ...input, channel, env: {} }), /Langfuse/)
    assert.throws(() => resolveDesktopProfile({ ...input, channel, env: { ...tracing, LANGFUSE_SECRET_KEY: ' ' } }), /Langfuse/)
    assert.throws(() => resolveDesktopProfile({ ...input, channel, env: { ...tracing, LANGFUSE_BASE_URL: 'https://user:password@example.com' } }), /Langfuse/)
  })
}

test('public tracing receipts omit deployment and trace coordinates', () => {
  assert.deepEqual(publicTracingReceipt({ observations: 8, mock_provider: true,
    environment: 'production', release: '0.3.0', trace_url: 'https://private.invalid/trace',
    trace_id: 'private-id', task_id: 'private-task', secret: 'private-secret' }),
  { observations: 8, mock_provider: true, environment: 'production', release: '0.3.0' })
})
