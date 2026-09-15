import { readRuntimeConfig } from './runtimeConfig'
import { isTauriRuntime } from './desktopMicrophonePermission'

const API_BASE = readRuntimeConfig('VITE_API_BASE_URL')

export async function apiFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers ?? {})
  if (isTauriRuntime()) {
    headers.set('X-VINote-Client', 'desktop')
    headers.set('X-VINote-Client-Version', import.meta.env.VITE_APP_VERSION || '0.5.2')
  }

  return fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: 'include',
    headers,
  })
}

export async function apiJson<T>(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  if (typeof init.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await apiFetch(path, { ...init, headers })
  if (response.status === 204 || response.status === 205) return undefined as T
  const contentType = response.headers.get('content-type') || ''
  const body = await response.text()
  const payload = contentType.includes('application/json') && body.trim() ? JSON.parse(body) : body

  if (!response.ok) {
    const detail =
      typeof payload === 'string'
        ? payload
        : payload?.detail || payload?.error_message || 'Request failed'
    const message = typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map(item => typeof item?.msg === 'string' ? item.msg : '请求参数不正确').join('；')
      : typeof detail?.message === 'string' ? detail.message : '请求失败，请稍后重试'
    throw new Error(message)
  }

  return payload as T
}
