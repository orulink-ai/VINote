import { expect, it } from 'vitest'
import { ApiError } from './api'
import { isRejectedVersionReceipt, meetingVersionDetails, readVersionReceipt, rejectedVersionParent, rejectedVersionSource, versionRejectionKey, versionSourceLocation, versionPreflightRejection } from './meetingVersionRecovery'

const rejected = { protocol: 1, status: 409, code: 'meeting_version_context_changed', message: '请重新核验。' }
const origin = 'https://original.invalid'
function receipt(extra = {}) {
  return { operationId: 'op', owner: 'owner', parentTaskId: 'parent', meetingVersion: true, meeting: true,
    independentGeneration: true, asrMode: 'reuse', summaryOnly: true, origin, modelConnection: { server_url: origin },
    meetingVersionContext: { protocol: 1, parent_task_id: 'parent', context_revision: 'a'.repeat(64),
      source: { version: 'b'.repeat(64), type: 'video', title: '原会议' } },
    modelName: 'original-luna', contentDepth: 'concise', presentation: 'text', createdAt: '2026-10-20T12:00:00Z',
    submissionState: 'not_accepted', preflightRejection: rejected, ...extra }
}

it.each(['accepted', 'reserved'])('preserves %s arriving between the audit and final receipt read', state => {
  const raw = JSON.stringify(receipt({ submissionState: 'unknown' }))
  const accepted = JSON.stringify(receipt({ submissionState: state, id: 'real-child' }))
  let reads = 0
  const storage = { getItem: (key: string) => key === versionRejectionKey('owner', 'op')
    ? JSON.stringify({ pending: raw, rejection: rejected }) : ++reads === 1 ? raw : accepted }
  expect(readVersionReceipt(storage, 'owner', 'op')).toMatchObject({ submissionState: state, id: 'real-child' })
})

it.each([{ pending: 'different' }, { rejection: { ...rejected, code: 'source_changed' } }])(
  'keeps an unmatched or unrecognized independent audit query-only: %j', extra => {
    const raw = JSON.stringify(receipt({ submissionState: 'unknown' }))
    const audit = JSON.stringify({ pending: raw, rejection: rejected, ...extra })
    expect(readVersionReceipt({ getItem: key => key === versionRejectionKey('owner', 'op') ? audit : raw }, 'owner', 'op'))
      .toMatchObject({ submissionState: 'unknown' })
  })

it('retains the exact source detail, transcript view and filtered parent after audit restoration', () => {
  const parent = '/meetings?q=kept&project=active'
  const detail = '/note/selected-note?' + new URLSearchParams({ view: 'transcript', returnTo: parent }) + '#part'
  const source = versionSourceLocation('selected-note', 'parent', [detail])
  const saved = receipt({ summaryNoteId: 'selected-note', ...source })
  expect(rejectedVersionSource(saved as never)).toBe(detail)
  expect(rejectedVersionParent(saved as never, '/tasks')).toBe(parent)
})

it('keeps a task detail and its validated state-only filtered parent', () => {
  const detail = '/generate?meeting=1&task=parent&view=transcript#source'
  const source = versionSourceLocation(undefined, 'parent', [detail], '/files?type=video&q=kept')
  const saved = receipt(source)
  expect(rejectedVersionSource(saved as never)).toBe(detail)
  expect(rejectedVersionParent(saved as never, '/tasks')).toBe('/files?type=video&q=kept')
})

it.each(['https://evil.invalid/note/selected-note', '//evil.invalid/note/selected-note',
  '/note/other?view=transcript', '/generate?meeting=1&task=parent&operation=active'])('does not restore an unbound source URL: %s', detail => {
  expect(versionSourceLocation('selected-note', 'parent', [detail], 'https://evil.invalid')).toEqual({})
})

it('removes an unsafe nested parent while preserving the bound detail view', () => {
  const source = versionSourceLocation('selected-note', 'parent', ['/note/selected-note?view=transcript&returnTo=https://evil.invalid'])
  expect(source).toEqual({ sourceDetailUrl: '/note/selected-note?view=transcript', sourceParentUrl: undefined })
})

it.each(['meeting_version_context_changed', 'meeting_version_selection_changed'])('recognizes only the pre-reservation contract %s', code => {
  expect(versionPreflightRejection(new ApiError('safe', 409, { code, message: '重新核验。' })))
    .toMatchObject({ protocol: 1, status: 409, code })
})

it.each([
  new Error('network'), { status: 409, detail: rejected },
  new ApiError('missing', 404, { code: rejected.code, message: 'missing' }),
  new ApiError('failed', 500, { code: rejected.code, message: 'failed' }),
  new ApiError('unknown', 409, { code: 'meeting_version_operation_changed', message: 'unknown' }),
  new ApiError('reserved', 409, { code: 'source_changed', message: 'after reserve' }),
  new ApiError('shape', 409, { code: rejected.code }),
  new ApiError('shape', 409, { code: rejected.code, message: '', task_id: 'child' }),
  new ApiError('shape', 409, [{ code: rejected.code, message: 'bad' }]),
])('does not turn ambiguous errors into nonacceptance: %j', error => {
  expect(versionPreflightRejection(error)).toBeNull()
})

it.each([{ owner: 'other' }, { id: 'accepted-child' }, { submissionState: 'accepted' },
  { submissionState: 'unknown' }, { submissionState: 'reserved' }, { summaryNoteId: {} },
  { task_id: 'accepted-child' }, { state: 'accepted' },
  { preflightRejection: { ...rejected, task_id: 'child' } },
  { preflightRejection: { ...rejected, code: 'unknown' } }])('rejects unbound/nonterminal audit metadata %j', extra => {
  expect(isRejectedVersionReceipt(receipt(extra), 'owner')).toBe(false)
})

it('labels only a valid frozen choice and submission time, never a global preference', () => {
  expect(isRejectedVersionReceipt(receipt(), 'owner')).toBe(true)
  expect(meetingVersionDetails(receipt(), 'owner')).toEqual({ title: '原会议', model: 'original-luna',
    depth: 'concise', presentation: 'text', createdAt: '2026-10-20T12:00:00Z', reuse: true })
})

it.each([{ owner: 'other' }, { createdAt: 'invalid' }, { presentation: ['text'] },
  { contentDepth: ['concise'] }, { modelName: '\ninternal' }, { origin: 'https://changed.invalid' }])(
  'does not present malformed or mismatched receipts as verified version metadata %j', extra => {
    expect(meetingVersionDetails(receipt(extra), 'owner')).toBeNull()
  })
