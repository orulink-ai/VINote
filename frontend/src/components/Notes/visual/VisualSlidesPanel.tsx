import { useEffect, useId, useRef, useState } from 'react'
import {
  ChevronDown,
  ChevronUp,
  Download,
  Loader2,
  Maximize2,
  RefreshCw,
  Sparkles,
} from 'lucide-react'
import { apiFetch, apiJson } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import { downloadRecording } from '@/lib/recordingDownload'
import { resolveBackendOrigin } from '@/lib/runtimeConfig'
import { resolveContentUrl } from '@/lib/videoLinks'
import {
  allSlidesEmbedded,
  apiErrorStatus,
  buildSlideDownloadFilename,
  CANONICAL_TASK_UUID_RE,
  isPngContentType,
  mapSlideDownloadError,
  mapVisualSlideErrorCode,
  MAX_VISUAL_SLIDE_PNG_BYTES,
  parseVisualSlidesPayload,
  slideImagePath,
  type ParsedVisualSlidesPayload,
  type SlideDownloadErrorCode,
  type VisualSlideItem,
} from '@/lib/visualSlides'
import { useAuthStore } from '@/stores/authStore'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'

const DEFAULT_POLL_INTERVAL_MS = 3000
const DEFAULT_MAX_POLL_ATTEMPTS = 80
const MAX_CONSECUTIVE_POLL_ERRORS = 3

type PanelStatus = 'loading' | 'idle' | 'generating' | 'ready' | 'empty' | 'failed'
type ErrorState =
  | { kind: 'trigger_default' }
  | { kind: 'poll_default' }
  | { kind: 'load_default' }
  | { kind: 'message'; text: string }
  | null
type DownloadNotice =
  | { kind: 'saved' }
  | { kind: 'cancelled' }
  | { kind: 'browser_started' }
  | { kind: 'error'; code: SlideDownloadErrorCode }
  | null

class SlideDownloadError extends Error {
  constructor(public readonly code: SlideDownloadErrorCode) {
    super(code)
    this.name = 'SlideDownloadError'
  }
}

export interface VisualSlidesPanelProps {
  taskId: string
  noteTitle: string
  noteContent: string
  disabled?: boolean
  pollIntervalMs?: number
  maxPollAttempts?: number
}

export function VisualSlidesPanel(props: VisualSlidesPanelProps) {
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

  if (!owner || !CANONICAL_TASK_UUID_RE.test(props.taskId)) {
    return null
  }

  return (
    <VisualSlidesDeck
      key={JSON.stringify([owner, props.taskId, origin, authEpoch])}
      {...props}
      owner={owner}
      origin={origin}
    />
  )
}

function VisualSlideCard({
  slide,
  zh,
  downloading,
  onDownload,
  canInteract,
}: {
  slide: VisualSlideItem
  zh: boolean
  downloading: boolean
  onDownload: (slide: VisualSlideItem) => void
  canInteract: () => boolean
}) {
  const [open, setOpen] = useState(false)
  const [thumbFailed, setThumbFailed] = useState(false)
  const [thumbAttempt, setThumbAttempt] = useState(0)
  const [previewState, setPreviewState] = useState<'loading' | 'loaded' | 'failed'>('loading')
  const [previewAttempt, setPreviewAttempt] = useState(0)
  const [originalSize, setOriginalSize] = useState(false)
  const [dimensions, setDimensions] = useState({ width: slide.width, height: slide.height })
  const triggerRef = useRef<HTMLButtonElement>(null)
  const retryRef = useRef<HTMLButtonElement>(null)
  const previewSeq = useRef(0)
  const thumbSeq = useRef(0)

  const path = slideImagePath(slide)
  const src = resolveContentUrl(path)
  const indexLabel = String(slide.index).padStart(2, '0')

  function reloadPreview() {
    if (!canInteract()) return
    setPreviewState('loading')
    setOriginalSize(false)
    setPreviewAttempt(++previewSeq.current)
  }

  return (
    <li className="flex min-w-0 flex-col overflow-hidden rounded-lg border bg-background">
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (next && !canInteract()) return
          if (next) reloadPreview()
          else previewSeq.current += 1
          setOpen(next)
        }}
      >
        <div className="relative min-w-0 bg-muted/40">
          {thumbFailed ? (
            <div className="flex aspect-video flex-col items-center justify-center gap-2 p-4 text-center">
              <p role="status" className="text-xs text-muted-foreground">
                {zh ? '幻灯片预览加载失败。' : 'Slide preview failed to load.'}
              </p>
              <Button
                ref={retryRef}
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  if (!canInteract()) return
                  setThumbFailed(false)
                  setThumbAttempt(++thumbSeq.current)
                }}
              >
                {zh ? '重新加载图片' : 'Reload image'}
              </Button>
            </div>
          ) : (
            <DialogTrigger asChild>
              <button
                ref={triggerRef}
                type="button"
                className="group relative block w-full cursor-zoom-in text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2"
                aria-label={zh ? `放大查看视觉幻灯片：${slide.title}` : `Zoom visual slide: ${slide.title}`}
              >
                <img
                  key={`${path}:${thumbAttempt}`}
                  src={src}
                  alt={slide.caption}
                  className="aspect-video w-full object-contain bg-muted/30"
                  loading="lazy"
                  onError={() => {
                    if (canInteract() && thumbSeq.current === thumbAttempt) {
                      setThumbFailed(true)
                    }
                  }}
                />
                <span className="pointer-events-none absolute right-2 bottom-2 inline-flex items-center gap-1 rounded-md bg-background/85 px-2 py-1 text-xs font-medium text-foreground shadow-sm backdrop-blur-xs opacity-90 transition-opacity group-hover:opacity-100">
                  <Maximize2 className="size-3" aria-hidden="true" />
                  {zh ? '放大查看' : 'Zoom'}
                </span>
              </button>
            </DialogTrigger>
          )}
        </div>

        <DialogContent
          closeLabel={zh ? '关闭幻灯片预览' : 'Close slide preview'}
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            if (
              !canInteract() ||
              document.querySelector('[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]')
            ) {
              return
            }
            const target = [triggerRef.current, retryRef.current].find(
              (button) => button?.isConnected && !button.disabled,
            )
            target?.focus({ preventScroll: true })
          }}
          className="flex max-h-[calc(100dvh-32px)] flex-col sm:max-w-[calc(100vw-32px)]"
        >
          <DialogHeader className="min-w-0 pr-8">
            <DialogTitle className="[overflow-wrap:anywhere]">
              {indexLabel} · {slide.title}
            </DialogTitle>
            <DialogDescription className="[overflow-wrap:anywhere]">
              {slide.caption}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={previewState !== 'loaded'}
              aria-pressed={originalSize}
              onClick={() => {
                if (canInteract()) setOriginalSize((value) => !value)
              }}
            >
              {zh ? '原始尺寸' : 'Original size'}
            </Button>
            <p className="text-xs text-muted-foreground">
              {originalSize
                ? zh
                  ? '按原始尺寸显示，可滚动查看细节。'
                  : 'Showing original dimensions. Scroll to inspect details.'
                : zh
                  ? '适应窗口显示，选择原始尺寸查看小字。'
                  : 'Fit to window. Switch to original size for small text.'}
            </p>
          </div>
          {previewState === 'failed' ? (
            <div className="flex min-h-40 flex-col items-start justify-center gap-3 rounded-lg border bg-muted p-4">
              <p role="status" className="text-sm">
                {zh ? '幻灯片大图加载失败。' : 'Failed to load full-size slide.'}
              </p>
              <Button type="button" variant="outline" size="sm" onClick={reloadPreview}>
                {zh ? '重新读取大图' : 'Reload full image'}
              </Button>
            </div>
          ) : (
            <>
              {previewState === 'loading' && (
                <p role="status" className="text-xs text-muted-foreground">
                  {zh ? '正在读取高清幻灯片…' : 'Loading slide preview…'}
                </p>
              )}
              <div
                role="region"
                aria-label={zh ? '视觉幻灯片大图，可滚动查看' : 'Full-size visual slide, scrollable'}
                tabIndex={0}
                aria-busy={previewState === 'loading'}
                className="h-[65dvh] min-h-0 overflow-auto rounded-lg border bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
              >
                <img
                  key={`${path}:${previewAttempt}`}
                  src={src}
                  alt={slide.caption}
                  className={
                    originalSize
                      ? 'mx-auto block max-w-none'
                      : 'mx-auto block max-h-full max-w-full object-contain'
                  }
                  style={originalSize ? dimensions : undefined}
                  onLoad={(event) => {
                    if (!canInteract() || previewSeq.current !== previewAttempt) return
                    const nw = event.currentTarget.naturalWidth
                    const nh = event.currentTarget.naturalHeight
                    if (nw > 0 && nh > 0) setDimensions({ width: nw, height: nh })
                    setPreviewState('loaded')
                  }}
                  onError={() => {
                    if (canInteract() && previewSeq.current === previewAttempt) {
                      setPreviewState('failed')
                    }
                  }}
                />
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      <div className="flex flex-1 flex-col justify-between gap-2 p-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="font-mono font-medium">{indexLabel}</span>
            {slide.targetHeading && (
              <span className="truncate" title={slide.targetHeading}>
                {slide.targetHeading}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm font-medium leading-snug [overflow-wrap:anywhere]">
            {slide.title}
          </p>
          {slide.caption !== slide.title && (
            <p className="mt-0.5 text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere]">
              {slide.caption}
            </p>
          )}
        </div>
        <div className="flex items-center justify-end pt-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={downloading}
            aria-busy={downloading}
            aria-label={zh ? `下载 PNG：${slide.title}` : `Download PNG: ${slide.title}`}
            onClick={() => onDownload(slide)}
          >
            <Download className="size-3.5" aria-hidden="true" />
            {zh ? '下载 PNG' : 'Download PNG'}
          </Button>
        </div>
      </div>
    </li>
  )
}

function VisualSlidesDeck({
  owner,
  origin,
  taskId,
  noteTitle,
  noteContent,
  disabled = false,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  maxPollAttempts = DEFAULT_MAX_POLL_ATTEMPTS,
}: VisualSlidesPanelProps & { owner: string; origin: string }) {
  const titleId = useId()
  const listId = useId()
  const disabledHelpId = useId()
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')

  const [unavailable, setUnavailable] = useState(false)
  const [status, setStatus] = useState<PanelStatus>('loading')
  const [slides, setSlides] = useState<VisualSlideItem[]>([])
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<ErrorState>(null)
  const [actionError, setActionError] = useState<ErrorState>(null)
  const [serverDisabled, setServerDisabled] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [pollTimedOut, setPollTimedOut] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [downloadNotice, setDownloadNotice] = useState<DownloadNotice>(null)

  const alive = useRef(true)
  const invalidatedRef = useRef(false)
  const requestSeq = useRef(0)
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const activeController = useRef<AbortController | null>(null)
  const downloadController = useRef<AbortController | null>(null)
  const triggerClaim = useRef(false)
  const refreshClaim = useRef(false)
  const downloadClaim = useRef(false)
  const statusRef = useRef<PanelStatus>('loading')
  const pollAttemptsRef = useRef(0)
  const consecutivePollErrorsRef = useRef(0)
  const justGeneratedRef = useRef(false)
  const noteContentRef = useRef(noteContent)
  noteContentRef.current = noteContent

  function setStatusSynced(next: PanelStatus) {
    statusRef.current = next
    setStatus(next)
  }

  function clearPollTimer() {
    if (pollTimer.current !== null) {
      clearTimeout(pollTimer.current)
      pollTimer.current = null
    }
  }

  function abortActiveRequest() {
    if (activeController.current) {
      activeController.current.abort()
      activeController.current = null
    }
  }

  // Any auth transition permanently revokes this mounted instance (including
  // synchronous A -> B -> A before React commits the key-driven remount).
  function isInScope() {
    return (
      alive.current &&
      !invalidatedRef.current &&
      Boolean(owner) &&
      useAuthStore.getState?.()?.user?.id === owner &&
      resolveBackendOrigin() === origin
    )
  }

  useEffect(() => {
    alive.current = true
    let observed = useAuthStore.getState?.()?.user?.id
    const unsubscribe =
      typeof useAuthStore.subscribe === 'function'
        ? useAuthStore.subscribe((state) => {
            const next = state.user?.id
            if (next !== observed) {
              observed = next
              invalidatedRef.current = true
              requestSeq.current += 1
              clearPollTimer()
              abortActiveRequest()
              downloadController.current?.abort()
              downloadController.current = null
              triggerClaim.current = false
              refreshClaim.current = false
              downloadClaim.current = false
            }
          })
        : undefined
    return () => {
      alive.current = false
      clearPollTimer()
      abortActiveRequest()
      downloadController.current?.abort()
      downloadController.current = null
      unsubscribe?.()
    }
  }, [])

  function applyManifest(parsed: ParsedVisualSlidesPayload, seq: number) {
    setLoadError(null)
    setActionError(null)
    setPollTimedOut(false)
    setErrorCode(parsed.errorCode)

    if (parsed.status === 'queued' || parsed.status === 'generating') {
      setStatusSynced('generating')
      schedulePoll(seq)
      return
    }

    clearPollTimer()
    const wasManualGeneration = justGeneratedRef.current
    justGeneratedRef.current = false

    if (parsed.status === 'ready') {
      setSlides(parsed.slides)
      setStatusSynced('ready')
      const embedded = allSlidesEmbedded(parsed.slides, noteContentRef.current)
      setExpanded(wasManualGeneration || !embedded)
      return
    }

    if (parsed.status === 'empty') {
      setSlides([])
      setStatusSynced('empty')
      setExpanded(false)
      return
    }

    if (parsed.status === 'failed') {
      setSlides([])
      setStatusSynced('failed')
      setExpanded(false)
      return
    }

    setSlides([])
    setStatusSynced('idle')
    setExpanded(false)
  }

  function schedulePoll(seq: number) {
    clearPollTimer()
    if (!isInScope() || requestSeq.current !== seq) return
    if (pollAttemptsRef.current >= maxPollAttempts) {
      setPollTimedOut(true)
      return
    }

    pollTimer.current = setTimeout(() => {
      pollTimer.current = null
      if (!isInScope() || requestSeq.current !== seq) return
      pollAttemptsRef.current += 1

      abortActiveRequest()
      const controller = new AbortController()
      activeController.current = controller

      void apiJson<unknown>(`/api/task/${encodeURIComponent(taskId)}/visual-slides`, {
        cache: 'no-store',
        signal: controller.signal,
      })
        .then((raw) => {
          if (!isInScope() || requestSeq.current !== seq) return
          consecutivePollErrorsRef.current = 0
          const parsed = parseVisualSlidesPayload(raw, taskId)
          if (!parsed) {
            clearPollTimer()
            setActionError({ kind: 'poll_default' })
            return
          }
          if (parsed.status === 'queued' || parsed.status === 'generating') {
            setStatusSynced('generating')
            if (pollAttemptsRef.current >= maxPollAttempts) {
              setPollTimedOut(true)
              return
            }
            schedulePoll(seq)
            return
          }
          applyManifest(parsed, seq)
        })
        .catch((cause) => {
          if (!isInScope() || requestSeq.current !== seq) return
          if (apiErrorStatus(cause) === 404) {
            clearPollTimer()
            setUnavailable(true)
            return
          }
          consecutivePollErrorsRef.current += 1
          if (consecutivePollErrorsRef.current >= MAX_CONSECUTIVE_POLL_ERRORS) {
            clearPollTimer()
            setActionError(
              cause instanceof Error && cause.message
                ? { kind: 'message', text: cause.message }
                : { kind: 'poll_default' },
            )
            return
          }
          if (pollAttemptsRef.current >= maxPollAttempts) {
            setPollTimedOut(true)
            return
          }
          schedulePoll(seq)
        })
    }, pollIntervalMs)
  }

  function fetchCurrentStatus(isManualRefresh = false) {
    if (!isInScope()) return
    if (isManualRefresh && refreshClaim.current) return

    const seq = ++requestSeq.current
    clearPollTimer()
    abortActiveRequest()
    pollAttemptsRef.current = 0
    consecutivePollErrorsRef.current = 0
    setPollTimedOut(false)

    if (isManualRefresh) {
      refreshClaim.current = true
      setRefreshing(true)
      setActionError(null)
    } else {
      setLoadError(null)
      setStatusSynced('loading')
    }

    const controller = new AbortController()
    activeController.current = controller

    void apiJson<unknown>(`/api/task/${encodeURIComponent(taskId)}/visual-slides`, {
      cache: 'no-store',
      signal: controller.signal,
    })
      .then((raw) => {
        if (!isInScope() || requestSeq.current !== seq) return
        const parsed = parseVisualSlidesPayload(raw, taskId)
        if (!parsed) {
          setStatusSynced('idle')
          setLoadError({ kind: 'load_default' })
          return
        }
        applyManifest(parsed, seq)
      })
      .catch((cause) => {
        if (!isInScope() || requestSeq.current !== seq) return
        if (apiErrorStatus(cause) === 404) {
          setUnavailable(true)
          return
        }
        setStatusSynced('idle')
        setLoadError(
          cause instanceof Error && cause.message
            ? { kind: 'message', text: cause.message }
            : { kind: 'load_default' },
        )
      })
      .finally(() => {
        if (activeController.current === controller) {
          activeController.current = null
        }
        if (isManualRefresh && requestSeq.current === seq) {
          refreshClaim.current = false
          if (alive.current) {
            setRefreshing(false)
          }
        }
      })
  }

  useEffect(() => {
    fetchCurrentStatus(false)
    return () => {
      clearPollTimer()
      abortActiveRequest()
    }
    // Intentionally excludes locale/noteContent; remount key handles owner/taskId/origin/authEpoch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [owner, taskId, origin])

  async function handleTrigger() {
    if (
      disabled ||
      serverDisabled ||
      Boolean(loadError) ||
      refreshClaim.current ||
      triggerClaim.current ||
      statusRef.current === 'loading' ||
      statusRef.current === 'generating' ||
      !isInScope()
    ) {
      return
    }

    const force = statusRef.current === 'ready' || statusRef.current === 'empty'
    triggerClaim.current = true
    setSubmitting(true)
    setActionError(null)
    setLoadError(null)
    setPollTimedOut(false)
    setDownloadNotice(null)

    const seq = ++requestSeq.current
    clearPollTimer()
    abortActiveRequest()
    pollAttemptsRef.current = 0
    consecutivePollErrorsRef.current = 0
    justGeneratedRef.current = true

    const controller = new AbortController()
    activeController.current = controller

    try {
      const raw = await apiJson<unknown>(`/api/task/${encodeURIComponent(taskId)}/visual-slides`, {
        method: 'POST',
        body: JSON.stringify({ force }),
        cache: 'no-store',
        signal: controller.signal,
      })
      if (!isInScope() || requestSeq.current !== seq) return
      const parsed = parseVisualSlidesPayload(raw, taskId)
      if (!parsed) {
        justGeneratedRef.current = false
        setActionError({ kind: 'trigger_default' })
        return
      }
      applyManifest(parsed, seq)
    } catch (cause) {
      if (!isInScope() || requestSeq.current !== seq) return
      justGeneratedRef.current = false
      const statusCode = apiErrorStatus(cause)
      if (statusCode === 404) {
        setUnavailable(true)
        return
      }
      if (
        statusCode === 409 &&
        cause instanceof Error &&
        (cause.message.includes('禁用') || cause.message.toLowerCase().includes('disabled'))
      ) {
        setServerDisabled(true)
      }
      setActionError(
        cause instanceof Error && cause.message
          ? { kind: 'message', text: cause.message }
          : { kind: 'trigger_default' },
      )
    } finally {
      if (activeController.current === controller) {
        activeController.current = null
      }
      if (requestSeq.current === seq) {
        triggerClaim.current = false
        if (alive.current) {
          setSubmitting(false)
        }
      }
    }
  }

  async function handleDownload(slide: VisualSlideItem) {
    if (downloadClaim.current || !isInScope()) return

    downloadClaim.current = true
    setDownloading(true)
    setDownloadNotice(null)

    downloadController.current?.abort()
    const controller = new AbortController()
    downloadController.current = controller

    const path = slideImagePath(slide)
    const filename = buildSlideDownloadFilename(noteTitle, slide.pngFilename)

    try {
      const result = await downloadRecording(
        async () => {
          if (!isInScope()) {
            throw new SlideDownloadError('scope_changed')
          }
          const response = await apiFetch(path, {
            cache: 'no-store',
            redirect: 'error',
            signal: controller.signal,
          })
          if (!response.ok) {
            throw new SlideDownloadError('fetch_failed')
          }
          if (!isPngContentType(response.headers.get('content-type') || '')) {
            throw new SlideDownloadError('invalid_type')
          }
          const declaredLength = Number(response.headers.get('content-length'))
          if (Number.isFinite(declaredLength) && declaredLength > MAX_VISUAL_SLIDE_PNG_BYTES) {
            throw new SlideDownloadError('invalid_size')
          }
          const blob = await response.blob()
          if (blob.size <= 0 || blob.size > MAX_VISUAL_SLIDE_PNG_BYTES) {
            throw new SlideDownloadError('invalid_size')
          }
          if (!isInScope()) {
            throw new SlideDownloadError('scope_changed')
          }
          return blob
        },
        noteTitle,
        filename,
        isInScope,
      )
      if (isInScope()) {
        setDownloadNotice({ kind: result })
      }
    } catch (cause) {
      if (isInScope()) {
        setDownloadNotice({
          kind: 'error',
          code: cause instanceof SlideDownloadError ? cause.code : 'unknown',
        })
      }
    } finally {
      if (downloadController.current === controller) {
        downloadController.current = null
        downloadClaim.current = false
        if (alive.current) {
          setDownloading(false)
        }
      }
    }
  }

  if (unavailable || status === 'loading') {
    return null
  }

  const pollStopped = pollTimedOut || (status === 'generating' && Boolean(actionError))
  const isActivelyGenerating = submitting || (status === 'generating' && !pollStopped)
  const isBusy = submitting || status === 'generating'
  const isEmbedded = allSlidesEmbedded(slides, noteContent)
  const showUnsavedHelp = disabled && !serverDisabled
  const actionLabel = isBusy
    ? pollStopped
      ? zh
        ? '后台生成中'
        : 'Generating in background'
      : zh
        ? '正在生成视觉幻灯片…'
        : 'Generating visual slides…'
    : status === 'ready'
      ? zh
        ? '重新生成'
        : 'Regenerate'
      : status === 'empty'
        ? zh
          ? '重新尝试生成'
          : 'Try generating again'
        : status === 'failed'
          ? zh
            ? '重新生成视觉幻灯片'
            : 'Retry visual slides'
          : zh
            ? '生成视觉幻灯片'
            : 'Generate visual slides'

  const loadErrorText =
    loadError === null
      ? ''
      : loadError.kind === 'message'
        ? loadError.text
        : zh
          ? '无法读取视觉幻灯片状态，请稍后重试。'
          : 'Could not load visual slides status. Please retry.'

  const actionErrorText =
    actionError === null
      ? ''
      : actionError.kind === 'message'
        ? actionError.text
        : actionError.kind === 'poll_default'
          ? zh
            ? '无法获取最新视觉幻灯片状态，请点击刷新状态重试。'
            : 'Could not read the latest visual slides status. Click refresh to retry.'
          : zh
            ? '无法触发视觉幻灯片生成，请稍后重试。'
            : 'Failed to trigger visual slide generation. Please retry.'

  const failedText = status === 'failed' ? mapVisualSlideErrorCode(errorCode, zh) : ''

  const downloadNoticeText =
    downloadNotice === null
      ? ''
      : downloadNotice.kind === 'saved'
        ? zh
          ? '幻灯片已保存到所选位置。'
          : 'Slide saved to the selected location.'
        : downloadNotice.kind === 'cancelled'
          ? zh
            ? '已取消幻灯片导出。'
            : 'Slide download cancelled.'
          : downloadNotice.kind === 'browser_started'
            ? zh
              ? '幻灯片已交给浏览器下载，请在下载列表查看。'
              : 'Slide handed to your browser for download.'
            : mapSlideDownloadError(downloadNotice.code, zh)

  return (
    <section
      aria-labelledby={titleId}
      className="mx-3 mt-4 shrink-0 min-w-0 rounded-xl border bg-card/40 px-4 py-3 sm:mx-6 sm:px-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Sparkles className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <h2 id={titleId} className="text-sm font-medium">
              {zh ? '视觉幻灯片' : 'Visual slides'}
            </h2>
            {status === 'ready' && slides.length > 0 && (
              <span className="text-xs text-muted-foreground">
                {zh
                  ? `已生成 ${slides.length} 页视觉幻灯片${isEmbedded ? ' · 已嵌入正文' : ''}`
                  : `${slides.length} visual ${slides.length === 1 ? 'slide' : 'slides'} ready${isEmbedded ? ' · embedded in body' : ''}`}
              </span>
            )}
          </div>
          {status === 'idle' && !loadError && !refreshing && (
            <p className="mt-1 text-xs text-muted-foreground">
              {zh
                ? '一键生成 16:9 HTML/SVG 会议核心图解卡片，不影响文字纪要阅读。'
                : 'Generate 16:9 HTML/SVG visual summary slides for this meeting without blocking text reading.'}
            </p>
          )}
          {status === 'generating' && !pollStopped && (
            <p role="status" className="mt-1 text-xs text-muted-foreground">
              {zh
                ? '正在后台规划并渲染 16:9 图解幻灯片，你可以继续阅读正文…'
                : 'Planning and rendering 16:9 visual slides in the background. You can keep reading…'}
            </p>
          )}
          {pollTimedOut && (
            <p role="status" className="mt-1 text-xs text-muted-foreground">
              {zh
                ? '视觉幻灯片仍在后台生成中，请稍后点击刷新状态查看。'
                : 'Visual slides are still generating in the background. Click refresh shortly.'}
            </p>
          )}
          {status === 'empty' && !loadError && !refreshing && (
            <p role="status" className="mt-1 text-xs text-muted-foreground">
              {zh
                ? '本次会议内容较简洁，未生成额外视觉幻灯片；你仍可重新尝试生成。'
                : 'This meeting summary did not produce additional visual slides. You can try regenerating.'}
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {status === 'ready' && slides.length > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-expanded={expanded}
              aria-controls={listId}
              onClick={() => setExpanded((value) => !value)}
            >
              {expanded ? (
                <>
                  <ChevronUp className="size-3.5" aria-hidden="true" />
                  {zh ? '收起卡片视图' : 'Hide slide cards'}
                </>
              ) : (
                <>
                  <ChevronDown className="size-3.5" aria-hidden="true" />
                  {zh ? '展开卡片视图' : 'Show slide cards'}
                </>
              )}
            </Button>
          )}
          {(pollStopped || Boolean(loadError) || refreshing) && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={refreshing}
              aria-busy={refreshing}
              onClick={() => fetchCurrentStatus(true)}
            >
              <RefreshCw
                className={refreshing ? 'size-3.5 animate-spin' : 'size-3.5'}
                aria-hidden="true"
              />
              {refreshing
                ? zh
                  ? '正在刷新状态…'
                  : 'Refreshing status…'
                : zh
                  ? '刷新状态'
                  : 'Refresh status'}
            </Button>
          )}
          <Button
            type="button"
            variant={status === 'ready' ? 'outline' : 'secondary'}
            size="sm"
            disabled={disabled || serverDisabled || Boolean(loadError) || refreshing || isBusy}
            aria-busy={isActivelyGenerating}
            aria-describedby={showUnsavedHelp ? disabledHelpId : undefined}
            onClick={() => void handleTrigger()}
          >
            {isActivelyGenerating ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
            ) : status === 'ready' ? (
              <RefreshCw className="size-3.5" aria-hidden="true" />
            ) : (
              <Sparkles className="size-3.5" aria-hidden="true" />
            )}
            {actionLabel}
          </Button>
        </div>
      </div>

      {showUnsavedHelp && (
        <p id={disabledHelpId} className="mt-2 text-xs text-muted-foreground">
          {zh
            ? '请先保存当前修改后再生成或重新生成视觉幻灯片。'
            : 'Save your changes before generating or regenerating visual slides.'}
        </p>
      )}

      {loadErrorText && (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {loadErrorText}
        </p>
      )}
      {actionErrorText && (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {actionErrorText}
        </p>
      )}
      {failedText && !actionErrorText && (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {failedText}
        </p>
      )}
      {downloading && (
        <p role="status" className="mt-2 text-xs text-muted-foreground">
          {zh ? '正在准备下载幻灯片 PNG…' : 'Preparing slide PNG download…'}
        </p>
      )}
      {downloadNoticeText && (
        <p
          role={downloadNotice?.kind === 'error' ? 'alert' : 'status'}
          className={
            downloadNotice?.kind === 'error'
              ? 'mt-2 text-xs text-destructive'
              : 'mt-2 text-xs text-muted-foreground'
          }
        >
          {downloadNoticeText}
        </p>
      )}

      {status === 'ready' && expanded && slides.length > 0 && (
        <ol id={listId} className="mt-4 grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-2">
          {slides.map((slide) => (
            <VisualSlideCard
              key={`${slide.id}:${slide.pngSha256 || ''}`}
              slide={slide}
              zh={zh}
              downloading={downloading}
              onDownload={(target) => void handleDownload(target)}
              canInteract={isInScope}
            />
          ))}
        </ol>
      )}
    </section>
  )
}
