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
  HTMLElement.prototype.scrollIntoView = vi.fn()
  HTMLElement.prototype.hasPointerCapture = vi.fn(() => false)
  HTMLElement.prototype.setPointerCapture = vi.fn()
  HTMLElement.prototype.releasePointerCapture = vi.fn()
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
  const summary = screen.getByRole('combobox', { name: '内容总结 / 画面分析' })
  await waitFor(() => expect(summary).not.toBeDisabled())
  await userEvent.click(summary)
  expect(screen.getByRole('option', { name: 'offline · 不可用' })).toHaveAttribute('aria-disabled', 'true')
  await userEvent.click(screen.getByRole('option', { name: 'second', exact: true }))
  expect(mocks.save).toHaveBeenCalledWith('speech', 'second')
  await userEvent.click(screen.getByRole('combobox', { name: '语音转写' }))
  await userEvent.click(screen.getByRole('option', { name: '跟随服务默认' }))
  expect(mocks.save).toHaveBeenCalledWith('', 'first')
})

it('shows catalog failures and allows a refresh', async () => {
  mocks.api.mockRejectedValueOnce(new Error('模型服务连接失败'))
  render(<ModelSourcePanel compact />)
  expect(await screen.findByRole('alert')).toHaveTextContent('模型服务连接失败')
  expect(screen.getByRole('combobox', { name: '内容总结 / 画面分析' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: '刷新' }))
  await waitFor(() => expect(screen.getByRole('combobox', { name: '内容总结 / 画面分析' })).not.toBeDisabled())
})
