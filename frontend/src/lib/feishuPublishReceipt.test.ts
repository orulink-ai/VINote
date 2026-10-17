import { beforeEach, expect, it, vi } from 'vitest'
import { deliveryById, deliveryByOperation } from './feishu'
import { newPublishDraft, persistPublishDraft, queryPublishReceipt, readPublishDraft, publishScope } from './feishuPublishReceipt'
const account = vi.hoisted(() => ({ owner: 'a', origin: '', listener: undefined as undefined | ((state: { user: { id: string } }) => void) }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: { getState: () => ({ user: { id: account.owner } }), subscribe: (listener: typeof account.listener) => { account.listener = listener; return () => {} } } }))
vi.mock('./runtimeConfig', () => ({ readRuntimeConfig: () => account.origin }))
vi.mock('./feishu', () => ({ deliveryById: vi.fn(), deliveryByOperation: vi.fn() }))
beforeEach(() => { localStorage.clear(); vi.resetAllMocks(); account.owner = 'a'; account.origin = '' })
const draft = () => newPublishDraft('a', 'note', { title: '原标题', content: '冻结正文', versionId: 'v2', revisionId: '2' }, { destination_config: { kind: 'personal' }, permission_policy: 'private', notify_self: false, groups: [] })
it('unknown survives storage reload and 404 without latest fallback or new request', async () => {
  const intent = { ...draft(), state: 'unknown' as const }; persistPublishDraft(intent)
  vi.mocked(deliveryByOperation).mockRejectedValue(new Error('404'))
  await expect(queryPublishReceipt(readPublishDraft('a', 'note')!)).rejects.toThrow('404')
  expect(readPublishDraft('a', 'note')).toMatchObject({ state: 'unknown', operationId: intent.operationId })
  expect(deliveryByOperation).toHaveBeenCalledWith(intent.operationId); expect(deliveryById).not.toHaveBeenCalled()
})
it('cannot edit a submitted version, recipient, or operation through draft persistence', () => {
  const intent = { ...draft(), state: 'unknown' as const }; persistPublishDraft(intent)
  expect(() => persistPublishDraft({ ...intent, options: { ...intent.options, notify_self: true } })).toThrow('不能改变')
  expect(() => persistPublishDraft({ ...intent, operationId: 'other' })).toThrow()
  expect(() => persistPublishDraft({ ...intent, state: 'draft' })).toThrow('不能改变')
})
it('only exact operation then job GET can acknowledge original intent', async () => {
  const intent = { ...draft(), state: 'unknown' as const }; persistPublishDraft(intent)
  const job = { id: 'job', operation_id: intent.operationId, status: 'queued' as const, document_url: '', recipients: {}, error: '' }
  vi.mocked(deliveryByOperation).mockResolvedValue(job)
  const result = await queryPublishReceipt(intent)
  vi.mocked(deliveryById).mockResolvedValue(job)
  await queryPublishReceipt(result.draft)
  expect(deliveryById).toHaveBeenCalledWith('job')
})
it('late owner switch cannot acknowledge another account or write its namespace', async () => {
  const intent = { ...draft(), state: 'unknown' as const }; persistPublishDraft(intent)
  vi.mocked(deliveryByOperation).mockImplementation(async () => { account.owner = 'b'; return { id: 'job', operation_id: intent.operationId, status: 'queued', document_url: '', recipients: {}, error: '' } })
  await expect(queryPublishReceipt(intent)).rejects.toThrow('账号')
  expect(localStorage.getItem('vinote:b:feishu-publish:note')).toBeNull()
  account.owner = 'a'; expect(readPublishDraft('a', 'note')?.state).toBe('unknown')
})
it('contacts including their display names and proofs stay immutable after dispatch', () => {
  const original = draft(); original.options.contacts = [{ open_id: 'ou_one', name: '原姓名', selection_token: 'proof', expiresAt: 123 }]
  const intent = { ...original, state: 'unknown' as const }; persistPublishDraft(intent)
  expect(() => persistPublishDraft({ ...intent, options: { ...intent.options, contacts: [{ ...intent.options.contacts![0], name: '新姓名' }] } })).toThrow('不能改变')
  expect(() => persistPublishDraft({ ...intent, options: { ...intent.options, contacts: [] } })).toThrow('不能改变')
})
it('a same-owner return after an identity change cannot acknowledge a previous-session response', async () => {
  const intent = { ...draft(), state: 'unknown' as const }; persistPublishDraft(intent)
  vi.mocked(deliveryByOperation).mockImplementation(async () => {
    account.owner = 'b'; account.listener?.({ user: { id: 'b' } })
    account.owner = 'a'; account.listener?.({ user: { id: 'a' } })
    return { id: 'job', operation_id: intent.operationId, status: 'queued', document_url: '', recipients: {}, error: '' }
  })
  await expect(queryPublishReceipt(intent)).rejects.toThrow('会话已变化')
  expect(readPublishDraft('a', 'note')?.state).toBe('unknown')
})

it('an Origin change invalidates a live scope and cannot reinterpret the frozen draft', () => {
  const intent = { ...draft(), state: 'unknown' as const }; persistPublishDraft(intent);
  const current = publishScope('a');
  account.origin = 'https://different-service.example';
  expect(current).toThrow('服务已变化');
  expect(() => readPublishDraft('a', 'note')).toThrow('其他服务');
  account.origin = '';
  expect(readPublishDraft('a', 'note')?.state).toBe('unknown');
});
it('recipient access policy is part of frozen input and cannot be backfilled or removed', () => {
  const original = draft();
  const intent = { ...original, state: 'unknown' as const }; persistPublishDraft(intent);
  expect(() => persistPublishDraft({ ...intent, options: { ...intent.options, recipient_access_policy: 'grant_view_and_notify' } })).toThrow('不能改变');
  localStorage.clear();
  const granted = { ...draft(), options: { ...original.options, recipient_access_policy: 'grant_view_and_notify' as const }, state: 'unknown' as const };
  persistPublishDraft(granted);
  expect(() => persistPublishDraft({ ...granted, options: original.options })).toThrow('不能改变');
});
