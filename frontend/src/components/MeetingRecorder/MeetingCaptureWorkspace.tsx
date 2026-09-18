import { useEffect, useRef, useState } from 'react'
import { AudioLines, ExternalLink, Monitor, Pause, Play, Square } from 'lucide-react'
import { useMeetingRecorderStore } from '@/stores/meetingRecorderStore'
import { controlMeeting, openMeetingController } from '@/lib/meetingController'
import { useI18n } from '@/lib/i18n'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Conversation, ConversationContent, ConversationEmptyState, ConversationMessage, ConversationScrollButton } from '@/components/ui/conversation'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

/** Capture status only. Do not display simulated speech or audio levels here. */
export function MeetingCaptureWorkspace({ title }: { title: string }) {
  const session = useMeetingRecorderStore()
  const { locale, copy } = useI18n()
  const zh = locale.startsWith('zh')
  const video = useRef<HTMLVideoElement>(null)
  const [showPreview, setShowPreview] = useState(true)
  const [compact, setCompact] = useState(false)
  const [compactPanel, setCompactPanel] = useState<'transcript' | 'preview'>('transcript')
  const running = session.phase === 'recording' || session.phase === 'paused'
  const minutesMode = session.captureOptions?.mode === 'minutes'
  const elapsed = `${Math.floor(session.elapsedSeconds / 60).toString().padStart(2, '0')}:${String(session.elapsedSeconds % 60).padStart(2, '0')}`

  useEffect(() => {
    const element = video.current
    if (element) element.srcObject = session.preview || null
    return () => { if (element) element.srcObject = null }
  }, [session.preview, showPreview])

  useEffect(() => {
    const query = window.matchMedia('(max-width: 1023px)')
    const update = () => setCompact(query.matches)
    update()
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  const liveStatusCopy = session.liveTranscriptStatus === 'live'
    ? (zh ? '实时转写中' : 'Transcribing')
    : session.liveTranscriptStatus === 'connecting' || session.liveTranscriptStatus === 'starting'
      ? (zh ? '正在连接' : 'Connecting')
      : session.liveTranscriptStatus === 'paused'
        ? (zh ? '转写已暂停' : 'Paused')
        : session.liveTranscriptStatus === 'failed'
          ? (zh ? '转写不可用' : 'Unavailable')
          : session.liveTranscriptStatus === 'finalizing'
            ? (zh ? '正在确认文本' : 'Finalizing')
            : session.liveTranscriptStatus === 'completed'
              ? (zh ? '转写已完成' : 'Completed')
              : (zh ? '等待开始' : 'Waiting')

  const transcriptPanel = <div className="flex min-h-0 flex-col">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-3">
      <div className="flex items-center gap-2">
        <AudioLines className="size-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold">{zh ? '实时逐字稿' : 'Live transcript'}</h3>
      </div>
      <Badge variant={session.liveTranscriptStatus === 'failed' ? 'destructive' : 'outline'}>{liveStatusCopy}</Badge>
    </div>
    <Conversation className="min-h-[24rem]">
      <ConversationContent className="min-h-full">
        {session.liveTranscriptSegments.length ? session.liveTranscriptSegments.map((segment, index) => <ConversationMessage
          key={segment.id}
          speaker={segment.kind === 'background' ? (zh ? '背景声音' : 'Background') : segment.speaker ? `${zh ? '说话人' : 'Speaker'} ${segment.speaker}` : (zh ? '当前发言' : 'Current speaker')}
          time={typeof segment.startMs === 'number' ? `${Math.floor(segment.startMs / 60000).toString().padStart(2, '0')}:${Math.floor(segment.startMs % 60000 / 1000).toString().padStart(2, '0')}` : undefined}
          active={!segment.final && index === session.liveTranscriptSegments.length - 1}
        >{segment.text}</ConversationMessage>) : <ConversationEmptyState
          icon={<AudioLines className="size-5" />}
          title={session.liveTranscriptStatus === 'failed' ? (zh ? '实时转写暂时不可用' : 'Live transcript unavailable') : (zh ? '等待发言' : 'Waiting for speech')}
          description={session.liveTranscriptStatus === 'failed' ? (zh ? '本地录制仍在继续。结束后可使用完整录音重新转写和区分说话人。' : 'Local recording continues and can be transcribed later.') : (zh ? '开始说话后，确认的内容会按时间出现在这里。静音和停顿不会停止录制。' : 'Confirmed speech will appear here. Silence never stops recording.')}
        />}
      </ConversationContent>
      <ConversationScrollButton />
    </Conversation>
  </div>

  const previewPanel = session.preview ? <aside className="flex min-h-0 flex-col bg-muted/20">
    <div className="flex items-center justify-between gap-3 border-b px-5 py-3">
      <h3 className="text-sm font-semibold">{zh ? '录制画面' : 'Capture preview'}</h3>
      <Badge variant="secondary">{zh ? '本地保存' : 'Saved locally'}</Badge>
    </div>
    <div className="grid flex-1 place-items-center p-4">
      <video ref={video} autoPlay muted playsInline aria-label={zh ? '录制画面预览' : 'Capture preview'} className="max-h-[42dvh] w-full rounded-xl bg-black object-contain shadow-sm" />
    </div>
    <p className="border-t px-5 py-4 text-sm leading-6 text-muted-foreground">{zh ? '可以切换到其他窗口。静音或会议停顿不会停止录制。' : 'You can switch windows. Silence does not stop recording.'}</p>
  </aside> : null

  return <section aria-label={zh ? '当前录制' : 'Current recording'} className="overflow-hidden rounded-2xl border bg-card shadow-sm">
    <header className="flex flex-wrap items-center justify-between gap-4 border-b px-6 py-4">
      <div className="flex min-w-0 items-center gap-3">
        <span className={`size-2.5 shrink-0 rounded-full ${session.phase === 'recording' ? 'bg-red-500 motion-safe:animate-pulse' : 'bg-muted-foreground'}`} />
        <h2 className="truncate text-base font-medium">{title || (zh ? '未命名会议' : 'Untitled meeting')}</h2>
        <Badge variant="secondary">{copy.meetingRecorder.phases[session.phase]}</Badge>
      </div>
      {session.preview && <Button variant="ghost" className="min-h-11" aria-expanded={showPreview} onClick={() => setShowPreview(value => !value)}>
        <Monitor />{showPreview ? (zh ? '收起预览' : 'Hide preview') : (zh ? '显示预览' : 'Show preview')}
      </Button>}
    </header>
    {minutesMode && compact && showPreview && session.preview ? <div className="min-h-[30rem]">
      <Tabs value={compactPanel} onValueChange={value => setCompactPanel(value as 'transcript' | 'preview')} className="flex min-h-[30rem] flex-col">
        <div className="border-b px-4 py-3"><TabsList className="grid w-full grid-cols-2"><TabsTrigger value="transcript">{zh ? '逐字稿' : 'Transcript'}</TabsTrigger><TabsTrigger value="preview">{zh ? '画面' : 'Preview'}</TabsTrigger></TabsList></div>
        <div className="min-h-0 flex-1">{compactPanel === 'transcript' ? transcriptPanel : previewPanel}</div>
      </Tabs>
    </div> : <div className={minutesMode && showPreview && session.preview ? 'grid min-h-[30rem] grid-cols-[minmax(0,1fr)_minmax(280px,32%)]' : 'grid min-h-[30rem]'}>
      {minutesMode ? <div className={showPreview && session.preview ? 'border-r' : ''}>{transcriptPanel}</div> : null}
      {showPreview ? previewPanel : null}
    </div>}
    <footer className="sticky bottom-0 flex flex-wrap items-center justify-between gap-4 border-t bg-card px-6 py-4">
      <div className="flex items-baseline gap-3">
        <span className="font-mono text-2xl font-semibold tabular-nums">{elapsed}</span>
        <span className="text-xs text-muted-foreground">{((session.sizeBytes || 0) / 1024 / 1024).toFixed(1)} MB</span>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" className="min-h-11" onClick={() => { session.restorePanel(); void openMeetingController().catch(() => undefined) }}><ExternalLink />{zh ? '悬浮控制' : 'Floating controls'}</Button>
        <Button variant="outline" className="min-h-11 min-w-24" disabled={!running} onClick={() => void controlMeeting(session.phase === 'paused' ? 'resume' : 'pause')}>
          {session.phase === 'paused' ? <Play /> : <Pause />}{session.phase === 'paused' ? (zh ? '继续' : 'Resume') : (zh ? '暂停' : 'Pause')}
        </Button>
        <Button variant="destructive" className="min-h-11 min-w-28" disabled={!running} onClick={() => void controlMeeting('request-stop')}><Square />{zh ? '结束录制' : 'End recording'}</Button>
      </div>
    </footer>
    {minutesMode && session.liveTranscriptError ? <p className="border-t px-6 py-3 text-xs leading-5 text-destructive">{zh ? `实时转写失败，但本地录制仍在继续：${session.liveTranscriptError}` : session.liveTranscriptError}</p> : null}
  </section>
}
