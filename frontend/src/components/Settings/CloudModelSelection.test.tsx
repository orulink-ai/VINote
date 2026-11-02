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

const speechService = {
  id: 'speech', name: '会议语音服务', modelType: 'asr', runtimeStatus: 'available',
  capabilities: { recordedAudio: {
    protocol: 1, supported: true, strategy: 'single_request', policySource: 'provider_model',
  }, useCases: ['meeting'], protocols: ['asr-recording'], audioFormats: ['wav'],
  audioDelivery: 'public', maxAudioSeconds: 10800, maxAudioBytes: 536870912,
  speakerDiarization: true, utteranceTimestamps: true },
}

beforeEach(() => {
  vi.clearAllMocks()
  HTMLElement.prototype.scrollIntoView = vi.fn()
  HTMLElement.prototype.hasPointerCapture = vi.fn(() => false)
  HTMLElement.prototype.setPointerCapture = vi.fn()
  HTMLElement.prototype.releasePointerCapture = vi.fn()
  mocks.api.mockResolvedValue([
    speechService,
    { ...speechService, id: 'speech-second', name: '另一会议模型' },
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
  expect(screen.getByRole('option', { name: /offline/ })).toHaveAttribute('aria-disabled', 'true')
  await userEvent.click(screen.getByRole('option', { name: 'second', exact: true }))
  expect(mocks.save).toHaveBeenCalledWith('speech', 'second')
  await userEvent.click(screen.getByRole('combobox', { name: '语音转写' }))
  expect(screen.queryByRole('option', { name: '跟随服务默认' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('option', { name: /另一会议模型/ }))
  expect(mocks.save).toHaveBeenCalledWith('speech-second', 'first')
})

it('shows catalog failures and allows a refresh', async () => {
  mocks.api.mockRejectedValueOnce(new Error('模型服务连接失败'))
  render(<ModelSourcePanel compact />)
  expect(await screen.findByRole('alert')).toHaveTextContent('模型服务连接失败')
  expect(screen.getByRole('combobox', { name: '内容总结 / 画面分析' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: '刷新' }))
  await waitFor(() => expect(screen.getByRole('combobox', { name: '内容总结 / 画面分析' })).not.toBeDisabled())
})

it('offers only whole-file public meeting ASR with speakers and timestamps', async () => {
  const capabilities = speechService.capabilities
  mocks.api.mockResolvedValue([
    speechService,
    ...[
      { speakerDiarization: false },
      { utteranceTimestamps: false },
      { audioDelivery: 'inline' },
      { useCases: ['recording'] },
      { recordedAudio: { ...capabilities.recordedAudio, strategy: 'adaptive_pause' } },
      { maxAudioSeconds: 0 },
    ].map((override, index) => ({
      ...speechService, id: `ineligible-${index}`, name: `不合格模型 ${index}`,
      capabilities: { ...capabilities, ...override },
    })),
  ])
  render(<ModelSourcePanel compact />)
  const speech = screen.getByRole('combobox', { name: '语音转写' })
  await waitFor(() => expect(speech).not.toBeDisabled())
  await userEvent.click(speech)
  expect(screen.getAllByRole('option')).toHaveLength(1)
  expect(screen.getByRole('option')).toHaveTextContent('会议语音服务')
  expect(screen.queryByText('跟随服务默认')).not.toBeInTheDocument()
  expect(mocks.save).not.toHaveBeenCalled()
})

it('never clears an unavailable speech selection when changing summary', async () => {
  mocks.api.mockResolvedValue([
    { ...speechService, runtimeStatus: 'not_available', availability: { status: 'auth_failed', retryAt: 1 } },
    { id: 'first', modelType: 'llm', runtimeStatus: 'available' },
    { id: 'second', modelType: 'llm', runtimeStatus: 'available' },
  ])
  render(<ModelSourcePanel compact />)
  const summary = screen.getByRole('combobox', { name: '内容总结 / 画面分析' })
  await waitFor(() => expect(summary).not.toBeDisabled())
  expect(screen.getByRole('combobox', { name: '语音转写' })).toHaveTextContent('会议语音服务')
  expect(screen.getByRole('combobox', { name: '语音转写' })).not.toHaveTextContent('speech')
  expect(mocks.save).not.toHaveBeenCalled()
  await userEvent.click(summary)
  await userEvent.click(screen.getByRole('option', { name: 'second', exact: true }))
  expect(mocks.save).toHaveBeenCalledWith('speech', 'second')
})
it('retains an expired transient model and shows retry eligibility without saving automatically', async () => {
  mocks.api.mockResolvedValue([
    { ...speechService, runtimeStatus: 'not_available', availability: { status: 'service_error', retryAt: Date.now() - 1 } },
    { id: 'first', modelType: 'llm', runtimeStatus: 'available' },
  ])
  render(<ModelSourcePanel compact />)
  expect(await screen.findByText(/原模型可重试/)).toBeInTheDocument()
  expect(mocks.save).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('combobox', { name: '语音转写' }))
  expect(screen.getByRole('option', { name: /会议语音服务.*可重试/ })).not.toHaveAttribute('aria-disabled', 'true')
  expect(mocks.save).not.toHaveBeenCalled()
})

it('blocks speech selection without meeting capabilities while preserving its ID when changing summary', async () => {
  mocks.api.mockResolvedValue([
    { id: 'speech', name: '会议语音服务', modelType: 'asr', runtimeStatus: 'available' },
    { id: 'first', modelType: 'llm', runtimeStatus: 'available' },
    { id: 'second', modelType: 'llm', runtimeStatus: 'available' },
  ])
  render(<ModelSourcePanel compact />)
  await screen.findByText(/公网服务暂未提供支持整段识别、说话人分离和时间戳的会议模型/)
  expect(mocks.save).not.toHaveBeenCalled()
  expect(screen.getByRole('combobox', { name: '语音转写' })).toBeDisabled()
  await userEvent.click(screen.getByRole('combobox', { name: '内容总结 / 画面分析' }))
  await userEvent.click(screen.getByRole('option', { name: 'second', exact: true }))
  expect(mocks.save).toHaveBeenCalledWith('speech', 'second')
})
