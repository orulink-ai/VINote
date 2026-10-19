import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { RegenerateMeetingSummary } from './RegenerateMeetingSummary'
import { useAuthStore } from '@/stores/authStore'
import { useAppModeStore } from '@/stores/appModeStore'
import { apiJson, ApiError } from '@/lib/api'
vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(), apiJson: vi.fn() }))
const config = { configured: true, mode: 'cloud' as const, llm_model: 'selected-exact-model', asr_model: 'unchanged', server_url: 'https://model.invalid' }
const context = { parent_task_id: 'parent', context_revision: 'a'.repeat(64), source: { version: 'b'.repeat(64), type: 'video' }, can_regenerate_summary: true }
const mock = vi.mocked(apiJson)
function Route() { const l = useLocation(); return <output data-testid="route">{l.pathname}{l.search}|{l.state?.returnTo}</output> }
function show() { return render(<MemoryRouter><RegenerateMeetingSummary noteId="note" taskId="parent" workspace={{ scope: 'personal' }} returnTo="/notes/note?view=transcript" /><Route /></MemoryRouter>) }
async function open() { fireEvent.click(screen.getByRole('button', { name: '重新生成纪要' })); await screen.findByRole('dialog') }
beforeEach(() => {
  localStorage.clear(); vi.resetAllMocks()
  useAuthStore.setState({ user: { id: 'owner' } as never })
  useAppModeStore.setState({ config, saving: false })
  mock.mockImplementation(async path => path === '/api/vilab/config' ? config : context)
})
afterEach(cleanup)
it('confirms exact selected LLM and persists the owner operation before a single POST, then uses existing recovery route', async () => {
  mock.mockImplementation(async (path, init) => {
    if (path.endsWith('/regenerate-summary')) {
      const body = JSON.parse(init!.body as string)
      expect(body).toEqual({ operation_id: expect.any(String), confirmed: true, context_revision: context.context_revision, source_version: context.source.version, model_name: config.llm_model })
      expect(JSON.parse(localStorage.getItem(`vinote:source-receipt:owner:${body.operation_id}`)!)).toMatchObject({ summaryOnly: true, submissionState: 'unknown', modelName: config.llm_model })
      return { operation_id: body.operation_id, task_id: 'child', state: 'accepted' }
    }
    return path === '/api/vilab/config' ? config : context
  })
  show(); await open()
  expect(screen.getByRole('dialog')).toHaveTextContent('不重新转录')
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '确认并重新生成纪要' }))
  await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent('/generate?meeting=1&operation='))
  expect(screen.getByTestId('route')).toHaveTextContent('|/notes/note?view=transcript')
  expect(mock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
})
it('retains unknown submission and reopening only navigates to GET recovery without another POST', async () => {
  mock.mockImplementation(async (path) => { if (path.endsWith('/regenerate-summary')) throw new Error('lost response'); return path === '/api/vilab/config' ? config : context })
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
