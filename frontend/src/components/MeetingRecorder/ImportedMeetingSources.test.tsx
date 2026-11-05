vi.mock('./MeetingDisplayEditor', () => ({ MeetingDisplayEditor: () => null }));
vi.mock('@/hooks/useMeetingDisplay', () => ({ useMeetingDisplay: () => ({}), MEETING_DISPLAY_CHANGED: 'vinote-meeting-display-changed' }));
import { act, render, screen, waitFor, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ api: vi.fn(), owner: 'owner', listeners: new Set<(state: { user: { id: string } }, previous: { user: { id: string } }) => void>() }));
vi.mock('@/lib/api', () => ({ apiJson: mocks.api }));
vi.mock('@/stores/authStore', () => ({ useAuthStore: { getState: () => ({ user: { id: mocks.owner } }), subscribe: (listener: (state: { user: { id: string } }, previous: { user: { id: string } }) => void) => { mocks.listeners.add(listener); return () => mocks.listeners.delete(listener); } } }));
import { ImportedMeetingSources } from './ImportedMeetingSources';
const source = { id: 'task:opaque', filename: '讨论.webm', purpose: 'meeting', task_id: 'same-task', processing_status: 'failed', error_code: 'unknown_result' };
const mount = (coveredTasks: string[] = []) => render(<MemoryRouter><ImportedMeetingSources owner="owner" coveredTasks={coveredTasks} returnTo="/meetings?q=讨论" /></MemoryRouter>);
beforeEach(() => { mocks.owner = 'owner'; mocks.listeners.clear(); mocks.api.mockReset(); });
afterEach(cleanup);
it('failed upload without minutes has a source-only link and never posts', async () => {
  mocks.api.mockResolvedValue({ items: [source] }); mount();
  expect((await screen.findAllByText('未命名会议')).length).toBeGreaterThan(0);
  expect(screen.getByRole('region', { name: '会议资料' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { level: 2, name: '待生成纪要的会议' })).toHaveClass('text-balance');
  expect(screen.getByRole('heading', { level: 3, name: '未命名会议' })).toHaveClass('text-balance');
  expect(screen.getByText('处理结果尚未确认，原文件已保留。')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '查看资料与处理记录' })).toHaveAttribute('href', '/meetings/files?purpose=meeting&file=task%3Aopaque');
  expect(screen.queryByText('same-task')).not.toBeInTheDocument();
  expect(mocks.api.mock.calls).toEqual([['/api/files']]);
});
it('saved minutes and retained recording task dedupe while notes stay separate', async () => {
  mocks.api.mockResolvedValue({ items: [source, { ...source, id: 'saved', task_id: 'other', note_id: 'note' }, { ...source, id: 'note-input', purpose: 'note' }] }); mount(['same-task']);
  await waitFor(() => expect(mocks.api).toHaveBeenCalled());
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  expect(screen.queryByRole('region', { name: '会议资料' })).not.toBeInTheDocument();
});
it('a failed source read offers an in-place GET retry without empty claims', async () => {
  mocks.api.mockRejectedValueOnce(new Error('failure')).mockResolvedValue({ items: [source] }); mount();
  await userEvent.click(await screen.findByRole('button', { name: '重新读取会议资料' }));
  expect((await screen.findAllByText('未命名会议')).length).toBeGreaterThan(0);
  expect(mocks.api.mock.calls).toEqual([['/api/files'], ['/api/files']]);
});
it('stale response after account changes cannot reveal an old source', async () => {
  let finish!: (value: { items: typeof source[] }) => void;
  mocks.api.mockImplementation(() => new Promise(resolve => { finish = resolve; })); mount();
  await act(async () => { mocks.owner = 'other'; finish({ items: [source] }); });
  expect(screen.queryByText('讨论.webm')).not.toBeInTheDocument();
});

it('A-B-A account change invalidates an in-flight source read even when owner returns', async () => {
  let finish!: (value: { items: typeof source[] }) => void;
  mocks.api.mockImplementation(() => new Promise(resolve => { finish = resolve; })); mount();
  await act(async () => {
  for (const next of ['other', 'owner']) {
    const previous = mocks.owner; mocks.owner = next;
    for (const listener of mocks.listeners) listener({ user: { id: next } }, { user: { id: previous } });
  }
  finish({ items: [source] });
  });
  expect(screen.queryByText('讨论.webm')).not.toBeInTheDocument();
});

it('source-only meetings obey the shared list search and report the matching count', async () => {
  mocks.api.mockResolvedValue({ items: [source, { ...source, id: 'task:second', task_id: 'second', filename: '其他.wav' }] });
  const onSourceCount = vi.fn();
  render(<MemoryRouter><ImportedMeetingSources owner="owner" coveredTasks={[]} returnTo="/meetings" query="讨论" filter="需处理" onSourceCount={onSourceCount} /></MemoryRouter>);
  expect((await screen.findAllByText('未命名会议')).length).toBeGreaterThan(0);
  expect(screen.queryByText('其他.wav')).not.toBeInTheDocument();
  await waitFor(() => expect(onSourceCount).toHaveBeenLastCalledWith(1));
});

it.each(['uploaded', 'preparing', 'downloading', 'transcribing', 'diarizing', 'parallel_analysis', 'aligning', 'analyzing_video', 'summarizing', 'screenshots', 'saving_result'])('includes backend %s originals in the processing filter', async status => {
  mocks.api.mockResolvedValue({ items: [{ ...source, processing_status: status }, { ...source, id: 'finished', filename: '完成.wav', processing_status: 'success' }, { ...source, id: 'failed', filename: '失败.wav', processing_status: 'failed' }] });
  const onSourceCount = vi.fn();
  render(<MemoryRouter><ImportedMeetingSources owner="owner" coveredTasks={[]} returnTo="/meetings" filter="处理中" onSourceCount={onSourceCount} /></MemoryRouter>);
  expect((await screen.findAllByText('未命名会议')).length).toBeGreaterThan(0);
  expect(screen.queryByText('完成.wav')).not.toBeInTheDocument();
  expect(screen.queryByText('失败.wav')).not.toBeInTheDocument();
  await waitFor(() => expect(onSourceCount).toHaveBeenLastCalledWith(1));
});

it('confirms deletion of an unassociated imported meeting and removes it only after success', async () => {
  mocks.api.mockResolvedValueOnce({ items: [{ id: 'file-1', filename: 'original.wav', purpose: 'meeting' }] }).mockResolvedValueOnce({ deleted: true });
  mount();
  await userEvent.click(await screen.findByRole('button', { name: '删除整场会议' }));
  expect(screen.getByRole('dialog')).toHaveTextContent('已发布的飞书文档不会删除');
  expect(mocks.api).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole('button', { name: '确认删除会议' }));
  await waitFor(() => expect(screen.queryByRole('region', { name: '会议资料' })).not.toBeInTheDocument());
  expect(mocks.api).toHaveBeenLastCalledWith('/api/files/file-1/orphan-meeting', { method: 'DELETE' });
});

it('keeps an imported meeting visible when deletion is rejected', async () => {
  mocks.api.mockResolvedValueOnce({ items: [{ id: 'file-1', filename: 'original.wav', purpose: 'meeting' }] }).mockRejectedValueOnce(new Error('会议已关联，请重新读取'));
  mount();
  await userEvent.click(await screen.findByRole('button', { name: '删除整场会议' }));
  await userEvent.click(screen.getByRole('button', { name: '确认删除会议' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('会议已关联');
  await userEvent.click(screen.getByRole('button', { name: '取消' }));
  expect(screen.getByRole('region', { name: '会议资料' })).toBeVisible();
});

it('uses the verified canonical identity for an imported task source', async () => {
  const remove = vi.fn().mockResolvedValue(undefined);
  mocks.api.mockResolvedValueOnce({ items: [source] });
  render(<MemoryRouter><ImportedMeetingSources owner="owner" coveredTasks={[]} returnTo="/meetings" onDeleteTask={remove} /></MemoryRouter>);
  await userEvent.click(await screen.findByRole('button', { name: '删除整场会议' }));
  await userEvent.click(screen.getByRole('button', { name: '确认删除会议' }));
  await waitFor(() => expect(remove).toHaveBeenCalledWith('opaque'));
  await waitFor(() => expect(screen.queryByRole('region', { name: '会议资料' })).not.toBeInTheDocument());
});
