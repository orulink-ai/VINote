import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { ModelSourcePanel } from './ModelSourcePanel'
import { SavedApiKey } from './SavedApiKey'
import { apiJson } from '../../lib/api'
import { useAppModeStore } from '../../stores/appModeStore'

vi.mock('../../lib/api', () => ({ apiJson: vi.fn() }))
vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ locale: 'zh-CN', copy: { locale: 'zh-CN' } }) }))
vi.mock('./ModelProfileManager', () => ({ ModelProfileManager: () => <div>自定义 LLM 表单</div> }))
vi.mock('./STTProfileManager', () => ({ STTProfileManager: () => <div>自定义 STT 表单</div> }))
vi.mock('../../stores/modelProfileStore', () => ({ useModelProfileStore: { getState: () => ({ selectProfile: vi.fn(), loadProfiles: vi.fn() }) } }))
vi.mock('../../stores/sttProfileStore', () => ({ useSTTProfileStore: { getState: () => ({ selectProfile: vi.fn(), loadProfiles: vi.fn() }) } }))

beforeEach(() => {
  HTMLElement.prototype.scrollIntoView = vi.fn()
  HTMLElement.prototype.hasPointerCapture = vi.fn(() => false)
  HTMLElement.prototype.setPointerCapture = vi.fn()
  HTMLElement.prototype.releasePointerCapture = vi.fn()
  vi.mocked(apiJson).mockReset()
  useAppModeStore.getState().reset()
  useAppModeStore.setState({ config: { configured: true, mode: 'cloud', asr_model: '', llm_model: '' } })
})

it('cloud mode exposes model choices without asking for credentials', async () => {
  vi.mocked(apiJson).mockResolvedValue([{ id: 'minimax-m2.7', modelType: 'llm', runtimeStatus: 'available' }])
  useAppModeStore.setState({ config: { configured: true, mode: 'cloud', asr_model: '', llm_model: 'minimax-m2.7' } })
  render(<ModelSourcePanel compact />)
  expect(screen.getAllByRole('combobox')).toHaveLength(2)
  expect(await screen.findByText('minimax-m2.7')).toBeInTheDocument()
  expect(screen.queryByLabelText(/密钥/)).not.toBeInTheDocument()
  expect(apiJson).toHaveBeenCalledWith('/api/vilab/models', { cache: 'no-store' })
})

it('keeps fixed service only during an outage without writing configuration', async () => {
  vi.mocked(apiJson).mockImplementation(async (path, init) => {
    if (path.endsWith('/models')) throw new Error('云端服务鉴权失败')
    return { configured: true, mode: init?.method === 'PUT' ? 'local' : 'cloud', asr_model: '', llm_model: '' }
  })
  render(<ModelSourcePanel />)
  expect(screen.queryByLabelText('云端账号邮箱')).not.toBeInTheDocument()
  expect(screen.queryByText('发送验证码')).not.toBeInTheDocument()
  expect(screen.queryByText('ViTalk')).not.toBeInTheDocument()
  expect(await screen.findByText('云端服务鉴权失败')).toBeInTheDocument()
  expect(screen.queryByRole('radio')).not.toBeInTheDocument()
  expect(screen.queryByRole('tab')).not.toBeInTheDocument()
  expect(screen.queryByText(/自定义.*表单/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '刷新' })).toBeEnabled()
  expect(vi.mocked(apiJson).mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it.each([false, true])('blocks legacy local configuration without exposing profiles (compact=%s)', compact => {
  useAppModeStore.setState({ config: { configured: true, mode: 'local', asr_model: 'saved', llm_model: '' } })
  render(<ModelSourcePanel compact={compact} />)
  expect(screen.getByRole('alert')).toHaveTextContent('VINote 仅使用固定公网服务')
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  expect(screen.queryByRole('radio')).not.toBeInTheDocument()
  expect(screen.queryByRole('tab')).not.toBeInTheDocument()
  expect(apiJson).not.toHaveBeenCalled()
  expect(useAppModeStore.getState().config?.asr_model).toBe('saved')
})

it('shows the fixed public service address without any endpoint controls', async () => {
  vi.mocked(apiJson).mockResolvedValue([])
  useAppModeStore.setState({ config: {
    configured: true, mode: 'cloud', asr_model: '', llm_model: '', server_url: 'https://api-hk.orulink.ai',
  } })
  render(<ModelSourcePanel compact />)
  expect(await screen.findByText('https://api-hk.orulink.ai')).toBeInTheDocument()
  expect(screen.getByText('公网地址，不可编辑')).toBeInTheDocument()
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  expect(screen.queryByRole('switch')).not.toBeInTheDocument()
})

it('blocks saved adaptive speech and gives user-facing availability guidance', async () => {
  vi.mocked(apiJson).mockResolvedValue([{
    id: 'stream-model', name: '流式转写', modelType: 'asr', runtimeStatus: 'available',
    capabilities: {
      recordedAudio: { protocol: 1, supported: true, strategy: 'adaptive_pause', policySource: 'service_budget', maxSessionAudioBytes: 2097152 },
      useCases: ['recording'], protocols: ['asr-streaming'],
    },
  }])
  useAppModeStore.setState({ config: {
    configured: true, mode: 'cloud', asr_model: 'stream-model', llm_model: '', server_url: 'https://api-hk.orulink.ai',
  } })
  render(<ModelSourcePanel compact />)
  expect(await screen.findByText('公网服务暂未提供支持整段识别、说话人分离和时间戳的会议模型。请稍后刷新或联系管理员。原选择已保留，不会自动替换。')).toBeInTheDocument()
  expect(screen.queryByText(/AWS/)).not.toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: '语音转写' })).toBeDisabled()
  expect(screen.getByText(/原语音选择不满足会议转写要求/)).toBeInTheDocument()
  expect(useAppModeStore.getState().config?.asr_model).toBe('stream-model')
  expect(vi.mocked(apiJson).mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('describes a meeting model by its declared whole-file capability', async () => {
  vi.mocked(apiJson).mockResolvedValue([{
    id: 'meeting-model', name: '会议转写', modelType: 'asr', runtimeStatus: 'available',
    capabilities: {
      recordedAudio: { protocol: 1, supported: true, strategy: 'single_request', policySource: 'provider_model' },
      useCases: ['recording', 'meeting'], protocols: ['asr-recording'], audioFormats: ['wav'],
      audioDelivery: 'public', maxAudioSeconds: 10800, maxAudioBytes: 536870912,
      speakerDiarization: true, utteranceTimestamps: true,
    },
  }])
  useAppModeStore.setState({ config: {
    configured: true, mode: 'cloud', asr_model: 'meeting-model', llm_model: '', server_url: 'https://api-hk.orulink.ai',
  } })
  render(<ModelSourcePanel compact />)
  expect(await screen.findByText('会议录音 · 整段识别 · 带说话人分离 · 带时间戳')).toBeInTheDocument()
  expect(screen.getByText('会议录音整段提交，结果包含说话人与发言时间。')).toBeInTheDocument()
  expect(screen.queryByText(/暂不能用于会议纪要/)).not.toBeInTheDocument()
})

it('loads a saved key only on demand and clears it when hidden', async () => {
  vi.mocked(apiJson).mockResolvedValue({ api_key: 'test-secret-value' })
  render(<SavedApiKey kind="model" profileId="profile-1" hint="test****alue" />)
  expect(apiJson).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: '显示已保存密钥' }))
  expect(await screen.findByText('test-secret-value')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '隐藏密钥' }))
  expect(screen.queryByText('test-secret-value')).not.toBeInTheDocument()
})

it('a failed mode save retains the confirmed global mode', async () => {
  vi.mocked(apiJson).mockRejectedValue(new Error('offline'))
  await useAppModeStore.getState().setMode('local')
  expect(useAppModeStore.getState().config?.mode).toBe('cloud')
  expect(useAppModeStore.getState().error).toBe('offline')
})


it('shows all configured models including unavailable ones without resurrecting removed selections', async () => {
  vi.mocked(apiJson).mockResolvedValue([
    { id: 'deployed', modelType: 'llm', runtimeStatus: 'available' },
    { id: 'configured-no-key', modelType: 'llm', runtimeStatus: 'missing_api_key' },
    { id: 'disabled-asr', name: '已停用语音服务', modelType: 'asr', runtimeStatus: 'disabled' },
  ])
  useAppModeStore.setState({ config: { configured: true, mode: 'cloud', asr_model: '', llm_model: 'removed-model' } })
  render(<ModelSourcePanel compact />)
  await screen.findByText(/原选择已不可用/)
  await userEvent.click(screen.getAllByRole('combobox')[1])
  expect(await screen.findByRole('option', { name: 'deployed' })).toBeInTheDocument()
  expect(screen.getByRole('option', { name: /configured-no-key/ })).toHaveAttribute('aria-disabled', 'true')
  expect(screen.getByRole('option', { name: '原选择暂不可用' })).toHaveAttribute('aria-disabled', 'true')
  expect(screen.queryByText(/removed-model/)).not.toBeInTheDocument()
  expect(useAppModeStore.getState().config?.llm_model).toBe('removed-model')
  await userEvent.keyboard('{Escape}')
  expect(screen.getAllByRole('combobox')[0]).toBeDisabled()
  expect(screen.queryByRole('option', { name: /已停用语音服务/ })).not.toBeInTheDocument()
  expect(vi.mocked(apiJson).mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('refresh replaces the catalog and a failed refresh does not retain old models', async () => {
  vi.mocked(apiJson).mockResolvedValueOnce([{ id: 'old-model', modelType: 'llm', runtimeStatus: 'available' }])
  useAppModeStore.setState({ config: { configured: true, mode: 'cloud', asr_model: '', llm_model: 'old-model' } })
  render(<ModelSourcePanel compact />)
  await screen.findByText('old-model')
  vi.mocked(apiJson).mockResolvedValueOnce([{ id: 'new-model', modelType: 'llm', runtimeStatus: 'available' }])
  await userEvent.click(screen.getByRole('button', { name: '刷新' }))
  await screen.findByText(/原选择已不可用/)
  expect(screen.getAllByRole('combobox')[1]).toHaveTextContent('原选择暂不可用')
  expect(screen.queryByText('old-model')).not.toBeInTheDocument()
  expect(useAppModeStore.getState().config?.llm_model).toBe('old-model')
  await userEvent.click(screen.getAllByRole('combobox')[1])
  expect(await screen.findByRole('option', { name: 'new-model' })).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('catalog offline'))
  await userEvent.click(screen.getByRole('button', { name: '刷新' }))
  await screen.findByText('catalog offline')
  expect(screen.getAllByRole('combobox')[1]).toHaveTextContent('原选择暂不可用'); expect(screen.queryByText('new-model')).not.toBeInTheDocument()
  expect(screen.getAllByRole('combobox')[1]).toBeDisabled()
  expect(useAppModeStore.getState().config?.llm_model).toBe('old-model')
  expect(vi.mocked(apiJson).mock.calls.every(([, init]) => !init?.method)).toBe(true)
})
