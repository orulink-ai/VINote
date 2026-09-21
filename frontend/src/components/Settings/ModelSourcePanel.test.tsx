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
  expect(apiJson).toHaveBeenCalledWith('/api/vilab/models')
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
