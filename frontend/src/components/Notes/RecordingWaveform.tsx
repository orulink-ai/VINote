import { useEffect, useState } from 'react'
import { apiJson } from '@/lib/api'
import { Button } from '@/components/ui/button'

export function RecordingWaveform({ noteId, onSeek }: { noteId: string; onSeek?: (seconds: number) => void }) {
  const [data, setData] = useState<{ duration: number; peaks: number[] } | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    setData(null); setError('')
    void apiJson<{ duration: number; peaks: number[] }>(`/api/notes/${noteId}/waveform`).then(next => { if (active) { if (!Array.isArray(next?.peaks) || !Number.isFinite(next.duration)) throw new Error('录音预览暂不可用'); setData(next) } }).catch(cause => { if (active) setError(cause.message || '录音预览暂不可用') })
    return () => { active = false }
  }, [noteId, attempt])
  if (!data) return <div className="flex min-h-16 items-center text-xs text-muted-foreground">{error ? <span>{error}<Button variant="ghost" size="sm" onClick={() => setAttempt(value => value + 1)}>重试预览</Button></span> : '正在准备录音预览…'}</div>
  const waveform = <svg viewBox={`0 0 ${data.peaks.length * 4} 56`} className="h-14 w-full" aria-hidden="true">{data.peaks.map((peak, i) => <rect key={i} x={i * 4} y={28 - Math.max(2, peak * 24)} width="2.5" height={Math.max(4, peak * 48)} rx="1.25" fill="currentColor" />)}</svg>
  return <div className="grid gap-2 text-muted-foreground">{onSeek ? <button type="button" aria-label="从录音开头播放" onClick={() => onSeek(0)} className="rounded focus-visible:outline focus-visible:outline-2">{waveform}</button> : waveform}<span className="text-xs">录音 {Math.floor(data.duration / 60)}:{String(Math.floor(data.duration % 60)).padStart(2, '0')}</span></div>
}
