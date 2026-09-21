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
  const elapsed = `${Math.floor(session.elapsedSeconds / 60).toString().padStart(2, '0')}:${String(session.elapsedSeconds % 60).padStart(2, '0')}`

  useEffect(() => {
    const element = video.current
    if (element) element.srcObject = session.preview || null
    return () => { if (element) element.srcObject = null }
  }, [session.preview, showPreview])

  return <section className={`mx-auto grid w-full gap-6 p-4 lg:p-8 ${session.captureOptions?.screen ? 'max-w-6xl lg:grid-cols-[minmax(0,1fr)_22rem]' : 'max-w-2xl'}`}>
    <div className="overflow-hidden rounded-3xl border bg-card shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-6 py-4">
        <div className="min-w-0"><p className="truncate font-semibold">{title}</p><p className="mt-1 text-sm text-muted-foreground">{session.captureOptions?.mode === 'minutes' ? (zh ? '保存后自动进行完整会后处理' : 'Full post-meeting processing starts after saving') : (zh ? '仅保存原始媒体，不调用转写或总结模型' : 'Save original media without transcription or summarization')}</p></div>
        <Badge variant={session.phase === 'paused' ? 'secondary' : 'destructive'}>{session.phase === 'paused' ? (zh ? '已暂停' : 'Paused') : (zh ? '录制中' : 'Recording')}</Badge>
      </div>
      {session.captureOptions?.screen && <div className="relative grid min-h-48 place-items-center bg-black">
        {session.preview && showPreview ? <video ref={video} autoPlay muted playsInline className="max-h-[70vh] w-full object-contain" /> : <div className="flex flex-col items-center gap-3 text-white/70"><Monitor className="size-10" /><p>{zh ? '当前录音不包含画面预览' : 'This recording has no video preview'}</p></div>}
      </div>}
    </div>
    <aside className="flex flex-col justify-between gap-8 rounded-3xl border bg-card p-6 shadow-sm">
      <div><p className="text-sm text-muted-foreground">{zh ? '录制时长' : 'Recording time'}</p><p className="mt-2 font-mono text-4xl font-semibold tabular-nums">{elapsed}</p>
        <div className="mt-8"><div className="mb-2 flex items-center justify-between text-sm"><span className="flex items-center gap-2"><Volume2 className="size-4" />{zh ? '麦克风音量' : 'Microphone level'}</span><span className="text-muted-foreground">{session.phase === 'paused' ? (zh ? '暂停' : 'Paused') : (zh ? '实时' : 'Live')}</span></div><div className="h-3 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-emerald-500 transition-[width] duration-75" style={{ width: `${Math.round((session.phase === 'paused' ? 0 : session.audioLevel) * 100)}%` }} /></div><p className="mt-2 text-xs leading-5 text-muted-foreground">{zh ? '静音或会议停顿不会中断录制。' : 'Silence and pauses do not stop recording.'}</p></div></div>
      <div className="grid gap-3">{session.preview ? <Button variant="outline" onClick={() => setShowPreview(value => !value)}>{showPreview ? (zh ? '隐藏画面预览' : 'Hide preview') : (zh ? '显示画面预览' : 'Show preview')}</Button> : null}<div className="grid grid-cols-2 gap-3"><Button variant="outline" disabled={!running} onClick={() => void controlMeeting(session.phase === 'paused' ? 'resume' : 'pause')}>{session.phase === 'paused' ? <Play /> : <Pause />}{session.phase === 'paused' ? (zh ? '继续' : 'Resume') : (zh ? '暂停' : 'Pause')}</Button><Button variant="destructive" disabled={!running} onClick={() => void controlMeeting('request-stop')}><Square />{zh ? '结束录制' : 'Stop'}</Button></div><Button variant="ghost" onClick={() => void openMeetingController()}><ExternalLink />{zh ? '打开录制控制窗' : 'Open recorder controls'}</Button></div>
    </aside>
  </section>
}
