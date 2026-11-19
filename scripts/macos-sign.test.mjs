import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { nativeSignTargets } from './macos-sign.mjs'

test('native signing discovers Mach-O files and ignores aliases and foreign executables', () => {
  const root = mkdtempSync(join(tmpdir(), 'vinote-sign-'))
  try {
    mkdirSync(join(root, 'nested'))
    const binary = join(root, 'nested', 'native')
    writeFileSync(binary, Buffer.from('cffaedfe00000000', 'hex'))
    writeFileSync(join(root, 'linux'), Buffer.from('7f454c4600000000', 'hex'))
    writeFileSync(join(root, 'text'), 'plain text')
    symlinkSync(binary, join(root, 'alias'))
    assert.deepEqual(nativeSignTargets(root), [binary])
  } finally { rmSync(root, { recursive: true }) }
})
