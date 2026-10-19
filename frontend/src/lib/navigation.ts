const parents = new Set(['/notes', '/projects', '/meetings', '/files', '/tasks', '/connections', '/settings', '/settings/storage', '/settings/sync', '/team', '/settings/feishu', '/settings/mcp'])

/** Only application parents are valid. Never trust arbitrary location.state URLs. */
export function resolvePageParent(value: unknown, fallback = '/notes'): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return fallback
  try {
    const url = new URL(value, 'https://vinote.invalid')
    if (url.origin !== 'https://vinote.invalid') return fallback
    return parents.has(url.pathname) || /^\/(workspace|note)\/[A-Za-z0-9_-]+$/.test(url.pathname) ? url.pathname + url.search + url.hash : fallback
  } catch { return fallback }
}

export function pageParentLabel(path: string): string {
  if (path.startsWith('/workspace/') || path.startsWith('/note/')) return '返回内容详情'
  const labels: Record<string, string> = { '/notes': '返回笔记', '/projects': '返回项目', '/meetings': '返回会议', '/files': '返回文件库', '/tasks': '返回任务与恢复', '/connections': '返回插件', '/settings': '返回设置', '/settings/storage': '返回存储', '/settings/sync': '返回存储', '/team': '返回空间与成员', '/settings/feishu': '返回飞书', '/settings/mcp': '返回 MCP 工具' }
  return labels[path.split(/[?#]/)[0]] || '返回上级'
}

export function contextualPageParent(pathname: string, search: string, stateParent?: unknown): string | null {
  for (const value of [new URLSearchParams(search).get('returnTo'), stateParent]) {
    const parent = resolvePageParent(value, '')
    if (parent && parent.split(/[?#]/)[0] !== pathname) return parent
  }
  return null
}

export function settingsPageParent(search: string, stateParent?: unknown): string | null {
  for (const value of [new URLSearchParams(search).get('returnTo'), stateParent]) {
    const parent = resolvePageParent(value, '')
    if (parent && !/^\/settings(?:[/?#]|$)/.test(parent)) return parent
  }
  return null
}

/** The persistent menu skips settings layers without losing their workspace source. */
export function settingsMenuParent(pathname: string, search: string, hash: string, stateParent?: unknown): string | null {
  if (!/^\/settings(?:\/|$)/.test(pathname)) return resolvePageParent(pathname + search + hash, '') || null
  for (const candidate of [new URLSearchParams(search).get('returnTo'), stateParent]) {
    let parent = resolvePageParent(candidate, '')
    const seen = new Set<string>()
    for (let depth = 0; parent && depth < 8 && !seen.has(parent); depth++) {
      if (!/^\/settings(?:[/?#]|$)/.test(parent)) return parent
      seen.add(parent)
      parent = resolvePageParent(new URL(parent, 'https://vinote.invalid').searchParams.get('returnTo'), '')
    }
  }
  return null
}

/** A top-level loading screen has no invented parent. Detail screens keep a way back. */
export function loadingPageParent(pathname: string, search: string, stateParent?: unknown): string | null {
  const params = new URLSearchParams(search)
  if (pathname === '/settings') {
    const source = settingsPageParent(search, stateParent)
    if (['spaces', 'profile', 'models', 'appearance', 'recording', 'storage', 'connections', 'about'].includes(params.get('tab') || '')) {
      return source ? '/settings?' + new URLSearchParams({ returnTo: source }).toString() : '/settings'
    }
    return source
  }
  const contextual = contextualPageParent(pathname, search, stateParent)
  if (contextual) return contextual
  if (['/notes', '/meetings', '/files', '/connections', '/settings'].includes(pathname)) return null
  if (pathname === '/settings/sync' || pathname === '/settings/storage') return '/settings?tab=storage'
  if (pathname === '/settings/mcp') {
    const note = params.get('note')
    return note ? resolvePageParent('/workspace/' + encodeURIComponent(note), '/connections') : '/connections'
  }
  if (pathname === '/settings/feishu') return '/connections'
  if (pathname === '/generate' && params.get('meeting') === '1') return '/meetings'
  if (pathname === '/generate' && params.get('task')) return '/tasks?tab=generation'
  return '/notes'
}

export function requestPageNavigation(to: string, navigate: (to: string) => void) {
  const request = new CustomEvent('vinote:check-navigation', { cancelable: true, detail: { to } })
  if (window.dispatchEvent(request)) navigate(to)
}
