import { apiJson } from './api'
export { modelConnectionScope, onModelConnectionIdentityChange } from './vilabConnectionIdentity'
import type { ModelEligibilityInput } from './modelEligibility'
import type { RecordedAudioModel } from './recordedAudioPolicy'
import type { FrozenModelCatalogEntry } from './frozenModelDisplay'

export type VILabModel = ModelEligibilityInput & RecordedAudioModel & FrozenModelCatalogEntry
export type VILabConnection = { connection_id: string; server_url: string; builtin?: boolean; has_credential?: boolean; auth_mode?: 'account' | 'api_key'; asr_model?: string; llm_model?: string }
export type VILabConnectionCheck = { check_id: string; server_url: string; models: VILabModel[]; expires_in: number; asr_model: string; llm_model: string; auth_mode?: 'account' | 'api_key' }
export type VILabConnectionDraft = { server_url?: string; api_key?: string; connection_id?: string; auth_mode?: 'account' | 'api_key'; account_consent?: boolean; authorized_origin?: string }

export const listVILabConnections = () => apiJson<{ connections: VILabConnection[] }>('/api/vilab/connections', { cache: 'no-store' })
export const checkVILabConnection = (draft: VILabConnectionDraft) => apiJson<VILabConnectionCheck>('/api/vilab/connections/check', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(draft),
})
