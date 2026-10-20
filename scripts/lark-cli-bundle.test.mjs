import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { resolveLarkCli } from './lark-cli-bundle.mjs'

test('packages only the native npm executable, never a shell shim or config', () => {
  const root = mkdtempSync(join(tmpdir(), 'vinote-cli-'))
  try {
    const native = join(root, 'node_modules', '@larksuite', 'cli', 'bin', 'lark-cli.exe')
    mkdirSync(join(root, 'node_modules', '@larksuite', 'cli', 'bin'), { recursive: true })
    writeFileSync(native, 'synthetic native file')
    writeFileSync(join(root, 'lark-cli.cmd'), 'synthetic shim')
    assert.equal(resolveLarkCli({ platform: 'win32', path: root }), native)
    assert.throws(() => resolveLarkCli({ platform: 'win32', override: join(root, 'lark-cli.cmd') }))
    assert.throws(() => resolveLarkCli({ platform: 'win32', override: './config.json' }))
  } finally { rmSync(root, { recursive: true, force: true }) }
})
