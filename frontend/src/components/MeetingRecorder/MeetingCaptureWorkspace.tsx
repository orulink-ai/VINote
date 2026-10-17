import { useEffect, useRef, useState } from 'react'
import { ExternalLink, Monitor, Pause, Play, Square, Volume2 } from 'lucide-react'
import { useMeetingRecorderStore } from '@/stores/meetingRecorderStore'
import { controlMeeting, openMeetingController } from '@/lib/meetingController'
import { useI18n } from '@/lib/i18n'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

export function MeetingCaptureWorkspace({ title }: { title: string }) {
  const session = useMeetingRecorderStore()
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const video = useRef<HTMLVideoElement>(null)
  const [showPreview, setShowPreview] = useState(true)
  const running = session.phase === 'recording' || session.phase === 'paused'
  const status = ({ requesting: zh ? '等待设备就绪' : 'Preparing devices', recording: zh ? '正在录制' : 'Recording', paused: zh ? '已暂停' : 'Paused', stopping: zh ? '正在保存' : 'Saving' } as Record<string, string>)[session.phase] || session.phase
  const track = session.preview?.getVideoTracks()[0]
  const quality = track && typeof track.getSettings === 'function' ? track.getSettings() : undefined
  const elapsed = `${Math.floor(session.elapsedSeconds / 60).toString().padStart(2, '0')}:${String(session.elapsedSeconds % 60).padStart(2, '0')}`

  useEffect(() => {
    const element = video.current
    if (element) element.srcObject = session.preview || null
    return () => { if (element) element.srcObject = null }
  }, [session.preview, showPreview])

  return <section className={`mx-auto grid w-full gap-6 p-4 lg:p-8 ${session.captureOptions?.screen ? 'max-w-6xl lg:grid-cols-[minmax(0,1fr)_22rem]' : 'max-w-2xl'}`}>
    <div className="overflow-hidden border-y bg-background">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-6 py-4">
        <div className="min-w-0"><p className="truncate font-semibold">{title || (zh ? '会议录制' : 'Meeting recording')}</p><p className="mt-1 text-sm text-muted-foreground">{zh ? '先录制并保存，结束后再选择是否生成会议纪要' : 'Record and save first, then choose whether to generate meeting notes'}</p></div>
        <Badge role="status" variant={session.phase === 'recording' ? 'destructive' : 'secondary'}>{status}</Badge>
      </div>
      {session.phase === 'requesting' && <div className="flex items-center justify-between gap-4 p-6 text-sm leading-6"><p role="status">{zh ? '请完成屏幕选择和麦克风许可。设备就绪前尚未开始录制。' : 'Complete screen selection and microphone permission. Recording has not started yet.'}</p><Button variant="outline" onClick={() => void controlMeeting('cancel-start')}>{zh ? '取消准备' : 'Cancel'}</Button></div>}
      {quality?.width && quality.height && <p className="px-6 py-2 text-xs text-muted-foreground">{zh ? '实际采集' : 'Actual capture'} · {quality.width} × {quality.height}{quality.frameRate ? ` · ${Math.round(quality.frameRate)} fps` : ''}</p>}
      {session.captureOptions?.screen && <div className="relative grid min-h-48 place-items-center bg-black">
        {session.preview && showPreview ? <video ref={video} autoPlay muted playsInline className="max-h-[70vh] w-full object-contain" /> : <div className="flex flex-col items-center gap-3 text-white/70"><Monitor className="size-10" /><p>{session.preview ? (zh ? '画面预览已隐藏，录制继续' : 'Preview hidden; recording continues') : (zh ? '等待选择录制画面' : 'Waiting for screen selection')}</p></div>}
      </div>}
    </div>
    <aside className="flex flex-col justify-between gap-8 border-y bg-background py-6">
      <div><p className="text-sm text-muted-foreground">{zh ? '录制时长' : 'Recording time'}</p><p className="mt-2 font-mono text-4xl font-semibold tabular-nums">{elapsed}</p>
        <div className="mt-8"><div className="mb-2 flex items-center justify-between text-sm"><span className="flex items-center gap-2"><Volume2 className="size-4" />{zh ? '麦克风音量' : 'Microphone level'}</span><span className="text-muted-foreground">{session.phase === 'paused' ? (zh ? '暂停' : 'Paused') : (zh ? '实时' : 'Live')}</span></div><div className="h-3 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-foreground transition-[width] duration-75" style={{ width: `${Math.round((session.phase === 'paused' ? 0 : session.audioLevel) * 100)}%` }} /></div><p className="mt-2 text-xs leading-5 text-muted-foreground">{zh ? '静音或会议停顿不会中断录制。' : 'Silence and pauses do not stop recording.'}</p></div></div>
      <div className="grid gap-3">{session.preview ? <Button variant="outline" onClick={() => setShowPreview(value => !value)}>{showPreview ? (zh ? '隐藏画面预览' : 'Hide preview') : (zh ? '显示画面预览' : 'Show preview')}</Button> : null}<div className="grid grid-cols-2 gap-3"><Button variant="outline" disabled={!running} onClick={() => void controlMeeting(session.phase === 'paused' ? 'resume' : 'pause')}>{session.phase === 'paused' ? <Play /> : <Pause />}{session.phase === 'paused' ? (zh ? '继续' : 'Resume') : (zh ? '暂停' : 'Pause')}</Button><Button variant="destructive" disabled={!running} onClick={() => void controlMeeting('request-stop')}><Square />{zh ? '结束录制' : 'Stop'}</Button></div><Button variant="ghost" onClick={() => void openMeetingController()}><ExternalLink />{zh ? '打开录制控制窗' : 'Open recorder controls'}</Button></div>
    </aside>
  </section>
}
