import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { ApiError, apiJson } from '@/lib/api';
import { publishScope } from '@/lib/feishuPublishReceipt';
import { readRuntimeConfig } from '@/lib/runtimeConfig';
import { useAuthStore } from '@/stores/authStore';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Alert, AlertDescription } from '@/components/ui/alert';

type Receipt = {
  protocol: 1; delivery_id: string; state: 'creating' | 'unknown' | 'confirmed' | 'failed';
  title: string; root_destination: { kind: 'wiki'; space_id: string; node_token: string };
  context_revision: string; can_recover: boolean; document_url: string;
};
function validate(value: Receipt, id: string) {
  if (!value || value.protocol !== 1 || value.delivery_id !== id || !['creating', 'unknown', 'confirmed', 'failed'].includes(value.state)
    || typeof value.title !== 'string' || !/^[a-f0-9]{64}$/.test(value.context_revision)
    || typeof value.can_recover !== 'boolean' || value.can_recover && value.state !== 'unknown'
    || value.root_destination?.kind !== 'wiki' || !value.root_destination.space_id || !value.root_destination.node_token) {
    throw new Error('原会议目录状态未核验，请重新查询');
  }
  return value;
}

/** Association only. The host may refresh a receipt; it must not auto-resume. */
export function FeishuMeetingContainerRecovery({ deliveryId, onRecovered }: { deliveryId: string; onRecovered?: () => void }) {
  const owner = useAuthStore(state => state.user?.id), location = useLocation();
  const route = JSON.stringify([location.key, location.pathname, location.search, location.hash]);
  const origin = readRuntimeConfig('VITE_API_BASE_URL') || window.location.origin;
  const key = JSON.stringify([owner, deliveryId, origin]);
  const storageKey = `vinote:feishu-container-recovery:${key}`;
  const path = `/api/feishu/meeting-containers/by-delivery/${encodeURIComponent(deliveryId)}`;
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [url, setUrl] = useState(''), [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState(''), [busy, setBusy] = useState('read');
  const [unknown, setUnknown] = useState(false), [success, setSuccess] = useState(false);
  const [attempt, setAttempt] = useState(0), [visit, setVisit] = useState(0);
  const sequence = useRef(0), pending = useRef(false), readGuard = useRef<(() => boolean) | null>(null);
  const live = useRef({ key, route }); live.current = { key, route };
  const displayedGuard = readGuard.current;
  const callback = useRef(onRecovered); callback.current = onRecovered;
  useEffect(() => useAuthStore.subscribe((next, previous) => {
    if (next.user?.id !== previous.user?.id) { ++sequence.current; pending.current = false; readGuard.current = null; setVisit(old => old + 1) }
  }), []);
  useEffect(() => {
    const request = ++sequence.current, scope = owner ? publishScope(owner) : null;
    const current = () => {
      try { scope?.(); return !!scope && sequence.current === request && live.current.key === key && live.current.route === route } catch { return false }
    };
    readGuard.current = null; pending.current = true;
    setBusy('read'); setError(''); setReceipt(null); setSuccess(false); setConfirmed(false); setUrl('');
    let uncertain = false;
    try { uncertain = sessionStorage.getItem(storageKey) === 'unknown' } catch { /* No submission has been authorized here. */ }
    setUnknown(uncertain);
    if (!owner) { pending.current = false; setBusy(''); return }
    void apiJson<Receipt>(path, { cache: 'no-store' }).then(raw => {
      if (!current()) return;
      const next = validate(raw, deliveryId); readGuard.current = current; setReceipt(next);
      if (uncertain && next.state === 'confirmed') {
        try { sessionStorage.removeItem(storageKey) } catch { /* Readback is authoritative. */ }
        setUnknown(false); setSuccess(true); callback.current?.();
      }
    }).catch(cause => {
      if (current() && (!(cause instanceof ApiError) || cause.status !== 404 || uncertain)) setError(cause instanceof Error ? cause.message : '原目录状态读取失败');
    }).finally(() => { if (current()) { pending.current = false; setBusy('') } });
    return () => { ++sequence.current; pending.current = false; readGuard.current = null };
  }, [key, route, visit, attempt]);
  const associate = async () => {
    if (pending.current || unknown || !receipt?.can_recover || !confirmed || !url.trim() || !displayedGuard?.()) return;
    // Persist before dispatch. A lost response/remount can only read this job.
    try { sessionStorage.setItem(storageKey, 'unknown') }
    catch { setError('恢复状态无法保存在此浏览器，未提交关联。请保留原交付记录。'); return }
    pending.current = true; setBusy('associate'); setError('');
    const current = displayedGuard;
    try {
      const raw = await apiJson<Receipt>(path + '/recover', { method: 'POST', body: JSON.stringify({
        expected_user_id: owner, confirmed: true, context_revision: receipt.context_revision, url: url.trim(),
      }) });
      if (!current()) return;
      const next = validate(raw, deliveryId);
      if (next.state !== 'confirmed') throw new Error('关联结果未确认，请查询原目录状态');
      setReceipt(next); setUnknown(false); setSuccess(true);
      try { sessionStorage.removeItem(storageKey) } catch { /* Successful readback remains authoritative. */ }
      callback.current?.();
    } catch (cause) {
      if (!current()) return;
      const definite = cause instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(cause.status);
      if (definite) {
        try { sessionStorage.removeItem(storageKey) } catch { /* Retain the marker on remount if cleanup fails. */ }
        setError(cause.message);
      } else { setUnknown(true); setError('关联结果尚未确认，只能查询原目录状态，不会重复提交。') }
    } finally { if (current()) { pending.current = false; setBusy('') } }
  };
  if (busy === 'read') return <p role="status" className="text-sm text-muted-foreground">正在查询原会议目录…</p>;
  if (success) return <p role="status" className="text-sm">会议目录已关联，尚未继续交付。</p>;
  if (!error && !unknown && !receipt?.can_recover) return null;
  return <section aria-label="恢复原会议目录" className="flex min-w-0 flex-col gap-3 rounded-lg border p-4">
    <h3 className="text-sm font-medium">核验原会议目录</h3>
    {receipt && <p className="break-words text-sm">{receipt.title}</p>}
    <p className="text-sm text-muted-foreground">目录创建结果未确认。请在原知识库父节点下核对已有会议目录；关联不会新建目录或继续交付，目录可以已有子文档。</p>
    {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
    {unknown ? <Button variant="outline" disabled={!!busy} onClick={() => setAttempt(old => old + 1)}>查询原目录状态</Button> : receipt?.can_recover ? <>
      <FieldGroup><Field><FieldLabel htmlFor="feishu-existing-container">已有会议目录的 Wiki 链接或节点标识</FieldLabel><Input id="feishu-existing-container" value={url} disabled={!!busy} onChange={event => { setUrl(event.target.value); setConfirmed(false) }} /><FieldDescription>须为原父节点下、标题一致的普通实体 Wiki 目录；不会打开或抓取填写的网址。</FieldDescription></Field>
        <Field orientation="horizontal"><Checkbox id="feishu-confirm-container" checked={confirmed} disabled={!!busy} onCheckedChange={value => setConfirmed(value === true)} /><FieldLabel htmlFor="feishu-confirm-container">我已核对这是原会议目录</FieldLabel></Field>
      </FieldGroup>
      <div className="flex flex-wrap gap-2"><Button disabled={!!busy || !confirmed || !url.trim()} onClick={() => void associate()}>{busy === 'associate' ? '正在核验并关联…' : '核验并关联现有目录'}</Button><Button variant="outline" disabled={!!busy} onClick={() => { setUrl(''); setConfirmed(false); setError('') }}>取消关联</Button></div>
    </> : <Button variant="outline" onClick={() => setAttempt(old => old + 1)}>查询原目录状态</Button>}
  </section>;
}
