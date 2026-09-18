import { ModelSourcePanel } from "../components/Settings/ModelSourcePanel"
import { useAppModeStore } from "../stores/appModeStore"
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { FileAudio, Link as LinkIcon, Settings2, Wand2, Check, Sparkles } from 'lucide-react'
import { FileUploader, type UploadMode } from '../components/NoteGenerator/FileUploader'
import { GenerateProgress } from '../components/NoteGenerator/GenerateProgress'
import { useI18n } from '../lib/i18n'
import { apiJson } from '../lib/api'
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
import { Badge } from '../components/ui/badge'

type TaskResponse = { task_id: string }
type SummaryMode = 'default' | 'accurate' | 'oneshot'
type TaskStatusResponse = {
  status: string
  message: string
  result?: {
    task_id: string
    title: string
    markdown: string
  }
}

export function NoteGenerator() {
  const [searchParams] = useSearchParams()
  const isMeeting = searchParams.get('meeting') === '1'
  const [videoUrl, setVideoUrl] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const requestedMode = searchParams.get('mode') === 'file' ? 'file' : 'url'
  const [uploadMode, setUploadMode] = useState<UploadMode>(isMeeting ? 'file' : requestedMode)
  const [summaryMode, setSummaryMode] = useState<SummaryMode>('default')
  const [taskMessage, setTaskMessage] = useState('')
  const [, setTaskId] = useState('')
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

  useEffect(() => {
    void loadProfiles()
    void loadSTTProfiles()
    void loadTeams()
  }, [loadProfiles, loadSTTProfiles, loadTeams])

  useEffect(() => {
    reset()

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
      reset()
    }
  }, [reset])

  useEffect(() => {
    setUploadMode(isMeeting ? 'file' : requestedMode)
    setSelectedFile(null)
  }, [isMeeting, requestedMode])

  const pollTaskStatus = (
    id: string,
    workspace = currentWorkspace,
    sourceUrl?: string,
    sourceType?: string,
  ) => {
    pollRef.current = setInterval(async () => {
      try {
        const data = await apiJson<TaskStatusResponse>(`/api/task/${id}`)
        setTaskMessage(data.message || '')

        if (data.status === 'success') {
          clearInterval(pollRef.current!)
          pollRef.current = null
          setProgress(100)
          setCurrentStep('success')
          setStatus('success')

          const note = await saveNote(
            data.result?.title || '',
            data.result?.markdown || '',
            sourceUrl || undefined,
            data.result?.task_id || id,
            workspace,
            isMeeting ? (sourceType === 'video' ? 'meeting_video' : 'meeting_recording') : sourceType,
          )
          if (note) {
            navigate(`/note/${note.id}`)
            return
          }

          setStatus('failed')
          setError(copy.generator.saveFailed)
        } else if (data.status === 'failed' || data.status === 'not_found') {
          clearInterval(pollRef.current!)
          pollRef.current = null
          setStatus('failed')
          setError(data.status === 'not_found'
            ? (language === 'zh-CN' ? '任务记录不存在或已丢失，请重新生成。' : 'Task record is missing. Please try again.')
            : data.message || 'Generation failed')
        } else if (data.status === 'transcribing') {
          setCurrentStep('transcribing')
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
        console.error('Failed to poll task status:', pollError)
        setTaskMessage('暂时无法获取任务进度，正在重试；请勿重复提交。')
      }
    }, 2000)
  }

  const handleGenerate = async () => {
    if ((uploadMode === 'url' && !videoUrl) || (uploadMode !== 'url' && !selectedFile)) {
      return
    }

    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }

    reset()
    setTaskMessage('')
    setStatus('uploading')
    setCurrentStep('uploading')
    setProgress(10)

    try {
      const generationWorkspace = currentWorkspace
      let data: TaskResponse
      const sourceUrl = uploadMode === 'url' ? videoUrl : ''

      if (uploadMode === 'url') {
        setCurrentStep('downloading')
        setProgress(20)
        data = await apiJson<TaskResponse>('/api/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            video_url: videoUrl,
            workflow: isMeeting ? 'meeting' : 'note_organization',
            summary_mode: summaryMode,
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
        const sourceType = uploadMode === 'transcript'
          ? 'transcript'
          : selectedFile.type.startsWith('video/')
            ? 'video'
            : 'audio'

        formData.append('file', selectedFile)
        formData.append('source_type', sourceType)
        formData.append('title', selectedFile.name)
        formData.append('style', isMeeting ? 'meeting' : 'detailed')
        formData.append('workflow', isMeeting ? 'meeting' : 'note_organization')
        formData.append('trace_source', 'local_file')
        if (sourceType !== 'transcript') formData.append('diarize', 'true')
        formData.append('summary_mode', summaryMode)
        formData.append('output_language', language)
        if (selectedProfileId) {
          formData.append('model_profile_id', selectedProfileId)
        }
        if (selectedSTTProfileId) {
          formData.append('stt_profile_id', selectedSTTProfileId)
        }

        data = await apiJson<TaskResponse>('/api/generate_from_upload', {
          method: 'POST',
          body: formData,
        })
      }

      setTaskId(data.task_id)
      setStatus('processing')
      setCurrentStep('transcribing')
      setProgress(30)
      const submittedSourceType = uploadMode === 'transcript'
        ? 'transcript'
        : uploadMode === 'file'
          ? selectedFile?.type.startsWith('video/') ? 'video' : 'audio'
          : undefined
      pollTaskStatus(data.task_id, generationWorkspace, sourceUrl, submittedSourceType)
    } catch (generationError) {
      setStatus('failed')
      setError(generationError instanceof Error ? generationError.message : copy.generator.unknownError)
    }
  }

  const handleEditInput = () => {
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
    copy.sidebar.home,
  )
  const summaryModeOptions: Array<{ value: SummaryMode; label: string; description: string }> = [
    {
      value: 'default' as SummaryMode,
      label: copy.generator.summaryModeDefaultLabel,
      description: copy.generator.summaryModeDefaultDesc,
    },
    {
      value: 'accurate' as SummaryMode,
      label: copy.generator.summaryModeAccurateLabel,
      description: copy.generator.summaryModeAccurateDesc,
    },
    {
      value: 'oneshot' as SummaryMode,
      label: copy.generator.summaryModeOneshotLabel,
      description: copy.generator.summaryModeOneshotDesc,
    },
  ]
  const selectedSummaryMode = summaryModeOptions.find((option) => option.value === summaryMode)
  const formatSTTProfileLabel = (name: string, profile: { provider: string; modelName: string | null; language: string | null }) => {
    const detail = profile.modelName || profile.language || profile.provider
    return `${name} / ${detail}`
  }

  const sourceReady = uploadMode === 'url' ? Boolean(videoUrl.trim()) : Boolean(selectedFile)

  const generationSettings = <div className="grid gap-6">
    <div className="rounded-xl border bg-muted/25 p-4"><Label>{copy.generator.saveTargetWorkspace}</Label><p className="mt-2 text-sm font-medium">{workspaceLabel}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{copy.generator.saveTargetWorkspaceHint}</p></div>
    {cloudMode ? <ModelSourcePanel compact /> : <div className="grid gap-5">
      <div><Label className="mb-2 block">{copy.generator.modelProfileLabel}</Label><Select value={selectedProfileId || 'system-default'} onValueChange={value => selectProfile(value === 'system-default' ? '' : value)}><SelectTrigger><SelectValue placeholder={copy.generator.systemDefaultModel} /></SelectTrigger><SelectContent><SelectItem value="system-default">{copy.generator.systemDefaultModel}</SelectItem>{profiles.map(profile => <SelectItem key={profile.id} value={profile.id}>{profile.name} / {profile.modelName}{profile.isDefault ? ' (default)' : ''}</SelectItem>)}</SelectContent></Select><p className="mt-2 text-xs leading-5 text-muted-foreground">{selectedProfile ? copy.generator.activeModelSelected(selectedProfile.name, selectedProfile.modelName) : defaultProfile ? copy.generator.activeModelDefault(defaultProfile.name, defaultProfile.modelName) : copy.generator.activeModelBackend}</p></div>
      <div><Label className="mb-2 block">{copy.generator.sttProfileLabel}</Label><Select value={selectedSTTProfileId || 'system-default'} onValueChange={value => selectSTTProfile(value === 'system-default' ? '' : value)}><SelectTrigger><SelectValue placeholder={copy.generator.systemDefaultSTT} /></SelectTrigger><SelectContent><SelectItem value="system-default">{copy.generator.systemDefaultSTT}</SelectItem>{sttProfiles.map(profile => <SelectItem key={profile.id} value={profile.id}>{formatSTTProfileLabel(profile.name, profile)}{profile.isDefault ? ' (default)' : ''}</SelectItem>)}</SelectContent></Select><p className="mt-2 text-xs leading-5 text-muted-foreground">{selectedSTTProfile ? copy.generator.activeSTTSelected(selectedSTTProfile.name, formatSTTProfileLabel(selectedSTTProfile.name, selectedSTTProfile)) : defaultSTTProfile ? copy.generator.activeSTTDefault(defaultSTTProfile.name, formatSTTProfileLabel(defaultSTTProfile.name, defaultSTTProfile)) : copy.generator.activeSTTBackend}</p></div>
    </div>}
    <div><Label className="mb-2 block">{copy.generator.summaryMode}</Label><Select value={summaryMode} onValueChange={value => setSummaryMode(value as SummaryMode)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{summaryModeOptions.map(option => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent></Select><p className="mt-2 text-xs leading-5 text-muted-foreground">{selectedSummaryMode?.description}</p></div>
  </div>

  const running = status === 'uploading' || status === 'processing'

  return <div className="mx-auto flex min-h-full max-w-[960px] flex-col gap-7 px-6 py-8 pb-24 lg:px-8">
    <header className="motion-rise max-w-2xl">
      <Badge variant="secondary" className="mb-3">{isMeeting ? '会议导入' : '资料整理'}</Badge>
      <h1 className="text-3xl font-semibold tracking-[-0.03em]">{isMeeting ? '从已有录制生成会议纪要' : '整理一份资料'}</h1>
      <p className="mt-2 text-[15px] leading-6 text-muted-foreground">{isMeeting ? '选择音频、视频或逐字稿。系统会完成转写、说话人整理和纪要生成。' : '先选择来源，再确认处理方式。完成后直接进入编辑器继续修改和分享。'}</p>
    </header>

    {running ? <section className="motion-rise overflow-hidden rounded-2xl border bg-card shadow-sm">
      <div className="border-b bg-muted/20 px-6 py-5"><div className="flex items-center gap-3"><span className="relative flex size-3"><span className="absolute inline-flex size-full animate-ping rounded-full bg-foreground/40" /><span className="relative inline-flex size-3 rounded-full bg-foreground" /></span><div><h2 className="text-lg font-semibold">{isMeeting ? '正在生成会议纪要' : '正在整理资料'}</h2><p className="mt-1 text-sm text-muted-foreground">处理期间可以留在此页查看每个阶段。</p></div></div></div>
      <div className="p-6"><GenerateProgress status={status} progress={progress} currentStep={currentStep} error={error} message={taskMessage} /></div>
    </section> : <>
      <section className="motion-rise rounded-2xl border bg-card p-6 shadow-sm sm:p-7" style={{ animationDelay: '70ms' }}>
        <div className="mb-5 flex items-start justify-between gap-4"><div className="flex items-start gap-3"><div className="grid size-9 shrink-0 place-items-center rounded-xl bg-foreground text-background">{isMeeting ? <FileAudio className="size-4" /> : <Sparkles className="size-4" />}</div><div><h2 className="text-lg font-semibold">{isMeeting ? '选择会议文件' : '资料从哪里来？'}</h2><p className="mt-1 text-sm leading-6 text-muted-foreground">{isMeeting ? '支持音频、视频和已有逐字稿。' : '链接适合网页、文章和公开视频；文件适合音视频、字幕和文本。'}</p></div></div><span className="shrink-0 rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">1 / 2</span></div>
        <FileUploader videoUrl={videoUrl} onVideoUrlChange={setVideoUrl} onFileSelect={setSelectedFile} onModeChange={setUploadMode} fileUploadEnabled initialMode={isMeeting ? 'file' : requestedMode} urlEnabled={!isMeeting} />
      </section>

      <section className="motion-rise rounded-2xl border bg-card p-6 shadow-sm sm:p-7" style={{ animationDelay: '120ms' }}>
        <div className="flex flex-wrap items-center justify-between gap-4"><div><h2 className="text-lg font-semibold">确认整理方式</h2><p className="mt-1 text-sm leading-6 text-muted-foreground">确认保存位置和处理模式后即可开始。</p></div><Sheet><SheetTrigger asChild><Button variant="outline"><Settings2 />处理设置</Button></SheetTrigger><SheetContent className="overflow-y-auto sm:max-w-md"><SheetHeader><SheetTitle>处理设置</SheetTitle><SheetDescription>设置保存位置、转写模型和笔记生成方式。</SheetDescription></SheetHeader><div className="py-8">{generationSettings}</div></SheetContent></Sheet></div>
        <div className="mt-5 grid overflow-hidden rounded-xl border sm:grid-cols-3 sm:divide-x">
          <div className="flex min-w-0 items-center gap-3 px-4 py-3"><Check className="size-4 shrink-0 text-muted-foreground" /><div className="min-w-0"><p className="text-xs text-muted-foreground">保存到</p><p className="mt-0.5 truncate text-sm font-medium">{workspaceLabel}</p></div></div>
          <div className="flex min-w-0 items-center gap-3 border-t px-4 py-3 sm:border-t-0"><Check className="size-4 shrink-0 text-muted-foreground" /><div className="min-w-0"><p className="text-xs text-muted-foreground">整理方式</p><p className="mt-0.5 truncate text-sm font-medium">{selectedSummaryMode?.label}</p></div></div>
          <div className="flex min-w-0 items-center gap-3 border-t px-4 py-3 sm:border-t-0">{uploadMode === 'url' ? <LinkIcon className="size-4 shrink-0 text-muted-foreground" /> : <FileAudio className="size-4 shrink-0 text-muted-foreground" />}<div className="min-w-0"><p className="text-xs text-muted-foreground">当前来源</p><p className="mt-0.5 truncate text-sm font-medium">{uploadMode === 'url' ? (videoUrl || '等待粘贴链接') : (selectedFile?.name || '等待选择文件')}</p></div></div>
        </div>
      </section>

      {status === 'failed' ? <Alert variant="destructive"><AlertDescription>{copy.generator.failedRecoveryHint}</AlertDescription><div className="mt-4 flex gap-3"><Button onClick={() => void handleGenerate()} disabled={!sourceReady}>{copy.generator.retryGeneration}</Button><Button variant="outline" onClick={handleEditInput}>{copy.generator.editInput}</Button></div></Alert> : null}

      <div className="motion-rise flex flex-col items-center justify-between gap-4 rounded-2xl bg-foreground px-6 py-5 text-background sm:flex-row" style={{ animationDelay: '170ms' }}><div><p className="font-medium">{sourceReady ? (isMeeting ? '会议文件已准备好' : '资料已准备好') : (isMeeting ? '先选择一个会议文件' : '先提供链接或文件')}</p><p className="mt-1 text-sm text-background/60">{sourceReady ? '开始后会显示真实处理阶段和失败恢复入口。' : '选好来源后即可开始，模型设置可在上方调整。'}</p></div><Button onClick={() => void handleGenerate()} disabled={!['idle', 'failed'].includes(status) || !sourceReady} variant="secondary" size="lg" className="motion-sheen min-w-52 rounded-full"><Wand2 />{language === 'zh-CN' ? (isMeeting ? '生成会议纪要' : '开始整理') : (isMeeting ? 'Generate meeting minutes' : 'Organize notes')}</Button></div>
    </>}
  </div>
}
