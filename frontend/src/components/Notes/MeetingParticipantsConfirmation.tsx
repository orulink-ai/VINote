import { useEffect, useId, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { ApiError, apiJson } from '@/lib/api';
import { feishuContacts, type FeishuPreferenceContact } from '@/lib/feishu';
import { publishScope } from '@/lib/feishuPublishReceipt';
import { useAuthStore } from '@/stores/authStore';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from '@/components/ui/field';

export type MeetingParticipantsContext = {
  note_key: string; task_id: string; canonical_task_id: string | null; evidence_revision: string; can_confirm: boolean;
  candidates: { candidate_id: string; name: string; status: string; evidence: { role?: string; excerpt?: string; start?: number }[] }[];
  confirmation: { revision: number; status: 'confirmed' | 'cleared' | 'stale' | 'unconfirmed'; participants: { open_id: string; name: string }[] };
};
export type MeetingParticipantsConfirmationProps = {
  noteId: string; taskId: string; disabled?: boolean;
  connectionKey?: string | number; sourceRevision?: string;
  onConfirmed?: () => void;
};

const roles: Record<string, string> = { self_introduction: '自我介绍表述', attendance_statement: '参会名单表述', action_owner: '任务负责人', mention: '普通提及', visual_name: '画面中的姓名' };
const validId = (value: string) => /^ou_[A-Za-z0-9_-]{1,196}$/.test(value);

function checkedContext(value: MeetingParticipantsContext, noteId: string, taskId: string) {
  if (!value || value.note_key !== noteId || value.task_id !== taskId || !/^[a-f0-9]{64}$/.test(value.evidence_revision)
    || typeof value.can_confirm !== 'boolean' || !Array.isArray(value.candidates)
    || value.candidates.some(c => !c || typeof c.name !== 'string' || typeof c.candidate_id !== 'string' || !Array.isArray(c.evidence))
    || !value.confirmation || !Number.isSafeInteger(value.confirmation.revision) || value.confirmation.revision < 0
    || !['confirmed', 'cleared', 'stale', 'unconfirmed'].includes(value.confirmation.status)
    || !Array.isArray(value.confirmation.participants) || value.confirmation.participants.length > 20
    || value.confirmation.participants.some(p => !p || typeof p.open_id !== 'string' || !validId(p.open_id) || typeof p.name !== 'string' || !p.name.trim())
    || new Set(value.confirmation.participants.map(p => p.open_id)).size !== value.confirmation.participants.length) {
    throw new Error('参会人资料未核验，请重新读取。');
  }
  return value;
}

/** Mount in a saved personal desktop meeting. This component never publishes. */
export function MeetingParticipantsConfirmation(props: MeetingParticipantsConfirmationProps) {
  const owner = useAuthStore(s => s.user?.id);
  const location = useLocation();
  return <ConfirmationAction key={JSON.stringify([owner, location.key, location.pathname, location.search, location.hash,
    props.noteId, props.taskId, props.connectionKey, props.sourceRevision, props.disabled])} {...props} owner={owner} />;
}

function ConfirmationAction({ noteId, taskId, disabled = false, onConfirmed, owner }: MeetingParticipantsConfirmationProps & { owner?: string }) {
  const [open, setOpen] = useState(false), [view, setView] = useState<MeetingParticipantsContext | null>(null);
  const [selected, setSelected] = useState<FeishuPreferenceContact[]>([]), [attested, setAttested] = useState(false);
  const [query, setQuery] = useState(''), [items, setItems] = useState<FeishuPreferenceContact[]>([]), [cursor, setCursor] = useState('');
  const [busy, setBusy] = useState(false), [searching, setSearching] = useState(false);
  const [error, setError] = useState(''), [message, setMessage] = useState(''), [mustRead, setMustRead] = useState(false);
  const mounted = useRef(true), generation = useRef(0), searchSequence = useRef(0), locked = useRef(false);
  const guard = useRef<(() => void) | null>(null), queryRef = useRef(query), disabledRef = useRef(disabled);
  queryRef.current = query; disabledRef.current = disabled;
  const id = useId(), path = `/api/meeting-participants/${encodeURIComponent(noteId)}`;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; ++generation.current; ++searchSequence.current } }, []);
  const active = (epoch: number) => {
    try { guard.current?.(); return mounted.current && !disabledRef.current && generation.current === epoch && !!owner && owner === useAuthStore.getState().user?.id } catch { return false }
  };
  const changeOpen = (next: boolean) => {
    ++generation.current; ++searchSequence.current; locked.current = false;
    setOpen(next); setBusy(false); setSearching(false); setView(null); setSelected([]); setItems([]); setCursor('');
    setQuery(''); setAttested(false); setError(''); setMessage(''); setMustRead(false);
    if (next) void read();
  };
  async function read() {
    if (!owner || disabledRef.current || locked.current) return;
    const epoch = generation.current;
    try { guard.current = publishScope(owner) } catch { return }
    locked.current = true; setBusy(true); setError(''); setMessage(''); setAttested(false); setView(null); setItems([]); setMustRead(true);
    try {
      const context = checkedContext(await apiJson<MeetingParticipantsContext>(path, { cache: 'no-store' }), noteId, taskId);
      if (!active(epoch)) return;
      setView(context); setSelected(context.confirmation.participants); setMustRead(false);
    } catch (cause) { if (active(epoch)) setError(cause instanceof Error ? cause.message : '读取参会人资料失败，请重试。') }
    finally { if (active(epoch)) { locked.current = false; setBusy(false) } }
  }
  async function search(append = false) {
    if (!view?.can_confirm || busy || searching || !query.trim() || !active(generation.current)) return;
    const epoch = generation.current, seq = ++searchSequence.current, expected = query;
    const current = () => active(epoch) && seq === searchSequence.current && queryRef.current === expected;
    setSearching(true); setError('');
    try {
      const page = await feishuContacts(query.trim(), append ? cursor : '');
      if (!current()) return;
      setItems(previous => [...new Map((append ? [...previous, ...page.items] : page.items).map(p => [p.open_id, p])).values()] as FeishuPreferenceContact[]);
      setCursor(page.has_more ? page.page_token : '');
      if (!page.items.length) setMessage('没有匹配的联系人，请调整姓名。');
    } catch (cause) { if (current()) setError(cause instanceof Error ? cause.message : '联系人读取失败，请重试。') }
    finally { if (current()) setSearching(false) }
  }
  async function save() {
    const epoch = generation.current;
    if (!view || !attested || mustRead || locked.current || searching || !active(epoch)
      || !view.can_confirm) return;
    locked.current = true; setBusy(true); setError(''); setMessage('');
    let dispatched = false;
    try {
      const contacts = [];
      for (const participant of selected) {
        let fresh = participant;
        if (!fresh.selection_token || !fresh.expiresAt || fresh.expiresAt <= Date.now()) {
          const page = await feishuContacts(participant.name);
          if (!active(epoch)) return;
          const matches = page.items.filter(p => p.open_id === participant.open_id);
          if (matches.length !== 1) throw new Error(`未能核验已选联系人“${participant.name}”，请重新搜索并选择。`);
          fresh = { ...matches[0], name: participant.name };
        }
        if (!active(epoch)) return;
        if (!fresh.selection_token || !fresh.expiresAt || fresh.expiresAt <= Date.now()) throw new Error('联系人选择已过期，请重新搜索。');
        contacts.push({ open_id: participant.open_id, selection_token: fresh.selection_token });
      }
      if (!active(epoch)) return;
      dispatched = true;
      const saved = checkedContext(await apiJson<MeetingParticipantsContext>(path, { method: 'PUT', body: JSON.stringify({
        confirmed: true, task_id: taskId, evidence_revision: view.evidence_revision,
        confirmation_revision: view.confirmation.revision, contacts,
      }) }), noteId, taskId);
      if (!active(epoch)) return;
      setView(saved); setSelected(saved.confirmation.participants); setAttested(false); setItems([]); setCursor('');
      setMessage('已保存参会人确认。已启用且等待本次确认的自动交付会按会议通知设置继续处理。');
      onConfirmed?.();
    } catch (cause) {
      if (!active(epoch)) return;
      if (dispatched) { setMustRead(true); setAttested(false); setSelected([]) }
      setError(cause instanceof ApiError && cause.status === 409 ? '名单或会议资料已变化，请重新读取并确认。'
        : dispatched ? '保存结果尚未核验，请重新读取名单；不会自动重复保存。'
        : cause instanceof Error ? cause.message : '联系人暂不能核验，请重试。');
    } finally { if (active(epoch)) { locked.current = false; setBusy(false) } }
  }
  const editingDisabled = busy || searching || mustRead;
  return <Dialog open={open} onOpenChange={changeOpen}>
    <DialogTrigger asChild><Button type="button" variant="outline" size="sm" disabled={disabled || !owner}>确认参会人</Button></DialogTrigger>
    <DialogContent closeLabel="关闭参会人确认" className="flex max-h-[85dvh] max-w-2xl flex-col">
      <DialogHeader><DialogTitle>本会议参会人</DialogTitle><DialogDescription>请核对实际参会者对应的飞书联系人，材料中的姓名只是线索。保存后，已启用且等待本次确认的自动交付会按会议通知设置继续创建文档并通知；未启用则只保存名单。</DialogDescription></DialogHeader>
      <div className="flex min-h-0 flex-col gap-4 overflow-y-auto" aria-busy={busy}>
        {busy && <p role="status">{view ? '正在核验并保存…' : '正在读取参会人资料…'}</p>}
        {searching && <p role="status">正在读取联系人…</p>}
        {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
        {message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}
        {view && <>
          {view.confirmation.status === 'stale' && <p role="status">原确认的来源或连接已变化，请重新核对。</p>}
          {!view.can_confirm && <p role="status">当前来源资料无法完整核验，暂不能确认名单或选择不通知参会人。</p>}
          <details><summary className="cursor-pointer text-sm">查看材料中的姓名线索（{view.candidates.length}）</summary>
            <ul className="flex flex-col gap-3 pt-2">{view.candidates.map(c => <li key={c.candidate_id} className="text-sm">
              <p className="break-words">{c.name} · 待核对</p>
              {c.evidence.slice(0, 3).map((e, index) => <p key={index} className="break-words text-muted-foreground">{roles[e.role || ''] || '材料线索'}{e.excerpt ? `：${e.excerpt}` : ''}</p>)}
            </li>)}</ul>
          </details>
          <FieldSet disabled={editingDisabled}><FieldLegend>本次确认名单（{selected.length}人）</FieldLegend>
            {!selected.length && <FieldDescription>尚未选择联系人。候选线索不会自动加入名单。</FieldDescription>}
            <ul className="flex flex-col gap-2">{selected.map(p => <li key={p.open_id} className="flex items-center justify-between gap-2">
              <span className="min-w-0 break-words text-sm">{p.name} · {p.open_id}</span>
              <Button type="button" variant="ghost" size="sm" onClick={() => { if (!active(generation.current)) return; setSelected(selected.filter(item => item.open_id !== p.open_id)); setAttested(false) }} aria-label={`移除参会人${p.name}`}>移除</Button>
            </li>)}</ul>
            <FieldGroup><Field><FieldLabel htmlFor={`${id}-search`}>搜索飞书联系人</FieldLabel>
              <Input id={`${id}-search`} value={query} maxLength={50} disabled={!view.can_confirm} placeholder="输入联系人姓名"
                onChange={event => { ++searchSequence.current; setQuery(event.target.value); queryRef.current = event.target.value; setItems([]); setCursor(''); setSearching(false); setMessage('') }} />
              <FieldDescription>同名时请核对飞书对象；已有名单保存前会重新核验。</FieldDescription>
            </Field></FieldGroup>
            <Button type="button" variant="outline" disabled={!view.can_confirm || !query.trim()} onClick={() => void search()}>搜索联系人</Button>
            <ul className="flex flex-col gap-2">{items.map(p => <li key={p.open_id}><Button type="button" variant="outline" className="h-auto w-full whitespace-normal justify-start" onClick={() => {
              if (!active(generation.current) || !p.expiresAt || p.expiresAt <= Date.now()) { setError('联系人选择已过期，请重新搜索。'); return }
              if (selected.length >= 20 && !selected.some(s => s.open_id === p.open_id)) { setError('最多选择20位参会人。'); return }
              setSelected([...selected.filter(s => s.open_id !== p.open_id), p]); setAttested(false);
            }}>选择{p.name}（{p.open_id}）</Button></li>)}</ul>
            {cursor && <Button type="button" variant="outline" onClick={() => void search(true)}>下一页联系人</Button>}
          </FieldSet>
          <Field orientation="horizontal" data-disabled={editingDisabled}>
            <Checkbox id={`${id}-attest`} checked={attested} disabled={editingDisabled || !view.can_confirm} onCheckedChange={checked => setAttested(checked === true)} />
            <FieldLabel htmlFor={`${id}-attest`}>{selected.length ? '我确认所选飞书对象实际参加了本次会议' : '本会议不通知参会人'}</FieldLabel>
          </Field>
          {!selected.length && <FieldDescription>需主动确认后保存；通知本人仍按独立设置执行。</FieldDescription>}
        </>}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" disabled={busy || searching} onClick={() => void read()}>重新读取名单</Button>
        <Button type="button" disabled={!view || editingDisabled || !attested || !view.can_confirm} onClick={() => void save()}>{selected.length ? '保存参会人确认' : '确认不通知参会人'}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
