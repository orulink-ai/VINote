import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import test from 'node:test'
import { resolveDesktopDevProfile } from './desktop-dev-profile.mjs'

test('test development ignores stale local server settings and uses a separate identity', () => {
  const env = { VILAB_SERVER_URL: 'http://localhost:9878' }
  const testing = resolveDesktopDevProfile({ channel: 'test', env, version: '0.5.2' })
  const local = resolveDesktopDevProfile({ channel: 'development', env, version: '0.5.2' })
  assert.equal(testing.server, 'http://192.168.1.143:9876')
  assert.equal(local.server, 'http://127.0.0.1:9878')
  assert.notEqual(testing.identifier, local.identifier)
  assert.equal(testing.tracingEnvironment, 'test')
  assert.equal(local.tracingEnvironment, 'development')
})

test('channel-specific origins take precedence and development has a local default', () => {
  const env = { VINOTE_TEST_VILAB_SERVER_URL: 'https://test.example.com',
    VINOTE_DEV_VILAB_SERVER_URL: 'http://127.0.0.1:9988', VILAB_SERVER_URL: 'http://localhost:9878' }
  assert.equal(resolveDesktopDevProfile({ channel: 'test', env }).server, env.VINOTE_TEST_VILAB_SERVER_URL)
  assert.equal(resolveDesktopDevProfile({ channel: 'development', env }).server, env.VINOTE_DEV_VILAB_SERVER_URL)
  assert.equal(resolveDesktopDevProfile({ channel: 'development' }).server, 'http://127.0.0.1:9878')
  assert.throws(() => resolveDesktopDevProfile({ channel: 'production' }))
  assert.throws(() => resolveDesktopDevProfile({ env: { VINOTE_TEST_VILAB_SERVER_URL: 'https://secret:password@example.com' } }))
})

test('plan exits without launching services and never prints private environment values', () => {
  const stdout = execFileSync(process.execPath, ['scripts/dev-desktop.mjs', '--channel', 'test', '--plan'], {
    encoding: 'utf8', windowsHide: true,
    env: { ...process.env, VINOTE_TEST_VILAB_SERVER_URL: 'https://test.example.com', LANGFUSE_SECRET_KEY: 'must-not-print' },
  })
  const plan = JSON.parse(stdout)
  assert.equal(plan.server, 'https://test.example.com')
  assert.equal(plan.identifier, 'app.vinote.desktop.test.dev')
  assert.equal(stdout.includes('must-not-print'), false)
})
