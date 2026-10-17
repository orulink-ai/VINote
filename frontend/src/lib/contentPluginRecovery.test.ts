import { afterEach, describe, expect, it, vi } from 'vitest'
import { canRetryContentPluginRun, clearSavedContentPluginReceipt, contentPluginRecoveryKey, readContentPluginReceipts, rememberContentPluginRun, writeContentPluginReceipt, type ContentPluginReceipt } from './contentPluginRecovery'

const receipt: ContentPluginReceipt = { request: { operation_id: 'operation-a', plugin_id: 'translation', note_key: 'note-a', version_id: 'original', base_revision: 3, language: 'ja', glossary: '' }, phase: 'submitted', created_at: '2026-10-12T00:00:00Z' }
const run = { id: 'operation-a', plugin_id: 'translation', note_key: 'note-a', base_revision: 3, status: 'ready', source_version_id: 'original', language: 'ja', output: '译文', error: '', model: 'model', created_at: receipt.created_at }
afterEach(() => { localStorage.clear(); vi.restoreAllMocks() })

describe('durable content plugin receipts', () => {
  it('retains source version, language and operation on cold re-entry, isolated by account', () => {
    writeContentPluginReceipt('alice', receipt)
    expect(readContentPluginReceipts('alice')).toEqual([receipt])
    expect(readContentPluginReceipts('bob')).toEqual([])
  })
  it('cannot replace an unknown operation with a different source or language', () => {
    writeContentPluginReceipt('alice', receipt)
    expect(() => writeContentPluginReceipt('alice', { ...receipt, request: { ...receipt.request, language: 'de' } })).toThrow('其他来源')
    expect(readContentPluginReceipts('alice')).toEqual([receipt])
  })
  it('keeps an uncertain save and will not clear it until a confirmed saved receipt', () => {
    writeContentPluginReceipt('alice', { ...receipt, phase: 'saving' })
    expect(() => clearSavedContentPluginReceipt('alice', run.id)).toThrow('尚未确认')
    rememberContentPluginRun('alice', { ...run, status: 'saved' })
    clearSavedContentPluginReceipt('alice', run.id)
    expect(readContentPluginReceipts('alice')).toEqual([])
  })
  it('rejects a contradictory server source without losing the original receipt', () => {
    writeContentPluginReceipt('alice', receipt)
    expect(() => rememberContentPluginRun('alice', { ...run, source_version_id: 'different' })).toThrow('不一致')
    expect(readContentPluginReceipts('alice')).toEqual([receipt])
  })
  it('does not hide corrupt or unwritable recovery storage', () => {
    localStorage.setItem(contentPluginRecoveryKey('alice'), '{bad')
    expect(() => readContentPluginReceipts('alice')).toThrow('无法读取')
    expect(() => writeContentPluginReceipt('alice', receipt)).toThrow('无法读取')
    localStorage.clear()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    expect(() => writeContentPluginReceipt('alice', receipt)).toThrow('quota')
  })
  it('enables retry only with the server safety flag and an eligible status', () => {
    expect(canRetryContentPluginRun({ ...run, status: 'failed' })).toBe(false)
    expect(canRetryContentPluginRun({ ...run, status: 'interrupted', retry_safe: false })).toBe(false)
    expect(canRetryContentPluginRun({ ...run, plugin_id: 'actions', language: 'zh', status: 'failed', retry_safe: true })).toBe(true)
    expect(canRetryContentPluginRun({ ...run, language: 'zh', status: 'failed', retry_safe: true })).toBe(false)
    expect(canRetryContentPluginRun({ ...run, status: 'running', retry_safe: true })).toBe(false)
  })
  it('restores a server-side run with its source instead of the current default version', () => {
    const saved = rememberContentPluginRun('alice', run)
    expect(saved.request.version_id).toBe('original')
    expect(saved.request.language).toBe('ja')
    expect(() => rememberContentPluginRun('alice', { ...run, id: 'legacy', source_version_id: undefined })).toThrow('源版本')
  })
  it('preserves historical languages for lookup without allowing a new translation retry', () => {
    rememberContentPluginRun('alice', { ...run, language: 'fr', status: 'failed', retry_safe: true })
    expect(readContentPluginReceipts('alice')[0].request.language).toBe('fr')
    expect(canRetryContentPluginRun({ ...run, status: 'failed', retry_safe: true })).toBe(false)
  })
})
