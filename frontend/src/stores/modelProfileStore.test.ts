import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ModelProfile } from '../lib/modelProfiles'

const apiMocks = vi.hoisted(() => ({
  updateModelProfile: vi.fn(),
}))

vi.mock('../lib/modelProfiles', () => ({
  createModelProfile: vi.fn(),
  deleteModelProfile: vi.fn(),
  fetchModelProfiles: vi.fn(),
  setDefaultModelProfile: vi.fn(),
  testModelProfileDraft: vi.fn(),
  testSavedModelProfile: vi.fn(),
  updateModelProfile: apiMocks.updateModelProfile,
}))

import { useModelProfileStore } from './modelProfileStore'

const profile: ModelProfile = {
  id: 'profile-1',
  name: 'Profile 1',
  provider: 'openai-compatible',
  baseUrl: 'https://old.example.com/v1',
  modelName: 'old-model',
  apiKeyHint: 'sk-...old',
  isDefault: true,
  isActive: true,
}

describe('modelProfileStore', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useModelProfileStore.getState().reset()
    useModelProfileStore.setState({
      profiles: [profile],
      selectedProfileId: profile.id,
      profileTestResults: {
        [profile.id]: {
          ok: true,
          provider: profile.provider,
          model: profile.modelName,
          latencyMs: 120,
          errorMessage: '',
        },
      },
    })
  })

  it('clears the cached connection result after a saved profile changes', async () => {
    const updated = {
      ...profile,
      baseUrl: 'https://new.example.com/v1',
      modelName: 'new-model',
    }
    apiMocks.updateModelProfile.mockResolvedValue(updated)

    await useModelProfileStore.getState().updateProfile(profile.id, {
      baseUrl: updated.baseUrl,
      modelName: updated.modelName,
    })

    expect(useModelProfileStore.getState().profileTestResults).not.toHaveProperty(profile.id)
  })
})
