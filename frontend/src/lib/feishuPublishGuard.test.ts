import { beforeEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({ owner: 'a', listeners: [] as Array<(state: { user: { id: string } }) => void>, read: vi.fn(), api: vi.fn() }));
vi.mock('@/stores/authStore', () => ({ useAuthStore: { getState: () => ({ user: { id: state.owner } }), subscribe: (callback: (value: { user: { id: string } }) => void) => { state.listeners.push(callback); return () => {}; } } }));
vi.mock('./api', () => ({ apiJson: state.api }));
vi.mock('./connectorPlugins', () => ({ createConnectorPluginStore: () => ({ read: state.read }) }));
import { publishToFeishu, deliveryById, verifyDeliveryPermissions } from './feishu';
const changeOwner = (owner: string) => { state.owner = owner; state.listeners.forEach(callback => callback({ user: { id: owner } })); };
beforeEach(() => { changeOwner('a'); vi.clearAllMocks(); });
it.each([['b'], ['b', 'a']])('blocks dispatch after asynchronous account changes %j', async (...owners) => {
  let resolve!: (value: { installed: boolean; enabled: boolean }) => void;
  state.read.mockReturnValue(new Promise(done => { resolve = done; }));
  const pending = publishToFeishu('note', 'title', 'body');
  const rejected = expect(pending).rejects.toThrow(/账号/);
  owners.forEach(changeOwner);
  resolve({ installed: true, enabled: true });
  await rejected;
  expect(state.api).not.toHaveBeenCalled();
});
it('publishes once for the unchanged account after installed state resolves', async () => {
  state.read.mockResolvedValue({ installed: true, enabled: true });
  state.api.mockResolvedValue({ id: 'job' });
  await publishToFeishu('note', 'title', 'body');
  expect(state.api).toHaveBeenCalledTimes(1);
});
it('rejects a stale response after a dispatched request without submitting it again', async () => {
  state.read.mockResolvedValue({ installed: true, enabled: true });
  let resolve!: (value: { id: string }) => void;
  state.api.mockReturnValue(new Promise(done => { resolve = done; }));
  const pending = publishToFeishu('note', 'title', 'body');
  const rejected = expect(pending).rejects.toThrow(/账号/);
  await vi.waitFor(() => expect(state.api).toHaveBeenCalledTimes(1));
  changeOwner('b'); changeOwner('a');
  resolve({ id: 'job' });
  await rejected;
  expect(state.api).toHaveBeenCalledTimes(1);
});
it('queries only the exact job without browser cache and forwards cancellation', async () => {
  const controller = new AbortController();
  state.api.mockResolvedValue({ id: 'job' });
  await deliveryById('job', controller.signal);
  expect(state.api).toHaveBeenCalledWith('/api/feishu/deliveries/by-id/job', { cache: 'no-store', signal: controller.signal });
});

import { beginPublishAttempt, newPublishDraft, persistPublishDraft, readPublishDraft, restoreUndispatchedDraft } from './feishuPublishReceipt';
const makeIntent = () => {
  const intent = newPublishDraft('a', 'note', { title: 'title', content: 'body' }, { destination_config: { kind: 'personal' }, permission_policy: 'private', notify_self: false, groups: [] });
  persistPublishDraft(intent);
  return intent;
};
it('a plugin preflight rejection has zero POST and can restore only its own live attempt', async () => {
  localStorage.clear();
  const draft = makeIntent(), attempt = beginPublishAttempt(draft);
  persistPublishDraft({ ...draft, state: 'unknown' });
  state.read.mockResolvedValue({ installed: true, enabled: false });
  await expect(publishToFeishu('note', 'title', 'body', false, { operation_id: draft.operationId }, attempt)).rejects.toThrow('启用');
  expect(state.api).not.toHaveBeenCalled();
  expect(restoreUndispatchedDraft({ operationId: draft.operationId })).toBeNull();
  expect(readPublishDraft('a', 'note')?.state).toBe('unknown');
  expect(restoreUndispatchedDraft(attempt)).toMatchObject({ state: 'draft', operationId: draft.operationId });
  expect(restoreUndispatchedDraft(attempt)).toBeNull();
});
it('network failures after POST remain unknown even for a live attempt', async () => {
  localStorage.clear();
  const draft = makeIntent(), attempt = beginPublishAttempt(draft);
  persistPublishDraft({ ...draft, state: 'unknown' });
  state.read.mockResolvedValue({ installed: true, enabled: true });
  state.api.mockRejectedValue(new Error('network unknown'));
  await expect(publishToFeishu('note', 'title', 'body', false, { operation_id: draft.operationId }, attempt)).rejects.toThrow('network');
  expect(state.api).toHaveBeenCalledTimes(1);
  expect(restoreUndispatchedDraft(attempt)).toBeNull();
  expect(readPublishDraft('a', 'note')?.state).toBe('unknown');
});
it('input validation refuses before POST and produces only current-attempt evidence', async () => {
  localStorage.clear();
  const draft = makeIntent(), attempt = beginPublishAttempt(draft);
  persistPublishDraft({ ...draft, state: 'unknown' });
  state.read.mockResolvedValue({ installed: true, enabled: true });
  await expect(publishToFeishu('note', '', 'body', false, { operation_id: draft.operationId }, attempt)).rejects.toThrow('尚未提交');
  expect(state.api).not.toHaveBeenCalled();
  expect(restoreUndispatchedDraft(attempt)?.state).toBe('draft');
});

it('a historical unknown cannot mint a fresh attempt to unlock itself', () => {
  localStorage.clear();
  const draft = makeIntent();
  persistPublishDraft({ ...draft, state: 'unknown' });
  expect(() => beginPublishAttempt(draft)).toThrow('只有当前未提交草稿');
  expect(readPublishDraft('a', 'note')?.state).toBe('unknown');
});
it('leaving the panel during plugin preflight prevents POST and keeps the unknown intent', async () => {
  localStorage.clear();
  const draft = makeIntent(); let current = true;
  const attempt = beginPublishAttempt(draft, () => { if (!current) throw new Error('面板已变化'); });
  persistPublishDraft({ ...draft, state: 'unknown' });
  let finish!: (value: { installed: boolean; enabled: boolean }) => void;
  state.read.mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const pending = publishToFeishu('note', 'title', 'body', false, { operation_id: draft.operationId }, attempt);
  const rejected = expect(pending).rejects.toThrow('面板已变化');
  current = false; finish({ installed: true, enabled: true });
  await rejected;
  expect(state.api).not.toHaveBeenCalled();
  expect(readPublishDraft('a', 'note')?.state).toBe('unknown');
});

it('permission verification calls only the exact no-body no-store endpoint', async () => {
  state.api.mockResolvedValue({ id: 'job/one' });
  await verifyDeliveryPermissions('job/one');
  expect(state.api).toHaveBeenCalledTimes(1);
  expect(state.api).toHaveBeenCalledWith('/api/feishu/deliveries/job%2Fone/verify-permissions', { method: 'POST', cache: 'no-store' });
  expect(state.read).not.toHaveBeenCalled();
});
it('permission verification rejects a different job without fallback or retry', async () => {
  state.api.mockResolvedValue({ id: 'other' });
  await expect(verifyDeliveryPermissions('job')).rejects.toThrow('不属于原发布任务');
  expect(state.api).toHaveBeenCalledTimes(1);
});
it('a stale verification response cannot settle a different identity', async () => {
  let finish!: (job: { id: string }) => void;
  state.api.mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const pending = verifyDeliveryPermissions('job');
  const rejected = expect(pending).rejects.toThrow('账号');
  changeOwner('b'); changeOwner('a'); finish({ id: 'job' });
  await rejected;
  expect(state.api).toHaveBeenCalledTimes(1);
});
