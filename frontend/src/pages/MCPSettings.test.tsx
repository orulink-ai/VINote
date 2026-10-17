import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { readMCPReceipts, writeMCPReceipt } from '@/lib/mcpTranslation'
const api = vi.hoisted(() => ({ json: vi.fn(), connections: vi.fn(), runs: vi.fn(), detail: vi.fn(), save: vi.fn() }))
vi.mock('@/lib/api', () => ({ apiJson: api.json }))
vi.mock('@/lib/mcpConnections', async () => ({ ...(await vi.importActual<typeof import('@/lib/mcpConnections')>('@/lib/mcpConnections')), mcpBase: '/api/mcp-connections', listMCPConnections: api.connections, listMCPRuns: api.runs, mcpRunLabel: { awaiting_confirmation: '等待确认', succeeded: '已完成', unknown: '结果未知', failed: '失败' } }))
vi.mock('@/stores/authStore', async () => { const { create } = await import('zustand'); return { useAuthStore: create(() => ({ user: { id: 'alice' } })) } })
vi.mock('@/stores/workspaceStore', async () => { const { create } = await import('zustand'); return { useWorkspaceStore: create(() => ({ owner: 'alice', pending: [], loadDetail: api.detail, save: api.save })) } })
vi.mock('@/components/Markdown/MarkdownContent', () => ({ MarkdownContent: ({ content }: { content: string }) => <p>{content}</p> }))
import { MCPSettings } from './MCPSettings'
import { useAuthStore } from '@/stores/authStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
const connection = { id: 'service', name: '用户真实服务', url: 'https://service.test/mcp', enabled: true, status: 'connected', authType: 'none', lastError: null }
const tool = { name: 'actual_tool', enabled: true, inputSchema: { type: 'object', properties: { text_input: { type: 'string' }, destination: { type: 'string', enum: ['zh', 'en'] } }, required: ['text_input', 'destination'] }, description: '真实工具描述' }
const note = { key: 'note', title: '原笔记', content: '当前新版', revision: 5, deleted: false, source_type: 'document', source_device: 'desktop', metadata: { default_version_id: 'latest' }, versions: [{ id: 'older', title: '旧的源版本', content: '固定旧原文', created_at: '2026-10-12T00:00:00Z' }, { id: 'latest', title: '当前版本', content: '当前新版', created_at: '2026-10-12T00:01:00Z' }] }
const receipt = { connectionId: 'service', requestId: 'original-request', toolName: 'actual_tool', arguments: { text_input: '固定旧原文', destination: 'zh' }, source: { note_key: 'note', source_version_id: 'older', base_revision: 5, content: '固定旧原文' }, mapping: { text_parameter: 'text_input', language_parameter: 'destination', target_language: 'zh' as const } }
const run = { id: 'run', connectionId: 'service', requestId: receipt.requestId, toolName: tool.name, arguments: receipt.arguments, status: 'succeeded', result: { content: [{ type: 'text', text: '真实译文' }] }, error: null, confirmationToken: null }
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); useAuthStore.setState({ user: { id: 'alice' } } as never); useWorkspaceStore.setState({ owner: 'alice', pending: [] } as never)
  api.connections.mockResolvedValue({ connections: [connection] }); api.runs.mockResolvedValue({ runs: [] }); api.detail.mockResolvedValue(note)
  api.json.mockImplementation(async (path, options) => {
    if (path.endsWith('/capabilities')) return { transport: 'streamable-http' }
    if (path.endsWith('/tools')) return { tools: [tool] }
    if (path.includes('/by-request/')) return run
    if (path.endsWith('/invoke')) { const body = JSON.parse(options.body); return { ...run, requestId: body.requestId, arguments: body.arguments, status: body.confirmed ? 'succeeded' : 'awaiting_confirmation', result: body.confirmed ? run.result : null, confirmationToken: body.confirmed ? null : 'server-confirmation' } }
    throw new Error(`unexpected ${path}`)
  })
})
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks() })
function mount(path = '/settings/mcp?mode=translation&note=note&version=older') { return render(<MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><MCPSettings /></MemoryRouter>) }
async function choose() {
  fireEvent.click(screen.getByRole('button', { name: '连接与授权' }))
  fireEvent.click(await screen.findByRole('button', { name: /用户真实服务/ }))
  fireEvent.click(await screen.findByRole('button', { name: '选择此工具翻译（高级）' }))
  fireEvent.change(screen.getByLabelText('正文参数'), { target: { value: 'text_input' } }); fireEvent.change(screen.getByLabelText('目标语言参数'), { target: { value: 'destination' } }); fireEvent.click(screen.getByRole('button', { name: '返回全文翻译' })); fireEvent.change(screen.getByLabelText('目标语言'), { target: { value: 'zh' } })
}
it('uses actual schema mapping, persists before prepare, and only executes after server confirmation', async () => {
  mount(); await choose()
  expect(screen.getByLabelText('源版本')).toHaveValue('older')
  const implementation = api.json.getMockImplementation()!
  api.json.mockImplementation(async (path, options) => { if (path.endsWith('/invoke')) expect(readMCPReceipts('alice')[0].arguments).toEqual({ text_input: '固定旧原文', destination: 'zh' }); return implementation(path, options) })
  fireEvent.click(screen.getByRole('button', { name: '预览本次翻译' }))
  const confirm = await screen.findByRole('button', { name: '确认服务、正文与参数，执行工具' })
  expect(api.json.mock.calls.filter(([path]) => path.endsWith('/invoke'))).toHaveLength(1)
  fireEvent.click(confirm); await screen.findByText('真实译文')
  const body = JSON.parse(api.json.mock.calls.filter(([path]) => path.endsWith('/invoke'))[1][1].body)
  expect(body).toMatchObject({ confirmed: true, confirmationToken: 'server-confirmation', arguments: { text_input: '固定旧原文', destination: 'zh' } })
  expect(Object.keys(body.arguments)).toHaveLength(2); expect(localStorage.getItem('vinote:alice:mcp-invocations:v1')).not.toContain('server-confirmation'); expect(api.save).not.toHaveBeenCalled()
})
it('has a truthful configuration empty state when no remote service exists', async () => {
  api.connections.mockResolvedValue({ connections: [] }); mount()
  await waitFor(() => expect(screen.getByRole('button', { name: '预览本次翻译' })).toBeDisabled())
  fireEvent.click(screen.getByRole('button', { name: '连接与授权' }))
  expect(await screen.findByText('没有远程翻译工具')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '添加自定义翻译服务（高级）' })).toBeEnabled()
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false)
})
it('restores via precise GET even when no connection exists, previews original/result and preserves close', async () => {
  writeMCPReceipt('alice', receipt); api.connections.mockResolvedValue({ connections: [] }); mount()
  fireEvent.click(await screen.findByRole('button', { name: /actual_tool · 查询原请求/ })); await screen.findByText('真实译文')
  expect(api.json).toHaveBeenCalledWith('/api/mcp-connections/runs/by-request/original-request')
  expect(screen.getByText('固定旧原文')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '关闭预览（保留原请求）' })); expect(readMCPReceipts('alice')[0].requestId).toBe(receipt.requestId)
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false)
})
it('keeps a 404 original request and blocks a fresh invocation', async () => {
  writeMCPReceipt('alice', receipt)
  api.json.mockImplementation(async path => { if (path.endsWith('/capabilities')) return { transport: 'streamable-http' }; if (path.endsWith('/tools')) return { tools: [tool] }; throw new Error('原请求尚未查到') })
  mount(); fireEvent.click(await screen.findByRole('button', { name: /actual_tool · 查询原请求/ })); await screen.findAllByText('原请求尚未查到')
  expect(screen.queryByRole('button', { name: '预览本次翻译' })).not.toBeInTheDocument(); expect(readMCPReceipts('alice')[0].requestId).toBe(receipt.requestId)
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false)
})
it('does not POST when durable storage fails', async () => {
  mount(); await choose(); vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
  fireEvent.click(screen.getByRole('button', { name: '预览本次翻译' })); await screen.findAllByText('quota')
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false)
})
it('rejects extra mandatory schema inputs without exposing guessed parameter JSON', async () => {
  api.json.mockImplementation(async path => { if (path.endsWith('/capabilities')) return { transport: 'streamable-http' }; if (path.endsWith('/tools')) return { tools: [{ ...tool, inputSchema: { ...tool.inputSchema, required: ['text_input', 'destination', 'secret'] } }] }; throw new Error('unexpected') })
  mount(); await choose(); expect(screen.getByText(/此工具还需要其他参数/)).toBeInTheDocument(); expect(screen.getByRole('button', { name: '预览本次翻译' })).toBeDisabled(); expect(screen.queryByLabelText('本次参数（JSON）')).not.toBeInTheDocument()
})
it('keeps an uncertain save and verifies the actual version via GET without another remote invocation', async () => {
  writeMCPReceipt('alice', receipt); api.save.mockResolvedValue(null); mount()
  fireEvent.click(await screen.findByRole('button', { name: /actual_tool · 查询原请求/ })); await screen.findByText('真实译文'); fireEvent.click(screen.getByRole('button', { name: '核对无误，保存为新版本' }))
  await screen.findAllByText(/保存尚未确认/); expect(screen.getByRole('button', { name: '保存待核验' })).toBeDisabled()
  const saved = readMCPReceipts('alice')[0]; expect(saved.saveBody?.versions?.[0].parent_id).toBe('older'); expect(saved.saveBody?.base_revision).toBe(5)
  api.detail.mockResolvedValue({ ...note, revision: 6, versions: [...saved.saveBody!.versions!, ...note.versions] })
  fireEvent.click(screen.getByRole('button', { name: '查询原请求状态' })); await screen.findByRole('button', { name: '新版本已保存' }); expect(api.save).toHaveBeenCalledTimes(1)
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false)
})
it('does not reopen a closed dialog when the late preparation response arrives', async () => {
  mount(); await choose(); let finish!: (value: unknown) => void
  const implementation = api.json.getMockImplementation()!
  api.json.mockImplementation((path, options) => path.endsWith('/invoke') ? new Promise(resolve => { finish = resolve }) : implementation(path, options))
  fireEvent.click(screen.getByRole('button', { name: '预览本次翻译' })); const saved = readMCPReceipts('alice')[0]
  fireEvent.click(screen.getByRole('button', { name: '关闭预览（保留原请求）' })); await act(async () => finish({ ...run, requestId: saved.requestId, arguments: saved.arguments, status: 'awaiting_confirmation', result: null, confirmationToken: 'token' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument()); expect(readMCPReceipts('alice')[0].runId).toBe('run')
})
it('a confirmation timeout disables repeated execution and retains only GET recovery', async () => {
  mount(); await choose(); fireEvent.click(screen.getByRole('button', { name: '预览本次翻译' })); await screen.findByRole('button', { name: '确认服务、正文与参数，执行工具' })
  api.json.mockRejectedValue(new Error('调用结果未知'))
  fireEvent.click(screen.getByRole('button', { name: '确认服务、正文与参数，执行工具' })); await screen.findAllByText('调用结果未知')
  expect(screen.queryByRole('button', { name: '确认服务、正文与参数，执行工具' })).not.toBeInTheDocument()
  expect(readMCPReceipts('alice')[0].status).toBe('running'); expect(screen.getByRole('button', { name: '查询原请求状态' })).toBeEnabled()
  expect(api.json.mock.calls.filter(([path]) => path.endsWith('/invoke'))).toHaveLength(2)
})
it('drops an old account reply even after switching away and back', async () => {
  writeMCPReceipt('alice', receipt); mount(); let finish!: (value: unknown) => void
  const implementation = api.json.getMockImplementation()!
  api.json.mockImplementation((path, options) => path.includes('/by-request/') ? new Promise(resolve => { finish = resolve }) : implementation(path, options))
  fireEvent.click(await screen.findByRole('button', { name: /actual_tool · 查询原请求/ }))
  await act(async () => { useAuthStore.setState({ user: { id: 'bob' } } as never) }); await act(async () => { useAuthStore.setState({ user: { id: 'alice' } } as never) })
  await act(async () => finish(run))
  expect(screen.queryByText('真实译文')).not.toBeInTheDocument(); expect(readMCPReceipts('bob')).toEqual([])
})


const managedConnection = { ...connection, id: 'official', name: 'VINote 云翻译 · 第一方 MCP', managed: true, providerId: 'vinote-cloud-translation', authType: 'vinote-session', url: 'https://supabase-vinote.orulink.ai/vinote-api/api/mcp-first-party/translation', status: 'unverified', hasCredential: false };
const officialTool = { ...tool, name: 'vinote_translate_text', enabled: false, inputSchema: { type: 'object', additionalProperties: false, properties: { text: { type: 'string', maxLength: 60000 }, target_language: { type: 'string', enum: ['zh', 'en'] }, model: { type: 'string', minLength: 1, maxLength: 200, pattern: '^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$' } }, required: ['text', 'target_language'] } };
const provider = { id: 'vinote-cloud-translation', toolName: 'vinote_translate_text', textParameter: 'text', languageParameter: 'target_language', configured: true };
const models = { providerId: 'vinote-cloud-translation', modelParameter: 'model', models: [{ id: 'codex/gpt-6-luna', modelType: 'llm', runtimeStatus: 'available' }, { id: 'deepseek-v4.1-flash', modelType: 'llm', runtimeStatus: 'available' }], defaultModel: null };
function officialAPI(defaultModel: string | null = 'codex/gpt-6-luna') {
  api.json.mockImplementation(async (path, options) => {
    if (path.endsWith('/capabilities')) return { transport: 'streamable-http' };
    if (path.endsWith('/first-party/translation/models')) return { ...models, defaultModel };
    if (path.endsWith('/first-party/translation')) return { connection: managedConnection, provider };
    if (path.endsWith('/discover')) return { connection: { ...managedConnection, status: 'connected' }, tools: [officialTool] };
    if (path.endsWith('/tools') && options?.method === 'PATCH') return { ...officialTool, enabled: true };
    if (path.endsWith('/tools')) return { tools: [] };
    if (path.endsWith('/invoke')) {
      const body = JSON.parse(options.body);
      return { ...run, connectionId: 'official', toolName: officialTool.name, requestId: body.requestId, arguments: body.arguments,
        status: body.confirmed ? 'succeeded' : 'awaiting_confirmation', confirmationToken: body.confirmed ? null : 'official-confirmation', result: body.confirmed ? run.result : null };
    }
    throw new Error(`unexpected ${path}`);
  });
}
async function openOfficialModels(defaultModel: string | null = null) {
  officialAPI(defaultModel);
  api.connections.mockResolvedValue({ connections: [{ ...managedConnection, status: 'connected' }] });
  const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation(async (path, options) => path.endsWith('/tools') && !options ? { tools: [{ ...officialTool, enabled: true }] } : implementation(path, options));
  mount();
  await waitFor(() => expect(screen.getByLabelText('翻译模型')).toBeEnabled());
}
it('requires explicit model with a null default and freezes it across preview, confirmation and recovery', async () => {
  await openOfficialModels();
  expect(screen.getByLabelText('翻译模型')).toHaveValue('');
  expect(screen.getByRole('button', { name: '预览本次翻译' })).toBeDisabled();
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
  fireEvent.change(screen.getByLabelText('翻译模型'), { target: { value: 'deepseek-v4.1-flash' } });
  fireEvent.click(screen.getByRole('button', { name: '预览本次翻译' }));
  const confirm = await screen.findByRole('button', { name: '确认服务、正文与参数，执行工具' });
  expect(screen.getByText(/及模型 deepseek-v4.1-flash/)).toBeInTheDocument();
  expect(screen.queryByLabelText('翻译模型')).not.toBeInTheDocument();
  expect(readMCPReceipts('alice')[0]).toMatchObject({ arguments: { model: 'deepseek-v4.1-flash' }, mapping: { model: 'deepseek-v4.1-flash', model_parameter: 'model' } });
  fireEvent.click(confirm); await screen.findByText('真实译文');
  const calls = api.json.mock.calls.filter(([path]) => path.endsWith('/invoke'));
  expect(calls).toHaveLength(2);
  expect(JSON.parse(calls[1][1].body).arguments).toEqual(JSON.parse(calls[0][1].body).arguments);
  fireEvent.click(screen.getByRole('button', { name: '关闭预览（保留原请求）' }));
  fireEvent.click(screen.getByRole('button', { name: /vinote_translate_text · 查询原请求/ }));
  await waitFor(() => expect(api.json).toHaveBeenCalledWith(expect.stringContaining('/by-request/')));
  expect(api.json.mock.calls.filter(([path]) => path.endsWith('/invoke'))).toHaveLength(2);
});
it('does not silently replace a selected model when a refreshed catalog removes it', async () => {
  await openOfficialModels();
  fireEvent.change(screen.getByLabelText('翻译模型'), { target: { value: 'codex/gpt-6-luna' } });
  const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation(async (path, options) => path.endsWith('/translation/models') ? { ...models, models: [models.models[1]], defaultModel: models.models[1].id } : implementation(path, options));
  fireEvent.click(screen.getByRole('button', { name: '重新读取翻译模型' }));
  await screen.findByText(/所选翻译模型不可用/);
  expect(screen.getByLabelText('翻译模型')).toHaveValue('codex/gpt-6-luna');
  expect(screen.getByRole('button', { name: '预览本次翻译' })).toBeDisabled();
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
});
it('keeps model-read failures visible and blocks calls instead of guessing a default', async () => {
  await openOfficialModels();
  const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation(async (path, options) => { if (path.endsWith('/translation/models')) throw new Error('模型目录读取失败'); return implementation(path, options) });
  fireEvent.click(screen.getByRole('button', { name: '重新读取翻译模型' }));
  await screen.findByText('模型目录读取失败');
  expect(screen.getByLabelText('翻译模型')).toBeDisabled();
  expect(screen.getByRole('button', { name: '预览本次翻译' })).toBeDisabled();
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
});
it('ignores a late model catalog after switching accounts and switching back', async () => {
  officialAPI(); api.connections.mockResolvedValue({ connections: [{ ...managedConnection, status: 'connected' }] });
  const implementation = api.json.getMockImplementation()!;
  const replies: ((catalog: unknown) => void)[] = [];
  api.json.mockImplementation((path, options) => {
    if (path.endsWith('/translation/models')) return new Promise(resolve => { replies.push(resolve) });
    if (path.endsWith('/tools') && !options) return Promise.resolve({ tools: [{ ...officialTool, enabled: true }] });
    return implementation(path, options);
  });
  mount(); fireEvent.click(screen.getByRole('button', { name: '连接与授权' })); fireEvent.click(await screen.findByRole('button', { name: /VINote 云翻译 · 第一方 MCP · 已启用/ }));
  fireEvent.click(screen.getByRole('button', { name: '返回全文翻译' }));
  await screen.findByText('正在读取当前账号可用模型…');
  await act(async () => { useAuthStore.setState({ user: { id: 'bob' } } as never) });
  await act(async () => { useAuthStore.setState({ user: { id: 'alice' } } as never) });
  await act(async () => replies[0]({ ...models, defaultModel: 'codex/gpt-6-luna' }));
  expect(screen.queryByRole('button', { name: '预览本次翻译' })).toBeDisabled();
  expect(screen.queryByDisplayValue('codex/gpt-6-luna')).not.toBeInTheDocument();
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
});
it('requires rediscovery and a new grant when the official tool still has the old two-field schema', async () => {
  officialAPI(); api.connections.mockResolvedValue({ connections: [{ ...managedConnection, status: 'connected' }] });
  const implementation = api.json.getMockImplementation()!;
  const oldProperties = Object.fromEntries(Object.entries(officialTool.inputSchema.properties).filter(([key]) => key !== 'model'));
  api.json.mockImplementation(async (path, options) => path.endsWith('/tools') && !options ? { tools: [{ ...officialTool, enabled: true, inputSchema: { ...officialTool.inputSchema, properties: oldProperties } }] } : implementation(path, options));
  mount(); fireEvent.click(screen.getByRole('button', { name: '连接与授权' })); fireEvent.click(await screen.findByRole('button', { name: /VINote 云翻译 · 第一方 MCP · 已启用/ }));
  expect(await screen.findByRole('button', { name: '准备官方云翻译' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: '连接并发现工具' }));
  await screen.findByText('已发现工具，待授权翻译工具');
  expect(screen.getByRole('button', { name: '准备官方云翻译' })).toBeDisabled();
  fireEvent.click(screen.getByRole('switch', { name: '启用 vinote_translate_text' }));
  await waitFor(() => expect(screen.getByRole('button', { name: '准备官方云翻译' })).toBeEnabled());
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
});
it('keeps the old failed request read-only without adding a model or replaying it', async () => {
  const old = { ...receipt, connectionId: 'official', requestId: '6719ab4c-e08d-4f51-93d6-b3238eff3588', toolName: 'vinote_translate_text', arguments: { text: '固定旧原文', target_language: 'zh' }, mapping: { text_parameter: 'text', language_parameter: 'target_language', target_language: 'zh' as const }, status: 'failed' as const };
  writeMCPReceipt('alice', old);
  api.json.mockImplementation(async path => {
    if (path.endsWith('/capabilities')) return { transport: 'streamable-http' };
    if (path.includes('/by-request/')) return { ...run, ...old, id: old.requestId, status: 'failed', result: null, error: { code: 'model_unavailable', message: '原请求没有可用默认模型' } };
    throw new Error(`unexpected ${path}`);
  });
  mount(); fireEvent.click(await screen.findByRole('button', { name: /vinote_translate_text · 查询原请求/ }));
  await screen.findByText('原请求没有可用默认模型');
  expect(screen.queryByRole('button', { name: '确认服务、正文与参数，执行工具' })).not.toBeInTheDocument();
  expect(readMCPReceipts('alice')[0].arguments).toEqual(old.arguments);
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke') || path.endsWith('/translation/models'))).toBe(false);
});
it('provisions a real unverified connection, then discovers, grants and confirms fixed schema without URL or JSON fields', async () => {
  api.connections.mockResolvedValue({ connections: [] }); officialAPI(); mount();
  fireEvent.click(screen.getByRole('button', { name: '连接与授权' }));
  const connect = await screen.findByRole('button', { name: '连接官方云翻译' }); await waitFor(() => expect(connect).toBeEnabled());
  fireEvent.click(connect); await screen.findAllByText('连接已保存，待发现工具');
  expect(api.json).toHaveBeenCalledWith('/api/mcp-connections/first-party/translation', { method: 'POST', body: '{}' });
  expect(screen.queryByRole('button', { name: '更新连接或凭证' })).not.toBeInTheDocument();
  expect(screen.queryByLabelText('服务地址')).not.toBeInTheDocument(); expect(screen.queryByLabelText('访问令牌')).not.toBeInTheDocument();
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: '连接并发现工具' }));
  await screen.findByText('已发现工具，待授权翻译工具');
  expect(screen.getByRole('button', { name: '准备官方云翻译' })).toBeDisabled();
  fireEvent.click(screen.getByRole('switch', { name: '启用 vinote_translate_text' }));
  const prepare = await screen.findByRole('button', { name: '准备官方云翻译' }); await waitFor(() => expect(prepare).toBeEnabled());
  fireEvent.click(prepare);
  expect(screen.queryByLabelText('正文参数')).not.toBeInTheDocument(); expect(screen.queryByLabelText('目标语言参数')).not.toBeInTheDocument(); expect(screen.queryByLabelText('本次参数（JSON）')).not.toBeInTheDocument();
  expect(screen.getByLabelText('目标语言')).toHaveValue('en');
  fireEvent.change(screen.getByLabelText('目标语言'), { target: { value: 'zh' } });
  await waitFor(() => expect(screen.getByRole('button', { name: '预览本次翻译' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: '预览本次翻译' }));
  const confirm = await screen.findByRole('button', { name: '确认服务、正文与参数，执行工具' });
  expect(readMCPReceipts('alice')[0].arguments).toEqual({ text: '固定旧原文', target_language: 'zh', model: 'codex/gpt-6-luna' });
  expect(readMCPReceipts('alice')[0].source).toMatchObject({ source_version_id: 'older', base_revision: 5 });
  expect(api.json.mock.calls.filter(([path]) => path.endsWith('/invoke'))).toHaveLength(1);
  fireEvent.click(confirm); await screen.findByText('真实译文');
  expect(api.save).not.toHaveBeenCalled(); expect(localStorage.getItem('vinote:alice:mcp-invocations:v1')).not.toContain('official-confirmation');
});
it.each([[404, '当前服务暂不支持第一方云翻译'], [405, '当前服务暂不支持第一方云翻译'], [503, 'VINote 云模型服务尚未配置']])('truthfully handles unsupported or unconfigured official provider HTTP %s', async (status, message) => {
  api.connections.mockResolvedValue({ connections: [] }); const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation(async (path, options) => { if (path.endsWith('/first-party/translation')) throw Object.assign(new Error('server'), { status }); return implementation(path, options); });
  mount(); fireEvent.click(screen.getByRole('button', { name: '连接与授权' })); const connect = await screen.findByRole('button', { name: '连接官方云翻译' }); await waitFor(() => expect(connect).toBeEnabled()); fireEvent.click(connect);
  await screen.findAllByText(new RegExp(message)); expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false); expect(screen.queryByLabelText('访问令牌')).not.toBeInTheDocument();
});
it('queries the connection list after uncertain provision, retains a disabled official connection and never auto-posts or invokes', async () => {
  api.connections.mockResolvedValueOnce({ connections: [] }).mockResolvedValue({ connections: [{ ...managedConnection, enabled: false }] });
  const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation(async (path, options) => { if (path.endsWith('/first-party/translation')) throw new Error('connection lost'); return implementation(path, options); });
  mount(); fireEvent.click(screen.getByRole('button', { name: '连接与授权' })); const connect = await screen.findByRole('button', { name: '连接官方云翻译' }); await waitFor(() => expect(connect).toBeEnabled()); fireEvent.click(connect);
  await screen.findAllByText('连接已禁用'); expect(api.connections).toHaveBeenCalledTimes(2);
  expect(api.json.mock.calls.filter(([path]) => path.endsWith('/first-party/translation'))).toHaveLength(1);
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false); expect(screen.getByRole('switch', { name: '启用连接' })).not.toBeChecked();
});
it('leaves an unresolved provision as read-only list recovery without inventing a connection', async () => {
  api.connections.mockResolvedValue({ connections: [] }); const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation(async (path, options) => { if (path.endsWith('/first-party/translation')) throw new Error('lost'); return implementation(path, options); });
  mount(); fireEvent.click(screen.getByRole('button', { name: '连接与授权' })); const connect = await screen.findByRole('button', { name: '连接官方云翻译' }); await waitFor(() => expect(connect).toBeEnabled()); fireEvent.click(connect);
  await screen.findByText('连接结果待核验'); expect(connect).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: '查询原官方连接' })); await waitFor(() => expect(api.connections).toHaveBeenCalledTimes(3));
  expect(api.json.mock.calls.filter(([path]) => path.endsWith('/first-party/translation'))).toHaveLength(1);
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
});
it('keeps the status frame and recovery slot mounted while async provision becomes unknown; recovery remains read-only', async () => {
  let finishList!: (value: unknown) => void;
  api.connections.mockImplementationOnce(() => new Promise(resolve => { finishList = resolve })).mockResolvedValue({ connections: [] });
  const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation(async (path, options) => { if (path.endsWith('/first-party/translation')) throw new Error('lost'); return implementation(path, options); });
  mount(); fireEvent.click(screen.getByRole('button', { name: '连接与授权' }));
  const statusFrame = screen.getByRole('region', { name: '官方连接状态与帮助' });
  const actions = screen.getByLabelText('官方连接操作');
  const recoverySlot = actions.lastElementChild;
  const connect = screen.getByRole('button', { name: '连接官方云翻译' });
  expect(statusFrame).toHaveTextContent('正在读取连接状态'); expect(connect).toBeDisabled();
  expect(statusFrame).toHaveClass('min-h-12'); expect(statusFrame).not.toHaveClass('h-24', 'overflow-y-auto'); expect(recoverySlot).toHaveClass('h-10');
  await waitFor(() => expect(api.connections).toHaveBeenCalledTimes(1));
  await act(async () => finishList({ connections: [] }));
  await waitFor(() => expect(connect).toBeEnabled()); fireEvent.click(connect);
  await screen.findByText('连接结果待核验');
  expect(screen.getByRole('region', { name: '官方连接状态与帮助' })).toBe(statusFrame);
  expect(screen.getByLabelText('官方连接操作')).toBe(actions); expect(actions.lastElementChild).toBe(recoverySlot);
  expect(statusFrame.querySelector('[role="alert"]')).not.toBeNull();
  const query = screen.getByRole('button', { name: '查询原官方连接' }); expect(recoverySlot).toContainElement(query);
  expect(connect).toBeDisabled(); fireEvent.click(query);
  await waitFor(() => expect(api.connections).toHaveBeenCalledTimes(3));
  expect(api.json.mock.calls.filter(([path]) => path.endsWith('/first-party/translation'))).toHaveLength(1);
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
});
it('does not replace the action slot or imply execution when a late provision becomes a saved unverified connection', async () => {
  api.connections.mockResolvedValue({ connections: [] }); officialAPI();
  let finish!: (value: unknown) => void; const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation((path, options) => path.endsWith('/first-party/translation') ? new Promise(resolve => { finish = resolve }) : implementation(path, options));
  mount(); fireEvent.click(screen.getByRole('button', { name: '连接与授权' })); const connect = await screen.findByRole('button', { name: '连接官方云翻译' }); await waitFor(() => expect(connect).toBeEnabled());
  const actions = screen.getByLabelText('官方连接操作'); const recoverySlot = actions.lastElementChild;
  fireEvent.click(connect); await waitFor(() => expect(connect).toBeDisabled());
  await act(async () => finish({ connection: managedConnection, provider }));
  await screen.findAllByText('连接已保存，待发现工具');
  expect(screen.getByLabelText('官方连接操作')).toBe(actions); expect(actions.lastElementChild).toBe(recoverySlot);
  expect(screen.getByRole('button', { name: '查看官方连接与授权' })).toHaveClass('h-10', 'w-full');
  expect(screen.queryByRole('button', { name: '准备官方云翻译' })).not.toBeInTheDocument();
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
});
it('keeps discovery and grant proof unconfirmed while the tool read is pending or fails', async () => {
  api.connections.mockResolvedValue({ connections: [{ ...managedConnection, status: 'connected' }] });
  let fail!: (error: Error) => void; const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation((path, options) => path.endsWith('/tools') ? new Promise((_resolve, reject) => { fail = reject }) : implementation(path, options));
  mount(); fireEvent.click(screen.getByRole('button', { name: '连接与授权' })); fireEvent.click(await screen.findByRole('button', { name: /VINote 云翻译 · 第一方 MCP · 已启用/ }));
  await screen.findAllByText('正在核对工具与授权…');
  expect(screen.queryByText('已发现工具，待授权翻译工具')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '准备官方云翻译' })).not.toBeInTheDocument();
  await act(async () => fail(new Error('授权状态读取失败')));
  await screen.findAllByText('工具与授权状态尚未确认');
  expect(screen.queryByText('工具已授权，可准备调用；尚未执行翻译')).not.toBeInTheDocument();
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
});
it('does not fallback a missing historical source; explicit selection is required before preparation', async () => {
  mount('/settings/mcp?mode=translation&note=note&version=deleted');
  await screen.findByText(/指定的历史版本不可用/); expect(screen.getByLabelText('源版本')).toHaveValue('');
  await choose(); expect(screen.getByRole('button', { name: '预览本次翻译' })).toBeDisabled();
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
  fireEvent.change(screen.getByLabelText('源版本'), { target: { value: 'older' } });
  expect(screen.getByRole('button', { name: '预览本次翻译' })).toBeEnabled();
  expect(screen.queryByText(/指定的历史版本不可用/)).not.toBeInTheDocument();
});
it('rejects a changed official schema rather than guessing mappings or enabling invocation', async () => {
  api.connections.mockResolvedValue({ connections: [{ ...managedConnection, status: 'connected' }] });
  const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation(async (path, options) => path.endsWith('/tools') ? { tools: [{ ...officialTool, enabled: true, inputSchema: tool.inputSchema }] } : implementation(path, options));
  mount(); fireEvent.click(screen.getByRole('button', { name: '连接与授权' })); fireEvent.click(await screen.findByRole('button', { name: /VINote 云翻译 · 第一方 MCP · 已启用/ }));
  expect(await screen.findByText(/官方工具定义不匹配/)).toBeInTheDocument(); expect(screen.getByRole('button', { name: '准备官方云翻译' })).toBeDisabled();
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
});

it('ignores a late provision response after the owner changes, including switching back', async () => {
  api.connections.mockResolvedValue({ connections: [] });
  let finish!: (value: unknown) => void;
  const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation((path, options) => path.endsWith('/first-party/translation') ? new Promise(resolve => { finish = resolve }) : implementation(path, options));
  mount(); fireEvent.click(screen.getByRole('button', { name: '连接与授权' })); const connect = await screen.findByRole('button', { name: '连接官方云翻译' }); await waitFor(() => expect(connect).toBeEnabled()); fireEvent.click(connect);
  await act(async () => { useAuthStore.setState({ user: { id: 'bob' } } as never); });
  await act(async () => { useAuthStore.setState({ user: { id: 'alice' } } as never); });
  await act(async () => finish({ connection: managedConnection, provider }));
  expect(screen.queryByText('连接已保存，待发现工具')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '查看官方连接与授权' })).not.toBeInTheDocument();
});
it('opens the fixed official translation workflow from generic MCP management instead of an empty JSON invocation', async () => {
  officialAPI();
  api.connections.mockResolvedValue({ connections: [{ ...managedConnection, status: 'connected' }] });
  const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation(async (path, options) => path.endsWith('/tools') ? { tools: [{ ...officialTool, enabled: true }] } : implementation(path, options));
  mount('/settings/mcp?note=note&version=older');
  fireEvent.click(await screen.findByRole('button', { name: /VINote 云翻译 · 第一方 MCP · 已启用/ }));
  fireEvent.click(await screen.findByRole('button', { name: '准备官方云翻译' }));
  expect(screen.getByLabelText('目标语言')).toHaveValue('en');
  expect(screen.queryByLabelText('本次参数（JSON）')).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', { name: '预览本次翻译' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: '预览本次翻译' }));
  await screen.findByRole('button', { name: '确认服务、正文与参数，执行工具' });
  expect(readMCPReceipts('alice')[0].arguments).toEqual({ text: '固定旧原文', target_language: 'en', model: 'codex/gpt-6-luna' });
});

it('compact translation shows source, real service and model without the management wall, preserving return and choices', async () => {
  officialAPI(); api.connections.mockResolvedValue({ connections: [{ ...managedConnection, status: 'connected' }] });
  const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation(async (path, options) => path.endsWith('/tools') && !options ? { tools: [{ ...officialTool, enabled: true }] } : implementation(path, options));
  render(<MemoryRouter initialEntries={[{ pathname: '/settings/mcp', search: '?mode=translation&note=note&version=older', state: { returnTo: '/workspace/note?version=older#source' } }]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><MCPSettings /></MemoryRouter>);
  await waitFor(() => expect(screen.getByLabelText('翻译模型')).toHaveValue('codex/gpt-6-luna'));
  expect(screen.getByRole('heading', { level: 1, name: '全文翻译' })).toBeInTheDocument();
  expect(within(screen.getByLabelText('翻译来源')).getByText('原笔记')).toBeInTheDocument();
  expect(screen.getByLabelText('源版本')).toHaveValue('older');
  expect(screen.getByRole('link', { name: '返回内容详情' })).toHaveAttribute('href', '/workspace/note?version=older#source');
  expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  expect(screen.queryByText('工具运行记录')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('服务地址')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('本次参数（JSON）')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '准备官方云翻译' })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('目标语言'), { target: { value: 'zh' } });
  fireEvent.change(screen.getByLabelText('翻译模型'), { target: { value: 'deepseek-v4.1-flash' } });
  fireEvent.click(screen.getByRole('button', { name: '连接与授权' }));
  expect(screen.getAllByRole('dialog')).toHaveLength(1);
  expect(screen.getByRole('switch', { name: '启用 vinote_translate_text' })).toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: '返回全文翻译' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByLabelText('目标语言')).toHaveValue('zh');
  expect(screen.getByLabelText('翻译模型')).toHaveValue('deepseek-v4.1-flash');
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: '预览本次翻译' }));
  await screen.findByRole('button', { name: '确认服务、正文与参数，执行工具' });
  expect(screen.getAllByRole('dialog')).toHaveLength(1);
  expect(screen.queryByRole('dialog', { name: '连接与授权' })).not.toBeInTheDocument();
  expect(readMCPReceipts('alice')[0]).toMatchObject({ source: { source_version_id: 'older', base_revision: 5 }, arguments: { text: '固定旧原文', target_language: 'zh', model: 'deepseek-v4.1-flash' } });
  const calls = api.json.mock.calls.filter(([path]) => path.endsWith('/invoke'));
  expect(calls).toHaveLength(1); expect(JSON.parse(calls[0][1].body).confirmed).toBeUndefined();
  fireEvent.click(screen.getByRole('button', { name: '关闭预览（保留原请求）' }));
  expect(screen.getByLabelText('翻译模型')).toHaveValue('deepseek-v4.1-flash');
  expect(screen.getByRole('button', { name: '预览本次翻译' })).toBeDisabled();
  expect(api.save).not.toHaveBeenCalled();
});
it('closed unknown preview keeps new calls disabled and recovers only by original request GET', async () => {
  writeMCPReceipt('alice', { ...receipt, status: 'unknown' });
  mount(); await screen.findByRole('button', { name: /actual_tool · 查询原请求/ });
  expect(screen.getByRole('button', { name: '预览本次翻译' })).toBeDisabled();
  const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation(async (path, options) => { if (path.includes('/by-request/')) throw new Error('原请求未查到（404）'); return implementation(path, options) });
  fireEvent.click(screen.getByRole('button', { name: /actual_tool · 查询原请求/ }));
  await screen.findByText('原请求未查到（404）');
  fireEvent.click(screen.getByRole('button', { name: '关闭预览（保留原请求）' }));
  expect(screen.getByRole('button', { name: '预览本次翻译' })).toBeDisabled();
  expect(readMCPReceipts('alice')[0]).toMatchObject({ requestId: 'original-request', status: 'unknown', source: receipt.source });
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
});

it('distinguishes equal-title equal-time source records by real kind and snapshot revision without deduplication or changing requests', async () => {
  const created_at = '2026-10-12T06:38:33Z';
  api.detail.mockResolvedValue({ ...note, versions: [
    { id: '__vinote:current:5', title: '同一标题', content: '当前正文', kind: 'edit', created_at },
    { id: 'generated-original', title: '同一标题', content: '生成原文', kind: 'generated', created_at },
    { id: 'edited-original', title: '同一标题', content: '编辑原文', kind: 'edit', created_at },
  ] });
  mount('/settings/mcp?mode=translation&note=note&version=edited-original');
  const source = await screen.findByLabelText('源版本');
  expect(within(source).getAllByRole('option')).toHaveLength(4);
  expect(within(source).getByRole('option', { name: /自动正文快照 · 修订 5/ })).toHaveValue('__vinote:current:5');
  expect(within(source).getByRole('option', { name: /生成版本 · 同一标题/ })).toHaveValue('generated-original');
  expect(within(source).getByRole('option', { name: /正文编辑/ })).toHaveValue('edited-original');
  expect(source).toHaveValue('edited-original');
  expect(within(source).queryByRole('option', { name: /版本1|版本 1/ })).not.toBeInTheDocument();
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
  await choose();
  fireEvent.click(screen.getByRole('button', { name: '预览本次翻译' }));
  await screen.findByRole('button', { name: '确认服务、正文与参数，执行工具' });
  expect(readMCPReceipts('alice')[0]).toMatchObject({ source: { source_version_id: 'edited-original', base_revision: 5, content: '编辑原文' }, arguments: { text_input: '编辑原文', destination: 'zh' } });
  const calls = api.json.mock.calls.filter(([path]) => path.endsWith('/invoke'));
  expect(calls).toHaveLength(1);
  expect(JSON.parse(calls[0][1].body).confirmed).toBeUndefined();
  expect(api.save).not.toHaveBeenCalled();
});
it('keeps imported and legacy source semantics honest when time or revision is absent', async () => {
  api.detail.mockResolvedValue({ ...note, versions: [
    { id: 'imported', title: '同一标题', content: '导入原文', kind: 'imported', created_at: '' },
    { id: 'legacy', title: '同一标题', content: '旧原文', created_at: 'invalid' },
    { id: '__vinote:saved:3', title: '同一标题', content: '写入前原文', kind: 'edit', created_at: '' },
  ] });
  mount('/settings/mcp?mode=translation&note=note&version=imported');
  const source = await screen.findByLabelText('源版本');
  expect(within(source).getByRole('option', { name: '导入记录 · 同一标题 · 时间未记录' })).toHaveValue('imported');
  expect(within(source).getByRole('option', { name: '其他保存记录 · 同一标题 · 时间未记录' })).toHaveValue('legacy');
  expect(within(source).getByRole('option', { name: '写入前正文快照 · 修订 3 · 时间未记录' })).toHaveValue('__vinote:saved:3');
  expect(within(source).queryByRole('option', { name: /修订 5|版本1|版本 1/ })).not.toBeInTheDocument();
  expect(source).toHaveValue('imported');
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
});

it('awaiting confirmation explains execution has not started and original-request verification does not invoke again', async () => {
  mount(); await choose();
  fireEvent.click(screen.getByRole('button', { name: '预览本次翻译' }));
  await screen.findByRole('button', { name: '确认服务、正文与参数，执行工具' });
  const explanation = screen.getByLabelText('翻译执行说明');
  expect(within(explanation).getByRole('heading', { name: '等待执行确认' })).toBeInTheDocument();
  expect(explanation).toHaveTextContent('确认后才会执行翻译');
  expect(explanation).not.toHaveTextContent('尚无已确认译文，请查询原请求');
  expect(screen.queryByRole('heading', { name: '译文预览' })).not.toBeInTheDocument();
  expect(screen.queryByLabelText('MCP 译文预览')).not.toBeInTheDocument();
  const original = readMCPReceipts('alice')[0];
  const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation(async (path, options) => path.includes('/by-request/') ? { ...run, requestId: original.requestId, arguments: original.arguments, status: 'awaiting_confirmation', result: null, confirmationToken: 'server-confirmation' } : implementation(path, options));
  fireEvent.click(screen.getByRole('button', { name: '核验原请求（不会执行）' }));
  await waitFor(() => expect(api.json).toHaveBeenCalledWith(`/api/mcp-connections/runs/by-request/${original.requestId}`));
  await waitFor(() => expect(screen.getByRole('button', { name: '核验原请求（不会执行）' })).toBeEnabled());
  expect(screen.getByLabelText('翻译执行说明')).toHaveTextContent('确认后才会执行翻译');
  const posts = api.json.mock.calls.filter(([path]) => path.endsWith('/invoke'));
  expect(posts).toHaveLength(1);
  expect(JSON.parse(posts[0][1].body).confirmed).toBeUndefined();
  expect(readMCPReceipts('alice')[0].requestId).toBe(original.requestId);
  expect(api.save).not.toHaveBeenCalled();
});

it('reopening a cancelled request shows only original-request verification until GET acknowledges its state', async () => {
  writeMCPReceipt('alice', receipt);
  let finish!: (value: unknown) => void;
  const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation((path, options) => path.includes('/by-request/') ? new Promise(resolve => { finish = resolve }) : implementation(path, options));
  mount(); fireEvent.click(await screen.findByRole('button', { name: /actual_tool · 查询原请求/ }));
  const verification = await screen.findByLabelText('原请求核验');
  expect(within(verification).getByRole('heading', { name: '正在核验原请求' })).toBeInTheDocument();
  expect(verification).toHaveTextContent('读取完成前不推断执行、取消或译文状态');
  expect(screen.getByRole('button', { name: '正在核验原请求' })).toBeDisabled();
  expect(screen.queryByText('尚无已确认译文，请查询原请求。')).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: '译文预览' })).not.toBeInTheDocument();
  expect(screen.queryByText('本次请求已取消；原文保留。')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '确认服务、正文与参数，执行工具' })).not.toBeInTheDocument();
  await act(async () => finish({ ...run, status: 'cancelled', result: null }));
  await screen.findByText('本次请求已取消；原文保留。');
  expect(screen.queryByLabelText('原请求核验')).not.toBeInTheDocument();
  expect(readMCPReceipts('alice')[0]).toMatchObject({ requestId: 'original-request', status: 'cancelled' });
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
});
it('refreshing an already-read run retains its confirmed state and result while the next GET is pending', async () => {
  writeMCPReceipt('alice', receipt); mount();
  fireEvent.click(await screen.findByRole('button', { name: /actual_tool · 查询原请求/ }));
  await screen.findByText('真实译文');
  let finish!: (value: unknown) => void;
  const implementation = api.json.getMockImplementation()!;
  api.json.mockImplementation((path, options) => path.includes('/by-request/') ? new Promise(resolve => { finish = resolve }) : implementation(path, options));
  fireEvent.click(screen.getByRole('button', { name: '查询原请求状态' }));
  expect(screen.getByRole('button', { name: '查询原请求状态' })).toBeDisabled();
  expect(screen.getByText('真实译文')).toBeInTheDocument();
  expect(screen.getByText('已完成')).toBeInTheDocument();
  expect(screen.queryByLabelText('原请求核验')).not.toBeInTheDocument();
  expect(screen.queryByText('尚无已确认译文，请查询原请求。')).not.toBeInTheDocument();
  await act(async () => finish(run));
  expect(screen.getByText('真实译文')).toBeInTheDocument();
  expect(api.json.mock.calls.some(([path]) => path.endsWith('/invoke'))).toBe(false);
});
