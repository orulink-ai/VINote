import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { ModelSourcePanel } from './ModelSourcePanel'

const mocks = vi.hoisted(() => ({ api: vi.fn(), save: vi.fn(), config: { mode: 'cloud', asr_model: 'speech', llm_model: 'first' } }))
vi.mock('../../lib/api', () => ({ apiJson: mocks.api }))
vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ locale: 'zh-CN' }) }))
vi.mock('../../stores/appModeStore', () => ({ useAppModeStore: () => ({ config: mocks.config, saving: false, error: '', saveModels: mocks.save }) }))
vi.mock('./ModelProfileManager', () => ({ ModelProfileManager: () => null }))
vi.mock('./STTProfileManager', () => ({ STTProfileManager: () => null }))

beforeEach(() => {
  vi.clearAllMocks()
  mocks.api.mockResolvedValue([
    { id: 'speech', modelType: 'asr', runtimeStatus: 'available' },
    { id: 'first', modelType: 'llm', runtimeStatus: 'available' },
    { id: 'second', modelType: 'llm', runtimeStatus: 'available' },
    { id: 'offline', modelType: 'llm', runtimeStatus: 'unavailable' },
  ])
  mocks.save.mockResolvedValue(undefined)
})

it('saves an available summary model while preserving the speech selection', async () => {
  render(<ModelSourcePanel compact />)
  const summary = screen.getByLabelText('内容总结')
  await waitFor(() => expect(summary).not.toBeDisabled())
  expect(screen.getByRole('option', { name: 'offline · 不可用' })).toBeDisabled()
  await userEvent.selectOptions(summary, 'second')
  expect(mocks.save).toHaveBeenCalledWith('speech', 'second')
  await userEvent.selectOptions(screen.getByLabelText('语音转写'), '')
  expect(mocks.save).toHaveBeenCalledWith('', 'first')
})

it('shows catalog failures and allows a refresh', async () => {
  mocks.api.mockRejectedValueOnce(new Error('模型服务连接失败'))
  render(<ModelSourcePanel compact />)
  expect(await screen.findByRole('alert')).toHaveTextContent('模型服务连接失败')
  expect(screen.getByLabelText('内容总结')).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: '刷新模型' }))
  await waitFor(() => expect(screen.getByLabelText('内容总结')).not.toBeDisabled())
})
