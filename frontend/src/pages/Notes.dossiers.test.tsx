import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
const mocks = vi.hoisted(() => ({ load: vi.fn(), remove: vi.fn() }));
vi.mock('@/stores/workspaceStore', async () => {
  const { create } = await import('zustand');
  return { useWorkspaceStore: create(() => ({ owner: 'alice', busy: false, error: '', changeDeleted: mocks.remove })) };
});
vi.mock('@/stores/noteLibraryStore', () => ({ useNoteLibraryStore: () => ({ loading: false, error: '', loadNotes: mocks.load }) }));
vi.mock('@/stores/teamStore', () => ({ useTeamStore: () => ({ currentWorkspace: { scope: 'personal' } }) }));
vi.mock('@/hooks/useViewState', async () => { const { useState } = await import('react'); return { useViewState: (_key: string, initial: unknown) => useState(initial) }; });
vi.mock('@/lib/i18n', () => ({ useI18n: () => ({ locale: 'zh-CN', formatDate: () => '今天' }) }));
vi.mock('@/hooks/useLibraryNotes', () => ({
  libraryNoteUrl: (note: { id: string }) => '/note/' + note.id,
  useLibraryNotes: () => [
    { id: 'new', title: '新版', content: '当前正文', updatedAt: '2026-11-04T02:00:00Z' },
    { id: 'old', title: '旧版', content: '独特旧关键词', updatedAt: '2026-11-04T01:00:00Z' },
  ].map(note => ({ ...note, createdAt: note.updatedAt, status: 'done', scope: 'personal', sourceType: 'document',
    originalSource: { ownerId: 'alice', originalId: 'file:one', canonicalTaskId: 'task' } })),
}));
import { Notes } from './Notes';
afterEach(cleanup);

it('shows one original with all summary versions even when search matches only an old version', () => {
  render(<MemoryRouter><Notes /></MemoryRouter>);
  expect(screen.getByText('1 篇笔记')).toBeVisible();
  fireEvent.change(screen.getByRole('textbox', { name: '搜索笔记' }), { target: { value: '独特旧关键词' } });
  expect(screen.getByRole('button', { name: '新版 · 已保存' })).toBeVisible();
  fireEvent.click(screen.getByText('2 个总结版本'));
  expect(screen.getByRole('link', { name: /旧版/ })).toHaveAttribute('href', '/note/old');
  expect(screen.getByRole('link', { name: /新版/ })).toHaveAttribute('href', '/note/new');
});

it('labels representative deletion as this version only and keeps other versions untouched', () => {
  render(<MemoryRouter><Notes /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: '删除当前版本《新版》' }));
  expect(within(screen.getByRole('alertdialog')).getByText(/其他总结版本/)).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: '保留笔记' }));
  expect(mocks.remove).not.toHaveBeenCalled();
});


it('filters grouped originals by save date and preserves every retained version', () => {
  render(<MemoryRouter><Notes /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: '筛选' }));
  fireEvent.change(screen.getByLabelText('按保存日期筛选'), { target: { value: '2026-11-03' } });
  expect(screen.queryByRole('button', { name: '新版 · 已保存' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '全部日期' }));
  expect(screen.getByRole('button', { name: '新版 · 已保存' })).toBeVisible();
  expect(screen.getByText('2 个总结版本')).toBeInTheDocument();
});
