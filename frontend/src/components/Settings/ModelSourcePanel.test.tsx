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

it('cloud mode offers VINote login and permits local mode during an outage', async () => {
  vi.mocked(apiJson).mockImplementation(async (path, init) => {
    if (path.endsWith('/models')) throw new Error('云端服务鉴权失败')
    return { configured: true, mode: init?.method === 'PUT' ? 'local' : 'cloud', asr_model: '', llm_model: '' }
  })
  render(<ModelSourcePanel />)
  expect(screen.queryByLabelText('云端账号邮箱')).not.toBeInTheDocument()
  expect(screen.queryByText('发送验证码')).not.toBeInTheDocument()
  expect(screen.queryByText('ViTalk')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('radio', { name: '本地 / 自定义' }))
  expect(await screen.findByText('自定义 LLM 表单')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('tab', { name: '语音转写' }))
  expect(await screen.findByText('自定义 STT 表单')).toBeInTheDocument()
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
    { id: 'disabled-asr', modelType: 'asr', runtimeStatus: 'disabled' },
  ])
  useAppModeStore.setState({ config: { configured: true, mode: 'cloud', asr_model: '', llm_model: 'removed-model' } })
  render(<ModelSourcePanel compact />)
  await screen.findByText(/原选择已不可用/)
  await userEvent.click(screen.getAllByRole('combobox')[1])
  expect(await screen.findByRole('option', { name: 'deployed' })).toBeInTheDocument()
  expect(screen.getByRole('option', { name: /configured-no-key/ })).toHaveAttribute('aria-disabled', 'true')
  expect(screen.queryByText('removed-model')).not.toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  await userEvent.click(screen.getAllByRole('combobox')[0])
  expect(screen.getByRole('option', { name: /disabled-asr/ })).toHaveAttribute('aria-disabled', 'true')
})

it('refresh replaces the catalog and a failed refresh does not retain old models', async () => {
  vi.mocked(apiJson).mockResolvedValueOnce([{ id: 'old-model', modelType: 'llm', runtimeStatus: 'available' }])
  useAppModeStore.setState({ config: { configured: true, mode: 'cloud', asr_model: '', llm_model: 'old-model' } })
  render(<ModelSourcePanel compact />)
  await screen.findByText('old-model')
  vi.mocked(apiJson).mockResolvedValueOnce([{ id: 'new-model', modelType: 'llm', runtimeStatus: 'available' }])
  await userEvent.click(screen.getByRole('button', { name: '刷新' }))
  await screen.findByText(/原选择已不可用/)
  expect(screen.queryByText('old-model')).not.toBeInTheDocument()
  await userEvent.click(screen.getAllByRole('combobox')[1])
  expect(await screen.findByRole('option', { name: 'new-model' })).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('catalog offline'))
  await userEvent.click(screen.getByRole('button', { name: '刷新' }))
  await screen.findByText('catalog offline')
  expect(screen.queryByText(/old-model|new-model/)).not.toBeInTheDocument()
  expect(screen.getAllByRole('combobox')[1]).toBeDisabled()
})
