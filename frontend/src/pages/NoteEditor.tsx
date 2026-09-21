import { Input } from '../components/ui/input'
import { Textarea } from '../components/ui/textarea'
import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Copy, Download, Edit3, Eye, FileText, MessageSquare, Trash2, Save, Share2 } from 'lucide-react'
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
import { Button } from '../components/ui/button'
import { Badge } from '../components/ui/badge'
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group'
import { Alert, AlertDescription } from '../components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '../components/ui/alert-dialog'
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '../components/ui/sheet'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '../components/ui/resizable'

type WorkspaceMode = 'write' | 'split' | 'preview'
type NoteView = 'summary' | 'transcript'

const HEADING_RE = /^(#{1,6})\s+(.*)$/
const TIMESTAMP_LINK_RE = /\[(\d{1,2}:\d{2})(?:-\d{1,2}:\d{2})?\]\(([^)]+)\)/
const IMAGE_RE = /!\[[^\]]*]\(([^)\s]+)(?:\s+"[^"]*")?\)/

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
  const previewRef = useRef<HTMLDivElement | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>('split')
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

  const selectedText = () => noteView === 'transcript' && transcriptEvidence
    ? renderTranscriptMarkdown(transcriptEvidence, transcriptTextMode) : content

  const handleCopyBody = async () => {
    try {
      await navigator.clipboard.writeText(selectedText())
    } catch {
      setError(zh ? '无法复制正文，请检查剪贴板权限或下载正文。' : 'Could not copy text. Check clipboard permission or download it.')
    }
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

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted border-t-primary"></div>
      </div>
    )
  }

  if (error && !content) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
        <p className="text-lg font-medium">{error}</p>
        <Button
          type="button"
          onClick={() => navigate('/notes')}
          variant="outline"
        >
          {copy.noteEditor.backToLibrary}
        </Button>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col bg-background">
      {id && ['meeting_recording', 'meeting_video'].includes(sourceType) && <SavedRecordingActions key={id} noteId={id} title={localTitle} onDeleted={() => setRecordingDeleted(true)} />}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b bg-background px-3 py-2">
        <div className="flex min-w-0 items-center gap-3">
          <Button
            onClick={() => navigate('/notes')}
            variant="ghost"
            size="icon"
          >
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Input
                type="text"
                value={localTitle}
                onChange={(event) => setLocalTitle(event.target.value)}
                placeholder={copy.noteEditor.untitled}
                className="h-8 w-full min-w-[220px] border-none bg-transparent px-0 text-base font-semibold shadow-none focus-visible:ring-0"
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
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Badge variant="secondary">{workspaceBadge}</Badge>
              {keyMoments.length} {zh ? '个可跳转关键时刻' : 'key moments'}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <ToggleGroup type="single" value={workspaceMode} onValueChange={value => value && setWorkspaceMode(value as WorkspaceMode)} className={noteView === 'transcript' ? 'invisible' : ''}>
            <ToggleGroupItem value="write"><Edit3 />{copy.common.edit}</ToggleGroupItem>
            <ToggleGroupItem value="split">{splitLabel}</ToggleGroupItem>
            <ToggleGroupItem value="preview"><Eye />{copy.common.preview}</ToggleGroupItem>
          </ToggleGroup>

          <ToggleGroup type="single" value={noteView} onValueChange={value => value && setNoteView(value as NoteView)} data-testid="note-view-switcher">
            <ToggleGroupItem value="summary"><FileText />{zh ? '纪要' : 'Summary'}</ToggleGroupItem>
            <ToggleGroupItem value="transcript"><MessageSquare />{zh ? '逐字稿' : 'Transcript'}</ToggleGroupItem>
          </ToggleGroup>
          <Button
            onClick={() => void handleCopyBody()} variant="outline" size="icon"
            title={zh ? '复制正文' : 'Copy text'} aria-label={zh ? '复制正文' : 'Copy text'}
          ><Copy className="size-5" /></Button>
          <Button
            onClick={() => void handleSave()}
            variant="outline" size="icon"
            title={saving ? copy.noteEditor.saving : copy.noteEditor.save}
          >
            <Save className="h-5 w-5" />
          </Button>
          <Button
            onClick={handleExport}
            variant="outline" size="icon"
            title={copy.noteEditor.export}
          >
            <Download className="h-5 w-5" />
          </Button>
          <Button
            onClick={() => void handleShareButtonClick()}
            variant="outline" size="icon"
            title={copy.noteEditor.share}
          >
            <Share2 className="h-5 w-5" />
          </Button>
          <Button ref={deleteButtonRef} onClick={() => { setDeleteError(''); setDeleteOpen(true) }} title={zh ? '删除笔记' : 'Delete note'} aria-label={zh ? '删除笔记' : 'Delete note'} variant="outline" size="icon" className="text-destructive">
            <Trash2 className="h-5 w-5" />
          </Button>
        </div>
      </div>

      <AlertDialog open={deleteOpen} onOpenChange={open => { if (!deleting) setDeleteOpen(open) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{zh ? '删除笔记？' : 'Delete this note?'}</AlertDialogTitle>
            <AlertDialogDescription>{zh ? `将永久删除“${localTitle}”，未保存的修改也会丢失。` : `“${localTitle}” and any unsaved changes will be permanently deleted.`}</AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError ? <Alert variant="destructive"><AlertDescription>{deleteError}</AlertDescription></Alert> : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>{zh ? '取消' : 'Cancel'}</AlertDialogCancel>
            <AlertDialogAction disabled={deleting || !id} className="bg-destructive text-destructive-foreground hover:bg-destructive/90" onClick={async event => {
                if (!id) return
                event.preventDefault()
                setDeleting(true); setDeleteError('')
                try { await deleteNote(id); navigate('/notes', { replace: true }) }
                catch (cause) { setDeleteError(cause instanceof Error ? cause.message : (zh ? '删除失败，请重试' : 'Could not delete note. Please retry.')) }
                finally { setDeleting(false) }
              }}>{deleting ? (zh ? '删除中…' : 'Deleting…') : (zh ? '确认删除' : 'Confirm deletion')}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {error ? (
        <Alert variant="destructive" className="rounded-none border-x-0 border-t-0"><AlertDescription>{error}</AlertDescription></Alert>
      ) : null}

      <Sheet open={sharePanelOpen} onOpenChange={setSharePanelOpen}>
        <SheetContent className="flex w-full flex-col sm:max-w-md">
          <SheetHeader>
            <SheetTitle>{shareCopy.title}</SheetTitle>
            <SheetDescription>{shareCopy.description}</SheetDescription>
          </SheetHeader>
          <div className="grid flex-1 content-start gap-4 py-6">
              {shareUrl ? (
                <Input
                  readOnly
                  value={shareUrl}
                  className="font-mono text-xs"
                />
              ) : (
                <p className="text-sm text-muted-foreground">{shareCopy.disabled}</p>
              )}
              {shareMessage ? <Alert><AlertDescription>{shareMessage}</AlertDescription></Alert> : null}
              {shareError ? <Alert variant="destructive"><AlertDescription>{shareError}</AlertDescription></Alert> : null}
          </div>
          <SheetFooter className="gap-2">
              {shareUrl ? (
                <>
                  <Button type="button" variant="outline" onClick={() => void handleDisableShare()} disabled={shareLoading} className="text-destructive">{shareCopy.disable}</Button>
                  <Button type="button" onClick={() => void copyShareUrl(shareUrl)} disabled={shareLoading}>{shareCopy.copy}</Button>
                </>
              ) : (
                <Button type="button" onClick={() => void handleShare()} disabled={shareLoading}>{shareLoading ? copy.common.loading : shareCopy.create}</Button>
              )}
          </SheetFooter>
        </SheetContent>
      </Sheet>

      {noteView === 'summary' && keyMoments.length > 0 ? (
        <div className="border-b border-border bg-card/70 px-4 py-3 xl:hidden">
          <div className="stealth-scroll flex gap-3 overflow-x-auto">
            {keyMoments.map((moment) => (
              <Button
                key={`${moment.anchorId}-${moment.seconds}`}
                type="button"
                onClick={() => handleSelectMoment(moment)}
                className={`shrink-0 rounded-xl border px-3 py-2 text-left text-sm ${
                  activeMoment?.anchorId === moment.anchorId
                    ? 'border-primary bg-primary/10'
                    : 'border-border bg-card'
                }`}
              >
                <div className="font-medium">{moment.timestampLabel}</div>
                <div className="mt-1 max-w-[180px] truncate text-xs text-muted-foreground dark:text-muted-foreground">
                  {moment.title}
                </div>
              </Button>
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

        <ResizablePanelGroup direction="horizontal" className="min-w-0 flex-1">
          {workspaceMode !== 'preview' ? (
            <ResizablePanel defaultSize={workspaceMode === 'split' ? 42 : 100} minSize={30} className="flex min-w-0 flex-col bg-card">
              <div className="border-b px-4 py-2 text-xs font-medium text-muted-foreground">Markdown</div>
              <Textarea
                value={content}
                onChange={(event) => setContent(event.target.value)}
                className="stealth-scroll min-h-0 flex-1 resize-none bg-card px-4 py-4 font-mono text-[13px] leading-6 outline-none"
                placeholder={copy.noteEditor.editorPlaceholder}
              />
            </ResizablePanel>
          ) : null}

          {workspaceMode === 'split' ? <ResizableHandle withHandle /> : null}

          {workspaceMode !== 'write' ? (
            <ResizablePanel defaultSize={workspaceMode === 'split' ? 58 : 100} minSize={32} className="flex min-w-0 flex-col bg-muted/20">
              <div className="border-b px-4 py-2 text-xs font-medium text-muted-foreground">{zh ? '预览' : 'Preview'}</div>
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
                  <div className="hidden w-[320px] shrink-0 border-l border-border bg-card/80 p-4 xl:flex dark:border-border ">
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
            </ResizablePanel>
          ) : null}
        </ResizablePanelGroup>
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
        <div className="border-t border-border bg-card px-4 py-3 dark:border-border ">
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
        <div className="border-t border-border bg-card px-4 py-3 dark:border-border ">
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
