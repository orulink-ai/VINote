import { useEffect, useState } from 'react'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { listenMeetingState, sendMeetingAction } from '../../lib/meetingController'
import { showMainWindow, startCurrentRecorderWindowDrag } from '../../lib/desktopRecorderWindow'
import { useI18n } from '../../lib/i18n'
import type { MeetingRecorderExternalSnapshot } from '../../stores/meetingRecorderStore'

/** A control surface only: capture stays in the window that received the user's click. */
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
  return <section className="flex h-full flex-col justify-between rounded-2xl border border-gray-200 bg-white p-4 text-gray-900">
    <div className="flex items-center justify-between">
      <span onPointerDown={() => void startCurrentRecorderWindowDrag()} className="cursor-grab text-sm font-semibold">{zh ? '会议记录' : 'Meeting recording'}</span>
      <button aria-label={zh ? '隐藏悬浮窗' : 'Hide controls'} onClick={() => void getCurrentWindow().hide()}>−</button>
    </div>
    <div className="flex items-center justify-between gap-3">
      <span className="font-mono text-lg tabular-nums">{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')}</span>
      <div className="flex gap-3 text-sm text-primary-light">
        {phase === 'recording' && <button onClick={() => void sendMeetingAction('pause')}>{copy.meetingRecorder.pause}</button>}
        {phase === 'paused' && <button onClick={() => void sendMeetingAction('resume')}>{copy.meetingRecorder.resume}</button>}
        {['paused', 'recording'].includes(phase) && <button onClick={() => void sendMeetingAction('stop')}>{copy.meetingRecorder.stop}</button>}
        {phase === 'stopped' && <button onClick={() => void sendMeetingAction('generate')}>{zh ? '生成纪要' : 'Generate notes'}</button>}
        {phase === 'failed' && <button onClick={() => void sendMeetingAction('retry')}>{zh ? '重试' : 'Retry'}</button>}
        <button onClick={() => void showMainWindow(state.noteId ? `/note/${state.noteId}` : '/meetings')}>{zh ? '查看' : 'Open'}</button>
      </div>
    </div>
    <p className="truncate text-xs text-gray-500" title={state.error}>{state.error || copy.meetingRecorder.phases[phase]}</p>
  </section>
}
