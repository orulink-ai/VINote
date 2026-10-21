import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { invoke } from '@tauri-apps/api/core'
import { apiJson } from './api'
import { isTauriRuntime } from './desktopMicrophonePermission'
import { revealOriginalFile } from './originalLocation'
vi.mock('./api', () => ({ apiJson: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))
vi.mock('./desktopMicrophonePermission', () => ({ isTauriRuntime: vi.fn() }))
beforeEach(() => { vi.mocked(isTauriRuntime).mockReturnValue(true); vi.mocked(apiJson).mockResolvedValue({ local_path_protocol: 1, absolute_path: 'D:\\recordings\\source.webm' }) })
afterEach(() => vi.resetAllMocks())

it.each([['/api/notes/note/media', '/api/notes/note/media/local-path'], ['/api/files/file/content?download=true', '/api/files/file/local-path'], ['/api/task/task/artifacts/media/source_video.webm', '/api/task/task/original/local-path']])('resolves the exact owned original %s before native reveal without downloading bytes', async (url, endpoint) => {
  expect(await revealOriginalFile(url)).toBe('shown')
  expect(apiJson).toHaveBeenCalledExactlyOnceWith(endpoint, { cache: 'no-store', redirect: 'error', signal: undefined })
  expect(invoke).toHaveBeenCalledExactlyOnceWith('reveal_original_file', { path: 'D:\\recordings\\source.webm' })
})
it.each(['https://outside.invalid/api/notes/a/media', '/api/files/../private/content', '/api/task/a/artifacts/%2e%2e/secret', '/api/notes/a/media?playback=true', '/api/task/a/artifacts/media%5csecret', '/api/files/a/content#token', '/api/task/a/artifacts/screenshots/frame.jpg', '/api/task/a/artifacts/media/.playback-preview/video.mp4', '/api/task/a/artifacts/media/frames/frame.jpg'])('rejects nonoriginal source %s before any request or native action', async url => {
  await expect(revealOriginalFile(url)).rejects.toThrow('未通过核验')
  expect(apiJson).not.toHaveBeenCalled(); expect(invoke).not.toHaveBeenCalled()
})
it.each(['relative.webm', '\\\\server\\share\\source.webm', 'https://example.invalid/source.webm', 'D:\\source\\..\\secret', 'D:\\source\nsecret'])('rejects an invalid native response path %s', async path => {
  vi.mocked(apiJson).mockResolvedValue({ local_path_protocol: 1, absolute_path: path })
  await expect(revealOriginalFile('/api/notes/a/media')).rejects.toThrow('未核验')
  expect(invoke).not.toHaveBeenCalled()
})
it('a late response after account/selection changes cannot open the old file', async () => {
  let finish!: (value: unknown) => void, current = true
  vi.mocked(apiJson).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const result = revealOriginalFile('/api/notes/a/media', () => current)
  current = false; finish({ local_path_protocol: 1, absolute_path: 'D:\\recordings\\source.webm' })
  expect(await result).toBe('cancelled'); expect(invoke).not.toHaveBeenCalled()
})
it('an ownership error is surfaced without falling back to download or a different original', async () => {
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('原文件不存在或无权访问'))
  await expect(revealOriginalFile('/api/notes/a/media')).rejects.toThrow('不存在或无权访问')
  expect(invoke).not.toHaveBeenCalled(); expect(apiJson).toHaveBeenCalledTimes(1)
})
it('does not expose the native operation to a browser runtime', async () => {
  vi.mocked(isTauriRuntime).mockReturnValue(false)
  await expect(revealOriginalFile('/api/notes/a/media')).rejects.toThrow('桌面端应用')
  expect(apiJson).not.toHaveBeenCalled(); expect(invoke).not.toHaveBeenCalled()
})
it('uses a retained task identifier without inventing an artifact filename', async () => {
  const taskId = 'd211c3a9-31ac-53de-957c-5cc41f97d0a8'
  expect(await revealOriginalFile({ taskId })).toBe('shown')
  expect(apiJson).toHaveBeenCalledWith(`/api/task/${taskId}/original/local-path`, expect.any(Object))
})
