import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { OriginalDownloadButton } from './OriginalDownloadButton'
import { apiFetch } from '@/lib/api'
import { downloadOriginalFile, type DownloadProgressCallback, type DownloadResult } from '@/lib/recordingDownload'
import { useAuthStore } from '@/stores/authStore'
vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }))
vi.mock('@/lib/recordingDownload', async original => ({ ...await original<typeof import('@/lib/recordingDownload')>(), downloadOriginalFile: vi.fn() }))
beforeEach(() => { useAuthStore.setState({ user: { id: 'owner' } as never }) })
afterEach(() => { cleanup(); vi.resetAllMocks() })

it.each(['saved', 'cancelled', 'browser_started'] as const)('shows a distinct %s result without altering the original', async result => {
  vi.mocked(downloadOriginalFile).mockResolvedValueOnce(result)
  render(<OriginalDownloadButton url="/api/task/source/artifacts/source.webm" filename="source.webm" />)
  fireEvent.click(screen.getByRole('button', { name: '导出原文件' }))
  expect(await screen.findByRole('status')).toHaveTextContent(result === 'saved' ? '已保存到所选位置' : result === 'cancelled' ? '已取消导出' : '下载列表')
  expect(apiFetch).not.toHaveBeenCalled() // Picker cancellation/handoff is controlled by the bridge mock.
})

it('exports exact original URL on demand and locks repeated clicks until the result', async () => {
  let finish!: (result: DownloadResult) => void
  vi.mocked(downloadOriginalFile).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  render(<OriginalDownloadButton url="/api/task/canonical/artifacts/media.webm" filename="media.webm" />)
  const button = screen.getByRole('button', { name: '导出原文件' })
  fireEvent.click(button); fireEvent.click(button)
  expect(button).toBeDisabled(); expect(button).toHaveAttribute('aria-busy', 'true')
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  expect(downloadOriginalFile).toHaveBeenCalledOnce()
  expect(downloadOriginalFile).toHaveBeenCalledWith('/api/task/canonical/artifacts/media.webm', 'media.webm', expect.any(Function), expect.any(AbortSignal), expect.any(Function))
  const progress = vi.mocked(downloadOriginalFile).mock.calls[0][4]!
  act(() => progress({ stage: 'choosing_destination' }))
  expect(screen.getByRole('status')).toHaveTextContent('请选择原文件保存位置')
  act(() => progress({ stage: 'waiting_response' }))
  expect(screen.getByRole('status')).toHaveTextContent('正在等待原文件响应')
  act(() => progress({ stage: 'writing', writtenBytes: 1024 * 1024, totalBytes: 2 * 1024 * 1024 }))
  expect(screen.getByRole('status')).toHaveTextContent('1.0 MB / 2.0 MB')
  act(() => progress({ stage: 'finishing', writtenBytes: 2 * 1024 * 1024, totalBytes: 2 * 1024 * 1024 }))
  expect(screen.getByRole('status')).toHaveTextContent('正在完成落盘')
  expect(screen.getByRole('status')).not.toHaveTextContent('已保存')
  await act(async () => finish('saved'))
  expect(button).toBeEnabled(); expect(screen.getByRole('status')).toHaveTextContent('已保存')
})

it('reports write failure with explicit retry and no success message', async () => {
  vi.mocked(downloadOriginalFile).mockRejectedValueOnce(new Error('磁盘写入失败')).mockResolvedValueOnce('cancelled')
  render(<OriginalDownloadButton url="/api/notes/source/media" filename="source.webm" />)
  fireEvent.click(screen.getByRole('button', { name: '导出原文件' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('磁盘写入失败')
  expect(screen.queryByRole('status')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '重试导出原文件' }))
  expect(await screen.findByRole('status')).toHaveTextContent('已取消导出')
  expect(screen.queryByRole('alert')).toBeNull()
})

it('invalidates an old owner/file result and its permission to write', async () => {
  let finish!: (result: DownloadResult) => void
  let current!: () => boolean
  let progress!: DownloadProgressCallback
  vi.mocked(downloadOriginalFile).mockImplementationOnce((_url, _filename, valid, _signal, onProgress) => {
    progress = onProgress!
    current = valid!; return new Promise(resolve => { finish = resolve })
  })
  const view = render(<OriginalDownloadButton url="/api/notes/old/media" filename="old.webm" />)
  fireEvent.click(screen.getByRole('button', { name: '导出原文件' }))
  act(() => useAuthStore.setState({ user: { id: 'other' } as never }))
  view.rerender(<OriginalDownloadButton url="/api/notes/new/media" filename="new.webm" />)
  expect(current()).toBe(false)
  act(() => progress({ stage: 'writing', writtenBytes: 1000 }))
  expect(screen.queryByRole('status')).toBeNull()
  await act(async () => finish('saved'))
  expect(screen.queryByRole('status')).toBeNull()
  expect(screen.getByRole('button', { name: '导出原文件' })).toBeEnabled()
})

it('offers cancellation during export and reports cancelled rather than failed or saved', async () => {
  vi.mocked(downloadOriginalFile).mockImplementationOnce((_url, _filename, _valid, signal) => new Promise(resolve => {
    signal!.addEventListener('abort', () => resolve('cancelled'), { once: true })
  }))
  render(<OriginalDownloadButton url="/api/notes/source/media" filename="source.webm" />)
  fireEvent.click(screen.getByRole('button', { name: '导出原文件' }))
  fireEvent.click(screen.getByRole('button', { name: '取消导出' }))
  await vi.waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('已取消导出'))
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByRole('button', { name: '导出原文件' })).toBeEnabled()
  await vi.waitFor(() => expect(screen.getByRole('button', { name: '导出原文件' })).toHaveFocus())
})
