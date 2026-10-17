import { afterEach, expect, it, vi } from 'vitest'
import { getTranslationModels, validatedTranslationModel, mcpRecoveryKey, readMCPReceipts, writeMCPReceipt, translationArguments, translationFields, translationText, verifyMCPRun, translationSaveBody, type MCPReceipt } from './mcpTranslation'
import type { MCPTool, MCPRun } from './mcpConnections'
import type { WorkspaceNote } from './workspace'
const tool: MCPTool = { name: 'real-service-tool', description: '', enabled: true, inputSchema: { type: 'object', properties: { body: { type: 'string' }, target: { type: 'string', enum: ['en', 'zh'] } }, required: ['body', 'target'] }, definitionHash: 'hash', annotations: {}, requiresConfirmation: true }
const source = { note_key: 'note', source_version_id: 'older-version', base_revision: 5, content: '完整原文' }
const mapping = { text_parameter: 'body', language_parameter: 'target', target_language: 'en' as const }
const api = vi.hoisted(() => ({ json: vi.fn() }))
vi.mock('./api', () => ({ apiJson: api.json }))
const receipt: MCPReceipt = { connectionId: 'service', requestId: 'original-request', toolName: tool.name, arguments: { body: source.content, target: 'en' }, source, mapping }
const run: MCPRun = { id: 'run', connectionId: 'service', requestId: 'original-request', toolName: tool.name, arguments: receipt.arguments, result: { content: [{ type: 'text', text: 'Translated text' }] }, status: 'succeeded', error: null, confirmationToken: null, confirmationExpiresAt: null, createdAt: '', updatedAt: '' }
afterEach(() => { localStorage.clear(); vi.restoreAllMocks() })
it('maps exactly two explicitly selected real schema string fields, with only zh/en', () => {
  expect(translationFields(tool)).toEqual(['body', 'target'])
  expect(translationArguments(tool, source, mapping)).toEqual(receipt.arguments)
  expect(() => translationArguments(tool, source, { ...mapping, target_language: 'ja' as never })).toThrow('中文或英文')
  expect(() => translationArguments(tool, source, { ...mapping, language_parameter: 'language' })).toThrow()
  expect(() => translationArguments(tool, source, { ...mapping, language_parameter: 'body' })).toThrow()
})
it('rejects extra required parameters and complex schema instead of guessing', () => {
  expect(() => translationArguments({ ...tool, inputSchema: { ...tool.inputSchema, required: ['body', 'target', 'secret'] } }, source, mapping)).toThrow('其他参数')
  expect(translationFields({ ...tool, inputSchema: { ...tool.inputSchema, anyOf: [] } })).toEqual([])
  expect(translationFields({ ...tool, inputSchema: { type: 'object', properties: { body: { type: 'array' }, target: { type: 'string' } } } })).toEqual(['target'])
})
it('rejects incompatible enum/format/maxLength and does not reinterpret language values', () => {
  const schema = (field: unknown) => ({ ...tool, inputSchema: { ...tool.inputSchema, properties: { body: { type: 'string' }, target: field } } })
  expect(() => translationArguments(schema({ type: 'string', enum: ['English'] }), source, mapping)).toThrow('枚举')
  expect(() => translationArguments(schema({ type: 'string', format: 'uri' }), source, mapping)).toThrow('格式')
  expect(() => translationArguments(schema({ type: 'string', maxLength: 1 }), source, mapping)).toThrow('长度')
})
it('checks source 60k and real UTF8 JSON 64KiB without truncating', () => {
  expect(() => translationArguments(tool, { ...source, content: 'a'.repeat(60001) }, mapping)).toThrow('60000')
  expect(() => translationArguments(tool, { ...source, content: '中'.repeat(22000) }, mapping)).toThrow('64 KiB')
  expect(translationArguments(tool, { ...source, content: 'a'.repeat(60000) }, mapping).body).toHaveLength(60000)
  expect(() => translationArguments(tool, { ...source, content: '  ' }, mapping)).toThrow('没有正文')
})
it('extracts actual complete text only, rejecting errors, truncation and mixed image results', () => {
  expect(translationText(run)).toBe('Translated text')
  expect(translationText({ ...run, result: { content: [{ type: 'text', text: 'A' }, { type: 'text', text: 'B' }] } })).toBe('A\n\nB')
  for (const result of [{ isError: true, content: [{ type: 'text', text: 'error' }] }, { truncated: true, content: [{ type: 'text', text: 'partial' }] }, { content: [{ type: 'text', text: ' ' }] }, { content: [{ type: 'image', data: 'x' }] }]) expect(translationText({ ...run, result })).toBeNull()
  expect(translationText({ ...run, status: 'unknown' })).toBeNull()
})
it('durably isolates source/request/mapping by owner and never retains confirmation tokens', () => {
  writeMCPReceipt('alice', { ...receipt, confirmationToken: 'secret' } as MCPReceipt)
  expect(readMCPReceipts('alice')[0]).toMatchObject(receipt)
  expect(readMCPReceipts('bob')).toEqual([])
  expect(localStorage.getItem(mcpRecoveryKey('alice'))).not.toContain('secret')
  expect(() => writeMCPReceipt('alice', { ...receipt, arguments: { body: 'other', target: 'en' } })).toThrow('不一致')
})
it('does not discard corrupted or unwritable recovery data', () => {
  localStorage.setItem(mcpRecoveryKey('alice'), '{bad')
  expect(() => readMCPReceipts('alice')).toThrow('无法读取')
  expect(() => writeMCPReceipt('alice', receipt)).toThrow('无法读取')
  localStorage.clear(); vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
  expect(() => writeMCPReceipt('alice', receipt)).toThrow('quota')
})
it('verifies exact original request and preserves save uncertainty while querying', () => {
  expect(verifyMCPRun({ ...receipt, saving: true }, run)).toMatchObject({ runId: 'run', saving: true })
  expect(() => verifyMCPRun(receipt, { ...run, requestId: 'other' })).toThrow('不一致')
  expect(() => verifyMCPRun(receipt, { ...run, arguments: { ...receipt.arguments, extra: 'x' } })).toThrow('不一致')
})
it('creates a standard CAS edit version retaining original parent and rejects a changed baseline', () => {
  const note = { key: 'note', title: '原笔记', revision: 5, deleted: false, source_type: 'document', source_device: 'desktop', metadata: { project: '保持项目' }, versions: [{ id: 'older-version', content: source.content }] } as unknown as WorkspaceNote
  const body = translationSaveBody(note, receipt, run)
  expect(body).toMatchObject({ base_revision: 5, content: 'Translated text', title: '原笔记', metadata: { project: '保持项目' }, versions: [{ parent_id: 'older-version' }] })
  expect(body.metadata?.default_version_id).toBe(body.versions?.[0].id)
  expect(() => translationSaveBody({ ...note, revision: 6 }, receipt, run)).toThrow('变化')
})
it('reads only owner-session available models and rejects an unvalidated default without choosing the first item', async () => {
  const catalog = { providerId: 'vinote-cloud-translation', modelParameter: 'model' as const, models: [{ id: 'codex/gpt-6-luna', modelType: 'llm' as const, runtimeStatus: 'available' as const }], defaultModel: null };
  api.json.mockResolvedValue(catalog);
  expect(await getTranslationModels()).toEqual(catalog);
  expect(api.json).toHaveBeenCalledWith('/api/mcp-connections/first-party/translation/models');
  expect(() => validatedTranslationModel(catalog, '')).toThrow('明确选择');
  expect(() => validatedTranslationModel(catalog, 'removed')).toThrow('不会自动替换');
  expect(validatedTranslationModel(catalog, 'codex/gpt-6-luna')).toBe('codex/gpt-6-luna');
  api.json.mockResolvedValue({ ...catalog, defaultModel: 'removed' });
  await expect(getTranslationModels()).rejects.toThrow('无法核验');
  api.json.mockResolvedValue({ ...catalog, models: [{ ...catalog.models[0], runtimeStatus: 'unavailable' }] });
  await expect(getTranslationModels()).rejects.toThrow('无法核验');
});
it('validates official model schema and binds its exact ID to durable source/language arguments', () => {
  const official = { ...tool, name: 'vinote_translate_text', inputSchema: { type: 'object', additionalProperties: false, required: ['text', 'target_language'], properties: { text: { type: 'string' }, target_language: { type: 'string', enum: ['en', 'zh'] }, model: { type: 'string', minLength: 1, maxLength: 200, pattern: '^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$' } } } };
  const modelMapping = { text_parameter: 'text', language_parameter: 'target_language', target_language: 'en' as const, model_parameter: 'model' as const, model: 'codex/gpt-6-luna' };
  const args = translationArguments(official, source, modelMapping);
  expect(args).toEqual({ text: source.content, target_language: 'en', model: 'codex/gpt-6-luna' });
  const saved = { ...receipt, toolName: official.name, arguments: args, mapping: modelMapping };
  writeMCPReceipt('alice', saved);
  expect(readMCPReceipts('alice')[0]).toMatchObject(saved);
  expect(() => writeMCPReceipt('alice', { ...saved, arguments: { ...args, model: 'other' } })).toThrow('不一致');
  expect(() => writeMCPReceipt('alice', { ...saved, arguments: { ...args, model: 'other' }, mapping: { ...modelMapping, model: 'other' } })).toThrow('已固定');
  expect(() => translationArguments(official, source, { ...modelMapping, model: 'bad model' })).toThrow('格式');
  expect(() => translationArguments(official, source, { ...modelMapping, model: 'x'.repeat(201) })).toThrow('长度');
  expect(() => translationArguments(tool, source, { ...mapping, model_parameter: 'model', model: 'codex/gpt-6-luna' })).toThrow('无法核验');
});
