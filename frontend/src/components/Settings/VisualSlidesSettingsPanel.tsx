import { useEffect, useId, useRef, useState } from 'react'
import { ApiError, apiJson } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import { resolveBackendOrigin } from '@/lib/runtimeConfig'
import { useAuthStore } from '@/stores/authStore'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'

interface VisualSlidesPreferencePayload {
  language?: string | null
  visual_slides_enabled: boolean
  visual_slides_auto_generate: boolean
}

type ErrorState = { kind: 'default' } | { kind: 'message'; text: string } | null
type StatusKind = 'enabled' | 'disabled' | null

function parsePreferencePayload(raw: unknown): VisualSlidesPreferencePayload | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const record = raw as Record<string, unknown>
  if (
    typeof record.visual_slides_enabled !== 'boolean' ||
    typeof record.visual_slides_auto_generate !== 'boolean'
  ) {
    return null
  }
  return {
    language: typeof record.language === 'string' || record.language === null ? record.language : null,
    visual_slides_enabled: record.visual_slides_enabled,
    visual_slides_auto_generate: record.visual_slides_auto_generate,
  }
}

export function VisualSlidesSettingsPanel() {
  const owner = useAuthStore((state) => state.user?.id)
  const origin = resolveBackendOrigin()
  const [authEpoch, setAuthEpoch] = useState(0)

  useEffect(() => {
    if (typeof useAuthStore.subscribe !== 'function') return
    let observed = useAuthStore.getState?.()?.user?.id
    return useAuthStore.subscribe((state) => {
      const next = state.user?.id
      if (next !== observed) {
        observed = next
        setAuthEpoch((n) => n + 1)
      }
    })
  }, [])

  return (
    <VisualSlidesPreferences
      key={JSON.stringify([owner || 'signed-out', origin, authEpoch])}
      owner={owner}
      origin={origin}
    />
  )
}

function VisualSlidesPreferences({ owner, origin }: { owner?: string; origin: string }) {
  const switchId = useId()
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const [loading, setLoading] = useState(Boolean(owner))
  const [saving, setSaving] = useState(false)
  const [serverEnabled, setServerEnabled] = useState(true)
  const [autoGenerate, setAutoGenerate] = useState(false)
  const [loadError, setLoadError] = useState<ErrorState>(null)
  const [saveError, setSaveError] = useState<ErrorState>(null)
  const [statusKind, setStatusKind] = useState<StatusKind>(null)
  const [reloadTick, setReloadTick] = useState(0)

  const alive = useRef(true)
  const epochRef = useRef(0)
  const loadSeq = useRef(0)
  const savingClaim = useRef(false)
  const autoGenerateRef = useRef(false)

  useEffect(() => {
    alive.current = true
    let observed = useAuthStore.getState?.()?.user?.id
    const unsubscribe =
      typeof useAuthStore.subscribe === 'function'
        ? useAuthStore.subscribe((state) => {
            const next = state.user?.id
            if (next !== observed) {
              observed = next
              epochRef.current += 1
            }
          })
        : undefined
    return () => {
      alive.current = false
      unsubscribe?.()
    }
  }, [])

  const isInScope = (capturedEpoch: number) =>
    alive.current &&
    Boolean(owner) &&
    epochRef.current === capturedEpoch &&
    useAuthStore.getState?.()?.user?.id === owner &&
    resolveBackendOrigin() === origin

  useEffect(() => {
    if (!owner) {
      setLoading(false)
      setLoadError(null)
      setAutoGenerate(false)
      autoGenerateRef.current = false
      return
    }
    const capturedEpoch = epochRef.current
    const seq = ++loadSeq.current
    const controller = new AbortController()
    setLoading(true)
    setLoadError(null)
    setSaveError(null)
    setStatusKind(null)

    void apiJson<unknown>('/api/preferences', {
      cache: 'no-store',
      signal: controller.signal,
    })
      .then((raw) => {
        if (!isInScope(capturedEpoch) || loadSeq.current !== seq) return
        const parsed = parsePreferencePayload(raw)
        if (!parsed) {
          setLoadError({ kind: 'default' })
          return
        }
        setServerEnabled(parsed.visual_slides_enabled)
        setAutoGenerate(parsed.visual_slides_auto_generate)
        autoGenerateRef.current = parsed.visual_slides_auto_generate
      })
      .catch((cause) => {
        if (!isInScope(capturedEpoch) || loadSeq.current !== seq) return
        setLoadError(
          cause instanceof Error && cause.message
            ? { kind: 'message', text: cause.message }
            : { kind: 'default' },
        )
      })
      .finally(() => {
        if (isInScope(capturedEpoch) && loadSeq.current === seq) {
          setLoading(false)
        }
      })

    return () => {
      controller.abort()
    }
  }, [owner, origin, reloadTick])

  async function handleToggle(nextValue: boolean) {
    if (!owner || loading || !serverEnabled || loadError || savingClaim.current) return
    const capturedEpoch = epochRef.current
    if (!isInScope(capturedEpoch)) return

    savingClaim.current = true
    const previous = autoGenerateRef.current
    setSaving(true)
    setSaveError(null)
    setStatusKind(null)
    setAutoGenerate(nextValue)
    autoGenerateRef.current = nextValue

    try {
      const raw = await apiJson<unknown>('/api/preferences', {
        method: 'PATCH',
        body: JSON.stringify({ visual_slides_auto_generate: nextValue }),
      })
      if (!isInScope(capturedEpoch)) return
      const parsed = parsePreferencePayload(raw)
      if (!parsed) {
        setAutoGenerate(previous)
        autoGenerateRef.current = previous
        setSaveError({ kind: 'default' })
        return
      }
      setServerEnabled(parsed.visual_slides_enabled)
      setAutoGenerate(parsed.visual_slides_auto_generate)
      autoGenerateRef.current = parsed.visual_slides_auto_generate
      setStatusKind(parsed.visual_slides_auto_generate ? 'enabled' : 'disabled')
    } catch (cause) {
      if (!isInScope(capturedEpoch)) return
      setAutoGenerate(previous)
      autoGenerateRef.current = previous
      if (cause instanceof ApiError && cause.status === 409) {
        setServerEnabled(false)
      }
      setSaveError(
        cause instanceof Error && cause.message
          ? { kind: 'message', text: cause.message }
          : { kind: 'default' },
      )
    } finally {
      savingClaim.current = false
      if (alive.current) {
        setSaving(false)
      }
    }
  }

  const loadErrorText =
    loadError === null
      ? ''
      : loadError.kind === 'message'
        ? loadError.text
        : zh
          ? '无法读取视觉幻灯片设置。'
          : 'Could not load visual slides preference.'

  const saveErrorText =
    saveError === null
      ? ''
      : saveError.kind === 'message'
        ? saveError.text
        : zh
          ? '保存设置失败，请重试。'
          : 'Failed to save preference. Please retry.'

  const statusText =
    statusKind === 'enabled'
      ? zh
        ? '已开启，下一次会议纪要完成后将自动生成配图。'
        : 'Enabled. Visual slides will generate automatically after the next meeting summary.'
      : statusKind === 'disabled'
        ? zh
          ? '已关闭，后续仍可在纪要页手动生成。'
          : 'Disabled. You can still generate visual slides manually from any meeting note.'
        : ''

  return (
    <section className="min-w-0">
      <h3 className="text-base font-medium">{zh ? '视觉幻灯片' : 'Visual slides'}</h3>
      <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
        {zh
          ? '会议纪要生成完成后，在后台按章节自动生成 16:9 HTML/SVG 图解并插入正文，不影响文字纪要阅读。'
          : 'After meeting minutes complete, asynchronously generate 16:9 HTML/SVG visual slides and insert them under matching headings without blocking text reading.'}
      </p>
      <div className="mt-4 flex items-center justify-between gap-4 border-y py-4">
        <label htmlFor={switchId} className="text-sm font-medium">
          {zh ? '会议纪要自动生成视觉幻灯片' : 'Auto-generate visual slides for meeting minutes'}
        </label>
        <Switch
          id={switchId}
          checked={autoGenerate}
          disabled={!owner || loading || saving || !serverEnabled || Boolean(loadError)}
          onCheckedChange={(checked) => void handleToggle(checked)}
        />
      </div>
      {!serverEnabled && !loadError && (
        <p className="mt-3 text-sm text-muted-foreground">
          {zh
            ? '当前服务端未启用视觉幻灯片功能（VISUAL_SLIDES_ENABLED=false）。'
            : 'Visual slides are disabled on this server (VISUAL_SLIDES_ENABLED=false).'}
        </p>
      )}
      {loadErrorText && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm text-destructive">{loadErrorText}</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={loading}
            onClick={() => setReloadTick((n) => n + 1)}
          >
            {zh ? '重新读取' : 'Retry'}
          </Button>
        </div>
      )}
      {saveErrorText && (
        <p role="alert" className="mt-2 text-sm text-destructive">{saveErrorText}</p>
      )}
      {statusText && (
        <p role="status" className="mt-2 text-sm text-muted-foreground">{statusText}</p>
      )}
    </section>
  )
}
