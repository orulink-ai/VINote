import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AssociateMeetingDialog } from './AssociateMeetingDialog';
import { MeetingWorkbench } from './MeetingWorkbench';
import type { LibraryNote } from '@/hooks/useLibraryNotes';

const state = vi.hoisted(() => ({ owner: 'owner', api: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiJson: state.api }));
vi.mock('@/stores/authStore', () => ({ useAuthStore: Object.assign(
  (select: (s: { user: { id: string } }) => unknown) => select({ user: { id: state.owner } }),
  { getState: () => ({ user: { id: state.owner } }) },
) }));
vi.mock('./LocalRecordingPreview', () => ({ LocalRecordingPreview: () => null }));

const noteId = '11111111-1111-4111-8111-111111111111';
const target = { canonical_task_id: '22222222-2222-4222-8222-222222222222', source_version: 'a'.repeat(64), media_kind: 'video', recording_started_at: '2026-10-19T07:41:05.355Z' };
const empty = () => ({ note_id: noteId, revision: 0, source_version: null, meeting_source: null });
const linked = () => ({ note_id: noteId, revision: 1, source_version: target.source_version, meeting_source: { owner_id: 'owner', canonical_task_id: target.canonical_task_id } });
const puts = () => state.api.mock.calls.filter(([, init]) => init?.method === 'PUT');
const close = vi.fn(), associated = vi.fn();
function show() { return render(<AssociateMeetingDialog noteId={noteId} noteTitle="待关联旧稿" ownerId="owner" onClose={close} onAssociated={associated} />); }
async function choose() {
  const select = await screen.findByRole('combobox', { name: '选择原始录制' });
  await userEvent.selectOptions(select, target.canonical_task_id);
}
beforeEach(() => {
  state.owner = 'owner'; sessionStorage.clear(); vi.clearAllMocks();
  state.api.mockImplementation(async (path, init) => path.endsWith('/targets') ? { targets: [target] } : init?.method === 'PUT' ? linked() : empty());
});
afterEach(cleanup);

it('requires explicit selection, freezes the exact canonical/hash/revision, and submits only once', async () => {
  show(); await screen.findByRole('combobox');
  expect(screen.getByRole('button', { name: '确认关联' })).toBeDisabled();
  expect(puts()).toHaveLength(0);
  await choose();
  const confirm = screen.getByRole('button', { name: '确认关联' });
  fireEvent.click(confirm); fireEvent.click(confirm);
  await waitFor(() => expect(associated).toHaveBeenCalledOnce());
  expect(puts()).toHaveLength(1);
  expect(puts()[0][0]).toBe(`/api/meeting-source-links/${noteId}`);
  expect(JSON.parse(puts()[0][1].body)).toEqual({ confirmed: true, canonical_task_id: target.canonical_task_id, source_version: target.source_version, expected_revision: 0 });
  expect(close).toHaveBeenCalledOnce();
  expect(state.api.mock.calls.every(([path]) => path.startsWith('/api/meeting-source-links/'))).toBe(true);
});

it('recovers an unknown write by GET without repeating the mutation', async () => {
  let accepted = false;
  state.api.mockImplementation(async (path, init) => {
    if (path.endsWith('/targets')) return { targets: [target] };
    if (init?.method === 'PUT') { accepted = true; throw new TypeError('transport'); }
    return accepted ? linked() : empty();
  });
  show(); await choose(); await userEvent.click(screen.getByRole('button', { name: '确认关联' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('关联结果尚未确认');
  expect(associated).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: '核验关联结果' }));
  expect(associated).toHaveBeenCalledOnce(); expect(puts()).toHaveLength(1);
});

it('keeps an unread unknown association query-only even when GET has no result yet', async () => {
  state.api.mockImplementation(async (path, init) => {
    if (path.endsWith('/targets')) return { targets: [target] };
    if (init?.method === 'PUT') throw new Error('unknown');
    return empty();
  });
  show(); await choose(); await userEvent.click(screen.getByRole('button', { name: '确认关联' }));
  await userEvent.click(await screen.findByRole('button', { name: '核验关联结果' }));
  expect(screen.getByRole('alert')).toHaveTextContent('暂未读取到确认的关联');
  expect(puts()).toHaveLength(1); expect(associated).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: '确认关联' })).not.toBeInTheDocument();
});

it('does not offer rebinding when the server has a trusted or explicit existing relation', async () => {
  state.api.mockImplementation(async path => path.endsWith('/targets') ? { targets: [target] } : linked());
  show(); await screen.findByText('此稿已关联到会议，无需重复归档。');
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument(); expect(puts()).toHaveLength(0);
});

it('reports candidate read failure instead of showing a false empty collection', async () => {
  state.api.mockRejectedValue(new Error('offline')); show();
  expect(await screen.findByRole('alert')).toHaveTextContent('无法读取');
  expect(screen.queryByText(/没有可核验的原始录制/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '确认关联' })).toBeDisabled(); expect(puts()).toHaveLength(0);
});

it('shows unknown capture time without a fabricated note title or saved date', async () => {
  state.api.mockImplementation(async path => path.endsWith('/targets') ? { targets: [{ ...target, recording_started_at: null, display_name: '待生成纪要' }] } : empty());
  show(); await screen.findByRole('combobox');
  expect(screen.getByRole('option', { name: /录制时间未记录 · 录屏/ })).toBeInTheDocument();
  expect(screen.queryByRole('option', { name: /待生成纪要/ })).not.toBeInTheDocument();
});

it('ignores completion after the account changes and does not refresh the new account', async () => {
  let finish!: (value: unknown) => void;
  state.api.mockImplementation(async (path, init) => path.endsWith('/targets') ? { targets: [target] }
    : init?.method === 'PUT' ? new Promise(resolve => { finish = resolve; }) : empty());
  show(); await choose(); fireEvent.click(screen.getByRole('button', { name: '确认关联' }));
  state.owner = 'other';
  await act(async () => { finish(linked()); });
  expect(associated).not.toHaveBeenCalled(); expect(close).not.toHaveBeenCalled(); expect(puts()).toHaveLength(1);
});

it('exposes association only for pending device note records and closes on route changes', async () => {
  const note: LibraryNote = { id: noteId, title: '旧稿', content: '正文', sourceType: 'meeting_video', status: 'done', scope: 'personal', createdAt: '2026-10-20T00:00:00Z', updatedAt: '2026-10-20T00:00:00Z', archived: true };
  const props = { notes: [note], recordings: [], loading: false, onOpenNote: vi.fn(), onDeleted: vi.fn(), onAssociated: associated, view: 'pending' as const };
  const view = render(<MeetingWorkbench {...props} associationContextKey="first-route" />);
  await userEvent.click(screen.getByRole('button', { name: '关联《旧稿》到会议' }));
  expect(screen.getByRole('dialog', { name: '关联到会议' })).toBeInTheDocument();
  view.rerender(<MeetingWorkbench {...props} associationContextKey="second-route" />);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  view.rerender(<MeetingWorkbench {...props} associationContextKey="first-route" />);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); expect(puts()).toHaveLength(0);
});

it('moves a confirmed source projection into the same dossier as future versions without rewriting task identities', () => {
  const source = { ownerId: 'owner', canonicalTaskId: target.canonical_task_id, recordingStartedAt: target.recording_started_at };
  const original: LibraryNote = { id: 'original-note', title: '原录制纪要', content: '正文', taskId: target.canonical_task_id, meetingSource: source,
    sourceType: 'meeting_video', status: 'done', scope: 'personal', createdAt: '2026-10-19T12:00:00Z', updatedAt: '2026-10-19T12:00:00Z' };
  const manual = { ...original, id: noteId, title: '旧稿', taskId: 'historical-task', meetingSource: undefined, archived: true };
  const props = { recordings: [], loading: false, onOpenNote: vi.fn(), onDeleted: vi.fn(), onAssociated: associated };
  const view = render(<MeetingWorkbench {...props} notes={[original, manual]} view="pending" />);
  expect(screen.getByRole('button', { name: '关联《旧稿》到会议' })).toBeInTheDocument();
  const associatedManual = { ...manual, meetingSource: source };
  const child = { ...original, id: 'new-version', taskId: 'new-child', archived: false };
  view.rerender(<MeetingWorkbench {...props} notes={[original, associatedManual, child]} view="meetings" />);
  expect(document.querySelectorAll('[data-meeting-row-ids]')).toHaveLength(1);
  expect(screen.getByText('3 份纪要')).toBeInTheDocument();
  expect(associatedManual.taskId).toBe('historical-task'); expect(original.taskId).toBe(target.canonical_task_id);
  expect(puts()).toHaveLength(0);
});

it('focuses the loaded selection, explains disabled confirmation and connects an error to the field', async () => {
  state.api.mockImplementation(async (path, init) => {
    if (path.endsWith('/targets')) return { targets: [target] };
    if (init?.method === 'PUT') throw Object.assign(new Error('此稿已有可信的其他会议来源，不能覆盖'), { status: 409 });
    return empty();
  });
  show();
  const select = await screen.findByRole('combobox', { name: '选择原始录制' });
  await waitFor(() => expect(select).toHaveFocus());
  expect(select).toHaveAccessibleDescription('请选择与此稿对应的原始录制，再确认关联。尚未确认时不会归档。');
  expect(select).toBeRequired();
  await choose(); await userEvent.click(screen.getByRole('button', { name: '确认关联' }));
  const error = await screen.findByRole('alert');
  expect(select).toHaveAttribute('aria-invalid', 'true');
  expect(select.getAttribute('aria-describedby')).toContain(error.id);
  expect(select).toHaveAccessibleDescription(/不能覆盖/); expect(puts()).toHaveLength(1);
});

it('keeps a user-selected focus position while delayed candidate reads complete', async () => {
  let resolveTargets!: (value: unknown) => void;
  state.api.mockImplementation(async path => path.endsWith('/targets') ? new Promise(resolve => { resolveTargets = resolve; }) : empty());
  show();
  screen.getByRole('button', { name: '关闭' }).focus();
  await act(async () => { resolveTargets({ targets: [target] }); });
  expect(screen.getByRole('button', { name: '关闭' })).toHaveFocus();
  expect(screen.getByRole('combobox')).not.toHaveFocus();
});

it('restores keyboard focus to the pending action after Escape without submitting', async () => {
  const note: LibraryNote = { id: noteId, title: '旧稿', content: '正文', sourceType: 'meeting_video', status: 'done', scope: 'personal', createdAt: '2026-10-20T00:00:00Z', updatedAt: '2026-10-20T00:00:00Z' };
  render(<MeetingWorkbench notes={[note]} recordings={[]} loading={false} onOpenNote={vi.fn()} onDeleted={vi.fn()} onAssociated={associated} view="pending" />);
  const trigger = screen.getByRole('button', { name: '关联《旧稿》到会议' });
  await userEvent.click(trigger);
  await screen.findByRole('combobox'); await userEvent.keyboard('{Escape}');
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  await waitFor(() => expect(trigger).toHaveFocus()); expect(puts()).toHaveLength(0);
});

it('announces a confirmed association and focuses the pending tab when the old trigger disappears', async () => {
  const manual: LibraryNote = { id: noteId, title: '旧稿', content: '正文', sourceType: 'meeting_video', status: 'done', scope: 'personal', createdAt: '2026-10-20T00:00:00Z', updatedAt: '2026-10-20T00:00:00Z' };
  const props = { recordings: [], loading: false, onOpenNote: vi.fn(), onDeleted: vi.fn(), view: 'pending' as const };
  const done = vi.fn(async () => { view.rerender(<MeetingWorkbench {...props} notes={[{ ...manual, meetingSource: { ownerId: 'owner', canonicalTaskId: target.canonical_task_id } }]} onAssociated={done} />); });
  const view = render(<MeetingWorkbench {...props} notes={[manual]} onAssociated={done} />);
  await userEvent.click(screen.getByRole('button', { name: '关联《旧稿》到会议' }));
  await choose(); await userEvent.click(screen.getByRole('button', { name: '确认关联' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('status')).toHaveTextContent('关联已确认');
  await waitFor(() => expect(screen.getByRole('tab', { name: '待归档' })).toHaveFocus());
  expect(puts()).toHaveLength(1); expect(done).toHaveBeenCalledOnce();
});

it('announces an in-flight mutation and disables confirmation before the network result', async () => {
  let finish!: (value: unknown) => void;
  state.api.mockImplementation(async (path, init) => path.endsWith('/targets') ? { targets: [target] }
    : init?.method === 'PUT' ? new Promise(resolve => { finish = resolve; }) : empty());
  show(); await choose(); await userEvent.click(screen.getByRole('button', { name: '确认关联' }));
  expect(screen.getByRole('status')).toHaveTextContent('正在保存关联');
  expect(screen.getByRole('button', { name: '正在关联…' })).toBeDisabled();
  expect(screen.getByRole('combobox')).toBeDisabled();
  await act(async () => { finish(linked()); });
  expect(puts()).toHaveLength(1);
});
