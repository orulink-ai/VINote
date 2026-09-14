import { createHash } from 'node:crypto'

export function resolveDesktopProfile({ channel = 'release', version, env = {}, publicConfig, buildId }) {
  if (!['release', 'test'].includes(channel)) throw new Error('Channel must be release or test')
  if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error('Base version must be major.minor.patch')
  if (!/^[a-zA-Z0-9._-]+$/.test(buildId)) throw new Error('Invalid build ID')
  const test = channel === 'test'
  const origin = env[test ? 'VINOTE_TEST_VILAB_SERVER_URL' : 'VINOTE_RELEASE_VILAB_SERVER_URL']
    || 'http://192.168.1.143:9876'
  const url = new URL(origin)
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('VILab URL must be an HTTP(S) origin without credentials, query or path')
  }
  const config = {
    VILAB_SERVER_URL: url.origin,
    VINOTE_SUPABASE_URL: env.VINOTE_SUPABASE_URL || publicConfig.VINOTE_SUPABASE_URL,
    VINOTE_SUPABASE_PUBLISHABLE_KEY: env.VINOTE_SUPABASE_PUBLISHABLE_KEY || publicConfig.VINOTE_SUPABASE_PUBLISHABLE_KEY,
    LANGFUSE_RELEASE: test ? `${version}-test` : version,
    LANGFUSE_TRACING_ENVIRONMENT: test ? 'test' : 'production',
    MEETING_REVIEW_MODEL: env.MEETING_REVIEW_MODEL ?? publicConfig.MEETING_REVIEW_MODEL ?? 'gpt-6-astra',
  }
  if (!config.VINOTE_SUPABASE_URL || !config.VINOTE_SUPABASE_PUBLISHABLE_KEY?.startsWith('sb_publishable_')) {
    throw new Error('Email accounts require a Supabase URL and publishable key; secret keys cannot be bundled')
  }
  return {
    channel, buildId, version: config.LANGFUSE_RELEASE,
    productName: test ? 'VINote Test' : 'VINote',
    identifier: test ? 'app.vinote.desktop.test' : 'app.vinote.desktop',
    binaryName: test ? 'vinote-test' : 'vinote',
    backendName: test ? 'vinote-test-backend' : 'vinote-backend',
    config,
  }
}

export function checksum(contents) {
  return createHash('sha256').update(contents).digest('hex')
}
