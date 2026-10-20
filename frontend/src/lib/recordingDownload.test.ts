import { Blob as NodeBlob } from 'node:buffer'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { invoke } from '@tauri-apps/api/core'
import { apiFetch } from './api'
import { isTauriRuntime } from './desktopMicrophonePermission'
import { downloadRecording, downloadOriginalFile, downloadResultMessage } from './recordingDownload'

vi.mock('./api', () => ({ apiFetch: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))
vi.mock('./desktopMicrophonePermission', () => ({ isTauriRuntime: vi.fn() }))
const original = () => new NodeBlob([new Uint8Array([0, 255, 16, 32])], { type: 'video/webm' }) as unknown as Blob
beforeEach(() => { vi.mocked(isTauriRuntime).mockReturnValue(true); vi.mocked(invoke).mockResolvedValue(undefined) })
afterEach(() => { vi.resetAllMocks(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers() })

it('cancels the native picker without fetching bytes or claiming success', async () => {
  vi.mocked(invoke).mockResolvedValueOnce(null)
  const read = vi.fn()
  expect(await downloadRecording(read, 'video', 'video.webm')).toBe('cancelled')
  expect(read).not.toHaveBeenCalled()
  expect(invoke).toHaveBeenCalledExactlyOnceWith('choose_original_destination', { filename: 'video.webm' })
  expect(downloadResultMessage('cancelled')).toContain('已取消')
})

it('saves exact original bytes, then reports completion only after the native finish', async () => {
  let finish!: () => void
  vi.mocked(invoke).mockImplementation(async command => {
    if (command === 'choose_original_destination') return 'session'
    if (command === 'finish_original_download') await new Promise<void>(resolve => { finish = resolve })
  })
  const done = vi.fn()
  const result = downloadRecording(original(), 'video', 'original.webm').then(done)
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  expect(done).not.toHaveBeenCalled()
  expect(invoke).toHaveBeenCalledWith('append_original_bytes', { id: 'session', bytes: [0, 255, 16, 32] })
  finish(); await result
  expect(done).toHaveBeenCalledWith('saved')
  expect(invoke).not.toHaveBeenCalledWith('cancel_original_download', expect.anything())
})

it('chunks large media instead of serializing the whole video in one IPC call', async () => {
  vi.mocked(invoke).mockResolvedValueOnce('session')
  await downloadRecording(new NodeBlob([new Uint8Array(1024 * 1024 + 2)]) as unknown as Blob, 'video')
  const chunks = vi.mocked(invoke).mock.calls.filter(([cmd]) => cmd === 'append_original_bytes')
  expect(chunks.map(([, args]) => (args as { bytes: number[] }).bytes.length)).toEqual([1024 * 1024, 2])
})

it.each(['read', 'append_original_bytes', 'finish_original_download'])('cleans the temporary native session on %s failure and does not claim saved', async failure => {
  vi.mocked(invoke).mockImplementation(async command => {
    if (command === 'choose_original_destination') return 'session'
    if (command === failure) throw new Error('disk unavailable')
  })
  await expect(downloadRecording(async () => { if (failure === 'read') throw new Error('read failed'); return original() }, 'video')).rejects.toThrow()
  expect(invoke).toHaveBeenCalledWith('cancel_original_download', { id: 'session' })
})

it('discards a late picker result after owner/route invalidation without reading the old file', async () => {
  vi.mocked(invoke).mockResolvedValueOnce('session')
  const read = vi.fn()
  expect(await downloadRecording(read, 'video', undefined, () => false)).toBe('cancelled')
  expect(read).not.toHaveBeenCalled()
  expect(invoke).toHaveBeenCalledWith('cancel_original_download', { id: 'session' })
})

it('hands browser downloads the original blob and reports handoff rather than a saved file', async () => {
  vi.useFakeTimers()
  vi.mocked(isTauriRuntime).mockReturnValue(false)
  const create = vi.fn(() => 'blob:original'); const revoke = vi.fn()
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.download).toBe('original.mp4'); expect(this.href).toBe('blob:original')
  })
  const blob = original()
  expect(await downloadRecording(blob, 'ignored', 'original.mp4')).toBe('browser_started')
  expect(create).toHaveBeenCalledWith(blob); expect(click).toHaveBeenCalledOnce()
  expect(document.querySelector('a[download]')).toBeNull()
  expect(invoke).not.toHaveBeenCalled()
  expect(downloadResultMessage('browser_started')).toContain('下载列表')
  vi.runAllTimers(); expect(revoke).toHaveBeenCalledWith('blob:original')
})


it('streams authenticated original media in bounded chunks without constructing a Blob', async () => {
  vi.mocked(invoke).mockResolvedValueOnce('session')
  const blob = vi.fn(() => { throw new Error('No whole-file Blob allowed') })
  const cancel = vi.fn()
  const body = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new Uint8Array([1, 2, 3])); controller.enqueue(new Uint8Array([4, 5])); controller.close() }, cancel })
  vi.mocked(apiFetch).mockResolvedValueOnce({ ok: true, body, blob } as unknown as Response)
  const abort = new AbortController()
  expect(await downloadOriginalFile('/api/notes/source/media', 'original.webm', () => true, abort.signal)).toBe('saved')
  expect(apiFetch).toHaveBeenCalledExactlyOnceWith('/api/notes/source/media', { redirect: 'error', signal: abort.signal })
  expect(blob).not.toHaveBeenCalled()
  expect(vi.mocked(invoke).mock.calls.filter(([cmd]) => cmd === 'append_original_bytes').map(([, args]) => (args as { bytes: number[] }).bytes)).toEqual([[1, 2, 3], [4, 5]])
})

it('cancels a partial stream and temporary native file after route invalidation', async () => {
  let valid = true
  const cancel = vi.fn()
  vi.mocked(invoke).mockImplementation(async cmd => { if (cmd === 'choose_original_destination') return 'session'; if (cmd === 'append_original_bytes') valid = false })
  const body = new ReadableStream<Uint8Array>({ pull(controller) { controller.enqueue(new Uint8Array([1])) }, cancel })
  vi.mocked(apiFetch).mockResolvedValueOnce({ ok: true, body } as Response)
  expect(await downloadOriginalFile('/api/files/file/content?download=true', 'file.webm', () => valid)).toBe('cancelled')
  expect(cancel).toHaveBeenCalledOnce()
  expect(invoke).toHaveBeenCalledWith('cancel_original_download', { id: 'session' })
  expect(invoke).not.toHaveBeenCalledWith('finish_original_download', expect.anything())
})

it('browser URL fallback verifies authorization before handing off without fetching a large Blob', async () => {
  vi.mocked(isTauriRuntime).mockReturnValue(false)
  const cancel = vi.fn().mockResolvedValue(undefined)
  vi.mocked(apiFetch).mockResolvedValueOnce({ status: 206, body: { cancel } } as unknown as Response)
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.getAttribute('href')).toBe('/api/notes/source/media')
    expect(this.download).toBe('original.webm'); expect(this.target).toBe('_blank'); expect(this.rel).toBe('noopener')
  })
  expect(await downloadOriginalFile('/api/notes/source/media', 'original.webm')).toBe('browser_started')
  expect(click).toHaveBeenCalledOnce(); expect(cancel).toHaveBeenCalledOnce()
  expect(apiFetch).toHaveBeenCalledExactlyOnceWith('/api/notes/source/media', { method: 'GET', headers: { Range: 'bytes=0-0' }, redirect: 'error', signal: undefined })
  expect(invoke).not.toHaveBeenCalled()
})

it.each(['https://outside.invalid/api/notes/source/media', '//outside.invalid/api/files/file/content', '/api/notes/source/media?playback=true', '/api/files/../secret/content', '/api/task/id/artifacts/%2e%2e/secret', '/api/files/id/content?download=true&token=secret', '/api/task/id/artifacts/secret%5cfile'])('rejects untrusted or derivative URL %s before any fetch, dialog or browser action', async path => {
  await expect(downloadOriginalFile(path, 'original.webm')).rejects.toThrow()
  expect(apiFetch).not.toHaveBeenCalled(); expect(invoke).not.toHaveBeenCalled()
})

it('cleans partial native output on an HTTP authorization failure and never falls back to an unauthenticated URL', async () => {
  vi.mocked(invoke).mockResolvedValueOnce('session')
  vi.mocked(apiFetch).mockResolvedValueOnce({ ok: false, status: 401 } as Response)
  await expect(downloadOriginalFile('/api/notes/source/media', 'source.webm')).rejects.toThrow('原文件导出失败')
  expect(invoke).toHaveBeenCalledWith('cancel_original_download', { id: 'session' })
  expect(invoke).not.toHaveBeenCalledWith('finish_original_download', expect.anything())
})

it('aborts a streamed export as cancelled, removes partial output and does not finish', async () => {
  const abort = new AbortController()
  const cancel = vi.fn()
  vi.mocked(invoke).mockImplementation(async cmd => {
    if (cmd === 'choose_original_destination') return 'session'
    if (cmd === 'append_original_bytes') abort.abort()
  })
  vi.mocked(apiFetch).mockResolvedValueOnce({ ok: true, body: new ReadableStream<Uint8Array>({ pull(controller) { controller.enqueue(new Uint8Array([1])) }, cancel }) } as Response)
  expect(await downloadOriginalFile('/api/notes/source/media', 'source.webm', () => true, abort.signal)).toBe('cancelled')
  expect(cancel).toHaveBeenCalledOnce()
  expect(invoke).toHaveBeenCalledWith('cancel_original_download', { id: 'session' })
  expect(invoke).not.toHaveBeenCalledWith('finish_original_download', expect.anything())
})


it.each([401, 403, 404, 500])('rejects browser original status %s without handing off or claiming started', async status => {
  vi.mocked(isTauriRuntime).mockReturnValue(false)
  const cancel = vi.fn().mockResolvedValue(undefined)
  vi.mocked(apiFetch).mockResolvedValueOnce({ status, body: { cancel } } as unknown as Response)
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  await expect(downloadOriginalFile('/api/notes/source/media', 'source.webm')).rejects.toThrow('原文件导出失败')
  expect(cancel).toHaveBeenCalledOnce(); expect(click).not.toHaveBeenCalled(); expect(invoke).not.toHaveBeenCalled()
})

it('accepts a server ignoring Range with HTTP 200 but cancels its body before browser handoff', async () => {
  vi.mocked(isTauriRuntime).mockReturnValue(false)
  const cancel = vi.fn().mockResolvedValue(undefined)
  const blob = vi.fn()
  vi.mocked(apiFetch).mockResolvedValueOnce({ status: 200, body: { cancel }, blob } as unknown as Response)
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => { expect(cancel).toHaveBeenCalledOnce() })
  expect(await downloadOriginalFile('/api/files/source/content?download=true', 'source.webm')).toBe('browser_started')
  expect(click).toHaveBeenCalledOnce(); expect(blob).not.toHaveBeenCalled()
})

it.each(['owner', 'abort'])('discards a successful but late browser preflight after %s invalidation', async kind => {
  vi.mocked(isTauriRuntime).mockReturnValue(false)
  let finish!: (response: Response) => void
  let current = true
  const abort = new AbortController()
  const cancel = vi.fn().mockResolvedValue(undefined)
  vi.mocked(apiFetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  const result = downloadOriginalFile('/api/notes/source/media', 'source.webm', () => current, abort.signal)
  if (kind === 'owner') current = false; else abort.abort()
  finish({ status: 206, body: { cancel } } as unknown as Response)
  expect(await result).toBe('cancelled')
  expect(cancel).toHaveBeenCalledOnce(); expect(click).not.toHaveBeenCalled()
})
