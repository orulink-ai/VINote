import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SavedRecordingActions } from './SavedRecordingActions'
import { apiJson, apiFetch } from '../../lib/api'
import { downloadOriginalFile } from '../../lib/recordingDownload'

vi.mock('../../lib/api', () => ({ apiJson: vi.fn(), apiFetch: vi.fn() }))
vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ locale: 'zh-CN' }) }))
vi.mock('../../lib/recordingDownload', async importOriginal => ({ ...await importOriginal<typeof import('../../lib/recordingDownload')>(), downloadOriginalFile: vi.fn() }))
const info = { available: true, deleted: false, can_delete: true, filename: 'meeting.m4a', size_bytes: 1000 }
beforeEach(() => { vi.mocked(apiJson).mockResolvedValue(info); vi.mocked(downloadOriginalFile).mockResolvedValue('browser_started') })
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

it('labels video correctly and downloads the original endpoint, never its playback derivative', async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(new Blob(['original']), { status: 200 }));
  render(<SavedRecordingActions noteId="video-note" title="合成视频" mediaKind="video" onDeleted={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: '导出原视频' }));
  await vi.waitFor(() => expect(downloadOriginalFile).toHaveBeenCalled());
  expect(downloadOriginalFile).toHaveBeenCalledWith('/api/notes/video-note/media', 'meeting.m4a', expect.any(Function), expect.any(AbortSignal));
  expect(await screen.findByRole('status')).toHaveTextContent('下载列表');
});

it('keeps lookup failure distinct from missing or loading in compact mode', async () => {
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('读取失败'));
  render(<SavedRecordingActions noteId="note-a" title="合成音频" compact onDeleted={vi.fn()} />);
  await screen.findByText('读取失败');
  expect(screen.queryByText('正在读取原文件状态…')).toBeNull();
  expect(screen.getByText('原文件状态未读取')).toBeVisible();
  expect(screen.queryByText('暂无可用原文件')).toBeNull();
});

it('keeps a confirmed absent original distinct from deletion and preserves text', async () => {
  vi.mocked(apiJson).mockResolvedValueOnce({ ...info, available: false, deleted: false });
  render(<SavedRecordingActions noteId="note-a" title="合成音频" onDeleted={vi.fn()} />);
  expect(await screen.findByText('暂无可用原文件')).toBeVisible();
  expect(screen.queryByText(/文件已删除/)).toBeNull();
  expect(screen.getByRole('button', { name: '导出原音频' })).toBeDisabled();
});

it('ignores original metadata returned for the previously selected note', async () => {
  let finish!: (value: typeof info) => void;
  vi.mocked(apiJson).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce({ ...info, available: false });
  const view = render(<SavedRecordingActions noteId="old-note" title="旧合成录制" onDeleted={vi.fn()} />);
  view.rerender(<SavedRecordingActions noteId="new-note" title="新合成录制" onDeleted={vi.fn()} />);
  await screen.findByText('暂无可用原文件');
  await act(async () => finish(info));
  await vi.waitFor(() => expect(screen.getByRole('button', { name: '导出原音频' })).toBeDisabled());
  expect(screen.queryByText(/原文件已保留/)).toBeNull();
});
