import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SavedRecordingActions } from './SavedRecordingActions'
import { apiJson } from '../../lib/api'

vi.mock('../../lib/api', () => ({ apiJson: vi.fn(), apiFetch: vi.fn() }))
vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ locale: 'zh-CN' }) }))
const info = { available: true, deleted: false, can_delete: true, filename: 'meeting.m4a', size_bytes: 1000 }
beforeEach(() => { vi.mocked(apiJson).mockResolvedValue(info) })
afterEach(() => { cleanup(); vi.resetAllMocks() })

it('keeps the player and note intact when deletion fails', async () => {
  const deleted = vi.fn()
  render(<><audio data-testid="original" src="/api/notes/note-a/media" /><SavedRecordingActions noteId="note-a" title="会议" onDeleted={deleted} /></>)
  fireEvent.click(await screen.findByText('管理原录音'))
  fireEvent.click(await screen.findByRole('button', { name: '删除录制' }))
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('删除失败，请重试'))
  fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
  await screen.findByText('删除失败，请重试')
  expect(screen.getByTestId('original').getAttribute('src')).toBe('/api/notes/note-a/media')
  expect(deleted).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: '导出原音频' })).toBeEnabled()
})

it('can retry a failed recording lookup without leaving the meeting', async () => {
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('读取失败'))
  render(<SavedRecordingActions noteId="note-a" title="会议" onDeleted={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: '重新加载录制' }))
  expect(await screen.findByRole('button', { name: '导出原音频' })).toBeEnabled()
})
