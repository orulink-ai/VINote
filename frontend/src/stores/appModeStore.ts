import { create } from 'zustand'
import { apiJson } from '../lib/api'
import { useModelProfileStore } from './modelProfileStore'
import { useSTTProfileStore } from './sttProfileStore'

export type AppMode = 'cloud' | 'local'
export type ModelSourceConfig = { configured: boolean; mode: AppMode; asr_model: string; llm_model: string; server_url?: string }
export const APP_MODE_EVENT = 'vinote.model-source.changed'
let revision = 0

async function refreshProfiles() {
  useModelProfileStore.getState().selectProfile('')
  useSTTProfileStore.getState().selectProfile('')
  await Promise.all([useModelProfileStore.getState().loadProfiles(), useSTTProfileStore.getState().loadProfiles()])
}

interface AppModeState {
  config: ModelSourceConfig | null
  saving: boolean
  error: string
  load: () => Promise<void>
  setMode: (mode: AppMode) => Promise<void>
  saveModels: (asrModel: string, llmModel: string) => Promise<void>
  reset: () => void
}

export const useAppModeStore = create<AppModeState>((set, get) => ({
  config: null, saving: false, error: '',
  load: async () => {
    if (get().saving) return
    const request = ++revision
    try {
      const config = await apiJson<ModelSourceConfig>('/api/vilab/config')
      if (request !== revision) return
      const changed = get().config && JSON.stringify(get().config) !== JSON.stringify(config)
      set({ config, error: '' })
      if (changed) await refreshProfiles()
    } catch (error) {
      if (request === revision) set({ error: error instanceof Error ? error.message : '无法读取运行模式，请重试' })
    }
  },
  setMode: async mode => {
    if (get().saving) return
    const request = ++revision
    set({ saving: true, error: '' })
    try {
      const config = await apiJson<ModelSourceConfig>('/api/vilab/mode', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode }),
      })
      if (request !== revision) return
      set({ config })
      await refreshProfiles()
      window.localStorage.setItem(APP_MODE_EVENT, String(Date.now()))
    } catch (error) {
      if (request === revision) set({ error: error instanceof Error ? error.message : '模式切换失败，请重试' })
    } finally { if (request === revision) set({ saving: false }) }
  },
  saveModels: async (asr_model, llm_model) => {
    if (get().saving) return
    const request = ++revision
    set({ saving: true, error: '' })
    try {
      const config = await apiJson<ModelSourceConfig>('/api/vilab/config', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'cloud', asr_model, llm_model }),
      })
      if (request !== revision) return
      set({ config })
      await refreshProfiles()
      window.localStorage.setItem(APP_MODE_EVENT, String(Date.now()))
    } catch (error) {
      if (request === revision) set({ error: error instanceof Error ? error.message : '模型保存失败' })
      throw error
    } finally { if (request === revision) set({ saving: false }) }
  },
  reset: () => { revision++; set({ config: null, saving: false, error: '' }) },
}))
