import { useEffect, useRef, useState } from 'react';
import { apiJson } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';
import { getPendingMeeting, updatePendingMeeting, type PendingMeeting } from '@/lib/audioStorage';
import { MEETING_DISPLAY_CHANGED } from '@/hooks/useMeetingDisplay';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';

export function MeetingDisplayEditor({ sourceKey, recording, title, date, onSaved }: {
  sourceKey?: string; recording?: PendingMeeting; title: string; date: string; onSaved?: () => void;
}) {
  const owner = useAuthStore(s => s.user?.id);
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [draftTitle, setDraftTitle] = useState(title), [draftDate, setDraftDate] = useState(date);
  const [savedOwner, setSavedOwner] = useState<string>();
  const epoch = useRef(0), openedEpoch = useRef(0);
  useEffect(() => useAuthStore.subscribe?.((next, previous) => {
    if (next.user?.id !== previous.user?.id) { epoch.current++; setOpen(false); }
  }), []);
  const remote = sourceKey && /^(task|file):[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(sourceKey);
  if (!remote && !recording) return null;
  const save = async () => {
    if (epoch.current !== openedEpoch.current || busy || !savedOwner || savedOwner !== owner || useAuthStore.getState().user?.id !== savedOwner) return;
    const started = epoch.current;
    const currentScope = () => started === epoch.current && useAuthStore.getState().user?.id === savedOwner;
    setBusy(true); setError('');
    try {
      if (remote) {
        const [kind, id] = sourceKey!.split(':');
        await apiJson(`/api/meeting-source-links/display/${kind}/${id}`, { method: 'PUT', body: JSON.stringify({ title: draftTitle.trim(), meeting_date: draftDate || null }) });
      } else if (recording) {
        const current = await getPendingMeeting(recording.id);
        if (!current || current.ownerId !== savedOwner || !currentScope()) throw new Error('账号或原录制已变化');
        await updatePendingMeeting(recording.id, { displayTitle: draftTitle.trim(), displayDate: draftDate || null });
      }
      if (!currentScope()) return;
      window.dispatchEvent(new Event(MEETING_DISPLAY_CHANGED)); onSaved?.(); setOpen(false);
    } catch (cause) { if (currentScope()) setError(cause instanceof Error ? cause.message : '保存失败，请重试'); }
    finally { setBusy(false); }
  };
  return <><Button size="sm" variant="ghost" onClick={() => { setDraftTitle(title); setDraftDate(date); setSavedOwner(owner); openedEpoch.current = epoch.current; setError(''); setOpen(true); }}>编辑会议信息</Button>
    <Dialog open={open && owner === savedOwner} onOpenChange={value => { if (!busy) setOpen(value); }}><DialogContent><DialogHeader><DialogTitle>会议名称与日期</DialogTitle><DialogDescription>用于列表展示与日期整理；不修改原始文件名、录制证据或已保存纪要。</DialogDescription></DialogHeader>
      <label className="grid gap-2 text-sm">会议名称<Input value={draftTitle} maxLength={180} onChange={event => setDraftTitle(event.target.value)} placeholder="未命名会议" disabled={busy} /></label>
      <label className="grid gap-2 text-sm">会议日期<Input type="date" value={draftDate} onChange={event => setDraftDate(event.target.value)} disabled={busy} /></label>
      <p className="text-xs text-muted-foreground">日期可补填或修改，清空后使用原录制日期；没有原录制日期则保持未知。</p>
      <details className="text-xs text-muted-foreground"><summary className="cursor-pointer py-2">稳定会议标识</summary><code className="select-text break-all">{sourceKey || `recording:${recording?.id}`}</code></details>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <DialogFooter><Button variant="outline" onClick={() => setOpen(false)} disabled={busy}>取消</Button><Button onClick={() => void save()} disabled={busy}>{busy ? '正在保存…' : '保存会议信息'}</Button></DialogFooter>
    </DialogContent></Dialog></>;
}
