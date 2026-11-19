import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createMacUpdaterArchive, assertMacUpdaterArchive } from './macos-updater-archive.mjs'

test('macOS updater archive has one app root and no AppleDouble entries', { skip: process.platform === 'win32' }, () => {
  const root = mkdtempSync(join(tmpdir(), 'vinote-ota-archive-'))
  try {
    const fixture = process.platform === 'darwin' ? process.env.VINOTE_MACOS_OTA_FIXTURE_APP : undefined
    const app = fixture || join(root, 'VINote.app')
    if (!fixture) {
      mkdirSync(join(app, 'Contents'), { recursive: true })
      writeFileSync(join(app, 'Contents', 'Info.plist'), 'archive fixture')
    }
    const original = readFileSync(join(app, 'Contents', 'Info.plist'))
    const archive = join(root, 'update.app.tar.gz')
    createMacUpdaterArchive(app, archive)
    const entries = execFileSync('/usr/bin/tar', ['-tzf', archive], { encoding: 'utf8', env: { ...process.env, COPYFILE_DISABLE: '1' } }).trim().split('\n')
    assert.ok(entries.length >= 3)
    assert.ok(entries.every(name => name.split('/')[0] === 'VINote.app'), entries.join('\n'))
    assert.ok(entries.every(name => !name.split('/').some(part => part.startsWith('._'))))
    const extracted = join(root, 'extracted')
    mkdirSync(extracted)
    execFileSync('/usr/bin/tar', ['-xzf', archive, '-C', extracted])
    assert.deepEqual(readFileSync(join(extracted, 'VINote.app/Contents/Info.plist')), original)
  } finally { rmSync(root, { recursive: true }) }
})


test('updater archive validation rejects AppleDouble siblings before publishing', { skip: process.platform === 'win32' }, () => {
  const root = mkdtempSync(join(tmpdir(), 'vinote-ota-invalid-'))
  try {
    mkdirSync(join(root, 'VINote.app'))
    writeFileSync(join(root, '._VINote.app'), 'AppleDouble metadata fixture')
    const archive = join(root, 'invalid.tar.gz')
    execFileSync('/usr/bin/tar', ['-czf', archive, '-C', root, '._VINote.app', 'VINote.app'], { env: { ...process.env, COPYFILE_DISABLE: '1' } })
    assert.throws(() => assertMacUpdaterArchive(archive, 'VINote.app'), /AppleDouble/)
  } finally { rmSync(root, { recursive: true }) }
})

test('updater archive rejects a dot wrapper consumed as the app root', { skip: process.platform === 'win32' }, () => {
  const root = mkdtempSync(join(tmpdir(), 'vinote-ota-wrapper-'))
  try {
    mkdirSync(join(root, 'VINote.app'))
    const archive = join(root, 'wrapped.tar.gz')
    execFileSync('/usr/bin/tar', ['-czf', archive, '-C', root, './VINote.app'], { env: { ...process.env, COPYFILE_DISABLE: '1' } })
    assert.throws(() => assertMacUpdaterArchive(archive, 'VINote.app'), /one application root/)
  } finally { rmSync(root, { recursive: true }) }
})
