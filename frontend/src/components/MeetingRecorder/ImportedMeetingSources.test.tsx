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
  expect(await screen.findByText('讨论.webm')).toBeInTheDocument();
  expect(screen.getByRole('region', { name: '会议资料' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { level: 2, name: '会议资料' })).toHaveClass('text-balance');
  expect(screen.getByRole('heading', { level: 3, name: '讨论.webm' })).toHaveClass('text-balance');
  expect(screen.getByText('录音、视频与逐字稿分别保留，可查看原文件和处理记录。')).toHaveClass('text-pretty');
  expect(screen.getByText('处理结果尚未确认，原文件已保留。')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '查看资料与处理记录' })).toHaveAttribute('href', '/files?purpose=meeting&file=task%3Aopaque');
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
  expect(await screen.findByText('讨论.webm')).toBeInTheDocument();
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
