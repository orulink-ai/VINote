import { beforeEach, describe, expect, it } from 'vitest'
import { createConnectorPluginStore, connectorPluginKey } from './connectorPlugins'

describe('device account connector installation', () => {
  let values: Map<string, string>
  let storage: { getItem: (key: string) => Promise<string | null>; setItem: (key: string, value: string) => Promise<void> }
  beforeEach(() => {
    values = new Map()
    storage = { getItem: async key => values.get(key) ?? null, setItem: async (key, value) => { values.set(key, value) } }
  })
  it('starts uninstalled, persists installation and disable across re-entry, isolates owners', async () => {
    const store = createConnectorPluginStore(storage)
    expect(await store.read('a', () => true)).toEqual({ installed: false, enabled: false })
    await store.save('a', { installed: true, enabled: true }, () => true)
    expect(await createConnectorPluginStore(storage).read('a', () => true)).toEqual({ installed: true, enabled: true })
    await store.save('a', { installed: true, enabled: false }, () => true)
    expect(await store.read('a', () => true)).toEqual({ installed: true, enabled: false })
    expect(await store.read('b', () => true)).toEqual({ installed: false, enabled: false })
    expect(connectorPluginKey('a/b')).not.toBe(connectorPluginKey('a%2Fb'))
  })
  it('does not report a failed write as installed and allows retry', async () => {
    const setItem = storage.setItem
    storage.setItem = async () => { throw new Error('disk full') }
    const store = createConnectorPluginStore(storage)
    await expect(store.save('a', { installed: true, enabled: true }, () => true)).rejects.toThrow('disk full')
    expect(await store.read('a', () => true)).toEqual({ installed: false, enabled: false })
    storage.setItem = setItem
    expect(await store.save('a', { installed: true, enabled: true }, () => true)).toEqual({ installed: true, enabled: true })
  })
  it('keeps corrupted state as a read failure, never an empty install list', async () => {
    values.set(connectorPluginKey('a'), '{broken')
    await expect(createConnectorPluginStore(storage).read('a', () => true)).rejects.toThrow('无法读取')
    values.set(connectorPluginKey('a'), JSON.stringify({ version: 1, feishu: { installed: false, enabled: true } }))
    await expect(createConnectorPluginStore(storage).read('a', () => true)).rejects.toThrow('无法读取')
  })
  it('rejects a late read after an account transition', async () => {
    let active = true
    storage.getItem = async () => { active = false; return null }
    await expect(createConnectorPluginStore(storage).read('a', () => active)).rejects.toThrow('账号已变化')
  })
  it('never writes a different owner and rejects late save acknowledgement', async () => {
    let active = true
    const setItem = storage.setItem
    storage.setItem = async (key, value) => { await setItem(key, value); active = false }
    const store = createConnectorPluginStore(storage)
    await expect(store.save('a', { installed: true, enabled: true }, () => active)).rejects.toThrow('账号已变化')
    expect(values.has(connectorPluginKey('b'))).toBe(false)
    await expect(store.save('b', { installed: true, enabled: true }, () => false)).rejects.toThrow('账号已变化')
  })
  it('requires an owner and rejects enabled without installation', async () => {
    const store = createConnectorPluginStore(storage)
    await expect(store.read('', () => true)).rejects.toThrow('账号已变化')
    await expect(store.save('a', { installed: false, enabled: true }, () => true)).rejects.toThrow('请先安装')
  })
})
