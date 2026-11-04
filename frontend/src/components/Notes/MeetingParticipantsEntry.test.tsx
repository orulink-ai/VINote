import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useAuthStore } from '@/stores/authStore';
import { MeetingParticipantsEntry } from './MeetingParticipantsEntry';
import { feishuStatus } from '@/lib/feishu';
vi.mock('@/lib/feishu', () => ({ feishuStatus: vi.fn() }));
vi.mock('./MeetingParticipantsConfirmation', () => ({ MeetingParticipantsConfirmation: () => <><button>确认参会人</button><input aria-label="映射草稿" defaultValue="" /></> }));
beforeEach(() => { vi.clearAllMocks(); useAuthStore.setState({ user: { id: 'owner' } as never }); });
afterEach(cleanup);
it('makes manual matching available for a valid connection even with automatic delivery off', async () => {
  vi.mocked(feishuStatus).mockResolvedValue({ connected: true, expired: false, auto_publish: false } as never);
  render(<MeetingParticipantsEntry noteId="note" taskId="task" />);
  expect(await screen.findByRole('button', { name: '确认参会人' })).toBeVisible();
  expect(screen.getByText('匹配本会议的说话人与飞书联系人，用于人物归属和通知对象。')).toBeVisible();
});
it('a disconnected account never mounts the contact-dependent confirmation', async () => {
  vi.mocked(feishuStatus).mockResolvedValue({ connected: false, expired: false } as never);
  render(<MeetingParticipantsEntry noteId="note" taskId="task" />);
  await waitFor(() => expect(feishuStatus).toHaveBeenCalledOnce());
  expect(screen.queryByRole('button')).toBeNull();
});
it('rejects a late connection result from an earlier owner visit', async () => {
  let resolve!: (value: never) => void;
  vi.mocked(feishuStatus).mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValue({ connected: false } as never);
  render(<MeetingParticipantsEntry noteId="note" taskId="task" />);
  await act(async () => { useAuthStore.setState({ user: { id: 'other' } as never }); useAuthStore.setState({ user: { id: 'owner' } as never }); });
  await act(async () => resolve({ connected: true, expired: false } as never));
  expect(screen.queryByRole('button')).toBeNull();
});

it.each([{ connected: true, expired: true }, { connected: true, expired: false, connection_state: 'service_unavailable' }, { connected: 'true', expired: false }])('does not mount contacts for expired, unknown or malformed connection state', async status => {
  vi.mocked(feishuStatus).mockResolvedValue(status as never);
  render(<MeetingParticipantsEntry noteId="note" taskId="task" />);
  await waitFor(() => expect(feishuStatus).toHaveBeenCalledOnce());
  expect(screen.queryByRole('button')).toBeNull();
});

it('rechecks connection on return to the window and unmounts a disconnected contact panel', async () => {
  vi.mocked(feishuStatus).mockResolvedValueOnce({ connected: true, expired: false } as never).mockResolvedValue({ connected: false, expired: false } as never);
  render(<MeetingParticipantsEntry noteId="note" taskId="task" />);
  await screen.findByRole('button', { name: '确认参会人' });
  await act(async () => window.dispatchEvent(new Event('focus')));
  expect(feishuStatus).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole('button')).toBeNull();
});

it('preserves an unsaved mapping while a focus recheck confirms the same connection', async () => {
  vi.mocked(feishuStatus).mockResolvedValue({ connected: true, expired: false, connection_binding_hash: 'same' } as never);
  render(<MeetingParticipantsEntry noteId="note" taskId="task" />);
  fireEvent.change(await screen.findByLabelText('映射草稿'), { target: { value: 'unsaved identity' } });
  await act(async () => window.dispatchEvent(new Event('focus')));
  expect(screen.getByLabelText('映射草稿')).toHaveValue('unsaved identity');
});
