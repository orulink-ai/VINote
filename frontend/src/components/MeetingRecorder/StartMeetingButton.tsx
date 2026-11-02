import { useId } from 'react'
import { Mic2, Monitor } from 'lucide-react'
import { useI18n } from '../../lib/i18n'
import type { MeetingType } from '../../lib/meetingCapture'
import { Button } from '@/components/ui/button'

export function StartMeetingButton({ disabled, type, onTypeChange, onStart }: { disabled: boolean; type: MeetingType; onTypeChange: (type: MeetingType) => void; onStart: (type: MeetingType) => void }) {
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const sourceId = useId()
  const start = (type: MeetingType) => {
    if (disabled) return
    // Keep display acquisition in the user's click, without an async boundary.
    onStart(type)
  }
  return <div className="grid w-full gap-4">
    <fieldset disabled={disabled} className="grid gap-3 sm:grid-cols-2 disabled:opacity-60">
      <legend className="mb-2 text-sm font-medium">{zh ? '录制内容' : 'Recording source'}</legend>
      {(['audio', 'video'] as const).map(value => <label key={value} className={`flex min-w-0 items-start gap-3 rounded-lg border p-4 text-sm transition-colors focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 ${disabled ? 'cursor-not-allowed' : 'cursor-pointer hover:bg-muted/50'} ${type === value ? 'border-foreground/50 bg-muted/60' : 'border-border'}`}>
        <input className="mt-1 size-4 shrink-0 accent-current" type="radio" name={sourceId} aria-labelledby={`${sourceId}-${value}-label`} aria-describedby={`${sourceId}-${value}-description`} checked={type === value} onChange={() => onTypeChange(value)} />
        <span className="min-w-0">
          <span id={`${sourceId}-${value}-label`} className="flex items-center gap-2 font-medium">
            {value === 'audio' ? <Mic2 aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" /> : <Monitor aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />}
            {value === 'audio' ? (zh ? '仅录音' : 'Audio') : (zh ? '录音与屏幕' : 'Audio and screen')}
          </span>
          <span id={`${sourceId}-${value}-description`} className="mt-2 block text-xs leading-5 text-muted-foreground">
            {value === 'audio' ? (zh ? '使用所选麦克风记录现场声音' : 'Capture sound from the selected microphone') : (zh ? '开始时选择要录制的窗口或屏幕' : 'Choose a window or screen when you start')}
          </span>
        </span>
      </label>)}
    </fieldset>
    <Button size="lg" disabled={disabled} onClick={() => start(type)}><Mic2 />{zh ? '开始录制' : 'Start recording'}</Button>
  </div>
}
