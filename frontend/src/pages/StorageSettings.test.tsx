import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
const calls = vi.hoisted(() => ({ restore: vi.fn(), initialize: vi.fn() }));
vi.mock('@/stores/authStore', async () => {
  const { create } = await import('zustand'); return { useAuthStore: create(() => ({ user: { id: 'alice' } })) };
});
vi.mock('@/stores/workspaceStore', async () => {
  const { create } = await import('zustand'); return { useWorkspaceStore: create(() => ({ ready: true, busy: false, error: '', details: {}, items: [], initialize: calls.initialize, changeDeleted: calls.restore })) };
});
vi.mock('@/lib/audioStorage', () => ({ listPendingMeetings: vi.fn(async () => []) }));
import { useWorkspaceStore } from '@/stores/workspaceStore';
import { StorageSettings } from './StorageSettings';
const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView');
beforeEach(() => { vi.clearAllMocks(); Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() }); useWorkspaceStore.setState({ ready: true, items: [{ key: 'exact-id', title: '删除的正文', deleted: true }] as never }); });
afterEach(() => { cleanup(); if (originalScroll) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScroll); else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView'); });
async function mount(path = '/settings/storage') { await act(async () => { render(<MemoryRouter initialEntries={[path]}><StorageSettings /></MemoryRouter>); }); }
it('keeps old trash deep links usable without exposing sync controls or checking remote state', async () => {
  await mount('/settings/sync?returnTo=%2Fnotes%3Fproject%3Dreal#trash');
  expect(screen.getByRole('heading', { name: '存储' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: '内容回收站' })).toHaveFocus();
  expect(screen.getByRole('link', { name: '返回笔记' })).toHaveAttribute('href', '/notes?project=real');
  expect(screen.queryByText(/同步|云端|配额|修订/)).not.toBeInTheDocument();
  expect(calls.initialize).not.toHaveBeenCalled();
});
it('keeps the same item and offers retry after failed restoration, without deleting originals', async () => {
  calls.restore.mockRejectedValueOnce(new Error('设备存储未能写入')).mockResolvedValueOnce({ key: 'exact-id', deleted: false });
  await mount();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '恢复内容' })));
  expect(screen.getByRole('alert')).toHaveTextContent('设备存储未能写入');
  expect(screen.getByText('删除的正文')).toBeInTheDocument();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '恢复内容' })));
  expect(calls.restore).toHaveBeenNthCalledWith(1, 'exact-id', false);
  expect(calls.restore).toHaveBeenNthCalledWith(2, 'exact-id', false);
  expect(calls.initialize).not.toHaveBeenCalled();
});
it('does not show an empty trash or zero contents before the first device read has completed', async () => {
  useWorkspaceStore.setState({ ready: false }); await mount();
  expect(screen.getByText('正在读取保存内容…')).toBeInTheDocument();
  expect(screen.queryByText('回收站为空。')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '恢复内容' })).not.toBeInTheDocument();
});
