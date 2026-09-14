import { openMeetingController } from '../lib/meetingController'
import { apiJson } from '../lib/api'
import { listPendingMeetings, type PendingMeeting } from '../lib/audioStorage'
import { useAuthStore } from '../stores/authStore'
import { useEffect, useRef, useState } from 'react'
import { Mic, Monitor, Upload } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { NoteGrid } from '../components/Notes/NoteGrid'
import { DEFAULT_CAPTURE_OPTIONS, START_MEETING_EVENT } from '../lib/meetingCapture'
import { useI18n } from '../lib/i18n'
import { useMeetingRecorderStore } from '../stores/meetingRecorderStore'
import { useNoteLibraryStore } from '../stores/noteLibraryStore'
import { getWorkspaceLabel, useTeamStore } from '../stores/teamStore'

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
  const { notes, loading, loadNotes } = useNoteLibraryStore()
  const { currentWorkspace, teams } = useTeamStore()
  const session = useMeetingRecorderStore()
  const previewRef = useRef<HTMLVideoElement>(null)
  const busy = !['idle', 'completed', 'failed'].includes(session.phase) || session.hasRecoverableRecording
  const workspace = getWorkspaceLabel(currentWorkspace, teams, zh ? '个人空间' : 'Personal workspace')
  useEffect(() => {
    void loadNotes(currentWorkspace)
    if (userId) void listPendingMeetings(userId).then(setPending).catch(() => setError(zh ? '无法读取本地待整理会议。' : 'Cannot load local recordings.'))
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
  const inputClass = 'w-full rounded-xl border border-gray-200 bg-transparent px-3 py-2.5 dark:border-gray-700'
  return <div className="mx-auto max-w-6xl space-y-8 p-8 pb-44">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-2xl font-semibold">{zh ? '会议记录' : 'Meetings'}</h1>
        <p className="mt-2 text-sm text-gray-500">{zh ? '记录讨论、共享画面与决策，让每次会议都有迹可循。' : 'Capture conversations, shared screens and decisions.'}</p></div>
      <button className="flex items-center gap-2 rounded-xl border px-4 py-2 text-sm dark:border-gray-700" onClick={() => navigate('/generate?meeting=1')}><Upload size={16} />{zh ? '导入会议文件' : 'Import meeting'}</button>
    </header>
    <section className="grid gap-8 rounded-2xl border border-gray-200 bg-gray-50 p-6 dark:border-gray-700 dark:bg-[#202020] md:grid-cols-2">
      <div className="space-y-5">
        <h2 className="flex items-center gap-2 font-semibold"><Mic size={20} />{zh ? '开始会议' : 'Start a meeting'}</h2>
        <label className="block space-y-2 text-sm"><span>{zh ? '会议名称（可选）' : 'Meeting name (optional)'}</span><input className={inputClass} maxLength={160} disabled={busy} value={options.title} onChange={event => setOptions({ ...options, title: event.target.value })} placeholder={zh ? '例如：产品方案评审' : 'e.g. Product review'} /></label>
        <label className="block space-y-2 text-sm"><span>{zh ? '麦克风 · 录制现场声音' : 'Microphone · local voices'}</span><select className={inputClass} disabled={busy} value={options.microphoneId} onChange={event => setOptions({ ...options, microphoneId: event.target.value })}><option value="">{zh ? '系统默认麦克风' : 'Default microphone'}</option>{devices.filter(device => device.deviceId && device.deviceId !== 'default').map((device, index) => <option key={device.deviceId} value={device.deviceId}>{device.label || `Microphone ${index + 1}`}</option>)}</select></label>
        <button disabled={busy} onClick={() => void refreshDevices()} className="text-sm text-primary-light">{zh ? '检测 / 刷新麦克风' : 'Detect / refresh microphones'}</button>
        <label className="flex items-start gap-3 text-sm"><input type="checkbox" disabled={busy} checked={options.systemAudio} onChange={event => setOptions({ ...options, systemAudio: event.target.checked })} /><span>{zh ? '采集会议声音' : 'Capture system audio'}<small className="mt-1 block text-gray-500">{zh ? '录制远端声音；需要在屏幕选择器中共享音频。' : 'For remote voices, share audio in the screen picker.'}</small></span></label>
        <label className="flex items-start gap-3 text-sm"><input type="checkbox" disabled={busy} checked={options.screen} onChange={event => setOptions({ ...options, screen: event.target.checked })} /><span>{zh ? '同时录制屏幕' : 'Record screen too'}<small className="mt-1 block text-gray-500">{zh ? '选择屏幕或窗口，生成带截图的纪要。录屏占用更多空间。' : 'Choose a screen or window for illustrated notes. Uses more disk space.'}</small></span></label>
        <label className="flex items-start gap-3 text-sm"><input type="checkbox" disabled={busy} checked={options.diarize} onChange={event => setOptions({ ...options, diarize: event.target.checked })} /><span>{zh ? '区分说话人' : 'Identify speakers'}<small className="mt-1 block text-gray-500">{zh ? '本地分析声音，按发言人转写；完成后可修改说话人姓名。' : 'Analyze voices locally and transcribe by speaker. Rename speakers afterwards.'}</small></span></label>
        {options.diarize && <label className="block space-y-2 text-sm"><span>{zh ? '说话人数' : 'Number of speakers'}</span><select className={inputClass} disabled={busy} value={options.speakerCount || ''} onChange={event => setOptions({ ...options, speakerCount: Number(event.target.value) || undefined })}><option value="">{zh ? '自动判断' : 'Detect automatically'}</option>{Array.from({ length: 20 }, (_, index) => index + 1).map(count => <option key={count} value={count}>{count}</option>)}</select></label>}
        {options.diarize && diarizationReady === false && <p className="text-sm text-amber-600">{zh ? '说话人模型尚未安装，请先完成本地模型配置，或暂时关闭说话人区分。' : 'Speaker models are not installed. Configure local models or disable speaker identification.'}</p>}
        {(error || session.error) && <p role="alert" className="text-sm text-red-500">{error || session.error}</p>}
        <p className="text-xs text-gray-500">{zh ? `保存到：${workspace}` : `Save to: ${workspace}`}</p>
        <button disabled={busy} className="rounded-xl bg-primary-light px-6 py-3 text-sm font-medium text-white disabled:opacity-40" onClick={() => window.dispatchEvent(new CustomEvent(START_MEETING_EVENT, { detail: options }))}>{zh ? '开始录制' : 'Start recording'}</button>
      </div>
      <div className="flex min-h-56 flex-col justify-center rounded-xl border border-dashed border-gray-300 p-6 dark:border-gray-600">
        {session.preview ? <video ref={previewRef} autoPlay muted playsInline className="w-full rounded-lg" /> : <div className="text-center"><Monitor className="mx-auto mb-4 text-gray-400" size={40} /><p className="text-sm text-gray-500">{zh ? '不开启录屏时，仅保留会议声音。' : 'Audio only unless screen recording is enabled.'}</p><p className="mt-3 text-xs text-gray-500">{zh ? '结束后可生成纪要、查看转写并回放原始录制。' : 'Generate notes, read the transcript and replay the recording.'}</p></div>}
        {busy && <button className="mt-5 rounded-lg bg-white p-3 text-sm dark:bg-[#191919]" onClick={() => { session.restorePanel(); void openMeetingController().catch(() => undefined) }}>{copy.meetingRecorder.phases[session.phase]} · {Math.floor(session.elapsedSeconds / 60)}:{String(session.elapsedSeconds % 60).padStart(2, '0')} · {((session.sizeBytes || 0) / 1024 / 1024).toFixed(1)} MB — {zh ? '显示控制面板' : 'Show controls'}</button>}
        <p className="mt-5 text-xs leading-6 text-gray-500">{zh ? '启用后以说话人编号整理发言，重叠发言单独标注。姓名与负责人需要确认；原始录制默认保留用于回放。' : 'Speakers receive stable labels; overlapping speech is marked separately. Confirm names and owners. Original recordings are retained for playback.'}</p>
      </div>
    </section>
    {pending.filter(item => item.workspace.scope === currentWorkspace.scope && (item.workspace.scope === 'personal' || currentWorkspace.scope === 'team' && item.workspace.teamId === currentWorkspace.teamId)).map(item => <div key={item.id} className="flex items-center justify-between rounded-xl border p-4 dark:border-gray-700"><div><p className="font-medium">{item.options.title || (zh ? '未整理会议' : 'Pending meeting')}</p><p className="text-xs text-gray-500">{new Date(item.startedAt).toLocaleString()} · {zh ? '录制已保存在此设备' : 'Recording saved on this device'}</p></div><button disabled={busy} className="text-sm text-primary-light disabled:opacity-40" onClick={() => window.dispatchEvent(new CustomEvent('vinote-restore-meeting', { detail: item }))}>{zh ? '继续整理' : 'Resume'}</button></div>)}
    <section className="space-y-4"><h2 className="font-semibold">{zh ? '会议历史' : 'Meeting history'}</h2><NoteGrid notes={notes.filter(note => ['meeting_recording', 'meeting_video'].includes(note.sourceType || ''))} loading={loading} emptyTitle={zh ? '还没有会议记录' : 'No meetings yet'} emptyBody={zh ? '开始录制或导入已有会议，纪要会保存在当前空间。' : 'Record or import a meeting to save it in this workspace.'} onOpen={note => navigate(`/note/${note.id}`)} /></section>
  </div>
}
