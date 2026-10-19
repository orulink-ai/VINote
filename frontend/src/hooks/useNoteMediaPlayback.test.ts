import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { apiFetch } from '@/lib/api'
import { useNoteMediaPlayback } from './useNoteMediaPlayback'

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }))
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.useRealTimers() })

it('ignores an obsolete missing response after the same player becomes playable', async () => {
  let finish!: (response: Response) => void
  vi.mocked(apiFetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const { result } = renderHook(() => useNoteMediaPlayback('/api/notes/a/media?playback=true', 'owner:a', true, false))
  let pending!: Promise<void>
  act(() => { pending = result.current.failed(document.createElement('video')) })
  act(() => result.current.ready())
  await act(async () => { finish(new Response(null, { status: 404 })); await pending })
  expect(result.current.phase).toBe('ready')
  expect(result.current.message).toBe('')
});

it('ignores an old account visit result even when returning to the same note identity', async () => {
  let finish!: (response: Response) => void
  vi.mocked(apiFetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const { result, rerender } = renderHook(({ identity }) => useNoteMediaPlayback('/api/notes/a/media?playback=true', identity, true, false), { initialProps: { identity: 'owner-a:a' } })
  let pending!: Promise<void>
  act(() => { pending = result.current.failed(document.createElement('video')) })
  rerender({ identity: 'owner-b:a' })
  rerender({ identity: 'owner-a:a' })
  await act(async () => { finish(new Response(null, { status: 403 })); await pending })
  expect(result.current.phase).toBe('loading')
  expect(result.current.message).toBe('')
});

it('bounds a hung status probe and reports uncertainty rather than a missing original', async () => {
  vi.useFakeTimers()
  vi.mocked(apiFetch).mockImplementationOnce((_path, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  const { result } = renderHook(() => useNoteMediaPlayback('/api/notes/a/media', 'owner:a', false, false))
  let pending!: Promise<void>
  act(() => { pending = result.current.failed(document.createElement('audio')) })
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); await pending })
  expect(result.current.phase).toBe('error')
  expect(result.current.message).toContain('availability is unverified')
  expect(result.current.message).not.toMatch(/deleted|not found/)
  expect(apiFetch).toHaveBeenCalledTimes(1)
});
