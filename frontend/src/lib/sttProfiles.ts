import { apiJson } from './api'

export type STTProviderType =
  | 'vliab-server'
  | 'groq'
  | 'whisper'
  | 'faster-whisper'
  | 'sensevoice'
  | 'sensevoice-local'

export interface STTProfile {
  id: string
  name: string
  provider: STTProviderType
  modelName: string | null
  baseUrl: string | null
  apiKeyHint: string
  language: string | null
  device: string | null
  computeType: string | null
  useGpu: boolean | null
  isDefault: boolean
  isActive: boolean
  createdAt?: string
  updatedAt?: string
}

export interface STTProfileDraft {
  name: string
  provider: STTProviderType
  modelName: string
  baseUrl: string
  apiKey: string
  language: string
  device: string
  computeType: string
  useGpu: boolean
  isDefault: boolean
  isActive: boolean
}

export interface LocalSTTSupportStatus {
  provider: string
  installed: boolean
  installCommand: string
  message: string
}

type ApiLocalSTTSupportStatus = {
  provider: string
  installed: boolean
  install_command: string
  message: string
}

type ApiSTTProfile = {
  id: string
  name: string
  provider: STTProviderType
  model_name: string | null
  base_url: string | null
  api_key_hint: string
  language: string | null
  device: string | null
  compute_type: string | null
  use_gpu: boolean | null
  is_default: boolean
  is_active: boolean
  created_at?: string
  updated_at?: string
}

const mapProfile = (profile: ApiSTTProfile): STTProfile => ({
  id: profile.id,
  name: profile.name,
  provider: profile.provider,
  modelName: profile.model_name,
  baseUrl: profile.base_url,
  apiKeyHint: profile.api_key_hint,
  language: profile.language,
  device: profile.device,
  computeType: profile.compute_type,
  useGpu: profile.use_gpu,
  isDefault: profile.is_default,
  isActive: profile.is_active,
  createdAt: profile.created_at,
  updatedAt: profile.updated_at,
})

const mapLocalSupportStatus = (status: ApiLocalSTTSupportStatus): LocalSTTSupportStatus => ({
  provider: status.provider,
  installed: status.installed,
  installCommand: status.install_command,
  message: status.message,
})

const buildDraftPayload = (draft: Partial<STTProfileDraft>) => {
  const payload: Record<string, unknown> = {}
  if (draft.name !== undefined) payload.name = draft.name
  if (draft.provider !== undefined) payload.provider = draft.provider
  if (draft.isDefault !== undefined) payload.is_default = draft.isDefault
  if (draft.isActive !== undefined) payload.is_active = draft.isActive

  const normalizeLanguage = (raw?: string) => {
    if (raw === undefined) return undefined
    const trimmed = raw.trim().toLowerCase()
    if (!trimmed || trimmed === 'auto') return null
    return trimmed
  }

  switch (draft.provider) {
    case 'vliab-server':
      if (draft.baseUrl !== undefined) payload.base_url = draft.baseUrl
      if (draft.modelName !== undefined) payload.model_name = draft.modelName || null
      if (draft.apiKey !== undefined && draft.apiKey.trim()) payload.api_key = draft.apiKey
      if (draft.language !== undefined) payload.language = normalizeLanguage(draft.language)
      break
    case 'groq':
      if (draft.modelName !== undefined) payload.model_name = draft.modelName || null
      if (draft.apiKey !== undefined && draft.apiKey.trim()) payload.api_key = draft.apiKey
      if (draft.language !== undefined) payload.language = normalizeLanguage(draft.language)
      break
    case 'whisper':
      if (draft.modelName !== undefined) payload.model_name = draft.modelName || null
      if (draft.device !== undefined) payload.device = draft.device
      break
    case 'faster-whisper':
      if (draft.modelName !== undefined) payload.model_name = draft.modelName || null
      if (draft.device !== undefined) payload.device = draft.device
      if (draft.computeType !== undefined) payload.compute_type = draft.computeType
      if (draft.language !== undefined) payload.language = normalizeLanguage(draft.language)
      break
    case 'sensevoice':
      if (draft.baseUrl !== undefined) payload.base_url = draft.baseUrl
      if (draft.language !== undefined) payload.language = normalizeLanguage(draft.language)
      break
    case 'sensevoice-local':
      if (draft.modelName !== undefined) payload.model_name = draft.modelName || null
      if (draft.language !== undefined) payload.language = normalizeLanguage(draft.language)
      if (draft.useGpu !== undefined) payload.use_gpu = draft.useGpu
      break
    default:
      break
  }

  return payload
}

export async function fetchSTTProfiles() {
  const data = await apiJson<ApiSTTProfile[]>('/api/stt-profiles')
  return data.map(mapProfile)
}

export async function createSTTProfile(draft: STTProfileDraft) {
  const data = await apiJson<ApiSTTProfile>('/api/stt-profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(buildDraftPayload(draft)),
  })
  return mapProfile(data)
}

export async function updateSTTProfile(id: string, draft: Partial<STTProfileDraft>) {
  const data = await apiJson<ApiSTTProfile>(`/api/stt-profiles/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(buildDraftPayload(draft)),
  })
  return mapProfile(data)
}

export async function deleteSTTProfile(id: string) {
  await apiJson<void>(`/api/stt-profiles/${id}`, { method: 'DELETE' })
}

export async function setDefaultSTTProfile(id: string) {
  const data = await apiJson<ApiSTTProfile>(`/api/stt-profiles/${id}/set-default`, { method: 'POST' })
  return mapProfile(data)
}

export async function fetchLocalSTTSupport() {
  const data = await apiJson<ApiLocalSTTSupportStatus>('/api/stt-profiles/local-support')
  return mapLocalSupportStatus(data)
}
