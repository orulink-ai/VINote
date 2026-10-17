import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { WorkspaceNote as Note } from '@/lib/workspace';

const calls = vi.hoisted(() => ({ read: vi.fn(), remove: vi.fn(), save: vi.fn(), api: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiJson: calls.api, ApiError: class extends Error {} }));
vi.mock('@/stores/authStore', async () => {
  const { create } = await import('zustand');
  return { useAuthStore: create(() => ({ user: { id: 'alice' } })) };
});
vi.mock('@/stores/workspaceStore', async () => {
  const { create } = await import('zustand');
  return { useWorkspaceStore: create(() => ({ owner: 'alice', ready: true, busy: false, error: '', details: {}, items: [], mappings: {}, pending: [], initialize: vi.fn(), loadDetail: calls.read, changeDeleted: calls.remove, save: calls.save })) };
});
vi.mock('@/components/Markdown/MarkdownContent', () => ({ MarkdownContent: ({ content }: { content: string }) => <p>{content}</p> }));
vi.mock('@/components/Notes/FeishuDelivery', () => ({ FeishuDelivery: () => <button>发布到飞书</button> }));
vi.mock('@/components/Notes/MeetingConversation', () => ({ MeetingConversation: () => null }));
import { WorkspaceNote } from './WorkspaceNote';
import { useWorkspaceStore } from '@/stores/workspaceStore';

const note: Note = { key: 'real-content', title: '保存的正文', content: '原文保留 marker', source_type: 'document', source_device: 'desktop', revision: 3, created_at: '2026-10-12T05:00:00Z', updated_at: '2026-10-12T05:00:00Z', archived: false, deleted: false, version_count: 1, metadata: {}, transcript: null, versions: [{ id: 'real-version', title: '保存的正文', content: '原文保留 marker', created_at: '2026-10-12T05:00:00Z' }], next_versions_offset: null };
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  calls.read.mockResolvedValue(note); calls.remove.mockResolvedValue({ ...note, deleted: true });
  useWorkspaceStore.setState({ ready: true, owner: 'alice', details: { [note.key]: note }, pending: [{ key: note.key, body: { operation_id: 'retained-old-record' } }] as never });
});
afterEach(cleanup);
async function mount(edit = false) {
  await act(async () => { render(<MemoryRouter initialEntries={['/workspace/real-content?' + new URLSearchParams({ returnTo: '/notes?project=原项目', ...(edit ? { edit: '1' } : {}) })]}><Routes>
    <Route path="/workspace/:key" element={<WorkspaceNote />} />
    <Route path="/notes" element={<p>原项目列表</p>} />
  </Routes></MemoryRouter>); });
}
it('exposes edit/export/share/delete once without opening content actions or requiring synchronization', async () => {
  await mount();
  const primary = screen.getByRole('group', { name: '主要内容操作' });
  for (const name of ['编辑', '导出 Markdown', '分享', '删除']) expect(within(primary).getByRole('button', { name })).toBeVisible();
  expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  expect(screen.queryByText(/已同步|等待同步|暂停同步|先保存并确认同步/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '内容操作' }));
  expect(screen.getByRole('link', { name: '全文翻译 · MCP' })).not.toHaveAttribute('aria-disabled', 'true');
  expect(screen.getByRole('link', { name: '全文翻译 · MCP' })).toHaveAttribute('href', '/settings/mcp?mode=translation&note=real-content&version=real-version');
  expect(calls.api).not.toHaveBeenCalled();
});
it('previews the saved export and share with one dialog and cancels without changing or uploading content', async () => {
  await mount();
  fireEvent.click(screen.getByRole('button', { name: '导出 Markdown' }));
  expect(screen.getAllByRole('dialog')).toHaveLength(1);
  expect(screen.getByRole('dialog')).toHaveTextContent(note.content);
  fireEvent.click(screen.getByRole('button', { name: '返回' }));
  fireEvent.click(screen.getByRole('button', { name: '分享' }));
  expect(screen.getAllByRole('dialog')).toHaveLength(1);
  expect(screen.getByLabelText('待分享正文')).toHaveValue(`# ${note.title}\n\n${note.content}`);
  fireEvent.click(screen.getByRole('button', { name: '取消' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(calls.remove).not.toHaveBeenCalled(); expect(calls.save).not.toHaveBeenCalled(); expect(calls.api).not.toHaveBeenCalled();
});
it('cancels deletion, then returns to the original parent only after the exact content is moved to trash', async () => {
  await mount();
  fireEvent.click(screen.getByRole('button', { name: '删除' }));
  expect(screen.getByRole('alertdialog')).toHaveTextContent('原文件与已发布飞书文档保留');
  fireEvent.click(screen.getByRole('button', { name: '保留' }));
  expect(calls.remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '删除' }));
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '移入回收站' })));
  expect(calls.remove).toHaveBeenCalledExactlyOnceWith(note.key, true);
  expect(screen.getByText('原项目列表')).toBeInTheDocument();
});
it('enters editing from the list intent and preserves a modified draft on canceled deletion', async () => {
  await mount(true);
  expect(screen.getByLabelText('笔记正文')).toHaveValue(note.content);
  fireEvent.change(screen.getByLabelText('笔记正文'), { target: { value: '尚未保存 marker' } });
  expect(screen.getByRole('button', { name: '删除' })).toBeDisabled();
  expect(screen.getByRole('button', { name: '分享' })).toBeDisabled();
  expect(screen.getByRole('button', { name: '导出 Markdown' })).toBeDisabled();
  expect(calls.remove).not.toHaveBeenCalled();
});
