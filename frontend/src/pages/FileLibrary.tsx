import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { FileAudio, FileVideo, FileText, Upload, RefreshCw } from 'lucide-react'
import { apiJson } from '@/lib/api'
import { resolveContentUrl } from '@/lib/videoLinks'
import { serverTimestamp } from '@/lib/serverTimestamp'
import { listPendingMeetings, type PendingMeeting } from '@/lib/audioStorage'
import { useAuthStore } from '@/stores/authStore'
import { useTeamStore } from '@/stores/teamStore'
import { useMeetingDisplay } from '@/hooks/useMeetingDisplay'
import { useViewState } from '@/hooks/useViewState'
import { OriginalDownloadButton } from '@/components/OriginalDownloadButton'
import { LocalRecordingPreview } from '@/components/MeetingRecorder/LocalRecordingPreview'
import { PageReturn } from '@/components/Layout/PageReturn'
import { resolvePageParent, pageParentLabel } from '@/lib/navigation'
import { PageHeading } from '@/components/Layout/PageHeading'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter } from '@/components/ui/alert-dialog'
import { ErrorState, LoadingState, EmptyState } from '@/components/Feedback/ResourceState'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { originalPurpose, fileGenerationPath, purposeLabel, originalFormat, formatFilter, type FilePurpose, type FilePurposeView } from '@/lib/filePurpose'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { versionHistoryTitle } from '@/lib/meetingVersionHistory'
import { taskDisplayTitle } from '@/lib/taskDisplay'
import { RelatedSummaryTasks } from '@/components/Notes/RelatedSummaryTasks'

type StoredFile = { id: string; filename: string; purpose?: FilePurposeView; source_type?: string; processing_status?: string; error_code?: string; retryable?: boolean; title?: string; category: string; size_bytes: number; created_at: string; available: boolean; note_id?: string; task_id?: string; content_url: string; location: string; media_type: string; can_delete: boolean; can_generate: boolean }
type FileRow = { id: string; title: string; category: string; purpose: FilePurposeView; date: string; recording?: PendingMeeting; file?: StoredFile }
const isMeetingOriginal = (file: StoredFile) => originalPurpose(file) === 'meeting' || file.source_type?.startsWith('meeting_')
const categories = [{ id: 'all', label: '全部' }, { id: 'audio', label: '音频' }, { id: 'video', label: '视频' }, { id: 'document', label: '文档' }]
const formatLabel = (category: string) => categories.find(item => item.id === originalFormat(category))!.label
const sourceBadge = (row: FileRow) => row.category === 'screen' ? '录屏' : row.category === 'video' && row.file ? '导入视频' : row.recording ? '录音' : ''
const fileSize = (bytes: number) => bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`
const fileFormat = (row: FileRow) => row.file?.filename.split('.').pop()?.toUpperCase() || formatLabel(row.category)
const fileLocation = (file?: StoredFile) => file?.location?.replace(/\s*·\s*已保留来源/g, '') || '当前设备'
const recordingDuration = (seconds: number) => { const total = Math.max(0, Math.round(seconds)); return `${Math.floor(total / 60)} 分 ${total % 60} 秒` }
const fileDate = (row: FileRow) => {
  const date = row.file ? serverTimestamp(row.date) : new Date(row.date)
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : '时间未记录'
}
const playbackSource = (source: string) => {
  const url = new URL(source, 'https://vinote.invalid')
  url.searchParams.delete('download'); url.searchParams.set('playback', 'true')
  return resolveContentUrl(source.startsWith('/') ? url.pathname + url.search + url.hash : url.toString())
}

export function FileLibrary({ scope }: { scope?: 'meeting' | 'note' }) {
  const owner = useAuthStore(s => s.user?.id)
  const navigate = useNavigate()
  const location = useLocation()
  const [savedQuery, saveQuery] = useViewState('files-query', '')
  const [params, setParams] = useSearchParams()
  const [savedCategory, saveCategory] = useViewState('files-category', 'all')
  const [savedPurpose, savePurpose] = useViewState<FilePurposeView>('files-purpose', 'meeting')
  const routePurpose = params.get('purpose')
  const purpose: FilePurposeView = scope || (['meeting', 'note', 'unknown'].includes(routePurpose || '') ? routePurpose as FilePurposeView : ['meeting', 'note', 'unknown'].includes(savedPurpose) ? savedPurpose : 'meeting')
  const sourceNote = params.get('note') || ''
  const display = useMeetingDisplay(purpose === 'meeting' ? owner : undefined)
  const routeCategory = params.get('type')
  const category = formatFilter(routeCategory !== null ? routeCategory : sourceNote ? 'all' : savedCategory)
  const query = params.has('q') ? params.get('q')! : sourceNote ? '' : savedQuery
  const updateQuery = (value: string) => { saveQuery(value); setParams(current => { const next = new URLSearchParams(current); next.set('q', value); return next }, { replace: true, state: location.state }) }
  const parent = resolvePageParent(location.state?.returnTo || params.get('returnTo'), scope === 'meeting' ? '/meetings' : scope === 'note' ? '/notes' : '/files')
  const returnParams = new URLSearchParams(params); returnParams.set('type', category); returnParams.set('q', query)
  if (!sourceNote) returnParams.set('purpose', purpose)
  if (parent.split(/[?#]/)[0] !== '/files') returnParams.set('returnTo', parent)
  const returnTo = location.pathname + '?' + returnParams.toString() + location.hash
  const setCategory = (value: string) => {
    saveCategory(value)
    setParams(current => { const next = new URLSearchParams(current); next.set('type', value); next.delete('file'); return next }, { state: location.state })
  }
  const setPurpose = (value: FilePurposeView) => {
    savePurpose(value); saveCategory('all'); saveQuery('')
    setParams(current => { const next = new URLSearchParams(current); next.set('purpose', value); next.set('type', 'all'); next.set('q', ''); next.delete('file'); return next }, { state: location.state })
  }
  const [importOpen, setImportOpen] = useState(false)
  const importIntent = useRef<{ owner: string; purpose: FilePurpose } | null>(null)
  const [storedRows, setRows] = useState<FileRow[]>([]), [selected, setSelected] = useState<FileRow | null>(null)
  const rows = useMemo(() => storedRows.map(row => {
    if (row.purpose !== 'meeting') return row
    const task = row.file?.task_id || row.recording?.taskId
    const metadata = (task ? display[`task:${task}`] : undefined) || display[`file:${row.id}`]
    const fallback = row.file && row.title === row.file.filename ? '未命名会议' : row.title
    return { ...row, title: metadata?.title || (metadata ? '' : row.recording?.displayTitle) || fallback }
  }), [storedRows, display])
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [deletion, setDeletion] = useState<StoredFile | null>(null)
  const deletionContext = useRef<{ owner: string; route: string } | null>(null)
  const restoreDeletionFocus = useRef(false)
  const deleteButton = useRef<HTMLButtonElement>(null)
  const detailTitle = useRef<HTMLHeadingElement>(null)
  const [mediaError, setMediaError] = useState(false), [mediaAttempt, setMediaAttempt] = useState(0)
  useEffect(() => { setMediaError(false); setMediaAttempt(0) }, [selected?.id])
  const input = useRef<HTMLInputElement>(null), epoch = useRef(0)
  const load = useCallback(async () => {
    const run = ++epoch.current
    if (!owner) { setLoading(false); return }
    setLoading(true); setError('')
    const result = await Promise.allSettled([listPendingMeetings(owner), apiJson<{ items: StoredFile[] }>('/api/files')])
    if (run !== epoch.current || useAuthStore.getState().user?.id !== owner) return
    setRows(previous => {
      const recordings = result[0].status === 'fulfilled' ? result[0].value : previous.flatMap(row => row.recording ? [row.recording] : [])
      const files = result[1].status === 'fulfilled' ? result[1].value.items : previous.flatMap(row => row.file ? [row.file] : [])
      const localTasks = new Set(recordings.map(r => r.taskId).filter(Boolean))
      return [
        ...recordings.map(r => ({ id: 'recording:' + r.id, title: versionHistoryTitle(r.options.title || '未命名录制'), purpose: 'meeting' as const, category: r.options.screen || r.options.meetingType === 'video' ? 'screen' : 'recording', date: r.startedAt, recording: r })),
        ...files.filter(f => !f.task_id || !localTasks.has(f.task_id)).map(f => ({ id: f.id, title: originalPurpose(f) === 'meeting' ? versionHistoryTitle(f.title || f.filename) : f.title || f.filename, purpose: originalPurpose(f), category: f.category, date: f.created_at, file: f })),
      ].sort((a, b) => b.date.localeCompare(a.date))
    })
    const failures = result.filter(r => r.status === 'rejected').length
    if (failures) setError('部分文件未读取成功。已读取的文件仍可使用，请重试。')
    setLoading(false)
  }, [owner])
  useEffect(() => { setRows([]); setSelected(null); setDeletion(null); setBusy(false); setImportOpen(false); importIntent.current = null; deletionContext.current = null; restoreDeletionFocus.current = false; void load(); return () => { epoch.current++ } }, [load])
  const closeDetails = () => { setSelected(null); setParams(current => { const next = new URLSearchParams(current); next.delete('file'); return next }, { replace: true, state: location.state }) }
  const openDetails = (row: FileRow) => { setSelected(row); setParams(current => { const next = new URLSearchParams(current); next.set('type', category); next.set('q', query); if (!sourceNote) next.set('purpose', row.purpose); next.set('file', row.id); return next }, { replace: true, state: location.state }) }
  const beginDeletion = (file: StoredFile) => {
    if (!owner || useAuthStore.getState().user?.id !== owner || isMeetingOriginal(file)) return
    deletionContext.current = { owner, route: location.pathname + location.search + location.hash }
    // Keep the selection in the URL; the confirmation temporarily replaces its Sheet.
    setError(''); setDeletion(file)
  }
  const cancelDeletion = () => {
    if (busy) return
    const context = deletionContext.current
    const canRestore = !!context && context.owner === useAuthStore.getState().user?.id
      && context.route === location.pathname + location.search + location.hash
      && selected?.id === deletion?.id
    restoreDeletionFocus.current = canRestore
    setDeletion(null); setError(''); deletionContext.current = null
    if (!canRestore) closeDetails()
  }
  useEffect(() => {
    const id = params.get('file')
    if (!id) { setSelected(null); return }
    const row = rows.find(item => item.id === id)
    if (row && (!scope || row.purpose === scope) && (!sourceNote || row.file?.note_id === sourceNote || row.recording?.noteId === sourceNote)) {
      setSelected(row)
      if (!sourceNote && routePurpose !== row.purpose) setParams(current => { const next = new URLSearchParams(current); next.set('purpose', row.purpose); return next }, { replace: true, state: location.state })
    }
    else if (deletion?.id === id && useAuthStore.getState().user?.id === owner) {
      // A concurrent refresh can remove the file while confirmation is open.
      // Retain its identity, but never restore playable or destructive actions.
      setSelected(previous => previous?.id === id && previous.file
        ? { ...previous, file: { ...previous.file, available: false, can_delete: false } }
        : null)
    }
    else setSelected(null)
  }, [rows, params.get('file'), sourceNote, scope])
  const clearFilters = () => { saveCategory('all'); saveQuery(''); setParams(current => { const next = new URLSearchParams(current); next.set('type', 'all'); next.set('q', ''); return next }, { state: location.state }) }
  const [savedMessage, setSavedMessage] = useState('')
  const [copiedFilename, setCopiedFilename] = useState('')
  const chooseImport = (value: FilePurpose) => {
    if (!owner || busy) return
    if (value === 'meeting') {
      importIntent.current = null; setImportOpen(false)
      navigate(`/generate?meeting=1&intent=import&draft=${crypto.randomUUID()}`, { state: { returnTo } })
      return
    }
    importIntent.current = { owner, purpose: value }
    setImportOpen(false)
    if (input.current) { input.current.accept = '.pdf,.docx,.txt,.md,.srt,.vtt,.json,.mp3,.wav,.m4a,.flac,.ogg,.aac,.opus,.mp4,.mov,.mkv,.webm,.avi,.m4v'; input.current.click() }
  }
  const upload = async (file: File) => {
    const intent = importIntent.current
    if (!intent || intent.purpose !== 'note' || intent.owner !== owner || useAuthStore.getState().user?.id !== intent.owner) return
    setBusy(true); setError(''); setSavedMessage('')
    try { const data = new FormData(); data.append('file', file); data.append('purpose', intent.purpose); await apiJson('/api/files', { method: 'POST', body: data }); if (useAuthStore.getState().user?.id !== intent.owner) return; setPurpose(intent.purpose); await load(); setSavedMessage(`${purposeLabel(intent.purpose)}原文件已保存，尚未生成正文。`) }
    catch (cause) { if (useAuthStore.getState().user?.id === intent.owner) setError(cause instanceof Error ? cause.message : '文件保存失败，请重新选择后重试') }
    finally { if (useAuthStore.getState().user?.id === intent.owner) setBusy(false); if (input.current) input.current.value = ''; importIntent.current = null }
  }
  const reclassify = async (file: StoredFile, value: FilePurpose) => {
    if (!owner || busy || useAuthStore.getState().user?.id !== owner) return
    const expectedOwner = owner
    setBusy(true); setError('')
    try {
      const updated = await apiJson<StoredFile>(`/api/files/${encodeURIComponent(file.id)}`, { method: 'PATCH', body: JSON.stringify({ purpose: value }) })
      if (useAuthStore.getState().user?.id !== expectedOwner) return
      if (updated.id !== file.id || updated.purpose !== value) throw new Error('资料用途尚未确认，请重新读取；原文件保留。')
      setRows(current => current.map(row => row.id === file.id ? { ...row, file: updated, purpose: value } : row))
      savePurpose(value)
      setParams(current => { const next = new URLSearchParams(current); if (!sourceNote) next.set('purpose', value); return next }, { replace: true, state: location.state })
    } catch (cause) { if (useAuthStore.getState().user?.id === expectedOwner) setError(cause instanceof Error ? cause.message : '用途未保存，请重试；原文件保留。') }
    finally { if (useAuthStore.getState().user?.id === expectedOwner) setBusy(false) }
  }
  const generate = async (file: StoredFile) => {
    if (!owner || useAuthStore.getState().user?.id !== owner || busy) return
    const filePurpose = originalPurpose(file)
    if (filePurpose === 'unknown') { setError('此原件用途尚未确认，请重新读取资料信息后再整理；原文件可继续播放或导出。'); return }
    const meeting = filePurpose === 'meeting'
    const target = fileGenerationPath(filePurpose)
    setBusy(true); setError('')
    const workspace = useTeamStore.getState().currentWorkspace
    const receiptKey = `vinote:import-receipt:${owner}:${meeting ? 'meeting' : 'note'}`
    try {
      if (file.task_id) {
        if (!/^[A-Za-z0-9_-]{1,64}$/.test(file.task_id)) throw new Error('原任务标识尚不能核验，请重新读取资料。')
        const route = new URLSearchParams(target.split('?')[1] || '')
        route.set('task', file.task_id)
        setSelected(null)
        navigate(target.split('?')[0] + '?' + route, { state: { returnTo, readOnlyTask: { id: file.task_id, owner, meeting, sourceTitle: file.title || file.filename, sourceType: file.source_type, localFileId: file.id } } })
        return
      }
      // Existing uncertain intake belongs to its original request, never this new file.
      const raw = localStorage.getItem(receiptKey)
      if (raw) {
        let existing: { id?: string; operationId?: string }
        try { existing = JSON.parse(raw); if (!existing || typeof existing !== 'object' || Array.isArray(existing)) throw new Error('invalid receipt') } catch { throw new Error('已有处理记录无法读取，请先到笔记整理核验，不能覆盖原请求。') }
        if (existing.operationId || existing.id) {
          if (file.task_id && existing.id !== file.task_id) throw new Error('另一个原任务仍需核验。请先查看处理历史，当前原件与处理记录均保留。')
          navigate(target, { state: { returnTo } }); return
        }
        throw new Error('已有处理记录缺少原请求标识，请先到笔记整理核验，不能覆盖原记录。')
      }
      const task = file.task_id ? { task_id: file.task_id, source_type: undefined } : await apiJson<{ task_id: string; source_type?: string }>(`/api/files/${encodeURIComponent(file.id)}/generate`, { method: 'POST', body: JSON.stringify({ meeting }) })
      if (useAuthStore.getState().user?.id !== owner) throw new Error('账号已切换，请在原账号文件库恢复任务')
      const documentSource = /\.(pdf|docx)$/i.test(file.filename)
      localStorage.setItem(receiptKey, JSON.stringify({ id: task.task_id, workspace, sourceType: task.source_type || file.source_type || (documentSource ? 'file' : meeting ? file.media_type.startsWith('video') ? 'meeting_video' : 'meeting_recording' : file.media_type.startsWith('video') ? 'video' : file.media_type.startsWith('audio') ? 'audio' : 'text'), sourceTitle: file.title || file.filename, localFileId: file.id, mode: 'file', meeting }))
      setSelected(null); navigate(target, { state: { returnTo } })
    } catch (cause) { setError(cause instanceof Error ? cause.message : '处理尚未确认，请保留原件并核验') }
    finally { setBusy(false) }
  }
  const remove = async () => {
    if (!deletion || isMeetingOriginal(deletion)) return
    const context = deletionContext.current
    const sameContext = () => !!context && context.owner === useAuthStore.getState().user?.id
      && context.route === location.pathname + location.search + location.hash
    if (!sameContext()) { setDeletion(null); deletionContext.current = null; restoreDeletionFocus.current = false; closeDetails(); return }
    setBusy(true); setError('')
    try { await apiJson(deletion.id.startsWith('note:') ? `/api/notes/${deletion.note_id}/recording` : `/api/files/${deletion.id}`, { method: 'DELETE' }); if (!sameContext()) return; setDeletion(null); deletionContext.current = null; closeDetails(); await load() }
    catch (cause) { if (sameContext()) setError(cause instanceof Error ? cause.message : '删除失败，请停止播放后重试') }
    finally { setBusy(false) }
  }
  const purposeLocked = !!selected?.file && (!!scope || selected.file.id.startsWith('note:') || selected.file.id.startsWith('task:'))
  const scopedRows = scope ? rows.filter(row => row.purpose === scope) : rows
  const sourceRows = sourceNote ? scopedRows.filter(row => row.file?.note_id === sourceNote || row.recording?.noteId === sourceNote) : scopedRows
  const purposeRows = sourceRows.filter(row => row.purpose === purpose)
  const visible = sourceNote ? sourceRows : purposeRows.filter(r => (category === 'all' || originalFormat(r.category) === category) && `${r.title} ${r.file?.filename || ''} ${r.file?.title || r.recording?.options.title || ''}`.toLowerCase().includes(query.trim().toLowerCase()))
  const meetingDeletionPath = selected?.file ? '/meetings?' + new URLSearchParams({
    ...(selected.file.note_id ? { locate_note: selected.file.note_id } : {}),
    ...(selected.file.task_id ? { locate_task: selected.file.task_id } : {}),
    locate_focus: 'meeting', returnTo,
  }).toString() : '/meetings'
  const contentTarget = (noteId: string, row = selected, focus?: 'meeting') => {
    if (row?.purpose === 'meeting') {
      const target = new URL(parent.split(/[?#]/)[0] === '/meetings' ? parent : '/meetings', 'https://vinote.invalid')
      for (const key of ['capture', 'locate_note', 'locate_task', 'locate_recording', 'locate_focus']) target.searchParams.delete(key)
      target.searchParams.set('locate_note', noteId)
      if (focus) target.searchParams.set('locate_focus', focus)
      const taskId = row.recording?.taskId || row.file?.task_id
      if (taskId) target.searchParams.set('locate_task', taskId)
      if (row.recording) target.searchParams.set('locate_recording', row.recording.id)
      target.searchParams.set('returnTo', returnTo)
      return target.pathname + target.search + target.hash
    }
    return sourceNote === noteId && /^\/(workspace|note)\//.test(parent) ? parent : '/note/' + encodeURIComponent(noteId)
  }
  const contentState = (noteId: string, row = selected, focus?: 'meeting') => ({ returnTo, ...(row?.purpose === 'meeting' ? {
    meetingLocator: { ownerId: owner, noteId, ...(focus ? { focus } : {}), taskId: row.recording?.taskId || row.file?.task_id, recordingId: row.recording?.id },
  } : {}) })
  const fullDetail = !!scope && params.has('file')
  const detailBody = (
      <div data-testid="file-details-body" className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-6">
      {selected?.recording && <section aria-label="录制原件与关联内容" className="pt-6"><h2 className="mb-3 text-sm font-medium">录制原件与关联内容</h2><LocalRecordingPreview recording={selected.recording} onDeleted={() => { closeDetails(); void load() }} onOpenNote={id => { const target = contentTarget(id), state = contentState(id); setSelected(null); navigate(target, { state }) }} /></section>}
      {selected?.file && <div className="flex flex-col gap-6 pt-6">

        <section aria-labelledby="file-info-heading" className="grid gap-3"><h2 id="file-info-heading" className="text-sm font-medium">文件信息</h2><div className="flex flex-wrap items-center gap-2"><p className="min-w-0 break-all text-sm">{selected.file.filename}</p><Button variant="ghost" size="sm" aria-label="复制原始文件名" onClick={() => { const filename = selected.file!.filename; void Promise.resolve().then(() => navigator.clipboard.writeText(filename)).then(() => setCopiedFilename(filename)).catch(() => setError('文件名未能复制，请选中文件名手动复制。')) }}>{copiedFilename === selected.file.filename ? '已复制' : '复制文件名'}</Button></div>{purposeLocked ? <p aria-label="资料用途" className="text-sm text-muted-foreground">{purposeLabel(selected.purpose)}</p> : <><label htmlFor="original-purpose" className="text-sm">资料用途</label><NativeSelect id="original-purpose" aria-label="资料用途" value={selected.purpose} disabled={busy || selected.file.id.startsWith('note:') || selected.file.id.startsWith('task:')} onChange={event => { if (event.target.value === 'meeting' || event.target.value === 'note') void reclassify(selected.file!, event.target.value) }}><NativeSelectOption value="unknown" disabled>请选择资料用途</NativeSelectOption><NativeSelectOption value="meeting">会议资料</NativeSelectOption><NativeSelectOption value="note">笔记资料</NativeSelectOption></NativeSelect><p className="text-xs text-muted-foreground">用途只决定原件分组，不改动已有正文或版本。</p></>}<p className="text-xs leading-6 text-muted-foreground">{fileFormat(selected)} · {fileSize(selected.file.size_bytes)} · {fileDate(selected)}<br />位置：{fileLocation(selected.file)}{!selected.file.available && ' · 文件暂不可用'}</p>
          {selected.file.available && selected.file.media_type.startsWith('video/') && <video aria-label="原文件视频回放" key={selected.id + mediaAttempt} src={playbackSource(selected.file.content_url)} onError={() => setMediaError(true)} controls preload="metadata" className="w-full" />}
          {selected.file.available && selected.file.media_type.startsWith('audio/') && <audio aria-label="原文件音频回放" key={selected.id + mediaAttempt} src={playbackSource(selected.file.content_url)} onError={() => setMediaError(true)} controls preload="metadata" className="w-full" />}
          {mediaError && <div role="alert" className="text-sm"><p>播放未成功。请重试读取，或导出后在系统播放器打开。</p><Button variant="outline" onClick={() => { setMediaError(false); setMediaAttempt(n => n + 1) }}>重试播放</Button></div>}
        </section>
        {owner && selected.purpose === 'meeting' && selected.file.task_id && selected.file.id === `task:${selected.file.task_id}` && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(selected.file.task_id) && <RelatedSummaryTasks key={`${owner}:${selected.file.task_id}`} canonical={selected.file.task_id} owner={owner} sourceType={selected.file.source_type} returnTo={returnTo} />}
        <section aria-labelledby="file-content-heading" className="grid gap-3 border-t pt-4"><h2 id="file-content-heading" className="text-sm font-medium">关联内容</h2>
          {selected.file.note_id ? <><p className="text-sm text-muted-foreground">已有正文保留在会议与笔记中。这里管理来源原件，不复制笔记正文。</p><Button asChild><Link to={contentTarget(selected.file.note_id, selected, !sourceNote && selected.purpose === 'meeting' ? 'meeting' : undefined)} state={contentState(selected.file.note_id, selected, !sourceNote && selected.purpose === 'meeting' ? 'meeting' : undefined)} onClick={() => setSelected(null)}>{!sourceNote && selected.purpose === 'meeting' ? '查看会议档案' : '查看关联内容'}</Link></Button></> : selected.file.task_id ? <><p className="text-sm text-muted-foreground">{selected.file.error_code === "unknown_result" || selected.file.error_code === "unknown_error" ? "处理结果尚未确认。原文件已保留，请查询原结果，不重复提交。" : "已有处理记录，先查询原结果，不再次提交此原件。"}</p><Button disabled={busy || selected.purpose === 'unknown'} onClick={() => void generate(selected.file!)}>{selected.purpose === 'meeting' ? '查看纪要生成进度' : '查看笔记生成进度'}</Button></> : selected.file.can_generate ? <><p className="text-sm text-muted-foreground">从这份已保存原件整理正文，原件继续保留。已有未确认资料处理会先恢复。</p><Button variant="outline" disabled={busy || !selected.file.available || selected.purpose === 'unknown'} onClick={() => void generate(selected.file!)}>{selected.purpose === 'meeting' ? '用此原件生成纪要' : '用此原件整理笔记'}</Button></> : <p className="text-sm text-muted-foreground">此格式目前只支持原件保存与导出，尚未接入正文整理。</p>}
        </section>
        <section aria-labelledby="file-management-heading" className="grid gap-3 border-t pt-4"><h2 id="file-management-heading" className="text-sm font-medium">原件管理</h2>
          {selected.file.available ? <OriginalDownloadButton key={`${owner}:${selected.file.id}`} url={selected.file.content_url + (selected.file.id.startsWith('note:') || selected.file.id.startsWith('task:') ? '' : '?download=true')} filename={selected.file.filename} /> : <Button variant="outline" disabled>原件不可用，暂不能导出</Button>}
          {isMeetingOriginal(selected.file) ? <>
            <p className="text-xs leading-5 text-muted-foreground">会议原文件与相关纪要一起删除，请前往会议档案选择“删除整场会议”。</p>
            {!selected.file.task_id && !selected.file.note_id && <p className="text-xs text-muted-foreground">此原件尚未关联会议档案，请到会议页查找并确认对应会议。</p>}
            <Button variant="ghost" className="h-auto whitespace-normal text-destructive" asChild><Link to={meetingDeletionPath} state={{ returnTo }}>前往会议档案 · 删除整场会议</Link></Button>
          </> : <>
          <Button ref={deleteButton} variant="ghost" className="text-destructive" disabled={busy || !selected.file.can_delete} onClick={() => beginDeletion(selected.file!)}>删除原始文件</Button>
          {!selected.file.can_delete && <p className="text-xs text-muted-foreground">{selected.file.id.startsWith('task:') ? '此原件作为处理记录的来源保留，当前不支持删除。' : '此原件当前不允许删除；已有正文与版本继续保留。'}</p>}
          <p className="text-xs leading-5 text-muted-foreground">{selected.file.can_delete ? "删除原文件后，已保存的笔记、版本与飞书文档仍保留。" : "已保存的纪要、笔记与版本可在对应页面管理。"}</p>
          </>}
        </section>
        {error && <p role="alert" className="text-sm">{error}</p>}
      </div>}
      </div>
  )
  return <div className="workspace-page">
    {parent.split(/[?#]/)[0] !== '/files' && <PageReturn to={parent} label={pageParentLabel(parent)} />}
    {fullDetail ? <>
      <PageHeading title={selected ? taskDisplayTitle(selected.title, purpose === 'meeting') : '来源原文件'} description={scope === 'meeting' ? '会议记录' : '笔记来源'} />
      {selected ? <div className="max-w-4xl">{detailBody}</div> : loading
        ? <LoadingState label="正在读取原文件…" />
        : error ? <ErrorState title="原文件暂未读取成功" error={error} onRetry={() => void load()} busy={loading || busy} />
        : <EmptyState title="未找到这份原文件" description="这份原件未在当前设备关联文件列表中找到。已有正文与版本仍保留。"><Button variant="outline" onClick={() => void load()}>重新读取原文件</Button></EmptyState>}
    </> : <>
    <PageHeading title={sourceNote ? '来源原文件' : scope === 'meeting' ? '会议原文件' : scope === 'note' ? '笔记原文件' : '文件库'} description={sourceNote ? '查看这份内容关联的原文件。正文与版本保留在内容详情中。' : scope ? '查看和管理此类内容的原文件。正文与版本保留在对应内容中。' : '按会议与笔记用途管理原件，正文与版本在会议与笔记中查看。'} actions={<><Button variant="outline" disabled={loading || busy} onClick={() => void load()} aria-label="重新读取文件库"><RefreshCw aria-hidden="true" /></Button>{!sourceNote && scope !== 'meeting' && <Button disabled={busy} onClick={() => scope ? chooseImport(scope) : setImportOpen(true)}><Upload aria-hidden="true" />{busy ? '正在处理…' : '导入资料'}</Button>}</>} />
    {!sourceNote && scope !== 'meeting' && <><input ref={input} className="sr-only" type="file" aria-label="选择保存到文件库的原文件" aria-describedby={!scope ? 'file-import-help' : undefined} disabled={busy} onChange={e => { const file = e.target.files?.[0]; if (file) void upload(file) }} />
    {!scope && <p id="file-import-help" className="sr-only">导入后保留原文件。会议原件与相关纪要一起管理。</p>}</>}
    {savedMessage && <p role="status" className="text-sm">{savedMessage}</p>}
    {sourceNote && <p role="status" className="text-sm text-muted-foreground">仅显示与此内容关联的本设备原件。</p>}
    {!sourceNote && !scope && <div role="group" aria-label="资料用途" className="flex flex-wrap gap-1 border-b pb-2">{(['meeting', 'note', ...(rows.some(row => row.purpose === 'unknown') || purpose === 'unknown' ? ['unknown'] : [])] as FilePurposeView[]).map(value => <Button key={value} variant={purpose === value ? 'secondary' : 'ghost'} aria-pressed={purpose === value} className="h-9" onClick={() => setPurpose(value)}>{purposeLabel(value)} · {rows.filter(row => row.purpose === value).length}</Button>)}</div>}
    {!sourceNote && (purposeRows.length > 0 || !!query || category !== 'all') && <section aria-label="文件筛选" className="flex flex-wrap items-center justify-between gap-3 border-b pb-4">
      <div role="group" aria-label="文件分类" className="line-tabs flex flex-wrap">{categories.map(c => <Button type="button" variant={category === c.id ? 'secondary' : 'ghost'} aria-pressed={category === c.id} className="h-9" key={c.id} onClick={() => setCategory(c.id)}>{c.label}</Button>)}</div>
      <Input value={query} onChange={e => updateQuery(e.target.value)} placeholder="搜索文件名称" aria-label="搜索文件名称" className="w-full sm:max-w-xs" />
    </section>}
    {error && <ErrorState title="文件库需要处理" error={error} onRetry={() => void load()} busy={loading || busy} />}
    {!loading && rows.length > 0 && <p role="status" className="text-xs text-muted-foreground">{sourceNote ? `本设备关联 ${visible.length} 个原文件` : `${purposeLabel(purpose)} ${purposeRows.length} 个原件 · 当前显示 ${visible.length} 个${error ? ' · 部分读取未完成' : ''}`}</p>}
    {loading && !rows.length ? <LoadingState label="正在读取文件…" /> : <ul aria-label="原文件列表" className="divide-y">{visible.map(row => {
      const Icon = originalFormat(row.category) === 'audio' ? FileAudio : originalFormat(row.category) === 'video' ? FileVideo : FileText
      const noteId = row.file?.note_id || row.recording?.noteId
      const taskId = row.file?.task_id || row.recording?.taskId
      return <li key={row.id}><button type="button" onClick={() => openDetails(row)} className="flex w-full items-center gap-3 px-2 py-3 text-left hover:bg-muted/50 focus-visible:outline focus-visible:outline-ring"><Icon className="size-5 shrink-0" aria-hidden="true" /><span className="min-w-0 flex-1"><span className="block truncate font-medium">{taskDisplayTitle(row.title, purpose === 'meeting')}</span>{row.file && row.file.filename !== taskDisplayTitle(row.title, purpose === 'meeting') && <span className="mt-1 block truncate text-xs text-muted-foreground">{row.file.filename}</span>}<span className="mt-1 block text-xs leading-5 text-muted-foreground">{fileFormat(row)}{sourceBadge(row) && <> · <span>{sourceBadge(row)}</span></>} · {row.file ? fileSize(row.file.size_bytes) : recordingDuration(row.recording?.elapsedSeconds || 0)} · {fileDate(row)}</span><span className="sr-only">{row.file?.available === false ? '文件暂不可用' : fileLocation(row.file)}{noteId ? ' · 有关联内容' : taskId ? row.file?.processing_status === 'failed' ? ' · 处理未完成' : ' · 有处理记录' : ' · 尚无关联内容'}</span></span><span aria-hidden="true" className="shrink-0">›</span></button></li>
    })}</ul>}
    {!loading && !visible.length && !error && <EmptyState title={sourceNote && !sourceRows.length ? '当前设备未找到可核验的原文件关联' : query || category !== 'all' ? '没有匹配的文件' : `暂无${purposeLabel(purpose)}`} description={sourceNote && !sourceRows.length ? '原文件可能尚未登记，或保存在其他设备；这不代表原文件已删除。可返回内容详情继续阅读正文与版本。' : query || category !== 'all' ? '试试其他格式或文件名称。清除筛选仍保留当前资料用途。' : purpose === 'meeting' ? '录制或导入会议后，原文件会保存在这里。' : '导入一份文档、音视频或文字文件。'}>{!sourceNote && !query && category === 'all' && <Button variant="outline" onClick={() => chooseImport(purpose === 'meeting' ? 'meeting' : 'note')}>{purpose === 'meeting' ? '导入会议' : '选择第一份文件'}</Button>}{!sourceNote && (query || category !== 'all') && <Button variant="outline" onClick={clearFilters}>清除筛选</Button>}</EmptyState>}
    {!loading && !error && params.get('file') && !sourceRows.some(row => row.id === params.get('file')) && <p role="status" className="text-sm text-muted-foreground">这份原件未在当前设备关联文件列表中找到。<Button variant="ghost" onClick={closeDetails}>返回文件列表</Button></p>}
    </>}
    <Sheet open={!fullDetail && !!selected && !deletion} onOpenChange={value => { if (!busy && !value && !deletion) closeDetails() }}><SheetContent onOpenAutoFocus={event => { if (restoreDeletionFocus.current) { event.preventDefault(); restoreDeletionFocus.current = false; const target = deleteButton.current && !deleteButton.current.disabled ? deleteButton.current : detailTitle.current; target?.focus() } }} className="flex h-full min-h-0 w-full flex-col overflow-hidden sm:max-w-md"><SheetHeader className="shrink-0"><SheetTitle ref={detailTitle} tabIndex={-1} className="break-words pr-7">{selected ? taskDisplayTitle(selected.title, purpose === 'meeting') : '文件详情'}</SheetTitle><SheetDescription>{selected?.file?.location || '录制原件在当前电脑'}</SheetDescription></SheetHeader>
      {detailBody}
    </SheetContent></Sheet>
    <Dialog open={importOpen && !sourceNote} onOpenChange={setImportOpen}><DialogContent><DialogHeader><DialogTitle>导入哪类资料？</DialogTitle><DialogDescription>先确定用途，再选择原文件。这里只保存原件，不自动生成正文。</DialogDescription></DialogHeader><div className="grid gap-3 sm:grid-cols-2"><Button variant="outline" className="min-h-20 flex-col items-start gap-1 whitespace-normal text-left" onClick={() => chooseImport('meeting')}>会议资料<span className="text-xs font-normal text-muted-foreground">会议音频、视频或逐字稿</span></Button><Button variant="outline" className="min-h-20 flex-col items-start gap-1 whitespace-normal text-left" onClick={() => chooseImport('note')}>笔记资料<span className="text-xs font-normal text-muted-foreground">PDF、Word、音视频与文字</span></Button></div></DialogContent></Dialog>
    <AlertDialog open={!!deletion} onOpenChange={value => { if (!value) cancelDeletion() }}><AlertDialogContent onCloseAutoFocus={event => { if (selected) event.preventDefault() }}><AlertDialogHeader><AlertDialogTitle>删除这台设备上的原始文件？</AlertDialogTitle><AlertDialogDescription>这会释放本地空间，可能影响播放与重新生成。已有笔记、纪要、全部版本和飞书文档保留。</AlertDialogDescription></AlertDialogHeader>{error && <p role="alert">{error}</p>}<AlertDialogFooter><Button variant="outline" disabled={busy} onClick={cancelDeletion}>取消</Button><Button variant="destructive" disabled={busy} onClick={() => void remove()}>{busy ? '正在删除…' : '确认删除文件'}</Button></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </div>
}
