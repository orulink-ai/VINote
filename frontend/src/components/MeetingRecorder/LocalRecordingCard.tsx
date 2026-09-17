import { useEffect, useState } from 'react'
import { Download, FileAudio, FileVideo, Play, Sparkles, Trash2 } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { deleteLocalRecording, getRecordedAudio, type PendingMeeting } from '../../lib/audioStorage'
import { downloadRecording } from '../../lib/recordingDownload'
import { useI18n } from '../../lib/i18n'

export function LocalRecordingCard({ recording, busy, onDeleted }: { recording: PendingMeeting; busy: boolean; onDeleted: () => void }) {
  const { locale } = useI18n(); const zh = locale.startsWith('zh')
  const [url, setUrl] = useState(''); const [error, setError] = useState(''); const [deleting, setDeleting] = useState(false)
  const title = recording.options.title || (zh ? '未命名会议' : 'Untitled meeting')
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  const load = async (download: boolean) => { setError(''); try { const blob = await getRecordedAudio(recording.id); if (!blob) throw new Error(zh ? '找不到此设备上的录制文件' : 'Recording not found on this device'); if (download) downloadRecording(blob, title); else setUrl(URL.createObjectURL(blob)) } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) } }
  const remove = async () => { setDeleting(true); setError(''); setUrl(''); try { await deleteLocalRecording(recording.id, recording.ownerId); onDeleted() } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) } finally { setDeleting(false) } }
  const Icon = recording.options.screen ? FileVideo : FileAudio
  return <Card><CardHeader className="flex-row items-start justify-between gap-4"><div className="flex min-w-0 gap-3"><div className="grid size-10 shrink-0 place-items-center rounded-xl bg-muted"><Icon className="size-5" /></div><div className="min-w-0"><CardTitle className="truncate text-base">{title}</CardTitle><p className="mt-1 text-xs text-muted-foreground">{new Date(recording.startedAt).toLocaleString()} · {Math.floor(recording.elapsedSeconds / 60)}:{String(recording.elapsedSeconds % 60).padStart(2, '0')}</p></div></div><Badge variant="secondary">{recording.options.screen ? (zh ? '录屏' : 'Video') : (zh ? '录音' : 'Audio')}</Badge></CardHeader>
    <CardContent className="grid gap-4">{url ? recording.options.screen ? <video src={url} controls className="max-h-80 w-full rounded-xl bg-muted" /> : <audio src={url} controls className="w-full" /> : null}
      <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => void load(false)}><Play />{zh ? '播放' : 'Play'}</Button><Button variant="outline" size="sm" onClick={() => void load(true)}><Download />{zh ? '下载' : 'Download'}</Button><Button size="sm" disabled={busy || deleting} onClick={() => window.dispatchEvent(new CustomEvent('vinote-restore-meeting', { detail: recording }))}><Sparkles />{zh ? '生成纪要' : 'Generate notes'}</Button>
        <AlertDialog><AlertDialogTrigger asChild><Button variant="ghost" size="sm" disabled={busy || deleting} className="text-destructive hover:text-destructive"><Trash2 />{zh ? '删除' : 'Delete'}</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{zh ? '删除本地录制？' : 'Delete local recording?'}</AlertDialogTitle><AlertDialogDescription>{zh ? '录音或视频会从此设备永久删除，之后无法回放或生成纪要。' : 'This recording will be permanently removed from this device.'}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>{zh ? '取消' : 'Cancel'}</AlertDialogCancel><AlertDialogAction disabled={deleting} onClick={() => void remove()}>{zh ? '确认删除' : 'Delete'}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
      </div>{error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}</CardContent></Card>
}
