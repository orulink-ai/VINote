import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AudioLines, FileText, Mic2, Monitor, RotateCcw, Settings2, Sparkles, Upload, Volume2 } from 'lucide-react'
import { apiJson } from '../lib/api'
import { listPendingMeetings, type PendingMeeting } from '../lib/audioStorage'
import { acquireMeetingMicrophone, DISPLAY_CAPTURE_FAILED, DEFAULT_CAPTURE_OPTIONS, START_MEETING_EVENT, SYSTEM_AUDIO_UNAVAILABLE } from '../lib/meetingCapture'
import { mapMicrophoneError } from '../lib/microphonePermission'
import { useAuthStore } from '../stores/authStore'
import { useMeetingRecorderStore } from '../stores/meetingRecorderStore'
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
  const busy = !['idle', 'completed', 'failed'].includes(session.phase) || session.hasRecoverableRecording
  const workspace = getWorkspaceLabel(currentWorkspace, teams, zh ? '个人空间' : 'Personal workspace')
  const workspacePending = pending.filter(item => item.workspace.scope === currentWorkspace.scope && (item.workspace.scope === 'personal' || currentWorkspace.scope === 'team' && item.workspace.teamId === currentWorkspace.teamId))
  const meetingNotes = notes.filter(note => ['meeting_recording', 'meeting_video'].includes(note.sourceType || ''))
  const displayFailed = Boolean(session.error?.includes(DISPLAY_CAPTURE_FAILED))
  const needsAudioFallback = displayFailed || Boolean(session.error?.includes(SYSTEM_AUDIO_UNAVAILABLE))

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
  const startRecording = (systemAudio = true) => {
    if (busy) return
    setError('')
    const nextOptions = {
      ...options,
      sessionId: crypto.randomUUID(),
      mode,
      meetingType,
      screen: meetingType === 'video',
      systemAudio: meetingType === 'video' ? systemAudio : false,
      diarize: true,
      speakerCount: undefined,
    }
    setOptions(nextOptions)
    window.dispatchEvent(new CustomEvent(START_MEETING_EVENT, { detail: nextOptions }))
  }

  return <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-8 px-6 py-8 pb-24 xl:px-8">
    <header className="motion-rise flex flex-wrap items-start justify-between gap-6">
      <div className="max-w-2xl"><div className="mb-2 text-sm text-muted-foreground">{workspace}</div><h1 className="text-3xl font-semibold tracking-[-0.03em]">{isCapturing ? (session.phase === 'requesting' ? (zh ? '正在准备录制' : 'Preparing recording') : session.phase === 'stopping' ? (zh ? '正在保存录制' : 'Saving recording') : (zh ? '会议正在进行' : 'Meeting in progress')) : (zh ? '开始一次会议' : 'Start a meeting')}</h1><p className="mt-3 text-[15px] leading-6 text-muted-foreground">{isCapturing ? (zh ? '专注讨论即可。录制结束后会先保存到本机，再由你决定是否生成会议纪要。' : 'Focus on the conversation. Save first, then decide whether to generate notes.') : (zh ? '检查声音和录制范围，然后开始。结束后可回放、下载或生成带说话人的会议纪要。' : 'Check sound and capture scope, then start.')}</p></div>
      {!isCapturing ? <div className="flex items-center gap-3"><Sheet><SheetTrigger asChild><Button variant="outline" size="lg"><Settings2 />{zh ? '处理设置' : 'Processing settings'}</Button></SheetTrigger><SheetContent className="w-full overflow-y-auto sm:max-w-md"><SheetHeader><SheetTitle>{zh ? '转写与总结设置' : 'Transcription and summary settings'}</SheetTitle><SheetDescription>{zh ? '选择主动生成会议纪要时使用的转写与总结服务。' : 'Choose the transcription and summary services used to generate meeting notes.'}</SheetDescription></SheetHeader><div className="mt-7"><ModelSourcePanel compact /></div></SheetContent></Sheet><Button variant="outline" size="lg" onClick={() => navigate('/generate?meeting=1')}><Upload />{zh ? '导入已有录制' : 'Import recording'}</Button></div> : null}
    </header>

    {isCapturing ? <MeetingCaptureWorkspace title={options.title} /> : <section className="motion-rise grid gap-7" style={{ animationDelay: '70ms' }}>
      <article className="interactive-card rounded-2xl border bg-card p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-5"><div><h2 className="text-xl font-semibold">{zh ? '这次会议要做什么？' : 'What should this meeting do?'}</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">{zh ? '先选择工作方式，再选择声音和画面范围。' : 'Choose the workflow, then the capture range.'}</p></div><Badge variant="secondary">{workspace}</Badge></div>
        <ToggleGroup type="single" value={mode} onValueChange={value => value && setMode(value as 'recording' | 'minutes')} className="mt-6 grid gap-4 md:grid-cols-2">
          <ToggleGroupItem value="recording" className="h-auto min-h-28 justify-start rounded-2xl border p-5 text-left data-[state=on]:border-foreground data-[state=on]:bg-foreground data-[state=on]:text-background"><span className="flex items-start gap-4"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-muted text-foreground"><Volume2 className="size-5" /></span><span><strong className="block text-base">{zh ? '会议记录' : 'Meeting recording'}</strong><span className="mt-1 block text-sm leading-6 opacity-70">{zh ? '只保存音频或视频，不自动转写和总结。' : 'Save audio or video without automatic processing.'}</span></span></span></ToggleGroupItem>
          <ToggleGroupItem value="minutes" className="h-auto min-h-28 justify-start rounded-2xl border p-5 text-left data-[state=on]:border-foreground data-[state=on]:bg-foreground data-[state=on]:text-background"><span className="flex items-start gap-4"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-muted text-foreground"><Sparkles className="size-5" /></span><span><strong className="block text-base">{zh ? '生成会议纪要' : 'Generate meeting notes'}</strong><span className="mt-1 block text-sm leading-6 opacity-70">{zh ? '边录边实时转写，结束后直接生成纪要。' : 'Transcribe live and generate notes when finished.'}</span></span></span></ToggleGroupItem>
        </ToggleGroup>
      </article>
      <div className="grid gap-7 lg:grid-cols-2">
        <article className="interactive-card rounded-2xl border bg-card p-6 shadow-sm"><div className="flex items-start justify-between gap-5"><div><div className="mb-4 grid size-10 place-items-center rounded-xl bg-foreground text-background"><FileText className="size-5" /></div><h2 className="text-xl font-semibold">{zh ? '会议信息' : 'Meeting details'}</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">{zh ? '给录制起一个容易查找的名字。' : 'Give the recording a searchable name.'}</p></div></div><div className="mt-6 space-y-5"><Field><FieldLabel>{zh ? '会议名称（可选）' : 'Meeting name (optional)'}</FieldLabel><Input className="h-12" maxLength={160} disabled={busy} value={options.title} onChange={event => setOptions({ ...options, title: event.target.value })} placeholder={zh ? '例如：产品方案评审' : 'e.g. Product review'} /></Field><p className="text-sm leading-6 text-muted-foreground">{mode === 'minutes' ? (zh ? '实时转写失败也不会中断本地录制。' : 'Local recording continues if live transcription fails.') : (zh ? '结束后可回放、下载、分享或稍后生成纪要。' : 'Replay, download, share or generate notes later.')}</p></div></article>
        <article className="interactive-card rounded-2xl border bg-card p-6 shadow-sm"><div><div className="mb-4 grid size-10 place-items-center rounded-xl bg-muted"><AudioLines className="size-5" /></div><h2 className="text-xl font-semibold">{zh ? '录制方式' : 'Capture type'}</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">{zh ? '音频会议只用麦克风；视频会议会打开屏幕选择器。' : 'Audio uses the microphone; video opens the screen picker.'}</p></div><div className="mt-6 space-y-5"><ToggleGroup type="single" value={meetingType} onValueChange={value => value && setMeetingType(value as 'audio' | 'video')} className="grid grid-cols-2 gap-3"><ToggleGroupItem value="audio" className="h-20 rounded-xl border data-[state=on]:border-foreground data-[state=on]:bg-muted"><Mic2 className="mr-2 size-5" />{mode === 'minutes' ? (zh ? '语音会议' : 'Audio meeting') : (zh ? '仅录音' : 'Audio only')}</ToggleGroupItem><ToggleGroupItem value="video" className="h-20 rounded-xl border data-[state=on]:border-foreground data-[state=on]:bg-muted"><Monitor className="mr-2 size-5" />{mode === 'minutes' ? (zh ? '视频会议' : 'Video meeting') : (zh ? '录音 + 屏幕' : 'Audio + screen')}</ToggleGroupItem></ToggleGroup><Field><div className="flex items-center justify-between gap-3"><FieldLabel>{zh ? '麦克风' : 'Microphone'}</FieldLabel><Button variant="ghost" size="sm" disabled={busy} onClick={() => void refreshDevices()}>{zh ? '检测设备' : 'Check device'}</Button></div><Select disabled={busy} value={options.microphoneId || 'default'} onValueChange={value => setOptions({ ...options, microphoneId: value === 'default' ? '' : value })}><SelectTrigger className="h-12"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="default">{zh ? '系统默认麦克风' : 'Default microphone'}</SelectItem>{devices.filter(device => device.deviceId && device.deviceId !== 'default').map((device, index) => <SelectItem key={device.deviceId} value={device.deviceId}>{device.label || 'Microphone ' + String(index + 1)}</SelectItem>)}</SelectContent></Select></Field></div></article>
      </div>
      <div className="lg:col-span-2">{diarizationReady === false ? <Alert className="mb-4"><AlertDescription>{zh ? '说话人识别服务当前不可用，但仍可正常录制并稍后重试生成。' : 'Speaker identification is unavailable, but recording still works.'}</AlertDescription></Alert> : null}{error || (session.error && !needsAudioFallback) ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error || session.error}</AlertDescription></Alert> : null}{needsAudioFallback ? <Alert className="motion-rise p-5"><AudioLines /><AlertDescription className="flex flex-col gap-4"><div className="flex flex-col gap-1"><strong className="text-base text-foreground">{displayFailed ? (zh ? '屏幕共享未能启动' : 'Screen sharing could not start') : (zh ? '当前共享未包含电脑音频' : 'The current share does not include computer audio')}</strong><span className="leading-6">{zh ? '这和你现在有没有说话无关，静音或会议停顿不会阻止录制。你可以明确选择不录电脑声音继续；如果已选择录屏，仍会保存屏幕画面和麦克风。电脑中其他参会人的声音不会被保存。' : 'This is unrelated to whether anyone is speaking. Silence never blocks recording. You can continue with the microphone, but audio played by the computer will not be saved.'}</span></div><details className="text-xs text-muted-foreground"><summary className="cursor-pointer">{zh ? '查看失败详情' : 'Failure details'}</summary><p className="mt-2 break-words">{session.error}</p></details><div className="flex flex-wrap gap-3"><Button onClick={() => startRecording(false)}><Mic2 data-icon="inline-start" />{meetingType === 'video' ? (zh ? '继续录屏（不含电脑声音）' : 'Record screen without computer audio') : (zh ? '继续录音（仅麦克风）' : 'Record microphone only')}</Button><Button variant="outline" onClick={() => startRecording(true)}><RotateCcw data-icon="inline-start" />{zh ? '重新选择共享并包含电脑音频' : 'Choose sharing again'}</Button></div></AlertDescription></Alert> : <div className="flex flex-col items-center justify-between gap-4 rounded-2xl bg-foreground px-6 py-5 text-background sm:flex-row"><div><p className="font-medium">{zh ? '录制将保存到 ' + workspace : 'Recording will be saved to ' + workspace}</p><p className="mt-1 max-w-3xl text-sm text-background/60">{mode === 'minutes' ? (zh ? '录制时实时转写，结束后根据逐字稿生成纪要；实时服务失败不影响本地录制。' : 'Transcribe live and generate notes when finished. Local recording continues if live transcription fails.') : (zh ? '只保存本地录制，不自动转写或总结。' : 'Save locally without automatic transcription or summary.')}</p></div><Button size="lg" variant="secondary" disabled={busy} className="motion-sheen min-w-48 rounded-full" onClick={() => startRecording(true)}><Mic2 />{mode === 'minutes' ? meetingType === 'video' ? (zh ? '开始视频会议' : 'Start video meeting') : (zh ? '开始语音会议' : 'Start audio meeting') : meetingType === 'video' ? (zh ? '开始录屏' : 'Start screen recording') : (zh ? '开始录音' : 'Start audio recording')}</Button></div>}</div>
    </section>}

    {!isCapturing ? <section className="motion-rise space-y-6" style={{ animationDelay: '140ms' }}><div><h2 className="text-2xl font-semibold tracking-tight">{zh ? '最近的会议内容' : 'Recent meeting content'}</h2><p className="mt-2 text-sm text-muted-foreground">{zh ? '录制先保存在本机；需要时再生成会议纪要。' : 'Recordings stay local until you generate notes.'}</p></div><Tabs defaultValue="recordings" className="grid gap-6"><TabsList className="w-fit"><TabsTrigger value="recordings">{zh ? '本地录制' : 'Local recordings'}<Badge variant="secondary" className="ml-2">{workspacePending.length}</Badge></TabsTrigger><TabsTrigger value="notes">{zh ? '会议纪要' : 'Meeting notes'}<Badge variant="secondary" className="ml-2">{meetingNotes.length}</Badge></TabsTrigger></TabsList><TabsContent value="recordings" className="m-0 grid gap-4 sm:grid-cols-2">{workspacePending.map(item => <LocalRecordingCard key={item.id} recording={item} busy={busy} onDeleted={() => setPending(items => items.filter(entry => entry.id !== item.id))} />)}{workspacePending.length === 0 ? <div className="rounded-[1.75rem] border border-dashed bg-muted/10 sm:col-span-2"><Empty><EmptyHeader><EmptyMedia variant="icon"><FileText /></EmptyMedia><EmptyTitle>{zh ? '还没有本地录制' : 'No local recordings'}</EmptyTitle><EmptyDescription>{zh ? '结束录制后会保存在这里，可回放、下载或生成会议纪要。' : 'Finished recordings appear here.'}</EmptyDescription></EmptyHeader></Empty></div> : null}</TabsContent><TabsContent value="notes" className="m-0"><NoteGrid notes={meetingNotes} loading={loading} emptyTitle={zh ? '还没有会议纪要' : 'No meeting notes yet'} emptyBody={zh ? '从本地录制生成，或导入已有会议文件。' : 'Generate from a local recording or import a meeting.'} onOpen={note => navigate('/note/' + note.id)} /></TabsContent></Tabs></section> : null}
  </div>
}
