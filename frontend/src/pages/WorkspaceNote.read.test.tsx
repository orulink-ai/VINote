import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Link, MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import type { WorkspaceNote as Note } from '@/lib/workspace';
import { PageReturn } from '@/components/Layout/PageReturn';

const api = vi.hoisted(() => ({ json: vi.fn(), readCache: vi.fn(), writeCache: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiJson: api.json, ApiError: class extends Error {} }));
vi.mock('@/lib/workspaceCache', () => ({ readWorkspaceCache: api.readCache, writeWorkspaceCache: api.writeCache }));
vi.mock('@/stores/authStore', async () => {
  const { create } = await import('zustand');
  return { useAuthStore: create(() => ({ user: { id: 'alice' } })) };
});
vi.mock('@/components/Markdown/MarkdownContent', () => ({ MarkdownContent: ({ content }: { content: string }) => <p>{content}</p> }));
vi.mock('@/components/Notes/VersionCompare', () => ({ VersionCompare: ({ left, leftLabel }: { left: string; leftLabel: string }) => <section aria-label="比较源版本"><h3>{leftLabel}</h3><p>{left}</p></section> }));
vi.mock('@/components/Notes/ExportPanel', () => ({ ExportPanel: ({ title, content, version }: { title: string; content: string; version: string }) => <button data-export-title={title} data-export-content={content} data-export-version={version}>导出 Markdown</button> }));
vi.mock('@/components/Notes/FeishuDelivery', () => ({ FeishuDelivery: ({ disabled }: { disabled: boolean }) => <button disabled={disabled}>发布到飞书</button> }));
vi.mock('@/components/Notes/MeetingConversation', () => ({ MeetingConversation: () => null }));

import { WorkspaceNote } from './WorkspaceNote';
import { useWorkspaceStore } from '@/stores/workspaceStore';
import { useAuthStore } from '@/stores/authStore';

const key = 'desktop-48b84237-2003-5e8c-97aa-59f7e989a466';
function note(id = key, body = '精确网络正文'): Note {
  return { key: id, title: 'PDF 笔记', content: body, revision: 4, source_type: 'document', source_device: 'desktop',
    metadata: {}, transcript: null, versions: [{ id: 'v1', title: '第一版', content: '历史正文', created_at: '2026-10-12T00:00:00Z' }],
    next_versions_offset: null, version_count: 1, deleted: false, archived: false, updated_at: '2026-10-12T00:01:00Z', created_at: '2026-10-12T00:00:00Z' };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (cause: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function ContextReturn() {
  const location = useLocation();
  return <><output aria-label="目标地址">{location.pathname + location.search + location.hash}</output><PageReturn to={location.state?.returnTo || `/workspace/${key}`} label="返回内容详情" /></>;
}
function actions() {
  const trigger = screen.getByRole('button', { name: '内容操作' });
  if (!trigger.closest('details')?.open) fireEvent.click(trigger);
}
function currentVersion(value = note()): Note {
  return { ...value, versions: [...value.versions, { id: 'current', title: value.title, content: value.content, created_at: value.updated_at }] };
}
function mount(path = `/workspace/${key}`, state?: object) {
  return render(<MemoryRouter initialEntries={[{ pathname: path.split('?')[0], search: path.includes('?') ? `?${path.split('?')[1]}` : '', state }]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <Link to="/workspace/second">切换精确链接</Link>
    <Routes>
      <Route path="/workspace/:key" element={<WorkspaceNote />} />
      <Route path="/notes" element={<p>笔记列表</p>} />
      <Route path="/meetings" element={<p>原会议列表</p>} />
      <Route path="/settings/mcp" element={<ContextReturn />} />
      <Route path="/connections" element={<ContextReturn />} />
      <Route path="/files" element={<ContextReturn />} />
    </Routes>
  </MemoryRouter>);
}
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  useAuthStore.setState({ user: { id: 'alice' } });
  useWorkspaceStore.getState().reset();
  useWorkspaceStore.setState({ owner: 'alice', ready: true });
  api.json.mockResolvedValue(note());
  api.readCache.mockResolvedValue(null);
  api.writeCache.mockResolvedValue(undefined);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('allows known unsent paused content to enter device trash through one confirmation without changing its original until confirmed', async () => {
  const original = note();
  const operation = { key, locallyQueued: true, body: { base_revision: 4, operation_id: 'never-dispatched', title: original.title, content: '本机未发送正文', source_type: original.source_type, source_device: original.source_device } };
  useWorkspaceStore.setState({ details: { [key]: original }, itemPolicies: { [key]: 'local' }, pending: [operation] });
  const remove = vi.spyOn(useWorkspaceStore.getState(), 'changeDeleted').mockResolvedValue({ ...original, deleted: true });
  mount(); await screen.findByText('本机未发送正文'); actions();
  const entry = screen.getByRole('button', { name: '移入回收站' });
  expect(entry).toBeEnabled(); fireEvent.click(entry);
  const confirmation = screen.getByRole('alertdialog');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(confirmation).toHaveTextContent('不发送云端删除请求');
  expect(confirmation).toHaveTextContent('原始文件与已发布飞书文档保留');
  fireEvent.click(within(confirmation).getByRole('button', { name: '保留' }));
  expect(remove).not.toHaveBeenCalled();
  expect(useWorkspaceStore.getState().pending[0]).toBe(operation);
  actions(); fireEvent.click(screen.getByRole('button', { name: '移入回收站' }));
  await act(async () => fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '移入回收站' })));
  expect(remove).toHaveBeenCalledExactlyOnceWith(key, true);
  expect(screen.getByText('笔记列表')).toBeInTheDocument();
  expect(api.json).not.toHaveBeenCalled();
});

it('does not allow a paused unknown remote result to be replaced with a deletion', async () => {
  const original = note();
  useWorkspaceStore.setState({ details: { [key]: original }, itemPolicies: { [key]: 'local' }, pending: [{ key, locallyQueued: false, body: { base_revision: 4, operation_id: 'original-unknown', title: original.title, content: '原请求正文', source_type: original.source_type, source_device: original.source_device } }] });
  const remove = vi.spyOn(useWorkspaceStore.getState(), 'changeDeleted');
  mount(); await screen.findByText(original.content); actions();
  expect(screen.getByRole('button', { name: '移入回收站' })).toBeDisabled();
  expect(screen.getByRole('link', { name: '处理保存与冲突' })).toBeInTheDocument();
  expect(remove).not.toHaveBeenCalled();
  expect(useWorkspaceStore.getState().pending[0].body.operation_id).toBe('original-unknown');
});

it('keeps sync disabled while paused content is in device trash so restoring precedes enabling', async () => {
  useWorkspaceStore.setState({ details: { [key]: { ...note(), deleted: true } }, itemPolicies: { [key]: 'local' } });
  mount(); await screen.findByText('精确网络正文'); actions();
  expect(screen.getByRole('switch', { name: '同步到其他设备' })).toBeDisabled();
  expect(screen.getByText(/此设备的内容已进入回收站，云端或其他设备已有内容保留/)).toBeInTheDocument();
  expect(api.json).not.toHaveBeenCalled();
});

it('connects a newly saved store-local detail to real device trash without any remote request', async () => {
  const localKey = 'text-new-local';
  const saved = await useWorkspaceStore.getState().save(localKey, {
    base_revision: 0, operation_id: 'local-first-save', title: '本机新笔记', content: '未上传的完整正文', source_type: 'text', source_device: 'desktop',
  });
  expect(saved).toMatchObject({ key: localKey, revision: 0 });
  const originalRequest = useWorkspaceStore.getState().pending[0];
  mount(`/workspace/${localKey}`); await screen.findByText('未上传的完整正文'); actions();
  fireEvent.click(screen.getByRole('button', { name: '移入回收站' }));
  expect(screen.getByRole('alertdialog')).toHaveTextContent('此设备的回收站');
  await act(async () => fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '移入回收站' })));
  expect(screen.getByText('笔记列表')).toBeInTheDocument();
  expect(useWorkspaceStore.getState().details[localKey]).toMatchObject({ content: '未上传的完整正文', deleted: true });
  expect(useWorkspaceStore.getState().pending[0]).toBe(originalRequest);
  expect(api.json).not.toHaveBeenCalled();
});

it('saves paused edits locally, reopens the local projection and keeps its original acknowledged comparison baseline', async () => {
  const original = note();
  useWorkspaceStore.setState({ details: { [key]: original }, itemPolicies: { [key]: 'local' } });
  const first = mount();
  await screen.findByText('精确网络正文');
  fireEvent.click(screen.getByRole('button', { name: '编辑' }));
  fireEvent.change(screen.getByRole('textbox', { name: '笔记正文' }), { target: { value: '本机保留的新正文' } });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '保存', exact: true })));
  expect(screen.getByText('本机保留的新正文', { selector: 'p' })).toBeInTheDocument();
  expect(within(screen.getByRole('banner')).getByText('已保存在此设备 · 此设备同步已暂停', { selector: 'span' })).toBeInTheDocument();
  expect(useWorkspaceStore.getState().details[key].content).toBe('本机保留的新正文');
  expect(useWorkspaceStore.getState().pending[0].baseline).toEqual(original);
  expect(useWorkspaceStore.getState().pending[0]).toMatchObject({ key, locallyQueued: true, body: { base_revision: 4, content: '本机保留的新正文' } });
  first.unmount(); mount();
  await screen.findByText('本机保留的新正文', { selector: 'p' });
  fireEvent.click(screen.getByRole('button', { name: '编辑' }));
  fireEvent.change(screen.getByRole('textbox', { name: '笔记正文' }), { target: { value: '再次本机编辑' } });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '保存', exact: true })));
  expect(useWorkspaceStore.getState().pending).toHaveLength(1);
  expect(useWorkspaceStore.getState().pending[0].body).toMatchObject({ base_revision: 4, content: '再次本机编辑' });
  expect(useWorkspaceStore.getState().details[key].content).toBe('再次本机编辑');
  expect(useWorkspaceStore.getState().pending[0].baseline).toEqual(original);
  expect(api.json.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it('distinguishes current/saved revision snapshots and real edits without changing history IDs or selection', async () => {
  const time = '2026-10-12T03:29:49Z';
  const versions: Note['versions'] = [
    { id: '__vinote:current:3', title: '同一PDF标题', content: '修订3正文快照', created_at: time, kind: 'edit' },
    { id: '__vinote:saved:3', title: '同一PDF标题', content: '修订3保存记录', created_at: time, kind: 'edit' },
    { id: 'edit-revision', title: '同一PDF标题 · V1 编辑', content: '真实编辑正文', created_at: time, kind: 'edit' },
  ];
  const original = { ...note(), versions, version_count: 3, metadata: { default_version_id: '__vinote:saved:3' } };
  api.json.mockResolvedValue(original); mount(); await screen.findByText('精确网络正文');
  actions(); fireEvent.click(screen.getByRole('button', { name: '来源与版本' }));
  const picker = screen.getByLabelText(/已保存版本/);
  const options = within(picker).getAllByRole('option');
  expect(options.map(option => option.getAttribute('value'))).toEqual(['', ...versions.map(version => version.id)]);
  expect(options[1]).toHaveTextContent(`自动正文快照 · ${new Date(time).toLocaleString()}`);
  expect(options[2]).toHaveTextContent(`写入前正文快照 · ${new Date(time).toLocaleString()}`);
  expect(options[3]).toHaveTextContent(`正文编辑 · ${new Date(time).toLocaleString()}`);
  expect(options[3]).not.toHaveTextContent('V1');
  for (const version of versions) {
    fireEvent.change(picker, { target: { value: version.id } });
    expect(picker).toHaveValue(version.id);
    expect(screen.getByText(version.content)).toBeInTheDocument();
    // The source Sheet correctly hides the background from accessibility queries;
    // inspect the export wiring without treating it as an available modal action.
    expect(screen.getByText('导出 Markdown', { selector: 'button' })).toHaveAttribute('data-export-version', options[versions.indexOf(version) + 1].textContent?.replace(' · 默认展示', ''));
  }
  fireEvent.click(screen.getByRole('button', { name: '比较当前与所选版本' }));
  expect(within(screen.getByRole('dialog')).getByRole('heading', { name: `正文编辑 · ${new Date(time).toLocaleString()}` })).toBeInTheDocument();
  expect(useWorkspaceStore.getState().details[key].versions).toEqual(versions);
  expect(useWorkspaceStore.getState().details[key].metadata.default_version_id).toBe('__vinote:saved:3');
  expect(api.json.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it('labels missing or invalid version times honestly and keeps the original-file target and return context', async () => {
  api.json.mockResolvedValue({ ...note(), versions: [
    { ...note().versions[0], id: '__vinote:saved:3', created_at: '', kind: 'edit' },
    { ...note().versions[0], id: 'edit-revision', created_at: 'invalid', kind: 'edit' },
  ] });
  useWorkspaceStore.setState({ mappings: { 'local-original': { key } } } as never);
  mount(); await screen.findByText('精确网络正文'); actions(); fireEvent.click(screen.getByRole('button', { name: '来源与版本' }));
  expect(screen.getByRole('option', { name: '写入前正文快照 · 时间未记录' })).toHaveValue('__vinote:saved:3');
  expect(screen.getByRole('option', { name: '正文编辑 · 时间未记录' })).toHaveValue('edit-revision');
  const sourceLink = screen.getByRole('link', { name: '查看原始资料' });
  const sourceUrl = new URL(sourceLink.getAttribute('href')!, 'https://vinote.invalid');
  expect(sourceUrl.pathname).toBe('/files');
  expect(sourceUrl.searchParams.get('note')).toBe('local-original');
  expect(sourceUrl.searchParams.has('file')).toBe(false);
  expect(sourceUrl.searchParams.get('returnTo')).toContain(`/workspace/${key}`);
  expect(screen.queryByText('打开本机原始资料')).not.toBeInTheDocument();
  expect(api.json.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it('closes source Sheet before the file-library handoff and retains the exact selected workspace version and parent', async () => {
  api.json.mockResolvedValue(note());
  useWorkspaceStore.setState({ mappings: { 'real-local-id': { key } } } as never);
  const parent = '/notes?project=source&archived=1';
  mount(`/workspace/${key}?returnTo=${encodeURIComponent(parent)}`);
  await screen.findByText('精确网络正文'); actions(); fireEvent.click(screen.getByRole('button', { name: '来源与版本' }));
  fireEvent.change(screen.getByLabelText(/已保存版本/), { target: { value: 'v1' } });
  const link = screen.getByRole('link', { name: '查看原始资料' });
  const url = new URL(link.getAttribute('href')!, 'https://vinote.invalid');
  expect(url.pathname).toBe('/files'); expect(url.searchParams.get('note')).toBe('real-local-id');
  const context = new URL(url.searchParams.get('returnTo')!, 'https://vinote.invalid');
  expect(context.pathname).toBe(`/workspace/${key}`); expect(context.searchParams.get('version')).toBe('v1');
  expect(context.searchParams.get('returnTo')).toBe(parent);
  fireEvent.click(link); expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: '返回内容详情' }));
  await screen.findByText('历史正文');
  expect(api.json.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it('groups only genuine generated versions and retains imported, unclassified and equal-content records with exact default identity', async () => {
  const value = note();
  const versions: Note['versions'] = [
    { ...value.versions[0], id: '__vinote:current:3', content: value.content, kind: 'edit' },
    { ...value.versions[0], id: 'generated-b', kind: 'generated' },
    { ...value.versions[0], id: 'imported', content: value.content, kind: 'imported' },
    { ...value.versions[0], id: 'generated-a', kind: 'generated' },
    { ...value.versions[0], id: 'translated-edit', title: 'V1 编辑', content: value.content, kind: 'edit' },
    { ...value.versions[0], id: 'unclassified', title: 'V1 生成', content: value.content, kind: undefined },
  ];
  api.json.mockResolvedValue({ ...value, versions, metadata: { default_version_id: 'imported' } });
  mount(); await screen.findByText(value.content); actions(); fireEvent.click(screen.getByRole('button', { name: '来源与版本' }));
  const picker = screen.getByLabelText(/已保存版本/);
  const ids = (label: string) => within(within(picker).getByRole('group', { name: label })).getAllByRole('option').map(option => option.getAttribute('value'));
  expect(ids('当前正文')).toEqual(['']);
  expect(ids('生成版本')).toEqual(['generated-b', 'generated-a']);
  expect(ids('编辑、保存与其他记录')).toEqual(['__vinote:current:3', 'imported', 'translated-edit', 'unclassified']);
  expect(within(picker).getAllByRole('option')).toHaveLength(versions.length + 1);
  expect(within(picker).getAllByRole('option').filter(option => option.textContent?.includes('默认展示')).map(option => option.getAttribute('value'))).toEqual(['imported']);
  expect(screen.queryByText('正文与当前正文完全相同，仍是独立记录。')).not.toBeInTheDocument();
  fireEvent.change(picker, { target: { value: 'imported' } });
  expect(screen.getByText('这是导入时保存的正文记录，不是正文编辑或生成记录。')).toBeInTheDocument();
  expect(screen.getByText('此记录为默认展示。')).toBeInTheDocument();
  expect(screen.getByText('正文与当前正文完全相同，仍是独立记录。')).toBeInTheDocument();
  fireEvent.change(picker, { target: { value: '__vinote:current:3' } });
  expect(screen.getByText(/不代表此刻的最新正文/)).toBeInTheDocument();
  expect(screen.queryByText('此记录为默认展示。')).not.toBeInTheDocument();
  fireEvent.change(picker, { target: { value: 'translated-edit' } });
  expect(screen.getByText('这是正文编辑保存的记录；时间相同不代表它与快照是同一记录。')).toBeInTheDocument();
  fireEvent.change(picker, { target: { value: 'unclassified' } });
  expect(screen.getByText('这是已保存记录，未记录具体类型。')).toBeInTheDocument();
  fireEvent.change(picker, { target: { value: '' } });
  expect(screen.getByText('当前已保存正文。')).toBeInTheDocument();
  expect(screen.queryByText('此记录为默认展示。')).not.toBeInTheDocument();
  expect(useWorkspaceStore.getState().details[key].versions).toEqual(versions);
  expect(useWorkspaceStore.getState().details[key].metadata.default_version_id).toBe('imported');
  expect(api.json.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it('does not invent missing default records or generation groups and keeps dirty drafts distinct from saved content', async () => {
  const value = { ...note(), metadata: { default_version_id: 'not-loaded' } };
  api.json.mockResolvedValue(value);
  localStorage.setItem(`vinote:draft:alice:workspace:${key}`, JSON.stringify({ title: value.title, content: '尚未保存草稿', baseRevision: value.revision }));
  mount(); await screen.findByDisplayValue('尚未保存草稿'); actions(); fireEvent.click(screen.getByRole('button', { name: '来源与版本' }));
  const picker = screen.getByLabelText(/已保存版本/);
  expect(picker).toBeDisabled();
  expect(within(picker).queryByRole('group', { name: '生成版本' })).not.toBeInTheDocument();
  expect(screen.getByText('默认展示记录尚未载入。')).toBeInTheDocument();
  expect(screen.getByText('另有本机未保存草稿；草稿尚未成为已保存正文。')).toBeInTheDocument();
  expect(within(picker).getAllByRole('option').some(option => option.textContent?.includes('默认展示'))).toBe(false);
  expect(api.json.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it('cold MCP return reads the exact note over the network without listing or syncing', async () => {
  const pending = deferred<Note>(); api.json.mockReturnValue(pending.promise);
  mount(`/settings/mcp?note=${key}`);
  fireEvent.click(screen.getByRole('link', { name: '返回内容详情' }));
  expect(screen.getByRole('status', { name: '正在读取内容及版本…' })).toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  await act(async () => pending.resolve(note()));
  await screen.findByText('精确网络正文');
  expect(api.json.mock.calls.map(([path]) => path)).toEqual([`/api/workspace/notes/${key}?versions_offset=0&versions_limit=50`]);
});

it('does not show an uncached alert while an existing summary/detail awaits its baseline', async () => {
  const pending = deferred<Note>(); api.json.mockReturnValue(pending.promise);
  useWorkspaceStore.setState({ details: { [key]: note(key, '缓存正文') } });
  mount(); await screen.findByText('缓存正文');
  expect(screen.queryByText(/尚未缓存/)).not.toBeInTheDocument();
  await act(async () => pending.resolve(note())); await screen.findByText('精确网络正文');
});

it('a network failure keeps an explicit retry and contextual return, then rereads the same key', async () => {
  api.json.mockRejectedValueOnce(new Error('网络暂不可用')).mockResolvedValue(note());
  mount(`/workspace/${key}?returnTo=${encodeURIComponent('/meetings?filter=old')}`);
  await screen.findByText('网络暂不可用');
  expect(screen.getByRole('link', { name: '返回会议' })).toHaveAttribute('href', '/meetings?filter=old');
  fireEvent.click(screen.getByRole('button', { name: '重新读取' }));
  await screen.findByText('精确网络正文');
  expect(api.json).toHaveBeenCalledTimes(2);
  expect(api.json.mock.calls.every(([path, options]) => path.includes(`/notes/${key}?`) && !options?.method)).toBe(true);
});

it('a missing or forbidden deep link shows the server failure and allows returning', async () => {
  api.json.mockRejectedValue(new Error('内容不存在或无权访问'));
  mount(); await screen.findByText('内容不存在或无权访问');
  fireEvent.click(screen.getByRole('link', { name: '返回笔记' }));
  await screen.findByText('笔记列表'); expect(api.json).toHaveBeenCalledTimes(1);
});

it('fetches every history page by exact identity, never by title', async () => {
  api.json.mockResolvedValueOnce({ ...note(), next_versions_offset: 50 })
    .mockResolvedValueOnce({ ...note(), versions: [{ ...note().versions[0], id: 'v2', title: '第二版' }] });
  mount(); await screen.findByText('精确网络正文');
  expect(useWorkspaceStore.getState().details[key].versions.map(v => v.id)).toEqual(['v1', 'v2']);
  expect(api.json.mock.calls.map(([path]) => path)).toEqual([0, 50].map(offset => `/api/workspace/notes/${key}?versions_offset=${offset}&versions_limit=50`));
});

it('retains the readable exact GET result if writing the offline cache fails', async () => {
  api.writeCache.mockRejectedValue(new Error('本机缓存写入失败'));
  mount(); await screen.findByText('精确网络正文'); await screen.findByText('本机缓存写入失败');
  expect(screen.queryByText(/尚未缓存/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '重新读取' })).toBeEnabled();
});

it('retains the cached content and protected draft while offline', async () => {
  useWorkspaceStore.setState({ details: { [key]: note(key, '缓存正文') } });
  localStorage.setItem(`vinote:draft:alice:workspace:${key}`, JSON.stringify({ title: 'PDF 笔记', content: '未提交草稿', baseRevision: 3 }));
  api.json.mockRejectedValue(new Error('离线，读取失败'));
  mount(); await screen.findByDisplayValue('未提交草稿'); await screen.findByText('离线，读取失败');
  expect(JSON.parse(localStorage.getItem(`vinote:draft:alice:workspace:${key}`)!).content).toBe('未提交草稿');
  expect(api.json).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: '重新读取' }));
  await waitFor(() => expect(api.json).toHaveBeenCalledTimes(2));
  expect(api.json.mock.calls.every(([, options]) => !options?.method)).toBe(true);
  expect(screen.getByDisplayValue('未提交草稿')).toBeInTheDocument();
});

it('does not let an old route response replace the new route content', async () => {
  const old = deferred<Note>(); api.json.mockImplementation(path => path.includes(`/notes/${key}?`) ? old.promise : Promise.resolve(note('second', '第二条正文')));
  mount(); fireEvent.click(screen.getByRole('link', { name: '切换精确链接' }));
  await screen.findByText('第二条正文');
  await act(async () => old.resolve(note(key, '迟到的旧正文')));
  expect(screen.queryByText('迟到的旧正文')).not.toBeInTheDocument();
  expect(screen.getByText('第二条正文')).toBeInTheDocument();
});

it('blocks old-owner responses and cache when the account changes', async () => {
  const old = deferred<Note>(); api.json.mockReturnValueOnce(old.promise).mockResolvedValue(note(key, '新账号正文'));
  mount();
  act(() => { useAuthStore.setState({ user: { id: 'bob' } }); useWorkspaceStore.getState().reset(); useWorkspaceStore.setState({ owner: 'bob', ready: true }); });
  await screen.findByText('新账号正文');
  await act(async () => old.resolve(note(key, '旧账号私有正文')));
  expect(screen.queryByText('旧账号私有正文')).not.toBeInTheDocument();
  expect(screen.getByText('新账号正文')).toBeInTheDocument();
});

it('offers initialization recovery rather than an endless spinner when local cache initialization fails', async () => {
  useWorkspaceStore.setState({ ready: false, error: '无法保存离线资料' });
  mount(); await screen.findByText('无法保存离线资料');
  expect(api.json).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '重新读取' }));
  await screen.findByText('精确网络正文'); expect(api.readCache).toHaveBeenCalledWith('alice');
});

it('the tools link preserves the content parent across its return URL', async () => {
  api.json.mockResolvedValue(currentVersion());
  mount(`/workspace/${key}`, { returnTo: '/meetings?filter=old' });
  await screen.findByText('精确网络正文');
  actions();
  expect(screen.getByRole('link', { name: '全文翻译 · MCP' })).toHaveAttribute('href', `/settings/mcp?mode=translation&note=${key}&version=current`);
  expect(screen.getByRole('button', { name: '返回会议' })).toBeInTheDocument();
  expect(api.json).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('link', { name: '全文翻译 · MCP' }));
  expect(screen.getByRole('link', { name: '返回内容详情' })).toHaveAttribute('href', `/workspace/${key}?returnTo=${encodeURIComponent('/meetings?filter=old')}`);
  fireEvent.click(screen.getByRole('link', { name: '返回内容详情' }));
  await screen.findByText('精确网络正文');
  fireEvent.click(screen.getByRole('button', { name: '返回会议' }));
  await screen.findByText('原会议列表');
});

it('waits for owner cache initialization before loading a cold deep link', async () => {
  useWorkspaceStore.setState({ ready: false });
  mount(); expect(screen.getByRole('status')).toBeInTheDocument();
  expect(api.json).not.toHaveBeenCalled();
  act(() => useWorkspaceStore.setState({ ready: true }));
  await screen.findByText('精确网络正文'); expect(api.json).toHaveBeenCalledTimes(1);
});

it('a concurrent history revision change fails explicitly and retry loads a consistent history', async () => {
  api.json.mockResolvedValueOnce({ ...note(), next_versions_offset: 50 })
    .mockResolvedValueOnce({ ...note(), revision: 5 })
    .mockResolvedValueOnce(note());
  mount(); await screen.findByText('内容已更新，请重新读取全部版本');
  expect(useWorkspaceStore.getState().details[key]).toBeUndefined();
  fireEvent.click(screen.getByRole('button', { name: '重新读取' }));
  await screen.findByText('精确网络正文');
  expect(useWorkspaceStore.getState().details[key].versions.map(v => v.id)).toEqual(['v1']);
});


it('has two primary actions and one discoverable secondary container, preserving classification and deletion', async () => {
  api.json.mockResolvedValue(currentVersion()); mount(); await screen.findByText('精确网络正文');
  const primary = screen.getByRole('group', { name: '主要内容操作' });
  expect(within(primary).getAllByRole('button')).toHaveLength(2);
  expect(within(primary).getByRole('button', { name: '编辑' })).toBeInTheDocument();
  expect(within(primary).getByRole('button', { name: '发布到飞书' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '来源与版本' })).not.toBeVisible();
  actions();
  expect(screen.getByRole('button', { name: '来源与版本' })).toBeVisible();
  expect(screen.getByRole('button', { name: '导出 Markdown' })).toHaveAttribute('data-export-content', '精确网络正文');
  expect(screen.getByRole('button', { name: '项目与标签' })).toBeVisible();
  expect(screen.getByRole('button', { name: '归档内容' })).toBeVisible();
  expect(screen.getByRole('button', { name: '移入回收站' })).toBeVisible();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '移入回收站' }));
  expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '保留' }));
  expect(api.json.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it('edits a labelled meeting title and only adds live Markdown preview after an explicit choice', async () => {
  api.json.mockResolvedValue({ ...currentVersion(), source_type: 'meeting_recording' });
  mount(); await screen.findByText('精确网络正文');
  expect(screen.getByRole('heading', { name: 'PDF 笔记', level: 1 })).toBeInTheDocument();
  expect(screen.queryByLabelText('会议名称')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '编辑' }));
  expect(screen.getByLabelText('会议名称')).toHaveValue('PDF 笔记');
  expect(screen.getByRole('textbox', { name: '纪要正文' })).toHaveValue('精确网络正文');
  expect(screen.queryByText('精确网络正文', { selector: 'p' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox', { name: '显示 Markdown 预览' }));
  expect(screen.getByText('精确网络正文', { selector: 'p' })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('会议名称'), { target: { value: '会议草稿' } });
  const primary = screen.getByRole('group', { name: '主要内容操作' });
  expect(within(primary).getAllByRole('button')).toHaveLength(2);
  expect(within(primary).getByRole('button', { name: '保存' })).toBeInTheDocument();
  expect(within(primary).getByRole('button', { name: '发布到飞书' })).toBeDisabled();
  actions(); expect(screen.getByRole('link', { name: '全文翻译 · MCP' })).toHaveAttribute('aria-disabled', 'true');
});

it('uses selected history title and content, merges only its matching first H1 and exports intact history', async () => {
  api.json.mockResolvedValue(currentVersion({ ...note(), content: '# PDF 笔记\n\n最新正文', versions: [{ id: 'history', title: '历史标题', content: '# 历史标题\n\n历史内容', created_at: '2026-10-12T00:00:00Z' }] }));
  mount(); await screen.findByText('最新正文');
  actions(); fireEvent.click(screen.getByRole('button', { name: '来源与版本' }));
  fireEvent.change(screen.getByLabelText(/已保存版本/), { target: { value: 'history' } });
  expect(screen.getByRole('button', { name: '生成新版本' })).toBeDisabled();
  expect(screen.getByText('正在查看历史版本。返回最新正文后，可基于已保存输入生成新版本。')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '关闭' }));
  expect(screen.getByRole('heading', { level: 1, name: '历史标题' })).toBeInTheDocument();
  expect(screen.getByText('历史内容')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '导出 Markdown' })).toHaveAttribute('data-export-content', '# 历史标题\n\n历史内容');
  expect(screen.getByRole('link', { name: '全文翻译 · MCP' })).toHaveAttribute('href', `/settings/mcp?mode=translation&note=${key}&version=history`);
});

it.each([['document', '完整结构化笔记'], ['video', '完整结构化笔记'], ['meeting_recording', '完整会议纪要'], ['meeting_video', '完整会议纪要']])('uses the confirmed target for %s, closes the version Sheet and preserves the previous body after generation failure', async (sourceType, label) => {
  api.json.mockImplementation((_path, options) => options?.method === 'POST' ? Promise.reject(new Error('模型暂不可用')) : Promise.resolve(currentVersion({ ...note(), source_type: sourceType })));
  mount(); await screen.findByText('精确网络正文'); actions();
  fireEvent.click(screen.getByRole('button', { name: '来源与版本' }));
  expect(screen.getByRole('dialog')).toHaveTextContent('来源与版本');
  fireEvent.click(screen.getByRole('button', { name: '生成新版本' }));
  expect(screen.getAllByRole('dialog')).toHaveLength(1);
  expect(screen.getByRole('dialog')).toHaveTextContent('生成并保存新版本');
  expect(screen.getByRole('option', { name: label })).toHaveValue('minutes');
  expect(screen.getByLabelText('整理目标')).toHaveValue('minutes');
  fireEvent.click(screen.getByRole('button', { name: '生成并保存新版本' }));
  await within(screen.getByRole('dialog')).findByText('模型暂不可用');
  expect(screen.getByText('精确网络正文')).toBeInTheDocument();
  const requests = api.json.mock.calls.filter(([, options]) => options?.method === 'POST'); expect(requests).toHaveLength(1);
  expect(JSON.parse(requests[0][1].body)).toMatchObject({ base_revision: 4, template: 'minutes' });
});

it('allows inspecting an original failed generation even while new generation is blocked by a draft', async () => {
  // Use the actual recovery helper format rather than guessing a storage key.
  const { readGenerationRecovery, writeGenerationRecovery } = await import('@/lib/workspaceGenerationRecovery');
  writeGenerationRecovery('alice', key, { operation_id: 'original-operation', instructions: '原要求', template: 'summary', base_revision: 4, error: '原请求未知' });
  localStorage.setItem(`vinote:draft:alice:workspace:${key}`, JSON.stringify({ title: 'PDF 笔记', content: '保留草稿', baseRevision: 4 }));
  api.json.mockResolvedValue(currentVersion()); mount(); await screen.findByDisplayValue('保留草稿'); actions();
  fireEvent.click(screen.getByRole('button', { name: '来源与版本' }));
  expect(screen.getByRole('button', { name: '查看与恢复原生成请求' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: '查看与恢复原生成请求' }));
  expect(screen.getAllByRole('dialog')).toHaveLength(1);
  expect(screen.getByLabelText('补充要求')).toHaveValue('原要求');
  expect(api.json.mock.calls.every(([, options]) => !options?.method)).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '关闭（保留原请求）' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(readGenerationRecovery('alice', key)?.operation_id).toBe('original-operation');
  expect(screen.getByLabelText('笔记正文')).toHaveValue('保留草稿');
  expect(api.json.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it('offers a visible generation cancel and Chinese close without sending a request or losing the inputs', async () => {
  api.json.mockResolvedValue(currentVersion()); mount(); await screen.findByText('精确网络正文'); actions();
  fireEvent.click(screen.getByRole('button', { name: '来源与版本' }));
  fireEvent.click(screen.getByRole('button', { name: '生成新版本' }));
  expect(screen.getByRole('button', { name: '关闭' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('补充要求'), { target: { value: '尚未提交的要求' } });
  fireEvent.click(screen.getByRole('button', { name: '取消' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByText('精确网络正文')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '来源与版本' })); fireEvent.click(screen.getByRole('button', { name: '生成新版本' }));
  expect(screen.getByLabelText('补充要求')).toHaveValue('尚未提交的要求');
  expect(api.json.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});
it('has visible classification cancel and comparison close, preserving content without a write', async () => {
  api.json.mockResolvedValue(currentVersion()); mount(); await screen.findByText('精确网络正文'); actions();
  fireEvent.click(screen.getByRole('button', { name: '项目与标签' }));
  expect(screen.getByRole('button', { name: '关闭' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '取消' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '来源与版本' }));
  fireEvent.change(screen.getByLabelText(/已保存版本/), { target: { value: 'v1' } });
  fireEvent.click(screen.getByRole('button', { name: '比较当前与所选版本' }));
  expect(screen.getAllByRole('dialog')).toHaveLength(1);
  expect(screen.getByRole('dialog')).toHaveTextContent('版本比较');
  fireEvent.click(screen.getByRole('button', { name: '关闭比较' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByText('历史正文')).toBeInTheDocument();
  expect(useWorkspaceStore.getState().details[key].content).toBe('精确网络正文');
  expect(api.json.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it.each(['全文翻译 · MCP', '流程图整理（选择已保存内容）'])('retains file filter and selected item through %s with a real source version', async name => {
  const parent = '/files?type=file&q=Word&file=file-1';
  api.json.mockResolvedValue(currentVersion()); mount(`/workspace/${key}?returnTo=${encodeURIComponent(parent)}&view=summary`, { returnTo: parent });
  await screen.findByText('精确网络正文'); actions(); fireEvent.click(screen.getByRole('link', { name }));
  const link = screen.getByRole('link', { name: '返回内容详情' });
  const context = new URL(link.getAttribute('href')!, 'https://vinote.invalid');
  expect(context.searchParams.get('returnTo')).toBe(parent); expect(context.searchParams.get('view')).toBe('summary');
  expect(screen.getByLabelText('目标地址')).toHaveTextContent('version=current');
  fireEvent.click(link); await screen.findByText('精确网络正文');
  fireEvent.click(screen.getByRole('button', { name: '返回文件库' }));
  expect(screen.getByLabelText('目标地址').textContent).toBe(parent);
});

it('explains unavailable source versions and does not substitute another version for translation', async () => {
  mount(); await screen.findByText('精确网络正文'); actions();
  const tool = screen.getByRole('link', { name: '全文翻译 · MCP' });
  expect(tool).toHaveAttribute('aria-disabled', 'true'); expect(tool.getAttribute('href')).not.toContain('version=');
  fireEvent.click(tool); expect(screen.getByText('精确网络正文')).toBeInTheDocument();
  expect(screen.getByText(/先保存并确认同步且源版本可读取/)).toBeInTheDocument();
});

it('returns from MCP to the same real historical title and body, not the latest view', async () => {
  api.json.mockResolvedValue(currentVersion()); mount(); await screen.findByText('精确网络正文'); actions();
  fireEvent.click(screen.getByRole('button', { name: '来源与版本' }));
  fireEvent.change(screen.getByLabelText(/已保存版本/), { target: { value: 'v1' } });
  fireEvent.click(screen.getByRole('button', { name: '关闭' }));
  fireEvent.click(screen.getByRole('link', { name: '全文翻译 · MCP' }));
  expect(screen.getByRole('link', { name: '返回内容详情' }).getAttribute('href')).toContain('version=v1');
  fireEvent.click(screen.getByRole('link', { name: '返回内容详情' }));
  await screen.findByText('历史正文'); expect(screen.getByRole('heading', { name: '第一版', level: 1 })).toBeInTheDocument();
  expect(screen.queryByText('精确网络正文')).not.toBeInTheDocument();
});
