import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { OriginalLocationButton } from './OriginalLocationButton'
import { revealOriginalFile } from '@/lib/originalLocation'
import { isTauriRuntime } from '@/lib/desktopMicrophonePermission'
import { useAuthStore } from '@/stores/authStore'
vi.mock('@/lib/originalLocation', () => ({ revealOriginalFile: vi.fn() }))
vi.mock('@/lib/desktopMicrophonePermission', () => ({ isTauriRuntime: vi.fn() }))
beforeEach(() => { vi.mocked(isTauriRuntime).mockReturnValue(true); useAuthStore.setState({ user: { id: 'original-owner' } as never }) })
afterEach(() => { cleanup(); vi.resetAllMocks() })
it('opens only on demand, locks duplicate clicks, and reports the native result', async () => {
  let finish!: (result: 'shown') => void
  vi.mocked(revealOriginalFile).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  render(<OriginalLocationButton url="/api/notes/a/media" />)
  expect(revealOriginalFile).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '在文件夹中显示' }))
  const pending = screen.getByRole('button', { name: '正在打开文件夹…' })
  expect(pending).toBeDisabled(); fireEvent.click(pending)
  expect(revealOriginalFile).toHaveBeenCalledTimes(1)
  await act(async () => finish('shown'))
  expect(screen.getByRole('status')).toHaveTextContent('定位原文件')
})
it('keeps missing-file errors beside the action and does not claim success', async () => {
  vi.mocked(revealOriginalFile).mockRejectedValueOnce(new Error('当前设备找不到可核验的原文件'))
  render(<OriginalLocationButton url="/api/notes/a/media" />)
  fireEvent.click(screen.getByRole('button', { name: '在文件夹中显示' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('找不到')
  expect(screen.queryByRole('status')).toBeNull()
  expect(screen.getByRole('button', { name: '在文件夹中显示' })).toBeEnabled()
})
it('invalidates the old path immediately when selection or owner changes', async () => {
  let finish!: (result: 'shown') => void, current!: () => boolean
  vi.mocked(revealOriginalFile).mockImplementationOnce((_url, valid) => { current = valid!; return new Promise(resolve => { finish = resolve }) })
  const view = render(<OriginalLocationButton url="/api/notes/a/media" />)
  fireEvent.click(screen.getByRole('button', { name: '在文件夹中显示' }))
  act(() => useAuthStore.setState({ user: { id: 'different-owner' } as never }))
  view.rerender(<OriginalLocationButton url="/api/notes/b/media" />)
  expect(current()).toBe(false)
  await act(async () => finish('shown'))
  expect(screen.queryByRole('status')).toBeNull()
  expect(screen.getByRole('button', { name: '在文件夹中显示' })).toBeEnabled()
})
it('hides OS location controls in browsers and disables unavailable originals', () => {
  const view = render(<OriginalLocationButton url="/api/notes/a/media" disabled />)
  expect(screen.getByRole('button', { name: '在文件夹中显示' })).toBeDisabled()
  vi.mocked(isTauriRuntime).mockReturnValue(false)
  view.rerender(<OriginalLocationButton url="/api/notes/a/media" />)
  expect(screen.queryByRole('button')).toBeNull(); expect(revealOriginalFile).not.toHaveBeenCalled()
})
it('does not revive an old file action when the account changes away and back in one render batch', async () => {
  let finish!: (result: 'shown') => void, current!: () => boolean
  vi.mocked(revealOriginalFile).mockImplementationOnce((_url, valid) => { current = valid!; return new Promise(resolve => { finish = resolve }) })
  render(<OriginalLocationButton url="/api/notes/a/media" />)
  fireEvent.click(screen.getByRole('button', { name: '在文件夹中显示' }))
  act(() => {
    useAuthStore.setState({ user: { id: 'different-owner' } as never })
    useAuthStore.setState({ user: { id: 'original-owner' } as never })
  })
  expect(current()).toBe(false)
  await act(async () => finish('shown'))
  expect(screen.queryByRole('status')).toBeNull()
})
