import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'
import { root } from './runtime.mjs'

const packageJson = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))

test('root scripts expose one canonical runtime and package command set', () => {
  const scripts = packageJson.scripts
  for (const target of ['desktop', 'web']) {
    for (const environment of ['lan', 'public']) {
      const key = `dev:${target}:${environment}`
      assert.equal(scripts[key], `node scripts/dev.mjs --target ${target} --environment ${environment}`)
      assert.equal(scripts[`${key}:plan`], `${scripts[key]} --plan`)
    }
  }
  assert.equal(scripts.setup, 'node scripts/dev.mjs --setup-only')
  assert.equal(scripts.verify, 'node scripts/verify-project.mjs')
  assert.equal(scripts.check, 'yarn --cwd frontend build && yarn desktop:check')
  assert.equal(scripts['dev:desktop'], 'node scripts/legacy-command.mjs dev:desktop dev:desktop:lan')
  assert.equal(scripts['client:test:dev'], 'node scripts/legacy-command.mjs client:test:dev dev:desktop:lan')
  assert.equal(scripts['client:dev'], 'node scripts/legacy-command.mjs client:dev dev:desktop:public')
  assert.equal(scripts['client:test'], 'node scripts/legacy-command.mjs client:test package:test')
  assert.equal(scripts['client:production'], 'node scripts/legacy-command.mjs client:production package:release')
  assert.equal(scripts['dev:api'], 'node scripts/dev-api.mjs')
  assert.equal(scripts['package:test'], 'node scripts/build-desktop.mjs --channel test')
  assert.equal(scripts['package:release'], 'node scripts/build-desktop.mjs --channel release')
  assert.equal(scripts['package:test:plan'], 'node scripts/build-desktop.mjs --channel test --plan')
  assert.equal(scripts['package:release:plan'], 'node scripts/build-desktop.mjs --channel release --plan')
})

test('compatibility launchers delegate without owning ports or processes', () => {
  for (const name of ['start-dev.ps1', 'start-dev.sh']) {
    const source = readFileSync(join(root, name), 'utf8')
    assert.match(source, /yarn dev/)
    assert.doesNotMatch(source, /taskkill|kill_on_port|Get-NetTCPConnection|Start-Process/)
  }
  const batch = readFileSync(join(root, 'start-dev.bat'), 'utf8')
  assert.match(batch, /start-dev\.ps1/)
})

test('obsolete shell implementations are removed', () => {
  assert.equal(existsSync(join(root, 'scripts/dev-desktop.sh')), false)
  assert.equal(existsSync(join(root, 'scripts/ensure-web-dev.sh')), false)
})
