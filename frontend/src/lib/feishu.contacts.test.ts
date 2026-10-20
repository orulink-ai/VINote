import { beforeEach, expect, it, vi } from 'vitest'
import { apiJson } from './api'
import { contactRecipients, contactsValid, feishuContacts, publishToFeishu, preferenceContacts, automaticConsentNeeded } from './feishu'
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
  vi.mocked(apiJson).mockRejectedValueOnce({ status: 404 }).mockResolvedValueOnce({ id: 'job' })
  await publishToFeishu('note', 'title', 'body', false, { operation_id: 'op', contacts: [contact] })
  const body = JSON.parse(vi.mocked(apiJson).mock.calls[1][1]!.body as string)
  expect(body.contacts).toEqual([{ open_id: 'ou_one', selection_token: 'opaque-proof' }])
  expect(JSON.stringify(contact)).toBe(original)
  expect(contactsValid([{ ...contact, expiresAt: Date.now() - 1 }])).toBe(false)
})
it('malformed contact pages fail instead of yielding an empty successful list', async () => {
  vi.mocked(apiJson).mockResolvedValue({ items: [], has_more: true, page_token: '', selection_expires_in: 900 })
  await expect(feishuContacts('姓名')).rejects.toThrow('未核验')
})
it('saved preference contacts need only identity; a new choice requires current proof and never sends names', () => {
  expect(preferenceContacts([{ open_id: 'ou_saved', name: '服务端名称' }], [{ open_id: 'ou_saved', name: '服务端名称' }])).toEqual([{ open_id: 'ou_saved' }])
  expect(preferenceContacts([contact], [])).toEqual([{ open_id: 'ou_one', selection_token: 'opaque-proof' }])
  expect(() => preferenceContacts([{ ...contact, expiresAt: Date.now() - 1 }], [])).toThrow('重新搜索')
  expect(() => preferenceContacts([{ open_id: 'ou_unknown', name: '不能凭名字授权' }], [])).toThrow('重新搜索')
})
it('enabling or changing enabled targets requires consent; disabling alone does not, while preset contact changes do', () => {
  const saved = { auto_publish: true, notify_self: true, groups: ['group'], contacts: [{ open_id: 'ou_saved', name: '姓名' }], destination_config: { kind: 'personal' as const } }
  expect(automaticConsentNeeded({ ...saved, auto_publish: false }, saved)).toBe(false)
  expect(automaticConsentNeeded(saved, { ...saved, auto_publish: false })).toBe(true)
  expect(automaticConsentNeeded({ ...saved, notify_self: false }, saved)).toBe(true)
  expect(automaticConsentNeeded({ ...saved, groups: [] }, saved)).toBe(true)
  expect(automaticConsentNeeded({ ...saved, contacts: [] }, saved)).toBe(true)
  expect(automaticConsentNeeded({ ...saved, destination_config: { kind: 'folder', folder_token: 'folder' } }, saved)).toBe(true)
  expect(automaticConsentNeeded(saved, saved)).toBe(false)
  expect(automaticConsentNeeded({ ...saved, auto_publish: false, contacts: [] }, { ...saved, auto_publish: false })).toBe(true)
  expect(automaticConsentNeeded({ ...saved, auto_publish: false }, { ...saved, auto_publish: false })).toBe(false)
})
