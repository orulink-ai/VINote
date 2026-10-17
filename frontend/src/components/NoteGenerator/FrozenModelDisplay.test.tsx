import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { FrozenModelDisplay } from './FrozenModelDisplay'
import { useAuthStore } from '@/stores/authStore'

const api = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api', () => ({ apiJson: api }))
const models = { mode: 'cloud', origin: 'https://original.test/service', asr_model: 'asr:14:opaque', llm_model: 'llm:22:opaque' }
const catalog = [{ id: models.asr_model, modelType: 'asr', providerId: 'aliyun', providerModel: 'Paraformer Realtime' }, { id: models.llm_model, modelType: 'llm', name: 'Luna' }]
const display = (contextKey = 'task-a:revision-a', value = models) => <dl><FrozenModelDisplay owner="owner-a" contextKey={contextKey} models={value} /></dl>
function deferred() { let resolve!: (value: unknown) => void; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
beforeEach(() => {
  api.mockReset(); useAuthStore.setState({ user: { id: 'owner-a', email: 'a@example.invalid' } })
  api.mockImplementation((path: string) => Promise.resolve(path.endsWith('/config') ? { server_url: models.origin } : catalog))
})
afterEach(cleanup)

it('updates delayed names by exact catalog identity without exposing routing ids or server URL', async () => {
  const late = deferred()
  api.mockImplementation((path: string) => path.endsWith('/models') ? late.promise : Promise.resolve({ server_url: models.origin }))
  render(display())
  expect(screen.getByText('原任务所选语音模型（名称暂不可读取）')).toBeInTheDocument()
  await act(async () => late.resolve(catalog))
  expect(await screen.findByText('阿里云 · Paraformer Realtime')).toBeInTheDocument()
  expect(screen.getByText('Luna')).toBeInTheDocument()
  expect(document.body.textContent).not.toContain(models.origin)
  expect(document.body.textContent).not.toContain(models.asr_model)
  expect(document.body.textContent).not.toContain(models.llm_model)
  expect(api.mock.calls.every(([, options]) => !options.method)).toBe(true)
})

it.each(['missing', 'wrong-kind', 'name-stripped', 'different-source', 'outage'])('uses explicit original selection fallback for %s rather than defaults or parsed ids', async reason => {
  api.mockImplementation((path: string) => {
    if (reason === 'outage') return Promise.reject(new Error('raw upstream https://private.invalid'))
    if (path.endsWith('/config')) return Promise.resolve({ server_url: reason === 'different-source' ? 'https://different.test' : models.origin, asr_model: 'current-default' })
    return Promise.resolve(reason === 'missing' ? [{ id: 'current-default', modelType: 'asr', name: 'Current default' }] : reason === 'wrong-kind' ? [{ id: models.asr_model, modelType: 'llm', name: 'Wrong kind' }] : reason === 'name-stripped' ? [{ id: models.asr_model, modelType: 'asr' }] : catalog)
  })
  render(display()); await act(async () => {})
  expect(screen.getByText('原任务所选语音模型（名称暂不可读取）')).toBeInTheDocument()
  for (const hidden of ['Current default', 'Wrong kind', '阿里云', models.asr_model, 'private.invalid']) expect(document.body.textContent).not.toContain(hidden)
})

it('ignores late catalog after owner A-B-A even if React batches identity changes', async () => {
  const late = deferred()
  api.mockImplementation((path: string) => path.endsWith('/models') ? late.promise : Promise.resolve({ server_url: models.origin }))
  render(display())
  await act(async () => {
    useAuthStore.setState({ user: { id: 'owner-b', email: 'b@example.invalid' } })
    useAuthStore.setState({ user: { id: 'owner-a', email: 'a@example.invalid' } })
    late.resolve(catalog)
  })
  expect(screen.queryByText('Luna')).not.toBeInTheDocument()
  expect(screen.getByText('原任务所选语音模型（名称暂不可读取）')).toBeInTheDocument()
})

it('does not fetch a catalog for another current account', async () => {
  useAuthStore.setState({ user: { id: 'owner-b', email: 'b@example.invalid' } })
  render(display()); await act(async () => {})
  expect(api).not.toHaveBeenCalled()
})

it('discards late catalog on context change even when source/model IDs coincide', async () => {
  const old = deferred(), next = deferred(); let requests = 0
  api.mockImplementation((path: string) => path.endsWith('/models') ? (++requests === 1 ? old.promise : next.promise) : Promise.resolve({ server_url: models.origin }))
  const view = render(display())
  view.rerender(display('task-b:revision-b'))
  await act(async () => old.resolve(catalog))
  expect(screen.queryByText('Luna')).not.toBeInTheDocument()
  await act(async () => next.resolve([{ ...catalog[1], name: 'New context verified name' }]))
  expect(await screen.findByText('New context verified name')).toBeInTheDocument()
})

it('clears previously displayed names immediately when context changes and ignores unmounted requests', async () => {
  const view = render(display()); await screen.findByText('Luna')
  const late = deferred(); api.mockImplementation((path: string) => path.endsWith('/models') ? late.promise : Promise.resolve({ server_url: models.origin }))
  view.rerender(display('revision-next'))
  expect(screen.queryByText('Luna')).not.toBeInTheDocument()
  view.unmount(); await act(async () => late.resolve(catalog))
  expect(screen.queryByText('Luna')).not.toBeInTheDocument()
})

it('renders custom mode only from frozen mode without cloud requests', async () => {
  render(display('local-task', { ...models, mode: 'local' }))
  expect(screen.getByText('本地 / 自定义模型')).toBeInTheDocument()
  await waitFor(() => expect(api).not.toHaveBeenCalled())
})
