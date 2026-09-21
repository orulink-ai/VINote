interface TranscriptionProgressProps {
  processedSeconds?: number
  totalSeconds?: number
  etaSeconds?: number
  zh: boolean
}

function duration(seconds: number) {
  const value = Math.max(0, Math.floor(seconds))
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`
}

export function TranscriptionProgress({ processedSeconds, totalSeconds, etaSeconds, zh }: TranscriptionProgressProps) {
  const measured = Number.isFinite(processedSeconds) && Number.isFinite(totalSeconds) && totalSeconds! > 0
  const processed = measured ? Math.min(totalSeconds!, Math.max(0, processedSeconds!)) : 0
  const percentage = measured ? Math.floor(processed / totalSeconds! * 100) : undefined
  const complete = measured && processed >= totalSeconds!
  const hasEstimate = Number.isFinite(etaSeconds) && etaSeconds! > 0 && processed > 0 && !complete
  return <div className="flex flex-col gap-2 text-sm" aria-live="polite" aria-atomic="true">
    <p>{measured
      ? `${zh ? '已转写' : 'Transcribed'} ${duration(processed)} / ${duration(totalSeconds!)} (${percentage}%)`
      : zh ? '正在转写完整录音' : 'Transcribing the complete recording'}</p>
    <p className="text-xs text-muted-foreground">{complete
      ? zh ? '音频转写完成，正在整理结果。' : 'Transcription complete; preparing results.'
      : hasEstimate
        ? zh ? `转写预计还需约 ${Math.ceil(etaSeconds!)} 秒，以实际服务速度为准。` : `About ${Math.ceil(etaSeconds!)} seconds remaining for transcription; service speed may vary.`
        : zh ? '等待实际分段结果，暂无法估算剩余时间。' : 'Waiting for measured results; remaining time is not yet available.'}</p>
  </div>
}
