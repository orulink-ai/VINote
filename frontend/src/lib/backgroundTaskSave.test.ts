import { beforeEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({ owner: 'alice', origin: 'https://local.invalid', listeners: new Set<(value: {user: {id: string}}) => void>(), api: vi.fn() }));
vi.mock('@/stores/authStore', () => ({ useAuthStore: { getState: () => ({ user: { id: state.owner } }), subscribe: (listener: (value: {user: {id: string}}) => void) => { state.listeners.add(listener); return () => state.listeners.delete(listener); } } }));
vi.mock('./api', () => ({ apiJson: state.api }));
vi.mock('./runtimeConfig', () => ({ readRuntimeConfig: () => state.origin }));
import { backgroundSaveCompletedTask } from './backgroundTaskSave';
const receipt = (patch = {}) => ({ id: 'task-1', operationId: 'op-1', submissionState: 'accepted', meeting: false, workspace: { scope: 'personal' }, sourceType: 'webpage', sourceUrl: 'https://x.com/a/status/123', ...patch });
const saveReceipt = (value = receipt(), owner = 'alice') => localStorage.setItem(`vinote:source-receipt:${owner}:op-1`, JSON.stringify(value));
const result = { task_id: 'task-1', status: 'success', result: { task_id: 'task-1', title: '原结果标题', markdown: '原结果正文' } };
const note = { id: 'note-1', task_id: 'task-1', scope: 'personal', team_id: null, title: '已保存标题', content: '已保存正文' };
function owner(value: string) { state.owner = value; state.listeners.forEach(listener => listener({ user: { id: value } })); }
beforeEach(() => { owner('alice'); state.origin = 'https://local.invalid'; localStorage.clear(); state.api.mockReset(); });
it('saves the exact successful result to receipt workspace without generating or publishing', async () => {
  saveReceipt(); state.api.mockResolvedValueOnce(result).mockResolvedValueOnce([]).mockResolvedValueOnce(note);
  expect(await backgroundSaveCompletedTask('alice', 'task-1')).toBe('note-1');
  expect(state.api.mock.calls[1][0]).toBe('/api/notes?scope=personal&task_id=task-1');
  const body = JSON.parse(state.api.mock.calls[2][1].body);
  expect(body).toEqual({ title: '原结果标题', content: '原结果正文', video_url: 'https://x.com/a/status/123', task_id: 'task-1', source_type: 'webpage', scope: 'personal', team_id: null, status: 'done' });
  expect(state.api.mock.calls.map(([path]) => path)).toEqual(['/api/task/task-1', '/api/notes?scope=personal&task_id=task-1', '/api/notes']);
});
it('returns an existing edited note without POST or PATCH', async () => {
  saveReceipt(); state.api.mockResolvedValueOnce(result).mockResolvedValueOnce([note]);
  expect(await backgroundSaveCompletedTask('alice', 'task-1')).toBe('note-1');
  expect(state.api).toHaveBeenCalledTimes(2);
});
it('deduplicates concurrent invocations and preserves original team destination', async () => {
  saveReceipt(receipt({ workspace: { scope: 'team', teamId: 'team-a' }, meeting: true, sourceType: 'video' }));
  state.api.mockResolvedValueOnce(result).mockResolvedValueOnce([]).mockResolvedValueOnce({ ...note, scope: 'team', team_id: 'team-a' });
  expect(await Promise.all([backgroundSaveCompletedTask('alice', 'task-1'), backgroundSaveCompletedTask('alice', 'task-1')])).toEqual(['note-1', 'note-1']);
  expect(state.api).toHaveBeenCalledTimes(3);
  const body = JSON.parse(state.api.mock.calls[2][1].body);
  expect(body).toMatchObject({ scope: 'team', team_id: 'team-a', source_type: 'meeting_video' });
});
it.each([{ submissionState: 'unknown' }, { sourceType: undefined }, { workspace: { scope: 'team' } }, { owner: 'bob' }, { summaryOnly: true }])('does not save insufficient or nonaccepted receipt %j', async patch => {
  saveReceipt(receipt(patch)); expect(await backgroundSaveCompletedTask('alice', 'task-1')).toBeNull(); expect(state.api).not.toHaveBeenCalled();
});
it('does not read another owner receipt or guess missing receipt', async () => {
  saveReceipt(receipt(), 'bob'); expect(await backgroundSaveCompletedTask('alice', 'task-1')).toBeNull(); expect(state.api).not.toHaveBeenCalled();
});
it('rejects conflicting destinations rather than guessing the current workspace', async () => {
  saveReceipt(); localStorage.setItem('vinote:import-receipt:alice:note', JSON.stringify(receipt({workspace: {scope: 'team', teamId: 'other'}})));
  expect(await backgroundSaveCompletedTask('alice', 'task-1')).toBeNull(); expect(state.api).not.toHaveBeenCalled();
});
it.each([{...result, status: 'failed'}, {...result, result: {...result.result, task_id: 'other'}}, {...result, result: {...result.result, markdown: ''}}])('rejects incomplete or wrong task result', async response => {
  saveReceipt(); state.api.mockResolvedValueOnce(response); expect(await backgroundSaveCompletedTask('alice', 'task-1')).toBeNull(); expect(state.api).toHaveBeenCalledTimes(1);
});
it('rejects A to B to A while the task read is pending', async () => {
  saveReceipt(); let finish!: (value: unknown) => void; state.api.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const pending = backgroundSaveCompletedTask('alice', 'task-1'); owner('bob'); owner('alice'); finish(result);
  expect(await pending).toBeNull(); expect(state.api).toHaveBeenCalledTimes(1);
});
it('does not recreate a previously saved note if later removed', async () => {
  saveReceipt(); state.api.mockResolvedValueOnce(result).mockResolvedValueOnce([]).mockResolvedValueOnce(note);
  await backgroundSaveCompletedTask('alice', 'task-1');
  state.api.mockReset().mockResolvedValueOnce(result).mockResolvedValueOnce([]);
  expect(await backgroundSaveCompletedTask('alice', 'task-1')).toBeNull(); expect(state.api).toHaveBeenCalledTimes(2);
});
it('a changed receipt during lookup cannot save in its old workspace', async () => {
  saveReceipt(); state.api.mockImplementation(async () => { saveReceipt(receipt({workspace: {scope:'team',teamId:'new'}})); return result; });
  expect(await backgroundSaveCompletedTask('alice', 'task-1')).toBeNull(); expect(state.api).toHaveBeenCalledTimes(1);
});

it('ignores a damaged unrelated receipt rather than blocking every completed task', async () => {
  localStorage.setItem('vinote:source-receipt:alice:damaged', 'not json'); saveReceipt();
  state.api.mockResolvedValueOnce(result).mockResolvedValueOnce([note]);
  expect(await backgroundSaveCompletedTask('alice', 'task-1')).toBe('note-1');
});

it('does not override a damaged exact-task recovery receipt with another slot', async () => {
  localStorage.setItem('vinote:source-task-receipt:alice:task-1', 'not json'); saveReceipt();
  expect(await backgroundSaveCompletedTask('alice', 'task-1')).toBeNull();
  expect(state.api).not.toHaveBeenCalled();
});
