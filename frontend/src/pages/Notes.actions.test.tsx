import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
const calls = vi.hoisted(() => ({ remove: vi.fn(), load: vi.fn(), initialize: vi.fn() }));
vi.mock('@/stores/workspaceStore', async () => {
  const { create } = await import('zustand'); return { useWorkspaceStore: create(() => ({ owner: 'owner', ready: true, busy: false, error: '', changeDeleted: calls.remove, initialize: calls.initialize })) };
});
vi.mock('@/stores/noteLibraryStore', () => ({ useNoteLibraryStore: () => ({ loading: false, error: '', loadNotes: calls.load }) }));
vi.mock('@/stores/teamStore', () => ({ useTeamStore: () => ({ currentWorkspace: { scope: 'personal' } }) }));
vi.mock('@/hooks/useViewState', async () => { const { useState } = await import('react'); return { useViewState: (_key: string, initial: unknown) => useState(initial) }; });
vi.mock('@/lib/i18n', () => ({ useI18n: () => ({ locale: 'zh-CN', formatDate: () => '2026/10/12' }) }));
vi.mock('@/hooks/useLibraryNotes', () => ({ useLibraryNotes: () => [{ id: 'exact-note', workspaceKey: 'exact-note', title: '笔记A', project: '项目A', content: '原正文', sourceType: 'document', sourceDevice: 'desktop', createdAt: '2026-10-12T05:00:00Z', status: 'done', syncLabel: '已同步' }], libraryNoteUrl: () => '/workspace/exact-note' }));
import { Notes } from './Notes';
function Where() { const location = useLocation(); return <output aria-label="页面位置">{JSON.stringify({ path: location.pathname + location.search + location.hash, state: location.state })}</output>; }
beforeEach(() => { vi.clearAllMocks(); calls.remove.mockResolvedValue({ key: 'exact-note', deleted: true }); });
afterEach(cleanup);
function mount() { render(<MemoryRouter initialEntries={['/notes?project=项目A#results']}><Notes /><Where /></MemoryRouter>); }
const where = () => JSON.parse(screen.getByLabelText('页面位置').textContent || '{}');
it('exposes independent edit and delete buttons without sync status or a hidden menu', () => {
  mount();
  expect(screen.getByRole('button', { name: '编辑《笔记A》' })).toBeVisible();
  expect(screen.getByRole('button', { name: '删除《笔记A》' })).toBeVisible();
  expect(screen.queryByText('已同步')).not.toBeInTheDocument();
  expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  expect(screen.queryByRole('menuitem')).not.toBeInTheDocument();
});
it('opens the exact saved content in edit mode and keeps the source project and list anchor', () => {
  mount(); fireEvent.click(screen.getByRole('button', { name: '编辑《笔记A》' }));
  expect(where().path).toBe('/workspace/exact-note?edit=1');
  expect(where().state.returnTo).toBe('/notes?project=%E9%A1%B9%E7%9B%AEA#results');
  expect(calls.remove).not.toHaveBeenCalled();
});
it('cancels deletion in place, then deletes only the actual content identity after explicit confirmation', async () => {
  mount(); fireEvent.click(screen.getByRole('button', { name: '删除《笔记A》' }));
  expect(screen.getByRole('alertdialog')).toHaveTextContent('原文件与已发布飞书文档保留');
  fireEvent.click(screen.getByRole('button', { name: '保留笔记' }));
  expect(calls.remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '删除《笔记A》' }));
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '移入回收站' })));
  expect(calls.remove).toHaveBeenCalledExactlyOnceWith('exact-note', true);
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  expect(decodeURIComponent(where().path)).toBe('/notes?project=项目A#results');
});
it('retains trash routing and its context through the canonical storage page', () => {
  mount(); const href = screen.getByRole('link', { name: '回收站' }).getAttribute('href')!;
  const target = new URL(href, 'https://vinote.invalid');
  expect(target.pathname).toBe('/settings/storage'); expect(target.hash).toBe('#trash');
  expect(decodeURIComponent(target.searchParams.get('returnTo')!)).toBe('/notes?project=项目A#results');
});
