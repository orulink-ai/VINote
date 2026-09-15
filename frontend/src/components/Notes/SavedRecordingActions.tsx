import { useEffect, useState } from 'react'
import { apiFetch, apiJson } from '../../lib/api'
import { downloadRecording } from '../../lib/recordingDownload'
import { useI18n } from '../../lib/i18n'

type RecordingInfo = { available: boolean; deleted: boolean; can_delete: boolean; filename: string; size_bytes: number }

export function SavedRecordingActions({ noteId, title, onDeleted }: { noteId: string; title: string; onDeleted: () => void }) {
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const [info, setInfo] = useState<RecordingInfo | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState(false)
  useEffect(() => {
    let active = true
    void apiJson<RecordingInfo>(`/api/notes/${noteId}/recording`).then(result => { if (active) setInfo(result) }).catch(cause => { if (active) setError(String(cause)) })
    return () => { active = false }
  }, [noteId])
  return <div className="border-b border-gray-200 bg-white px-4 py-3 text-sm dark:border-gray-700 dark:bg-[#202020]">
    <div className="flex flex-wrap items-center gap-4">
      <span>{zh ? '原始录制' : 'Original recording'}{info?.available ? ` · ${(info.size_bytes / 1024 / 1024).toFixed(1)} MB` : ''}</span>
      {info?.available && !info.can_delete && <span className="text-xs text-gray-500">{zh ? '文件被共用或无法验证归属，仅支持下载' : 'Shared or unverified recording: download only'}</span>}
      {info?.deleted && <span className="text-gray-500">{zh ? '文件已删除，纪要和转写已保留' : 'Recording deleted; notes and transcript retained'}</span>}
      {info?.available && <>
        <button disabled={busy} className="text-primary-light disabled:opacity-40" onClick={async () => {
          setBusy(true); setError('')
          try {
            const response = await apiFetch(`/api/notes/${noteId}/media`)
            if (!response.ok) throw new Error(zh ? '录制下载失败，请重试' : 'Download failed')
            downloadRecording(await response.blob(), title, info.filename)
          } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
          finally { setBusy(false) }
        }}>{zh ? '下载录音 / 视频' : 'Download recording'}</button>
        {info.can_delete && <button disabled={busy} className="text-red-600" onClick={() => setConfirming(true)}>{zh ? '删除录制文件' : 'Delete recording'}</button>}
      </>}
    </div>
    {confirming && <div role="alertdialog" aria-label={zh ? '删除录制文件？' : 'Delete recording?'} className="mt-3 space-y-3 rounded-lg bg-red-50 p-3 dark:bg-red-950/20">
      <p>{zh ? '将永久删除此录制及其音频副本，无法继续回放。文字纪要、转写和已生成的截图会保留。' : 'Permanently delete the recording and its audio copies. Notes, transcript and screenshots are retained.'}</p>
      <div className="flex gap-4"><button disabled={busy} onClick={() => setConfirming(false)}>{zh ? '取消' : 'Cancel'}</button><button disabled={busy} className="text-red-600" onClick={async () => {
        setBusy(true); setError('')
        try {
          document.querySelectorAll<HTMLMediaElement>('audio, video').forEach(media => { media.pause(); media.removeAttribute('src'); media.load() })
          await apiJson(`/api/notes/${noteId}/recording`, { method: 'DELETE' })
          setInfo(info ? { ...info, available: false, deleted: true } : null)
          setConfirming(false); onDeleted()
        } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
        finally { setBusy(false) }
      }}>{zh ? '确认删除文件' : 'Confirm deletion'}</button></div>
    </div>}
    {error && <p role="alert" className="mt-2 text-red-600">{error}</p>}
  </div>
}
