import { useEffect, useState } from 'react'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { ExternalLink, Minus, Pause, Play, RotateCcw, Square } from 'lucide-react'
import { listenMeetingState, sendMeetingAction } from '../../lib/meetingController'
import { showMainWindow, startCurrentRecorderWindowDrag } from '../../lib/desktopRecorderWindow'
import { useI18n } from '../../lib/i18n'
import type { MeetingRecorderExternalSnapshot } from '../../stores/meetingRecorderStore'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'

export function MeetingRecorderController() {
  const [state, setState] = useState<MeetingRecorderExternalSnapshot>({ phase: 'requesting' })
  const { copy, locale } = useI18n()
  const zh = locale.startsWith('zh')
  useEffect(() => {
    let disposed = false
    let unsubscribe: (() => void) | undefined
    void listenMeetingState(setState).then(cleanup => {
      if (disposed) cleanup()
      else { unsubscribe = cleanup; void sendMeetingAction('sync') }
    })
    return () => { disposed = true; unsubscribe?.() }
  }, [])
  const phase = state.phase || 'requesting'
  const seconds = state.elapsedSeconds || 0
  const notePath = state.noteId ? '/note/' + state.noteId : '/meetings'
  return <Card className="flex h-full flex-col overflow-hidden rounded-2xl border-border/70 bg-card/95 shadow-lg backdrop-blur">
    <CardHeader className="flex-row items-center justify-between px-4 py-3">
      <CardTitle onPointerDown={() => void startCurrentRecorderWindowDrag()} className="flex cursor-grab items-center gap-2 text-sm">
        <span className="relative flex size-3"><span className="absolute inline-flex size-full animate-ping rounded-full bg-destructive/50" /><span className="relative inline-flex size-3 rounded-full bg-destructive" /></span>
        {zh ? '会议录制' : 'Meeting recording'}
      </CardTitle>
      <Button size="icon" variant="ghost" aria-label={zh ? '隐藏悬浮窗' : 'Hide controls'} onClick={() => void getCurrentWindow().hide()}><Minus /></Button>
    </CardHeader>
    <CardContent className="flex flex-1 items-center justify-between gap-3 border-t px-4 py-3">
      <div className="min-w-0">
        <Badge variant="secondary" className="font-mono text-base tabular-nums">{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')}</Badge>
        <p className="mt-1 max-w-36 truncate text-xs text-muted-foreground" title={state.error}>{state.error || copy.meetingRecorder.phases[phase]}</p>
      </div>
      <div className="flex items-center gap-2">
        {phase === 'recording' && <Button size="sm" variant="outline" onClick={() => void sendMeetingAction('pause')}><Pause />{copy.meetingRecorder.pause}</Button>}
        {phase === 'paused' && <Button size="sm" onClick={() => void sendMeetingAction('resume')}><Play />{copy.meetingRecorder.resume}</Button>}
        {['paused', 'recording'].includes(phase) && <Button size="sm" variant="destructive" onClick={() => void sendMeetingAction('stop')}><Square />{copy.meetingRecorder.stop}</Button>}
        {phase === 'stopped' && <Button size="sm" onClick={() => void sendMeetingAction('generate')}><Play />{zh ? '生成纪要' : 'Generate notes'}</Button>}
        {phase === 'failed' && <Button size="sm" variant="outline" onClick={() => void sendMeetingAction('retry')}><RotateCcw />{zh ? '重试' : 'Retry'}</Button>}
        <Button size="icon" variant="outline" aria-label={zh ? '打开工作台' : 'Open workspace'} onClick={() => void showMainWindow(notePath)}><ExternalLink /></Button>
      </div>
    </CardContent>
  </Card>
}
