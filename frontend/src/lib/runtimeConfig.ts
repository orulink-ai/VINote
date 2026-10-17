type RuntimeConfig = {
  VITE_API_BASE_URL?: string
  VITE_DOCS_BASE_URL?: string
}

declare global {
  interface Window {
    __VINOTE_CONFIG__?: RuntimeConfig
  }
}

const runtimeConfig: RuntimeConfig =
  typeof window !== 'undefined' ? window.__VINOTE_CONFIG__ || {} : {}

function resolveAbsoluteUrl(value: string) {
  if (typeof window === 'undefined') {
    return value
  }

  try {
    return new URL(value, window.location.origin).toString()
  } catch {
    return value
  }
}

export function resolveBackendOrigin() {
  const apiBase = readRuntimeConfig('VITE_API_BASE_URL').trim()

  if (typeof window === 'undefined') {
    return 'http://127.0.0.1:8900'
  }

  if (!apiBase) {
    return window.location.port === '3100'
      ? `${window.location.protocol}//${window.location.hostname}:8900`
      : window.location.origin
  }

  try {
    return new URL(apiBase, window.location.origin).origin
  } catch {
    return window.location.origin
  }
}

export function readRuntimeConfig(key: keyof RuntimeConfig) {
  const runtimeValue = runtimeConfig[key]
  if (runtimeValue && runtimeValue.trim()) {
    return runtimeValue
  }

  return import.meta.env[key] || ''
}

export function resolveApiRootUrl() {
  const apiBase = readRuntimeConfig('VITE_API_BASE_URL').trim()

  if (typeof window === 'undefined') {
    return '/api'
  }

  if (!apiBase) {
    return window.location.port === '3100'
      ? `${window.location.protocol}//${window.location.hostname}:8900/api`
      : `${window.location.origin}/api`
  }

  return resolveAbsoluteUrl(apiBase)
}

export function resolveSwaggerUrl() {
  return `${resolveBackendOrigin()}/docs`
}

export function resolveMcpUrl() {
  return `${resolveBackendOrigin()}/mcp`
}

export function resolveDocumentUrl() {
  const docsBase = readRuntimeConfig('VITE_DOCS_BASE_URL').trim()

  if (typeof window === 'undefined') {
    return resolveSwaggerUrl()
  }

  if (docsBase) {
    return resolveAbsoluteUrl(docsBase)
  }

  if (window.location.port === '3100') {
    return `${window.location.protocol}//${window.location.hostname}:3101/`
  }

  return resolveSwaggerUrl()
}
