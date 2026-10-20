import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import type { LibraryNote } from '@/hooks/useLibraryNotes';
import type { PendingMeeting } from '@/lib/audioStorage';

const state = vi.hoisted(() => ({ owner: 'owner', notes: [] as LibraryNote[], recordings: [] as PendingMeeting[],
  api: vi.fn(), load: vi.fn(), list: vi.fn(), update: vi.fn(), publish: vi.fn(), download: vi.fn(), reveal: vi.fn(), native: false,
  workspace: { scope: 'personal' as const }, files: [] as Record<string, unknown>[], error: '' }));
vi.mock('@/lib/api', () => ({ apiJson: state.api }));
vi.mock('@/lib/audioStorage', () => ({ listPendingMeetings: state.list, updatePendingMeeting: state.update }));
vi.mock('@/lib/feishu', () => ({ publishToFeishu: state.publish }));
vi.mock('@/lib/i18n', () => ({ useI18n: () => ({ locale: 'zh-CN' }) }));
vi.mock('@/stores/authStore', () => ({ useAuthStore: Object.assign(
  (select: (s: { user: { id: string } }) => unknown) => select({ user: { id: state.owner } }),
  { getState: () => ({ user: { id: state.owner } }), subscribe: () => () => undefined },
) }));
vi.mock('@/stores/teamStore', () => ({ useTeamStore: Object.assign(() => ({ currentWorkspace: state.workspace, teams: [] }),
  { getState: () => ({ currentWorkspace: state.workspace }) }), getWorkspaceLabel: () => '个人空间' }));
vi.mock('@/stores/noteLibraryStore', () => ({ useNoteLibraryStore: () => ({ loading: false, error: state.error, loadNotes: state.load }) }));
vi.mock('@/stores/meetingRecorderStore', () => ({ isMeetingBusy: () => false, useMeetingRecorderStore: () => ({ phase: 'idle', recordingId: null }) }));
vi.mock('@/hooks/useLibraryNotes', async original => ({ ...await original<typeof import('@/hooks/useLibraryNotes')>(), useLibraryNotes: () => state.notes }));
vi.mock('@/components/ui/motion', () => ({ TextReveal: ({ children }: { children: ReactNode }) => <>{children}</>, ProcessingWave: () => null }));
vi.mock('@/components/MeetingRecorder/SavedRecordingChoice', () => ({ SavedRecordingChoice: () => null }));
vi.mock('@/components/MeetingRecorder/MicrophoneCheck', () => ({ MicrophoneCheck: () => null }));
vi.mock('@/components/MeetingRecorder/LocalRecordingPreview', () => ({ LocalRecordingPreview: ({ recording, onOpenNote }: { recording: PendingMeeting; onOpenNote: (id: string) => void }) =>
  <button onClick={() => onOpenNote(recording.noteId!)}>打开录制纪要</button> }));
vi.mock('@/lib/recordingDownload', async original => ({ ...await original<typeof import('@/lib/recordingDownload')>(), downloadOriginalFile: state.download }));
vi.mock('@/lib/originalLocation', () => ({ revealOriginalFile: state.reveal }));
vi.mock('@/lib/desktopMicrophonePermission', async original => ({ ...await original<typeof import('@/lib/desktopMicrophonePermission')>(), isTauriRuntime: () => state.native }));
import { FileLibrary } from './FileLibrary';
import { Meetings } from './Meetings';

const saved = '2026-10-19T12:00:00Z';
const note = (id: string, taskId: string, canonical?: string): LibraryNote => ({ id, taskId, title: '完全相同的纪要标题', content: '完整保存稿',
  sourceType: 'meeting_video', status: 'done', scope: 'personal', createdAt: saved, updatedAt: saved,
  meetingSource: canonical ? { ownerId: state.owner, canonicalTaskId: canonical, recordingStartedAt: '2026-10-19T07:41:05.355Z' } : undefined });
const file = () => ({ id: 'note:saved-a', filename: 'capture.webm', title: '完全不同的原件标题', purpose: 'meeting', category: 'video', media_type: 'video/webm',
  size_bytes: 1000, created_at: saved, available: true, note_id: 'saved-a', task_id: 'child-a', content_url: '/api/notes/saved-a/media', location: '当前电脑', can_delete: false, can_generate: false });
function Location() { const location = useLocation(); return <output aria-label="路由快照">{JSON.stringify({ path: location.pathname + location.search + location.hash, state: location.state })}</output>; }
function mount(path: string, routeState?: unknown) {
  return render(<MemoryRouter initialEntries={[{ ...new URL(path, 'https://vinote.invalid'), pathname: new URL(path, 'https://vinote.invalid').pathname,
    search: new URL(path, 'https://vinote.invalid').search, hash: new URL(path, 'https://vinote.invalid').hash, state: routeState }]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <Location /><Routes><Route path="/files" element={<FileLibrary />} /><Route path="/meetings" element={<Meetings />} />
      <Route path="/note/:id" element={<p>笔记详情</p>} /><Route path="/workspace/:id" element={<p>笔记详情</p>} /></Routes>
  </MemoryRouter>);
}
const snapshot = () => JSON.parse(screen.getByLabelText('路由快照').textContent!);
const noWrites = () => {
  expect(state.api.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true);
  expect(state.update).not.toHaveBeenCalled(); expect(state.publish).not.toHaveBeenCalled();
};
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear(); localStorage.clear(); state.owner = 'owner'; state.error = ''; state.native = false;
  state.notes = [note('canonical-note', 'canonical-a', 'canonical-a'), note('saved-a', 'child-a', 'canonical-a'), note('other-note', 'other-task', 'canonical-b')];
  state.recordings = []; state.files = [file()]; state.load.mockResolvedValue(undefined); state.list.mockImplementation(async () => state.recordings);
  state.download.mockResolvedValue('saved'); state.reveal.mockResolvedValue('shown');
  state.api.mockImplementation(async path => path === '/api/files' ? { items: state.files } : path.startsWith('/api/task/')
    ? { status: 'success', result: { title: '真实保存结果', markdown: '正文' } } : { diarization: { available: true } });
});
afterEach(cleanup);

it('routes a meeting original to its exact dossier and child, preserves hidden filters, and visibly returns to the same selected file', async () => {
  sessionStorage.setItem('vinote:view:owner:recordings-query', JSON.stringify('不匹配的旧搜索'));
  sessionStorage.setItem('vinote:view:owner:recordings-filter', JSON.stringify('未生成'));
  const filesPath = '/files?purpose=meeting&type=video&q=capture&file=note%3Asaved-a#chosen';
  mount(filesPath);
  await userEvent.click(await screen.findByRole('link', { name: '查看关联内容' }));
  await screen.findByText('已定位原会议档案和关联纪要。原筛选已保留。');
  expect(snapshot().path).toMatch(/^\/meetings\?/); expect(snapshot().path).toContain('locate_note=saved-a');
  expect(snapshot().path).toContain('locate_task=child-a'); expect(screen.queryByText('笔记详情')).not.toBeInTheDocument();
  const target = document.querySelector<HTMLElement>('[data-meeting-located="true"]')!;
  expect(target.closest('details')).toHaveAttribute('open'); expect(target).toHaveAttribute('aria-current', 'true');
  await waitFor(() => expect(target).toHaveFocus());
  expect(screen.getByText('2 份纪要')).toBeInTheDocument(); expect(document.querySelectorAll('[data-meeting-row-ids]')).toHaveLength(1);
  expect(screen.getByRole('textbox', { name: '搜索记录' })).toHaveValue('不匹配的旧搜索');
  expect(screen.getByRole('tab', { name: '未生成' })).toHaveAttribute('aria-selected', 'true');
  expect(JSON.parse(sessionStorage.getItem('vinote:view:owner:recordings-filter')!)).toBe('未生成');
  const back = screen.getByRole('link', { name: '返回文件库' }); expect(back).toHaveAttribute('href', filesPath);
  await userEvent.click(back); await screen.findByRole('dialog');
  expect(snapshot().path).toBe(filesPath);
  await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '关闭', exact: true }));
  expect(screen.getByRole('textbox', { name: '搜索文件名称' })).toHaveValue('capture');
  noWrites();
});

it('locates an unassociated historical meeting note in pending instead of making a meeting or opening its editor', async () => {
  state.notes = [note('saved-a', 'child-a'), note('other-note', 'other-task', 'canonical-b')];
  mount('/files?purpose=meeting&file=note%3Asaved-a');
  await userEvent.click(await screen.findByRole('link', { name: '查看关联内容' }));
  await screen.findByText('此纪要尚未关联到会议，已定位待归档内容。原筛选已保留。');
  expect(screen.getByRole('tab', { name: '待归档' })).toHaveAttribute('aria-selected', 'true');
  expect(document.querySelectorAll('[data-meeting-row-ids]')).toHaveLength(0);
  expect(document.querySelector('[data-meeting-located="true"]')).toBeInTheDocument(); noWrites();
});

it('keeps note-purpose files on their note detail route', async () => {
  state.files = [{ ...file(), purpose: 'note', source_type: 'video' }];
  mount('/files?purpose=note&file=note%3Asaved-a');
  await userEvent.click(await screen.findByRole('link', { name: '查看关联内容' }));
  expect(await screen.findByText('笔记详情')).toBeInTheDocument(); expect(snapshot().path).toBe('/note/saved-a'); noWrites();
});

it.each(['locate_note=saved-a&locate_task=other-task', 'locate_note=missing', 'locate_note=saved-a&locate_note=other-note', 'locate_note=..%2Fbad'])('fails recoverably for conflicting, absent or invalid identity without guessing from title (%s)', async target => {
  mount('/meetings?' + target + '&returnTo=' + encodeURIComponent('/files?purpose=meeting&type=video&q=capture&file=note%3Asaved-a'));
  await screen.findByRole('button', { name: '重新读取关联' });
  expect(document.querySelector('[data-meeting-located="true"]')).toBeNull();
  expect(screen.getByRole('link', { name: '返回文件库' })).toHaveAttribute('href', '/files?purpose=meeting&type=video&q=capture&file=note%3Asaved-a');
  expect(screen.queryByText('笔记详情')).not.toBeInTheDocument(); noWrites();
});

it('recovers a missing exact association by explicit re-read without a POST', async () => {
  state.notes = [];
  mount('/meetings?locate_note=saved-a');
  await screen.findByRole('button', { name: '重新读取关联' });
  state.load.mockImplementationOnce(async () => { state.notes = [note('saved-a', 'child-a', 'canonical-a')]; });
  await userEvent.click(screen.getByRole('button', { name: '重新读取关联' }));
  await screen.findByText('已定位原会议档案和关联纪要。原筛选已保留。');
  expect(document.querySelector('[data-meeting-located="true"]')).toBeInTheDocument(); noWrites();
});

it('supports state-only identities and validated sourceReturnTo while rejecting stale-owner state', async () => {
  const source = '/files?type=video&q=capture&purpose=meeting&file=note%3Asaved-a';
  const view = mount('/meetings?returnTo=https%3A%2F%2Fevil.invalid', { sourceReturnTo: source, meetingLocator: { ownerId: 'owner', noteId: 'saved-a', taskId: 'child-a' } });
  await screen.findByText('已定位原会议档案和关联纪要。原筛选已保留。');
  expect(screen.getByRole('link', { name: '返回文件库' })).toHaveAttribute('href', source);
  view.unmount();
  mount('/meetings?locate_note=saved-a', { returnTo: source, meetingLocator: { ownerId: 'another-owner', noteId: 'saved-a' } });
  await screen.findByText('定位标识无效或账号已变化，请返回文件库重新选择。');
  expect(document.querySelector('[data-meeting-located="true"]')).toBeNull(); noWrites();
});

it('does not invent a return link on a normal meeting visit or an invalid external source', async () => {
  mount('/meetings?returnTo=%2F%2Fevil.invalid');
  await waitFor(() => expect(state.load).toHaveBeenCalled());
  expect(screen.queryByRole('link', { name: '返回文件库' })).not.toBeInTheDocument();
});

it('waits for the owner collection read before resolving and focusing a deep link', async () => {
  let finish!: () => void; state.notes = [];
  state.load.mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }));
  mount('/meetings?locate_note=saved-a');
  expect(await screen.findByText('正在读取并定位关联会议…')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '重新读取关联' })).not.toBeInTheDocument();
  await act(async () => { state.notes = [note('saved-a', 'child-a', 'canonical-a')]; finish(); });
  await screen.findByText('已定位原会议档案和关联纪要。原筛选已保留。'); noWrites();
});

it('resolves IndexedDB recording identity without changing its original task or activating pending delivery', async () => {
  state.files = [];
  state.recordings = [{ id: 'capture-session', taskId: 'canonical-a', noteId: 'saved-a', ownerId: state.owner, workspace: state.workspace,
    options: { title: '录制原件' }, startedAt: saved, processingStatus: 'completed', recordingStatus: 'saved', feishuPending: true } as PendingMeeting];
  mount('/files?purpose=meeting&file=recording%3Acapture-session');
  await userEvent.click(await screen.findByRole('button', { name: '打开录制纪要' }));
  await screen.findByText('已定位原会议档案和关联纪要。原筛选已保留。');
  expect(snapshot().path).toContain('locate_recording=capture-session'); expect(snapshot().path).toContain('locate_task=canonical-a');
  expect(state.recordings[0].taskId).toBe('canonical-a'); noWrites();
});

it('uses derived playback only in the player while native download and reveal retain the original URL', async () => {
  state.native = true;
  mount('/files?purpose=meeting&file=note%3Asaved-a');
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByLabelText('原文件视频回放')).toHaveAttribute('src', '/api/notes/saved-a/media?playback=true');
  await userEvent.click(within(dialog).getByRole('button', { name: '另存为…' }));
  await waitFor(() => expect(state.download).toHaveBeenCalledWith('/api/notes/saved-a/media', 'capture.webm', expect.any(Function), expect.any(AbortSignal)));
  await userEvent.click(within(dialog).getByRole('button', { name: '在文件夹中显示' }));
  await waitFor(() => expect(state.reveal).toHaveBeenCalledWith('/api/notes/saved-a/media', expect.any(Function), expect.any(AbortSignal)));
  noWrites();
});
