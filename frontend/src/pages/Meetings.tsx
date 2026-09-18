import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileText, Mic2, Monitor, Settings2, Sparkles, Upload, Volume2 } from 'lucide-react'
import { apiJson } from '../lib/api'
import { listPendingMeetings, type PendingMeeting } from '../lib/audioStorage'
import { acquireMeetingMicrophone, DEFAULT_CAPTURE_OPTIONS, START_MEETING_EVENT } from '../lib/meetingCapture'
import { mapMicrophoneError } from '../lib/microphonePermission'
import { useAuthStore } from '../stores/authStore'
import { isMeetingBusy, useMeetingRecorderStore } from '../stores/meetingRecorderStore'
import { useNoteLibraryStore } from '../stores/noteLibraryStore'
import { getWorkspaceLabel, useTeamStore } from '../stores/teamStore'
import { useI18n } from '../lib/i18n'
import { LocalRecordingCard } from '../components/MeetingRecorder/LocalRecordingCard'
import { NoteGrid } from '../components/Notes/NoteGrid'
import { ModelSourcePanel } from '../components/Settings/ModelSourcePanel'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Field, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { MeetingCaptureWorkspace } from '../components/MeetingRecorder/MeetingCaptureWorkspace'

const capturePhases = ['requesting', 'recording', 'paused', 'stopping']

export function Meetings() {
  const userId = useAuthStore(state => state.user?.id)
  const [pending, setPending] = useState<PendingMeeting[]>([])
  const [options, setOptions] = useState(DEFAULT_CAPTURE_OPTIONS)
  const [mode, setMode] = useState<'recording' | 'minutes'>('recording')
  const [meetingType, setMeetingType] = useState<'audio' | 'video'>('audio')
  const [diarizationReady, setDiarizationReady] = useState<boolean | null>(null)
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const { notes, loading, loadNotes } = useNoteLibraryStore()
  const { currentWorkspace, teams } = useTeamStore()
  const session = useMeetingRecorderStore()
  const isCapturing = capturePhases.includes(session.phase)
  const busy = isMeetingBusy(session)
  const workspace = getWorkspaceLabel(currentWorkspace, teams, zh ? '个人空间' : 'Personal workspace')
  const workspacePending = pending.filter(item => item.workspace.scope === currentWorkspace.scope && (item.workspace.scope === 'personal' || currentWorkspace.scope === 'team' && item.workspace.teamId === currentWorkspace.teamId))
  const meetingNotes = notes.filter(note => ['meeting_recording', 'meeting_video'].includes(note.sourceType || ''))

  useEffect(() => {
    void loadNotes(currentWorkspace)
    let active = true
    setPending([])
    if (userId) void listPendingMeetings(userId).then(items => { if (active) setPending(items) }).catch(() => { if (active) setError(zh ? '无法读取本地录制。' : 'Cannot load local recordings.') })
    return () => { active = false }
  }, [currentWorkspace, loadNotes, session.phase, userId, zh])
  useEffect(() => { void apiJson<{ diarization: { available: boolean } }>('/api/meeting-capabilities').then(result => setDiarizationReady(result.diarization.available)).catch(() => setDiarizationReady(false)) }, [])
  useEffect(() => {
    const refresh = () => { void navigator.mediaDevices?.enumerateDevices().then(items => setDevices(items.filter(item => item.kind === 'audioinput'))).catch(() => undefined) }
    refresh()
    navigator.mediaDevices?.addEventListener('devicechange', refresh)
    return () => navigator.mediaDevices?.removeEventListener('devicechange', refresh)
  }, [])

  const refreshDevices = async () => {
    setError('')
    try {
      const stream = await acquireMeetingMicrophone(options.microphoneId)
      stream.getTracks().forEach(track => track.stop())
      const nextDevices = (await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === 'audioinput')
      setDevices(nextDevices)
      if (options.microphoneId && !nextDevices.some(device => device.deviceId === options.microphoneId)) {
        setOptions(current => ({ ...current, microphoneId: '' }))
      }
    } catch (deviceError) {
      const reason = mapMicrophoneError(deviceError)
      setError(reason === 'denied'
        ? (zh ? '麦克风权限未开启，请在 Windows 隐私设置中允许 VINote 使用麦克风。' : 'Microphone permission is disabled. Allow VINote to use it in Windows privacy settings.')
        : reason === 'no-device'
          ? (zh ? '没有检测到可用的麦克风，请重新连接耳机后检测。' : 'No microphone was detected. Reconnect the headset and check again.')
          : (zh ? '暂时无法启动这个麦克风。请重新检测，或改用“系统默认麦克风”。' : 'This microphone could not start. Check again or use the system default microphone.'))
    }
  }
  const startRecording = () => {
    if (busy) return
    setError('')
    const nextOptions = {
      ...options,
      sessionId: crypto.randomUUID(),
      mode,
      meetingType,
      screen: meetingType === 'video',
      // The microphone is the required meeting audio source. Screen capture must
      // never be blocked by optional WebView/Windows system-audio capture.
      systemAudio: false,
      diarize: true,
      speakerCount: undefined,
    }
    setOptions(nextOptions)
    window.dispatchEvent(new CustomEvent(START_MEETING_EVENT, { detail: nextOptions }))
  }

  return <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-8 px-6 py-8 pb-24 xl:px-8">
    <header className="motion-rise flex flex-wrap items-start justify-between gap-6">
      <div className="max-w-2xl"><div className="mb-2 text-sm text-muted-foreground">{workspace}</div><h1 className="text-3xl font-semibold tracking-[-0.03em]">{isCapturing ? (session.phase === 'requesting' ? (zh ? '正在准备录制' : 'Preparing recording') : session.phase === 'stopping' ? (zh ? '正在保存录制' : 'Saving recording') : (zh ? '会议正在进行' : 'Meeting in progress')) : (zh ? '开始一次会议' : 'Start a meeting')}</h1><p className="mt-3 text-[15px] leading-6 text-muted-foreground">{isCapturing ? (zh ? '专注讨论即可。录制结束后会先保存到本机，再由你决定是否生成会议纪要。' : 'Focus on the conversation. Save first, then decide whether to generate notes.') : (zh ? '检查声音和录制范围，然后开始。结束后可回放、下载或生成带说话人的会议纪要。' : 'Check sound and capture scope, then start.')}</p></div>
      {!isCapturing ? <div className="flex items-center gap-3"><Sheet><SheetTrigger asChild><Button variant="outline" size="lg"><Settings2 data-icon="inline-start" />{zh ? '处理设置' : 'Processing settings'}</Button></SheetTrigger><SheetContent className="w-full overflow-y-auto sm:max-w-md"><SheetHeader><SheetTitle>{zh ? '转写与总结设置' : 'Transcription and summary settings'}</SheetTitle><SheetDescription>{zh ? '选择主动生成会议纪要时使用的转写与总结服务。' : 'Choose the transcription and summary services used to generate meeting notes.'}</SheetDescription></SheetHeader><div className="mt-7"><ModelSourcePanel compact /></div></SheetContent></Sheet><Button variant="outline" size="lg" onClick={() => navigate('/generate?meeting=1')}><Upload data-icon="inline-start" />{zh ? '导入已有录制' : 'Import recording'}</Button></div> : null}
    </header>

    {isCapturing ? <MeetingCaptureWorkspace title={options.title} /> : <section className="motion-rise mx-auto w-full max-w-[1180px]" style={{ animationDelay: '70ms' }}>
      <article className="overflow-hidden rounded-[1.75rem] border bg-card shadow-[0_18px_60px_-42px_rgba(0,0,0,0.35)]">
        <div className="border-b px-6 py-6 sm:px-8 lg:px-10">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div><h2 className="text-xl font-semibold tracking-tight">{zh ? '设置这次会议' : 'Set up this meeting'}</h2><p className="mt-1.5 text-sm leading-6 text-muted-foreground">{zh ? '按顺序选择用途、录制范围和声音设备。' : 'Choose the purpose, capture range and audio device.'}</p></div>
            <Badge variant="secondary" className="max-w-full truncate px-3 py-1">{workspace}</Badge>
          </div>
        </div>

        <div className="grid min-w-0 gap-0 min-[1080px]:grid-cols-[minmax(0,1.18fr)_minmax(360px,0.82fr)]">
          <div className="flex min-w-0 flex-col gap-10 px-6 py-8 sm:px-8 lg:px-10 min-[1080px]:border-r">
            <section className="min-w-0">
              <div className="mb-5 flex items-start gap-4"><span className="grid size-8 shrink-0 place-items-center rounded-full bg-foreground text-sm font-semibold text-background">1</span><div className="min-w-0"><h3 className="font-semibold">{zh ? '选择工作方式' : 'Choose a workflow'}</h3><p className="mt-1 text-sm leading-6 text-muted-foreground">{zh ? '只保留原始记录，或同时实时转写并生成纪要。' : 'Keep the recording only, or transcribe live and generate notes.'}</p></div></div>
              <ToggleGroup type="single" value={mode} onValueChange={value => value && setMode(value as 'recording' | 'minutes')} className="grid min-w-0 gap-3 sm:grid-cols-2">
                <ToggleGroupItem value="recording" className="h-auto min-h-32 min-w-0 items-start justify-start whitespace-normal rounded-2xl border p-5 text-left data-[state=on]:border-foreground data-[state=on]:bg-foreground data-[state=on]:text-background"><span className="flex min-w-0 items-start gap-4"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-muted text-foreground"><Volume2 className="size-5" /></span><span className="min-w-0"><strong className="block text-base leading-6">{zh ? '会议记录' : 'Meeting recording'}</strong><span className="mt-1.5 block text-sm leading-6 opacity-70">{zh ? '保存音频或屏幕录像，之后再决定如何使用。' : 'Save audio or screen video for later use.'}</span></span></span></ToggleGroupItem>
                <ToggleGroupItem value="minutes" className="h-auto min-h-32 min-w-0 items-start justify-start whitespace-normal rounded-2xl border p-5 text-left data-[state=on]:border-foreground data-[state=on]:bg-foreground data-[state=on]:text-background"><span className="flex min-w-0 items-start gap-4"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-muted text-foreground"><Sparkles className="size-5" /></span><span className="min-w-0"><strong className="block text-base leading-6">{zh ? '生成会议纪要' : 'Generate meeting notes'}</strong><span className="mt-1.5 block text-sm leading-6 opacity-70">{zh ? '录制时实时转写，结束后根据逐字稿生成纪要。' : 'Transcribe live and generate notes when finished.'}</span></span></span></ToggleGroupItem>
              </ToggleGroup>
            </section>

            <section className="min-w-0">
              <div className="mb-5 flex items-start gap-4"><span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-sm font-semibold">2</span><div className="min-w-0"><h3 className="font-semibold">{zh ? '选择录制范围' : 'Choose the capture range'}</h3><p className="mt-1 text-sm leading-6 text-muted-foreground">{zh ? '录音只采集麦克风；录屏会让你选择屏幕或窗口。' : 'Audio captures the microphone; screen recording opens the picker.'}</p></div></div>
              <ToggleGroup type="single" value={meetingType} onValueChange={value => value && setMeetingType(value as 'audio' | 'video')} className="grid min-w-0 gap-3 sm:grid-cols-2">
                <ToggleGroupItem value="audio" className="h-auto min-h-24 min-w-0 items-start justify-start whitespace-normal rounded-2xl border p-4 text-left data-[state=on]:border-foreground data-[state=on]:bg-muted"><span className="flex min-w-0 items-start gap-3"><span className="grid size-9 shrink-0 place-items-center rounded-xl bg-background shadow-sm"><Mic2 className="size-4" /></span><span className="min-w-0"><strong className="block leading-6">{mode === 'minutes' ? (zh ? '语音会议' : 'Audio meeting') : (zh ? '仅录音' : 'Audio only')}</strong><span className="mt-1 block text-xs leading-5 text-muted-foreground">{zh ? '使用麦克风记录现场声音' : 'Capture sound from the microphone'}</span></span></span></ToggleGroupItem>
                <ToggleGroupItem value="video" className="h-auto min-h-24 min-w-0 items-start justify-start whitespace-normal rounded-2xl border p-4 text-left data-[state=on]:border-foreground data-[state=on]:bg-muted"><span className="flex min-w-0 items-start gap-3"><span className="grid size-9 shrink-0 place-items-center rounded-xl bg-background shadow-sm"><Monitor className="size-4" /></span><span className="min-w-0"><strong className="block leading-6">{mode === 'minutes' ? (zh ? '视频会议' : 'Video meeting') : (zh ? '录音和屏幕' : 'Audio and screen')}</strong><span className="mt-1 block text-xs leading-5 text-muted-foreground">{zh ? '记录屏幕画面，并通过麦克风收录现场可听声音' : 'Capture the screen and audible meeting sound through the microphone'}</span></span></span></ToggleGroupItem>
              </ToggleGroup>
            </section>
          </div>

          <div className="flex min-w-0 flex-col gap-8 bg-muted/[0.16] px-6 py-8 sm:px-8 lg:px-10">
            <section className="min-w-0">
              <div className="mb-5 flex items-start gap-4"><span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-sm font-semibold">3</span><div className="min-w-0"><h3 className="font-semibold">{zh ? '确认会议信息' : 'Confirm meeting details'}</h3><p className="mt-1 text-sm leading-6 text-muted-foreground">{zh ? '名称可以留空，保存后仍可修改。' : 'The name is optional and can be changed later.'}</p></div></div>
              <Field><FieldLabel>{zh ? '会议名称（可选）' : 'Meeting name (optional)'}</FieldLabel><Input className="h-12 min-w-0" maxLength={160} disabled={busy} value={options.title} onChange={event => setOptions({ ...options, title: event.target.value })} placeholder={zh ? '例如：产品方案评审' : 'e.g. Product review'} /></Field>
            </section>
            <section className="min-w-0 border-t pt-7">
              <Field><div className="flex flex-wrap items-center justify-between gap-2"><FieldLabel>{zh ? '麦克风' : 'Microphone'}</FieldLabel><Button variant="ghost" size="sm" className="shrink-0" disabled={busy} onClick={() => void refreshDevices()}>{zh ? '检测设备' : 'Check device'}</Button></div><Select disabled={busy} value={options.microphoneId || 'default'} onValueChange={value => setOptions({ ...options, microphoneId: value === 'default' ? '' : value })}><SelectTrigger className="h-12 min-w-0"><SelectValue className="truncate" /></SelectTrigger><SelectContent><SelectItem value="default">{zh ? '系统默认麦克风' : 'Default microphone'}</SelectItem>{devices.filter(device => device.deviceId && device.deviceId !== 'default').map((device, index) => <SelectItem key={device.deviceId} value={device.deviceId}>{device.label || 'Microphone ' + String(index + 1)}</SelectItem>)}</SelectContent></Select></Field>
              <p className="mt-4 text-sm leading-6 text-muted-foreground">{meetingType === 'video' ? (zh ? '麦克风会记录你和现场可听到的会议声音；屏幕选择只决定录制哪部分画面。' : 'The microphone captures audible meeting sound; screen selection only chooses the picture.') : mode === 'minutes' ? (zh ? '实时转写服务异常时，本地录制仍会继续并安全保存。' : 'Local recording continues if live transcription is unavailable.') : (zh ? '结束后可回放、下载、复制、分享或稍后生成纪要。' : 'Replay, download, copy, share or generate notes later.')}</p>
            </section>
          </div>
        </div>

        <div className="border-t px-6 py-5 sm:px-8 lg:px-10">{diarizationReady === false ? <Alert className="mb-4"><AlertDescription>{zh ? '说话人识别服务当前不可用，但仍可正常录制并稍后重试生成。' : 'Speaker identification is unavailable, but recording still works.'}</AlertDescription></Alert> : null}{error || session.error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error || session.error}</AlertDescription></Alert> : null}<div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><p className="font-medium">{mode === 'minutes' ? (zh ? '实时转写并生成会议纪要' : 'Transcribe and generate meeting notes') : (zh ? '保存会议记录' : 'Save meeting recording')}</p><p className="mt-1 text-sm leading-6 text-muted-foreground">{meetingType === 'video' ? (zh ? '下一步只需选择要录制的屏幕或窗口；声音由当前麦克风记录。' : 'Next, choose a screen or window. Sound is recorded by the microphone.') : zh ? '保存到 ' + workspace + '，录制结束前不会上传媒体。' : 'Save to ' + workspace + '. Media is not uploaded before recording ends.'}</p></div><Button size="lg" disabled={busy} className="motion-sheen h-12 w-full shrink-0 rounded-full px-7 sm:w-auto sm:min-w-52" onClick={startRecording}><Mic2 data-icon="inline-start" />{mode === 'minutes' ? meetingType === 'video' ? (zh ? '选择屏幕并开始' : 'Choose screen and start') : (zh ? '开始语音会议' : 'Start audio meeting') : meetingType === 'video' ? (zh ? '选择屏幕并开始' : 'Choose screen and start') : (zh ? '开始录音' : 'Start audio recording')}</Button></div></div>
      </article>
    </section>}

    {!isCapturing ? <section className="motion-rise space-y-6" style={{ animationDelay: '140ms' }}><div><h2 className="text-2xl font-semibold tracking-tight">{zh ? '最近的会议内容' : 'Recent meeting content'}</h2><p className="mt-2 text-sm text-muted-foreground">{zh ? '录制先保存在本机；需要时再生成会议纪要。' : 'Recordings stay local until you generate notes.'}</p></div><Tabs defaultValue="recordings" className="grid gap-6"><TabsList className="w-fit"><TabsTrigger value="recordings">{zh ? '本地录制' : 'Local recordings'}<Badge variant="secondary" className="ml-2">{workspacePending.length}</Badge></TabsTrigger><TabsTrigger value="notes">{zh ? '会议纪要' : 'Meeting notes'}<Badge variant="secondary" className="ml-2">{meetingNotes.length}</Badge></TabsTrigger></TabsList><TabsContent value="recordings" className="m-0 grid gap-4 sm:grid-cols-2">{workspacePending.map(item => <LocalRecordingCard key={item.id} recording={item} busy={busy} generating={session.recordingId === item.id && ['uploading', 'transcribing', 'summarizing', 'saving'].includes(session.phase)} generationError={session.recordingId === item.id && session.phase === 'failed' ? session.error : undefined} onDeleted={() => setPending(items => items.filter(entry => entry.id !== item.id))} />)}{workspacePending.length === 0 ? <div className="rounded-[1.75rem] border border-dashed bg-muted/10 sm:col-span-2"><Empty><EmptyHeader><EmptyMedia variant="icon"><FileText /></EmptyMedia><EmptyTitle>{zh ? '还没有本地录制' : 'No local recordings'}</EmptyTitle><EmptyDescription>{zh ? '结束录制后会保存在这里，可回放、下载或生成会议纪要。' : 'Finished recordings appear here.'}</EmptyDescription></EmptyHeader></Empty></div> : null}</TabsContent><TabsContent value="notes" className="m-0"><NoteGrid notes={meetingNotes} loading={loading} emptyTitle={zh ? '还没有会议纪要' : 'No meeting notes yet'} emptyBody={zh ? '从本地录制生成，或导入已有会议文件。' : 'Generate from a local recording or import a meeting.'} onOpen={note => navigate('/note/' + note.id)} /></TabsContent></Tabs></section> : null}
  </div>
}
