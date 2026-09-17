import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { NativeSelect } from '../ui/native-select'
import { SavedApiKey } from './SavedApiKey'
import { useEffect, useState } from 'react'
import clsx from 'clsx'
import { Plus, RotateCcw, Trash2 } from 'lucide-react'
import { useI18n } from '../../lib/i18n'
import { type STTProfile, type STTProfileDraft, type STTProviderType } from '../../lib/sttProfiles'
import { useSTTProfileStore } from '../../stores/sttProfileStore'
import { Badge } from '../ui/badge'
import { Alert, AlertDescription } from '../ui/alert'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '../ui/empty'

const providerOptions: Array<{
  value: STTProviderType
  label: string
}> = [
  { value: 'vliab-server', label: 'VILab Server (vliab-server)' },
  { value: 'groq', label: 'Groq Whisper' },
  { value: 'whisper', label: 'OpenAI Whisper' },
  { value: 'faster-whisper', label: 'faster-whisper' },
  { value: 'sensevoice', label: 'SenseVoice API' },
  { value: 'sensevoice-local', label: 'SenseVoice Local' },
]

const getDefaultDraft = (provider: STTProviderType = 'groq'): STTProfileDraft => {
  switch (provider) {
    case 'vliab-server':
      return { ...getDefaultDraft('groq'), provider, modelName: '', baseUrl: 'http://localhost:9876' }
    case 'groq':
      return {
        name: '',
        provider,
        modelName: 'whisper-large-v3-turbo',
        baseUrl: 'https://api.groq.com/openai/v1',
        apiKey: '',
        language: '',
        device: '',
        computeType: '',
        useGpu: false,
        isDefault: false,
        isActive: true,
      }
    case 'whisper':
      return {
        name: '',
        provider,
        modelName: 'base',
        baseUrl: '',
        apiKey: '',
        language: '',
        device: 'cpu',
        computeType: '',
        useGpu: false,
        isDefault: false,
        isActive: true,
      }
    case 'faster-whisper':
      return {
        name: '',
        provider,
        modelName: 'base',
        baseUrl: '',
        apiKey: '',
        language: '',
        device: 'cpu',
        computeType: 'int8',
        useGpu: false,
        isDefault: false,
        isActive: true,
      }
    case 'sensevoice':
      return {
        name: '',
        provider,
        modelName: '',
        baseUrl: 'http://localhost:50000',
        apiKey: '',
        language: 'auto',
        device: '',
        computeType: '',
        useGpu: false,
        isDefault: false,
        isActive: true,
      }
    case 'sensevoice-local':
      return {
        name: '',
        provider,
        modelName: 'small',
        baseUrl: '',
        apiKey: '',
        language: 'auto',
        device: '',
        computeType: '',
        useGpu: false,
        isDefault: false,
        isActive: true,
      }
  }
}

const profileToDraft = (profile: STTProfile): STTProfileDraft => ({
  name: profile.name,
  provider: profile.provider,
  modelName: profile.modelName || '',
  baseUrl: profile.baseUrl || '',
  apiKey: '',
  language: profile.language || (profile.provider === 'groq' ? '' : 'auto'),
  device: profile.device || '',
  computeType: profile.computeType || '',
  useGpu: profile.useGpu ?? false,
  isDefault: profile.isDefault,
  isActive: profile.isActive,
})

const formatProfileSummary = (profile: STTProfile) => (
  [
    profile.provider,
    profile.modelName,
    profile.language ? `lang=${profile.language}` : null,
    profile.device ? `device=${profile.device}` : null,
    profile.computeType ? `compute=${profile.computeType}` : null,
    profile.useGpu !== null ? `gpu=${profile.useGpu ? 'on' : 'off'}` : null,
  ].filter(Boolean).join(' / ')
)

const requiresApiKey = (provider: STTProviderType) => (provider === 'groq' || provider === 'vliab-server')

const canSave = (draft: STTProfileDraft, editingId: string | null) => {
  if (!draft.name.trim()) {
    return false
  }
  if (draft.provider === 'vliab-server') {
    return Boolean(draft.baseUrl.trim() && (editingId || draft.apiKey.trim()))
  }
  if (draft.provider === 'groq') {
    return Boolean(draft.modelName.trim() && (editingId || draft.apiKey.trim()))
  }
  if (draft.provider === 'whisper') {
    return Boolean(draft.modelName.trim() && draft.device.trim())
  }
  if (draft.provider === 'faster-whisper') {
    return Boolean(draft.modelName.trim() && draft.device.trim() && draft.computeType.trim())
  }
  if (draft.provider === 'sensevoice') {
    return Boolean(draft.baseUrl.trim() && draft.language.trim())
  }
  return Boolean(draft.modelName.trim() && draft.language.trim())
}

const languageOptions = [
  { value: '', label: 'Auto' },
  { value: 'auto', label: 'Auto' },
  { value: 'zh', label: 'Chinese' },
  { value: 'en', label: 'English' },
  { value: 'yue', label: 'Cantonese' },
  { value: 'ja', label: 'Japanese' },
  { value: 'ko', label: 'Korean' },
]

export function STTProfileManager() {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState<STTProfileDraft>(() => getDefaultDraft())
  const { copy } = useI18n()

  const {
    profiles,
    loading,
    saving,
    error,
    localSupport,
    localSupportLoading,
    loadProfiles,
    loadLocalSupport,
    createProfile,
    updateProfile,
    deleteProfile,
    setDefaultProfile,
  } = useSTTProfileStore()

  useEffect(() => {
    void loadProfiles()
  }, [loadProfiles])

  useEffect(() => {
    if (draft.provider === 'faster-whisper') {
      void loadLocalSupport()
    }
  }, [draft.provider, loadLocalSupport])

  const resetForm = () => {
    setEditingId(null)
    setDraft(getDefaultDraft())
  }

  const handleSetDefaultProfile = async (profile: STTProfile) => {
    await setDefaultProfile(profile.id)
    if (editingId === profile.id) {
      setDraft((current) => ({ ...current, isDefault: true }))
    }
  }

  const editingProfile = editingId ? profiles.find((profile) => profile.id === editingId) : null
  const editingDefaultProfile = Boolean(editingProfile?.isDefault)

  const startEdit = (profile: STTProfile) => {
    setEditingId(profile.id)
    setDraft(profileToDraft(profile))
  }

  const handleProviderChange = (provider: STTProviderType) => {
    setDraft((current) => ({
      ...getDefaultDraft(provider),
      name: current.name,
      isDefault: current.isDefault,
      isActive: current.isActive,
    }))
  }

  const handleSave = async () => {
    const draftToSave = editingDefaultProfile ? { ...draft, isDefault: true } : draft
    if (editingId) {
      await updateProfile(editingId, draftToSave)
    } else {
      await createProfile(draftToSave)
    }
    resetForm()
  }

  const showModel = draft.provider !== 'sensevoice'
  const showBaseUrl = draft.provider === 'sensevoice' || draft.provider === 'vliab-server'
  const showApiKey = requiresApiKey(draft.provider)
  const showLanguage = draft.provider === 'vliab-server' || draft.provider === 'groq' || draft.provider === 'faster-whisper' || draft.provider === 'sensevoice' || draft.provider === 'sensevoice-local'
  const showDevice = draft.provider === 'whisper' || draft.provider === 'faster-whisper'
  const showComputeType = draft.provider === 'faster-whisper'
  const showUseGpu = draft.provider === 'sensevoice-local'
  const showLocalSupport = draft.provider === 'faster-whisper'
  const availableLanguageOptions = languageOptions.filter((option) => (
    draft.provider === 'groq' ? option.value !== 'auto' : option.value !== ''
  ))

  return (
    <section className="py-2">
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.45fr)_380px]">
        <div className="min-w-0 grid gap-4">
          <div className="flex flex-col gap-4 border-b pb-5 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex items-center gap-3">
                <h3 className="text-xl font-semibold">{copy.sttProfiles.title}</h3>
                <Badge variant="secondary">{profiles.length}</Badge>
              </div>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground dark:text-muted-foreground">{copy.sttProfiles.body}</p>
            </div>
            <Button
              onClick={resetForm}
              variant="outline" className="self-start whitespace-nowrap"
            >
              <Plus className="w-4 h-4" />
              {copy.sttProfiles.newProfile}
            </Button>
          </div>

          {loading ? (
            <div className="border-b py-5 text-sm text-muted-foreground">{copy.sttProfiles.loading}</div>
          ) : profiles.length === 0 ? (
            <Empty className="border border-dashed"><EmptyHeader><EmptyTitle>{copy.sttProfiles.empty}</EmptyTitle><EmptyDescription>{copy.sttProfiles.body}</EmptyDescription></EmptyHeader></Empty>
          ) : (
            <div className="stealth-scroll max-h-[620px] grid gap-3 overflow-y-auto pr-1">
              {profiles.filter(profile => profile.id !== 'vilab-cloud').map((profile) => (
                <div
                  key={profile.id}
                  className="border-b px-1 py-4 last:border-b-0"
                >
                  <div className="grid gap-4">
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h4 className="font-medium">{profile.name}</h4>
                        {profile.isDefault && (
                          <Badge>{copy.sttProfiles.default}</Badge>
                        )}
                        {!profile.isActive && (
                          <Badge variant="outline">{copy.sttProfiles.inactive}</Badge>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-muted-foreground dark:text-muted-foreground">{formatProfileSummary(profile)}</p>
                      {profile.baseUrl && <p className="mt-2 break-all text-xs leading-5 text-muted-foreground">{profile.baseUrl}</p>}
                      <SavedApiKey key={profile.updatedAt} kind="stt" profileId={profile.id} hint={profile.apiKeyHint} />
                    </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        onClick={() => startEdit(profile)}
                        variant="outline" size="sm"
                      >
                        {copy.sttProfiles.edit}
                      </Button>
                      {!profile.isDefault && (
                        <Button
                          onClick={() => void handleSetDefaultProfile(profile)}
                          variant="outline" size="sm"
                        >
                          {copy.sttProfiles.setDefault}
                        </Button>
                      )}
                      <Button
                        onClick={() => void deleteProfile(profile.id)}
                        variant="ghost" size="icon" className="text-destructive hover:text-destructive"
                        title={copy.sttProfiles.delete}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <aside className="xl:sticky xl:top-8 xl:self-start">
          <section className="grid gap-4 border-l pl-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-semibold">{editingId ? copy.sttProfiles.editTitle : copy.sttProfiles.createTitle}</h3>
                <Badge variant="secondary">{editingId ? copy.sttProfiles.edit : copy.sttProfiles.newProfile}</Badge>
              </div>
              <p className="mt-2 text-sm leading-6 text-muted-foreground dark:text-muted-foreground">{copy.sttProfiles.formBody}</p>
            </div>
            <Button
              onClick={resetForm}
              variant="ghost" size="icon"
              title={copy.sttProfiles.resetForm}
            >
              <RotateCcw className="w-4 h-4" />
            </Button>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">{copy.sttProfiles.name}</label>
            <Input
              value={draft.name}
              onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
              placeholder={copy.sttProfiles.namePlaceholder}
              className="w-full px-4 py-2.5 rounded-lg border border-border dark:border-border bg-card  outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">{copy.sttProfiles.provider}</label>
            <NativeSelect
              value={draft.provider}
              onChange={(event) => handleProviderChange(event.target.value as STTProviderType)}
              className="w-full px-4 py-2.5 rounded-lg border border-border dark:border-border bg-card  outline-none focus:ring-2 focus:ring-ring"
            >
              {providerOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </NativeSelect>
          </div>

          {showLocalSupport && (
            <Alert>
              <AlertDescription>
              <p className="font-medium">
                {localSupportLoading
                  ? copy.sttProfiles.loading
                  : localSupport?.message || (localSupport?.installed ? copy.sttProfiles.localSupportInstalled : copy.sttProfiles.localSupportMissing)}
              </p>
              <p className="mt-1 text-xs opacity-80">
                {localSupport?.installed
                  ? copy.sttProfiles.localSupportModelHint
                  : copy.sttProfiles.localSupportManualInstall}
              </p>
              <code className="mt-3 block border bg-muted px-3 py-2 text-xs text-foreground">
                {localSupport?.installCommand || 'pip install -r requirements.local-transcribers.txt'}
              </code>
              </AlertDescription>
            </Alert>
          )}

          {showModel && (
            <div>
              <label className="block text-sm font-medium mb-2">{copy.sttProfiles.model}</label>
              <Input
                value={draft.modelName}
                onChange={(event) => setDraft((current) => ({ ...current, modelName: event.target.value }))}
                placeholder={copy.sttProfiles.modelPlaceholder}
                className="w-full px-4 py-2.5 rounded-lg border border-border dark:border-border bg-card  outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
          )}

          {showBaseUrl && (
            <div>
              <label className="block text-sm font-medium mb-2">{copy.sttProfiles.baseUrl}</label>
              <Input
                value={draft.baseUrl}
                onChange={(event) => setDraft((current) => ({ ...current, baseUrl: event.target.value }))}
                placeholder="http://localhost:50000"
                className="w-full px-4 py-2.5 rounded-lg border border-border dark:border-border bg-card  outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
          )}

          {showApiKey && (
            <div>
              <label className="block text-sm font-medium mb-2">
                {copy.sttProfiles.apiKey} {editingId ? <span className="text-xs text-muted-foreground">{copy.sttProfiles.keepCurrentKey}</span> : null}
              </label>
              <Input
                type="password"
                value={draft.apiKey}
                onChange={(event) => setDraft((current) => ({ ...current, apiKey: event.target.value }))}
                placeholder={editingId ? copy.sttProfiles.apiKeyEditPlaceholder : copy.sttProfiles.apiKeyCreatePlaceholder}
                className="w-full px-4 py-2.5 rounded-lg border border-border dark:border-border bg-card  outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
          )}

          {showLanguage && (
            <div>
              <label className="block text-sm font-medium mb-2">{copy.sttProfiles.language}</label>
              <NativeSelect
                value={draft.language}
                onChange={(event) => setDraft((current) => ({ ...current, language: event.target.value }))}
                className="w-full px-4 py-2.5 rounded-lg border border-border dark:border-border bg-card  outline-none focus:ring-2 focus:ring-ring"
              >
                {availableLanguageOptions.map((option) => (
                  <option key={`${draft.provider}-${option.value}`} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </NativeSelect>
            </div>
          )}

          {showDevice && (
            <div>
              <label className="block text-sm font-medium mb-2">{copy.sttProfiles.device}</label>
              <NativeSelect
                value={draft.device}
                onChange={(event) => setDraft((current) => ({ ...current, device: event.target.value }))}
                className="w-full px-4 py-2.5 rounded-lg border border-border dark:border-border bg-card  outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="cpu">CPU</option>
                <option value="cuda">CUDA</option>
                {draft.provider === 'faster-whisper' && <option value="auto">Auto</option>}
              </NativeSelect>
            </div>
          )}

          {showComputeType && (
            <div>
              <label className="block text-sm font-medium mb-2">{copy.sttProfiles.computeType}</label>
              <NativeSelect
                value={draft.computeType}
                onChange={(event) => setDraft((current) => ({ ...current, computeType: event.target.value }))}
                className="w-full px-4 py-2.5 rounded-lg border border-border dark:border-border bg-card  outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="int8">int8</option>
                <option value="float16">float16</option>
                <option value="float32">float32</option>
              </NativeSelect>
            </div>
          )}

          {showUseGpu && (
            <label className="flex items-center gap-3">
              <Input
                type="checkbox"
                checked={draft.useGpu}
                onChange={(event) => setDraft((current) => ({ ...current, useGpu: event.target.checked }))}
                className="w-4 h-4"
              />
              <span className="text-sm">{copy.sttProfiles.useGpu}</span>
            </label>
          )}

          <label className="flex items-center gap-3">
            <Input
              type="checkbox"
              checked={draft.isDefault}
              disabled={editingDefaultProfile}
              onChange={(event) => setDraft((current) => ({ ...current, isDefault: editingDefaultProfile || event.target.checked }))}
              className="w-4 h-4"
            />
            <span className="text-sm">{copy.sttProfiles.useAsDefault}</span>
          </label>

          <label className="flex items-center gap-3">
            <Input
              type="checkbox"
              checked={draft.isActive}
              onChange={(event) => setDraft((current) => ({ ...current, isActive: event.target.checked }))}
              className="w-4 h-4"
            />
            <span className="text-sm">{copy.sttProfiles.profileIsActive}</span>
          </label>

          {error && (
            <div className={clsx('p-3 rounded-lg text-sm bg-muted/40 text-foreground dark:bg-muted dark:text-muted-foreground')}>
              {error}
            </div>
          )}

          <div className="grid gap-3">
            <Button
              onClick={() => void handleSave()}
              disabled={saving || !canSave(draft, editingId)}
            >
              {editingId ? copy.sttProfiles.saveChanges : copy.sttProfiles.createProfile}
            </Button>
          </div>

          {requiresApiKey(draft.provider) && (
            <p className="text-xs text-muted-foreground">{copy.sttProfiles.keyHint}</p>
          )}
          </section>
        </aside>
      </div>
    </section>
  )
}
