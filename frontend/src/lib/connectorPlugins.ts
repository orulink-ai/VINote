export type ConnectorPluginState = { installed: boolean; enabled: boolean }
export type ConnectorStorage = { getItem(key: string): string | null | Promise<string | null>; setItem(key: string, value: string): void | Promise<void> }
export const connectorPluginKey = (owner: string) => `vinote:connector-plugins:v1:${encodeURIComponent(owner)}`
const empty = (): ConnectorPluginState => ({ installed: false, enabled: false })

// Device storage only: no workspace request, credential or downloadable package.
export function createConnectorPluginStore(storage: ConnectorStorage) {
  const check = (owner: string, current: () => boolean) => {
    if (!owner || !current()) throw new Error('账号已变化，请返回当前账号的插件商店。')
  }
  return {
    async read(owner: string, current: () => boolean): Promise<ConnectorPluginState> {
      check(owner, current)
      const raw = await storage.getItem(connectorPluginKey(owner))
      check(owner, current)
      if (raw === null) return empty()
      let value: unknown
      try { value = JSON.parse(raw) } catch { throw new Error('安装状态无法读取，请重试；不会覆盖已有设置。') }
      const saved = value as { version?: unknown; feishu?: ConnectorPluginState } | null
      if (saved?.version !== 1 || typeof saved.feishu?.installed !== 'boolean' || typeof saved.feishu.enabled !== 'boolean' || (!saved.feishu.installed && saved.feishu.enabled)) throw new Error('安装状态无法读取，请重试；不会覆盖已有设置。')
      return { installed: saved.feishu.installed, enabled: saved.feishu.enabled }
    },
    async save(owner: string, next: ConnectorPluginState, current: () => boolean): Promise<ConnectorPluginState> {
      check(owner, current)
      if (!next.installed && next.enabled) throw new Error('请先安装插件。')
      const committed = { installed: next.installed, enabled: next.enabled }
      await storage.setItem(connectorPluginKey(owner), JSON.stringify({ version: 1, feishu: committed }))
      check(owner, current)
      return committed
    },
  }
}
