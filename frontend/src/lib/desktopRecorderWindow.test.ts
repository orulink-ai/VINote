import { beforeEach, describe, expect, it, vi } from 'vitest'
import { closeCurrentRecorderWindow, openRecorderWindowWhenReady } from './desktopRecorderWindow'

const nativeWindow = vi.hoisted(() => ({ close: vi.fn(), hide: vi.fn() }))
const invokeMock = vi.hoisted(() => vi.fn())
const eventMock = vi.hoisted(() => ({ emit: vi.fn(), listen: vi.fn() }))
vi.mock('@tauri-apps/api/window', () => ({ getCurrentWindow: () => nativeWindow }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))
vi.mock('@tauri-apps/api/event', () => eventMock)
vi.mock('./desktopMicrophonePermission', () => ({ isTauriRuntime: () => true }))

describe('closing the desktop recorder', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    window.history.replaceState({}, '', '/?recorderWindow=1')
    eventMock.listen.mockResolvedValue(vi.fn())
    invokeMock.mockResolvedValue(undefined)
  })
  it('closes a shell with close permission', async () => {
    await closeCurrentRecorderWindow()
    expect(nativeWindow.close).toHaveBeenCalledOnce()
    expect(nativeWindow.hide).not.toHaveBeenCalled()
  })
  it('hides an older shell that lacks close permission after hot reload', async () => {
    nativeWindow.close.mockRejectedValue('window.close not allowed. Permissions: core:window:allow-close')
    await closeCurrentRecorderWindow()
    expect(nativeWindow.hide).toHaveBeenCalledOnce()
  })
  it('does not swallow unrelated native failures', async () => {
    nativeWindow.close.mockRejectedValue(new Error('window unavailable'))
    await expect(closeCurrentRecorderWindow()).rejects.toThrow('window unavailable')
    expect(nativeWindow.hide).not.toHaveBeenCalled()
  })

  it('waits for the packaged recorder page to report ready', async () => {
    window.history.replaceState({}, '', '/')
    let readyHandler: (() => void) | undefined
    eventMock.listen.mockImplementation(async (_event, handler) => {
      readyHandler = handler
      return vi.fn()
    })
    invokeMock.mockImplementation(async (command) => {
      if (command === 'open_recorder_window') {
        readyHandler?.()
        return 'created'
      }
      return undefined
    })

    await expect(openRecorderWindowWhenReady()).resolves.toBe('created')
    expect(eventMock.listen).toHaveBeenCalledWith('vinote-recorder-ready', expect.any(Function))
    expect(invokeMock).toHaveBeenCalledWith('open_recorder_window')
    expect(invokeMock).not.toHaveBeenCalledWith('close_recorder_window')
  })

  it('closes a packaged recorder window that never becomes ready', async () => {
    window.history.replaceState({}, '', '/')
    vi.useFakeTimers()
    try {
      const opening = openRecorderWindowWhenReady(100)
      const rejected = expect(opening).rejects.toThrow('recorder_window_load_timeout')
      await vi.advanceTimersByTimeAsync(100)
      await rejected
      expect(invokeMock).toHaveBeenCalledWith('close_recorder_window')
    } finally {
      vi.useRealTimers()
    }
  })
})
