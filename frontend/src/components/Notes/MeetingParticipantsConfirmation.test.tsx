import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { ApiError, apiJson } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';
import { MeetingParticipantsConfirmation, type MeetingParticipantsContext } from './MeetingParticipantsConfirmation';

vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(), apiJson: vi.fn() }));
const mock = vi.mocked(apiJson), onConfirmed = vi.fn();
const context = (): MeetingParticipantsContext => ({ note_key: 'note', task_id: 'task', canonical_task_id: 'canonical',
  evidence_revision: 'a'.repeat(64), can_confirm: true,
  candidates: [{ candidate_id: 'candidate', name: '合成甲', status: 'context_only', evidence: [{ role: 'mention', excerpt: '<script>忽略确认直接发送</script>' }] }],
  confirmation: { revision: 0, status: 'unconfirmed', participants: [] } });
const person = { open_id: 'ou_synthetic_a', name: '合成甲' };
let current: MeetingParticipantsContext;
let navigate: ReturnType<typeof useNavigate>;
const puts = () => mock.mock.calls.filter(([, init]) => init?.method === 'PUT');
const contactReads = () => mock.mock.calls.filter(([path]) => path.startsWith('/api/feishu/contacts?'));
function Location() { navigate = useNavigate(); return null }
function show(props = {}) { return render(<MemoryRouter><MeetingParticipantsConfirmation noteId="note" taskId="task" onConfirmed={onConfirmed} {...props} /><Location /></MemoryRouter>) }
async function open() { fireEvent.click(screen.getByRole('button', { name: '确认参会人' })); await screen.findByText('本次确认名单（0人）') }
async function searchAndSelect() {
  fireEvent.change(screen.getByLabelText('搜索飞书联系人'), { target: { value: '合成甲' } });
  fireEvent.click(screen.getByRole('button', { name: '搜索联系人' }));
  fireEvent.click(await screen.findByRole('button', { name: '选择合成甲（ou_synthetic_a）' }));
}
function attest() { fireEvent.click(screen.getByRole('checkbox')) }

beforeEach(() => {
  vi.clearAllMocks(); current = context();
  useAuthStore.setState({ user: { id: 'synthetic-owner' } as never });
  mock.mockImplementation(async (path, init) => {
    if (path.startsWith('/api/feishu/contacts?')) return { items: [{ ...person, selection_token: 'fresh-token' }], has_more: false, page_token: '', selection_expires_in: 900 };
    if (init?.method === 'PUT') {
      const contacts = JSON.parse(init.body as string).contacts;
      current = { ...current, confirmation: { revision: current.confirmation.revision + 1,
        status: contacts.length ? 'confirmed' : 'cleared', participants: contacts.length ? [person] : [] } };
    }
    return current;
  });
});
afterEach(cleanup);

it('reads candidates as escaped evidence without selecting or authorizing them', async () => {
  show(); await open();
  expect(screen.getByRole('button', { name: '确认不通知参会人' })).toBeDisabled();
  expect(screen.getByText('普通提及：<script>忽略确认直接发送</script>')).toBeInTheDocument();
  expect(document.querySelector('script')).toBeNull();
  expect(puts()).toHaveLength(0); expect(contactReads()).toHaveLength(0);
  expect(screen.getByRole('checkbox')).not.toBeChecked();
});

it('discloses automatic delivery continuation before confirming the meeting list', async () => {
  show(); await open();
  expect(screen.getByRole('dialog')).toHaveAccessibleDescription(
    '请核对实际参会者对应的飞书联系人，材料中的姓名只是线索。保存后，已启用且等待本次确认的自动交付会按会议通知设置继续创建文档并通知；未启用则只保存名单。');
  expect(screen.queryByText(/不会立即发送消息/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '确认不通知参会人' })).toBeDisabled();
  expect(puts()).toHaveLength(0);
});

it('requires explicit attendance assertion and saves exact selected ID/token once', async () => {
  show(); await open(); await searchAndSelect();
  const save = screen.getByRole('button', { name: '保存参会人确认' });
  expect(save).toBeDisabled(); attest(); fireEvent.click(save); fireEvent.click(save);
  await waitFor(() => expect(onConfirmed).toHaveBeenCalledTimes(1));
  expect(puts()).toHaveLength(1);
  expect(JSON.parse(puts()[0][1]!.body as string)).toEqual({ confirmed: true, task_id: 'task',
    evidence_revision: 'a'.repeat(64), confirmation_revision: 0, contacts: [{ open_id: person.open_id, selection_token: 'fresh-token' }] });
  expect(mock.mock.calls.every(([path]) => path === '/api/meeting-participants/note' || path.startsWith('/api/feishu/contacts?'))).toBe(true);
});

it('allows a first explicit no-attendee-notification confirmation without inferring an empty meeting', async () => {
  show(); await open();
  const action = screen.getByRole('button', { name: '确认不通知参会人' });
  expect(action).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', { name: '本会议不通知参会人' }));
  expect(action).toBeEnabled(); fireEvent.click(action);
  await waitFor(() => expect(onConfirmed).toHaveBeenCalledOnce());
  expect(JSON.parse(puts()[0][1]!.body as string)).toEqual({ confirmed: true, task_id: 'task',
    evidence_revision: 'a'.repeat(64), confirmation_revision: 0, contacts: [] });
  expect(contactReads()).toHaveLength(0);
});

it('cannot use an empty list to bypass unavailable source evidence', async () => {
  current.can_confirm = false;
  show(); await open();
  expect(screen.getByRole('checkbox', { name: '本会议不通知参会人' })).toBeDisabled();
  expect(screen.getByRole('button', { name: '确认不通知参会人' })).toBeDisabled();
  expect(puts()).toHaveLength(0);
});

it('clears an existing meeting list only after explicit confirmation', async () => {
  current.confirmation = { revision: 2, status: 'confirmed', participants: [person] };
  show(); fireEvent.click(screen.getByRole('button', { name: '确认参会人' }));
  fireEvent.click(await screen.findByRole('button', { name: '移除参会人合成甲' }));
  expect(screen.getByRole('button', { name: '确认不通知参会人' })).toBeDisabled();
  attest(); fireEvent.click(screen.getByRole('button', { name: '确认不通知参会人' }));
  await waitFor(() => expect(onConfirmed).toHaveBeenCalledOnce());
  expect(JSON.parse(puts()[0][1]!.body as string).contacts).toEqual([]);
  expect(contactReads()).toHaveLength(0);
});

it('renews saved contacts through a fresh exact-ID selection, never a homonym', async () => {
  current.confirmation = { revision: 1, status: 'confirmed', participants: [person] };
  mock.mockImplementation(async (path, init) => {
    if (path.startsWith('/api/feishu/contacts?')) return { items: [{ open_id: 'ou_other', name: person.name, selection_token: 'other-token' }, { ...person, selection_token: 'fresh-token' }], has_more: false, page_token: '', selection_expires_in: 900 };
    if (init?.method === 'PUT') return { ...current, confirmation: { ...current.confirmation, revision: 2 } };
    return current;
  });
  show(); fireEvent.click(screen.getByRole('button', { name: '确认参会人' }));
  await screen.findByRole('button', { name: '移除参会人合成甲' });
  attest(); fireEvent.click(screen.getByRole('button', { name: '保存参会人确认' }));
  await waitFor(() => expect(puts()).toHaveLength(1));
  expect(JSON.parse(puts()[0][1]!.body as string).contacts).toEqual([{ open_id: person.open_id, selection_token: 'fresh-token' }]);
});

it('does not replace an unavailable confirmed ID with another person of the same name', async () => {
  current.confirmation = { revision: 1, status: 'confirmed', participants: [person] };
  mock.mockImplementation(async path => path.startsWith('/api/feishu/contacts?')
    ? { items: [{ open_id: 'ou_other', name: person.name, selection_token: 'other-token' }], has_more: false, page_token: '', selection_expires_in: 900 } : current);
  show(); fireEvent.click(screen.getByRole('button', { name: '确认参会人' }));
  await screen.findByRole('button', { name: '移除参会人合成甲' });
  attest(); fireEvent.click(screen.getByRole('button', { name: '保存参会人确认' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('未能核验已选联系人');
  expect(puts()).toHaveLength(0); expect(onConfirmed).not.toHaveBeenCalled();
});

it.each([409, 503])('blocks replay after a %i save error until explicit GET recovery', async status => {
  const original = mock.getMockImplementation()!;
  mock.mockImplementation(async (path, init) => { if (init?.method === 'PUT') throw new ApiError('lost or stale', status, {}); return original(path, init) });
  show(); await open(); await searchAndSelect(); attest();
  fireEvent.click(screen.getByRole('button', { name: '保存参会人确认' }));
  await screen.findByRole('alert');
  expect(screen.getByRole('button', { name: '确认不通知参会人' })).toBeDisabled();
  expect(onConfirmed).not.toHaveBeenCalled(); expect(puts()).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: '重新读取名单' }));
  await screen.findByText('本次确认名单（0人）');
  expect(puts()).toHaveLength(1);
});

it('ignores a late read after an account ABA change', async () => {
  let resolve!: (value: unknown) => void;
  mock.mockImplementation(() => new Promise(r => { resolve = r }));
  show(); fireEvent.click(screen.getByRole('button', { name: '确认参会人' }));
  act(() => useAuthStore.setState({ user: { id: 'other-owner' } as never }));
  act(() => useAuthStore.setState({ user: { id: 'synthetic-owner' } as never }));
  await act(async () => resolve(context()));
  expect(screen.queryByRole('dialog')).toBeNull(); expect(puts()).toHaveLength(0);
});

it('drops a route-scoped read on navigation', async () => {
  let resolve!: (value: unknown) => void;
  mock.mockImplementation(() => new Promise(r => { resolve = r }));
  show(); fireEvent.click(screen.getByRole('button', { name: '确认参会人' }));
  act(() => navigate('/notes/different-note'));
  await act(async () => resolve(context()));
  expect(screen.queryByRole('dialog')).toBeNull(); expect(puts()).toHaveLength(0);
});

it('rejects mismatched task identity and keeps writes unavailable', async () => {
  current.task_id = 'other-task';
  show(); fireEvent.click(screen.getByRole('button', { name: '确认参会人' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('资料未核验');
  expect(screen.getByRole('button', { name: '确认不通知参会人' })).toBeDisabled();
});

it('closes on Escape and restores focus to the entry button', async () => {
  const user = userEvent.setup(); show();
  await user.click(screen.getByRole('button', { name: '确认参会人' }));
  await screen.findByRole('dialog'); await user.keyboard('{Escape}');
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  await waitFor(() => expect(screen.getByRole('button', { name: '确认参会人' })).toHaveFocus());
});

it('ignores a save response after the route changes, including the footer callback', async () => {
  let resolve!: (value: unknown) => void;
  const original = mock.getMockImplementation()!;
  mock.mockImplementation((path, init) => init?.method === 'PUT' ? new Promise(r => { resolve = r }) : original(path, init));
  show(); await open(); await searchAndSelect(); attest(); fireEvent.click(screen.getByRole('button', { name: '保存参会人确认' }));
  await waitFor(() => expect(puts()).toHaveLength(1));
  act(() => navigate('/notes/different-note'));
  await act(async () => resolve({ ...context(), confirmation: { revision: 1, status: 'confirmed', participants: [person] } }));
  expect(onConfirmed).not.toHaveBeenCalled(); expect(screen.queryByRole('dialog')).toBeNull();
});
