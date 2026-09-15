import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Download, Edit3, Eye, FileText, MessageSquare, Trash2, Save, Share2 } from 'lucide-react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { MarkdownContent } from '../components/Markdown/MarkdownContent'
import { KeyMomentsRail } from '../components/Notes/KeyMomentsRail'
import { VideoReferencePanel } from '../components/Notes/VideoReferencePanel'
import { SavedRecordingActions } from '../components/Notes/SavedRecordingActions'
import { RecordingRetryBar } from '../components/Notes/RecordingRetryBar'
import { TranscriptEvidencePanel } from '../components/Notes/TranscriptEvidencePanel'
import { apiJson } from '../lib/api'
import { findActiveKeyMoment, type KeyMoment } from '../lib/markdownKeyMoments'
import {
  renderTranscriptMarkdown,
  type TranscriptEvidence,
  type TranscriptTextMode,
} from '../lib/noteTranscript'
import { useI18n } from '../lib/i18n'
import { resolveContentUrl } from '../lib/videoLinks'
import { type NoteRecord, type NoteShareRecord, useNoteLibraryStore } from '../stores/noteLibraryStore'

type WorkspaceMode = 'write' | 'split' | 'preview'
type NoteView = 'summary' | 'transcript'

const HEADING_RE = /^(#{1,6})\s+(.*)$/
const TIMESTAMP_LINK_RE = /\[(\d{1,2}:\d{2})(?:-\d{1,2}:\d{2})?\]\(([^)]+)\)/
const IMAGE_RE = /!\[[^\]]*]\(([^)\s]+)(?:\s+"[^"]*")?\)/

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

function deriveKeyMoments(content: string): KeyMoment[] {
  const lines = content.split(/\r?\n/)
  const sections: Array<{ level: number; heading: string; body: string[] }> = []
  let current: { level: number; heading: string; body: string[] } | null = null

  for (const line of lines) {
    const headingMatch = line.match(HEADING_RE)
    if (headingMatch) {
      if (current) {
        sections.push(current)
      }
      current = {
        level: headingMatch[1].length,
        heading: headingMatch[2],
        body: [],
      }
      continue
    }

    if (current) {
      current.body.push(line)
    }
  }

  if (current) {
    sections.push(current)
  }

  return sections.flatMap((section) => {
    if (section.level < 2) {
      return []
    }

    const timestampMatch = findTimestamp(section.heading, section.body)
    if (!timestampMatch) {
      return []
    }

    const plainHeading = stripMarkdown(section.heading)
    return [{
      anchorId: slugifyHeading(plainHeading),
      title: plainHeading.replace(timestampMatch.label, '').trim(),
      timestampLabel: timestampMatch.label,
      seconds: timestampMatch.seconds,
      imageUrl: findImage(section.body),
      excerpt: findExcerpt(section.body),
      level: section.level,
    }]
  })
}

function findTimestamp(heading: string, body: string[]) {
  const headingMatch = heading.match(TIMESTAMP_LINK_RE)
  if (headingMatch) {
    return {
      label: headingMatch[1],
      seconds: parseSeconds(headingMatch[1], headingMatch[2]),
    }
  }

  for (const line of body) {
    const lineMatch = line.match(TIMESTAMP_LINK_RE)
    if (lineMatch) {
      return {
        label: lineMatch[1],
        seconds: parseSeconds(lineMatch[1], lineMatch[2]),
      }
    }
  }

  return null
}

function findImage(lines: string[]) {
  for (const line of lines) {
    const imageMatch = line.match(IMAGE_RE)
    if (imageMatch) {
      return resolveContentUrl(imageMatch[1])
    }
  }

  return undefined
}

function findExcerpt(lines: string[]) {
  for (const line of lines) {
    if (!line.trim() || IMAGE_RE.test(line)) {
      continue
    }

    const excerpt = stripMarkdown(line)
    if (excerpt) {
      return excerpt.length > 140 ? `${excerpt.slice(0, 137)}...` : excerpt
    }
  }

  return undefined
}

function parseSeconds(label: string, href: string) {
  const queryMatch = href.match(/[?&](?:t|start|time_continue)=(\d+)/)
  if (queryMatch) {
    return Number.parseInt(queryMatch[1], 10)
  }

  const [minutes, seconds] = label.split(':').map((value) => Number.parseInt(value, 10))
  return minutes * 60 + seconds
}

function stripMarkdown(text: string) {
  return text
    .replace(TIMESTAMP_LINK_RE, '$1')
    .replace(/\[([^\]]+)]\([^)]+\)/g, '$1')
    .replace(/[*_`>#]/g, ' ')
    .replace(/!\[[^\]]*]\([^)]+\)/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function slugifyHeading(text: string) {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, '')
    .replace(/\s+/g, '-')
}

export function NoteEditor() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { copy, locale } = useI18n()
  const { loadNoteById, updateNote, deleteNote, createShareLink, getShareLink, disableShareLink } = useNoteLibraryStore()
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const deleteButtonRef = useRef<HTMLButtonElement>(null)
  const zh = locale.startsWith('zh')
  const workspaceRef = useRef<HTMLDivElement | null>(null)
  const previewRef = useRef<HTMLDivElement | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>('split')
  const [editorWidth, setEditorWidth] = useState(40)
  const [localTitle, setLocalTitle] = useState('')
  const [content, setContent] = useState('')
  const [videoUrl, setVideoUrl] = useState('')
  const [taskId, setTaskId] = useState('')
  const [sourceType, setSourceType] = useState('')
  const [noteScope, setNoteScope] = useState<'personal' | 'team'>('personal')
  const [noteWorkspaceName, setNoteWorkspaceName] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [shareLoading, setShareLoading] = useState(false)
  const [shareState, setShareState] = useState<NoteShareRecord | null>(null)
  const [shareMessage, setShareMessage] = useState('')
  const [shareError, setShareError] = useState('')
  const [sharePanelOpen, setSharePanelOpen] = useState(false)
  const [error, setError] = useState('')
  const [currentNote, setCurrentNote] = useState<NoteRecord | null>(null)
  const [currentTimestamp, setCurrentTimestamp] = useState(0)
  const [jumpRequestId, setJumpRequestId] = useState(0)
  const [keyMoments, setKeyMoments] = useState<KeyMoment[]>([])
  const [transcriptEvidence, setTranscriptEvidence] = useState<TranscriptEvidence | null>(null)
  const [transcriptLoading, setTranscriptLoading] = useState(false)
  const [transcriptTextMode, setTranscriptTextMode] = useState<TranscriptTextMode>('clean')

  const noteView: NoteView = searchParams.get('view') === 'transcript' ? 'transcript' : 'summary'
  const activeMoment = findActiveKeyMoment(keyMoments, currentTimestamp)
  const [recordingDeleted, setRecordingDeleted] = useState(false)
  useEffect(() => setRecordingDeleted(false), [id])
  const localMediaUrl = id && taskId && !recordingDeleted ? `/api/notes/${id}/media` : undefined
  const isAudioNote = Boolean(localMediaUrl) && ['audio', 'meeting_recording'].includes(sourceType)
  const isVideoNote = Boolean(localMediaUrl) && ['video', 'meeting_video'].includes(sourceType)
  const splitLabel = locale.startsWith('zh') ? '对照' : 'Split'
  const workspaceBadge = noteScope === 'team'
    ? noteWorkspaceName || (locale.startsWith('zh') ? '团队笔记' : 'Team note')
    : (locale.startsWith('zh') ? '个人笔记' : 'Personal note')
  const shareUrl = shareState?.shareEnabled ? shareState.shareUrl : undefined
  const shareCopy = {
    title: locale.startsWith('zh') ? '分享链接' : 'Share link',
    description: locale.startsWith('zh')
      ? '生成一个后端托管的公开链接，局域网内的其他设备可以直接打开。'
      : 'Create a backend-hosted public link that other devices on your LAN can open directly.',
    create: locale.startsWith('zh') ? '创建链接' : 'Create link',
    copy: locale.startsWith('zh') ? '复制链接' : 'Copy link',
    disable: 'Disable sharing',
    disabled: 'Sharing is currently disabled.',
    created: locale.startsWith('zh') ? '分享链接已创建' : 'Share link created',
    copied: locale.startsWith('zh') ? '分享链接已复制到剪贴板' : 'Share link copied to clipboard',
    copyBlocked: locale.startsWith('zh')
      ? '浏览器阻止了剪贴板访问，请手动复制下方链接。'
      : 'Clipboard access is blocked in this browser. Copy the link below manually.',
    createFailed: locale.startsWith('zh') ? '创建分享链接失败' : 'Failed to create share link',
    disableFailed: 'Failed to disable sharing',
    disabledSuccess: 'Sharing disabled. The old link is no longer accessible.',
  }

  useEffect(() => {
    let active = true

    async function loadNote() {
      if (!id) {
        setError(copy.noteEditor.missingId)
        setLoading(false)
        return
      }

      const note = await loadNoteById(id)
      if (!active) {
        return
      }

      if (!note) {
        setError(copy.noteEditor.notFound)
        setLoading(false)
        return
      }

      setLocalTitle(note.title)
      setContent(note.content)
      setVideoUrl(note.videoUrl || '')
      setTaskId(note.taskId || '')
      setSourceType(note.sourceType || '')
      setNoteScope(note.scope)
      setNoteWorkspaceName(note.teamName || '')
      setCurrentNote(note)
      setError('')
      setLoading(false)

      const existingShare = await getShareLink(note.id)
      if (!active || !existingShare) {
        return
      }

      setShareState(existingShare)
    }

    void loadNote()

    return () => {
      active = false
    }
  }, [copy.noteEditor.missingId, copy.noteEditor.notFound, getShareLink, id, loadNoteById])

  useEffect(() => {
    setKeyMoments(deriveKeyMoments(content))
  }, [content])

  useEffect(() => {
    let active = true

    async function loadTranscript() {
      if (!id || !taskId) {
        setTranscriptEvidence(null)
        return
      }
      setTranscriptLoading(true)
      try {
        const evidence = await apiJson<TranscriptEvidence>(`/api/notes/${id}/transcript`)
        if (active) setTranscriptEvidence(evidence)
      } catch {
        if (active) setTranscriptEvidence(null)
      } finally {
        if (active) setTranscriptLoading(false)
      }
    }

    void loadTranscript()
    return () => {
      active = false
    }
  }, [id, taskId])

  const handleSave = async () => {
    if (!id) {
      return
    }

    setSaving(true)
    const updated = await updateNote(id, localTitle, content)
    if (!updated) {
      setError(copy.noteEditor.saveFailed)
      setSaving(false)
      return
    }

    setLocalTitle(updated.title)
    setContent(updated.content)
    setError('')
    setSaving(false)
  }

  const copyShareUrl = async (url: string, options?: { silentFailure?: boolean }) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url)
        setShareMessage(shareCopy.copied)
        setShareError('')
        return true
      }
    } catch (copyError) {
      console.error('Failed to copy share url:', copyError)
    }

    if (options?.silentFailure) {
      setShareMessage(shareCopy.copyBlocked)
    } else {
      setShareMessage(shareCopy.copyBlocked)
    }
    setShareError('')
    return false
  }

  const handleShare = async () => {
    if (!id) {
      return
    }

    setSharePanelOpen(true)
    setShareLoading(true)
    setShareMessage('')
    setShareError('')

    const nextShareState = await createShareLink(id)
    setShareLoading(false)

    const nextShareUrl = nextShareState?.shareUrl

    if (!nextShareState?.shareEnabled || !nextShareUrl) {
      setShareError(shareCopy.createFailed)
      return
    }

    setShareState(nextShareState)
    setShareMessage(shareCopy.created)
    await copyShareUrl(nextShareUrl, { silentFailure: true })
  }

  const handleDisableShare = async () => {
    if (!id) {
      return
    }

    setShareLoading(true)
    setShareMessage('')
    setShareError('')

    const nextShareState = await disableShareLink(id)
    setShareLoading(false)

    if (!nextShareState) {
      setShareError(shareCopy.disableFailed)
      return
    }

    setShareState(nextShareState)
    setShareMessage(shareCopy.disabledSuccess)
  }

  const handleShareButtonClick = async () => {
    if (shareUrl) {
      setSharePanelOpen(true)
      setShareMessage('')
      setShareError('')
      return
    }

    await handleShare()
  }

  const handleExport = () => {
    const baseTitle = localTitle.trim() || 'note'
    const exportingTranscript = noteView === 'transcript' && Boolean(transcriptEvidence?.segments.length)
    const payload = exportingTranscript && transcriptEvidence
      ? renderTranscriptMarkdown(transcriptEvidence, transcriptTextMode)
      : content
    const blob = new Blob([payload], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = exportingTranscript ? `${baseTitle}.transcript.md` : `${baseTitle}.md`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const scrollPreviewToAnchor = (anchorId: string) => {
    const escape = window.CSS?.escape ?? ((value: string) => value)
    const target = previewRef.current?.querySelector<HTMLElement>(`#${escape(anchorId)}`)
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const jumpToTimestamp = (seconds: number, anchorId?: string) => {
    setCurrentTimestamp(seconds)
    setJumpRequestId((value) => value + 1)

    if (isAudioNote && audioRef.current) {
      audioRef.current.currentTime = seconds
      void audioRef.current.play().catch(() => {
        // The seek remains valid when autoplay is blocked.
      })
      return
    }
    if (isVideoNote && videoRef.current) {
      videoRef.current.currentTime = seconds
      void videoRef.current.play().catch(() => {
        // The seek remains valid when autoplay is blocked.
      })
      return
    }

    if (workspaceMode === 'write') {
      setWorkspaceMode('preview')
    }

    if (anchorId) {
      requestAnimationFrame(() => {
        scrollPreviewToAnchor(anchorId)
      })
    }
  }

  const handleSelectMoment = (moment: KeyMoment) => {
    jumpToTimestamp(moment.seconds, moment.anchorId)
  }

  const setNoteView = (view: NoteView) => {
    const next = new URLSearchParams(searchParams)
    next.set('view', view)
    setSearchParams(next, { replace: true })
  }

  const saveSpeakerAlias = async (speakerId: string, label: string) => {
    if (!id) return
    const result = await apiJson<{ aliases: Record<string, string> }>(`/api/notes/${id}/speakers`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ aliases: { [speakerId]: label } }),
    })
    setTranscriptEvidence((current) => current ? { ...current, aliases: result.aliases } : current)
  }

  const handleEditorResizeStart = (event: React.MouseEvent<HTMLButtonElement>) => {
    if (workspaceMode !== 'split' || !workspaceRef.current) {
      return
    }

    event.preventDefault()
    const rect = workspaceRef.current.getBoundingClientRect()

    const handlePointerMove = (moveEvent: MouseEvent) => {
      const nextWidth = ((moveEvent.clientX - rect.left) / rect.width) * 100
      setEditorWidth(clamp(nextWidth, 32, videoUrl ? 52 : 68))
    }

    const handlePointerUp = () => {
      document.removeEventListener('mousemove', handlePointerMove)
      document.removeEventListener('mouseup', handlePointerUp)
    }

    document.addEventListener('mousemove', handlePointerMove)
    document.addEventListener('mouseup', handlePointerUp)
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-primary-light"></div>
      </div>
    )
  }

  if (error && !content) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
        <p className="text-lg font-medium">{error}</p>
        <button
          type="button"
          onClick={() => navigate('/notes')}
          className="rounded-lg border border-gray-200 px-4 py-2 dark:border-gray-700"
        >
          {copy.noteEditor.backToLibrary}
        </button>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col bg-[#f1efe8] dark:bg-[#0f0f0f]">
      {id && ['meeting_recording', 'meeting_video'].includes(sourceType) && <SavedRecordingActions key={id} noteId={id} title={localTitle} onDeleted={() => setRecordingDeleted(true)} />}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-gray-200 px-4 py-3 dark:border-gray-800">
        <div className="flex min-w-0 items-center gap-3">
          <button
            onClick={() => navigate('/notes')}
            className="rounded-xl p-2 hover:bg-white/80 dark:hover:bg-[#1b1b1b]"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={localTitle}
                onChange={(event) => setLocalTitle(event.target.value)}
                placeholder={copy.noteEditor.untitled}
                className="w-full min-w-[220px] border-none bg-transparent text-lg font-semibold outline-none focus:ring-0"
              />
              {currentNote ? (
                <RecordingRetryBar
                  note={currentNote}
                  onUpdated={(updated) => {
                    setCurrentNote(updated)
                    setLocalTitle(updated.title)
                    setContent(updated.content)
                    setTaskId(updated.taskId || '')
                  }}
                />
              ) : null}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              <span className="mr-2 inline-flex rounded-full bg-white/70 px-2 py-0.5 text-[11px] font-medium text-gray-600 dark:bg-[#1a1a1a] dark:text-gray-300">
                {workspaceBadge}
              </span>
              {keyMoments.length} key moments with direct timestamp jumps
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className={`flex rounded-xl bg-white/80 p-1 shadow-sm dark:bg-[#1a1a1a] ${noteView === 'transcript' ? 'invisible' : ''}`}>
            <button
              type="button"
              onClick={() => setWorkspaceMode('write')}
              className={`rounded-lg px-3 py-1.5 text-sm transition ${
                workspaceMode === 'write' ? 'bg-primary-light text-white dark:bg-primary-dark' : 'text-gray-600 dark:text-gray-300'
              }`}
            >
              <span className="inline-flex items-center gap-1">
                <Edit3 className="h-4 w-4" />
                {copy.common.edit}
              </span>
            </button>
            <button
              type="button"
              onClick={() => setWorkspaceMode('split')}
              className={`rounded-lg px-3 py-1.5 text-sm transition ${
                workspaceMode === 'split' ? 'bg-primary-light text-white dark:bg-primary-dark' : 'text-gray-600 dark:text-gray-300'
              }`}
            >
              {splitLabel}
            </button>
            <button
              type="button"
              onClick={() => setWorkspaceMode('preview')}
              className={`rounded-lg px-3 py-1.5 text-sm transition ${
                workspaceMode === 'preview' ? 'bg-primary-light text-white dark:bg-primary-dark' : 'text-gray-600 dark:text-gray-300'
              }`}
            >
              <span className="inline-flex items-center gap-1">
                <Eye className="h-4 w-4" />
                {copy.common.preview}
              </span>
            </button>
          </div>

          <div className="flex w-[220px] rounded-xl bg-white/80 p-1 shadow-sm dark:bg-[#1a1a1a]" data-testid="note-view-switcher">
            <button
              type="button"
              onClick={() => setNoteView('summary')}
              className={`flex flex-1 items-center justify-center gap-1 rounded-lg px-3 py-1.5 text-sm ${
                noteView === 'summary' ? 'bg-primary-light text-white dark:bg-primary-dark' : 'text-gray-600 dark:text-gray-300'
              }`}
            >
              <FileText className="h-4 w-4" />
              Summary
            </button>
            <button
              type="button"
              onClick={() => setNoteView('transcript')}
              className={`flex flex-1 items-center justify-center gap-1 rounded-lg px-3 py-1.5 text-sm ${
                noteView === 'transcript' ? 'bg-primary-light text-white dark:bg-primary-dark' : 'text-gray-600 dark:text-gray-300'
              }`}
            >
              <MessageSquare className="h-4 w-4" />
              Transcript
            </button>
          </div>

          <button
            onClick={() => void handleSave()}
            className="rounded-xl bg-white/80 p-2 shadow-sm hover:bg-white dark:bg-[#1a1a1a] dark:hover:bg-[#232323]"
            title={saving ? copy.noteEditor.saving : copy.noteEditor.save}
          >
            <Save className="h-5 w-5" />
          </button>
          <button
            onClick={handleExport}
            className="rounded-xl bg-white/80 p-2 shadow-sm hover:bg-white dark:bg-[#1a1a1a] dark:hover:bg-[#232323]"
            title={copy.noteEditor.export}
          >
            <Download className="h-5 w-5" />
          </button>
          <button
            onClick={() => void handleShareButtonClick()}
            className="rounded-xl bg-white/80 p-2 shadow-sm hover:bg-white dark:bg-[#1a1a1a] dark:hover:bg-[#232323]"
            title={copy.noteEditor.share}
          >
            <Share2 className="h-5 w-5" />
          </button>
          <button ref={deleteButtonRef} onClick={() => { setDeleteError(''); setDeleteOpen(true) }} title={zh ? '删除笔记' : 'Delete note'} aria-label={zh ? '删除笔记' : 'Delete note'} className="rounded-xl bg-white/80 p-2 text-red-600 shadow-sm hover:bg-red-50 dark:bg-[#1a1a1a] dark:text-red-400 dark:hover:bg-red-950/30">
            <Trash2 className="h-5 w-5" />
          </button>
        </div>
      </div>

      {deleteOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div role="alertdialog" aria-modal="true" aria-labelledby="delete-note-title" aria-describedby="delete-note-description" className="w-full max-w-md space-y-4 rounded-2xl bg-white p-6 shadow-xl dark:bg-[#1b1b1b]" onKeyDown={event => {
            if (event.key === 'Escape' && !deleting) { setDeleteOpen(false); deleteButtonRef.current?.focus() }
            if (event.key === 'Tab') {
              const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'))
              const first = buttons[0], last = buttons[buttons.length - 1]
              if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
              else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
            }
          }}>
            <h2 id="delete-note-title" className="text-lg font-semibold">{zh ? '删除笔记？' : 'Delete this note?'}</h2>
            <p id="delete-note-description" className="text-sm leading-6 text-gray-500 dark:text-gray-400">{zh ? `将删除“${localTitle}”，此操作不可撤销，未保存的修改也会丢失。` : `“${localTitle}” will be deleted permanently, including any unsaved changes.`}</p>
            {deleteError && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{deleteError}</p>}
            <div className="flex justify-end gap-3">
              <button autoFocus disabled={deleting} onClick={() => { setDeleteOpen(false); deleteButtonRef.current?.focus() }} className="rounded-xl border border-gray-200 px-4 py-2 text-sm hover:bg-gray-100 disabled:opacity-60 dark:border-gray-700 dark:hover:bg-gray-800">{zh ? '取消' : 'Cancel'}</button>
              <button disabled={deleting || !id} onClick={async () => {
                if (!id) return
                setDeleting(true); setDeleteError('')
                try { await deleteNote(id); navigate('/notes', { replace: true }) }
                catch (cause) { setDeleteError(cause instanceof Error ? cause.message : (zh ? '删除失败，请重试' : 'Could not delete note. Please retry.')) }
                finally { setDeleting(false) }
              }} className="rounded-xl bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60">{deleting ? (zh ? '删除中…' : 'Deleting…') : (zh ? '确认删除' : 'Confirm deletion')}</button>
            </div>
          </div>
        </div>
      )}
      {error ? (
        <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-600 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-300">
          {error}
        </div>
      ) : null}

      {sharePanelOpen ? (
        <div className="border-b border-sky-200 bg-sky-50/80 px-4 py-3 text-sm text-sky-900 dark:border-sky-900/40 dark:bg-sky-950/30 dark:text-sky-100">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="space-y-1">
              <div className="font-medium">{shareCopy.title}</div>
              <p className="text-xs text-sky-800/80 dark:text-sky-200/80">{shareCopy.description}</p>
              {shareUrl ? (
                <input
                  readOnly
                  value={shareUrl}
                  className="w-full rounded-lg border border-sky-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none dark:border-sky-900/50 dark:bg-slate-900 dark:text-slate-100 md:min-w-[420px]"
                />
              ) : (
                <p className="text-xs text-sky-800/80 dark:text-sky-200/80">{shareCopy.disabled}</p>
              )}
              {shareMessage ? (
                <p className="text-xs text-emerald-700 dark:text-emerald-300">{shareMessage}</p>
              ) : null}
              {shareError ? <p className="text-xs text-red-600 dark:text-red-300">{shareError}</p> : null}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {shareUrl ? (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      void copyShareUrl(shareUrl)
                    }}
                    disabled={shareLoading}
                    className="rounded-lg border border-sky-200 px-3 py-2 text-xs font-medium text-sky-800 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-60 dark:border-sky-800/50 dark:text-sky-100 dark:hover:bg-sky-950/50"
                  >
                    {shareCopy.copy}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDisableShare()}
                    disabled={shareLoading}
                    className="rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-700 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-60 dark:border-red-900/40 dark:text-red-300 dark:hover:bg-red-950/30"
                  >
                    {shareCopy.disable}
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => void handleShare()}
                  disabled={shareLoading}
                  className="rounded-lg bg-sky-600 px-3 py-2 text-xs font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {shareLoading ? copy.common.loading : shareCopy.create}
                </button>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {noteView === 'summary' && keyMoments.length > 0 ? (
        <div className="border-b border-gray-200 bg-white/70 px-4 py-3 xl:hidden dark:border-gray-800 dark:bg-[#151515]">
          <div className="stealth-scroll flex gap-3 overflow-x-auto">
            {keyMoments.map((moment) => (
              <button
                key={`${moment.anchorId}-${moment.seconds}`}
                type="button"
                onClick={() => handleSelectMoment(moment)}
                className={`shrink-0 rounded-xl border px-3 py-2 text-left text-sm ${
                  activeMoment?.anchorId === moment.anchorId
                    ? 'border-primary-light bg-primary-light/10 dark:border-primary-dark dark:bg-primary-dark/10'
                    : 'border-gray-200 bg-white dark:border-gray-700 dark:bg-[#1b1b1b]'
                }`}
              >
                <div className="font-medium">{moment.timestampLabel}</div>
                <div className="mt-1 max-w-[180px] truncate text-xs text-gray-600 dark:text-gray-400">
                  {moment.title}
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {noteView === 'summary' ? (
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <KeyMomentsRail
          moments={keyMoments}
          activeAnchorId={activeMoment?.anchorId}
          onSelectMoment={handleSelectMoment}
        />

        <div className="flex min-w-0 flex-1 overflow-hidden" ref={workspaceRef}>
          {workspaceMode !== 'preview' ? (
            <section
              style={workspaceMode === 'split' ? { width: `${editorWidth}%` } : undefined}
              className={`flex min-w-0 flex-col border-r border-gray-200 bg-white dark:border-gray-800 dark:bg-[#111111] ${
                workspaceMode === 'split' ? 'shrink-0' : 'flex-1'
              }`}
            >
              <div className="border-b border-gray-200 px-4 py-3 dark:border-gray-800">
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500 dark:text-gray-400">
                  Markdown
                </p>
                <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                  Keep the source editable. Timestamp links stay visible in plain text.
                </p>
              </div>
              <textarea
                value={content}
                onChange={(event) => setContent(event.target.value)}
                className="stealth-scroll min-h-0 flex-1 resize-none bg-white px-4 py-4 font-mono text-[13px] leading-6 outline-none dark:bg-[#111111]"
                placeholder={copy.noteEditor.editorPlaceholder}
              />
            </section>
          ) : null}

          {workspaceMode === 'split' ? (
            <button
              type="button"
              onMouseDown={handleEditorResizeStart}
              className="hidden w-3 shrink-0 items-stretch justify-center bg-transparent lg:flex"
              aria-label="Resize editor and preview panes"
            >
              <span className="my-6 w-1 rounded-full bg-gray-300 dark:bg-gray-700" />
            </button>
          ) : null}

          {workspaceMode !== 'write' ? (
            <section className="flex min-w-0 flex-1 flex-col bg-[#fcfbf7] dark:bg-[#181818]">
              <div className="border-b border-gray-200 px-4 py-3 dark:border-gray-800">
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500 dark:text-gray-400">
                  Preview
                </p>
                <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                  Key timestamps and screenshots should read like a guided re-watch path.
                </p>
              </div>
              <div className="flex min-h-0 flex-1 overflow-hidden">
                <div ref={previewRef} className="stealth-scroll min-w-0 flex-1 overflow-auto">
                  <MarkdownContent
                    content={content || copy.noteEditor.previewEmpty}
                    className="prose w-full max-w-none px-6 py-6 dark:prose-invert lg:px-8"
                    videoUrl={videoUrl || undefined}
                    mediaUrl={localMediaUrl}
                    onVideoJump={(seconds) => {
                      jumpToTimestamp(seconds)
                    }}
                  />
                </div>

                {videoUrl && !isVideoNote ? (
                  <div className="hidden w-[320px] shrink-0 border-l border-gray-200 bg-white/80 p-4 xl:flex dark:border-gray-800 dark:bg-[#141414]">
                    <VideoReferencePanel
                      noteId={id}
                      taskId={undefined}
                      videoUrl={videoUrl}
                      currentTimestamp={currentTimestamp}
                      jumpRequestId={jumpRequestId}
                      activeMomentTitle={activeMoment?.title}
                      className="w-full"
                      onTimestampChange={setCurrentTimestamp}
                    />
                  </div>
                ) : null}
              </div>
            </section>
          ) : null}
        </div>
      </div>
      ) : (
        <TranscriptEvidencePanel
          evidence={transcriptEvidence}
          loading={transcriptLoading}
          currentTimestamp={currentTimestamp}
          textMode={transcriptTextMode}
          onTextModeChange={setTranscriptTextMode}
          onSeek={jumpToTimestamp}
          onSaveAlias={saveSpeakerAlias}
        />
      )}

      {isAudioNote && localMediaUrl ? (
        <div className="border-t border-gray-200 bg-white px-4 py-3 dark:border-gray-800 dark:bg-[#111111]">
          <div className="mx-auto flex max-w-6xl items-center gap-3">
            <span className="shrink-0 text-sm font-medium">Audio</span>
            <audio
              ref={audioRef}
              data-testid="source-audio"
              controls
              preload="metadata"
              src={resolveContentUrl(localMediaUrl)}
              className="h-10 min-w-0 flex-1"
              onTimeUpdate={(event) => setCurrentTimestamp(event.currentTarget.currentTime)}
            />
          </div>
        </div>
      ) : null}

      {isVideoNote && localMediaUrl ? (
        <div className="border-t border-gray-200 bg-white px-4 py-3 dark:border-gray-800 dark:bg-[#111111]">
          <div className="mx-auto flex max-w-6xl items-center gap-3">
            <span className="shrink-0 text-sm font-medium">Video</span>
            <video
              ref={videoRef}
              data-testid="source-video"
              controls
              preload="metadata"
              src={resolveContentUrl(localMediaUrl)}
              className="h-28 min-w-0 flex-1 bg-black object-contain"
              onTimeUpdate={(event) => setCurrentTimestamp(event.currentTarget.currentTime)}
            />
          </div>
        </div>
      ) : null}
    </div>
  )
}
