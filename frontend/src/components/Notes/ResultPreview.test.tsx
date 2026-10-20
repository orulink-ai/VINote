import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ResultPreview } from './ResultPreview'
import { apiJson, ApiError } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import * as presentation from '@/lib/summaryPresentation'
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
  expect(screen.getByRole('button', { name: '导出 HTML' })).toBeInTheDocument()
})

it('keeps historical Markdown readable when no presentation metadata exists', async () => {
  vi.mocked(apiJson).mockRejectedValue(new ApiError('legacy', 404, {}))
  render(<ResultPreview taskId={task} content="Historical saved body" />)
  expect(screen.getByText('Historical saved body')).toBeInTheDocument()
  await waitFor(() => expect(apiJson).toHaveBeenCalled())
  expect(screen.queryByRole('alert')).toBeNull()
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
