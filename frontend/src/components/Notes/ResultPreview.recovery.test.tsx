import { webcrypto } from 'node:crypto'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ResultPreview } from './ResultPreview'
import { apiJson, ApiError } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import * as runtime from '@/lib/runtimeConfig'
import { makeVisualFixture, visualSavedBody, visualTask } from '../../../test-fixtures/summaryVisual'

vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(), apiJson: vi.fn() }))
vi.mock('@/components/Markdown/MarkdownContent', () => ({ MarkdownContent: ({ content }: { content: string }) => <article>{content}</article> }))
vi.mock('./visual/SummaryVisualPanel', () => ({ SummaryVisualPanel: ({ visual }: { visual: { task_id: string } }) => <section aria-label="Validated graphic">{visual.task_id}</section> }))
const metadata = { protocol: 1, task_id: visualTask, content_depth: 'brief', presentation: 'infographic' }
const metaPath = `/api/task/${visualTask}/summary-presentation`
const visualPath = `/api/task/${visualTask}/summary-visual`
const retry = () => screen.getByRole('button', { name: '重新读取形式与图形' })
const deferred = () => {
  let resolve!: (value: unknown) => void, reject!: (cause: unknown) => void
  const promise = new Promise<unknown>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
function expectOnlyArtifactGets() {
  for (const [path, init] of vi.mocked(apiJson).mock.calls) {
    expect(path).toMatch(/^\/api\/task\/[a-f0-9-]+\/summary-(presentation|visual)$/)
    expect(init?.method ?? 'GET').toBe('GET')
    expect(init?.body).toBeUndefined()
  }
}
beforeEach(() => {
  vi.stubGlobal('crypto', webcrypto)
  useAuthStore.setState({ user: { id: 'owner-a' } as never })
  vi.spyOn(runtime, 'resolveBackendOrigin').mockReturnValue('https://origin-a.example.invalid')
})
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('explicitly re-reads only this task after a presentation failure and preserves the body throughout', async () => {
  const visual = await makeVisualFixture('infographic'), pending = deferred()
  vi.mocked(apiJson).mockRejectedValueOnce(new TypeError('connection failed'))
    .mockImplementationOnce(() => pending.promise).mockResolvedValueOnce(visual)
  render(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('形式信息读取失败')
  fireEvent.click(retry())
  const busy = screen.getByRole('button', { name: '正在重新读取…' })
  expect(busy).toBeDisabled(); fireEvent.click(busy)
  expect(screen.getByRole('article').textContent).toBe(visualSavedBody)
  expect(apiJson).toHaveBeenCalledTimes(2)
  await act(async () => pending.resolve(metadata))
  expect(await screen.findByRole('region', { name: 'Validated graphic' })).toHaveTextContent(visualTask)
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.queryByRole('button', { name: '重新读取形式与图形' })).toBeNull()
  expect(vi.mocked(apiJson).mock.calls.map(([path]) => path)).toEqual([metaPath, metaPath, visualPath])
  expectOnlyArtifactGets()
})

it('recovers a graphic transport failure through a fresh presentation/visual pair, without accepting an invalid plan', async () => {
  const visual = await makeVisualFixture('infographic')
  const invalid = structuredClone(visual); invalid.body_sha256 = '0'.repeat(64)
  vi.mocked(apiJson).mockResolvedValueOnce(metadata).mockRejectedValueOnce(new ApiError('unavailable', 503, {}))
    .mockResolvedValueOnce(metadata).mockResolvedValueOnce(invalid)
    .mockResolvedValueOnce(metadata).mockResolvedValueOnce(visual)
  render(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  await screen.findByText('图形读取失败，已保留正文。')
  fireEvent.click(retry())
  await screen.findByText('图形对应的已保存正文已变化，请查看当前正文。')
  expect(screen.queryByRole('region', { name: 'Validated graphic' })).toBeNull()
  fireEvent.click(retry())
  await screen.findByRole('region', { name: 'Validated graphic' })
  expect(screen.getByRole('article').textContent).toBe(visualSavedBody)
  expect(vi.mocked(apiJson).mock.calls.map(([path]) => path)).toEqual([metaPath, visualPath, metaPath, visualPath, metaPath, visualPath])
  expectOnlyArtifactGets()
})

it.each(['presentation', 'visual'])('preserves the historical %s 404 boundary without retry or generation controls', async kind => {
  vi.mocked(apiJson).mockImplementation(async path => {
    if (kind === 'presentation' || path.endsWith('/summary-visual')) throw new ApiError('historical missing', 404, {})
    return metadata
  })
  render(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  if (kind === 'visual') await screen.findByText('此版本尚无可核验图形，已保留正文。')
  else await waitFor(() => expect(apiJson).toHaveBeenCalledTimes(1))
  expect(screen.getByRole('article').textContent).toBe(visualSavedBody)
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.queryByRole('button', { name: '重新读取形式与图形' })).toBeNull()
  expectOnlyArtifactGets()
})

it('clears the earlier failure if the explicit read finds a historical 404', async () => {
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('offline')).mockRejectedValueOnce(new ApiError('missing', 404, {}))
  render(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  await screen.findByRole('alert'); fireEvent.click(retry())
  await waitFor(() => expect(screen.queryByRole('button', { name: '正在重新读取…' })).toBeNull())
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.queryByRole('button', { name: '重新读取形式与图形' })).toBeNull()
  expect(screen.getByRole('article').textContent).toBe(visualSavedBody)
})

it('rejects foreign task metadata on re-read before requesting any graph', async () => {
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ ...metadata, task_id: 'foreign-task' })
  render(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  await screen.findByRole('alert'); fireEvent.click(retry())
  await screen.findByText('形式信息无法核验，正文仍可阅读。')
  expect(screen.queryByRole('region', { name: 'Validated graphic' })).toBeNull()
  expect(vi.mocked(apiJson).mock.calls.map(([path]) => path)).toEqual([metaPath, metaPath])
})

it.each([
  ['null', null],
  ['unknown protocol', { ...metadata, protocol: 2 }],
  ['unknown presentation', { ...metadata, presentation: 'unknown' }],
  ['unknown depth', { ...metadata, content_depth: 'unknown' }],
])('recovers invalid metadata (%s) only after an explicit artifact GET re-read', async (_kind, invalid) => {
  const visual = await makeVisualFixture('infographic')
  vi.mocked(apiJson).mockResolvedValueOnce(invalid).mockResolvedValueOnce(metadata).mockResolvedValueOnce(visual)
  render(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  await screen.findByText('形式信息无法核验，正文仍可阅读。')
  expect(apiJson).toHaveBeenCalledTimes(1)
  expect(screen.queryByRole('region', { name: 'Validated graphic' })).toBeNull()
  expect(screen.getByRole('article').textContent).toBe(visualSavedBody)
  fireEvent.click(retry())
  await screen.findByRole('region', { name: 'Validated graphic' })
  expect(screen.queryByRole('alert')).toBeNull()
  expect(vi.mocked(apiJson).mock.calls.map(([path]) => path)).toEqual([metaPath, metaPath, visualPath])
  expectOnlyArtifactGets()
})

it.each(['task', 'body', 'account', 'origin'].flatMap(kind => ['presentation', 'visual'].map(stage => [kind, stage])))('ignores a late %s-scoped retry at the %s stage', async (switchKind, stage) => {
  const visual = await makeVisualFixture('infographic'), pending = deferred()
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('offline'))
  if (stage === 'visual') vi.mocked(apiJson).mockResolvedValueOnce(metadata)
  vi.mocked(apiJson).mockImplementationOnce(() => pending.promise).mockRejectedValue(new ApiError('new scope missing', 404, {}))
  const view = render(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  await screen.findByRole('alert'); fireEvent.click(retry())
  await waitFor(() => expect(apiJson).toHaveBeenCalledTimes(stage === 'visual' ? 3 : 2))
  if (switchKind === 'account') act(() => useAuthStore.setState({ user: { id: 'owner-b' } as never }))
  else if (switchKind === 'origin') {
    vi.mocked(runtime.resolveBackendOrigin).mockReturnValue('https://origin-b.example.invalid')
    view.rerender(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  } else view.rerender(<ResultPreview taskId={switchKind === 'task' ? '22222222-2222-4222-8222-222222222222' : visualTask} content={switchKind === 'body' ? 'New saved body' : visualSavedBody} />)
  await act(async () => pending.resolve(stage === 'visual' ? visual : metadata))
  expect(screen.queryByRole('region', { name: 'Validated graphic' })).toBeNull()
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByRole('article').textContent).toBe(switchKind === 'body' ? 'New saved body' : visualSavedBody)
  expect(apiJson).toHaveBeenCalledTimes(stage === 'visual' ? 4 : 3)
  expectOnlyArtifactGets()
})

it('blocks a late A→B→A account result and allows a new explicit read', async () => {
  const pending = deferred()
  vi.mocked(apiJson).mockImplementationOnce(() => pending.promise).mockResolvedValueOnce({ ...metadata, presentation: 'text' })
  render(<ResultPreview taskId={visualTask} content={visualSavedBody} />)
  act(() => {
    useAuthStore.setState({ user: { id: 'owner-b' } as never })
    useAuthStore.setState({ user: { id: 'owner-a' } as never })
  })
  await act(async () => pending.resolve(metadata))
  expect(apiJson).toHaveBeenCalledTimes(1)
  expect(screen.queryByRole('region', { name: 'Validated graphic' })).toBeNull()
  fireEvent.click(retry())
  await screen.findByText('摘要 · 文字')
  expectOnlyArtifactGets()
})

it('does not query artifacts without a task and keeps the body readable', () => {
  render(<ResultPreview content="Historical body without task" />)
  expect(screen.getByRole('article')).toHaveTextContent('Historical body without task')
  expect(apiJson).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: '重新读取形式与图形' })).toBeNull()
})
