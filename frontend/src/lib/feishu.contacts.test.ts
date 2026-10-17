import { beforeEach, expect, it, vi } from 'vitest'
import { apiJson } from './api'
import { contactRecipients, contactsValid, feishuContacts, publishToFeishu } from './feishu'
vi.mock('./api', () => ({ apiJson: vi.fn() }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: { getState: () => ({ user: { id: 'owner' } }) } }))
vi.mock('./connectorPlugins', () => ({ createConnectorPluginStore: () => ({ read: async () => ({ installed: true, enabled: true }) }) }))
beforeEach(() => vi.resetAllMocks())
const contact = { open_id: 'ou_one', name: '真实姓名', selection_token: 'opaque-proof', expiresAt: Date.now() + 900000 }
it('encodes query/cursor and stamps bounded selection lifetime without a write', async () => {
  vi.mocked(apiJson).mockResolvedValue({ items: [contact], has_more: true, page_token: 'next', selection_expires_in: 900 })
  const result = await feishuContacts('张 & 李', 'page&2')
  expect(apiJson).toHaveBeenCalledWith(expect.stringContaining('page_token=page%262'), { cache: 'no-store' })
  expect(contactsValid(result.items)).toBe(true)
  expect(result.items[0].expiresAt).toBeLessThanOrEqual(Date.now() + 900000)
})
it('serializes only recipient identity and proof while preserving local display evidence', async () => {
  const original = JSON.stringify(contact)
  expect(contactRecipients([contact])).toEqual([{ open_id: 'ou_one', selection_token: 'opaque-proof' }])
  await publishToFeishu('note', 'title', 'body', false, { operation_id: 'op', contacts: [contact] })
  const body = JSON.parse(vi.mocked(apiJson).mock.calls[0][1]!.body as string)
  expect(body.contacts).toEqual([{ open_id: 'ou_one', selection_token: 'opaque-proof' }])
  expect(JSON.stringify(contact)).toBe(original)
  expect(contactsValid([{ ...contact, expiresAt: Date.now() - 1 }])).toBe(false)
})
it('malformed contact pages fail instead of yielding an empty successful list', async () => {
  vi.mocked(apiJson).mockResolvedValue({ items: [], has_more: true, page_token: '', selection_expires_in: 900 })
  await expect(feishuContacts('姓名')).rejects.toThrow('未核验')
})
