import { ModelSourcePanel } from "../components/Settings/ModelSourcePanel"
import { useAppModeStore } from "../stores/appModeStore"
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, FileAudio, Link as LinkIcon, Settings2, Wand2 } from 'lucide-react'
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

  return (
    <div className="mx-auto max-w-[1280px] px-6 py-8 lg:px-10">
      <div className="mb-6 flex items-start gap-3 border-b pb-5">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={() => navigate('/')}
          aria-label="返回"
        >
          <ArrowLeft className="w-5 h-5" />
        </Button>
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">{isMeeting ? '导入会议录制' : '整理资料'}</h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            {isMeeting ? '导入已经录制的音频或视频，生成带说话人、时间戳、决策和待办的会议纪要。' : '从链接或文件提取内容，转写并整理为可编辑、可共享的结构化笔记。'}
          </p>
        </div>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section className="grid gap-5 border-t pt-5">
          <div className="flex items-center gap-3"><span className="flex size-9 items-center justify-center border bg-muted"><FileAudio className="size-4" /></span><div><h3 className="text-sm font-semibold">{isMeeting ? '选择会议文件' : '选择内容来源'}</h3><p className="text-xs text-muted-foreground">{isMeeting ? '支持本地音频、视频和逐字稿文件。' : '链接支持网页、文章和公开视频；文件支持音视频、字幕与文本。'}</p></div></div>
        <FileUploader
          videoUrl={videoUrl}
          onVideoUrlChange={setVideoUrl}
          onFileSelect={setSelectedFile}
          onModeChange={setUploadMode}
          fileUploadEnabled={true}
          initialMode={isMeeting ? 'file' : requestedMode}
          urlEnabled={!isMeeting}
        />

        <div className="flex items-start gap-3 border-l-2 border-foreground bg-muted/30 px-4 py-3 text-sm">
          {uploadMode === 'url' ? <LinkIcon className="h-5 w-5 shrink-0" /> : <FileAudio className="h-5 w-5 shrink-0" />}
          <div>
            <p className="font-medium">{language === 'zh-CN' ? (isMeeting ? '输出会议纪要与说话人逐字稿' : '输出结构化笔记') : (isMeeting ? 'Meeting minutes and speaker transcript' : 'Structured note output')}</p>
            <p className="mt-0.5 text-xs opacity-75">{language === 'zh-CN'
              ? (uploadMode === 'url' ? '粘贴网页、文章或公开视频链接；系统会按内容类型提取、转写并整理。' : selectedFile ? `已选择：${selectedFile.name}` : '请选择本地音频、视频、字幕或文字文件。')
              : (uploadMode === 'url' ? 'The video will be downloaded, transcribed, and illustrated with key frames.' : selectedFile ? `Selected: ${selectedFile.name}` : 'Choose a local audio, video, or transcript file.')}</p>
            {uploadMode !== 'transcript' && (
              <p className="mt-1 text-xs opacity-75">
                {language === 'zh-CN' ? '音频与视频会自动降噪并区分说话人，无需设置人数。' : 'Audio and video automatically use denoising and speaker detection.'}
              </p>
            )}
          </div>
        </div>

        </section>
        <aside className="grid gap-4 lg:sticky lg:top-5">
        <section className="grid gap-4 border-l pl-5"><header className="flex items-center gap-3"><span className="flex size-9 items-center justify-center border bg-muted"><Settings2 className="size-4" /></span><h3 className="text-base font-semibold">生成设置</h3></header>
          <div className="border-y py-3">
          <Label className="mb-2 block">
            {copy.generator.saveTargetWorkspace}
          </Label>
          <p className="text-sm text-foreground">{workspaceLabel}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            {copy.generator.saveTargetWorkspaceHint}
          </p>
          </div>

        {cloudMode ? <ModelSourcePanel compact /> : <>
        <div className="mt-4 border-t pt-4">
          <Label className="mb-2 block">{copy.generator.modelProfileLabel}</Label>
          <Select
            value={selectedProfileId || 'system-default'}
            onValueChange={(value) => selectProfile(value === 'system-default' ? '' : value)}
          >
            <SelectTrigger><SelectValue placeholder={copy.generator.systemDefaultModel} /></SelectTrigger>
            <SelectContent><SelectItem value="system-default">{copy.generator.systemDefaultModel}</SelectItem>
            {profiles.map((profile) => (
              <SelectItem key={profile.id} value={profile.id}>
                {profile.name} / {profile.modelName}
                {profile.isDefault ? ' (default)' : ''}
              </SelectItem>
            ))}
            </SelectContent>
          </Select>
          <p className="mt-2 text-sm text-muted-foreground">
            {copy.generator.activeModelPrefix}
            {selectedProfile
              ? copy.generator.activeModelSelected(selectedProfile.name, selectedProfile.modelName)
              : defaultProfile
                ? copy.generator.activeModelDefault(defaultProfile.name, defaultProfile.modelName)
                : copy.generator.activeModelBackend}
          </p>
        </div>

        <div className="mt-4 border-t pt-4">
          <Label className="mb-2 block">{copy.generator.sttProfileLabel}</Label>
          <Select
            value={selectedSTTProfileId || 'system-default'}
            onValueChange={(value) => selectSTTProfile(value === 'system-default' ? '' : value)}
          >
            <SelectTrigger><SelectValue placeholder={copy.generator.systemDefaultSTT} /></SelectTrigger>
            <SelectContent><SelectItem value="system-default">{copy.generator.systemDefaultSTT}</SelectItem>
            {sttProfiles.map((profile) => (
              <SelectItem key={profile.id} value={profile.id}>
                {formatSTTProfileLabel(profile.name, profile)}
                {profile.isDefault ? ' (default)' : ''}
              </SelectItem>
            ))}
            </SelectContent>
          </Select>
          <p className="mt-2 text-sm text-muted-foreground">
            {copy.generator.activeSTTPrefix}
            {selectedSTTProfile
              ? copy.generator.activeSTTSelected(selectedSTTProfile.name, formatSTTProfileLabel(selectedSTTProfile.name, selectedSTTProfile))
              : defaultSTTProfile
                ? copy.generator.activeSTTDefault(defaultSTTProfile.name, formatSTTProfileLabel(defaultSTTProfile.name, defaultSTTProfile))
                : copy.generator.activeSTTBackend}
          </p>
        </div>

        </>}
        <div className="mt-4 border-t pt-4">
          <Label className="mb-2 block">
            {copy.generator.summaryMode}
          </Label>
          <Select
            value={summaryMode}
            onValueChange={(value) => setSummaryMode(value as SummaryMode)}
          >
            <SelectTrigger><SelectValue /></SelectTrigger><SelectContent>
            {summaryModeOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
            </SelectContent>
          </Select>
          <p className="mt-2 text-sm text-muted-foreground">
            {selectedSummaryMode?.description}
          </p>
        </div>

        <Button
          onClick={() => void handleGenerate()}
          disabled={!['idle', 'failed'].includes(status) || (uploadMode === 'url' ? !videoUrl : !selectedFile)}
          className="w-full"
          size="lg"
        >
          <Wand2 className="w-5 h-5" />
          {status === 'uploading' || status === 'processing'
            ? copy.generator.generating
            : language === 'zh-CN'
              ? isMeeting ? '生成会议纪要' : '开始整理'
              : isMeeting ? 'Generate meeting minutes' : 'Organize notes'}
        </Button>

        </section>

        {status === 'failed' ? (
          <Alert variant="destructive">
            <AlertDescription>
              {copy.generator.failedRecoveryHint}
            </AlertDescription>
            <div className="mt-3 flex flex-col gap-2 sm:flex-row">
              <Button
                type="button"
                onClick={() => void handleGenerate()}
                disabled={uploadMode === 'url' ? !videoUrl : !selectedFile}
                className="flex-1"
              >
                {copy.generator.retryGeneration}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={handleEditInput}
                className="flex-1"
              >
                {copy.generator.editInput}
              </Button>
            </div>
          </Alert>
        ) : null}

        <GenerateProgress
          status={status}
          progress={progress}
          currentStep={currentStep}
          error={error}
          message={taskMessage}
        />
        </aside>
      </div>
    </div>
  )
}
