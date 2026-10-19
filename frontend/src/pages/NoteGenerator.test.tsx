import { useAppModeStore } from '../stores/appModeStore'
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, UNSAFE_NavigationContext } from 'react-router-dom'
import { useContext } from 'react'
import { useAuthStore } from '../stores/authStore'
import { I18nProvider } from '../lib/i18n'
import { useNoteGenerationStore } from '../stores/noteGenerationStore'
import { NoteGenerator } from './NoteGenerator'
import { ApiError } from '../lib/api'

const apiMock = vi.hoisted(() => ({
  apiJson: vi.fn(),
}))
const navigateMock = vi.hoisted(() => vi.fn())
const queryMock = vi.hoisted(() => ({ value: '' }))
const languageMock = vi.hoisted(() => ({ value: 'en' as 'en' | 'zh-CN' }))

vi.mock('../lib/api', () => ({
  apiJson: apiMock.apiJson,
  ApiError: class extends Error { constructor(message: string, public status: number) { super(message) } },
}))

vi.mock('react-router-dom', async () => ({
  ...await vi.importActual<typeof import('react-router-dom')>('react-router-dom'),
  useNavigate: () => navigateMock,
  useSearchParams: () => [new URLSearchParams(queryMock.value)],
}))

vi.mock('../stores/languageStore', () => ({
  useLanguageStore: () => ({
    language: languageMock.value,
    setLanguage: vi.fn(),
    syncWithAccount: vi.fn(),
  }),
}))

vi.mock('../stores/modelProfileStore', () => ({
  useModelProfileStore: () => ({
    profiles: [],
    selectedProfileId: '',
    selectProfile: vi.fn(),
    loadProfiles: vi.fn(),
  }),
}))

vi.mock('../stores/sttProfileStore', () => ({
  useSTTProfileStore: () => ({
    profiles: [],
    selectedProfileId: '',
    selectProfile: vi.fn(),
    loadProfiles: vi.fn(),
  }),
}))

const libraryMock = vi.hoisted(() => ({ saveNote: vi.fn(), loadNotes: vi.fn(async () => {}), notes: [] as { taskId: string; id: string }[] }))
vi.mock('../stores/noteLibraryStore', () => ({
  useNoteLibraryStore: Object.assign(() => libraryMock, { getState: () => libraryMock }),
}))

vi.mock('../stores/teamStore', async () => {
  const actual = await vi.importActual<typeof import('../stores/teamStore')>('../stores/teamStore')
  return {
    ...actual,
    useTeamStore: () => ({
      currentWorkspace: { scope: 'personal' },
      teams: [],
      loadTeams: vi.fn(),
    }),
  }
})

function renderGenerator(returnTo?: string) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/generate', search: queryMock.value ? `?${queryMock.value}` : '', state: returnTo ? { returnTo } : undefined }]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><I18nProvider>
      <NoteGenerator />
    </I18nProvider></MemoryRouter>
  )
}

describe('NoteGenerator failed generation recovery', () => {
  it('reads a restored task immediately and shows no generation before delayed GET resolves', async () => {
    const receipt = { id: 'delayed-task', submissionState: 'accepted', workspace: { scope: 'personal' }, meeting: false }
    localStorage.setItem('vinote:import-receipt:import-owner:note', JSON.stringify(receipt))
    let resolve!: (value: unknown) => void
    apiMock.apiJson.mockReturnValue(new Promise(done => { resolve = done }))
    renderGenerator('/notes?project=kept')
    expect(apiMock.apiJson).toHaveBeenCalledWith('/api/task/delayed-task')
    expect(screen.getByRole('heading', { name: '正在读取处理进度' })).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(useNoteGenerationStore.getState().status).toBe('idle')
    expect(libraryMock.saveNote).not.toHaveBeenCalled()
    expect(screen.getByRole('link', { name: '返回笔记' })).toHaveAttribute('href', '/notes?project=kept')
    await act(async () => resolve({ status: 'failed', message: 'actual failure', retryable: true }))
    expect(await screen.findByText('actual failure')).toBeInTheDocument()
    expect(screen.queryByText('正在读取处理进度')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试处理原任务' })).toBeInTheDocument()
    expect(apiMock.apiJson.mock.calls.every(call => !call[1]?.method || call[1].method === 'GET')).toBe(true)
  })

  it('returning to the same task rejects the previous mount delayed success', async () => {
    const receipt = { id: 'same-task', submissionState: 'accepted', workspace: { scope: 'personal' }, meeting: false }
    localStorage.setItem('vinote:import-receipt:import-owner:note', JSON.stringify(receipt))
    let oldResolve!: (value: unknown) => void
    let newResolve!: (value: unknown) => void
    apiMock.apiJson.mockReturnValueOnce(new Promise(done => { oldResolve = done }))
      .mockReturnValueOnce(new Promise(done => { newResolve = done }))
    const first = renderGenerator()
    first.unmount()
    renderGenerator()
    expect(apiMock.apiJson).toHaveBeenCalledTimes(2)
    await act(async () => oldResolve({ status: 'success', result: { task_id: 'same-task', title: 'old', markdown: 'old' } }))
    expect(screen.getByText('正在读取处理进度')).toBeInTheDocument()
    expect(libraryMock.saveNote).not.toHaveBeenCalled()
    expect(navigateMock).not.toHaveBeenCalled()
    await act(async () => newResolve({ status: 'failed', message: 'returned task failed' }))
    expect(await screen.findByText('returned task failed')).toBeInTheDocument()
  })

  it('a failed initial GET exposes query recovery without submission or automatic retry', async () => {
    localStorage.setItem('vinote:import-receipt:import-owner:note', JSON.stringify({ id: 'read-failure', submissionState: 'accepted', workspace: { scope: 'personal' }, meeting: false }))
    apiMock.apiJson.mockRejectedValue(new Error('offline'))
    renderGenerator()
    expect(await screen.findByText(/无法读取原任务进度/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新查询原任务状态' })).toBeInTheDocument()
    expect(apiMock.apiJson).toHaveBeenCalledTimes(1)
    expect(libraryMock.saveNote).not.toHaveBeenCalled()
  })

  it('ignores the old epoch after switching accounts away and back to the same task', async () => {
    const receipt = { id: 'epoch-task', submissionState: 'accepted', workspace: { scope: 'personal' }, meeting: false }
    localStorage.setItem('vinote:import-receipt:import-owner:note', JSON.stringify(receipt))
    let oldResolve!: (value: unknown) => void
    let newResolve!: (value: unknown) => void
    apiMock.apiJson.mockReturnValueOnce(new Promise(done => { oldResolve = done }))
      .mockReturnValueOnce(new Promise(done => { newResolve = done }))
    renderGenerator()
    await act(async () => useAuthStore.setState({ user: { id: 'other-owner', email: 'other@example.invalid' } }))
    await act(async () => useAuthStore.setState({ user: { id: 'import-owner', email: 'import@example.invalid' } }))
    expect(apiMock.apiJson).toHaveBeenCalledTimes(2)
    await act(async () => oldResolve({ status: 'success', result: { title: 'stale', markdown: 'stale', task_id: 'epoch-task' } }))
    expect(screen.getByText('正在读取处理进度')).toBeInTheDocument()
    expect(libraryMock.saveNote).not.toHaveBeenCalled()
    expect(libraryMock.loadNotes).not.toHaveBeenCalled()
    await act(async () => newResolve({ status: 'transcribing', message: '', received_seconds: 12, total_seconds: 100 }))
    expect(useNoteGenerationStore.getState().currentStep).toBe('transcribing')
    expect(screen.queryByText('正在读取处理进度')).not.toBeInTheDocument()
  })
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.apiJson.mockReset()
    apiMock.apiJson.mockResolvedValue({ status: 'preparing', message: '' })
    queryMock.value = ''
    languageMock.value = 'en'
    libraryMock.saveNote.mockReset()
    libraryMock.notes = []
    useNoteGenerationStore.getState().reset()
    sessionStorage.clear()
    localStorage.clear()
    useAuthStore.setState({ user: { id: 'import-owner', email: 'import@example.invalid' } })
  })
  afterEach(() => { cleanup(); sessionStorage.clear(); localStorage.clear(); vi.unstubAllEnvs() })

  function deferred<T>() {
    let resolve!: (value: T) => void
    let reject!: (cause: Error) => void
    const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
    return { promise, resolve, reject }
  }
  it.each(['success', 'failure'] as const)('ignores late operation A %s after same-mounted route selects read-only task B', async outcome => {
    const old = JSON.stringify({ operationId: 'operation-a', workspace: { scope: 'personal' }, meeting: true, submissionState: 'unknown' })
    localStorage.setItem('vinote:import-receipt:import-owner:meeting', old)
    localStorage.setItem('vinote:source-receipt:import-owner:operation-a', old)
    const responseA = deferred<unknown>()
    apiMock.apiJson.mockImplementation((path: string) => path === '/api/source-requests/operation-a' ? responseA.promise : Promise.resolve(path === '/api/task/task-b' ? { task_id: 'task-b', status: 'failed', message: 'task B remains selected', retryable: true } : { task_id: 'task-a', status: 'success', result: { task_id: 'task-a', title: 'wrong result A', markdown: 'wrong body A' } }))
    libraryMock.saveNote.mockResolvedValue({ id: 'must-not-save' })
    let push!: (path: string) => void
    function Driver() { const navigation = useContext(UNSAFE_NavigationContext); push = path => navigation!.navigator.push(path, { returnTo: '/files?purpose=meeting&file=task%3Atask-b&q=kept' }); return null }
    queryMock.value = 'meeting=1&operation=operation-a'
    render(<MemoryRouter initialEntries={['/generate?meeting=1&operation=operation-a']}><Driver /><I18nProvider><NoteGenerator /></I18nProvider></MemoryRouter>)
    expect(apiMock.apiJson).toHaveBeenCalledWith('/api/source-requests/operation-a')
    await act(async () => { queryMock.value = 'meeting=1&task=task-b'; push('/generate?meeting=1&task=task-b') })
    await screen.findByText('task B remains selected')
    const callsBeforeLate = apiMock.apiJson.mock.calls.length
    await act(async () => { if (outcome === 'success') responseA.resolve({ operation_id: 'operation-a', task_id: 'task-a', state: 'accepted' }); else responseA.reject(new Error('late-A-error')) })
    expect(screen.getByText('task B remains selected')).toBeInTheDocument()
    expect(screen.queryByText('late-A-error')).not.toBeInTheDocument()
    expect(apiMock.apiJson.mock.calls).toHaveLength(callsBeforeLate)
    expect(apiMock.apiJson).not.toHaveBeenCalledWith('/api/task/task-a')
    expect(libraryMock.saveNote).not.toHaveBeenCalled(); expect(navigateMock).not.toHaveBeenCalled()
    expect(localStorage.getItem('vinote:import-receipt:import-owner:meeting')).toBe(old)
    expect(localStorage.getItem('vinote:source-receipt:import-owner:operation-a')).toBe(old)
    expect(screen.getByRole('link', { name: '返回文件库' })).toHaveAttribute('href', '/files?purpose=meeting&file=task%3Atask-b&q=kept')
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
  })

  it.each([
    ['operation-route', 'success'], ['operation-route', 'failure'],
    ['account-A-B-A', 'success'], ['account-A-B-A', 'failure'],
  ] as const)('old receipt %s/%s cannot overwrite the new operation or release its request lock', async (transition, outcome) => {
    const pending = (operationId: string) => JSON.stringify({ operationId, workspace: { scope: 'personal' }, meeting: true, submissionState: 'unknown' })
    const global = pending('global-untouched'); const oldA = pending('operation-a'); const oldB = pending('operation-b')
    localStorage.setItem('vinote:import-receipt:import-owner:meeting', global)
    localStorage.setItem('vinote:source-receipt:import-owner:operation-a', oldA)
    localStorage.setItem('vinote:source-receipt:import-owner:operation-b', oldB)
    localStorage.setItem('vinote:source-receipt:other-owner:operation-b', oldB)
    const responseA = deferred<unknown>(); const responseB = deferred<unknown>(); const intermediateB = deferred<unknown>()
    let bCalls = 0
    apiMock.apiJson.mockImplementation((path: string) => {
      if (path === '/api/source-requests/operation-a') return responseA.promise
      if (path === '/api/source-requests/operation-b') {
        bCalls++
        return useAuthStore.getState().user?.id === 'other-owner' ? intermediateB.promise : responseB.promise
      }
      return Promise.resolve({ task_id: 'task-a', status: 'success', result: { task_id: 'task-a', title: 'must-not-save', markdown: 'body' } })
    })
    libraryMock.saveNote.mockResolvedValue({ id: 'must-not-save' })
    let push!: (path: string) => void
    function Driver() { const navigation = useContext(UNSAFE_NavigationContext); push = path => navigation!.navigator.push(path); return null }
    const tree = <MemoryRouter initialEntries={['/generate?meeting=1&operation=operation-a']}><Driver /><I18nProvider><NoteGenerator /></I18nProvider></MemoryRouter>
    queryMock.value = 'meeting=1&operation=operation-a'; const view = render(tree)
    expect(apiMock.apiJson).toHaveBeenCalledWith('/api/source-requests/operation-a')
    await act(async () => {
      queryMock.value = 'meeting=1&operation=operation-b'
      if (transition === 'account-A-B-A') useAuthStore.setState({ user: { id: 'other-owner', email: 'other@example.invalid' } })
      push('/generate?meeting=1&operation=operation-b')
    })
    if (transition === 'account-A-B-A') await act(async () => useAuthStore.setState({ user: { id: 'import-owner', email: 'import@example.invalid' } }))
    const expectedBCalls = transition === 'account-A-B-A' ? 2 : 1
    expect(bCalls).toBe(expectedBCalls)
    await act(async () => {
      if (outcome === 'success') { responseA.resolve({ operation_id: 'operation-a', task_id: 'task-a', state: 'accepted' }); if (transition === 'account-A-B-A') intermediateB.resolve({ operation_id: 'operation-b', task_id: 'foreign-task', state: 'accepted' }) }
      else { responseA.reject(new Error('late-A-error')); if (transition === 'account-A-B-A') intermediateB.reject(new Error('late-foreign-error')) }
    })
    // Force a current-scope render so a stale finally that mutates only a ref
    // cannot escape the assertion by leaving the DOM temporarily disabled.
    view.rerender(<MemoryRouter initialEntries={['/generate?meeting=1&operation=operation-a']}><Driver /><I18nProvider><NoteGenerator /></I18nProvider></MemoryRouter>)
    const query = screen.getByRole('button', { name: '核验原提交' })
    expect(query).toBeDisabled()
    await userEvent.click(query)
    expect(bCalls).toBe(expectedBCalls)
    expect(screen.queryByText('late-A-error')).not.toBeInTheDocument()
    expect(screen.queryByText('late-foreign-error')).not.toBeInTheDocument()
    expect(apiMock.apiJson).not.toHaveBeenCalledWith('/api/task/task-a')
    expect(apiMock.apiJson).not.toHaveBeenCalledWith('/api/task/foreign-task')
    expect(libraryMock.saveNote).not.toHaveBeenCalled(); expect(navigateMock).not.toHaveBeenCalled()
    expect(localStorage.getItem('vinote:import-receipt:import-owner:meeting')).toBe(global)
    expect(localStorage.getItem('vinote:source-receipt:import-owner:operation-a')).toBe(oldA)
    expect(localStorage.getItem('vinote:source-receipt:import-owner:operation-b')).toBe(oldB)
    await act(async () => responseB.resolve({ operation_id: 'operation-b', task_id: 'task-b', state: 'reserved' }))
    await screen.findByText('提交已登记，尚未确认排队。请继续核验原提交，不会自动重新派发。')
    expect(screen.getByRole('button', { name: '核验原提交' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: '核验原提交' }))
    expect(bCalls).toBe(expectedBCalls + 1)
    expect(localStorage.getItem('vinote:import-receipt:import-owner:meeting')).toBe(global)
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
  })

  const frozenContext = { protocol: 1, parent_task_id: 'selected-task', workflow: 'meeting', context_revision: 'a'.repeat(64), source: { title: '保留视频', version: 'b'.repeat(64), type: 'meeting_video' }, frozen_models: { mode: 'cloud', origin: 'https://original.invalid', asr_model: 'original-asr', llm_model: 'original-llm' }, can_confirm_new_operation: true }
  const openFrozenSheet = async (context: typeof frozenContext & { canonical_task_id?: unknown } = frozenContext) => {
    queryMock.value = 'meeting=1&task=selected-task'
    apiMock.apiJson.mockImplementation((path: string) => path.endsWith('/new-generation-context') ? Promise.resolve(context) : Promise.resolve({ task_id: 'selected-task', status: 'failed', message: '上次未完成', error_code: 'unknown_result', retryable: false }))
    renderGenerator('/files?purpose=meeting&file=task%3Aselected-task')
    await screen.findByText('上次未完成')
    await userEvent.click(screen.getByRole('button', { name: '确认原模型，开始新的处理' }))
    return screen.findByRole('dialog')
  }
  it('frozen confirmation open and cancellation only GET original context', async () => {
    const dialog = await openFrozenSheet()
    expect(within(dialog).getByText('原任务所选语音模型（名称暂不可读取）')).toBeInTheDocument()
    expect(within(dialog).getByText('原任务所选总结模型（名称暂不可读取）')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: '取消' }))
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
    expect(localStorage.length).toBe(0)
  })
  it('frozen new-generation Sheet shows exact public catalog names while hiding origin and routing ids', async () => {
    queryMock.value = 'meeting=1&task=selected-task'
    apiMock.apiJson.mockImplementation((path: string) => Promise.resolve(
      path.endsWith('/new-generation-context') ? frozenContext
        : path === '/api/vilab/config' ? { server_url: frozenContext.frozen_models.origin, asr_model: 'new-default' }
          : path === '/api/vilab/models' ? [{ id: 'original-asr', modelType: 'asr', name: '原选择 · 阿里云语音' }, { id: 'original-llm', modelType: 'llm', name: '原选择 · Luna' }, { id: 'new-default', modelType: 'asr', name: '当前默认' }]
            : { task_id: 'selected-task', status: 'failed', message: '上次未完成', error_code: 'unknown_result', retryable: false }))
    renderGenerator()
    await screen.findByText('上次未完成')
    await userEvent.click(screen.getByRole('button', { name: '确认原模型，开始新的处理' }))
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText('原选择 · 阿里云语音')
    expect(within(dialog).getByText('原选择 · Luna')).toBeInTheDocument()
    expect(within(dialog).getByText('云端模型')).toBeInTheDocument()
    for (const hidden of [frozenContext.frozen_models.origin, 'original-asr', 'original-llm', '当前默认']) expect(dialog.textContent).not.toContain(hidden)
    await userEvent.click(within(dialog).getByRole('button', { name: '取消' }))
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
    expect(localStorage.length).toBe(0)
  })
  it('explicit confirmation persists distinct operation; lost POST response only navigates to exact operation query', async () => {
    const old = JSON.stringify({ id: 'different-task', meeting: true, workspace: { scope: 'personal' } })
    localStorage.setItem('vinote:import-receipt:import-owner:meeting', old)
    const dialog = await openFrozenSheet()
    apiMock.apiJson.mockImplementation((path: string, init?: RequestInit) => init?.method === 'POST' ? Promise.reject(new Error('lost response')) : Promise.resolve({ task_id: 'selected-task', status: 'failed', message: '上次未完成' }))
    await userEvent.click(within(dialog).getByRole('button', { name: '确认原模型并开始新的处理' }))
    await waitFor(() => expect(navigateMock).toHaveBeenCalled())
    const writes = apiMock.apiJson.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(writes).toHaveLength(1)
    expect(writes[0][0]).toBe('/api/task/selected-task/new-generation')
    const body = JSON.parse(writes[0][1].body)
    expect(Object.keys(body).sort()).toEqual(['confirmed', 'context_revision', 'operation_id', 'source_version'])
    expect(body.context_revision).toBe(frozenContext.context_revision)
    const pending = JSON.parse(localStorage.getItem(`vinote:source-receipt:import-owner:${body.operation_id}`)!)
    expect(pending.submissionState).toBe('unknown')
    expect(navigateMock.mock.calls.at(-1)![0]).toContain(`operation=${body.operation_id}`)
    expect(localStorage.getItem('vinote:import-receipt:import-owner:meeting')).toBe(old)
    expect(JSON.parse(localStorage.getItem('vinote:source-task-receipt:import-owner:selected-task')!).id).toBe('selected-task')
  })
  it.each(['lost', 'accepted'])('v2 explicitly confirms one operation with canonical id and preserves frozen context for %s response', async outcome => {
    const context = { ...frozenContext, protocol: 2, canonical_task_id: '2bfa5300-a102-45a8-89cf-123456789abc' }
    const dialog = await openFrozenSheet(context)
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method)).toBe(true)
    apiMock.apiJson.mockImplementation((_path: string, init?: RequestInit) => {
      const body = JSON.parse(init!.body as string)
      const pending = JSON.parse(localStorage.getItem(`vinote:source-receipt:import-owner:${body.operation_id}`)!)
      expect(pending.frozenContext).toEqual(context)
      expect(pending.sourceType).toBe('meeting_video')
      expect(pending.submissionState).toBe('unknown')
      return outcome === 'lost' ? Promise.reject(new Error('lost response')) : Promise.resolve({ operation_id: body.operation_id, task_id: 'new-independent-child', state: 'accepted' })
    })
    await userEvent.dblClick(within(dialog).getByRole('button', { name: '确认原模型并开始新的处理' }))
    await waitFor(() => expect(navigateMock).toHaveBeenCalled())
    const writes = apiMock.apiJson.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(writes).toHaveLength(1)
    expect(writes[0][0]).toBe('/api/task/selected-task/new-generation')
    expect(JSON.parse(writes[0][1].body)).toEqual({ operation_id: expect.any(String), confirmed: true, canonical_task_id: context.canonical_task_id, context_revision: context.context_revision, source_version: context.source.version })
    expect(navigateMock.mock.calls.at(-1)![0]).toContain('operation=')
  })
  it.each([
    ['meeting_video', 'meeting_video', 5],
    ['video', 'meeting_video', 5],
    ['meeting_audio', 'meeting_recording', 4],
    ['meeting_recording', 'meeting_recording', 4],
    ['audio', 'meeting_recording', 4],
    ['unrecognized.webm', 'unknown', 4],
  ] as const)('v2 verified source %s survives confirmation, recovery and saving as %s', async (type, classified, steps) => {
    const context = { ...frozenContext, protocol: 2, canonical_task_id: '2bfa5300-a102-45a8-89cf-123456789abc', source: { ...frozenContext.source, title: 'Synthetic-video.webm', type } }
    const dialog = await openFrozenSheet(context)
    apiMock.apiJson.mockImplementation(async (_path: string, init?: RequestInit) => {
      const body = JSON.parse(init!.body as string)
      expect(JSON.parse(localStorage.getItem(`vinote:source-receipt:import-owner:${body.operation_id}`)!).sourceType).toBe(classified)
      return { operation_id: body.operation_id, task_id: 'classified-child', state: 'accepted', source_type: 'audio' }
    })
    await userEvent.click(within(dialog).getByRole('button', { name: '确认原模型并开始新的处理' }))
    await waitFor(() => expect(navigateMock).toHaveBeenCalled())
    const route = navigateMock.mock.calls.at(-1)![0] as string
    const operation = new URL(route, 'https://fixture.invalid').searchParams.get('operation')!
    const key = `vinote:source-receipt:import-owner:${operation}`
    expect(JSON.parse(localStorage.getItem(key)!).sourceType).toBe(classified)
    cleanup(); queryMock.value = 'meeting=1&operation=' + operation
    apiMock.apiJson.mockResolvedValue({ task_id: 'classified-child', status: 'transcribing', processed_seconds: 10, total_seconds: 30 })
    renderGenerator()
    const list = await screen.findByRole('list', { name: '会议纪要处理步骤' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(steps)
    expect(screen.queryByRole('listitem', { name: /核对共享画面与发言/ }) !== null).toBe(classified === 'meeting_video')
    cleanup()
    libraryMock.saveNote.mockResolvedValue({ id: 'saved-classified' })
    apiMock.apiJson.mockResolvedValue({ task_id: 'classified-child', status: 'success', result: { task_id: 'classified-child', title: '2026-10-19 15:41 | Source topic', markdown: '# Synthetic summary' } })
    renderGenerator()
    await waitFor(() => expect(libraryMock.saveNote).toHaveBeenCalled())
    expect(libraryMock.saveNote.mock.calls[0][5]).toBe(classified === 'unknown' ? 'meeting_unknown' : classified)
    expect(libraryMock.saveNote.mock.calls[0][0]).toBe('2026-10-19 15:41｜Synthetic summary')
    expect(apiMock.apiJson.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  })
  it.each([undefined, null, 'bad-id', '2BFA5300-A102-45A8-89CF-123456789ABC', '11111111-1111-4111-8111-111111111111'])('v2 invalid canonical %s cannot open confirmation or POST', async canonical => {
    const parent = '11111111-1111-4111-8111-111111111111'
    const context = { ...frozenContext, protocol: 2, parent_task_id: parent, canonical_task_id: canonical }
    queryMock.value = `meeting=1&task=${parent}`
    apiMock.apiJson.mockImplementation((path: string) => Promise.resolve(path.endsWith('/new-generation-context') ? context : { task_id: parent, status: 'failed', message: '上次未完成', retryable: false }))
    renderGenerator(); await screen.findByText('上次未完成')
    await userEvent.click(screen.getByRole('button', { name: '确认原模型，开始新的处理' }))
    await screen.findByText('原文件与冻结模型尚不能完整核验，未使用当前默认模型。')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method)).toBe(true)
    expect(localStorage.length).toBe(0)
  })
  it('v1 rejects an unexpected canonical field instead of upgrading the request implicitly', async () => {
    queryMock.value = 'meeting=1&task=selected-task'
    apiMock.apiJson.mockImplementation((path: string) => Promise.resolve(path.endsWith('/new-generation-context') ? { ...frozenContext, canonical_task_id: '2bfa5300-a102-45a8-89cf-123456789abc' } : { task_id: 'selected-task', status: 'failed', message: '上次未完成', retryable: false }))
    renderGenerator(); await screen.findByText('上次未完成')
    await userEvent.click(screen.getByRole('button', { name: '确认原模型，开始新的处理' }))
    await screen.findByText('原文件与冻结模型尚不能完整核验，未使用当前默认模型。')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  })
  it('v2 unknown operation recovery only queries the exact receipt and never replays its canonical submission', async () => {
    const context = { ...frozenContext, protocol: 2, canonical_task_id: '2bfa5300-a102-45a8-89cf-123456789abc' }
    const pending = { operationId: 'v2-unknown', independentGeneration: true, parentTaskId: 'selected-task', frozenContext: context, meeting: true, workspace: { scope: 'personal' }, submissionState: 'unknown' }
    localStorage.setItem('vinote:source-receipt:import-owner:v2-unknown', JSON.stringify(pending))
    queryMock.value = 'meeting=1&operation=v2-unknown'
    apiMock.apiJson.mockResolvedValue({ operation_id: 'v2-unknown', task_id: 'reserved-child', state: 'reserved' })
    renderGenerator()
    expect(within(await screen.findByRole('alert')).getByText(/提交已登记，尚未确认排队/)).toBeVisible()
    expect(apiMock.apiJson.mock.calls.every(([path, init]) => path === '/api/source-requests/v2-unknown' && !init?.method)).toBe(true)
    expect(JSON.parse(localStorage.getItem('vinote:source-receipt:import-owner:v2-unknown')!).frozenContext).toEqual(context)
    expect(libraryMock.saveNote).not.toHaveBeenCalled()
  })
  it('v2 account ABA invalidates the open confirmation before any POST', async () => {
    await openFrozenSheet({ ...frozenContext, protocol: 2, canonical_task_id: '2bfa5300-a102-45a8-89cf-123456789abc' })
    act(() => { useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } }); useAuthStore.setState({ user: { id: 'import-owner', email: 'import@example.invalid' } }) })
    expect(screen.queryByRole('button', { name: '确认原模型并开始新的处理' })).toBeNull()
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method)).toBe(true)
    expect(localStorage.length).toBe(0)
  })
  it('double confirmation accepts one distinct operation without changing the global receipt', async () => {
    const old = JSON.stringify({ id: 'different-task', meeting: true, workspace: { scope: 'personal' } })
    localStorage.setItem('vinote:import-receipt:import-owner:meeting', old)
    const dialog = await openFrozenSheet()
    apiMock.apiJson.mockImplementation((_path: string, init?: RequestInit) => {
      const body = JSON.parse(init!.body as string)
      return Promise.resolve({ operation_id: body.operation_id, task_id: 'independent-task', state: 'accepted' })
    })
    await userEvent.dblClick(within(dialog).getByRole('button', { name: '确认原模型并开始新的处理' }))
    const writes = apiMock.apiJson.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(writes).toHaveLength(1)
    const body = JSON.parse(writes[0][1].body)
    expect(JSON.parse(localStorage.getItem(`vinote:source-receipt:import-owner:${body.operation_id}`)!)).toMatchObject({ id: 'independent-task', submissionState: 'accepted', independentGeneration: true, parentTaskId: 'selected-task', frozenContext })
    expect(localStorage.getItem('vinote:import-receipt:import-owner:meeting')).toBe(old)
  })
  it('restored unknown independent operation queries its exact receipt without replaying POST or replacing global intake', async () => {
    const old = JSON.stringify({ id: 'another-task', meeting: true, workspace: { scope: 'personal' } })
    localStorage.setItem('vinote:import-receipt:import-owner:meeting', old)
    localStorage.setItem('vinote:source-receipt:import-owner:new-op', JSON.stringify({ operationId: 'new-op', independentGeneration: true, parentTaskId: 'selected-task', frozenContext, meeting: true, workspace: { scope: 'personal' }, submissionState: 'unknown' }))
    queryMock.value = 'meeting=1&operation=new-op'
    apiMock.apiJson.mockImplementation((path: string) => Promise.resolve(path.includes('source-requests') ? { operation_id: 'new-op', task_id: 'independent-task', state: 'accepted' } : { task_id: 'independent-task', status: 'failed', message: '本次未完成', error_code: 'unknown_result' }))
    renderGenerator()
    await screen.findByText('本次未完成')
    expect(apiMock.apiJson).toHaveBeenCalledWith('/api/source-requests/new-op')
    expect(apiMock.apiJson).toHaveBeenCalledWith('/api/task/independent-task')
    expect(apiMock.apiJson.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
    expect(localStorage.getItem('vinote:import-receipt:import-owner:meeting')).toBe(old)
    expect(screen.queryByRole('button', { name: '确认原模型，开始新的处理' })).not.toBeInTheDocument()
  })

  it('receipt storage failure prevents new POST', async () => {
    const dialog = await openFrozenSheet()
    const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage full') })
    try {
      await userEvent.click(within(dialog).getByRole('button', { name: '确认原模型并开始新的处理' }))
      await screen.findByText('storage full')
      expect(apiMock.apiJson.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
    } finally { write.mockRestore() }
  })
  it('A-B-A account switch invalidates a previously opened frozen confirmation', async () => {
    await openFrozenSheet()
    act(() => { useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } }); useAuthStore.setState({ user: { id: 'import-owner', email: 'import@example.invalid' } }) })
    expect(screen.queryByRole('button', { name: '确认原模型并开始新的处理' })).not.toBeInTheDocument()
    expect(apiMock.apiJson.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  })

  it.each(['failed', 'success'])('exact task route only reads %s and preserves another active receipt', async state => {
    const old = JSON.stringify({ id: 'another-task', workspace: { scope: 'personal' }, meeting: true, submissionState: 'accepted' })
    localStorage.setItem('vinote:import-receipt:import-owner:meeting', old)
    queryMock.value = 'meeting=1&task=selected-task'
    apiMock.apiJson.mockResolvedValue({ task_id: 'selected-task', status: state, message: '处理未完成', retryable: true, error_code: state === 'failed' ? 'unknown_result' : undefined, result: state === 'success' ? { task_id: 'selected-task', title: '原结果', markdown: 'body' } : undefined })
    renderGenerator('/files?purpose=meeting&file=task%3Aselected-task&q=kept')
    await waitFor(() => expect(apiMock.apiJson).toHaveBeenCalledWith('/api/task/selected-task'))
    if (state === 'failed') { await screen.findByText('处理未完成'); await userEvent.click(screen.getByRole('button', { name: '查看原任务状态' })) }
    else await screen.findByText('原任务已完成。当前仅查看处理记录，不会重新生成或恢复保存。')
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
    expect(libraryMock.saveNote).not.toHaveBeenCalled()
    expect(localStorage.getItem('vinote:import-receipt:import-owner:meeting')).toBe(old)
    expect(screen.getByRole('link', { name: '返回文件库' })).toHaveAttribute('href', '/files?purpose=meeting&file=task%3Aselected-task&q=kept')
  })

  it.each([true, false])('read-only meeting=%s uses a record heading even before delayed GET and collapses source', async meeting => {
    queryMock.value = `${meeting ? 'meeting=1&' : ''}task=selected-task`
    let resolve!: (value: unknown) => void
    apiMock.apiJson.mockReturnValue(new Promise(done => { resolve = done }))
    renderGenerator('/files?purpose=meeting&q=kept')
    expect(screen.getByRole('heading', { level: 1, name: meeting ? '会议处理记录' : '处理记录' })).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(screen.getByText('查看本次处理的进度、结果与来源。')).toBeInTheDocument()
    expect(screen.queryByText('从已有录制生成会议纪要')).not.toBeInTheDocument()
    const source = screen.getByRole('region', { name: '任务来源' })
    expect(source.querySelector('details')).not.toHaveAttribute('open')
    await act(async () => resolve({ task_id: 'selected-task', status: 'failed', message: '此次处理未完成', error_code: 'unknown_result', retryable: false }))
    expect(await screen.findByRole('button', { name: '查看原任务状态' })).toBeInTheDocument()
    if (meeting) expect(screen.getByRole('button', { name: '确认原模型，开始新的处理' })).toBeInTheDocument()
    else expect(screen.queryByRole('button', { name: '确认原模型，开始新的处理' })).toBeNull()
    expect(screen.queryByRole('button', { name: '更换来源，开始新任务' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看处理历史与恢复' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回文件库' })).toHaveAttribute('href', '/files?purpose=meeting&q=kept')
    expect(screen.queryByRole('link', { name: '返回资料与原文件' })).not.toBeInTheDocument()
    expect(source.querySelector('details')).not.toHaveAttribute('open')
    await userEvent.click(within(source).getByText('查看任务来源'))
    expect(source.querySelector('details')).toHaveAttribute('open')
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
    expect(localStorage.length).toBe(0)
  })

  it('completed read-only record keeps one top return without a duplicate materials link', async () => {
    queryMock.value = 'meeting=1&task=selected-task'
    apiMock.apiJson.mockResolvedValue({ task_id: 'selected-task', status: 'success', result: { task_id: 'selected-task', title: '完成', markdown: 'body' } })
    renderGenerator('/files?q=original-query')
    await screen.findByText('原任务已完成。当前仅查看处理记录，不会重新生成或恢复保存。')
    expect(screen.getByRole('heading', { level: 1, name: '会议处理记录' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: '返回文件库' })).toHaveLength(1)
    expect(screen.queryByRole('link', { name: '返回资料与原文件' })).not.toBeInTheDocument()
    expect(libraryMock.saveNote).not.toHaveBeenCalled()
  })

  it.each(['not_found', 'source_unavailable', 'source_version_unavailable'])('read-only %s retains a necessary original materials entry', async reason => {
    queryMock.value = 'meeting=1&task=selected-task'
    apiMock.apiJson.mockResolvedValue({ task_id: 'selected-task', status: reason === 'not_found' ? reason : 'failed', error_code: reason, retryable: false, message: '原文件需重新核验' })
    renderGenerator('/tasks?tab=generation')
    await screen.findByRole('link', { name: '返回资料与原文件' })
    expect(screen.getByRole('link', { name: '返回任务与恢复' })).toHaveAttribute('href', '/tasks?tab=generation')
    expect(apiMock.apiJson.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  })

  it.each([true, false])('ordinary intake meeting=%s preserves original heading and does not become read-only', async meeting => {
    queryMock.value = meeting ? 'meeting=1' : ''
    renderGenerator('/files?q=kept')
    expect(screen.getByRole('heading', { level: 1, name: meeting ? '从已有录制生成会议纪要' : '链接或文件转笔记' })).toBeInTheDocument()
    expect(screen.queryByText('查看本次处理的进度、结果与来源。')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '处理设置' })).toBeInTheDocument()
    expect(apiMock.apiJson).not.toHaveBeenCalled()
  })

  it('read-only unknown outcome uses two product lines and exact GET query without replay', async () => {
    vi.stubEnv('DEV', false)
    try {
      queryMock.value = 'meeting=1&task=selected-task'
      apiMock.apiJson.mockResolvedValue({ task_id: 'selected-task', status: 'failed', message: 'connection unknown internal result', error_code: 'unknown_result', retryable: true })
      renderGenerator('/files?q=kept')
      const alert = await screen.findByRole('alert')
      expect(alert.querySelectorAll('p')).toHaveLength(2)
      expect(within(alert).getByText('本次处理结果尚未确认，暂无可保存的完整结果。')).toBeVisible()
      expect(within(alert).getByText('可查询本次状态；重新处理需要再次确认，不会自动重试。')).toBeVisible()
      expect(Array.from(alert.querySelectorAll('p'), part => part.textContent).join('')).not.toMatch(/原任务|后台|底层|恢复保存|此次转写未完成/)
      expect(document.body.textContent).not.toContain('connection unknown internal result')
      expect(screen.getByText('查看本次处理的进度、结果与来源。')).toBeVisible()
      await userEvent.click(screen.getByRole('button', { name: '查看原任务状态' }))
      await screen.findByRole('alert')
      expect(apiMock.apiJson.mock.calls.every(([path, init]) => path === '/api/task/selected-task' && (!init?.method || init.method === 'GET'))).toBe(true)
      expect(localStorage.length).toBe(0)
      expect(libraryMock.saveNote).not.toHaveBeenCalled()
      expect(screen.getByRole('button', { name: '确认原模型，开始新的处理' })).toBeInTheDocument()
    } finally { vi.unstubAllEnvs() }
  })

  it('keeps a bare running task neutral without inventing note workflow, six steps or a media lookup', async () => {
    queryMock.value = 'task=selected-task'
    apiMock.apiJson.mockResolvedValue({ task_id: 'selected-task', status: 'transcribing', processed_seconds: 1200, total_seconds: 1536, message: '正在处理原任务' })
    renderGenerator()
    await screen.findByRole('heading', { name: '正在处理任务' })
    expect(screen.getByRole('heading', { level: 1, name: '处理记录' })).toBeVisible()
    expect(screen.getByRole('link', { name: '返回任务与恢复' })).toHaveAttribute('href', '/tasks?tab=generation')
    expect(screen.queryByText('笔记处理记录')).toBeNull()
    expect(screen.queryByText('正在生成笔记')).toBeNull()
    expect(screen.queryByRole('list', { name: '笔记处理步骤' })).toBeNull()
    expect(screen.queryByRole('progressbar')).toBeNull()
    expect(apiMock.apiJson.mock.calls.every(([path, init]) => path === '/api/task/selected-task' && !init?.method)).toBe(true)
    expect(libraryMock.saveNote).not.toHaveBeenCalled()
    expect(localStorage.length).toBe(0)
  })
  it('does not infer meeting workflow from media type or a foreign-owner task context', async () => {
    queryMock.value = 'task=selected-task'
    apiMock.apiJson.mockResolvedValue({ task_id: 'selected-task', status: 'transcribing', message: '' })
    render(<MemoryRouter initialEntries={[{ pathname: '/generate', search: '?task=selected-task', state: { readOnlyTask: { id: 'selected-task', owner: 'different-owner', meeting: true, sourceType: 'meeting_video' } } }]}><I18nProvider><NoteGenerator /></I18nProvider></MemoryRouter>)
    await screen.findByRole('heading', { name: '正在处理任务' })
    expect(screen.getByRole('heading', { level: 1, name: '处理记录' })).toBeVisible()
    expect(screen.queryByRole('list')).toBeNull()
    expect(apiMock.apiJson.mock.calls.every(([path, init]) => path === '/api/task/selected-task' && !init?.method)).toBe(true)
  })
  it('preserves a valid return context but rejects an unsafe parent for bare task records', async () => {
    queryMock.value = 'task=selected-task'
    apiMock.apiJson.mockResolvedValue({ task_id: 'selected-task', status: 'transcribing', message: '' })
    const first = renderGenerator('/files?q=kept')
    await screen.findByRole('heading', { name: '正在处理任务' })
    expect(screen.getByRole('link', { name: '返回文件库' })).toHaveAttribute('href', '/files?q=kept')
    first.unmount()
    renderGenerator('https://outside.invalid/')
    await screen.findByRole('heading', { name: '正在处理任务' })
    expect(screen.getByRole('link', { name: '返回任务与恢复' })).toHaveAttribute('href', '/tasks?tab=generation')
    expect(apiMock.apiJson.mock.calls.every(([path, init]) => path === '/api/task/selected-task' && !init?.method)).toBe(true)
  })
  it.each(['unknown_result', 'typed_terminal'])('bare failed %s can only query or return, never confirm a new note operation or save', async errorCode => {
    queryMock.value = 'task=selected-task'
    apiMock.apiJson.mockResolvedValue({ task_id: 'selected-task', status: 'failed', message: '此次处理未完成', error_code: errorCode, retryable: true })
    renderGenerator()
    await screen.findByRole('alert')
    expect(screen.getByRole('heading', { level: 1, name: '处理记录' })).toBeVisible()
    expect(screen.queryByRole('button', { name: '确认原模型，开始新的处理' })).toBeNull()
    expect(screen.queryByRole('button', { name: /恢复保存|更换来源|开始整理/ })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '查看原任务状态' }))
    await screen.findByRole('alert')
    expect(apiMock.apiJson.mock.calls.every(([path, init]) => path === '/api/task/selected-task' && !init?.method)).toBe(true)
    expect(libraryMock.saveNote).not.toHaveBeenCalled()
    expect(localStorage.length).toBe(0)
    expect(screen.getByRole('link', { name: '返回任务与恢复' })).toHaveAttribute('href', '/tasks?tab=generation')
  })
  it('read-only first query failure remains unconfirmed and only offers another read', async () => {
    queryMock.value = 'task=selected-task'
    apiMock.apiJson.mockRejectedValue(new TypeError('network failure'))
    renderGenerator()
    const alert = await screen.findByRole('alert')
    expect(alert.querySelectorAll('p')).toHaveLength(2)
    expect(within(alert).getByText('本次处理结果尚未确认。')).toBeVisible()
    expect(within(alert).getByText('请重新查询本次状态，确认前不会重新处理。')).toBeVisible()
    expect(screen.queryByRole('button', { name: '确认原模型，开始新的处理' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '重新查询原任务状态' }))
    await screen.findByRole('alert')
    expect(apiMock.apiJson.mock.calls.every(([path, init]) => path === '/api/task/selected-task' && !init?.method)).toBe(true)
  })

  it('read-only known failure retains its specific reason without repeating the general outcome', async () => {
    queryMock.value = 'meeting=1&task=selected-task'
    apiMock.apiJson.mockResolvedValue({ task_id: 'selected-task', status: 'failed', error_code: 'quota_exhausted', retryable: false, message: '语音服务额度不足，本次处理未完成。' })
    renderGenerator()
    const alert = await screen.findByRole('alert')
    expect(alert.querySelectorAll('p')).toHaveLength(2)
    expect(within(alert).getByText('语音服务额度不足，本次处理未完成。')).toBeVisible()
    expect(within(alert).getByText('原文件和处理记录已保留。可查询状态，重新处理需要再次确认。')).toBeVisible()
    expect(alert.textContent).not.toContain('尚未确认')
    expect(screen.getAllByText('语音服务额度不足，本次处理未完成。')).toHaveLength(1)
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  })

  it('read-only missing source keeps the necessary original entry and two clear lines', async () => {
    queryMock.value = 'meeting=1&task=selected-task'
    apiMock.apiJson.mockResolvedValue({ task_id: 'selected-task', status: 'failed', error_code: 'source_unavailable', retryable: false, message: '原文件暂不可用，请重新读取资料。' })
    renderGenerator('/tasks?tab=generation')
    const alert = await screen.findByRole('alert')
    expect(alert.querySelectorAll('p')).toHaveLength(2)
    expect(within(alert).getByText('原文件暂不可读取，本次处理未完成。')).toBeVisible()
    expect(within(alert).getByText('请返回资料查看原文件，或查看处理历史。')).toBeVisible()
    expect(within(alert).getByRole('link', { name: '返回资料与原文件' })).toBeInTheDocument()
  })

  it('exact task route rejects a different response identity without save or receipt changes', async () => {
    queryMock.value = 'task=selected-task'
    apiMock.apiJson.mockResolvedValue({ task_id: 'other', status: 'success', result: { task_id: 'other', title: 'wrong', markdown: 'body' } })
    renderGenerator()
    await screen.findByText('无法读取原任务进度，处理结果尚未确认。请查询原结果，不重复生成。')
    expect(libraryMock.saveNote).not.toHaveBeenCalled()
    expect(localStorage.length).toBe(0)
  })

  it.each([
    ['zh-CN', true, '生成完成后，会议纪要会保存到所选位置。'],
    ['zh-CN', false, '生成完成后，笔记会保存到所选位置。'],
    ['en', true, 'When generation finishes, the meeting minutes will be saved to the selected location.'],
    ['en', false, 'When generation finishes, the note will be saved to the selected location.'],
  ] as const)('uses workflow-aware save copy for %s meeting=%s without dispatching', async (language, meeting, hint) => {
    languageMock.value = language
    queryMock.value = meeting ? 'meeting=1' : ''
    renderGenerator()
    await userEvent.click(screen.getByRole('button', { name: '处理设置' }))
    expect(within(screen.getByRole('dialog')).getByText(hint)).toBeVisible()
    expect(apiMock.apiJson).not.toHaveBeenCalled()
  })

  it('uses one processing title and explanation, collapses the source and keeps independent received duration without saved coverage', async () => {
    queryMock.value = 'meeting=1'
    localStorage.setItem('vinote:import-receipt:import-owner:meeting', JSON.stringify({ id: 'active-meeting', submissionState: 'accepted', workspace: { scope: 'personal' }, meeting: true, sourceType: 'audio', sourceTitle: 'Original meeting.wav' }))
    apiMock.apiJson.mockResolvedValue({ status: 'transcribing', stage: 'parallel_analysis', total_seconds: 3037, received_seconds: 2772, speaker_analysis_ready: true, message: '技术警告：等待服务器，音频进度并非整体完成' })
    renderGenerator()
    await screen.findByText('已提交识别 46:12 / 50:37', {}, { timeout: 4000 })
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(1)
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('正在生成会议纪要')
    expect(screen.queryByText(/技术警告|等待服务器|并非整体完成/)).not.toBeInTheDocument()
    const source = screen.getByRole('region', { name: '任务来源' })
    expect(source.querySelector('details')).not.toHaveAttribute('open')
    await userEvent.click(within(source).getByText('查看任务来源'))
    expect(within(source).getByText('Original meeting.wav')).toBeVisible()
    expect(apiMock.apiJson.mock.calls.every(([, options]) => !options?.method)).toBe(true)
  })

  it('keeps invalid links as field errors without starting a task or offering task recovery', async () => {
    renderGenerator()
    const input = screen.getByRole('textbox', { name: '网页或视频链接' })
    await userEvent.type(input, '不是有效链接')
    await userEvent.click(screen.getByRole('button', { name: 'Organize notes' }))
    expect(input).toHaveValue('不是有效链接')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveFocus()
    expect(screen.getByRole('alert')).toHaveTextContent('请粘贴完整的 http 或 https 网页或视频链接')
    expect(screen.queryByRole('button', { name: '重新生成' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '查看处理历史与恢复' })).not.toBeInTheDocument()
    expect(apiMock.apiJson).not.toHaveBeenCalled()
    expect(localStorage.getItem('vinote:import-receipt:import-owner:note')).toBeNull()
    await userEvent.clear(input)
    await userEvent.type(input, 'https://example.com/video')
    expect(input).not.toHaveAttribute('aria-invalid', 'true')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(apiMock.apiJson).not.toHaveBeenCalled()
    apiMock.apiJson.mockResolvedValueOnce({ task_id: 'valid-after-correction' })
    await userEvent.click(screen.getByRole('button', { name: 'Organize notes' }))
    expect(apiMock.apiJson.mock.calls.map(([path]) => path)).toEqual(['/api/generate', '/api/task/valid-after-correction'])
    expect(JSON.parse(localStorage.getItem('vinote:import-receipt:import-owner:note')!)).toMatchObject({ id: 'valid-after-correction' })
  })

  it('shows a neutral task source during the first PDF registration without claiming recovery', async () => {
    queryMock.value = 'mode=file'
    apiMock.apiJson.mockImplementation((path: string) => {
      if (path === '/api/files') return new Promise(() => {})
      throw new Error(`Unexpected request: ${path}`)
    })
    renderGenerator()
    await userEvent.upload(screen.getByLabelText('选择或拖入音视频、PDF、Word 和文字文件'), new File(['pdf'], 'first-import.pdf', { type: 'application/pdf' }))
    await userEvent.click(screen.getByRole('button', { name: 'Organize notes' }))
    const source = await screen.findByRole('region', { name: '任务来源' })
    expect(within(source).getByText('查看任务来源')).toBeInTheDocument()
    expect(source).toHaveTextContent('first-import.pdf')
    expect(source).toHaveTextContent('导入文档')
    expect(source).toHaveTextContent('提交状态')
    expect(source).toHaveTextContent('文件保存待确认')
    expect(screen.queryByText(/正在恢复原提交|正在恢复原任务|原任务来源/)).not.toBeInTheDocument()
    expect(apiMock.apiJson.mock.calls.map(([path]) => path)).toEqual(['/api/files'])
    expect(JSON.parse(localStorage.getItem('vinote:import-receipt:import-owner:note')!)).toMatchObject({ sourceTitle: 'first-import.pdf', submissionState: 'registering' })
  })

  it('resumes the accepted task after leaving without submitting generation again', async () => {
    apiMock.apiJson.mockResolvedValueOnce({ task_id: 'accepted-import' })
    const view = renderGenerator()
    await userEvent.type(screen.getByPlaceholderText('Paste a webpage, video, or online document URL...'), 'https://example.com/video')
    await userEvent.click(screen.getByRole('button', { name: 'Organize notes' }))
    await waitFor(() => expect(localStorage.getItem('vinote:import-receipt:import-owner:note')).toContain('accepted-import'))
    view.unmount()
    renderGenerator()
    await waitFor(() => expect(useNoteGenerationStore.getState().status).toBe('processing'))
    expect(apiMock.apiJson.mock.calls.filter(([path]) => path === '/api/generate')).toHaveLength(1)
    expect(apiMock.apiJson.mock.calls.filter(([path]) => path === '/api/task/accepted-import')).toHaveLength(2)
    expect(screen.getByRole('link', { name: '返回笔记' })).toHaveAttribute('href', '/notes')
  })

  it('recovers an unsaved result by querying the same task without a second generation', async () => {
    apiMock.apiJson.mockResolvedValueOnce({ task_id: 'save-recovery' }).mockResolvedValue({ status: 'success', result: { task_id: 'save-recovery', title: 'Recovered', markdown: '# Preserved result' } })
    libraryMock.saveNote.mockResolvedValueOnce(null).mockResolvedValueOnce({ id: 'saved-note' })
    renderGenerator()
    await userEvent.type(screen.getByPlaceholderText('Paste a webpage, video, or online document URL...'), 'https://example.com/video')
    await userEvent.click(screen.getByRole('button', { name: 'Organize notes' }))
    await waitFor(() => expect(useNoteGenerationStore.getState().status).toBe('failed'), { timeout: 4000 })
    expect(localStorage.getItem('vinote:import-receipt:import-owner:note')).toContain('save-recovery')
    await userEvent.click(screen.getByRole('button', { name: '查询原结果并恢复保存' }))
    await waitFor(() => expect(useNoteGenerationStore.getState().status).toBe('success'), { timeout: 4000 })
    expect(apiMock.apiJson.mock.calls.filter(([path]) => path === '/api/generate')).toHaveLength(1)
    expect(localStorage.getItem('vinote:import-receipt:import-owner:note')).toBeNull()
  })

  it('stops polling when the task record is missing' , async () => {
    apiMock.apiJson.mockResolvedValueOnce({ task_id: 'missing-task' })
      .mockResolvedValue({ status: 'not_found', message: 'Task not found' })
    renderGenerator()
    await userEvent.type(
      screen.getByPlaceholderText('Paste a webpage, video, or online document URL...'),
      'https://example.com/video'
    )
    await userEvent.click(screen.getByRole('button', { name: 'Organize notes' }))
    await waitFor(() => expect(useNoteGenerationStore.getState().status).toBe('failed'), { timeout: 4000 })
    expect(screen.getByText('任务记录不存在或已丢失。原回执已保留，请核验原提交，不重复生成。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新查询原任务状态' })).toBeEnabled()
    expect(localStorage.getItem('vinote:import-receipt:import-owner:note')).toContain('missing-task')
  })

  it('recovers a lost submission by GET of the protected operation without repeating POST', async () => {
    apiMock.apiJson
      .mockRejectedValueOnce(new Error('backend unavailable'))
      .mockImplementationOnce(async (path) => ({ task_id: 'retry-task', state: 'accepted', operation_id: String(path).split('/').pop(), source_type: 'file' }))

    renderGenerator()

    await userEvent.type(
      screen.getByPlaceholderText('Paste a webpage, video, or online document URL...'),
      'https://example.com/video'
    )
    await userEvent.click(screen.getByRole('button', { name: 'Organize notes' }))

    expect(await screen.findByText('backend unavailable')).toBeInTheDocument()

    const pending = JSON.parse(localStorage.getItem('vinote:import-receipt:import-owner:note')!)
    await userEvent.click(screen.getByRole('button', { name: '核验原提交' }))

    await waitFor(() => expect(apiMock.apiJson).toHaveBeenCalledTimes(3))
    expect(apiMock.apiJson.mock.calls[1][0]).toBe(`/api/source-requests/${pending.operationId}`)
    expect(apiMock.apiJson.mock.calls[1][1]).toBeUndefined()
    expect(apiMock.apiJson.mock.calls.filter(([path]) => path === '/api/generate')).toHaveLength(1)
  })
  it('stores its operation and source before dispatch and sends the same header', async () => {
    apiMock.apiJson.mockImplementationOnce(async (_path, init) => {
      const pending = JSON.parse(localStorage.getItem('vinote:import-receipt:import-owner:note')!)
      expect(pending).toMatchObject({ submissionState: 'unknown', sourceUrl: 'https://python.org/about' })
      expect(init.headers['X-VINote-Operation-Id']).toBe(pending.operationId)
      expect(localStorage.getItem(`vinote:source-receipt:import-owner:${pending.operationId}`)).toBeTruthy()
      return { task_id: 'accepted', operation_id: pending.operationId, state: 'accepted', source_type: 'file' }
    })
    renderGenerator()
    await userEvent.type(screen.getByPlaceholderText('Paste a webpage, video, or online document URL...'), 'https://python.org/about')
    await userEvent.click(screen.getByRole('button', { name: 'Organize notes' }))
    await waitFor(() => expect(useNoteGenerationStore.getState().status).toBe('processing'))
  })
  it('cold start queries the original reserved receipt and never dispatches it', async () => {
    const pending = { operationId: 'original', workspace: { scope: 'personal' }, meeting: false, submissionState: 'unknown', sourceUrl: 'https://python.org/about' }
    localStorage.setItem('vinote:import-receipt:import-owner:note', JSON.stringify(pending))
    apiMock.apiJson.mockResolvedValue({ operation_id: 'original', task_id: 'reserved-task', state: 'reserved' })
    renderGenerator()
    await waitFor(() => expect(within(screen.getByRole('alert')).getByText(/提交已登记，尚未确认排队/)).toBeInTheDocument())
    expect(apiMock.apiJson).toHaveBeenCalledWith('/api/source-requests/original')
    expect(apiMock.apiJson).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: '更换来源，开始新任务' })).toBeDisabled()
    expect(JSON.parse(localStorage.getItem('vinote:import-receipt:import-owner:note')!).operationId).toBe('original')
  })
  it('404 keeps the original ID and only offers another read', async () => {
    const pending = { operationId: 'unknown', workspace: { scope: 'personal' }, meeting: false, submissionState: 'unknown' }
    localStorage.setItem('vinote:import-receipt:import-owner:note', JSON.stringify(pending))
    apiMock.apiJson.mockRejectedValue(new (await import('../lib/api')).ApiError('not found', 404, null))
    renderGenerator()
    await screen.findByText(/尚未查到原提交回执/)
    await userEvent.click(screen.getByRole('button', { name: '核验原提交' }))
    expect(apiMock.apiJson.mock.calls.every(([path]) => path === '/api/source-requests/unknown')).toBe(true)
    expect(JSON.parse(localStorage.getItem('vinote:import-receipt:import-owner:note')!).operationId).toBe('unknown')
  })
  it('failure to protect an operation prevents network dispatch', async () => {
    const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => { throw new Error('disk full') })
    renderGenerator()
    await userEvent.type(screen.getByPlaceholderText('Paste a webpage, video, or online document URL...'), 'https://python.org/about')
    await userEvent.click(screen.getByRole('button', { name: 'Organize notes' }))
    expect(apiMock.apiJson).not.toHaveBeenCalled()
    storage.mockRestore()
  })
  it('registers the DOCX original once and protects its ID before upload dispatch', async () => {
    queryMock.value = 'mode=file'
    apiMock.apiJson.mockImplementation(async (path, init) => {
      if (path === '/api/task/document-task') return { status: 'preparing', message: '' }
      const pending = JSON.parse(localStorage.getItem('vinote:import-receipt:import-owner:note')!)
      if (path === '/api/files') {
        expect(pending.submissionState).toBe('registering')
        return { id: 'original-file' }
      }
      expect(path).toBe('/api/generate_from_upload')
      expect(pending).toMatchObject({ localFileId: 'original-file', submissionState: 'unknown', sourceTitle: 'source.docx' })
      expect(init.body.get('local_file_id')).toBe('original-file')
      expect(init.body.get('source_type')).toBe('document')
      expect(init.headers['X-VINote-Operation-Id']).toBe(pending.operationId)
      return { task_id: 'document-task', operation_id: pending.operationId, state: 'accepted', source_type: 'file' }
    })
    renderGenerator()
    await userEvent.upload(screen.getByLabelText('选择或拖入音视频、PDF、Word 和文字文件'), new File(['document'], 'source.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }))
    await userEvent.click(screen.getByRole('button', { name: 'Organize notes' }))
    await waitFor(() => expect(useNoteGenerationStore.getState().status).toBe('processing'))
    expect(apiMock.apiJson.mock.calls.map(([path]) => path)).toEqual(['/api/files', '/api/generate_from_upload', '/api/task/document-task'])
  })
  it('an unknown file registration cannot automatically register or upload again', async () => {
    queryMock.value = 'mode=file'
    apiMock.apiJson.mockRejectedValueOnce(new Error('registration response lost')).mockRejectedValueOnce(new (await import('../lib/api')).ApiError('not found', 404, null))
    renderGenerator()
    await userEvent.upload(screen.getByLabelText('选择或拖入音视频、PDF、Word 和文字文件'), new File(['document'], 'source.docx'))
    await userEvent.click(screen.getByRole('button', { name: 'Organize notes' }))
    await screen.findByText('registration response lost')
    const pending = JSON.parse(localStorage.getItem('vinote:import-receipt:import-owner:note')!)
    await userEvent.click(screen.getByRole('button', { name: '核验原提交' }))
    await within(screen.getByRole('alert')).findByText(/文件是否保存尚未确认/)
    expect(apiMock.apiJson.mock.calls.map(([path]) => path)).toEqual(['/api/files', `/api/source-requests/${pending.operationId}`])
  })
  it('retries an explicitly failed source only through its original task after readback', async () => {
    localStorage.setItem('vinote:import-receipt:import-owner:note', JSON.stringify({ id: 'same-task', operationId: 'same-op', submissionState: 'accepted', workspace: { scope: 'personal' }, meeting: false }))
    apiMock.apiJson.mockResolvedValue({ status: 'error', retryable: true, message: 'provider error' })
    renderGenerator()
    await waitFor(() => expect(useNoteGenerationStore.getState().status).toBe('failed'), { timeout: 4000 })
    apiMock.apiJson.mockResolvedValueOnce({ status: 'failed', retryable: true }).mockResolvedValueOnce({ status: 'preparing' }).mockResolvedValue({ status: 'preparing', message: '' })
    await userEvent.click(screen.getByRole('button', { name: '重试处理原任务' }))
    await waitFor(() => expect(useNoteGenerationStore.getState().status).toBe('processing'))
    expect(apiMock.apiJson.mock.calls.slice(-3)).toEqual([['/api/task/same-task'], ['/api/task/same-task/retry', { method: 'POST' }], ['/api/task/same-task']])
    expect(apiMock.apiJson.mock.calls.some(([path]) => path.startsWith('/api/generate'))).toBe(false)
  })
  it('an archived operation deep link cannot silently replace missing recovery metadata', async () => {
    queryMock.value = 'operation=missing-archive'
    renderGenerator()
    expect(await screen.findByText(/无法读取本机任务回执/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Regenerate' })).toBeDisabled()
    expect(apiMock.apiJson).not.toHaveBeenCalled()
  })
  it('shows the accepted original document while a new URL entry resumes the same task', async () => {
    localStorage.setItem('vinote:import-receipt:import-owner:note', JSON.stringify({ id: 'old-document-task', operationId: 'old-document-op', submissionState: 'accepted', workspace: { scope: 'personal' }, meeting: false, mode: 'document', sourceType: 'file', sourceTitle: 'previous-review.docx' }))
    apiMock.apiJson.mockResolvedValue({ status: 'preparing', message: 'processing' })
    renderGenerator()
    const source = screen.getByRole('region', { name: '任务来源' })
    expect(source).toHaveTextContent('previous-review.docx'); expect(source).toHaveTextContent('导入文档'); expect(source).toHaveTextContent('服务已接收任务')
    expect(screen.queryByPlaceholderText('Paste a webpage, video, or online document URL...')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('选择或拖入音视频、PDF、Word 和文字文件')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '处理设置' })).not.toBeInTheDocument()
    await waitFor(() => expect(apiMock.apiJson).toHaveBeenCalledWith('/api/task/old-document-task'), { timeout: 4000 })
    expect(apiMock.apiJson.mock.calls.every(([path]) => path === '/api/task/old-document-task')).toBe(true)
    expect(screen.getByRole('region', { name: '任务来源' })).toBe(source)
  })
  it('keeps the original URL visible when a file entry restores an unknown submission', async () => {
    queryMock.value = 'mode=file'
    const receipt = { operationId: 'original-url', workspace: { scope: 'personal' }, meeting: false, submissionState: 'unknown', sourceUrl: 'https://python.org/about', mode: 'url' }
    localStorage.setItem('vinote:import-receipt:import-owner:note', JSON.stringify(receipt))
    apiMock.apiJson.mockRejectedValue(new (await import('../lib/api')).ApiError('missing', 404, null))
    renderGenerator('/notes?project=Review&archived=1#selected')
    await screen.findByText(/尚未查到原提交回执/)
    const source = screen.getByRole('region', { name: '任务来源' })
    expect(source).toHaveTextContent(receipt.sourceUrl); expect(source).toHaveTextContent('网页或视频链接')
    expect(screen.queryByText('等待选择文件')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('选择或拖入音视频、PDF、Word 和文字文件')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '更换来源，开始新任务' })).toBeDisabled()
    const history = new URL(screen.getByRole('link', { name: '查看处理历史与恢复' }).getAttribute('href')!, 'https://vinote.invalid')
    expect(history.searchParams.get('tab')).toBe('generation'); expect(history.searchParams.get('returnTo')).toBe('/notes?project=Review&archived=1#selected')
    expect(apiMock.apiJson.mock.calls.every(([path]) => path === '/api/source-requests/original-url')).toBe(true)
    expect(JSON.parse(localStorage.getItem('vinote:import-receipt:import-owner:note')!)).toEqual(receipt)
  })
  it.each(['{broken', 'null'])('keeps damaged or missing archived metadata blocked with a safe history link (%s)', async raw => {
    queryMock.value = 'operation=unreadable'
    localStorage.setItem('vinote:source-receipt:import-owner:unreadable', raw)
    renderGenerator('/files?type=other&q=doc&file=original#selected')
    await screen.findByText(/无法读取本机任务回执/)
    expect(screen.getByRole('region', { name: '任务来源' })).toHaveTextContent('任务记录无法读取')
    expect(screen.getByRole('button', { name: 'Regenerate' })).toBeDisabled()
    expect(screen.queryByLabelText('选择或拖入音视频、PDF、Word 和文字文件')).not.toBeInTheDocument()
    const history = new URL(screen.getByRole('link', { name: '查看处理历史与恢复' }).getAttribute('href')!, 'https://vinote.invalid')
    expect(history.searchParams.get('returnTo')).toBe('/files?type=other&q=doc&file=original#selected')
    expect(apiMock.apiJson).not.toHaveBeenCalled()
    expect(localStorage.getItem('vinote:source-receipt:import-owner:unreadable')).toBe(raw)
  })
  it('does not invent missing source identity or let a source route bypass reserved recovery', async () => {
    const receipt = { operationId: 'reserved-source', workspace: { scope: 'personal' }, meeting: false, submissionState: 'reserved' }
    localStorage.setItem('vinote:import-receipt:import-owner:note', JSON.stringify(receipt))
    apiMock.apiJson.mockResolvedValue({ task_id: 'reserved-task', operation_id: 'reserved-source', state: 'reserved' })
    renderGenerator('//untrusted.example')
    await waitFor(() => expect(within(screen.getByRole('alert')).getByText(/提交已登记，尚未确认排队/)).toBeInTheDocument())
    expect(screen.getByRole('region', { name: '任务来源' })).toHaveTextContent('来源信息不完整')
    expect(screen.getByRole('button', { name: '更换来源，开始新任务' })).toBeDisabled()
    expect(new URL(screen.getByRole('link', { name: '查看处理历史与恢复' }).getAttribute('href')!, 'https://vinote.invalid').searchParams.get('returnTo')).toBe('/notes')
    expect(apiMock.apiJson.mock.calls.every(([path]) => path === '/api/source-requests/reserved-source')).toBe(true)
  })
  it('production hides internal diagnostics while unknown submission only queries its original operation', async () => {
    vi.stubEnv('DEV', false)
    const operationId = 'bf1cf8b3-c2d0-44f5-a9a0-d408d1234567'
    localStorage.setItem('vinote:import-receipt:import-owner:note', JSON.stringify({ operationId, workspace: { scope: 'personal' }, meeting: false, submissionState: 'unknown', sourceUrl: 'https://python.org/about' }))
    apiMock.apiJson.mockRejectedValue(new (await import('../lib/api')).ApiError('not found', 404, null))
    renderGenerator()
    await screen.findByRole('button', { name: '核验原提交' })
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('暂未查到原任务'))
    expect(screen.getByRole('region', { name: '任务来源' })).toHaveTextContent('https://python.org/about')
    expect(screen.getByRole('region', { name: '任务来源' })).toHaveTextContent('保存位置')
    expect(document.body.textContent).not.toMatch(/回执|提交编号|去重|首次原件注册|开发诊断/)
    expect(document.body.textContent).not.toContain(operationId)
    await userEvent.click(screen.getByRole('button', { name: '核验原提交' }))
    expect(apiMock.apiJson.mock.calls.every(([path, init]) => path === `/api/source-requests/${operationId}` && !init)).toBe(true)
    expect(JSON.parse(localStorage.getItem('vinote:import-receipt:import-owner:note')!).operationId).toBe(operationId)
  })

  it('opens model confirmation after retry409 and submits the same source task with concrete models', async () => {
    const receipt = { id: 'legacy-task', operationId: 'legacy-op', submissionState: 'accepted', workspace: { scope: 'personal' }, meeting: false, sourceTitle: 'Original recording' }
    localStorage.setItem('vinote:import-receipt:import-owner:note', JSON.stringify(receipt))
    const selection = { mode: 'cloud', server_url: 'https://source.test', asr_model: 'selected-aliyun', llm_model: 'selected-llm' }
    let posts = 0
    apiMock.apiJson.mockImplementation(async (path, options) => {
      if (path.endsWith('/model-confirmation')) return { task_id: receipt.id, source: { title: receipt.sourceTitle, type: 'media' }, requires_confirmation: true, can_confirm: true, selection }
      if (path.endsWith('/retry')) {
        if (++posts === 1) throw new ApiError('Model confirmation required', 409)
        return { task_id: receipt.id, status: 'uploaded' }
      }
      return posts >= 2 ? { status: 'preparing', message: '' } : { status: 'failed', retryable: true, message: 'network' }
    })
    renderGenerator()
    await waitFor(() => expect(useNoteGenerationStore.getState().status).toBe('failed'), { timeout: 4000 })
    await userEvent.click(screen.getByRole('button', { name: '重试处理原任务' }))
    await screen.findByRole('dialog', { name: '确认原任务的恢复模型' })
    await userEvent.click(screen.getByRole('button', { name: '确认模型并恢复原任务' }))
    await waitFor(() => expect(useNoteGenerationStore.getState().status).toBe('processing'))
    expect(apiMock.apiJson.mock.calls.filter(([, options]) => options?.body)).toEqual([
      ['/api/task/legacy-task/retry', { method: 'POST', body: JSON.stringify({ confirmed: true, ...selection }) }],
    ])
    expect(apiMock.apiJson.mock.calls.some(([path]) => path.startsWith('/api/generate'))).toBe(false)
    expect(JSON.parse(localStorage.getItem('vinote:import-receipt:import-owner:note')!).id).toBe(receipt.id)
  })

it('structured unknown result never posts retry even if legacy retryable is true', async () => {
  useAuthStore.setState({ user: { id: 'import-owner' } as never });
  localStorage.setItem('vinote:import-receipt:import-owner:note', JSON.stringify({ id: 'unknown-task', workspace: { scope: 'personal' }, meeting: false, submissionState: 'accepted' }));
  apiMock.apiJson.mockResolvedValue({ status: 'failed', error_code: 'unknown_result', retryable: true, message: '处理结果尚未确认' });
  render(<MemoryRouter><I18nProvider><NoteGenerator /></I18nProvider></MemoryRouter>);
  await waitFor(() => expect(useNoteGenerationStore.getState().status).toBe('failed'), { timeout: 4000 });
  await userEvent.click(screen.getByRole('button', { name: '重新查询原任务状态' }));
  expect(apiMock.apiJson.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
});

  it('known failed unknown task shows terminal copy and materials/history links without POST or receipt changes', async () => {
    queryMock.value = 'meeting=1';
    const id = '61b4e05a-e9d6-4d58-b151-f043210c908c';
    const receipt = { id, operationId: 'frozen-old-operation', submissionState: 'accepted', workspace: { scope: 'personal' }, meeting: true, localFileId: 'task:' + id };
    localStorage.setItem('vinote:import-receipt:import-owner:meeting', JSON.stringify(receipt));
    localStorage.setItem('vinote:source-receipt:import-owner:frozen-old-operation', JSON.stringify(receipt));
    apiMock.apiJson.mockResolvedValue({ task_id: id, status: 'failed', error_code: 'unknown_result', retryable: false, message: '转写结果尚未确认' });
    renderGenerator('/files?purpose=meeting');
    const action = await screen.findByRole('button', { name: '查看原任务状态' });
    expect(screen.getByText(/未获得可保存的完整结果/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '查询原结果并恢复保存' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '更换来源，开始新任务' })).toBeDisabled();
    expect(screen.getByRole('link', { name: '返回资料与原文件' })).toHaveAttribute('href', expect.stringContaining('/files?purpose=meeting&file=task%3A'));
    expect(screen.getByRole('link', { name: '查看处理历史与恢复' })).toBeInTheDocument();
    await userEvent.click(action);
    expect(apiMock.apiJson.mock.calls.every(([path, options]) => path === '/api/task/' + id && !options?.method)).toBe(true);
    expect(JSON.parse(localStorage.getItem('vinote:source-receipt:import-owner:frozen-old-operation')!)).toEqual(receipt);
    expect(JSON.parse(localStorage.getItem('vinote:import-receipt:import-owner:meeting')!)).toEqual(receipt);
  });

  it('upload acceptance unknown only checks its operation and never claims failed-ASR recovery', async () => {
    const receipt = { operationId: 'unconfirmed-upload', submissionState: 'unknown', workspace: { scope: 'personal' }, meeting: false };
    localStorage.setItem('vinote:import-receipt:import-owner:note', JSON.stringify(receipt));
    apiMock.apiJson.mockRejectedValue(new ApiError('not found', 404));
    renderGenerator();
    const action = await screen.findByRole('button', { name: '核验原提交' });
    expect(screen.getByText(/提交是否被接收尚未确认/)).toBeInTheDocument();
    expect(screen.queryByText(/未获得可保存的完整结果/)).not.toBeInTheDocument();
    await userEvent.click(action);
    expect(apiMock.apiJson.mock.calls.every(([path, options]) => path === '/api/source-requests/unconfirmed-upload' && !options?.method)).toBe(true);
    expect(JSON.parse(localStorage.getItem('vinote:import-receipt:import-owner:note')!)).toEqual(receipt);
  });

})


describe('summary-only operation recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks(); apiMock.apiJson.mockReset(); localStorage.clear(); sessionStorage.clear()
    useNoteGenerationStore.getState().reset()
    useAuthStore.setState({ user: { id: 'import-owner', email: 'import@example.invalid' } })
    libraryMock.notes = []; libraryMock.saveNote.mockReset()
  })
  afterEach(() => { cleanup(); localStorage.clear(); useAppModeStore.getState().reset() })
  const config = { configured: true, mode: 'cloud' as const, llm_model: 'exact-choice', asr_model: 'unused', server_url: 'https://summary.invalid' }
  function receipt(origin = config.server_url) {
    queryMock.value = 'meeting=1&operation=summary-op'
    localStorage.setItem('vinote:source-receipt:import-owner:summary-op', JSON.stringify({ operationId: 'summary-op', summaryOnly: true, independentGeneration: true, origin, meeting: true, workspace: { scope: 'personal' }, submissionState: 'unknown' }))
    useAppModeStore.setState({ config })
  }
  it('queries the exact source receipt and child task without resubmission', async () => {
    receipt()
    apiMock.apiJson.mockImplementation((path: string) => Promise.resolve(path === '/api/source-requests/summary-op' ? { operation_id: 'summary-op', task_id: 'summary-child', state: 'accepted' } : { task_id: 'summary-child', status: 'failed', message: 'summary pending review', retryable: false }))
    renderGenerator()
    await screen.findByText('summary pending review')
    expect(apiMock.apiJson).toHaveBeenCalledWith('/api/source-requests/summary-op')
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  })
  it('refuses recovery on a different model service Origin', async () => {
    receipt('https://original.invalid')
    renderGenerator()
    await screen.findByText(/无法读取本机任务回执/)
    expect(apiMock.apiJson).not.toHaveBeenCalled()
  })
  it('keeps summary child recovery query-only even if a status claims retryable', async () => {
    receipt()
    apiMock.apiJson.mockImplementation((path: string) => Promise.resolve(path.includes('source-requests') ? { operation_id: 'summary-op', task_id: 'summary-child', state: 'accepted' } : { task_id: 'summary-child', status: 'failed', message: 'summary stopped', retryable: true }))
    renderGenerator(); await screen.findByText('summary stopped')
    await userEvent.click(screen.getByRole('button', { name: '查看原任务状态' }))
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  })
  it('saves the original 15:41 source clock with the LLM topic rather than the 19:35 operation time', async () => {
    receipt()
    const key = 'vinote:source-receipt:import-owner:summary-op'
    localStorage.setItem(key, JSON.stringify({ ...JSON.parse(localStorage.getItem(key)!), createdAt: '2026-10-19T19:35:00+08:00' }))
    libraryMock.saveNote.mockResolvedValue({ id: 'saved-title' })
    apiMock.apiJson.mockImplementation((path: string) => Promise.resolve(path.includes('source-requests') ? { operation_id: 'summary-op', task_id: 'summary-child', state: 'accepted' } : { task_id: 'summary-child', status: 'success', result: { task_id: 'summary-child', title: '2026-10-19 15:41 | Synthetic source topic', markdown: '# Synthetic LLM topic' } }))
    renderGenerator()
    await waitFor(() => expect(libraryMock.saveNote).toHaveBeenCalled())
    expect(libraryMock.saveNote.mock.calls[0][0]).toBe('2026-10-19 15:41｜Synthetic LLM topic')
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  })
  it('does not substitute summary-operation creation time when a source timestamp is absent', async () => {
    receipt()
    const key = 'vinote:source-receipt:import-owner:summary-op'
    localStorage.setItem(key, JSON.stringify({ ...JSON.parse(localStorage.getItem(key)!), createdAt: '2026-10-19T19:35:00+08:00' }))
    libraryMock.saveNote.mockResolvedValue({ id: 'saved-title' })
    apiMock.apiJson.mockImplementation((path: string) => Promise.resolve(path.includes('source-requests') ? { operation_id: 'summary-op', task_id: 'summary-child', state: 'accepted' } : { task_id: 'summary-child', status: 'success', result: { task_id: 'summary-child', title: 'Synthetic source topic', markdown: '# Synthetic LLM topic' } }))
    renderGenerator()
    await waitFor(() => expect(libraryMock.saveNote).toHaveBeenCalled())
    expect(libraryMock.saveNote.mock.calls[0][0]).toBe('Time unknown｜Synthetic LLM topic')
  })
  it('clears the original-detail pending pointer only after saving the new summary is acknowledged', async () => {
    receipt()
    const key = 'vinote:source-receipt:import-owner:summary-op'
    localStorage.setItem(key, JSON.stringify({ ...JSON.parse(localStorage.getItem(key)!), summaryNoteId: 'note', parentTaskId: 'parent' }))
    const pointer = `vinote:summary-operation:import-owner:${config.server_url}:note:parent`
    localStorage.setItem(pointer, 'summary-op')
    libraryMock.saveNote.mockResolvedValue({ id: 'saved-child' })
    apiMock.apiJson.mockImplementation((path: string) => Promise.resolve(path.includes('source-requests') ? { operation_id: 'summary-op', task_id: 'summary-child', state: 'accepted' } : { task_id: 'summary-child', status: 'success', result: { task_id: 'summary-child', title: 'Synthetic summary', markdown: 'Synthetic body' } }))
    renderGenerator()
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/note/saved-child', expect.anything()))
    expect(localStorage.getItem(pointer)).toBeNull()
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  })

})


describe('meeting shared-video verification stage', () => {
  beforeEach(() => {
    vi.clearAllMocks(); apiMock.apiJson.mockReset(); localStorage.clear(); sessionStorage.clear()
    useNoteGenerationStore.getState().reset(); useAuthStore.setState({ user: { id: 'import-owner', email: 'import@example.invalid' } })
    queryMock.value = 'meeting=1&task=video-task'
    apiMock.apiJson.mockResolvedValue({ task_id: 'video-task', status: 'transcribing', stage: 'analyzing_video', processed_seconds: 900, total_seconds: 900, speaker_analysis_ready: true })
  })
  afterEach(() => { cleanup(); localStorage.clear(); queryMock.value = '' })
  it('honors analyzing_video substage ahead of a retained transcribing status and only reads the task', async () => {
    renderGenerator()
    await screen.findByRole('heading', { name: '核对共享画面与发言' })
    expect(useNoteGenerationStore.getState().currentStep).toBe('analyzing_video')
    expect(useNoteGenerationStore.getState().status).toBe('processing')
    expect(screen.getByRole('listitem', { name: '保存会议纪要：待开始' })).toBeVisible()
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow')
    expect(apiMock.apiJson.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  })
})
