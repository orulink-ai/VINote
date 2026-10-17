import { useState } from 'react'
import { Pencil } from 'lucide-react'
import { useI18n } from '../../lib/i18n'
import { getPendingMeeting, updatePendingMeeting, type PendingMeeting } from '../../lib/audioStorage'
import { useAuthStore } from '../../stores/authStore'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'

export function RecordingTitleEditor({ recording, title, onSaved }: { recording: PendingMeeting; title: string; onSaved: (title: string) => void }) {
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(title)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const save = async () => {
    if (!draft.trim() || saving) return
    setSaving(true); setError('')
    try {
      const current = await getPendingMeeting(recording.id)
      if (!current || current.ownerId !== useAuthStore.getState().user?.id) throw new Error(zh ? '无法修改此录制' : 'Cannot rename this recording')
      await updatePendingMeeting(recording.id, { titleEdited: true, options: { ...current.options, title: draft.trim() } })
      onSaved(draft.trim()); setOpen(false)
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setSaving(false) }
  }
  return <AlertDialog open={open} onOpenChange={value => { if (!saving) { setOpen(value); if (value) { setDraft(title); setError('') } } }}>
    <AlertDialogTrigger asChild><Button variant="ghost" size="sm"><Pencil data-icon="inline-start" />{zh ? '修改录制标题' : 'Rename recording'}</Button></AlertDialogTrigger>
    <AlertDialogContent>
      <AlertDialogHeader><AlertDialogTitle>{zh ? '修改录制标题' : 'Rename recording'}</AlertDialogTitle><AlertDialogDescription>{zh ? '默认采用“时间｜内容”，也可以自定义。手动修改后，生成纪要不会覆盖此标题。已生成的纪要标题可在详情页单独修改。' : 'The default is time and subject. A custom title is preserved during generation. Saved note titles can be edited separately in their details.'}</AlertDialogDescription></AlertDialogHeader>
      <Input aria-label={zh ? '录制标题' : 'Recording title'} value={draft} maxLength={255} disabled={saving} onChange={event => setDraft(event.target.value)} />
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <AlertDialogFooter><AlertDialogCancel disabled={saving}>{zh ? '取消' : 'Cancel'}</AlertDialogCancel><AlertDialogAction disabled={saving || !draft.trim()} onClick={event => { event.preventDefault(); void save() }}>{zh ? '保存标题' : 'Save title'}</AlertDialogAction></AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
}
