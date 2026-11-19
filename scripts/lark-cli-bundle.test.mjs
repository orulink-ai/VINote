import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, realpathSync, symlinkSync } from 'node:fs'
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
    assert.equal(resolveLarkCli({ platform: 'win32', path: root }), realpathSync(native))
    assert.throws(() => resolveLarkCli({ platform: 'win32', override: join(root, 'lark-cli.cmd') }))
    assert.throws(() => resolveLarkCli({ platform: 'win32', override: './config.json' }))
  } finally { rmSync(root, { recursive: true, force: true }) }
})

test('macOS npm launcher resolves to its bundled native executable', () => {
  const root = mkdtempSync(join(tmpdir(), 'vinote-macos-cli-'))
  try {
    const packageRoot = join(root, 'lib', 'node_modules', '@larksuite', 'cli')
    mkdirSync(join(packageRoot, 'scripts'), { recursive: true })
    mkdirSync(join(packageRoot, 'bin'), { recursive: true })
    mkdirSync(join(root, 'bin'))
    writeFileSync(join(packageRoot, 'scripts', 'run.js'), '#!/usr/bin/env node')
    const native = join(packageRoot, 'bin', 'lark-cli')
    writeFileSync(native, 'native fixture')
    symlinkSync(join(packageRoot, 'scripts', 'run.js'), join(root, 'bin', 'lark-cli'))
    assert.equal(resolveLarkCli({ platform: 'darwin', path: join(root, 'bin') }), realpathSync(native))
  } finally { rmSync(root, { recursive: true, force: true }) }
})
