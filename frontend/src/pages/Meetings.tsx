import { openMeetingController } from '../lib/meetingController'
import { apiJson } from '../lib/api'
import { listPendingMeetings, type PendingMeeting } from '../lib/audioStorage'
import { useAuthStore } from '../stores/authStore'
import { useEffect, useRef, useState } from 'react'
import { Monitor, Upload, FileText, Sparkles, Radio, Settings2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { ModelSourcePanel } from '../components/Settings/ModelSourcePanel'
import { LocalRecordingCard } from '../components/MeetingRecorder/LocalRecordingCard'
import { NoteGrid } from '../components/Notes/NoteGrid'
import { DEFAULT_CAPTURE_OPTIONS, START_MEETING_EVENT, SYSTEM_AUDIO_UNAVAILABLE } from '../lib/meetingCapture'
import { useI18n } from '../lib/i18n'
import { useMeetingRecorderStore } from '../stores/meetingRecorderStore'
import { useNoteLibraryStore } from '../stores/noteLibraryStore'
import { getWorkspaceLabel, useTeamStore } from '../stores/teamStore'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Conversation, ConversationContent, ConversationEmptyState, ConversationMessage, ConversationScrollButton } from '@/components/ui/conversation'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Checkbox } from '@/components/ui/checkbox'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Field, FieldContent, FieldDescription, FieldLabel, FieldTitle } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

export function Meetings() {
  const userId = useAuthStore(state => state.user?.id)
  const [pending, setPending] = useState<PendingMeeting[]>([])
  const navigate = useNavigate()
  const { locale, copy } = useI18n()
  const zh = locale.startsWith('zh')
  const [options, setOptions] = useState(DEFAULT_CAPTURE_OPTIONS)
  const [diarizationReady, setDiarizationReady] = useState<boolean | null>(null)
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [error, setError] = useState('')
  const [recordingMode, setRecordingMode] = useState<'record' | 'smart'>('smart')
  const { notes, loading, loadNotes } = useNoteLibraryStore()
  const { currentWorkspace, teams } = useTeamStore()
  const session = useMeetingRecorderStore()
  const previewRef = useRef<HTMLVideoElement>(null)
  const busy = !['idle', 'completed', 'failed'].includes(session.phase) || session.hasRecoverableRecording
  const workspace = getWorkspaceLabel(currentWorkspace, teams, zh ? '个人空间' : 'Personal workspace')
  const workspacePending = pending.filter(item => item.workspace.scope === currentWorkspace.scope && (item.workspace.scope === 'personal' || currentWorkspace.scope === 'team' && item.workspace.teamId === currentWorkspace.teamId))
  const meetingNotes = notes.filter(note => ['meeting_recording', 'meeting_video'].includes(note.sourceType || ''))
  useEffect(() => {
    void loadNotes(currentWorkspace)
    let active = true
    setPending([])
    if (userId) void listPendingMeetings(userId).then(items => { if (active) setPending(items) }).catch(() => { if (active) setError(zh ? '无法读取本地录制。' : 'Cannot load local recordings.') })
    return () => { active = false }
  }, [currentWorkspace, loadNotes, session.phase, userId])
  useEffect(() => {
    if (previewRef.current) previewRef.current.srcObject = session.preview || null
  }, [session.preview])
  useEffect(() => {
    void apiJson<{ diarization: { available: boolean } }>('/api/meeting-capabilities')
      .then(result => setDiarizationReady(result.diarization.available)).catch(() => setDiarizationReady(false))
  }, [])
  useEffect(() => {
    const refresh = () => { void navigator.mediaDevices?.enumerateDevices().then(items => setDevices(items.filter(item => item.kind === 'audioinput'))).catch(() => undefined) }
    refresh()
    navigator.mediaDevices?.addEventListener('devicechange', refresh)
    return () => navigator.mediaDevices?.removeEventListener('devicechange', refresh)
  }, [])
  const refreshDevices = async () => {
    setError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach(track => track.stop())
      setDevices((await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === 'audioinput'))
    } catch { setError(zh ? '无法访问麦克风，请检查设备和麦克风权限。' : 'Cannot access microphone. Check your device and permissions.') }
  }
  return <div className="mx-auto flex max-w-[1480px] flex-col gap-7 px-6 py-7 pb-32 lg:px-8">
    <header className="flex flex-wrap items-start justify-between gap-5">
      <div><div className="mb-2 text-sm text-muted-foreground">{workspace}</div><h1 className="text-3xl font-semibold tracking-tight">{zh ? '会议工作台' : 'Meeting workspace'}</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">{zh ? '在一个工作区完成录制、回放、按说话人整理逐字稿和生成会议纪要。' : 'Capture, replay, organize speaker transcripts and generate meeting notes in one workspace.'}</p></div>
      <div className="flex items-center gap-2"><Sheet><SheetTrigger asChild><Button variant="outline"><Settings2 />{zh ? '处理设置' : 'Processing settings'}</Button></SheetTrigger><SheetContent className="w-full overflow-y-auto sm:max-w-xl"><SheetHeader><SheetTitle>{zh ? '转写与总结设置' : 'Transcription and summary settings'}</SheetTitle><SheetDescription>{zh ? '选择下一次生成会议纪要时使用的语音和语言模型。' : 'Choose the speech and language models for the next meeting note.'}</SheetDescription></SheetHeader><div className="mt-6"><ModelSourcePanel compact /></div></SheetContent></Sheet><Button variant="outline" onClick={() => navigate('/generate?meeting=1')}><Upload />{zh ? '导入会议' : 'Import meeting'}</Button></div>
    </header>
    <section className="min-h-[590px] overflow-hidden rounded-xl border bg-card shadow-sm">
      <ResizablePanelGroup direction="horizontal">
      <ResizablePanel defaultSize={31} minSize={25} maxSize={42}>
      <section className="flex h-full flex-col p-5">
      <header><div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">{zh ? '新建录制' : 'New recording'}</h2><Badge variant="secondary">{zh ? '保存到本机' : 'Saved locally'}</Badge></div><p className="text-sm leading-6 text-muted-foreground">{recordingMode === 'smart' ? (zh ? '停止后先保存录制，再由你确认是否生成逐字稿和纪要。' : 'Save first, then choose whether to generate transcript and notes.') : (zh ? '只保存录制，不调用转写和总结。' : 'Save the recording without transcription or summarization.')}</p></header>
      <ToggleGroup type="single" value={recordingMode} onValueChange={value => value && setRecordingMode(value as 'record' | 'smart')} className="mt-5 grid grid-cols-2"><ToggleGroupItem value="record"><Radio />{zh ? '仅录制' : 'Record only'}</ToggleGroupItem><ToggleGroupItem value="smart"><Sparkles />{zh ? '生成纪要' : 'Create notes'}</ToggleGroupItem></ToggleGroup>
      <div className="mt-6 flex flex-1 flex-col gap-5">
        <Field><FieldLabel>{zh ? '会议名称（可选）' : 'Meeting name (optional)'}</FieldLabel><Input maxLength={160} disabled={busy} value={options.title} onChange={event => setOptions({ ...options, title: event.target.value })} placeholder={zh ? '例如：产品方案评审' : 'e.g. Product review'} /></Field>
        <Field><FieldLabel>{zh ? '麦克风 · 录制现场声音' : 'Microphone · local voices'}</FieldLabel><Select disabled={busy} value={options.microphoneId || 'default'} onValueChange={value => setOptions({ ...options, microphoneId: value === 'default' ? '' : value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="default">{zh ? '系统默认麦克风' : 'Default microphone'}</SelectItem>{devices.filter(device => device.deviceId && device.deviceId !== 'default').map((device, index) => <SelectItem key={device.deviceId} value={device.deviceId}>{device.label || `Microphone ${index + 1}`}</SelectItem>)}</SelectContent></Select><Button variant="link" size="sm" disabled={busy} onClick={() => void refreshDevices()} className="w-fit px-0">{zh ? '检测 / 刷新麦克风' : 'Detect / refresh microphones'}</Button></Field>
        <Field orientation="horizontal" className="border-y py-4"><Checkbox id="record-screen" disabled={busy} checked={options.screen} onCheckedChange={checked => setOptions({ ...options, screen: checked === true })} /><FieldContent><FieldLabel htmlFor="record-screen"><FieldTitle>{zh ? '同时录制屏幕' : 'Record screen too'}</FieldTitle></FieldLabel><FieldDescription>{zh ? '选择屏幕或窗口，生成带截图的纪要。录屏会占用更多空间。' : 'Choose a screen or window for illustrated notes. Uses more disk space.'}</FieldDescription></FieldContent></Field>
        {diarizationReady === false ? <Alert><AlertDescription>{zh ? '说话人识别服务当前不可用，但仍可正常录制并稍后重试生成。' : 'Speaker identification is unavailable, but recording and later retry still work.'}</AlertDescription></Alert> : null}
        {(error || session.error) ? <Alert variant="destructive"><AlertDescription>{error || session.error}</AlertDescription></Alert> : null}
        {session.error?.includes(SYSTEM_AUDIO_UNAVAILABLE) ? <Button variant="outline" onClick={() => window.dispatchEvent(new CustomEvent(START_MEETING_EVENT, { detail: { ...options, systemAudio: false, diarize: true, speakerCount: undefined } }))}>{zh ? '仅录麦克风继续' : 'Continue with microphone only'}</Button> : null}
        <div className="mt-auto border-t pt-5"><p className="mb-3 text-xs text-muted-foreground">{zh ? `保存到：${workspace}` : `Save to: ${workspace}`}</p><Button size="lg" disabled={busy} className="w-full transition-transform active:scale-[.99]" onClick={() => window.dispatchEvent(new CustomEvent(START_MEETING_EVENT, { detail: { ...options, systemAudio: true, diarize: true, speakerCount: undefined } }))}>{zh ? '开始录制' : 'Start recording'}</Button></div>
      </div></section>
      </ResizablePanel><ResizableHandle withHandle />
      <ResizablePanel defaultSize={69} minSize={50}>
      <section className="flex h-full min-h-[590px] flex-col overflow-hidden"><header className="border-b p-5"><div className="flex items-center justify-between"><div><h2 className="font-semibold">{zh ? '对话时间线' : 'Conversation timeline'}</h2><p className="mt-1 text-sm text-muted-foreground">{zh ? '录制状态和按说话人整理的逐字稿在这里连续呈现。' : 'Recording status and the speaker transcript appear in one continuous timeline.'}</p></div>{busy ? <Badge variant="destructive">{copy.meetingRecorder.phases[session.phase]}</Badge> : <Badge variant="secondary">{zh ? '等待录制' : 'Ready'}</Badge>}</div></header>
      {session.preview ? <div className="border-b p-4"><video ref={previewRef} autoPlay muted playsInline className="max-h-40 w-full bg-black object-contain" /></div> : null}
      <Conversation className="min-h-0"><ConversationContent>{busy ? <><ConversationMessage speaker={zh ? '录制状态' : 'Recording'} time="00:00">{zh ? '正在完整保存麦克风和系统声音。停止后，录制会先保存在本机。' : 'Microphone and system audio are being saved. The recording is stored locally when stopped.'}</ConversationMessage><ConversationMessage speaker={zh ? '处理说明' : 'Processing'} active>{recordingMode === 'smart' ? (zh ? '停止后可点击生成，系统再进行分段转写、说话人识别和会议总结。' : 'After stopping, start generation to transcribe chunks, identify speakers and summarize.') : (zh ? '当前为仅录制模式，不会自动调用转写或总结。' : 'Record-only mode will not call transcription or summarization.')}</ConversationMessage></> : <ConversationEmptyState icon={options.screen ? <Monitor className="size-5" /> : <FileText className="size-5" />} title={zh ? '开始录制后在这里查看状态' : 'Recording status appears here'} description={zh ? '当前不是实时语音转写。完整录制保存后，可生成按说话人和时间排列的对话式逐字稿。' : 'This is not live speech recognition yet. Generate after saving to get a speaker-based conversation transcript.'} />} </ConversationContent><ConversationScrollButton /></Conversation>
        {busy ? <Button variant="secondary" className="m-4 mt-0" onClick={() => { session.restorePanel(); void openMeetingController().catch(() => undefined) }}>{copy.meetingRecorder.phases[session.phase]} · {Math.floor(session.elapsedSeconds / 60)}:{String(session.elapsedSeconds % 60).padStart(2, '0')} · {((session.sizeBytes || 0) / 1024 / 1024).toFixed(1)} MB — {zh ? '显示控制面板' : 'Show controls'}</Button> : null}
        <p className="px-4 pb-4 text-xs leading-6 text-muted-foreground">{zh ? '自动区分发言人，转写完成后可修改姓名。' : 'Speakers are identified automatically. You can edit their names in the transcript.'}</p>
      </section></ResizablePanel></ResizablePanelGroup>
    </section>
    <Tabs defaultValue="recordings" className="grid gap-4"><div className="flex items-center justify-between"><TabsList><TabsTrigger value="recordings">{zh ? '本地录制' : 'Local recordings'}<Badge variant="secondary" className="ml-2">{workspacePending.length}</Badge></TabsTrigger><TabsTrigger value="notes">{zh ? '会议纪要' : 'Meeting notes'}<Badge variant="secondary" className="ml-2">{meetingNotes.length}</Badge></TabsTrigger></TabsList></div>
      <TabsContent value="recordings" className="m-0 rounded-xl border bg-card px-5">{workspacePending.map(item => <LocalRecordingCard key={item.id} recording={item} busy={busy} onDeleted={() => setPending(items => items.filter(entry => entry.id !== item.id))} />)}{workspacePending.length === 0 ? <Empty><EmptyHeader><EmptyMedia variant="icon"><FileText /></EmptyMedia><EmptyTitle>{zh ? '还没有本地录制' : 'No local recordings'}</EmptyTitle><EmptyDescription>{zh ? '结束录制后会自动保存在这里，无需先生成纪要。' : 'Recordings are saved here when you finish, even without a summary.'}</EmptyDescription></EmptyHeader></Empty> : null}</TabsContent>
      <TabsContent value="notes" className="m-0"><NoteGrid notes={meetingNotes} loading={loading} emptyTitle={zh ? '还没有会议纪要' : 'No meeting notes yet'} emptyBody={zh ? '从本地录制生成，或导入已有会议文件。' : 'Generate from a local recording or import an existing meeting.'} onOpen={note => navigate(`/note/${note.id}`)} /></TabsContent>
    </Tabs>
  </div>
}
