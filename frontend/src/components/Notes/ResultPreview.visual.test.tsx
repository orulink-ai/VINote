import { webcrypto } from 'node:crypto'
import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ResultPreview } from './ResultPreview'
import { SummaryVisualPanel } from './visual/SummaryVisualPanel'
import { apiJson, ApiError } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { downloadRecording } from '@/lib/recordingDownload'
import * as graphicExport from '@/lib/summaryVisualExport'
import { makeVisualFixture, visualSavedBody, visualTask, visualTitle } from '../../../test-fixtures/summaryVisual'

vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(), apiJson: vi.fn() }))
vi.mock('@/lib/recordingDownload', () => ({ downloadRecording: vi.fn() }))
vi.mock('@/components/Markdown/MarkdownContent', () => ({ MarkdownContent: ({ content }: { content: string }) => <article>{content}</article> }))
beforeEach(() => { vi.stubGlobal('crypto', webcrypto); useAuthStore.setState({ user: { id: 'synthetic-owner' } as never }) })
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
async function mockPresentation(presentation: 'comic' | 'infographic') {
  const visual = await makeVisualFixture(presentation)
  vi.mocked(apiJson).mockImplementation(async path => path.endsWith('/summary-presentation') ? { protocol: 1, task_id: visualTask, content_depth: 'detailed', presentation } : visual)
  return visual
}

it('shows real frame assets with grounded descriptions, keeps body, and only GETs this task', async () => {
  await mockPresentation('comic')
  const jump = vi.fn()
  render(<ResultPreview taskId={visualTask} title={visualTitle} content={visualSavedBody} onVideoJump={jump} />)
  const images = await screen.findAllByRole('img')
  expect(images).toHaveLength(2)
  expect(images[0]).toHaveAttribute('src', `/api/task/${visualTask}/artifacts/screenshots/summary-source-0.jpg`)
  expect(screen.getByRole('article').textContent).toBe(visualSavedBody)
  expect(screen.queryByText('漫画')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '播放 01:04 的原录屏' }))
  expect(jump).toHaveBeenCalledWith(64.2)
  expect(vi.mocked(apiJson).mock.calls.map(call => call[0])).toEqual([`/api/task/${visualTask}/summary-presentation`, `/api/task/${visualTask}/summary-visual`])
  expect(vi.mocked(apiJson).mock.calls.every(call => call[1] === undefined)).toBe(true)
})

it('does not replace an unreadable real screenshot with a decorative generated card', async () => {
  await mockPresentation('comic')
  render(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  const images = await screen.findAllByRole('img')
  fireEvent.error(images[0])
  expect(screen.getByText('此处原始画面暂不可用，说明和正文保留。')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '重新读取画面' }))
  expect(screen.getAllByRole('img')).toHaveLength(2)
})

it('shows all supplied relations as text and never converts technical labels into links', async () => {
  const visual = await mockPresentation('infographic')
  visual.diagram!.nodes[0].grounded_label = '缓存延迟 < 120ms'
  render(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  expect(await screen.findByRole('region', { name: '信息图，可横向滚动查看' })).toBeInTheDocument()
  expect(screen.getByRole('list', { name: '图中关系与原文依据' }).children).toHaveLength(3)
  expect(document.querySelector('svg a,svg image,script,foreignObject')).toBeNull()
})

it('keeps historical 404 and an invalid spec recoverable through the saved body', async () => {
  const visual = await mockPresentation('comic'); visual.scenes[0].block_ids = ['missing']
  const view = render(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  expect(await screen.findByText('图形引用的正文依据缺失，未补造关联。')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '导出 PNG' })).toBeNull()
  expect(screen.getByRole('article').textContent).toBe(visualSavedBody)
  view.unmount()
  vi.mocked(apiJson).mockImplementation(async path => {
    if (path.endsWith('/summary-visual')) throw new ApiError('legacy', 404, {})
    return { protocol: 1, task_id: visualTask, content_depth: 'detailed', presentation: 'comic' }
  })
  render(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  expect(await screen.findByText('此版本尚无可核验图形，已保留正文。')).toBeInTheDocument()
})

it('binds the graphic to exportContent and not an unsaved preview draft', async () => {
  await mockPresentation('comic')
  const view = render(<ResultPreview taskId={visualTask} content="Unsaved edits" exportContent={visualSavedBody} />)
  expect(await screen.findAllByRole('img')).toHaveLength(2)
  expect(screen.getByRole('article')).toHaveTextContent('Unsaved edits')
  view.rerender(<ResultPreview taskId={visualTask} content="Changed saved revision" exportContent="Changed saved revision" />)
  expect(await screen.findByText('图形对应的已保存正文已变化，请查看当前正文。')).toBeInTheDocument()
  expect(screen.queryAllByRole('img')).toHaveLength(0)
})

it('ignores a late previous-account visual response', async () => {
  const visual = await makeVisualFixture()
  let finish!: (value: unknown) => void
  vi.mocked(apiJson).mockImplementation(async path => {
    if (useAuthStore.getState().user?.id !== 'synthetic-owner') throw new ApiError('other owner', 404, {})
    if (path.endsWith('/summary-presentation')) return { protocol: 1, task_id: visualTask, content_depth: 'brief', presentation: 'comic' }
    return new Promise(resolve => { finish = resolve })
  })
  render(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  await waitFor(() => expect(finish).toBeTypeOf('function'))
  act(() => useAuthStore.setState({ user: { id: 'other-owner' } as never }))
  await act(async () => finish(visual))
  expect(screen.queryAllByRole('img')).toHaveLength(0)
})

it('exports through the existing native-capable save flow once and reports graphic-specific success', async () => {
  const visual = await makeVisualFixture('infographic')
  let finish!: (value: 'saved') => void
  vi.mocked(downloadRecording).mockImplementation(async (source, _title, filename, current) => {
    expect(filename).toMatch(/\.svg$/)
    expect(current!()).toBe(true)
    const blob = await (source as () => Promise<Blob>)()
    expect(blob.type).toContain('image/svg+xml')
    return new Promise(resolve => { finish = resolve })
  })
  render(<SummaryVisualPanel visual={visual} savedBody={visualSavedBody} title={visualTitle} />)
  const trigger = screen.getByRole('button', { name: '导出 SVG' })
  fireEvent.click(trigger); fireEvent.click(trigger)
  await waitFor(() => expect(finish).toBeTypeOf('function'))
  expect(downloadRecording).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: '导出 PNG' })).toBeDisabled()
  await act(async () => finish('saved'))
  expect(screen.getByText('图形已保存到所选位置。')).toBeInTheDocument()
  expect(screen.queryByText(/原文件已保存/)).toBeNull()
})

it('cancelled save does not prepare images or pixels and remains retryable', async () => {
  const visual = await makeVisualFixture()
  const prepare = vi.spyOn(graphicExport, 'buildSummaryVisualPng')
  vi.mocked(downloadRecording).mockResolvedValue('cancelled')
  render(<SummaryVisualPanel visual={visual} savedBody={visualSavedBody} title={visualTitle} />)
  fireEvent.click(screen.getByRole('button', { name: '导出 PNG' }))
  expect(await screen.findByText('已取消图形导出。')).toBeInTheDocument()
  expect(prepare).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: '导出 PNG' })).toBeEnabled()
})

it('keeps save usable under the application StrictMode effect cycle', async () => {
  const visual = await makeVisualFixture('infographic')
  vi.mocked(downloadRecording).mockImplementation(async (_source, _title, _filename, current) => {
    expect(current!()).toBe(true); return 'cancelled'
  })
  render(<StrictMode><SummaryVisualPanel visual={visual} savedBody={visualSavedBody} title={visualTitle} /></StrictMode>)
  fireEvent.click(screen.getByRole('button', { name: '导出 SVG' }))
  expect(await screen.findByText('已取消图形导出。')).toBeInTheDocument()
})

it('a changed account or saved body invalidates a pending export', async () => {
  const visual = await makeVisualFixture('infographic')
  let current!: () => boolean, finish!: (value: 'saved') => void
  vi.mocked(downloadRecording).mockImplementation(async (_source, _title, _filename, valid) => {
    current = valid!; return new Promise(resolve => { finish = resolve })
  })
  const view = render(<SummaryVisualPanel visual={visual} savedBody={visualSavedBody} title={visualTitle} />)
  fireEvent.click(screen.getByRole('button', { name: '导出 SVG' }))
  expect(current()).toBe(true)
  view.rerender(<SummaryVisualPanel visual={visual} savedBody="Changed saved body" title={visualTitle} />)
  expect(current()).toBe(false)
  act(() => useAuthStore.setState({ user: { id: 'other-owner' } as never }))
  await act(async () => finish('saved'))
  expect(screen.queryByText('图形已保存到所选位置。')).toBeNull()
})

it('invalidates HTML export on A→B→A even before React has remounted the page', async () => {
  vi.mocked(apiJson).mockResolvedValue({ protocol: 1, task_id: visualTask, content_depth: 'brief', presentation: 'text' })
  let current!: () => boolean, source!: () => Promise<Blob>, finish!: (value: 'cancelled') => void
  vi.mocked(downloadRecording).mockImplementation(async (prepare, _title, _filename, valid) => {
    source = prepare as () => Promise<Blob>; current = valid!
    return new Promise(resolve => { finish = resolve })
  })
  render(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  fireEvent.click(await screen.findByRole('button', { name: '导出 HTML' }))
  expect(current()).toBe(true)
  act(() => {
    useAuthStore.setState({ user: { id: 'other-owner' } as never })
    useAuthStore.setState({ user: { id: 'synthetic-owner' } as never })
  })
  expect(current()).toBe(false)
  await expect(source()).rejects.toThrow('账号已变化')
  await act(async () => finish('cancelled'))
  expect(screen.queryByText('HTML 纪要已保存到所选位置。')).toBeNull()
})
