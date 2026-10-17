import { create } from 'zustand'
import {
  createModelProfile,
  deleteModelProfile,
  fetchModelProfiles,
  setDefaultModelProfile,
  testModelProfileDraft,
  testSavedModelProfile,
  updateModelProfile,
  type ConnectionTestResult,
  type ModelProfile,
  type ModelProfileDraft,
} from '../lib/modelProfiles'

export type { ConnectionTestResult, ModelProfile, ModelProfileDraft, ProviderType } from '../lib/modelProfiles'

interface ModelProfileState {
  profiles: ModelProfile[]
  loading: boolean
  saving: boolean
  error: string
  selectedProfileId: string
  lastTestResult: ConnectionTestResult | null
  profileTestResults: Record<string, ConnectionTestResult>
  testingProfileIds: string[]
  loadProfiles: () => Promise<void>
  createProfile: (draft: ModelProfileDraft) => Promise<ModelProfile>
  updateProfile: (id: string, draft: Partial<ModelProfileDraft>) => Promise<ModelProfile>
  deleteProfile: (id: string) => Promise<void>
  setDefaultProfile: (id: string) => Promise<ModelProfile>
  testDraft: (draft: ModelProfileDraft) => Promise<ConnectionTestResult>
  testProfile: (id: string) => Promise<ConnectionTestResult>
  selectProfile: (id: string) => void
  reset: () => void
}

const emptyState = {
  profiles: [] as ModelProfile[],
  loading: false,
  saving: false,
  error: '',
  selectedProfileId: '',
  lastTestResult: null as ConnectionTestResult | null,
  profileTestResults: {} as Record<string, ConnectionTestResult>,
  testingProfileIds: [] as string[],
}

const syncDefaultSelection = (profiles: ModelProfile[], currentId: string) => {
  if (currentId && profiles.some((profile) => profile.id === currentId)) {
    return currentId
  }
  return profiles.find((profile) => profile.isDefault)?.id || ''
}

const mergeProfile = (profiles: ModelProfile[], updated: ModelProfile) =>
  [updated, ...profiles.filter((profile) => profile.id !== updated.id)].map((profile) => (
    updated.isDefault && profile.id !== updated.id ? { ...profile, isDefault: false } : profile
  ))

const clearProfileTestResult = (
  results: Record<string, ConnectionTestResult>,
  profileId: string,
) => Object.fromEntries(
  Object.entries(results).filter(([resultProfileId]) => resultProfileId !== profileId),
)

let profileRequest = 0;
export const useModelProfileStore = create<ModelProfileState>((set, get) => ({
  ...emptyState,
  loadProfiles: async () => {
    const request = ++profileRequest;
    set({ loading: true, error: '' })
    try {
      const profiles = await fetchModelProfiles()
      if (request !== profileRequest) return;
      set((state) => ({
        profiles,
        loading: false,
        selectedProfileId: syncDefaultSelection(profiles, state.selectedProfileId),
      }))
    } catch (error) {
      if (request !== profileRequest) return;
      set({
        loading: false,
        error: error instanceof Error ? error.message : 'Failed to load model profiles',
      })
    }
  },
  createProfile: async (draft) => {
    set({ saving: true, error: '' })
    try {
      const created = await createModelProfile(draft)
      const profiles = mergeProfile(get().profiles, created)
      set({
        profiles,
        saving: false,
        selectedProfileId: syncDefaultSelection(profiles, created.id),
      })
      return created
    } catch (error) {
      set({
        saving: false,
        error: error instanceof Error ? error.message : 'Failed to create model profile',
      })
      throw error
    }
  },
  updateProfile: async (id, draft) => {
    set({ saving: true, error: '' })
    try {
      const updated = await updateModelProfile(id, draft)
      const profiles = get().profiles.map((profile) => (
        profile.id === id ? updated : updated.isDefault ? { ...profile, isDefault: false } : profile
      ))
      set({
        profiles,
        saving: false,
        selectedProfileId: syncDefaultSelection(profiles, get().selectedProfileId),
        profileTestResults: clearProfileTestResult(get().profileTestResults, id),
      })
      return updated
    } catch (error) {
      set({
        saving: false,
        error: error instanceof Error ? error.message : 'Failed to update model profile',
      })
      throw error
    }
  },
  deleteProfile: async (id) => {
    set({ saving: true, error: '' })
    try {
      await deleteModelProfile(id)
      const nextSelectedId = get().selectedProfileId === id ? '' : get().selectedProfileId
      const profiles = get().profiles.filter((profile) => profile.id !== id)
      set({
        profiles,
        saving: false,
        selectedProfileId: syncDefaultSelection(profiles, nextSelectedId),
      })
    } catch (error) {
      set({
        saving: false,
        error: error instanceof Error ? error.message : 'Failed to delete model profile',
      })
      throw error
    }
  },
  setDefaultProfile: async (id) => {
    set({ saving: true, error: '' })
    try {
      const updated = await setDefaultModelProfile(id)
      const profiles = get().profiles.map((profile) => ({
        ...profile,
        isDefault: profile.id === updated.id,
      }))
      set({ profiles, saving: false, selectedProfileId: updated.id })
      return updated
    } catch (error) {
      set({
        saving: false,
        error: error instanceof Error ? error.message : 'Failed to set default model profile',
      })
      throw error
    }
  },
  testDraft: async (draft) => {
    set({ saving: true, error: '', lastTestResult: null })
    try {
      const result = await testModelProfileDraft(draft)
      set({ saving: false, lastTestResult: result })
      return result
    } catch (error) {
      set({
        saving: false,
        error: error instanceof Error ? error.message : 'Failed to test model profile',
      })
      throw error
    }
  },
  testProfile: async (id) => {
    set((state) => ({
      saving: true,
      error: '',
      lastTestResult: null,
      testingProfileIds: state.testingProfileIds.includes(id)
        ? state.testingProfileIds
        : [...state.testingProfileIds, id],
    }))
    try {
      const result = await testSavedModelProfile(id)
      set((state) => ({
        saving: false,
        lastTestResult: result,
        profileTestResults: { ...state.profileTestResults, [id]: result },
        testingProfileIds: state.testingProfileIds.filter((profileId) => profileId !== id),
      }))
      return result
    } catch (error) {
      set({
        saving: false,
        error: error instanceof Error ? error.message : 'Failed to test model profile',
        testingProfileIds: get().testingProfileIds.filter((profileId) => profileId !== id),
      })
      throw error
    }
  },
  selectProfile: (id) => set({ selectedProfileId: id }),
  reset: () => { ++profileRequest; set(emptyState) },
}))
