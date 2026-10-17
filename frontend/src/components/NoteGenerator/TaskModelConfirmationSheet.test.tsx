import { cleanup, render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/authStore'
import { ApiError } from '@/lib/api'
import { TaskModelConfirmationSheet } from './TaskModelConfirmationSheet'

const api = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api', () => ({ apiJson: api, ApiError: class extends Error { constructor(message: string, public status: number) { super(message) } } }))
const selection = { mode: 'cloud', server_url: 'https://source.test', asr_model: 'selected-aliyun', llm_model: 'selected-llm' }
const context = { task_id: 'original-task', source: { title: 'Original recording', type: 'media' }, requires_confirmation: true, can_confirm: true, selection }
const accepted = vi.fn(), close = vi.fn(), query = vi.fn()
const open = () => render(<TaskModelConfirmationSheet taskId="original-task" owner="owner" onClose={close} onAccepted={accepted} onQuery={query} />)
beforeEach(() => { vi.clearAllMocks(); api.mockReset(); useAuthStore.setState({ user: { id: 'owner', email: 'owner@example.invalid' } }) })
afterEach(cleanup)

it('reads the source without submission, locks both models and confirms the same task once', async () => {
  api.mockResolvedValueOnce(context).mockResolvedValueOnce({ task_id: 'original-task', status: 'uploaded' })
  open()
  await screen.findByText('Original recording')
  expect(api).toHaveBeenCalledTimes(1)
  expect(screen.getAllByRole('combobox')).toHaveLength(2)
  for (const control of screen.getAllByRole('combobox')) expect(control).toBeDisabled()
  await userEvent.dblClick(screen.getByRole('button', { name: '确认模型并恢复原任务' }))
  expect(api.mock.calls.filter(call => call[1]?.method === 'POST')).toHaveLength(1)
  expect(api).toHaveBeenLastCalledWith('/api/task/original-task/retry', { method: 'POST', body: JSON.stringify({ confirmed: true, ...selection }) })
  expect(accepted).toHaveBeenCalledTimes(1)
})

it('keeps blocked selections visible and disables confirmation', async () => {
  api.mockResolvedValue({ ...context, can_confirm: false })
  open(); await screen.findByText('Original recording')
  expect(screen.getByRole('button', { name: '确认模型并恢复原任务' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: '返回原任务' }))
  expect(close).toHaveBeenCalledOnce(); expect(api).toHaveBeenCalledTimes(1)
})

it('does not replace the displayed model when a refresh reports changed preferences', async () => {
  api.mockResolvedValueOnce(context).mockResolvedValueOnce({ ...context, selection: { ...selection, asr_model: 'other' } })
  open(); await screen.findByText('Original recording')
  await userEvent.click(screen.getByRole('button', { name: '刷新模型状态' }))
  await screen.findByText(/模型设置已变化/)
  expect(screen.getByRole('button', { name: '确认模型并恢复原任务' })).toBeDisabled()
  expect(screen.getByRole('combobox', { name: '语音转写模型' })).toHaveTextContent('selected-aliyun')
})

it('retries a failed read and a known rejected confirmation without claiming acceptance', async () => {
  api.mockRejectedValueOnce(new Error('Read failed')).mockResolvedValueOnce(context).mockRejectedValueOnce(new ApiError('Unavailable', 400))
  open(); await screen.findByText('Read failed')
  await userEvent.click(screen.getByRole('button', { name: '重试读取' }))
  await screen.findByText('Original recording')
  await userEvent.click(screen.getByRole('button', { name: '确认模型并恢复原任务' }))
  await screen.findByText('Unavailable')
  expect(accepted).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: '确认模型并恢复原任务' })).toBeDisabled()
})

it('an unknown POST outcome offers a query and never another POST', async () => {
  api.mockResolvedValueOnce(context).mockRejectedValueOnce(new TypeError('Network failure'))
  open(); await screen.findByText('Original recording')
  await userEvent.click(screen.getByRole('button', { name: '确认模型并恢复原任务' }))
  await userEvent.click(await screen.findByRole('button', { name: '查询原任务状态' }))
  expect(query).toHaveBeenCalledOnce(); expect(accepted).not.toHaveBeenCalled()
  expect(api).toHaveBeenCalledTimes(2)
})

it.each(['read', 'post'])('ignores late %s results after the account changes', async stage => {
  let resolve!: (value: unknown) => void
  const pending = new Promise(r => { resolve = r })
  if (stage === 'read') api.mockReturnValueOnce(pending)
  else api.mockResolvedValueOnce(context).mockReturnValueOnce(pending)
  open()
  if (stage === 'post') {
    await screen.findByText('Original recording')
    await userEvent.click(screen.getByRole('button', { name: '确认模型并恢复原任务' }))
  }
  useAuthStore.setState({ user: { id: 'new-owner', email: 'new@example.invalid' } })
  await act(async () => { resolve(stage === 'read' ? context : { task_id: 'original-task', status: 'uploaded' }); await pending })
  expect(accepted).not.toHaveBeenCalled()
  if (stage === 'read') expect(screen.queryByText('Original recording')).not.toBeInTheDocument()
})

it.each([{ ...context, task_id: 'other' }, { ...context, requires_confirmation: false }])('fails closed for an invalid or already frozen context', async value => {
  api.mockResolvedValue(value); open()
  await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  expect(screen.getByRole('button', { name: '确认模型并恢复原任务' })).toBeDisabled()
  expect(api).toHaveBeenCalledTimes(1)
})
