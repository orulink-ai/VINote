import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, ChevronDown, Copy, Download, FileAudio, FileText, FileVideo, Play, RotateCcw, Sparkles, Trash2 } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { deleteLocalRecording, getRecordedAudio, type PendingMeeting } from '../../lib/audioStorage'
import { downloadRecording } from '../../lib/recordingDownload'
import { useI18n } from '../../lib/i18n'

interface LocalRecordingCardProps { recording: PendingMeeting; busy: boolean; onDeleted: () => void }

function transcriptText(recording: PendingMeeting) {
  return (recording.transcript ?? []).filter(segment => segment.final && segment.text.trim()).map(segment => `${segment.speaker?.trim() || '未识别说话人'}：${segment.text.trim()}`).join('\n')
}

export function LocalRecordingCard({ recording, busy, onDeleted }: LocalRecordingCardProps) {
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [transcriptExpanded, setTranscriptExpanded] = useState(false)
  const [copied, setCopied] = useState(false)
  const title = recording.options.title || (zh ? '未命名会议' : 'Untitled meeting')
  const isVideo = recording.options.meetingType === 'video' || recording.options.screen
  const minutesMode = recording.options.mode === 'minutes'
  const savedTranscript = useMemo(() => transcriptText(recording), [recording])
  const Icon = isVideo ? FileVideo : FileAudio

  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])

  const load = async (download: boolean) => {
    setError('')
    try {
      const blob = await getRecordedAudio(recording.id)
      if (!blob) throw new Error(zh ? '找不到此设备上的录制文件' : 'Recording not found on this device')
      if (download) downloadRecording(blob, title)
      else { if (url) URL.revokeObjectURL(url); setUrl(URL.createObjectURL(blob)); setExpanded(true) }
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
  }

  const copyTranscript = async () => {
    if (!savedTranscript) return
    try { await navigator.clipboard.writeText(savedTranscript); setCopied(true); window.setTimeout(() => setCopied(false), 1600) }
    catch { setError(zh ? '复制逐字稿失败，请稍后重试' : 'Could not copy the transcript') }
  }

  const remove = async () => {
    setDeleting(true); setError(''); setUrl('')
    try { await deleteLocalRecording(recording.id, recording.ownerId); onDeleted() }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setDeleting(false) }
  }

  const restore = () => window.dispatchEvent(new CustomEvent('vinote-restore-meeting', { detail: recording }))

  return <article className="interactive-card motion-rise flex min-h-72 flex-col overflow-hidden rounded-2xl border bg-card shadow-sm">
    <button type="button" onClick={() => setExpanded(value => !value)} className="flex items-start gap-4 p-5 text-left">
      <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-muted"><Icon className="size-5" /></span>
      <span className="min-w-0 flex-1"><span className="block truncate font-semibold">{title}</span><span className="mt-1 block text-xs text-muted-foreground">{new Date(recording.startedAt).toLocaleString()} · {Math.floor(recording.elapsedSeconds / 60)}:{String(recording.elapsedSeconds % 60).padStart(2, '0')}</span></span>
      <span className="flex items-center gap-2"><Badge variant="secondary">{isVideo ? (zh ? '视频' : 'Video') : (zh ? '音频' : 'Audio')}</Badge><ChevronDown className={expanded ? 'size-4 rotate-180 transition-transform' : 'size-4 transition-transform'} /></span>
    </button>

    {expanded ? <div className="animate-in border-y bg-muted/20 p-4 fade-in slide-in-from-top-2 duration-300">{url ? isVideo ? <video src={url} controls className="max-h-72 w-full rounded-xl bg-black" /> : <audio src={url} controls autoPlay className="w-full" /> : <button type="button" onClick={() => void load(false)} className="flex min-h-32 w-full flex-col items-center justify-center rounded-xl border border-dashed bg-background text-sm text-muted-foreground transition-colors hover:border-foreground/20 hover:text-foreground"><Play className="mb-2 size-5" />{zh ? '点击加载并回放' : 'Load and play'}</button>}</div> : null}

    <div className="flex flex-1 flex-col gap-4 p-5 pt-3">
      <div className="rounded-xl border bg-muted/25 p-4">
        <div className="flex items-start gap-3">{savedTranscript ? <CheckCircle2 className="mt-0.5 size-5 text-emerald-600" /> : <FileText className="mt-0.5 size-5 text-muted-foreground" />}<div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{savedTranscript ? (zh ? '实时逐字稿已保存' : 'Live transcript saved') : minutesMode ? (zh ? '录制已保留，可重新生成纪要' : 'Recording saved and ready to retry') : (zh ? '当前只保存了本地录制' : 'Saved locally only')}</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">{savedTranscript ? (zh ? '生成纪要时会优先使用这份逐字稿，无需重新等待完整转写。' : 'This transcript will be used first when generating notes.') : minutesMode ? (zh ? '实时转写没有产生可用正文，本地媒体没有丢失，可稍后使用完整录制重试。' : 'No final live transcript was produced; the local media is safe.') : (zh ? '播放、下载或删除不会触发转写；需要时再生成会议纪要。' : 'Playback and download do not start transcription.')}</p>
        </div></div>
        {savedTranscript ? <div className="mt-3 flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => setTranscriptExpanded(value => !value)}><FileText />{transcriptExpanded ? (zh ? '收起逐字稿' : 'Hide transcript') : (zh ? '预览逐字稿' : 'Preview transcript')}</Button><Button variant="outline" size="sm" onClick={() => void copyTranscript()}>{copied ? <CheckCircle2 /> : <Copy />}{copied ? (zh ? '已复制' : 'Copied') : (zh ? '复制逐字稿' : 'Copy transcript')}</Button></div> : null}
        {transcriptExpanded && savedTranscript ? <div className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border bg-background p-3 text-xs leading-6">{savedTranscript}</div> : null}
      </div>

      <div className="mt-auto grid gap-2">
        <Button disabled={busy || deleting} onClick={restore} className="motion-sheen w-full">{minutesMode ? <RotateCcw /> : <Sparkles />}{minutesMode ? (zh ? '重新生成会议纪要' : 'Retry meeting notes') : (zh ? '稍后生成纪要' : 'Generate notes later')}</Button>
        <div className="grid grid-cols-3 gap-2"><Button variant="outline" size="sm" onClick={() => void load(false)}><Play />{zh ? '播放' : 'Play'}</Button><Button variant="outline" size="sm" onClick={() => void load(true)}><Download />{zh ? '下载' : 'Download'}</Button>
          <AlertDialog><AlertDialogTrigger asChild><Button variant="ghost" size="sm" disabled={busy || deleting} className="text-destructive hover:text-destructive"><Trash2 />{zh ? '删除' : 'Delete'}</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{zh ? '删除本地录制？' : 'Delete local recording?'}</AlertDialogTitle><AlertDialogDescription>{zh ? '录音或视频会从此设备永久删除，之后无法回放或生成纪要。' : 'This recording will be permanently removed from this device.'}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>{zh ? '取消' : 'Cancel'}</AlertDialogCancel><AlertDialogAction disabled={deleting} onClick={() => void remove()}>{zh ? '确认删除' : 'Delete'}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
        </div>{error ? <Alert variant="destructive" className="mt-1"><AlertDescription>{error}</AlertDescription></Alert> : null}
      </div>
    </div>
  </article>
}
