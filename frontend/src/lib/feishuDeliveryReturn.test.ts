import { beforeEach, expect, it, vi } from 'vitest'
import { feishuSettingsReturn, takeFeishuDeliveryReturn } from './feishuDeliveryReturn'
const scope = vi.hoisted(() => ({ epoch: 0, owner: 'owner', operation: 'op' }))
vi.mock('./feishuPublishReceipt', () => ({
  publishScope: (owner: string) => { const epoch = scope.epoch; return () => { if (scope.owner !== owner || scope.epoch !== epoch) throw Error('changed') } },
  readPublishDraft: () => ({ operationId: scope.operation }),
}))
beforeEach(() => { scope.owner = 'owner'; scope.operation = 'op' })
const source = '/note/saved?returnTo=%2Fnotes%3Fquery%3Dmeeting#body'
const returnPath = () => new URL(feishuSettingsReturn(source, 'owner', 'saved', 'op'), 'https://test.invalid').searchParams.get('returnTo')!
it('preserves the saved-content route, consumes once and never restores a copied URL', () => {
  const path = returnPath()
  expect(takeFeishuDeliveryReturn(path, 'owner', 'saved', false)).toEqual({ clean: source, reopen: true })
  expect(takeFeishuDeliveryReturn(path, 'owner', 'saved', false)).toBeNull()
})
it('rejects account ABA, wrong note, disabled content and replaced operation', () => {
  let path = returnPath(); scope.epoch++
  expect(takeFeishuDeliveryReturn(path, 'owner', 'saved', false)?.reopen).toBe(false)
  path = returnPath()
  expect(takeFeishuDeliveryReturn(path, 'owner', 'other', false)?.reopen).toBe(false)
  path = returnPath()
  expect(takeFeishuDeliveryReturn(path, 'owner', 'saved', true)?.reopen).toBe(false)
  path = returnPath(); scope.operation = 'replacement'
  expect(takeFeishuDeliveryReturn(path, 'owner', 'saved', false)?.reopen).toBe(false)
})
it('does not create a delivery recovery intent from plugin management', () => {
  expect(() => feishuSettingsReturn('/connections', 'owner', 'saved')).toThrow()
})
