import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { apiFetch } from '@/lib/api'
import { useNoteMediaPlayback } from './useNoteMediaPlayback'

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }))
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.useRealTimers() })

it.each([200, 206, 404, 500])('clears an existing HTTP %s error on initial metadata without claiming playable', async status => {
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(null, { status }))
  const { result } = renderHook(() => useNoteMediaPlayback('/api/notes/a/media?playback=true', 'owner:a', true, true))
  const video = document.createElement('video')
  Object.defineProperty(video, 'duration', { value: 1585 })
  await act(async () => { await result.current.failed(video) })
  expect(result.current.message).not.toBe('')
  act(() => result.current.metadata(video))
  expect(result.current.message).toBe('')
  expect(result.current.phase).toBe('loading')
  expect(result.current.status).not.toBe('')
  expect(video.duration).toBe(1585)
  expect(apiFetch).toHaveBeenCalledTimes(1)
  act(() => result.current.ready())
  expect(result.current.phase).toBe('ready')
  expect(result.current.status).toBe('')
})

it.each(['resolve', 'reject'] as const)('invalidates a pending probe on metadata before its late %s', async outcome => {
  let finish!: (response: Response) => void
  let reject!: (cause: Error) => void
  vi.mocked(apiFetch).mockImplementationOnce(() => new Promise((resolve, fail) => { finish = resolve; reject = fail }))
  const { result } = renderHook(() => useNoteMediaPlayback('/api/notes/a/media?playback=true', 'owner:a', true, false))
  const video = document.createElement('video')
  let pending!: Promise<void>
  act(() => { pending = result.current.failed(video) })
  const signal = vi.mocked(apiFetch).mock.calls[0][1]!.signal!
  act(() => result.current.metadata(video))
  expect(signal.aborted).toBe(true)
  expect(result.current.phase).toBe('loading')
  await act(async () => {
    if (outcome === 'resolve') finish(new Response(null, { status: 404 }))
    else reject(new Error('old transport failed'))
    await pending
  })
  expect(result.current.message).toBe('')
  expect(result.current.phase).toBe('loading')
})

it('ignores abort rejection from the old probe but displays a new genuine media error after metadata', async () => {
  vi.mocked(apiFetch).mockImplementationOnce((_path, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  })).mockResolvedValueOnce(new Response(null, { status: 404 }))
  const { result } = renderHook(() => useNoteMediaPlayback('/api/notes/a/media?playback=true', 'owner:a', true, false))
  const video = document.createElement('video')
  let pending!: Promise<void>
  act(() => { pending = result.current.failed(video) })
  await act(async () => { result.current.metadata(video); await pending })
  expect(result.current.phase).toBe('loading')
  expect(result.current.message).toBe('')
  await act(async () => { await result.current.failed(video) })
  expect(result.current.phase).toBe('missing')
  expect(result.current.message).toContain('Playback source unavailable')
  expect(apiFetch).toHaveBeenCalledTimes(2)
})

it.each(['sourceUrl', 'identity'] as const)('ignores the previous %s probe after metadata for the new visit', async changed => {
  let finish!: (response: Response) => void
  vi.mocked(apiFetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const initial = { sourceUrl: '/api/notes/a/media?playback=true', identity: 'owner:a' }
  const { result, rerender } = renderHook(({ sourceUrl, identity }) => useNoteMediaPlayback(sourceUrl, identity, true, false), { initialProps: initial })
  const video = document.createElement('video')
  let pending!: Promise<void>
  act(() => { pending = result.current.failed(video) })
  rerender({ ...initial, [changed]: changed === 'sourceUrl' ? '/api/notes/b/media?playback=true' : 'other-owner:a' })
  act(() => result.current.metadata(video))
  await act(async () => { finish(new Response(null, { status: 404 })); await pending })
  expect(result.current.phase).toBe('loading')
  expect(result.current.message).toBe('')
  act(() => result.current.ready())
  expect(result.current.phase).toBe('ready')
})

it.each([
  ['sourceUrl', false], ['identity', false], ['sourceUrl', true], ['identity', true],
] as const)('ignores a captured old metadata callback after %s changes (ABA=%s) without clearing the new error', async (changed, roundTrip) => {
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(null, { status: 403 }))
  const initial = { sourceUrl: '/api/notes/a/media?playback=true', identity: 'owner:a' }
  const { result, rerender } = renderHook(({ sourceUrl, identity }) => useNoteMediaPlayback(sourceUrl, identity, true, false), { initialProps: initial })
  const oldMetadata = result.current.metadata
  const oldVideo = document.createElement('video')
  rerender({ ...initial, [changed]: changed === 'sourceUrl' ? '/api/notes/b/media?playback=true' : 'other-owner:a' })
  if (roundTrip) rerender(initial)
  await act(async () => { await result.current.failed(document.createElement('video')) })
  const message = result.current.message
  expect(result.current.phase).toBe('error')
  expect(message).toContain('check permission')
  act(() => oldMetadata(oldVideo))
  expect(result.current.phase).toBe('error')
  expect(result.current.message).toBe(message)
})

it.each([
  ['sourceUrl', false], ['identity', false], ['sourceUrl', true], ['identity', true],
] as const)('ignores a captured old metadata callback after %s changes (ABA=%s) without aborting or invalidating the new probe', async (changed, roundTrip) => {
  let finish!: (response: Response) => void
  vi.mocked(apiFetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const initial = { sourceUrl: '/api/notes/a/media?playback=true', identity: 'owner:a' }
  const { result, rerender } = renderHook(({ sourceUrl, identity }) => useNoteMediaPlayback(sourceUrl, identity, true, false), { initialProps: initial })
  const oldMetadata = result.current.metadata
  const oldVideo = document.createElement('video')
  rerender({ ...initial, [changed]: changed === 'sourceUrl' ? '/api/notes/b/media?playback=true' : 'other-owner:a' })
  if (roundTrip) rerender(initial)
  let pending!: Promise<void>
  act(() => { pending = result.current.failed(document.createElement('video')) })
  const signal = vi.mocked(apiFetch).mock.calls[0][1]!.signal!
  act(() => oldMetadata(oldVideo))
  expect(signal.aborted).toBe(false)
  expect(result.current.phase).toBe('checking')
  await act(async () => { finish(new Response(null, { status: 403 })); await pending })
  expect(result.current.phase).toBe('error')
  expect(result.current.message).toContain('check permission')
  expect(apiFetch).toHaveBeenCalledTimes(1)
})

it('accepts captured metadata across same-visit rerenders and request sequence changes', async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(null, { status: 403 }))
    .mockImplementationOnce((_path, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
  const { result, rerender } = renderHook(({ zh }) => useNoteMediaPlayback('/api/notes/a/media?playback=true', 'owner:a', true, zh), { initialProps: { zh: false } })
  const metadata = result.current.metadata
  const video = document.createElement('video')
  await act(async () => { await result.current.failed(video) })
  rerender({ zh: true })
  expect(result.current.message).not.toBe('')
  act(() => metadata(video))
  expect(result.current.phase).toBe('loading')
  expect(result.current.message).toBe('')
  act(() => result.current.ready())
  let pending!: Promise<void>
  act(() => { pending = result.current.failed(video) })
  const signal = vi.mocked(apiFetch).mock.calls[1][1]!.signal!
  rerender({ zh: false })
  await act(async () => { metadata(video); await pending })
  expect(signal.aborted).toBe(true)
  expect(result.current.phase).toBe('loading')
  expect(result.current.message).toBe('')
})

it.each([false, true])('restores reload position and rate without declaring ready (playing=%s)', async playing => {
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(null, { status: 500 }))
  const { result } = renderHook(() => useNoteMediaPlayback('/api/notes/a/media?playback=true', 'owner:a', true, false))
  const video = document.createElement('video')
  Object.defineProperties(video, { duration: { value: 1585 }, paused: { value: !playing } })
  const play = vi.spyOn(video, 'play').mockResolvedValue(undefined)
  const load = vi.spyOn(video, 'load').mockImplementation(() => undefined)
  video.currentTime = 1212.55
  video.playbackRate = 1.5
  act(() => result.current.remember(video))
  await act(async () => { await result.current.failed(video) })
  video.currentTime = 0
  act(() => result.current.reload(video))
  video.playbackRate = 1
  act(() => result.current.metadata(video))
  expect(load).toHaveBeenCalledTimes(1)
  expect(video.currentTime).toBe(1212.55)
  expect(video.playbackRate).toBe(1.5)
  expect(play).toHaveBeenCalledTimes(playing ? 1 : 0)
  expect(result.current.phase).toBe('loading')
  expect(result.current.message).toBe('')
  act(() => result.current.ready())
  expect(result.current.phase).toBe('ready')
})

it('does not downgrade readiness already established by canplay when metadata is received again', () => {
  const { result } = renderHook(() => useNoteMediaPlayback('/api/notes/a/media?playback=true', 'owner:a', true, false))
  act(() => result.current.ready())
  act(() => result.current.metadata(document.createElement('video')))
  expect(result.current.phase).toBe('ready')
  expect(result.current.message).toBe('')
  expect(result.current.status).toBe('')
})

it('does not let an older probe erase a newer error after metadata', async () => {
  let finish!: (response: Response) => void
  vi.mocked(apiFetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    .mockResolvedValueOnce(new Response(null, { status: 403 }))
  const { result } = renderHook(() => useNoteMediaPlayback('/api/notes/a/media?playback=true', 'owner:a', true, false))
  const video = document.createElement('video')
  let pending!: Promise<void>
  act(() => { pending = result.current.failed(video) })
  act(() => result.current.metadata(video))
  await act(async () => { await result.current.failed(video) })
  const message = result.current.message
  expect(result.current.phase).toBe('error')
  expect(message).toContain('check permission')
  await act(async () => { finish(new Response(null, { status: 404 })); await pending })
  expect(result.current.phase).toBe('error')
  expect(result.current.message).toBe(message)
})

it.each(['resolve', 'reject'] as const)('ignores an obsolete probe %s after the same player becomes playable', async outcome => {
  let finish!: (response: Response) => void
  let reject!: (cause: Error) => void
  vi.mocked(apiFetch).mockImplementationOnce(() => new Promise((resolve, fail) => { finish = resolve; reject = fail }))
  const { result } = renderHook(() => useNoteMediaPlayback('/api/notes/a/media?playback=true', 'owner:a', true, false))
  let pending!: Promise<void>
  act(() => { pending = result.current.failed(document.createElement('video')) })
  act(() => result.current.ready())
  await act(async () => {
    if (outcome === 'resolve') finish(new Response(null, { status: 404 }))
    else reject(new Error('old transport failed'))
    await pending
  })
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
