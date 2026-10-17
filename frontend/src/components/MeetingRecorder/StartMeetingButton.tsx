import { Mic2, Monitor } from 'lucide-react'
import { useI18n } from '../../lib/i18n'
import type { MeetingType } from '../../lib/meetingCapture'
import { Button } from '@/components/ui/button'

export function StartMeetingButton({ disabled, type, onTypeChange, onStart }: { disabled: boolean; type: MeetingType; onTypeChange: (type: MeetingType) => void; onStart: (type: MeetingType) => void }) {
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const start = (type: MeetingType) => {
    if (disabled) return
    // Keep display acquisition in the user's click, without an async boundary.
    onStart(type)
  }
  return <div className="grid w-full gap-3">
    <fieldset disabled={disabled} className="grid grid-cols-2 gap-3">
      <legend className="mb-2 text-sm font-medium">{zh ? '录制内容' : 'Recording source'}</legend>
      {(['audio', 'video'] as const).map(value => <label key={value} className={`flex cursor-pointer items-center gap-2 rounded-xl border p-3 text-sm ${type === value ? 'border-foreground bg-muted' : ''}`}>
        <input type="radio" name="meeting-recording-source" checked={type === value} onChange={() => onTypeChange(value)} />
        {value === 'audio' ? <Mic2 className="size-4" /> : <Monitor className="size-4" />}
        {value === 'audio' ? (zh ? '仅录音' : 'Audio') : (zh ? '录音与屏幕' : 'Audio and screen')}
      </label>)}
    </fieldset>
    <Button size="lg" disabled={disabled} onClick={() => start(type)}><Mic2 />{zh ? '开始录制' : 'Start recording'}</Button>
  </div>
}
