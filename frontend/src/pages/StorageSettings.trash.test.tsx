import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter, useNavigate } from 'react-router-dom';
const f = vi.hoisted(() => ({ purge: vi.fn(), restore: vi.fn() }));
vi.mock('@/stores/authStore', async () => {
  const { create } = await import('zustand'); return { useAuthStore: create(() => ({ user: { id: 'alice' } })) };
});
vi.mock('@/stores/workspaceStore', async () => {
  const { create } = await import('zustand'); return { useWorkspaceStore: create(() => ({ owner: 'alice', ready: true,
    busy: false, error: '', items: [], details: {}, initialize: vi.fn(), changeDeleted: f.restore, purgeDeleted: f.purge })) };
});
vi.mock('@/lib/audioStorage', () => ({ listPendingMeetings: vi.fn(async () => []) }));
import { useWorkspaceStore } from '@/stores/workspaceStore';
import { useAuthStore } from '@/stores/authStore';
import { StorageSettings } from './StorageSettings';
const item = (key: string) => ({ key, title: `Synthetic ${key}`, deleted: true, revision: 4 });
const click = async (name: string) => { await act(async () => { fireEvent.click(screen.getByRole('button', { name, exact: true })); }); };
let navigate: ReturnType<typeof useNavigate>;
function Navigation() { navigate = useNavigate(); return null; }
async function mount() { await act(async () => { render(<MemoryRouter><Navigation /><StorageSettings /></MemoryRouter>); }); }
beforeEach(() => {
  vi.resetAllMocks(); useAuthStore.setState({ user: { id: 'alice' } } as never);
  useWorkspaceStore.setState({ owner: 'alice', ready: true, busy: false, items: [item('one'), item('two')] as never, details: {} });
  f.purge.mockImplementation(async (key: string) => {
    useWorkspaceStore.setState(s => ({ items: s.items.filter(item => item.key !== key) }));
  });
});
afterEach(cleanup);

it('requires explicit confirmation for one exact item and cancel makes no request', async () => {
  await mount(); await click('永久删除Synthetic one');
  const dialog = screen.getByRole('alertdialog');
  expect(within(dialog).getByText(/原始音视频.*不受影响/)).toBeInTheDocument();
  expect(f.purge).not.toHaveBeenCalled();
  await click('取消');
  expect(f.purge).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.getByRole('button', { name: '永久删除Synthetic one' })).toHaveFocus());
  await click('永久删除Synthetic one'); await click('确认永久删除');
  expect(f.purge.mock.calls).toEqual([['one', 'alice', 4]]);
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('已永久清理 1 份内容');
  expect(screen.getByText('Synthetic two')).toBeInTheDocument();
  expect(f.restore).not.toHaveBeenCalled();
});

it('bulk cleanup reports partial failure and retries only failures from the frozen selection', async () => {
  f.purge.mockImplementationOnce(async () => {
    useWorkspaceStore.setState(s => ({ items: s.items.filter(item => item.key !== 'one') }));
  }).mockRejectedValueOnce(new Error('设备存储未能写入'));
  await mount(); await click('清空回收站');
  // New trash appearing after the confirmation is outside its frozen selection.
  act(() => useWorkspaceStore.setState(s => ({ items: [...s.items, item('later')] as never })));
  await click('确认永久删除');
  expect(f.purge.mock.calls).toEqual([['one', 'alice', 4], ['two', 'alice', 4]]);
  expect(within(screen.getByRole('alertdialog')).getByRole('alert')).toHaveTextContent('设备存储未能写入');
  expect(screen.getByRole('button', { name: '重试清理' })).toBeEnabled();
  await click('重试清理');
  expect(f.purge.mock.calls).toEqual([['one', 'alice', 4], ['two', 'alice', 4], ['two', 'alice', 4]]);
  expect(screen.getByText('Synthetic later')).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('已永久清理 2 份内容');
});

it('a route change cancels an unsubmitted confirmation without deleting', async () => {
  await mount(); await click('清空回收站');
  act(() => navigate('/settings/storage?changed=1'));
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  expect(f.purge).not.toHaveBeenCalled();
});

it('an old in-flight response cannot clear the next item or report success to another account', async () => {
  let resolve!: () => void;
  f.purge.mockImplementationOnce(() => new Promise<void>(done => { resolve = done; }));
  await mount(); await click('清空回收站'); await click('确认永久删除');
  expect(f.purge).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: '清理中…' })).toBeDisabled();
  act(() => {
    useAuthStore.setState({ user: { id: 'bob' } } as never);
    useWorkspaceStore.setState({ owner: 'bob', items: [item('bob')] as never });
  });
  await act(async () => { resolve(); });
  expect(f.purge).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(screen.getByText('Synthetic bob')).toBeInTheDocument();
});

it('two confirmation clicks in the same render submit once and do not create a false retry', async () => {
  let resolve!: () => void;
  f.purge.mockImplementationOnce(() => new Promise<void>(done => { resolve = done; }));
  await mount(); await click('永久删除Synthetic one');
  const button = screen.getByRole('button', { name: '确认永久删除' });
  act(() => { fireEvent.click(button); fireEvent.click(button); });
  expect(f.purge).toHaveBeenCalledTimes(1);
  await act(async () => { resolve(); });
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('已永久清理 1 份内容');
});

it('does not offer an enabled clear action before owner-bound cache reading succeeds', async () => {
  useWorkspaceStore.setState({ ready: false }); await mount();
  expect(screen.queryByRole('button', { name: '清空回收站' })).not.toBeInTheDocument();
  expect(f.purge).not.toHaveBeenCalled();
});
