import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ResultPreview } from './ResultPreview'
import { apiJson, ApiError } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import * as presentation from '@/lib/summaryPresentation'
import * as recording from '@/lib/recordingDownload'
vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(), apiJson: vi.fn() }))
vi.mock('@/components/Markdown/MarkdownContent', () => ({ MarkdownContent: ({ content }: { content: string }) => <article>{content}</article> }))
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
const task = '11111111-1111-4111-8111-111111111111'
const metadata = { protocol: 1, task_id: task, content_depth: 'brief', presentation: 'html' }

it('uses a sandboxed HTML preview of this saved body and exposes a real export', async () => {
  vi.mocked(apiJson).mockResolvedValue(metadata)
  render(<ResultPreview taskId={task} title="Topic" content="# Automatic facts" />)
  await waitFor(() => expect(screen.getByTitle('安全 HTML 纪要预览')).toHaveAttribute('sandbox', ''))
  expect(screen.getByTitle('安全 HTML 纪要预览')).toHaveAttribute('srcdoc', expect.stringContaining('Automatic facts'))
  expect(screen.getByTitle('安全 HTML 纪要预览')).toHaveAttribute('referrerpolicy', 'no-referrer')
  expect(screen.getByTitle('安全 HTML 纪要预览')).toHaveClass('min-h-0', 'flex-1')
  expect(screen.getByTitle('安全 HTML 纪要预览')).not.toHaveClass('min-h-[65vh]')
  expect(screen.getByTitle('安全 HTML 纪要预览').parentElement).toHaveAttribute('data-summary-html-preview')
  expect(screen.getByTitle('安全 HTML 纪要预览').parentElement).toHaveClass('min-h-40')
  expect(screen.getByRole('button', { name: '导出 HTML' })).toBeInTheDocument()
})

it('keeps historical Markdown readable when no presentation metadata exists', async () => {
  vi.mocked(apiJson).mockRejectedValue(new ApiError('legacy', 404, {}))
  render(<ResultPreview taskId={task} content="Historical saved body" />)
  expect(screen.getByText('Historical saved body')).toBeInTheDocument()
  await waitFor(() => expect(apiJson).toHaveBeenCalled())
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByText('Historical saved body').parentElement).not.toHaveAttribute('data-summary-html-preview')
})

it('does not show a late previous account presentation after switching', async () => {
  useAuthStore.setState({ user: { id: 'first' } as never })
  let resolve!: (value: unknown) => void
  vi.mocked(apiJson).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    .mockRejectedValue(new ApiError('other owner', 404, {}))
  render(<ResultPreview taskId={task} content="Body" />)
  act(() => useAuthStore.setState({ user: { id: 'second' } as never }))
  await act(async () => resolve(metadata))
  expect(screen.queryByTitle('安全 HTML 纪要预览')).toBeNull()
})

it('exports only the frozen saved body when split preview contains unsaved changes', async () => {
  vi.mocked(apiJson).mockResolvedValue(metadata)
  const create = vi.fn(() => 'blob:export')
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: vi.fn() })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  render(<ResultPreview taskId={task} title="Topic" content="# Unsaved draft" exportContent="# Saved facts" />)
  fireEvent.click(await screen.findByRole('button', { name: '导出 HTML' }))
  await waitFor(() => expect(create).toHaveBeenCalled())
  const blob = create.mock.calls[0][0] as unknown as Blob
  const text = await new Promise<string>(resolve => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(blob) })
  expect(text).toContain('Saved facts')
  expect(text).not.toContain('Unsaved draft')
  click.mockRestore(); vi.unstubAllGlobals()
})

it('cancels a late HTML export after an account switch', async () => {
  useAuthStore.setState({ user: { id: 'first' } as never })
  vi.mocked(apiJson).mockResolvedValue({ ...metadata, presentation: 'text' })
  let resolve!: (value: string) => void
  vi.spyOn(presentation, 'buildSummaryHtml').mockImplementation(() => new Promise(done => { resolve = done }))
  const create = vi.fn()
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: vi.fn() })
  render(<ResultPreview taskId={task} title="Topic" content="# Saved facts" />)
  fireEvent.click(await screen.findByRole('button', { name: '导出 HTML' }))
  act(() => useAuthStore.setState({ user: { id: 'second' } as never }))
  await act(async () => resolve('<html>Old account</html>'))
  expect(create).not.toHaveBeenCalled()
})

it('never exports compact preview CSS, including when preview and saved body are identical', async () => {
  vi.mocked(apiJson).mockResolvedValue(metadata)
  const create = vi.fn(() => 'blob:export')
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: vi.fn() })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  const content = '# Saved facts\n\nFinal paragraph stays complete.'
  render(<ResultPreview taskId={task} title="Topic" content={content} />)
  const frame = await screen.findByTitle('安全 HTML 纪要预览')
  expect(frame.getAttribute('srcdoc')).toContain('font-size:1.25rem')
  fireEvent.click(screen.getByRole('button', { name: '导出 HTML' }))
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
  const blob = create.mock.calls[0][0] as unknown as Blob
  const output = await new Promise<string>(resolve => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(blob) })
  expect(output).toBe(await presentation.buildSummaryHtml(content, 'Topic', task))
  expect(output).not.toContain('font-size:1.25rem')
  expect(new DOMParser().parseFromString(output, 'text/html').body.innerHTML).toBe(new DOMParser().parseFromString(frame.getAttribute('srcdoc')!, 'text/html').body.innerHTML)
})

it.each(['same', 'different'] as const)('isolates completed HTML save notices across A→B→A saved notes with %s body', async kind => {
  vi.mocked(apiJson).mockResolvedValue(metadata)
  const download = vi.spyOn(recording, 'downloadRecording').mockResolvedValue('saved')
  const a = '# Shared body', b = kind === 'same' ? a : '# Different body'
  // Deliberately identical task/title: body alone cannot establish note identity.
  const view = render(<ResultPreview noteId="note-A" taskId={task} title="Shared title" content={a} />)
  fireEvent.click(await screen.findByRole('button', { name: '导出 HTML' }))
  expect(await screen.findByText('HTML 纪要已保存到所选位置。')).toBeInTheDocument()
  view.rerender(<ResultPreview noteId="note-B" taskId={task} title="Shared title" content={b} />)
  await screen.findByTitle('安全 HTML 纪要预览')
  expect(screen.queryByText('HTML 纪要已保存到所选位置。')).toBeNull()
  expect(screen.getByRole('button', { name: '导出 HTML' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: '导出 HTML' }))
  expect(await screen.findByText('HTML 纪要已保存到所选位置。')).toBeInTheDocument()
  view.rerender(<ResultPreview noteId="note-A" taskId={task} title="Shared title" content={a} />)
  await screen.findByTitle('安全 HTML 纪要预览')
  expect(screen.queryByText('HTML 纪要已保存到所选位置。')).toBeNull()
  expect(download).toHaveBeenCalledTimes(2)
  expect(apiJson).toHaveBeenCalledTimes(3)
})

it.each(['saved', 'cancelled', 'failure'] as const)('rejects a pending old-note %s result after same-body A→B→A, without blocking the current export', async outcome => {
  vi.mocked(apiJson).mockResolvedValue(metadata)
  let resolve!: (result: 'saved' | 'cancelled') => void, reject!: (cause: Error) => void
  const pending: Promise<'saved' | 'cancelled'> = new Promise((done, fail) => { resolve = done; reject = fail })
  const download = vi.spyOn(recording, 'downloadRecording').mockImplementationOnce(() => pending).mockResolvedValue('saved')
  const props = { taskId: task, title: 'Same title', content: '# Identical final body' }
  const view = render(<ResultPreview noteId="note-A" {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '导出 HTML' }))
  expect(screen.getByRole('button', { name: '正在准备导出…' })).toBeDisabled()
  const oldCurrent = download.mock.calls[0][3]!
  const oldSource = download.mock.calls[0][0] as () => Promise<Blob>
  expect(oldCurrent()).toBe(true)
  view.rerender(<ResultPreview noteId="note-B" {...props} />)
  await screen.findByTitle('安全 HTML 纪要预览')
  expect(oldCurrent()).toBe(false)
  expect(screen.getByRole('button', { name: '导出 HTML' })).toBeEnabled()
  view.rerender(<ResultPreview noteId="note-A" {...props} />)
  await screen.findByTitle('安全 HTML 纪要预览')
  expect(oldCurrent()).toBe(false)
  await expect(oldSource()).rejects.toThrow('纪要或账号已变化')
  await act(async () => { if (outcome === 'failure') reject(new Error('old save failed')); else resolve(outcome) })
  expect(screen.queryByText('HTML 纪要已保存到所选位置。')).toBeNull()
  expect(screen.queryByText('已取消 HTML 导出。')).toBeNull()
  expect(screen.queryByText('HTML 导出失败，请重试。')).toBeNull()
  expect(screen.getByRole('button', { name: '导出 HTML' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: '导出 HTML' }))
  expect(await screen.findByText('HTML 纪要已保存到所选位置。')).toBeInTheDocument()
})
