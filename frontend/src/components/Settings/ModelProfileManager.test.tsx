import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../lib/i18n'
import { ModelProfileManager } from './ModelProfileManager'
import { STTProfileManager } from './STTProfileManager'
import type { ConnectionTestResult, ModelProfile } from '../../lib/modelProfiles'
import type { STTProfile } from '../../lib/sttProfiles'

const modelStoreMock = vi.hoisted(() => ({
  state: {} as {
    profiles: ModelProfile[]
    loading: boolean
    saving: boolean
    error: string
    lastTestResult: ConnectionTestResult | null
    profileTestResults?: Record<string, ConnectionTestResult>
    testingProfileIds?: string[]
    loadProfiles: ReturnType<typeof vi.fn>
    createProfile: ReturnType<typeof vi.fn>
    updateProfile: ReturnType<typeof vi.fn>
    deleteProfile: ReturnType<typeof vi.fn>
    setDefaultProfile: ReturnType<typeof vi.fn>
    testDraft: ReturnType<typeof vi.fn>
    testProfile: ReturnType<typeof vi.fn>
  },
}))

const sttStoreMock = vi.hoisted(() => ({
  state: {} as {
    profiles: STTProfile[]
    loading: boolean
    saving: boolean
    error: string
    localSupport: { provider: string; installed: boolean; installCommand: string; message: string } | null
    localSupportLoading: boolean
    loadProfiles: ReturnType<typeof vi.fn>
    loadLocalSupport: ReturnType<typeof vi.fn>
    createProfile: ReturnType<typeof vi.fn>
    updateProfile: ReturnType<typeof vi.fn>
    deleteProfile: ReturnType<typeof vi.fn>
    setDefaultProfile: ReturnType<typeof vi.fn>
  },
}))

vi.mock('../../stores/modelProfileStore', () => ({
  useModelProfileStore: () => modelStoreMock.state,
}))

vi.mock('../../stores/sttProfileStore', () => ({
  useSTTProfileStore: () => sttStoreMock.state,
}))

vi.mock('../../stores/authStore', () => ({
  useAuthStore: () => ({ initialized: true, user: { id: 'user-1' } }),
}))

vi.mock('../../stores/languageStore', () => ({
  useLanguageStore: () => ({
    language: 'zh-CN',
    setLanguage: vi.fn(),
    syncWithAccount: vi.fn(),
  }),
}))

const defaultModelProfiles: ModelProfile[] = [
  {
    id: 'silicon-flow',
    name: 'Silicon Flow',
    provider: 'openai-compatible',
    baseUrl: 'https://api.siliconflow.cn/v1',
    modelName: 'Qwen/Qwen3.6-35B-A3B',
    apiKeyHint: 'sk-...flow',
    isDefault: false,
    isActive: true,
  },
  {
    id: 'openai-main',
    name: 'OpenAI Main',
    provider: 'openai-compatible',
    baseUrl: 'https://api.openai.com/v1',
    modelName: 'gpt-4o-mini',
    apiKeyHint: 'sk-...openai',
    isDefault: true,
    isActive: true,
  },
]

const defaultSTTProfiles: STTProfile[] = [
  {
    id: 'stt-default',
    name: 'New STT',
    provider: 'groq',
    modelName: 'whisper-large-v3-turbo',
    baseUrl: 'https://api.groq.com/openai/v1',
    apiKeyHint: 'gsk-...123',
    language: '',
    device: null,
    computeType: null,
    useGpu: null,
    isDefault: true,
    isActive: true,
  },
]

function renderWithI18n(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  modelStoreMock.state = {
    profiles: defaultModelProfiles,
    loading: false,
    saving: false,
    error: '',
    lastTestResult: null,
    profileTestResults: {},
    testingProfileIds: [],
    loadProfiles: vi.fn(),
    createProfile: vi.fn(),
    updateProfile: vi.fn(),
    deleteProfile: vi.fn(),
    setDefaultProfile: vi.fn().mockResolvedValue(defaultModelProfiles[1]),
    testDraft: vi.fn(),
    testProfile: vi.fn().mockResolvedValue({
      ok: true,
      provider: 'openai-compatible',
      model: 'Qwen/Qwen3.6-35B-A3B',
      latencyMs: 321,
      errorMessage: '',
    }),
  }
  sttStoreMock.state = {
    profiles: defaultSTTProfiles,
    loading: false,
    saving: false,
    error: '',
    localSupport: {
      provider: 'faster-whisper',
      installed: false,
      installCommand: 'pip install -r requirements.local-transcribers.txt',
      message: '本地 STT 支持尚未安装。',
    },
    localSupportLoading: false,
    loadProfiles: vi.fn(),
    loadLocalSupport: vi.fn(),
    createProfile: vi.fn(),
    updateProfile: vi.fn(),
    deleteProfile: vi.fn(),
    setDefaultProfile: vi.fn().mockResolvedValue(defaultSTTProfiles[0]),
  }
})

describe('ModelProfileManager', () => {
  it('opens the tested saved profile in the edit panel before showing connection feedback', async () => {
    renderWithI18n(<ModelProfileManager />)

    const card = screen.getByText('Silicon Flow').closest('div.border-b') as HTMLElement
    await userEvent.click(within(card).getByRole('button', { name: '测试连接' }))

    expect(modelStoreMock.state.testProfile).toHaveBeenCalledWith('silicon-flow')
    expect(screen.getByRole('heading', { name: '编辑配置' })).toBeInTheDocument()
    expect(screen.getByDisplayValue('https://api.siliconflow.cn/v1')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Qwen/Qwen3.6-35B-A3B')).toBeInTheDocument()
  })

  it('renders per-card connection status instead of only a global form result', () => {
    modelStoreMock.state.profileTestResults = {
      'silicon-flow': {
        ok: true,
        provider: 'openai-compatible',
        model: 'Qwen/Qwen3.6-35B-A3B',
        latencyMs: 4013,
        errorMessage: '',
      },
      'openai-main': {
        ok: false,
        provider: 'openai-compatible',
        model: 'gpt-4o-mini',
        latencyMs: 0,
        errorMessage: 'invalid_api_key',
      },
    }
    renderWithI18n(<ModelProfileManager />)

    const siliconCard = screen.getByText('Silicon Flow').closest('div.border-b') as HTMLElement
    const openaiCard = screen.getByText('OpenAI Main').closest('div.border-b') as HTMLElement

    expect(within(siliconCard).getByText('连接成功，耗时 4013 ms')).toBeInTheDocument()
    expect(within(openaiCard).getByText('连接失败：invalid_api_key')).toBeInTheDocument()
  })

  it('keeps the default model checkbox checked and locked while editing the current default profile', async () => {
    renderWithI18n(<ModelProfileManager />)

    const card = screen.getByText('OpenAI Main').closest('div.border-b') as HTMLElement
    await userEvent.click(within(card).getByRole('button', { name: '编辑' }))

    const defaultCheckbox = screen.getByRole('checkbox', {
      name: '作为我的默认配置',
    })
    expect(defaultCheckbox).toBeChecked()
    expect(defaultCheckbox).toBeDisabled()
  })

  it('syncs the edit form when the profile being edited becomes the default', async () => {
    renderWithI18n(<ModelProfileManager />)

    const card = screen.getByText('Silicon Flow').closest('div.border-b') as HTMLElement
    await userEvent.click(within(card).getByRole('button', { name: '编辑' }))
    await userEvent.click(within(card).getByRole('button', { name: '设为默认' }))

    expect(modelStoreMock.state.setDefaultProfile).toHaveBeenCalledWith('silicon-flow')
    expect(screen.getByRole('checkbox', { name: '作为我的默认配置' })).toBeChecked()
  })
})

describe('STTProfileManager', () => {
  it('keeps the default STT checkbox checked and locked while editing the current default profile', async () => {
    renderWithI18n(<STTProfileManager />)

    const card = screen.getByText('New STT').closest('div.border-b') as HTMLElement
    await userEvent.click(within(card).getByRole('button', { name: '编辑' }))

    const defaultCheckbox = screen.getByRole('checkbox', {
      name: '作为我的默认 STT 配置',
    })
    expect(defaultCheckbox).toBeChecked()
    expect(defaultCheckbox).toBeDisabled()
  })

  it('syncs the edit form when the STT profile being edited becomes the default', async () => {
    const secondaryProfile: STTProfile = {
      ...defaultSTTProfiles[0],
      id: 'stt-secondary',
      name: 'Secondary STT',
      isDefault: false,
    }
    sttStoreMock.state.profiles = [...defaultSTTProfiles, secondaryProfile]
    sttStoreMock.state.setDefaultProfile.mockResolvedValue(secondaryProfile)
    renderWithI18n(<STTProfileManager />)

    const card = screen.getByText('Secondary STT').closest('div.border-b') as HTMLElement
    await userEvent.click(within(card).getByRole('button', { name: '编辑' }))
    await userEvent.click(within(card).getByRole('button', { name: '设为默认' }))

    expect(sttStoreMock.state.setDefaultProfile).toHaveBeenCalledWith('stt-secondary')
    expect(screen.getByRole('checkbox', { name: '作为我的默认 STT 配置' })).toBeChecked()
  })

  it('shows a manual local STT install command without a server mutation action', async () => {
    renderWithI18n(<STTProfileManager />)

    await userEvent.selectOptions(screen.getAllByRole('combobox')[0], 'faster-whisper')

    expect(screen.getByText('本地 STT 支持尚未安装。')).toBeInTheDocument()
    expect(screen.getByText('pip install -r requirements.local-transcribers.txt')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '安装本地 STT 支持' })).not.toBeInTheDocument()
  })
})
