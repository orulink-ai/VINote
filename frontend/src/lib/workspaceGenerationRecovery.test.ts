import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearGenerationRecovery, readGenerationRecovery, writeGenerationRecovery } from './workspaceGenerationRecovery'

afterEach(() => { localStorage.clear(); vi.restoreAllMocks() })
describe('generation recovery', () => {
  const request = { operation_id: 'generation-once', base_revision: 4, template: 'summary', instructions: '保留证据' }
  it('retains the original operation and completed result across re-entry, isolated by account and note', () => {
    writeGenerationRecovery('alice', 'note/a', { ...request, generatedContent: '# 已生成但保存冲突' })
    expect(readGenerationRecovery('alice', 'note/a')).toEqual({ ...request, generatedContent: '# 已生成但保存冲突' })
    expect(readGenerationRecovery('bob', 'note/a')).toBeNull()
    expect(readGenerationRecovery('alice', 'note/b')).toBeNull()
    clearGenerationRecovery('alice', 'note/a')
    expect(readGenerationRecovery('alice', 'note/a')).toBeNull()
  })
  it('does not hide a failed durable write behind a successful-looking recovery', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    expect(() => writeGenerationRecovery('alice', 'a', request)).toThrow('quota')
    expect(readGenerationRecovery('alice', 'a')).toBeNull()
  })
})
