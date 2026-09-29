import { useState } from 'react'
import { Mic2 } from 'lucide-react'
import { useI18n } from '../../lib/i18n'
import type { MeetingType } from '../../lib/meetingCapture'
import { Button } from '@/components/ui/button'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'

export function StartMeetingButton({ disabled, onStart }: { disabled: boolean; onStart: (type: MeetingType) => void }) {
  const [open, setOpen] = useState(false)
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const start = (type: MeetingType) => {
    if (disabled) return
    setOpen(false)
    // Keep display acquisition in the user's click, without an async boundary.
    onStart(type)
  }
  return <>
    <Button size="lg" disabled={disabled} className="h-12 w-full rounded-full px-7 sm:w-auto sm:min-w-52" onClick={() => setOpen(true)}><Mic2 data-icon="inline-start" />{zh ? '开始会议' : 'Start meeting'}</Button>
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{zh ? '这次会议需要共享屏幕吗？' : 'Share your screen for this meeting?'}</AlertDialogTitle>
          <AlertDialogDescription>{zh ? '共享屏幕会将所选窗口或屏幕画面一起录制；不共享则只录制麦克风声音。' : 'Sharing records the selected window or screen alongside your microphone. Without sharing, only microphone audio is recorded.'}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter className="gap-2">
          <AlertDialogCancel>{zh ? '取消' : 'Cancel'}</AlertDialogCancel>
          <Button variant="outline" disabled={disabled} onClick={() => start('audio')}>{zh ? '不共享，开始会议' : 'Start without sharing'}</Button>
          <AlertDialogAction disabled={disabled} onClick={() => start('video')}>{zh ? '共享屏幕并开始' : 'Share screen and start'}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </>
}
