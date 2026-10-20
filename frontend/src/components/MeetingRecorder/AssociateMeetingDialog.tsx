import { useEffect, useId, useRef, useState } from 'react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Field, FieldLabel, FieldDescription } from '@/components/ui/field';
import { NativeSelect } from '@/components/ui/native-select';
import { apiJson } from '@/lib/api';
import { meetingRecordingTitle } from '@/lib/meetingGroups';
import { useAuthStore } from '@/stores/authStore';

type Target = {
  canonical_task_id: string;
  source_version: string;
  media_kind: 'audio' | 'video';
  recording_started_at: string | null;
};
type Association = {
  note_id: string;
  revision: number;
  source_version: string | null;
  meeting_source: { owner_id: string; canonical_task_id: string } | null;
};

export function AssociateMeetingDialog({ noteId, noteTitle, ownerId, onClose, onAssociated }: {
  noteId: string;
  noteTitle: string;
  ownerId: string;
  onClose: () => void;
  onAssociated: () => Promise<void> | void;
}) {
  const fieldId = useId();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const selectRef = useRef<HTMLSelectElement>(null);
  const [targets, setTargets] = useState<Target[]>([]);
  const [association, setAssociation] = useState<Association>();
  const [selected, setSelected] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [unknown, setUnknown] = useState(false);
  const live = useRef(false);
  const claimed = useRef(false);
  const selectedTarget = targets.find(target => target.canonical_task_id === selected);
  const current = () => live.current && useAuthStore.getState().user?.id === ownerId;
  const path = `/api/meeting-source-links/${encodeURIComponent(noteId)}`;
  useEffect(() => {
    if (!loading && document.activeElement === titleRef.current) selectRef.current?.focus({ preventScroll: true });
  }, [loading]);

  useEffect(() => {
    live.current = true;
    const controller = new AbortController();
    void Promise.all([
      apiJson<{ targets: Target[] }>('/api/meeting-source-links/targets', { signal: controller.signal }),
      apiJson<Association>(path, { signal: controller.signal }),
    ]).then(([options, existing]) => {
      if (!current() || controller.signal.aborted) return;
      if (!Array.isArray(options.targets) || existing.note_id !== noteId || !Number.isInteger(existing.revision)) throw new Error('归档信息读取不完整，请关闭后重新打开。');
      setTargets(options.targets);
      setAssociation(existing);
    }).catch(() => {
      if (current() && !controller.signal.aborted) setError('无法读取可关联的会议，请关闭后重新打开。');
    }).finally(() => { if (current() && !controller.signal.aborted) setLoading(false); });
    return () => { live.current = false; controller.abort(); };
  }, [noteId, ownerId, path]);

  const complete = async () => {
    await onAssociated();
    if (current()) onClose();
  };
  const matches = (result: Association, target: Target) => result.note_id === noteId &&
    result.meeting_source?.owner_id === ownerId && result.meeting_source.canonical_task_id === target.canonical_task_id &&
    result.source_version === target.source_version;
  const confirm = async () => {
    if (!current() || claimed.current || !selectedTarget || !association || association.meeting_source) return;
    claimed.current = true;
    setSaving(true);
    setError('');
    try {
      const result = await apiJson<Association>(path, { method: 'PUT', body: JSON.stringify({
        confirmed: true, canonical_task_id: selectedTarget.canonical_task_id,
        source_version: selectedTarget.source_version, expected_revision: association.revision,
      }) });
      if (!current()) return;
      if (!matches(result, selectedTarget)) throw new Error('Unconfirmed association');
      await complete();
    } catch (cause) {
      if (!current()) return;
      const status = cause && typeof cause === 'object' && 'status' in cause ? Number(cause.status) : 0;
      if (status >= 400 && status < 500) setError(cause instanceof Error ? cause.message : '关联未完成，请关闭后重新读取。');
      else {
        setUnknown(true);
        setError('关联结果尚未确认，请核验结果。');
      }
    } finally { if (current()) setSaving(false); }
  };
  const recover = async () => {
    if (!current() || saving || !selectedTarget) return;
    setSaving(true);
    try {
      const result = await apiJson<Association>(path);
      if (!current()) return;
      if (matches(result, selectedTarget)) await complete();
      else setError(result.meeting_source ? '此稿已有其他会议关联，请关闭后重新读取。' : '暂未读取到确认的关联，可继续核验。');
    } catch { if (current()) setError('尚无法核验关联结果，请稍后继续核验。'); }
    finally { if (current()) setSaving(false); }
  };

  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent closeLabel="关闭关联到会议" className="min-w-0 max-w-lg [overflow-wrap:anywhere]"
      onOpenAutoFocus={event => { event.preventDefault(); titleRef.current?.focus({ preventScroll: true }); }}>
      <DialogHeader>
        <DialogTitle ref={titleRef} tabIndex={-1}>关联到会议</DialogTitle>
        <DialogDescription className="text-left">
          选择这份纪要对应的录音或录屏档案，正文、保存版本和原项目均保留。
          <span className="mt-2 line-clamp-2" title={noteTitle}>纪要：{noteTitle}</span>
        </DialogDescription>
      </DialogHeader>
      {loading ? <p role="status" className="text-sm text-muted-foreground">正在核验可关联的会议…</p>
        : association?.meeting_source ? <p role="status" className="text-sm">此稿已关联到会议，无需重复归档。</p>
        : association && targets.length ? <Field className="min-w-0" data-invalid={!!error || undefined}>
          <FieldLabel htmlFor={fieldId}>选择原始录制</FieldLabel>
          <NativeSelect ref={selectRef} id={fieldId} className="min-w-0 max-w-full truncate" required
            aria-describedby={`${fieldId}-help${error ? ` ${fieldId}-error` : ''}`}
            aria-invalid={!!error || undefined} value={selected} disabled={saving || claimed.current} onChange={event => setSelected(event.target.value)}>
            <option value="">请选择会议</option>
            {targets.map(target => <option key={target.canonical_task_id} value={target.canonical_task_id}>
              {meetingRecordingTitle(target.recording_started_at || undefined)} · {target.media_kind === 'video' ? '录屏' : '录音'} · {target.canonical_task_id.slice(0, 8)}
            </option>)}
          </NativeSelect>
          <FieldDescription id={`${fieldId}-help`}>请选择与此稿对应的原始录制，再确认关联。尚未确认时不会归档。</FieldDescription>
        </Field> : association && !error ? <p className="text-sm text-muted-foreground">没有可核验的原始录制，内容继续保留在待归档。</p> : null}
      {saving && <p role="status" className="text-sm text-muted-foreground">{unknown ? '正在核验关联结果…' : '正在保存关联，请稍候…'}</p>}
      {error && <p id={`${fieldId}-error`} role="alert" className="text-sm leading-6 text-destructive">{error}</p>}
      <div aria-busy={saving} className="flex min-w-0 flex-wrap justify-end gap-2">
        <Button variant="outline" onClick={onClose}>关闭</Button>
        {association?.meeting_source ? <Button onClick={() => { void complete(); }}>刷新会议档案</Button>
          : unknown ? <Button disabled={saving} onClick={() => { void recover(); }}>{saving ? '正在核验…' : '核验关联结果'}</Button>
          : <Button disabled={loading || saving || claimed.current || !selectedTarget || !association} onClick={() => { void confirm(); }}>{saving ? '正在关联…' : '确认关联'}</Button>}
      </div>
    </DialogContent>
  </Dialog>;
}
