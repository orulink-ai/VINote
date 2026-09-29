import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getPendingMeeting, type PendingMeeting } from '../../lib/audioStorage'
import { processSavedMeeting } from '../../lib/meetingProcessing'
import { useAuthStore } from '../../stores/authStore'
import { useI18n } from '../../lib/i18n'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'

/** The route also hands a saved compatibility-window recording back to the main window. */
export function SavedRecordingChoice() {
  const [params, setParams] = useSearchParams()
  const id = params.get('recordingSaved')
  const userId = useAuthStore(state => state.user?.id)
  const [recording, setRecording] = useState<PendingMeeting | null>(null)
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')

  useEffect(() => {
    let active = true
    setRecording(null)
    if (id && userId) void getPendingMeeting(id).then(row => {
      if (active && row?.ownerId === userId && row.recordingStatus === 'saved' && row.processingStatus === 'idle') setRecording(row)
    }).catch(() => undefined) // The durable history remains available for later retry.
    return () => { active = false }
  }, [id, userId])

  const dismiss = () => {
    setRecording(null)
    setParams(current => { const next = new URLSearchParams(current); next.delete('recordingSaved'); return next }, { replace: true })
  }

  return <AlertDialog open={!!recording && recording.ownerId === userId} onOpenChange={open => { if (!open) dismiss() }}>
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>{zh ? '录制已保存，生成会议纪要？' : 'Recording saved. Generate meeting notes?'}</AlertDialogTitle>
        <AlertDialogDescription>{zh ? '原始录制已保存在本机。现在可以生成会议纪要，也可以暂不生成，之后从本地录制中继续。' : 'Your original recording is saved locally. Generate notes now, or keep it and generate them later from Local recordings.'}</AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel>{zh ? '暂不生成' : 'Not now'}</AlertDialogCancel>
        <AlertDialogAction onClick={() => { if (recording) void processSavedMeeting(recording, locale); dismiss() }}>{zh ? '生成会议纪要' : 'Generate meeting notes'}</AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
}
