import { useEffect, useState } from 'react'
import { deleteLocalRecording, getRecordedAudio, type PendingMeeting } from '../../lib/audioStorage'
import { downloadRecording } from '../../lib/recordingDownload'
import { useI18n } from '../../lib/i18n'

export function LocalRecordingCard({ recording, busy, onDeleted }: { recording: PendingMeeting; busy: boolean; onDeleted: () => void }) {
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const title = recording.options.title || (zh ? '未命名会议' : 'Untitled meeting')
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  const load = async (download: boolean) => {
    setError('')
    try {
      const blob = await getRecordedAudio(recording.id)
      if (!blob) throw new Error(zh ? '找不到此设备上的录制文件' : 'Recording not found on this device')
      if (download) downloadRecording(blob, title)
      else setUrl(URL.createObjectURL(blob))
    } catch (cause) { setError(String(cause instanceof Error ? cause.message : cause)) }
  }
  return <article className="space-y-3 rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-[#202020]">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h3 className="font-medium">{title}</h3><p className="mt-1 text-xs text-gray-500">{new Date(recording.startedAt).toLocaleString()} · {Math.floor(recording.elapsedSeconds / 60)}:{String(recording.elapsedSeconds % 60).padStart(2, '0')} · {recording.options.screen ? (zh ? '视频' : 'Video') : (zh ? '录音' : 'Audio')}</p></div>
      <div className="flex flex-wrap gap-4 text-sm">
        <button onClick={() => void load(false)}>{zh ? '播放' : 'Play'}</button>
        <button onClick={() => void load(true)}>{zh ? '下载' : 'Download'}</button>
        <button disabled={busy || deleting} className="text-primary-light disabled:opacity-40" onClick={() => window.dispatchEvent(new CustomEvent('vinote-restore-meeting', { detail: recording }))}>{zh ? '生成纪要' : 'Generate notes'}</button>
        <button disabled={busy || deleting} className="text-red-600 disabled:opacity-40" onClick={() => setConfirming(true)}>{zh ? '删除录制' : 'Delete recording'}</button>
      </div>
    </div>
    {url && (recording.options.screen ? <video src={url} controls className="max-h-80 w-full rounded-lg" /> : <audio src={url} controls className="w-full" />)}
    {confirming && <div role="alertdialog" aria-label={zh ? '删除录制文件？' : 'Delete recording?'} className="space-y-3 rounded-lg bg-red-50 p-4 text-sm dark:bg-red-950/20">
      <p>{zh ? '将永久删除此设备上的录音或视频，之后无法回放或生成纪要。已下载的副本不受影响。' : 'Permanently delete this recording from this device. Downloaded copies are kept.'}</p>
      <div className="flex gap-4"><button disabled={deleting} onClick={() => setConfirming(false)}>{zh ? '取消' : 'Cancel'}</button><button disabled={deleting} className="text-red-600" onClick={async () => {
        setDeleting(true); setError(''); setUrl('')
        try { await deleteLocalRecording(recording.id, recording.ownerId); onDeleted() }
        catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
        finally { setDeleting(false) }
      }}>{zh ? '确认删除' : 'Confirm deletion'}</button></div>
    </div>}
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
  </article>
}
