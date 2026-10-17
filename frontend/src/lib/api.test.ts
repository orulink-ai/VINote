import { afterEach, expect, it, vi } from 'vitest'
import { apiJson } from './api'

afterEach(() => vi.unstubAllGlobals())

it('marks only Tauri requests as desktop traffic', async () => {
  Object.defineProperty(window, '__TAURI_INTERNALS__', { value: {}, configurable: true })
  const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetchMock)
  await apiJson('/api/test')
  expect(fetchMock.mock.calls[0][1].headers.get('X-VINote-Client')).toBe('desktop')
  delete (window as typeof window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__
})

it('does not mark browser requests as desktop traffic', async () => {
  delete (window as typeof window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__
  const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetchMock)
  await apiJson('/api/test')
  expect(fetchMock.mock.calls[0][1].headers.has('X-VINote-Client')).toBe(false)
})

it('accepts successful deletion with an empty JSON-labelled 204 response', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, {
    status: 204, headers: { 'Content-Type': 'application/json' },
  })))
  await expect(apiJson<void>('/api/notes/test', { method: 'DELETE' })).resolves.toBeUndefined()
})

it('accepts empty successful bodies without parsing JSON', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', {
    headers: { 'Content-Type': 'application/json' },
  })))
  await expect(apiJson('/api/test')).resolves.toBe('')
})

it('still reports a failed request with an empty body', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, {
    status: 500, headers: { 'Content-Type': 'application/json' },
  })))
  await expect(apiJson('/api/test')).rejects.toThrow()
})

it('sends JSON headers for authentication payloads', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetchMock)
  await apiJson('/api/auth/code', { method: 'POST', body: JSON.stringify({ email: 'test@example.com' }) })
  expect(fetchMock.mock.calls[0][1].headers.get('Content-Type')).toBe('application/json')
  expect(fetchMock.mock.calls[0][1].credentials).toBe('include')
})

it('shows validation messages without object coercion', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:[{msg:'Invalid email'}]}), {
    status:422, headers:{'Content-Type':'application/json'},
  })))
  await expect(apiJson('/api/auth/code')).rejects.toThrow('Invalid email')
})

it('lets the browser set the multipart boundary for uploads', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response('{}', {headers:{'Content-Type':'application/json'}}))
  vi.stubGlobal('fetch', fetchMock)
  await apiJson('/api/upload', {method:'POST', body:new FormData()})
  expect(fetchMock.mock.calls[0][1].headers.has('Content-Type')).toBe(false)
})
