import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ api: vi.fn(), owner: 'alice', localRead: vi.fn(), localWrite: vi.fn(), listeners: new Set<(next: { user: { id: string } }, previous: { user: { id: string } }) => void>() }));
vi.mock('@/lib/api', () => ({ apiJson: mocks.api }));
vi.mock('@/stores/authStore', () => ({ useAuthStore: Object.assign((select: (state: { user: { id: string } }) => unknown) => select({ user: { id: mocks.owner } }), { getState: () => ({ user: { id: mocks.owner } }), subscribe: (listener: (next: { user: { id: string } }, previous: { user: { id: string } }) => void) => { mocks.listeners.add(listener); return () => mocks.listeners.delete(listener); } }) }));
vi.mock('@/lib/audioStorage', () => ({ getPendingMeeting: mocks.localRead, updatePendingMeeting: mocks.localWrite }));
import { MeetingDisplayEditor } from './MeetingDisplayEditor';
const task = '11111111-1111-4111-8111-111111111111';
afterEach(cleanup);
beforeEach(() => { mocks.owner = 'alice'; vi.clearAllMocks(); });
it('edits display metadata using the same canonical ID without sending original or note changes', async () => {
  mocks.api.mockResolvedValue({ source_key: `task:${task}`, title: '采购会议', meeting_date: '2026-10-31' });
  const saved = vi.fn();
  render(<MeetingDisplayEditor sourceKey={`task:${task}`} title="" date="" onSaved={saved} />);
  fireEvent.click(screen.getByRole('button', { name: '编辑会议信息' }));
  fireEvent.change(screen.getByLabelText('会议名称'), { target: { value: '采购会议' } });
  fireEvent.change(screen.getByLabelText('会议日期'), { target: { value: '2026-10-31' } });
  fireEvent.click(screen.getByRole('button', { name: '保存会议信息' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(mocks.api).toHaveBeenCalledExactlyOnceWith(`/api/meeting-source-links/display/task/${task}`, { method: 'PUT', body: JSON.stringify({ title: '采购会议', meeting_date: '2026-10-31' }) });
});
it('keeps edited values after a failed save', async () => {
  mocks.api.mockRejectedValue(new Error('保存未完成'));
  render(<MeetingDisplayEditor sourceKey={`task:${task}`} title="原标题" date="2026-11-04" />);
  fireEvent.click(screen.getByRole('button', { name: '编辑会议信息' }));
  fireEvent.change(screen.getByLabelText('会议名称'), { target: { value: '新标题' } });
  fireEvent.click(screen.getByRole('button', { name: '保存会议信息' }));
  await screen.findByRole('alert');
  expect(screen.getByLabelText('会议名称')).toHaveValue('新标题');
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});
it('does not save across an account change', () => {
  render(<MeetingDisplayEditor sourceKey={`task:${task}`} title="会议" date="" />);
  fireEvent.click(screen.getByRole('button', { name: '编辑会议信息' }));
  mocks.owner = 'bob';
  fireEvent.click(screen.getByRole('button', { name: '保存会议信息' }));
  expect(mocks.api).not.toHaveBeenCalled();
});

it('does not apply an old save acknowledgement after A to B to A', async () => {
  let finish!: (value: unknown) => void;
  mocks.api.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const saved = vi.fn();
  render(<MeetingDisplayEditor sourceKey={`task:${task}`} title="会议" date="" onSaved={saved} />);
  fireEvent.click(screen.getByRole('button', { name: '编辑会议信息' }));
  fireEvent.click(screen.getByRole('button', { name: '保存会议信息' }));
  await act(async () => {
    for (const owner of ['bob', 'alice']) {
      const previous = mocks.owner; mocks.owner = owner;
      mocks.listeners.forEach(listener => listener({ user: { id: owner } }, { user: { id: previous } }));
    }
    finish({});
  });
  expect(saved).not.toHaveBeenCalled();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
