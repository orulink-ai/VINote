import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { RegenerateMeetingSummary } from './RegenerateMeetingSummary'
import { useAuthStore } from '@/stores/authStore'
import { useAppModeStore } from '@/stores/appModeStore'
import { apiJson, ApiError } from '@/lib/api'
vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(), apiJson: vi.fn() }))
const config = { configured: true, mode: 'cloud' as const, llm_model: 'selected-exact-model', asr_model: 'unchanged', server_url: 'https://model.invalid' }
const models = [{ id: config.llm_model, modelType: 'llm', runtimeStatus: 'available' }, { id: 'another-task-model', modelType: 'llm', runtimeStatus: 'available' }, { id: 'speech-only', modelType: 'asr', runtimeStatus: 'available' }, { id: 'unavailable-model', modelType: 'llm', runtimeStatus: 'not_available' }]
const context = { parent_task_id: 'parent', context_revision: 'a'.repeat(64), source: { version: 'b'.repeat(64), type: 'video' }, can_regenerate_summary: true }
const mock = vi.mocked(apiJson)
function Route() { const l = useLocation(); return <output data-testid="route">{l.pathname}{l.search}|{l.state?.returnTo}</output> }
function show() { return render(<MemoryRouter><RegenerateMeetingSummary noteId="note" taskId="parent" workspace={{ scope: 'personal' }} returnTo="/notes/note?view=transcript" /><Route /></MemoryRouter>) }
async function open() { fireEvent.click(screen.getByRole('button', { name: '重新生成纪要' })); await screen.findByRole('dialog') }
function moveFocusToBody() {
  // jsdom does not blur disabled buttons consistently; model the browser outcome.
  document.body.setAttribute('tabindex', '-1')
  document.body.focus()
  document.body.removeAttribute('tabindex')
}
beforeEach(() => {
  localStorage.clear(); vi.resetAllMocks()
  useAuthStore.setState({ user: { id: 'owner' } as never })
  useAppModeStore.setState({ config, saving: false })
  mock.mockImplementation(async path => path === '/api/vilab/models' ? models : path === '/api/vilab/config' ? config : context)
})
afterEach(cleanup)
it('confirms exact selected LLM and persists the owner operation before a single POST, then uses existing recovery route', async () => {
  mock.mockImplementation(async (path, init) => {
    if (path.endsWith('/regenerate-summary')) {
      const body = JSON.parse(init!.body as string)
      expect(body).toEqual({ operation_id: expect.any(String), confirmed: true, context_revision: context.context_revision, source_version: context.source.version, model_name: config.llm_model, content_depth: 'concise', presentation: 'text' })
      expect(JSON.parse(localStorage.getItem(`vinote:source-receipt:owner:${body.operation_id}`)!)).toMatchObject({ summaryOnly: true, submissionState: 'unknown', modelName: config.llm_model })
      return { operation_id: body.operation_id, task_id: 'child', state: 'accepted' }
    }
    return path === '/api/vilab/models' ? models : path === '/api/vilab/config' ? config : context
  })
  show(); await open()
  expect(screen.getByRole('dialog')).toHaveTextContent('不重新转录')
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '确认并重新生成纪要' }))
  await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent('/generate?meeting=1&operation='))
  expect(screen.getByTestId('route')).toHaveTextContent('|/notes/note?view=transcript')
  expect(mock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  const post = mock.mock.calls.find(([path]) => path.endsWith('/regenerate-summary'))!
  expect(JSON.parse(post[1]!.body as string)).toMatchObject({ content_depth: 'concise', presentation: 'text' })
})
it('retains unknown submission and reopening only navigates to GET recovery without another POST', async () => {
  mock.mockImplementation(async (path) => { if (path.endsWith('/regenerate-summary')) throw new Error('lost response'); return path === '/api/vilab/models' ? models : path === '/api/vilab/config' ? config : context })
  const view = show(); await open(); fireEvent.click(screen.getByRole('button', { name: '确认并重新生成纪要' }))
  await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent('operation='))
  const route = screen.getByTestId('route').textContent
  view.unmount(); show(); fireEvent.click(screen.getByRole('button', { name: '重新生成纪要' }))
  await waitFor(() => expect(screen.getByTestId('route').textContent).toBe(route))
  expect(mock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
})
it('treats missing summary evidence 409 as unavailable without ASR or any write', async () => {
  mock.mockRejectedValue(new ApiError('no evidence', 409, {}))
  show(); fireEvent.click(screen.getByRole('button', { name: '重新生成纪要' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('不可重新生成纪要')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})
it('prevents submission when operation storage cannot be protected', async () => {
  show(); await open()
  vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => { throw new Error('storage blocked') })
  fireEvent.click(screen.getByRole('button', { name: '确认并重新生成纪要' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('storage blocked')
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  vi.restoreAllMocks()
})
it('requires renewed confirmation if model selection changed', async () => {
  show(); await open()
  act(() => useAppModeStore.setState({ config: { ...config, llm_model: 'another-exact-model' } }))
  fireEvent.click(screen.getByRole('button', { name: '确认并重新生成纪要' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('模型选择已变化')
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})
it('ignores old context after an account ABA change', async () => {
  let resolve!: (value: unknown) => void
  mock.mockImplementation(path => path === '/api/vilab/config' ? Promise.resolve(config) : new Promise(r => { resolve = r }))
  show(); fireEvent.click(screen.getByRole('button', { name: '重新生成纪要' }))
  act(() => useAuthStore.setState({ user: { id: 'other' } as never }))
  act(() => useAuthStore.setState({ user: { id: 'owner' } as never }))
  await act(async () => resolve(context))
  expect(screen.queryByRole('dialog')).toBeNull()
})
it('closes confirmation on Origin change without submitting', async () => {
  show(); await open()
  act(() => useAppModeStore.setState({ config: { ...config, server_url: 'https://other.invalid' } }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('freezes explicit depth and available format in the operation and POST', async () => {
  mock.mockImplementation(async path => path === '/api/vilab/models' ? models : path === '/api/vilab/config' ? config : {
    ...context, presentation_options: { text: { available: true }, html: { available: true }, illustrated: { available: false }, comic: { available: false }, infographic: { available: false } },
  })
  show(); await open()
  fireEvent.click(screen.getByRole('radio', { name: '摘要' }))
  fireEvent.click(screen.getByRole('radio', { name: 'HTML' }))
  expect(screen.getByRole('radio', { name: '漫画（不可用）' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '确认并重新生成纪要' }))
  await waitFor(() => expect(mock.mock.calls.some(([path]) => path.endsWith('/regenerate-summary'))).toBe(true))
  const post = mock.mock.calls.find(([path]) => path.endsWith('/regenerate-summary'))!
  const body = JSON.parse(post[1]!.body as string)
  expect(body).toMatchObject({ content_depth: 'brief', presentation: 'html' })
  expect(JSON.parse(localStorage.getItem(`vinote:source-receipt:owner:${body.operation_id}`)!)).toMatchObject({ contentDepth: 'brief', presentation: 'html' })
})

it('closes the dialog if the connection changes at the same Origin', async () => {
  const first = { ...config, connection_id: 'first-connection' }
  useAppModeStore.setState({ config: first })
  mock.mockImplementation(async path => path === '/api/vilab/models' ? models : path === '/api/vilab/config' ? first : context)
  show(); await open()
  act(() => useAppModeStore.setState({ config: { ...config, connection_id: 'second-connection' } as typeof config }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('selects the LLM per generation without changing global preferences or showing ASR/unavailable entries', async () => {
  show(); await open()
  const picker = screen.getByRole('combobox', { name: '本次总结模型' })
  expect(picker).toHaveValue(config.llm_model)
  expect(screen.queryByRole('option', { name: 'speech-only' })).toBeNull()
  expect(screen.queryByRole('option', { name: 'unavailable-model' })).toBeNull()
  fireEvent.change(picker, { target: { value: 'another-task-model' } })
  expect(useAppModeStore.getState().config).toEqual(config)
  expect(screen.getByRole('dialog')).toHaveTextContent('不以上一版纪要为输入')
  fireEvent.click(screen.getByRole('button', { name: '确认并重新生成纪要' }))
  await waitFor(() => expect(mock.mock.calls.some(([path]) => path.endsWith('/regenerate-summary'))).toBe(true))
  const post = mock.mock.calls.find(([path]) => path.endsWith('/regenerate-summary'))!
  expect(JSON.parse(post[1]!.body as string).model_name).toBe('another-task-model')
  expect(mock.mock.calls.filter(([, init]) => init?.method && init.method !== 'GET').map(([path]) => path)).toEqual(['/api/task/parent/regenerate-summary'])
})

it('fails closed when the current connection catalog cannot be read', async () => {
  mock.mockImplementation(async path => {
    if (path === '/api/vilab/models') throw new Error('catalog unavailable')
    return path === '/api/vilab/config' ? config : context
  })
  show(); fireEvent.click(screen.getByRole('button', { name: '重新生成纪要' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('catalog unavailable')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('permits a new version after independently verifying the previous operation was saved', async () => {
  const pointer = 'vinote:summary-operation:owner:https://model.invalid:note:parent'
  localStorage.setItem(pointer, 'completed-operation')
  mock.mockImplementation(async path => {
    if (path === '/api/source-requests/completed-operation') return { operation_id: 'completed-operation', task_id: 'saved-child', state: 'accepted' }
    if (path === '/api/task/saved-child') return { task_id: 'saved-child', status: 'success' }
    if (path === '/api/notes?scope=personal') return [{ id: 'saved-note', task_id: 'saved-child' }]
    return path === '/api/vilab/models' ? models : path === '/api/vilab/config' ? config : context
  })
  show(); await open()
  expect(localStorage.getItem(pointer)).toBeNull()
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '确认并重新生成纪要' }))
  await waitFor(() => expect(mock.mock.calls.some(([path]) => path.endsWith('/regenerate-summary'))).toBe(true))
  const post = mock.mock.calls.find(([path]) => path.endsWith('/regenerate-summary'))!
  expect(JSON.parse(post[1]!.body as string).operation_id).not.toBe('completed-operation')
})

it.each(['unknown', 'success-unsaved', 'notes-read-failed'])('protects the previous %s operation and never submits another', async state => {
  const pointer = 'vinote:summary-operation:owner:https://model.invalid:note:parent'
  localStorage.setItem(pointer, 'protected-operation')
  mock.mockImplementation(async path => {
    if (path === '/api/source-requests/protected-operation') return { operation_id: 'protected-operation', task_id: 'child', state: 'accepted' }
    if (path === '/api/task/child') return { task_id: 'child', status: state === 'unknown' ? 'preparing' : 'success' }
    if (path === '/api/notes?scope=personal') { if (state === 'notes-read-failed') throw new Error('read failed'); return [] }
    throw new Error('unexpected request')
  })
  show(); fireEvent.click(screen.getByRole('button', { name: '重新生成纪要' }))
  await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent('operation=protected-operation'))
  expect(localStorage.getItem(pointer)).toBe('protected-operation')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

const failedPointer = 'vinote:summary-operation:owner:https://model.invalid:note:parent'
const failedRecordKey = 'vinote:source-receipt:owner:failed-operation'
function failedFixture(overrides: { record?: object; receipt?: object; task?: object } = {}) {
  const record = { operationId: 'failed-operation', id: 'failed-child', parentTaskId: 'parent', summaryNoteId: 'note',
    origin: config.server_url, workspace: { scope: 'personal' }, summaryOnly: true, meeting: true, submissionState: 'accepted', ...overrides.record }
  localStorage.setItem(failedPointer, 'failed-operation')
  localStorage.setItem(failedRecordKey, JSON.stringify(record))
  mock.mockImplementation(async (path, init) => {
    if (path === '/api/source-requests/failed-operation') return { operation_id: 'failed-operation', task_id: 'failed-child', state: 'accepted', ...overrides.receipt }
    if (path === '/api/task/failed-child') return { task_id: 'failed-child', status: 'failed', failed_stage: 'summarizing', retryable: false, ...overrides.task }
    if (path.endsWith('/regenerate-summary')) {
      const body = JSON.parse(init!.body as string)
      return { operation_id: body.operation_id, task_id: 'new-child', state: 'accepted' }
    }
    return path === '/api/vilab/models' ? models : path === '/api/vilab/config' ? config : context
  })
}

async function exposeFailedAction() {
  fireEvent.click(screen.getByRole('button', { name: '重新生成纪要' }))
  return screen.findByRole('button', { name: '保留失败记录，另建新版本' })
}

it('requires an explicit failed-version action and a new model/format confirmation while preserving the old receipt', async () => {
  failedFixture()
  const old = localStorage.getItem(failedRecordKey)
  show()
  const action = await exposeFailedAction()
  expect(localStorage.getItem(failedPointer)).toBe('failed-operation')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(mock.mock.calls.some(([path]) => path.endsWith('/summary-context'))).toBe(false)
  fireEvent.click(action)
  await screen.findByRole('dialog')
  expect(localStorage.getItem(failedPointer)).toBe('failed-operation')
  fireEvent.change(screen.getByRole('combobox', { name: '本次总结模型' }), { target: { value: 'another-task-model' } })
  fireEvent.click(screen.getByRole('radio', { name: 'HTML' }))
  fireEvent.click(screen.getByRole('button', { name: '确认并重新生成纪要' }))
  await waitFor(() => expect(mock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1))
  const post = mock.mock.calls.find(([, init]) => init?.method === 'POST')!
  expect(post[0]).toBe('/api/task/parent/regenerate-summary')
  const body = JSON.parse(post[1]!.body as string)
  expect(body).toMatchObject({ model_name: 'another-task-model', presentation: 'html' })
  expect(body.operation_id).not.toBe('failed-operation')
  expect(localStorage.getItem(failedPointer)).toBe(body.operation_id)
  expect(localStorage.getItem(failedRecordKey)).toBe(old)
  expect(useAppModeStore.getState().config).toEqual(config)
})

it('cancels a scrollable failed-version dialog without changing records and restores focus to its opener', async () => {
  failedFixture()
  const user = userEvent.setup()
  show()
  const action = await exposeFailedAction()
  await user.click(action)
  const dialog = await screen.findByRole('dialog')
  expect(dialog.className).toContain('max-h-')
  expect(dialog.className).toContain('overflow-y-auto')
  await user.click(screen.getByRole('button', { name: '取消' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await waitFor(() => expect(action).toHaveFocus())
  expect(localStorage.getItem(failedPointer)).toBe('failed-operation')
  expect(localStorage.getItem(failedRecordKey)).not.toBeNull()
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it.each(['取消', '关闭', 'Escape'])('restores the explicit opener after delayed preparation loses body focus: %s', async close => {
  let ready!: (value: unknown) => void
  const source = new Promise(resolve => { ready = resolve })
  mock.mockImplementation(path => path.endsWith('/summary-context') ? source : Promise.resolve(path === '/api/vilab/models' ? models : config))
  const user = userEvent.setup()
  show()
  const opener = screen.getByRole('button', { name: '重新生成纪要' })
  await user.click(opener)
  expect(opener).toBeDisabled()
  moveFocusToBody() // Some browsers blur a disabled button while GET is pending.
  expect(document.body).toHaveFocus()
  await act(async () => ready(context))
  await screen.findByRole('dialog')
  if (close === 'Escape') await user.keyboard('{Escape}')
  else await user.click(screen.getByRole('button', { name: close }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await waitFor(() => expect(opener).toHaveFocus())
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('restores the failed-version action after a delayed second preparation loses focus', async () => {
  failedFixture()
  show()
  const opener = await exposeFailedAction()
  const previousMock = mock.getMockImplementation()!
  let ready!: (value: unknown) => void
  const source = new Promise(resolve => { ready = resolve })
  mock.mockImplementation((path, init) => path.endsWith('/summary-context') ? source : previousMock(path, init))
  const user = userEvent.setup()
  await user.click(opener)
  expect(opener).toBeDisabled()
  moveFocusToBody()
  expect(document.body).toHaveFocus()
  await act(async () => ready(context))
  await screen.findByRole('dialog')
  await user.click(screen.getByRole('button', { name: '取消' }))
  await waitFor(() => expect(opener).toHaveFocus())
  expect(localStorage.getItem(failedPointer)).toBe('failed-operation')
})

it.each(['owner', 'route'])('does not restore an old opener after %s changes', async change => {
  function NewSurface() {
    const navigate = useNavigate()
    return <><button onClick={() => navigate('/other')}>切换页面</button><input aria-label="新页面焦点" /></>
  }
  render(<MemoryRouter><RegenerateMeetingSummary noteId="note" taskId="parent" workspace={{ scope: 'personal' }} returnTo="/notes" /><NewSurface /></MemoryRouter>)
  const user = userEvent.setup()
  const opener = screen.getByRole('button', { name: '重新生成纪要' })
  await user.click(opener)
  await screen.findByRole('dialog')
  const oldFocus = vi.spyOn(opener, 'focus')
  if (change === 'owner') act(() => useAuthStore.setState({ user: { id: 'other' } as never }))
  else fireEvent.click(screen.getByRole('button', { name: '切换页面', hidden: true }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  const input = screen.getByRole('textbox', { name: '新页面焦点' })
  input.focus()
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)) })
  expect(input).toHaveFocus()
  expect(oldFocus).not.toHaveBeenCalled()
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  oldFocus.mockRestore()
})

it.each([
  { receipt: { state: 'reserved' } },
  { receipt: { operation_id: 'foreign-operation' } },
  { task: { task_id: 'foreign-child' } },
  { task: { operation_id: 'foreign-operation' } },
  { task: { failed_stage: 'transcribing' } },
  { task: { status: 'preparing' } },
  { task: { status: 'success' } },
  { task: { error_code: 'summary_result_unconfirmed' } },
  { task: { error_code: 'unknown_result' } },
  { task: { retryable: undefined } },
  { record: { id: 'foreign-child' } },
  { record: { parentTaskId: 'foreign-parent' } },
  { record: { operationId: 'foreign-operation' } },
  { record: { summaryOnly: false } },
  { record: { submissionState: 'unknown' } },
  { record: { origin: 'https://other.invalid' } },
])('protects unconfirmed or mismatched failed operation %j', async overrides => {
  failedFixture(overrides)
  show(); fireEvent.click(screen.getByRole('button', { name: '重新生成纪要' }))
  await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent('operation=failed-operation'))
  expect(screen.queryByRole('button', { name: '保留失败记录，另建新版本' })).toBeNull()
  expect(localStorage.getItem(failedPointer)).toBe('failed-operation')
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it.each(['before-prepare', 'before-confirm', 'task-became-unconfirmed'])('revalidates failed operation and protects changed bindings %s', async change => {
  failedFixture(); show()
  const action = await exposeFailedAction()
  if (change === 'before-prepare') localStorage.setItem(failedPointer, 'newer-operation')
  fireEvent.click(action)
  if (change !== 'before-prepare') {
    await screen.findByRole('dialog')
    if (change === 'before-confirm') localStorage.setItem(failedPointer, 'newer-operation')
    else failedFixture({ task: { error_code: 'summary_result_unconfirmed' } })
    fireEvent.click(screen.getByRole('button', { name: '确认并重新生成纪要' }))
  }
  await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent('operation=' + (change === 'task-became-unconfirmed' ? 'failed-operation' : 'newer-operation')))
  expect(localStorage.getItem(failedRecordKey)).not.toBeNull()
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})
