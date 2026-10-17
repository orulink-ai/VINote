import { FrozenModelDisplay } from '@/components/NoteGenerator/FrozenModelDisplay'
import { taskRecoveryView, type RecoveryTask } from '@/lib/taskRecoveryView'
import { sourceRecoveryCopy } from '@/lib/sourceRecoveryCopy'
import { ModelSourcePanel } from "../components/Settings/ModelSourcePanel"
import { useAppModeStore } from "../stores/appModeStore"
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { resolvePageParent, pageParentLabel } from '@/lib/navigation'
import { PageReturn } from '@/components/Layout/PageReturn'
import { useAuthStore } from '@/stores/authStore'
import type { WorkspaceSelection } from '@/stores/teamStore'
import { FileAudio, Link as LinkIcon, Settings2, Wand2, Check } from 'lucide-react'
import { FileUploader, type UploadMode } from '../components/NoteGenerator/FileUploader'
import { GenerateProgress } from '../components/NoteGenerator/GenerateProgress'
import { TaskModelConfirmationSheet } from '../components/NoteGenerator/TaskModelConfirmationSheet'
import { useI18n } from '../lib/i18n'
import { apiJson, ApiError } from '../lib/api'
import { sourceVideoUrl, isBilibiliSourceUrl } from '../lib/sourceInput'
import { formatContentTitle } from '../lib/meetingTitle'
import { useModelProfileStore } from '../stores/modelProfileStore'
import { useNoteGenerationStore } from '../stores/noteGenerationStore'
import { useNoteLibraryStore } from '../stores/noteLibraryStore'
import { useSTTProfileStore } from '../stores/sttProfileStore'
import { getWorkspaceLabel, useTeamStore } from '../stores/teamStore'
import { Alert, AlertDescription } from '../components/ui/alert'
import { Button } from '../components/ui/button'
import { Label } from '../components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '../components/ui/sheet'

type FrozenNewContext = { protocol: number; parent_task_id: string; workflow: string; context_revision: string; source: { title: string; version: string }; frozen_models: { mode: string; origin: string; asr_model: string; llm_model: string }; can_confirm_new_operation: boolean }
type TaskResponse = { task_id: string; source_type?: string; operation_id?: string; state?: 'reserved' | 'accepted' }
type ImportReceipt = { id?: string; operationId?: string; createdAt?: string; submissionState?: 'registering' | 'unknown' | 'reserved' | 'accepted'; workspace: WorkspaceSelection; sourceUrl?: string; sourceType?: string; sourceTitle?: string; mode?: UploadMode; meeting: boolean; localFileId?: string; independentGeneration?: boolean; parentTaskId?: string; frozenContext?: FrozenNewContext }
type TaskStatusResponse = {
  task_id?: string
  error_code?: string
  retryable?: boolean
  stage?: string
  status: string
  message: string
  processed_seconds?: number | null
  received_seconds?: number | null
  speaker_detection_progress?: number | null
  speaker_analysis_ready?: boolean | null
  total_seconds?: number | null
  result?: {
    task_id: string
    title: string
    markdown: string
  }
}

export function NoteGenerator() {
  const [searchParams] = useSearchParams()
  const isMeeting = searchParams.get('meeting') === '1'
  const location = useLocation()
  const parent = resolvePageParent(location.state?.returnTo, isMeeting ? '/meetings' : '/notes')
  const [videoUrl, setVideoUrl] = useState('')
  const [sourceError, setSourceError] = useState('')
  const sourceInput = useRef<HTMLInputElement>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const registeredDocument = useRef<{ file: File; owner: string; id: string } | null>(null)
  const requestedMode = searchParams.get('mode') === 'file' ? 'file' : 'url'
  const [uploadMode, setUploadMode] = useState<UploadMode>(isMeeting ? 'file' : requestedMode)
  const [taskMessage, setTaskMessage] = useState('')
  const [readingTask, setReadingTask] = useState(false)
  const [transcriptionMeasure, setTranscriptionMeasure] = useState<{ processed: number; total: number } | null>(null)
  const [analysisMeasure, setAnalysisMeasure] = useState<{ received?: number; total?: number; detection?: number; speakersReady?: boolean }>({})
  const [taskId, setTaskId] = useState('')
  const owner = useAuthStore(s => s.user?.id)
  const receiptKey = owner ? `vinote:import-receipt:${owner}:${isMeeting ? 'meeting' : 'note'}` : ''
  const [receipt, setReceipt] = useState<ImportReceipt | null>(null)
  const [receiptProtected, setReceiptProtected] = useState(true)
  const [recoveryUnavailable, setRecoveryUnavailable] = useState(false)
  const submissionLock = useRef(false)
  const recoveryLock = useRef<{ token: symbol; owner: string; epoch: number; operationId: string; route: string } | null>(null)
  const operationParam = searchParams.get('operation') || ''
  const taskParam = searchParams.get('task') || ''
  const readOnlyTask = !!taskParam
  const routeBinding = JSON.stringify([location.key, location.pathname, location.search, location.hash, operationParam, taskParam, isMeeting, parent])
  const routeIdentity = useRef(routeBinding)
  routeIdentity.current = routeBinding
  const [taskRetryable, setTaskRetryable] = useState(false)
  const [verifiedTask, setVerifiedTask] = useState<RecoveryTask | null>(null)
  const [modelConfirmation, setModelConfirmation] = useState<{ receipt: ImportReceipt; owner: string; epoch: number } | null>(null)
  const [newConfirmation, setNewConfirmation] = useState<{ context: FrozenNewContext; owner: string; epoch: number } | null>(null)
  const [newBusy, setNewBusy] = useState(false)
  const newLock = useRef(false)
  const recoveryEpoch = useRef(0)
  const mounted = useRef(true)
  const pollingTask = useRef('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const { copy, language } = useI18n()

  const {
    status,
    progress,
    currentStep,
    error,
    setStatus,
    setProgress,
    setCurrentStep,
    setError,
    reset,
  } = useNoteGenerationStore()
  const { saveNote } = useNoteLibraryStore()
  const { currentWorkspace, teams, loadTeams } = useTeamStore()
  const cloudMode = useAppModeStore(state => state.config?.mode === "cloud")
  const { profiles, selectedProfileId, selectProfile, loadProfiles } = useModelProfileStore()
  const {
    profiles: sttProfiles,
    selectedProfileId: selectedSTTProfileId,
    selectProfile: selectSTTProfile,
    loadProfiles: loadSTTProfiles,
  } = useSTTProfileStore()
  const navigate = useNavigate()

  useEffect(() => useAuthStore.subscribe((next, previous) => {
    if (next.user?.id !== previous.user?.id) {
      recoveryEpoch.current++
      recoveryLock.current = null
      pollingTask.current = ''
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    }
  }), [])

  useEffect(() => {
    void loadProfiles()
    void loadSTTProfiles()
    void loadTeams()
  }, [loadProfiles, loadSTTProfiles, loadTeams])

  useEffect(() => {
    mounted.current = true
    recoveryEpoch.current++
    recoveryLock.current = null
    setModelConfirmation(null); setNewConfirmation(null)
    setReadingTask(false); setTaskRetryable(false); setVerifiedTask(null)
    setReceipt(null); setTaskId(''); setReceiptProtected(true); setRecoveryUnavailable(false)
    reset()
    if (taskParam) {
      if (!owner || operationParam || !/^[A-Za-z0-9_-]{1,64}$/.test(taskParam)) {
        setRecoveryUnavailable(true); setStatus('failed'); setError('无法核验指定任务，请返回资料重新打开。')
      } else {
        const selection = (location.state as { readOnlyTask?: Partial<ImportReceipt> & { owner?: string } } | null)?.readOnlyTask
        const sameSelection = selection?.owner === owner && selection.id === taskParam && selection.meeting === isMeeting
        const viewed: ImportReceipt = { id: taskParam, workspace: { scope: 'personal' }, meeting: isMeeting, submissionState: 'accepted', ...(sameSelection ? { sourceTitle: selection.sourceTitle, sourceType: selection.sourceType, localFileId: selection.localFileId } : {}) }
        setReceipt(viewed); setTaskId(taskParam)
        pollTaskStatus(taskParam, viewed.workspace, undefined, viewed.sourceType)
      }
    } else if (receiptKey) {
      try {
        const key = operationParam && /^[A-Za-z0-9_-]{1,160}$/.test(operationParam) ? `vinote:source-receipt:${owner}:${operationParam}` : receiptKey
        const saved = JSON.parse(localStorage.getItem(key) || 'null') as ImportReceipt | null
        if (operationParam && (!saved || saved.operationId !== operationParam)) throw new Error('缺少原操作回执')
        if ((saved?.id || saved?.operationId) && saved?.workspace && saved.meeting === isMeeting) {
          setReceipt(saved); setTaskId(saved.id || '')
          if (saved.sourceUrl) setVideoUrl(saved.sourceUrl)
          if (saved.operationId && saved.submissionState !== 'accepted') {
            setStatus('failed'); void recoverSubmission(saved)
          } else if (saved.id) {
            pollTaskStatus(saved.id, saved.workspace, saved.sourceUrl, saved.sourceType, saved.operationId, saved.createdAt)
          }
        }
      } catch { setRecoveryUnavailable(true); setStatus('failed'); setError('无法读取本机任务回执，请勿重复提交，先检查处理记录。') }
    }

    return () => {
      mounted.current = false
      recoveryEpoch.current++
      recoveryLock.current = null
      pollingTask.current = ''
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [reset, receiptKey, isMeeting, operationParam, taskParam, routeBinding])

  useEffect(() => {
    setUploadMode(isMeeting ? 'file' : requestedMode)
    setSelectedFile(null)
  }, [isMeeting, requestedMode])

  const pollTaskStatus = (
    id: string,
    workspace = currentWorkspace,
    sourceUrl?: string,
    sourceType?: string,
    operationId?: string,
    createdAt?: string,
  ) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollingTask.current = id
    const epoch = recoveryEpoch.current
    const route = routeIdentity.current
    const active = () => mounted.current && routeIdentity.current === route && recoveryEpoch.current === epoch && pollingTask.current === id && owner === useAuthStore.getState().user?.id
    let inFlight = false
    let firstRead = true
    setReadingTask(true); setTaskRetryable(false); setVerifiedTask(null); setTaskMessage('')
    setTranscriptionMeasure(null); setAnalysisMeasure({})
    const readStatus = async () => {
      if (!active() || inFlight) return
      inFlight = true
      try {
        const data = await apiJson<TaskStatusResponse>(`/api/task/${id}`)
        if (!active()) return
        if (!data || typeof data.status !== 'string') throw new Error('任务进度响应无效')
        if (readOnlyTask && data.task_id !== id) throw new Error('指定任务响应身份尚未核验。')
        if (data.task_id && data.task_id !== id) throw new Error('响应与原任务不一致，请重新核验。')
        setVerifiedTask({ taskId: data.task_id || data.result?.task_id || '', status: data.status, errorCode: data.error_code, hasCompleteResult: !!data.result?.markdown?.trim() && !!data.result?.title?.trim() })
        firstRead = false
        setReadingTask(false)
        setStatus('processing')
        setTaskMessage(data.message || '')
        setAnalysisMeasure({ total: data.total_seconds ?? undefined, received: data.received_seconds ?? undefined, detection: data.speaker_detection_progress ?? undefined, speakersReady: data.speaker_analysis_ready ?? undefined })
        setTranscriptionMeasure(data.status === 'transcribing' && Number.isFinite(data.processed_seconds) && Number.isFinite(data.total_seconds) && (data.total_seconds || 0) > 0
          ? { processed: Math.max(0, data.processed_seconds || 0), total: data.total_seconds! }
          : null)

        if (readOnlyTask && data.status === 'success') {
          clearInterval(pollRef.current!); pollRef.current = null; setStatus('success'); setTaskMessage('原任务已完成。当前仅查看处理记录，不会重新生成或恢复保存。'); return
        }
        if (data.status === 'success') {
          if (!data.result?.markdown?.trim() || !data.result.title?.trim()) throw new Error('任务结果不完整，继续核验原结果。')
          clearInterval(pollRef.current!)
          pollRef.current = null
          setProgress(100)
          setCurrentStep('success')
          setCurrentStep('saving')

          await useNoteLibraryStore.getState().loadNotes(workspace)
          if (!active()) return
          const existing = useNoteLibraryStore.getState().notes.find(n => n.taskId === id)
          const note = existing || await saveNote(
            formatContentTitle(createdAt || '', data.result?.markdown || '', data.result?.title || '', language),
            data.result?.markdown || '',
            sourceUrl || undefined,
            data.result?.task_id || id,
            workspace,
            isMeeting ? (sourceType === 'video' || sourceType === 'meeting_video' ? 'meeting_video' : 'meeting_recording') : sourceType,
          )
          if (!active()) return
          if (note) {
            const active = JSON.parse(localStorage.getItem(receiptKey) || 'null') as ImportReceipt | null
            if (active?.id === id) localStorage.removeItem(receiptKey)
            // The per-operation record remains until saving has been acknowledged.
            if (operationId) localStorage.removeItem(`vinote:source-receipt:${owner}:${operationId}`)
            else if (active?.id === id && active.operationId) localStorage.removeItem(`vinote:source-receipt:${owner}:${active.operationId}`)
            setReceipt(null)
          setReceiptProtected(true)
            setStatus('success')
            navigate(`/note/${note.id}`, { state: { returnTo: parent } })
            return
          }

          setStatus('failed')
          setError(copy.generator.saveFailed)
        } else if (['failed', 'error', 'not_found'].includes(data.status)) {
          setTaskRetryable(!readOnlyTask && ['failed', 'error'].includes(data.status) && !!data.retryable && !['unknown_result', 'unknown_error', 'asr_incomplete_result'].includes(data.error_code || ''))
          setReceiptProtected(true)
          clearInterval(pollRef.current!)
          pollRef.current = null
          setStatus('failed')
          setError(data.status === 'not_found'
            ? '任务记录不存在或已丢失。原回执已保留，请核验原提交，不重复生成。'
            : data.message || 'Generation failed')
        } else if (data.status === 'preparing') {
          setCurrentStep('preparing'); setProgress(15)
        } else if (data.status === 'transcribing') {
          setCurrentStep(isMeeting && ['parallel_analysis', 'diarizing', 'aligning', 'transcript_ready'].includes(data.stage || '') ? data.stage! : 'transcribing')
          const chunk = data.message?.match(/Transcribing chunk (\d+)\/(\d+)/)
          setProgress(chunk ? 30 + Math.round(45 * (Number(chunk[1]) - 1) / Number(chunk[2])) : 30)
        } else if (data.status === 'summarizing') {
          setCurrentStep('summarizing')
          setProgress(80)
        } else if (data.status === 'screenshots') {
          setCurrentStep('screenshots')
          setProgress(90)
        }
      } catch (pollError) {
        if (!active()) return
        if (firstRead) {
          if (pollRef.current) clearInterval(pollRef.current)
          pollRef.current = null
          setReadingTask(false); setStatus('failed')
          setError('无法读取原任务进度，处理结果尚未确认。请查询原结果，不重复生成。')
          return
        }
        console.error('Failed to poll task status:', pollError)
        setTaskMessage('暂时无法获取任务进度，正在重试；请勿重复提交。')
        if (!pollRef.current && mounted.current) { setStatus('failed'); setError('结果保存尚未确认，请查询原任务并恢复保存。') }
      } finally {
        inFlight = false
      }
    }
    pollRef.current = setInterval(() => void readStatus(), 2000)
    void readStatus()
  }

  const persistReceipt = (value: ImportReceipt) => {
    if (!owner || owner !== useAuthStore.getState().user?.id || !receiptKey) throw new Error('账号已切换，请重新打开来源')
    if (value.operationId) localStorage.setItem(`vinote:source-receipt:${owner}:${value.operationId}`, JSON.stringify(value))
    if (!operationParam) localStorage.setItem(receiptKey, JSON.stringify(value))
  }
  const resumeReceipt = (value: ImportReceipt) => {
    setReceipt(value); setTaskId(value.id || '')
    try { persistReceipt(value) } catch { setReceiptProtected(false); setTaskMessage('原提交回执保存失败，请保留此页并核验原结果。') }
    if (value.submissionState === 'reserved') {
      setStatus('failed'); setError('提交已登记，尚未确认排队。请继续核验原提交，不会自动重新派发。'); return
    }
    if (!value.id) throw new Error('尚未收到任务编号，原提交保留')
    setStatus('processing'); setCurrentStep('preparing'); setProgress(15)
    pollTaskStatus(value.id, value.workspace, value.sourceUrl, value.sourceType, value.operationId, value.createdAt)
  }
  const recoverSubmission = async (value: ImportReceipt) => {
    if (!owner || readOnlyTask || !value.operationId || recoveryLock.current || (operationParam && operationParam !== value.operationId)) return
    const request = { token: Symbol('receipt-read'), owner, epoch: recoveryEpoch.current, operationId: value.operationId, route: routeIdentity.current }
    recoveryLock.current = request
    const active = () => mounted.current && request.owner === useAuthStore.getState().user?.id
      && recoveryEpoch.current === request.epoch && routeIdentity.current === request.route
      && recoveryLock.current?.token === request.token && recoveryLock.current.operationId === request.operationId
    setTaskMessage('正在核验上次提交…')
    try {
      const data = await apiJson<TaskResponse>(`/api/source-requests/${encodeURIComponent(request.operationId)}`)
      if (!active()) return
      if (data.operation_id !== request.operationId || !data.task_id || !['reserved', 'accepted'].includes(data.state || '')) throw new Error('回执与原操作不一致，请继续核验')
      resumeReceipt({ ...value, id: data.task_id, sourceType: data.source_type || value.sourceType, submissionState: data.state })
    } catch (cause) {
      if (!active()) return
      setStatus('failed')
      setError(cause instanceof ApiError && cause.status === 404
        ? (value.independentGeneration ? '尚未查到本次提交回执。请保留本次处理记录并继续查询，不会重新提交。' : value.submissionState === 'registering' ? '原件注册尚未确认，请在文件库核验；首次文件注册不支持去重，不自动重新注册。' : '尚未查到原提交回执，请稍后核验。原编号已保留；媒体来源尚未支持提交去重，不自动重新提交。')
        : cause instanceof Error ? cause.message : '原提交尚未确认，请重试查询')
    } finally { if (active()) recoveryLock.current = null }
  }

  const handleGenerate = async () => {
    if (submissionLock.current || recoveryUnavailable) return
    if (receipt) { if (receipt.operationId && receipt.submissionState !== 'accepted') void recoverSubmission(receipt); else setError('原任务仍需核验，请先查询原结果，不重复提交。'); return }
    if ((uploadMode === 'url' && !videoUrl) || (uploadMode !== 'url' && !selectedFile)) {
      return
    }
    if (isMeeting && (uploadMode === 'url' || uploadMode === 'document' || selectedFile && /\.(pdf|docx|doc|md)$/i.test(selectedFile.name))) {
      setSourceError('会议只支持音视频或逐字稿；网页、PDF 和 Word 请在笔记中整理。')
      return
    }

    // Invalid input has no task to retry. Validate before receipt or progress changes.
    let sourceUrl = ''
    if (uploadMode === 'url') {
      try { sourceUrl = sourceVideoUrl(videoUrl) }
      catch (cause) {
        setSourceError(cause instanceof Error ? cause.message : '请检查来源链接')
        sourceInput.current?.focus()
        return
      }
    }
    setSourceError('')

    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }

    submissionLock.current = true
    reset()
    setTaskMessage('')
    setTranscriptionMeasure(null)
    setAnalysisMeasure({})
    setStatus('uploading')
    setCurrentStep('uploading')
    setProgress(10)

    try {
      const generationWorkspace = currentWorkspace
      if (!owner || owner !== useAuthStore.getState().user?.id) throw new Error('请登录后整理来源')
      let data: TaskResponse
      const pending: ImportReceipt = { operationId: crypto.randomUUID(), createdAt: new Date().toISOString(), submissionState: uploadMode === 'document' ? 'registering' : 'unknown', workspace: generationWorkspace, sourceUrl, sourceType: uploadMode === 'document' ? 'file' : uploadMode === 'transcript' ? 'transcript' : uploadMode === 'file' ? selectedFile?.type.startsWith('video/') ? 'video' : 'audio' : undefined, sourceTitle: selectedFile?.name, mode: uploadMode, meeting: isMeeting }
      // Durable owner-scoped operation precedes every POST, including registration.
      persistReceipt(pending); setReceipt(pending)

      if (uploadMode === 'url') {
        setCurrentStep('downloading')
        setProgress(20)
        data = await apiJson<TaskResponse>('/api/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-VINote-Operation-Id': pending.operationId! },
          body: JSON.stringify({
            video_url: sourceUrl,
            workflow: isMeeting ? 'meeting' : 'note_organization',
            summary_mode: 'default',
            output_language: language,
            model_profile_id: selectedProfileId || undefined,
            stt_profile_id: selectedSTTProfileId || undefined,
          }),
        })
      } else {
        if (!selectedFile) {
          throw new Error(copy.generator.fileRequired)
        }

        const formData = new FormData()
        const sourceType = uploadMode === 'document' ? 'document' : uploadMode === 'transcript'
          ? 'transcript'
          : selectedFile.type.startsWith('video/')
            ? 'video'
            : 'audio'

        formData.append('file', selectedFile)
        formData.append('source_type', sourceType)
        if (sourceType === 'document') {
          if (!owner || useAuthStore.getState().user?.id !== owner) throw new Error('请登录后导入文档')
          let original = registeredDocument.current
          if (!original || original.file !== selectedFile || original.owner !== owner) {
            const source = new FormData()
            source.append('file', selectedFile)
            const stored = await apiJson<{ id: string }>('/api/files', { method: 'POST', body: source })
            original = { file: selectedFile, owner, id: stored.id }
            registeredDocument.current = original
          }
          if (useAuthStore.getState().user?.id !== owner) throw new Error('账号已切换，原件保留在原账号文件库')
          formData.append('local_file_id', original.id)
          pending.localFileId = original.id
        }
        formData.append('title', selectedFile.name)
        formData.append('style', isMeeting ? 'meeting' : 'detailed')
        formData.append('workflow', isMeeting ? 'meeting' : 'note_organization')
        formData.append('trace_source', 'local_file')
        if (!['transcript', 'document'].includes(sourceType)) formData.append('diarize', 'true')
        formData.append('summary_mode', 'default')
        formData.append('output_language', language)
        if (selectedProfileId) {
          formData.append('model_profile_id', selectedProfileId)
        }
        if (selectedSTTProfileId) {
          formData.append('stt_profile_id', selectedSTTProfileId)
        }

        pending.submissionState = 'unknown'; persistReceipt(pending)
        if (owner !== useAuthStore.getState().user?.id) throw new Error('账号已切换，请重新打开来源')
        data = await apiJson<TaskResponse>('/api/generate_from_upload', {
          method: 'POST',
          headers: { 'X-VINote-Operation-Id': pending.operationId! },
          body: formData,
        })
      }

      const submittedSourceType = data.source_type || (uploadMode === 'document' ? 'file' : uploadMode === 'transcript'
        ? 'transcript'
        : uploadMode === 'file'
          ? selectedFile?.type.startsWith('video/') ? 'video' : 'audio'
          : undefined)
      if (!mounted.current || owner !== useAuthStore.getState().user?.id) return
      if (!data.task_id || (data.state && !['reserved', 'accepted'].includes(data.state)) || (data.operation_id && data.operation_id !== pending.operationId)) throw new Error('服务回执不完整，原操作已保留，请核验原提交')
      resumeReceipt({ ...pending, id: data.task_id, sourceType: submittedSourceType, submissionState: data.state || 'accepted' })
    } catch (generationError) {
      if (!mounted.current || owner !== useAuthStore.getState().user?.id) return
      setStatus('failed')
      setError(generationError instanceof Error ? generationError.message : copy.generator.unknownError)
    } finally { submissionLock.current = false }
  }

  const resumeOriginal = async () => {
    if (!receipt) { await handleGenerate(); return }
    if (receipt.operationId && receipt.submissionState !== 'accepted') { await recoverSubmission(receipt); return }
    if (!receipt.id || submissionLock.current) return
    const epoch = recoveryEpoch.current
    submissionLock.current = true
    try {
      if (!readOnlyTask && taskRetryable) {
        const latest = await apiJson<TaskStatusResponse>(`/api/task/${receipt.id}`)
        if (!mounted.current || epoch !== recoveryEpoch.current || owner !== useAuthStore.getState().user?.id) return
        if (['failed', 'error'].includes(latest.status) && latest.retryable && !['unknown_result', 'unknown_error', 'asr_incomplete_result'].includes(latest.error_code || '')) await apiJson(`/api/task/${receipt.id}/retry`, { method: 'POST' })
      }
      if (!mounted.current || epoch !== recoveryEpoch.current || owner !== useAuthStore.getState().user?.id) return
      setTaskRetryable(false); setStatus('processing')
      pollTaskStatus(receipt.id, receipt.workspace, receipt.sourceUrl, receipt.sourceType, receipt.operationId, receipt.createdAt)
    } catch (cause) {
      if (mounted.current && epoch === recoveryEpoch.current && owner === useAuthStore.getState().user?.id) {
        setError((cause as Error).message)
        if (cause instanceof ApiError && cause.status === 409 && owner) setModelConfirmation({ receipt: { ...receipt }, owner, epoch })
      }
    }
    finally { submissionLock.current = false }
  }

  const openNewGeneration = async () => {
    if (!receipt?.id || !owner || newLock.current || !verifiedTask || verifiedTask.taskId !== receipt.id || !['failed', 'error'].includes(verifiedTask.status)) return
    const epoch = recoveryEpoch.current; const parentTask = receipt.id
    const active = () => mounted.current && epoch === recoveryEpoch.current && owner === useAuthStore.getState().user?.id
    newLock.current = true; setNewBusy(true)
    try {
      const context = await apiJson<FrozenNewContext>(`/api/task/${encodeURIComponent(parentTask)}/new-generation-context`)
      if (!active()) return
      const origin = new URL(context.frozen_models.origin)
      if (context.protocol !== 1 || context.parent_task_id !== parentTask || !context.can_confirm_new_operation || context.workflow !== (isMeeting ? 'meeting' : 'note_organization') || context.frozen_models.mode !== 'cloud' || !context.frozen_models.asr_model?.trim() || !context.frozen_models.llm_model?.trim() || !/^[0-9a-f]{64}$/.test(context.context_revision) || !/^[0-9a-f]{64}$/.test(context.source.version) || !['https:', 'http:'].includes(origin.protocol) || origin.username || origin.password || origin.search || origin.hash) throw new Error('原文件与冻结模型尚不能完整核验，未使用当前默认模型。')
      setNewConfirmation({ context, owner, epoch })
    } catch (cause) { if (active()) setError(cause instanceof Error ? cause.message : '无法读取冻结模型，请返回处理记录。') }
    finally { newLock.current = false; if (active()) setNewBusy(false) }
  }
  const confirmNewGeneration = async () => {
    const confirmed = newConfirmation
    if (!confirmed || !receipt?.id || newLock.current) return
    const active = () => mounted.current && confirmed.epoch === recoveryEpoch.current && confirmed.owner === useAuthStore.getState().user?.id && confirmed.context.parent_task_id === receipt.id
    if (!active()) { setNewConfirmation(null); return }
    newLock.current = true; setNewBusy(true)
    const operationId = crypto.randomUUID()
    const pending: ImportReceipt = { operationId, createdAt: new Date().toISOString(), submissionState: 'unknown', workspace: readOnlyTask ? currentWorkspace : receipt.workspace, sourceTitle: confirmed.context.source.title, sourceType: receipt.sourceType, localFileId: receipt.localFileId || `task:${receipt.id}`, mode: 'file', meeting: isMeeting, independentGeneration: true, parentTaskId: receipt.id, frozenContext: confirmed.context }
    const key = `vinote:source-receipt:${owner}:${operationId}`
    let protectedOperation = false
    const route = `/generate?${new URLSearchParams({ ...(isMeeting ? { meeting: '1' } : {}), operation: operationId })}`
    try {
      // Archive the task-only identity separately; never replace a global slot
      // or invent an operation ID for the old task. Failure prevents all POSTs.
      localStorage.setItem(`vinote:source-task-receipt:${owner}:${receipt.id}`, JSON.stringify(receipt))
      localStorage.setItem(key, JSON.stringify(pending))
      if (localStorage.getItem(key) !== JSON.stringify(pending)) throw new Error('无法保护本次提交记录，未开始处理。')
      protectedOperation = true
      if (!active()) return
      const result = await apiJson<TaskResponse>(`/api/task/${encodeURIComponent(receipt.id)}/new-generation`, { method: 'POST', body: JSON.stringify({ operation_id: operationId, confirmed: true, context_revision: confirmed.context.context_revision, source_version: confirmed.context.source.version }) })
      if (!active()) return
      if (result.operation_id !== operationId || !result.task_id || result.task_id === receipt.id || !['reserved', 'accepted'].includes(result.state || '')) throw new Error('本次提交结果尚未确认，只能查询本次操作。')
      localStorage.setItem(key, JSON.stringify({ ...pending, id: result.task_id, submissionState: result.state, sourceType: result.source_type || pending.sourceType }))
      setNewConfirmation(null); navigate(route, { state: { returnTo: parent } })
    } catch (cause) {
      if (!active()) return
      setNewConfirmation(null)
      if (protectedOperation) navigate(route, { state: { returnTo: parent } })
      else setError(cause instanceof Error ? cause.message : '无法保护处理记录，未开始新的处理。')
    } finally { newLock.current = false; if (active()) setNewBusy(false) }
  }

  const handleEditInput = () => {
    if (readOnlyTask || recoveryUnavailable || receipt && (!taskRetryable || receipt.submissionState !== 'accepted')) return;
    if (receiptKey && receipt) localStorage.removeItem(receiptKey);
    setReceipt(null);
    setTaskRetryable(false);
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    reset()
  }

  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId)
  const defaultProfile = profiles.find((profile) => profile.isDefault)
  const selectedSTTProfile = sttProfiles.find((profile) => profile.id === selectedSTTProfileId)
  const defaultSTTProfile = sttProfiles.find((profile) => profile.isDefault)
  const workspaceLabel = getWorkspaceLabel(
    currentWorkspace,
    teams,
    language === 'zh-CN' ? '个人空间' : 'Personal workspace',
  )
  const formatSTTProfileLabel = (name: string, profile: { provider: string; modelName: string | null; language: string | null }) => {
    const detail = profile.modelName || profile.language || profile.provider
    return `${name} / ${detail}`
  }

  let currentUrlError = ''
  if (uploadMode === 'url' && videoUrl.trim()) {
    try { sourceVideoUrl(videoUrl) }
    catch { currentUrlError = '请粘贴完整有效的 http 或 https 链接' }
  }
  const visibleSourceError = sourceError || currentUrlError
  const sourceReady = isMeeting
    ? uploadMode !== 'url' && uploadMode !== 'document' && Boolean(selectedFile) && !/\.(pdf|docx|doc|md)$/i.test(selectedFile?.name || '')
    : uploadMode === 'url' ? Boolean(videoUrl.trim()) : Boolean(selectedFile)
  const restoringSource = !!receipt || recoveryUnavailable
  const originalSource = receipt?.sourceUrl || receipt?.sourceTitle || '来源信息不完整'
  const originalSourceType = receipt?.sourceUrl || receipt?.mode === 'url' ? '网页或视频链接'
    : receipt?.mode === 'document' || ['file', 'document'].includes(receipt?.sourceType || '') ? '导入文档'
      : receipt?.mode === 'transcript' || receipt?.sourceType === 'transcript' ? '文字或逐字稿文件'
        : ['video', 'meeting_video'].includes(receipt?.sourceType || '') ? '视频文件' : ['audio', 'meeting_recording'].includes(receipt?.sourceType || '') ? '音频文件'
          : receipt?.mode === 'file' ? '导入文件' : '来源类型待核验'
  const originalWorkspace = readOnlyTask ? '当前只查看处理记录' : receipt ? getWorkspaceLabel(receipt.workspace, teams, language === 'zh-CN' ? '个人空间' : 'Personal workspace') : '保存位置尚未核验'
  const recoveryView = taskRecoveryView(receipt, verifiedTask, taskRetryable)
  const originalState = readOnlyTask && !verifiedTask ? '原任务状态待核验' : verifiedTask?.status === 'success' ? '原任务已完成' : recoveryView.kind === 'failed_unknown' ? '任务已接收，此次转写未完成'
    : recoveryView.kind === 'failed_terminal' ? '任务已接收，此次处理未完成'
    : receipt?.submissionState === 'accepted' ? '服务已接收任务'
    : receipt?.submissionState === 'reserved' ? '提交已登记，排队尚未确认'
      : receipt?.submissionState === 'registering' ? '文件保存待确认'
        : receipt ? '提交待确认' : '任务记录无法读取，处理状态待确认'
  const originalNeedsAttention = recoveryUnavailable || verifiedTask?.status === 'not_found' || ['source_unavailable', 'source_version_unavailable'].includes(verifiedTask?.errorCode || '')
  const recordFailure = !readOnlyTask ? null : originalNeedsAttention ? {
    outcome: verifiedTask?.status === 'not_found' ? '暂未查到本次处理记录。'
      : recoveryUnavailable ? '暂时无法读取本次处理记录。' : '原文件暂不可读取，本次处理未完成。',
    next: '请返回资料查看原文件，或查看处理历史。',
  } : recoveryView.kind === 'failed_unknown' ? {
    outcome: '本次处理结果尚未确认，暂无可保存的完整结果。',
    next: '可查询本次状态；重新处理需要再次确认，不会自动重试。',
  } : recoveryView.kind === 'failed_terminal' ? {
    outcome: sourceRecoveryCopy(error) || '本次处理未完成。',
    next: '原文件和处理记录已保留。可查询状态，重新处理需要再次确认。',
  } : {
    outcome: '本次处理结果尚未确认。',
    next: '请重新查询本次状态，确认前不会重新处理。',
  }
  const historyPath = `/tasks?tab=generation&returnTo=${encodeURIComponent(parent)}`
  const originalFile = receipt?.localFileId || (receipt?.id && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(receipt.id) ? `task:${receipt.id}` : undefined)
  const materialsPath = `/files?${new URLSearchParams({ purpose: isMeeting ? "meeting" : "note", ...(originalFile ? { file: originalFile } : {}), returnTo: parent })}`

  const generationSettings = <div className="grid gap-6">
    <div className="border-b pb-4"><Label>{copy.generator.saveTargetWorkspace}</Label><p className="mt-2 text-sm font-medium">{workspaceLabel}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{isMeeting ? copy.generator.saveTargetMeetingHint : copy.generator.saveTargetWorkspaceHint}</p></div>
    {cloudMode ? <ModelSourcePanel compact /> : <div className="grid gap-5">
      <div><Label className="mb-2 block">{copy.generator.modelProfileLabel}</Label><Select value={selectedProfileId || 'system-default'} onValueChange={value => selectProfile(value === 'system-default' ? '' : value)}><SelectTrigger><SelectValue placeholder={copy.generator.systemDefaultModel} /></SelectTrigger><SelectContent><SelectItem value="system-default">{copy.generator.systemDefaultModel}</SelectItem>{profiles.map(profile => <SelectItem key={profile.id} value={profile.id}>{profile.name} / {profile.modelName}{profile.isDefault ? ' (default)' : ''}</SelectItem>)}</SelectContent></Select><p className="mt-2 text-xs leading-5 text-muted-foreground">{selectedProfile ? copy.generator.activeModelSelected(selectedProfile.name, selectedProfile.modelName) : defaultProfile ? copy.generator.activeModelDefault(defaultProfile.name, defaultProfile.modelName) : copy.generator.activeModelBackend}</p></div>
      <div><Label className="mb-2 block">{copy.generator.sttProfileLabel}</Label><Select value={selectedSTTProfileId || 'system-default'} onValueChange={value => selectSTTProfile(value === 'system-default' ? '' : value)}><SelectTrigger><SelectValue placeholder={copy.generator.systemDefaultSTT} /></SelectTrigger><SelectContent><SelectItem value="system-default">{copy.generator.systemDefaultSTT}</SelectItem>{sttProfiles.map(profile => <SelectItem key={profile.id} value={profile.id}>{formatSTTProfileLabel(profile.name, profile)}{profile.isDefault ? ' (default)' : ''}</SelectItem>)}</SelectContent></Select><p className="mt-2 text-xs leading-5 text-muted-foreground">{selectedSTTProfile ? copy.generator.activeSTTSelected(selectedSTTProfile.name, formatSTTProfileLabel(selectedSTTProfile.name, selectedSTTProfile)) : defaultSTTProfile ? copy.generator.activeSTTDefault(defaultSTTProfile.name, formatSTTProfileLabel(defaultSTTProfile.name, defaultSTTProfile)) : copy.generator.activeSTTBackend}</p></div>
    </div>}
  </div>

  const running = readingTask || status === 'uploading' || status === 'processing'

  return <div className="workspace-page intake-page max-w-3xl pb-8">
    <Sheet open={!!newConfirmation && newConfirmation.owner === owner && newConfirmation.epoch === recoveryEpoch.current} onOpenChange={open => { if (!open && !newBusy) setNewConfirmation(null) }}><SheetContent><SheetHeader><SheetTitle>确认原模型，开始新的处理</SheetTitle><SheetDescription>这是一次独立处理，可能再次产生处理费用。原文件和上次处理记录继续保留；不会重试上次任务。</SheetDescription></SheetHeader>{newConfirmation && <div className="mt-5 grid gap-4"><dl className="grid gap-3 text-sm"><div><dt>来源</dt><dd>{newConfirmation.context.source.title}</dd></div><FrozenModelDisplay key={`${newConfirmation.owner}:${newConfirmation.epoch}:${newConfirmation.context.context_revision}`} owner={newConfirmation.owner} contextKey={JSON.stringify([newConfirmation.epoch, newConfirmation.context.parent_task_id, newConfirmation.context.context_revision, newConfirmation.context.source.version])} models={newConfirmation.context.frozen_models} /><div><dt>保存位置</dt><dd>{readOnlyTask ? workspaceLabel : originalWorkspace}</dd></div></dl><Button disabled={newBusy} onClick={() => void confirmNewGeneration()}>{newBusy ? '正在提交…' : '确认原模型并开始新的处理'}</Button><Button variant="outline" disabled={newBusy} onClick={() => setNewConfirmation(null)}>取消</Button></div>}</SheetContent></Sheet>
    {modelConfirmation?.receipt.id && modelConfirmation.owner === owner && <TaskModelConfirmationSheet
      key={`${modelConfirmation.owner}:${modelConfirmation.receipt.id}:${modelConfirmation.epoch}`}
      taskId={modelConfirmation.receipt.id} owner={modelConfirmation.owner}
      onClose={() => setModelConfirmation(null)}
      onAccepted={() => {
        if (modelConfirmation.epoch !== recoveryEpoch.current || owner !== useAuthStore.getState().user?.id) return
        setModelConfirmation(null); setTaskRetryable(false); resumeReceipt(modelConfirmation.receipt)
      }}
      onQuery={() => {
        if (modelConfirmation.epoch !== recoveryEpoch.current || owner !== useAuthStore.getState().user?.id) return
        setModelConfirmation(null); setTaskRetryable(false); resumeReceipt(modelConfirmation.receipt)
      }}
    />}
    {status !== 'uploading' && receiptProtected && <PageReturn to={parent} label={parent.split('?')[0] === '/notes' ? '返回笔记' : pageParentLabel(parent)} />}
    {!receiptProtected && receipt && <Button variant="ghost" disabled>本机任务保护失败，请完成保存后返回</Button>}
    {status === 'uploading' && <Button variant="ghost" disabled>正在提交来源，完成后可返回上级</Button>}
    {(readOnlyTask || !running) && <>
    <header className="max-w-2xl">
      <h1 className="text-2xl font-medium text-balance">{readOnlyTask ? (isMeeting ? '会议处理记录' : '笔记处理记录') : isMeeting ? '从已有录制生成会议纪要' : '链接或文件转笔记'}</h1>
      <p className="mt-2 text-[15px] leading-6 text-muted-foreground">{readOnlyTask ? '查看本次处理的进度、结果与来源。' : isMeeting ? '选择音频、视频或逐字稿。系统会完成转写、说话人整理和纪要生成。' : '选择来源并确认保存位置。完成后直接进入编辑器继续修改和分享。'}</p>
    </header>

    </>}

    {restoringSource && <section aria-label="任务来源" className="grid gap-3 rounded-xl border bg-muted/20 p-4">
      <details open={!running && !readOnlyTask}>
      <summary className="cursor-pointer text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{recoveryUnavailable ? '处理状态待确认' : '查看任务来源'}</summary>
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div className="min-w-0"><dt className="text-xs text-muted-foreground">来源</dt><dd className="mt-1 break-words">{originalSource}</dd></div>
        <div><dt className="text-xs text-muted-foreground">来源类型</dt><dd className="mt-1">{originalSourceType}</dd></div>
        <div><dt className="text-xs text-muted-foreground">保存位置</dt><dd className="mt-1">{originalWorkspace}</dd></div>
        <div><dt className="text-xs text-muted-foreground">提交状态</dt><dd className="mt-1">{originalState}</dd></div>
      </dl>
      </details>
    </section>}

    {readOnlyTask && verifiedTask?.status === 'success' && <section role="status"><p>{taskMessage}</p></section>}
    {readingTask ? <section role="status" aria-live="polite" aria-busy="true" className="rounded-xl border p-6">
      {readOnlyTask ? <h2 className="text-lg font-medium text-balance">正在读取处理进度</h2> : <h1 className="text-lg font-medium text-balance">正在读取处理进度</h1>}
      <p className="mt-2 text-sm text-muted-foreground text-pretty">正在查询原任务，读取后显示实际阶段和处理结果。</p>
    </section> : running ? <GenerateProgress status={status} progress={progress} processedSeconds={transcriptionMeasure?.processed} totalSeconds={transcriptionMeasure?.total ?? analysisMeasure.total} receivedSeconds={analysisMeasure.received} speakerDetectionProgress={analysisMeasure.detection} speakersReady={analysisMeasure.speakersReady} currentStep={currentStep} error={sourceRecoveryCopy(error)} message={sourceRecoveryCopy(taskMessage)} meeting={isMeeting} audioOnlySource={receipt?.sourceType === 'audio' || isBilibiliSourceUrl(receipt?.sourceUrl || videoUrl)} documentSource={receipt?.sourceType === 'file' || uploadMode === 'document'} /> : <>
      {!restoringSource && <section className="border-b py-3">
        <div className="mb-3 flex items-start justify-between gap-4"><div className="flex items-start gap-3"><div><h2 className="text-lg font-semibold">{isMeeting ? '选择会议文件' : '选择笔记来源'}</h2><p className="mt-1 text-sm leading-6 text-muted-foreground">{isMeeting ? '支持音频、视频和已有逐字稿。' : '粘贴网页或视频链接，或上传 PDF、Word、音视频和文字文件。PDF、Word 上限 20 MB，PDF 上限 200 页。'}</p></div></div></div>
        <fieldset disabled={!!receipt || recoveryUnavailable}><FileUploader videoUrl={videoUrl} urlError={visibleSourceError} urlInputRef={sourceInput} onVideoUrlChange={value => { if (!receipt) { setVideoUrl(value); setSourceError('') } }} onFileSelect={value => { if (!receipt) setSelectedFile(value) }} onModeChange={value => { if (!receipt) { setUploadMode(value); setSourceError('') } }} fileUploadEnabled initialMode={uploadMode} file={selectedFile} urlEnabled={!isMeeting} meetingOnly={isMeeting} /></fieldset>
      </section>}

      {!restoringSource && <section className="border-b py-3" style={{ animationDelay: '120ms' }}>
        <div className="flex flex-wrap items-center justify-between gap-4"><div><h2 className="text-lg font-semibold">确认资料</h2></div><Sheet><SheetTrigger asChild><Button variant="outline"><Settings2 />处理设置</Button></SheetTrigger><SheetContent className="overflow-y-auto sm:max-w-md"><SheetHeader><SheetTitle>处理设置</SheetTitle><SheetDescription>查看保存位置，选择转写与总结服务。</SheetDescription></SheetHeader><div className="py-8">{generationSettings}</div></SheetContent></Sheet></div>
        <div className="mt-3 grid border-y sm:grid-cols-2 sm:divide-x">
          <div className="flex min-w-0 items-center gap-3 px-4 py-3"><Check className="size-4 shrink-0 text-muted-foreground" /><div className="min-w-0"><p className="text-xs text-muted-foreground">保存到</p><p className="mt-0.5 truncate text-sm font-medium">{workspaceLabel}</p></div></div>
          <div className="flex min-w-0 items-center gap-3 border-t px-4 py-3 sm:border-t-0">{uploadMode === 'url' ? <LinkIcon className="size-4 shrink-0 text-muted-foreground" /> : <FileAudio className="size-4 shrink-0 text-muted-foreground" />}<div className="min-w-0"><p className="text-xs text-muted-foreground">当前来源</p><p className="mt-0.5 truncate text-sm font-medium">{uploadMode === 'url' ? (videoUrl || '等待粘贴链接') : (selectedFile?.name || '等待选择文件')}</p></div></div>
        </div>
      </section>}

      {import.meta.env.DEV && (receipt || error) && <details className="text-xs text-muted-foreground" aria-label="开发诊断"><summary>开发诊断</summary><div className="mt-2 grid gap-2">{receipt?.operationId && <p>提交编号：{receipt.operationId}</p>}{(receipt?.id || taskId) && <p>任务编号：{receipt?.id || taskId}</p>}<p>网页和 PDF/DOCX 支持提交去重；媒体、逐字稿与首次原件注册尚未覆盖。</p>{error && (readOnlyTask && recordFailure?.outcome !== sourceRecoveryCopy(error) || error !== sourceRecoveryCopy(error)) && <p className="whitespace-pre-wrap">{error}</p>}</div></details>}
      {status === 'failed' ? <Alert variant="destructive"><AlertDescription><p>{recordFailure?.outcome ?? sourceRecoveryCopy(error)}</p><p className="mt-2">{recordFailure?.next ?? (receipt ? recoveryView.explanation : copy.generator.failedRecoveryHint)}</p></AlertDescription><div className="mt-4 flex flex-wrap gap-3"><Button onClick={() => void resumeOriginal()} disabled={recoveryUnavailable || !!recoveryLock.current || (!receipt && !sourceReady)}>{receipt ? recoveryView.action : copy.generator.retryGeneration}</Button>{!readOnlyTask && <Button variant="outline" disabled={readOnlyTask || recoveryUnavailable || !!receipt && (!taskRetryable || receipt.submissionState !== 'accepted')} onClick={handleEditInput}>{receipt ? '更换来源，开始新任务' : copy.generator.editInput}</Button>}{!receipt?.independentGeneration && verifiedTask?.taskId === receipt?.id && ['failed', 'error'].includes(verifiedTask?.status || '') && <Button variant="outline" disabled={newBusy} onClick={() => void openNewGeneration()}>确认原模型，开始新的处理</Button>}{(!readOnlyTask || originalNeedsAttention) && <Button variant="ghost" asChild><Link to={materialsPath} state={{ returnTo: parent }}>返回资料与原文件</Link></Button>}<Button variant="ghost" asChild><Link to={historyPath}>查看处理历史与恢复</Link></Button></div></Alert> : null}

      {status !== 'failed' && !restoringSource && <div className="flex flex-col items-start justify-between gap-4 border-t bg-background py-4 sm:flex-row sm:items-center" style={{ animationDelay: '170ms' }}><div><p className="font-medium">{visibleSourceError ? '请修正来源链接' : sourceReady ? (isMeeting ? '会议文件已准备好' : '来源已准备好') : (isMeeting ? '先选择一个会议文件' : '先提供链接或文件')}</p><p className="mt-1 text-sm text-muted-foreground">{visibleSourceError ? '当前输入已保留，修改链接后再开始整理。' : sourceReady ? '开始后会显示真实处理阶段和失败恢复入口。' : '选好来源后即可开始，模型设置可在上方调整。'}</p></div><Button onClick={() => void handleGenerate()} disabled={status !== 'idle' || !sourceReady} size="lg" className="min-w-52"><Wand2 />{language === 'zh-CN' ? (isMeeting ? '生成会议纪要' : '开始整理') : (isMeeting ? 'Generate meeting minutes' : 'Organize notes')}</Button></div>}
    </>}
  </div>
}
