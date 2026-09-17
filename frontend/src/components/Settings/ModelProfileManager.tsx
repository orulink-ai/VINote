import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { NativeSelect } from '../ui/native-select'
import { SavedApiKey } from './SavedApiKey'
import { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { Plus, RotateCcw, Trash2, Wifi } from 'lucide-react'
import { useI18n } from '../../lib/i18n'
import { type ModelProfile, type ModelProfileDraft, type ProviderType } from '../../lib/modelProfiles'
import { useModelProfileStore } from '../../stores/modelProfileStore'
import { Badge } from '../ui/badge'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '../ui/empty'

const providerOptions: Array<{
  value: ProviderType
  label: string
  defaultBaseUrl: string
}> = [
  { value: 'openai-compatible', label: 'OpenAI Compatible', defaultBaseUrl: 'https://api.openai.com/v1' },
  { value: 'anthropic-compatible', label: 'Anthropic Compatible', defaultBaseUrl: 'https://api.anthropic.com/v1' },
  { value: 'azure-openai', label: 'Azure OpenAI', defaultBaseUrl: 'https://your-resource.openai.azure.com' },
  { value: 'ollama', label: 'Ollama', defaultBaseUrl: 'http://localhost:11434/v1' },
  { value: 'groq-openai-compatible', label: 'Groq OpenAI Compatible', defaultBaseUrl: 'https://api.groq.com/openai/v1' },
]

const makeDraft = (): ModelProfileDraft => ({
  name: '',
  provider: 'openai-compatible',
  baseUrl: 'https://api.openai.com/v1',
  modelName: '',
  apiKey: '',
  isDefault: false,
  isActive: true,
})

const profileToDraft = (profile: ModelProfile): ModelProfileDraft => ({
  name: profile.name,
  provider: profile.provider,
  baseUrl: profile.baseUrl,
  modelName: profile.modelName,
  apiKey: '',
  isDefault: profile.isDefault,
  isActive: profile.isActive,
})

export function ModelProfileManager() {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState<ModelProfileDraft>(makeDraft)
  const formRef = useRef<HTMLFormElement>(null)
  const { copy } = useI18n()

  const {
    profiles,
    loading,
    saving,
    error,
    lastTestResult,
    profileTestResults,
    testingProfileIds,
    loadProfiles,
    createProfile,
    updateProfile,
    deleteProfile,
    setDefaultProfile,
    testDraft,
    testProfile,
  } = useModelProfileStore()

  useEffect(() => {
    void loadProfiles()
  }, [loadProfiles])

  const resetForm = () => {
    setEditingId(null)
    setDraft(makeDraft())
  }

  const editingProfile = editingId ? profiles.find((profile) => profile.id === editingId) : null
  const editingDefaultProfile = Boolean(editingProfile?.isDefault)

  const startEdit = (profile: ModelProfile) => {
    setEditingId(profile.id)
    setDraft(profileToDraft(profile))
  }

  const readFormDraft = (): ModelProfileDraft => {
    const form = formRef.current
    if (!form) {
      return draft
    }

    const formData = new FormData(form)
    const field = (name: string, fallback: string) => {
      const value = formData.get(name)
      return typeof value === 'string' ? value : fallback
    }

    return {
      name: field('name', draft.name),
      provider: field('provider', draft.provider) as ProviderType,
      baseUrl: field('baseUrl', draft.baseUrl),
      modelName: field('modelName', draft.modelName),
      apiKey: field('apiKey', draft.apiKey),
      isDefault: editingDefaultProfile || formData.has('isDefault'),
      isActive: formData.has('isActive'),
    }
  }

  const handleSavedProfileTest = async (profile: ModelProfile) => {
    startEdit(profile)
    await testProfile(profile.id)
  }

  const handleSetDefaultProfile = async (profile: ModelProfile) => {
    await setDefaultProfile(profile.id)
    if (editingId === profile.id) {
      setDraft((current) => ({ ...current, isDefault: true }))
    }
  }

  const formatConnectionResult = (result: typeof lastTestResult) => {
    if (!result) {
      return ''
    }
    return result.ok
      ? copy.modelProfiles.connectionSucceeded(result.latencyMs)
      : copy.modelProfiles.connectionFailed(result.errorMessage || copy.modelProfiles.unknownError)
  }

  const handleProviderChange = (provider: ProviderType) => {
    const previousMeta = providerOptions.find((item) => item.value === draft.provider)
    const meta = providerOptions.find((item) => item.value === provider)
    setDraft((current) => ({
      ...current,
      provider,
      baseUrl:
        !current.baseUrl.trim() || current.baseUrl === previousMeta?.defaultBaseUrl
          ? meta?.defaultBaseUrl || ''
          : current.baseUrl,
    }))
  }

  const handleSave = async () => {
    if (!formRef.current?.reportValidity()) {
      return
    }

    const formDraft = readFormDraft()
    if (editingId) {
      await updateProfile(editingId, formDraft)
    } else {
      await createProfile(formDraft)
    }
    resetForm()
  }

  const handleTest = async () => {
    const formDraft = readFormDraft()
    if (editingId && !formDraft.apiKey.trim()) {
      await testProfile(editingId)
      return
    }
    await testDraft(formDraft)
  }

  return (
    <section className="py-2">
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.45fr)_380px]">
        <div className="min-w-0 grid gap-4">
          <div className="flex flex-col gap-4 border-b pb-5 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex items-center gap-3">
                <h3 className="text-xl font-semibold">{copy.modelProfiles.title}</h3>
                <Badge variant="secondary">{profiles.length}</Badge>
              </div>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground dark:text-muted-foreground">{copy.modelProfiles.body}</p>
            </div>
            <Button
              onClick={resetForm}
              variant="outline" className="self-start"
            >
              <Plus className="w-4 h-4" />
              {copy.modelProfiles.newProfile}
            </Button>
          </div>

          {loading ? (
            <div className="border-b py-5 text-sm text-muted-foreground">{copy.modelProfiles.loading}</div>
          ) : profiles.length === 0 ? (
            <Empty className="border border-dashed"><EmptyHeader><EmptyTitle>{copy.modelProfiles.empty}</EmptyTitle><EmptyDescription>{copy.modelProfiles.body}</EmptyDescription></EmptyHeader></Empty>
          ) : (
            <div className="stealth-scroll max-h-[620px] grid gap-3 overflow-y-auto pr-1">
              {profiles.filter(profile => profile.id !== 'vilab-cloud').map((profile) => {
                const profileResult = profileTestResults?.[profile.id]
                const isTestingProfile = testingProfileIds?.includes(profile.id)
                return (
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
                          <Badge>{copy.modelProfiles.default}</Badge>
                        )}
                        {!profile.isActive && (
                          <Badge variant="outline">{copy.modelProfiles.inactive}</Badge>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground dark:text-muted-foreground mt-1">
                        {profile.provider} / {profile.modelName}
                      </p>
                      <p className="mt-2 break-all text-xs leading-5 text-muted-foreground">{profile.baseUrl}</p>
                      <SavedApiKey key={profile.updatedAt} kind="model" profileId={profile.id} hint={profile.apiKeyHint} />
                      {(isTestingProfile || profileResult) && (
                        <p
                          className={clsx(
                            'mt-3 inline-flex rounded-full px-2.5 py-1 text-xs font-medium',
                            isTestingProfile
                              ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300'
                              : profileResult?.ok
                                ? 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-300'
                                : 'bg-destructive/10 text-destructive dark:bg-red-900/20 dark:text-red-300'
                          )}
                        >
                          {isTestingProfile ? '测试中...' : formatConnectionResult(profileResult)}
                        </p>
                      )}
                    </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        onClick={() => void handleSavedProfileTest(profile)}
                        disabled={isTestingProfile}
                        variant="outline" size="sm"
                        title={copy.modelProfiles.testConnection}
                      >
                        <Wifi className="w-4 h-4" />
                        {copy.modelProfiles.testConnection}
                      </Button>
                      <Button
                        onClick={() => startEdit(profile)}
                        variant="outline" size="sm"
                      >
                        {copy.modelProfiles.edit}
                      </Button>
                      {!profile.isDefault && (
                        <Button
                          onClick={() => void handleSetDefaultProfile(profile)}
                          variant="outline" size="sm"
                        >
                          {copy.modelProfiles.setDefault}
                        </Button>
                      )}
                      <Button
                        onClick={() => void deleteProfile(profile.id)}
                        variant="ghost" size="icon" className="text-destructive hover:text-destructive"
                        title={copy.modelProfiles.delete}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                </div>
                )
              })}
            </div>
          )}
        </div>

        <aside className="xl:sticky xl:top-8 xl:self-start">
          <form
            ref={formRef}
            onSubmit={(event) => {
              event.preventDefault()
              void handleSave()
            }}
            className="grid gap-4 border-l pl-6"
          >
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-semibold">{editingId ? copy.modelProfiles.editTitle : copy.modelProfiles.createTitle}</h3>
                <Badge variant="secondary">{editingId ? copy.modelProfiles.edit : copy.modelProfiles.newProfile}</Badge>
              </div>
              <p className="mt-2 text-sm leading-6 text-muted-foreground dark:text-muted-foreground">{copy.modelProfiles.connectionBody}</p>
            </div>
            <Button
              onClick={resetForm}
              variant="ghost" size="icon"
              title={copy.modelProfiles.resetForm}
            >
              <RotateCcw className="w-4 h-4" />
            </Button>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">{copy.modelProfiles.name}</label>
            <Input
              name="name"
              required
              value={draft.name}
              onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
              placeholder={copy.modelProfiles.namePlaceholder}
              className="w-full px-4 py-2.5 rounded-lg border border-border dark:border-border bg-card  outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">{copy.modelProfiles.provider}</label>
            <NativeSelect
              name="provider"
              value={draft.provider}
              onChange={(event) => handleProviderChange(event.target.value as ProviderType)}
              className="w-full px-4 py-2.5 rounded-lg border border-border dark:border-border bg-card  outline-none focus:ring-2 focus:ring-ring"
            >
              {providerOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </NativeSelect>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">{copy.modelProfiles.baseUrl}</label>
            <Input
              name="baseUrl"
              required
              value={draft.baseUrl}
              onChange={(event) => setDraft((current) => ({ ...current, baseUrl: event.target.value }))}
              placeholder={providerOptions.find((item) => item.value === draft.provider)?.defaultBaseUrl}
              className="w-full px-4 py-2.5 rounded-lg border border-border dark:border-border bg-card  outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">{copy.modelProfiles.model}</label>
            <Input
              name="modelName"
              required
              value={draft.modelName}
              onChange={(event) => setDraft((current) => ({ ...current, modelName: event.target.value }))}
              placeholder={copy.modelProfiles.modelPlaceholder}
              className="w-full px-4 py-2.5 rounded-lg border border-border dark:border-border bg-card  outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">
              {copy.modelProfiles.apiKey} {editingId ? <span className="text-xs text-muted-foreground">{copy.modelProfiles.keepCurrentKey}</span> : null}
            </label>
            <Input
              name="apiKey"
              required={!editingId}
              type="password"
              value={draft.apiKey}
              onChange={(event) => setDraft((current) => ({ ...current, apiKey: event.target.value }))}
              placeholder={editingId ? copy.modelProfiles.apiKeyEditPlaceholder : copy.modelProfiles.apiKeyCreatePlaceholder}
              className="w-full px-4 py-2.5 rounded-lg border border-border dark:border-border bg-card  outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          <label className="flex items-center gap-3">
            <Input
              name="isDefault"
              type="checkbox"
              checked={draft.isDefault}
              disabled={editingDefaultProfile}
              onChange={(event) => setDraft((current) => ({ ...current, isDefault: editingDefaultProfile || event.target.checked }))}
              className="w-4 h-4"
            />
            <span className="text-sm">{copy.modelProfiles.useAsDefault}</span>
          </label>

          <label className="flex items-center gap-3">
            <Input
              name="isActive"
              type="checkbox"
              checked={draft.isActive}
              onChange={(event) => setDraft((current) => ({ ...current, isActive: event.target.checked }))}
              className="w-4 h-4"
            />
            <span className="text-sm">{copy.modelProfiles.profileIsActive}</span>
          </label>

          {(error || lastTestResult) && (
            <div
              className={clsx(
                'p-3 rounded-lg text-sm',
                lastTestResult?.ok
                  ? 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-300'
                  : 'bg-muted/40 text-foreground dark:bg-muted dark:text-muted-foreground'
              )}
            >
              {error || (
                lastTestResult?.ok
                  ? copy.modelProfiles.connectionSucceeded(lastTestResult.latencyMs)
                  : copy.modelProfiles.connectionFailed(lastTestResult?.errorMessage || copy.modelProfiles.unknownError)
              )}
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <Button
              type="button"
              onClick={() => void handleTest()}
              disabled={saving}
              variant="outline"
            >
              <Wifi className="w-4 h-4" />
              {copy.modelProfiles.testConnection}
            </Button>
            <Button
              type="submit"
              disabled={saving}
            >
              {editingId ? copy.modelProfiles.saveChanges : copy.modelProfiles.createProfile}
            </Button>
          </div>
          </form>
        </aside>
      </div>
    </section>
  )
}
