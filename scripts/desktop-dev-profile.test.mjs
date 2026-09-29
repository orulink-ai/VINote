import assert from 'node:assert/strict'
import { execFileSync, spawn } from 'node:child_process'
import { createConnection, createServer } from 'node:net'
import test from 'node:test'
import { resolveDesktopDevProfile } from './desktop-dev-profile.mjs'
import { serviceOrigin } from './service-environments.mjs'

const stale = { ...process.env, VILAB_SERVER_URL: 'http://localhost:9878',
  VINOTE_TEST_VILAB_SERVER_URL: 'https://test.example.com',
  VINOTE_DEV_VILAB_SERVER_URL: 'https://dev.example.com',
  VINOTE_RELEASE_VILAB_SERVER_URL: 'https://release.example.com',
  LANGFUSE_SECRET_KEY: 'must-not-print' }

test('source environments have fixed origins, distinct identities and development tracing', () => {
  const lan = resolveDesktopDevProfile({ environment: 'lan', env: stale, version: '0.6.1' })
  const publicProfile = resolveDesktopDevProfile({ environment: 'public', env: stale, version: '0.6.1' })
  assert.equal(lan.server, 'http://192.168.1.143:9876')
  assert.equal(publicProfile.server, 'https://api.orulink.ai')
  assert.notEqual(lan.identifier, publicProfile.identifier)
  assert.equal(lan.tracingEnvironment, 'development')
  assert.equal(publicProfile.tracingEnvironment, 'development')
  for (const invalid of ['production', 'constructor', '__proto__']) assert.throws(() => serviceOrigin(invalid))
})

for (const target of ['desktop', 'web']) {
  for (const environment of ['lan', 'public']) {
    test(`${target}/${environment} plan resolves without bootstrap, services or secrets`, () => {
      const stdout = execFileSync(process.execPath, ['scripts/dev.mjs', '--target', target, '--environment', environment, '--plan'], {
        encoding: 'utf8', windowsHide: true, env: stale,
      })
      const plan = JSON.parse(stdout)
      assert.equal(plan.target, target)
      assert.equal(plan.environment, environment)
      assert.equal(plan.server, undefined)
      assert.equal(stdout.includes(serviceOrigin(environment)), false)
      assert.equal(plan.backend, 'http://127.0.0.1:8900')
      assert.equal(stdout.includes('must-not-print'), false)
    })
  }
}

test('legacy development command now resolves to public instead of localhost', () => {
  const stdout = execFileSync(process.execPath, ['scripts/legacy-command.mjs', 'client:dev', 'dev:desktop:public', '--plan'], {
    encoding: 'utf8', windowsHide: true, env: stale, stdio: ['ignore', 'pipe', 'pipe'],
  })
  assert.equal(JSON.parse(stdout).environment, 'public')
  assert.equal(JSON.parse(stdout).server, undefined)
})

test('occupied API port blocks web startup without terminating its owner', async () => {
  const server = createServer()
  let ownsServer = false
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(8900, '127.0.0.1', resolve) })
    ownsServer = true
  } catch (error) {
    if (error.code !== 'EADDRINUSE') throw error
  }
  try {
    const child = spawn(process.execPath, ['scripts/dev.mjs', '--target', 'web', '--environment', 'public'], { windowsHide: true })
    let output = ''
    child.stdout.on('data', chunk => { output += chunk })
    child.stderr.on('data', chunk => { output += chunk })
    const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('exit', resolve) })
    assert.equal(code, 1)
    assert.match(output, /8900|开发实例已运行/)
    if (ownsServer) assert.equal(server.listening, true)
    await new Promise((resolve, reject) => {
      const socket = createConnection({ host: '127.0.0.1', port: 8900 })
      socket.once('connect', () => { socket.destroy(); resolve() })
      socket.once('error', reject)
    })
  } finally {
    if (ownsServer) await new Promise(resolve => server.close(resolve))
  }
})
