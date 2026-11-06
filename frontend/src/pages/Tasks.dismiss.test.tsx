vi.mock('@/stores/noteLibraryStore', () => ({ useNoteLibraryStore: (select: (state: unknown) => unknown) => select({ loadNotes: taskHistoryLoad }) }));
const taskHistoryLoad = vi.hoisted(() => vi.fn(async () => {}));
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Tasks } from './Tasks';
import { apiJson } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';
import { listPendingMeetings } from '@/lib/audioStorage';
vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(), apiJson: vi.fn() }));
vi.mock('@/lib/audioStorage', () => ({ listPendingMeetings: vi.fn(async () => []) }));
vi.mock('@/hooks/useLibraryNotes', () => ({ useLibraryNotes: () => [], libraryNoteUrl: () => '/notes' }));
const api = vi.mocked(apiJson);
const key = 'vinote:source-receipt:owner:failed';
const raw = JSON.stringify({ id: 'failed', operationId: 'failed', meeting: true, sourceTitle: '失败会议', submissionState: 'accepted' });
const show = () => render(<MemoryRouter><Tasks /></MemoryRouter>);
beforeEach(() => {
  localStorage.clear(); vi.resetAllMocks();
  useAuthStore.setState({ user: { id: 'owner' } as never });
  localStorage.setItem(key, raw);
  vi.mocked(listPendingMeetings).mockResolvedValue([]);
  api.mockImplementation(async path => ({ task_id: path.split('/').pop(), status: 'failed' }));
});
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); });
async function confirmDelete() {
  fireEvent.click(await screen.findByRole('button', { name: '删除失败记录' }));
  await act(async () => { fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '删除记录' })); });
}
it('confirms dismissal, persists across reload, and preserves the original operation receipt', async () => {
  const view = show();
  fireEvent.click(await screen.findByRole('button', { name: '删除失败记录' }));
  expect(screen.getByRole('alertdialog')).toHaveTextContent('原文件、已保存内容和提交凭据都会保留');
  fireEvent.click(screen.getByRole('button', { name: '取消' }));
  expect(screen.getByRole('heading', { name: '失败会议' })).toBeVisible();
  await confirmDelete();
  expect(screen.queryByRole('heading', { name: '失败会议' })).toBeNull();
  expect(localStorage.getItem(key)).toBe(raw);
  view.unmount(); show();
  await waitFor(() => expect(screen.getByText('暂无生成任务')).toBeVisible());
  expect(localStorage.getItem(key)).toBe(raw);
  expect(api.mock.calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true);
});
it.each(['summary_result_unconfirmed', 'unknown_result', 'unknown_error', 'asr_incomplete_result'])('keeps running and %s tasks visible after earlier dismissal', async errorCode => {
  const view = show(); await confirmDelete(); view.unmount();
  api.mockImplementation(async path => ({ task_id: path.split('/').pop(), status: 'transcribing' }));
  const next = show();
  expect(await screen.findByText('转写中')).toBeVisible();
  expect(screen.getByRole('heading', { name: '失败会议' })).toBeVisible();
  expect(screen.queryByRole('button', { name: '删除失败记录' })).toBeNull();
  next.unmount();
  api.mockImplementation(async path => ({ task_id: path.split('/').pop(), status: 'failed', error_code: errorCode }));
  api.mockClear();
  show(); await waitFor(() => expect(api).toHaveBeenCalled());
  expect(await screen.findByRole('heading', { name: '失败会议' })).toBeVisible();
  expect(screen.queryByRole('button', { name: '删除失败记录' })).toBeNull();
});
it('never treats stale recording failure metadata as confirmation when its task cannot be read', async () => {
  localStorage.clear();
  vi.mocked(listPendingMeetings).mockResolvedValue([{ id: 'recording', ownerId: 'owner', taskId: 'failed', processingStatus: 'failed', options: { title: '原录音' } }] as never);
  api.mockRejectedValue(new Error('offline'));
  show();
  expect(await screen.findByRole('heading', { name: '原录音' })).toBeVisible();
  await waitFor(() => expect(api).toHaveBeenCalled());
  expect(screen.queryByRole('button', { name: '删除失败记录' })).toBeNull();
});
it('isolates dismissal by account and cancels an open confirmation on account change', async () => {
  show(); await confirmDelete();
  localStorage.setItem('vinote:source-receipt:other:failed', raw);
  act(() => useAuthStore.setState({ user: { id: 'other' } as never }));
  fireEvent.click(await screen.findByRole('button', { name: '删除失败记录' }));
  act(() => useAuthStore.setState({ user: { id: 'owner' } as never }));
  expect(screen.queryByRole('alertdialog')).toBeNull();
  act(() => useAuthStore.setState({ user: { id: 'other' } as never }));
  expect(await screen.findByRole('button', { name: '删除失败记录' })).toBeVisible();
});
it('does not dismiss a receipt replaced while the confirmation is open', async () => {
  show(); fireEvent.click(await screen.findByRole('button', { name: '删除失败记录' }));
  localStorage.setItem(key, JSON.stringify({ ...JSON.parse(raw), id: 'new-task' }));
  fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '删除记录' }));
  expect(screen.getByRole('heading', { name: '失败会议' })).toBeVisible();
});
it('dismisses failed recording history without removing the recording', async () => {
  localStorage.clear();
  const recording = { id: 'recording', ownerId: 'owner', taskId: 'failed', processingStatus: 'failed', options: { title: '原录音' } };
  vi.mocked(listPendingMeetings).mockResolvedValue([recording] as never);
  const view = show(); await confirmDelete();
  expect(screen.queryByRole('heading', { name: '原录音' })).toBeNull();
  expect(recording.taskId).toBe('failed');
  view.unmount(); show();
  await waitFor(() => expect(screen.getByText('暂无生成任务')).toBeVisible());
});
it('keeps the row when local persistence fails', async () => {
  show(); fireEvent.click(await screen.findByRole('button', { name: '删除失败记录' }));
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota'); });
  fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '删除记录' }));
  expect(screen.getByRole('heading', { name: '失败会议' })).toBeVisible();
  expect(screen.getByText('未能删除处理记录，请重试。')).toBeVisible();
});
