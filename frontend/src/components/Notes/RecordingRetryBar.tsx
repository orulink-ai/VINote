import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { AlertCircle, Loader2, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useI18n } from '../../lib/i18n'
import { getPendingMeeting, listPendingMeetings } from '../../lib/audioStorage'
import { processSavedMeeting } from '../../lib/meetingProcessing'
import { useAuthStore } from '../../stores/authStore'
import {
  MeetingGenerationError,
  completeMeetingRecordingGeneration,
  resumeMeetingTask,

} from '../../lib/meetingGeneration'
import { useNoteLibraryStore, type NoteRecord } from '../../stores/noteLibraryStore'


interface RecordingRetryBarProps {
  note: NoteRecord
  onUpdated: (note: NoteRecord) => void
}

export function RecordingRetryBar({ note, onUpdated }: RecordingRetryBarProps) {
  const { copy, language } = useI18n()
  const { updateNote, loadNoteById } = useNoteLibraryStore()
  const ownerId = useAuthStore(state => state.user?.id)
  const location = useLocation()

  const [status, setStatus] = useState<'idle' | 'working' | 'error'>('idle')
  const [message, setMessage] = useState('')
  const [sourceId, setSourceId] = useState<string | null>(null)
  const epoch = useRef(0)
  const locked = useRef(false)


  useEffect(() => {
    setStatus('idle')
    setMessage('')
    setSourceId(null)
    epoch.current++
    return () => { epoch.current++ }
  }, [note.id, ownerId])

  if (!['meeting_recording', 'meeting_video'].includes(note.sourceType || '')) return null
  if (note.status === 'done') return null

  const isFailed = ['failed', 'transcribing_failed', 'generation_failed'].includes(note.status)

  const runRetry = async () => {
    if (locked.current) return
    locked.current = true
    const run = epoch.current
    const current = () => epoch.current === run && !!ownerId && useAuthStore.getState().user?.id === ownerId
    setStatus('working')
    setMessage('')
    try {
      if (!ownerId) throw new Error('请重新登录后恢复原任务。')
      const local = (await listPendingMeetings(ownerId)).find(item => item.ownerId === ownerId &&
        ((!!note.taskId && item.taskId === note.taskId) || item.draftNoteId === note.id || item.noteId === note.id))
      if (!current()) return
      if (local) {
        const pending = await getPendingMeeting(local.id)
        if (!current()) return
        if (!pending || pending.id !== local.id || pending.ownerId !== ownerId || pending.recordingStatus !== 'saved' ||
          !((!!note.taskId && pending.taskId === note.taskId) || pending.draftNoteId === note.id || pending.noteId === note.id)) throw new Error('原录制状态未核验，请重新读取。')
        if (pending.generationConfirmationRequired || (!pending.taskId && !pending.generationOperation)) {
          setSourceId(pending.id); setStatus('idle'); setMessage('请到原录制详情确认本次模型；尚未重新提交生成。')
          return
        }
        await processSavedMeeting(pending, language)
        if (!current()) return
        const result = await getPendingMeeting(pending.id)
        if (!current()) return
        if (result?.ownerId === ownerId && result.generationConfirmationRequired) {
          setSourceId(result.id); setStatus('idle'); setMessage(result.processingError || '请到原录制详情确认模型。')
          return
        }
        if (result?.processingStatus === 'failed') throw new Error(result.processingError || copy.meetingRecorder.unknownError)
        if (result?.processingStatus !== 'completed') throw new Error('原任务尚未确认完成，请核对原任务状态。')
        const refreshed = await loadNoteById(note.id)
        if (!current()) return
        if (refreshed) onUpdated(refreshed)
        setStatus('idle')
        return
      }
      if (!note.taskId) throw new Error(copy.meetingRecorder.noRecoverableAudio)
      const response = await resumeMeetingTask(note.taskId)
      if (!current()) return
      setMessage(copy.meetingRecorder.phases.transcribing)
      const saved = await completeMeetingRecordingGeneration({
        taskId: response.task_id,
        workspace: note.scope === 'team' && note.teamId ? { scope: 'team', teamId: note.teamId } : { scope: 'personal' },
        saveNote: async (title, content) => {
          if (!current()) throw new Error('账号或内容已变化，请返回原账号恢复保存。')
          const updated = await updateNote(note.id, title, content, 'done')
          return updated
        },
      })
      if (!current()) return
      onUpdated({ ...note, id: saved.id, status: 'done', content: saved.content, title: saved.title, taskId: response.task_id })
      setStatus('idle')
      setMessage('')
      await loadNoteById(note.id)
    } catch (retryError) {
      if (!current()) return
      const errorMessage = retryError instanceof MeetingGenerationError
        ? retryError.message
        : retryError instanceof Error
          ? retryError.message
          : copy.meetingRecorder.unknownError
      setStatus('error')
      setMessage(errorMessage)
    } finally { locked.current = false }
  }

  // Only the failed variant renders as a compact icon. Pending recordings
  // surface their state through the editor itself; no extra chrome needed.
  if (!isFailed) return null

  const isWorking = status === 'working'

  return (
    <span className="inline-flex items-center gap-1.5">
      {sourceId ? <><span role="status" className="text-xs text-muted-foreground">{message}</span><Button variant="outline" size="sm" asChild><Link to={'/meetings?' + new URLSearchParams({ recordingConfirm: sourceId, returnTo: location.pathname + location.search + location.hash }).toString()}>原录制详情 · 确认模型</Link></Button></> : <>
      <Tooltip><TooltipTrigger asChild><Button
        type="button" variant="outline" size="icon"
        onClick={() => void runRetry()}
        disabled={isWorking}
        title={copy.meetingRecorder.retry}
        aria-label={copy.meetingRecorder.retry}
        data-testid="recording-retry-icon"
        className="rounded-full text-destructive hover:text-destructive"
      >
        {isWorking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
      </Button></TooltipTrigger><TooltipContent>{copy.meetingRecorder.retry}</TooltipContent></Tooltip>
      {status === 'error' ? (
        <Tooltip><TooltipTrigger asChild><span
          title={message}
          aria-label={message}
          className="inline-flex size-7 shrink-0 items-center justify-center rounded-full text-destructive"
        >
          <AlertCircle className="h-4 w-4" />
        </span></TooltipTrigger><TooltipContent>{message}</TooltipContent></Tooltip>
      ) : null}
      </>}
    </span>
  )
}
