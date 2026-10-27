import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { publishScope } from '@/lib/feishuPublishReceipt';
import { feishuObjectHotwords, refreshFeishuObjectHotwords, bindFeishuObjectAlias, deleteFeishuObjectAlias, normalizeObjectAlias, type FeishuObjectHotwords as Directory } from '@/lib/feishu';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { FeishuObjectPicker } from './FeishuObjectPicker';
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Alert, AlertDescription } from '@/components/ui/alert';

export function FeishuObjectHotwords({ connectionKey, connectionCurrent }: { connectionKey: number; connectionCurrent: () => boolean }) {
  const owner = useAuthStore(state => state.user?.id);
  const [visit, setVisit] = useState(0);
  const [data, setData] = useState<Directory | null>(null);
  const [alias, setAlias] = useState(''), [target, setTarget] = useState('');
  const [pending, setPending] = useState(''), [error, setError] = useState(''), [message, setMessage] = useState('');
  const sequence = useRef(0), working = useRef(false), directoryGuard = useRef<(() => boolean) | null>(null);
  const live = useRef({ owner, connectionKey, connectionCurrent }); live.current = { owner, connectionKey, connectionCurrent };
  // Handlers retain the exact batch/identity that rendered them, even after ABA.
  const displayedDirectory = directoryGuard.current;
  const renderScope = owner ? publishScope(owner) : null;
  const readable = () => !!displayedDirectory?.();
  const run = async (action: string, request: () => Promise<Directory>) => {
    if (!owner || working.current || !connectionCurrent()) return;
    try { if (!renderScope) return; renderScope() } catch { return }
    const seq = ++sequence.current, scope = publishScope(owner);
    const current = () => {
      try { scope(); return seq === sequence.current && live.current.owner === owner && live.current.connectionKey === connectionKey && live.current.connectionCurrent() } catch { return false }
    };
    working.current = true; setPending(action); setError(''); setMessage('');
    try {
      const next = await request();
      if (!current()) return;
      setData(next); directoryGuard.current = current;
      if (action === 'save') { setAlias(''); setTarget(''); setMessage('别称已保存。') }
      if (action === 'delete') setMessage('别称已删除。');
      if (action === 'refresh') setMessage('已更新当前可见对象。');
      setTarget(previous => next.objects.some(item => item.id === previous) ? previous : '');
    } catch (cause) { if (current()) setError(cause instanceof Error ? cause.message : '对象目录读取失败，请重试') }
    finally { if (current()) { working.current = false; setPending('') } }
  };
  useEffect(() => useAuthStore.subscribe((state, previous) => {
    if (state.user?.id !== previous.user?.id) { ++sequence.current; working.current = false; directoryGuard.current = null; setVisit(value => value + 1) }
  }), []);
  useEffect(() => {
    setData(null); setAlias(''); setTarget(''); setError(''); setMessage(''); setPending('');
    working.current = false; directoryGuard.current = null;
    void run('read', feishuObjectHotwords);
    return () => { ++sequence.current; working.current = false; directoryGuard.current = null };
  }, [owner, visit, connectionKey]);
  const bind = () => {
    if (!data || !readable() || working.current) return;
    const text = alias.trim(), selected = data.objects.find(item => item.id === target);
    if (!text || Array.from(text).length > 50 || !selected) { setError('请输入1至50字的别称，并选择一个真实联系人或群。'); return }
    const normalized = normalizeObjectAlias(text);
    if (data.aliases.some(item => normalizeObjectAlias(item.alias) === normalized)
      || data.objects.some(item => item.id !== selected.id && normalizeObjectAlias(item.name) === normalized)) {
      setError('这个别称已对应其他名称或绑定，请换一个不会混淆的别称。'); return;
    }
    void run('save', () => bindFeishuObjectAlias(text, selected.id));
  };
  const available = readable() && !pending;
  return <section aria-label="对象热词设置" className="flex flex-col gap-5 rounded-xl border p-5">
    <div className="flex flex-col gap-2"><h2 className="font-medium">对象热词</h2><p className="text-sm text-muted-foreground">为当前飞书可见的联系人或群绑定常用别称。每个别称只绑定一个对象，不按相似姓名自动匹配；保存别称不会发送消息。</p></div>
    <Button variant="outline" disabled={!!pending} onClick={() => void run('refresh', refreshFeishuObjectHotwords)}>{pending === 'refresh' ? '正在更新对象…' : '更新可见对象'}</Button>
    {pending && <p role="status" className="text-sm text-muted-foreground">{pending === 'save' ? '正在保存别称…' : pending === 'delete' ? '正在删除别称…' : '正在读取当前可见对象…'}</p>}
    {error && <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription><Button variant="outline" disabled={!!pending} onClick={() => void run('read', feishuObjectHotwords)}>重新读取对象</Button></Alert>}
    {message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}
    {data && <>
      <p className="text-sm text-muted-foreground">{data.partial ? '当前仅显示部分可见对象，可更新后再查找。' : '以下为当前授权可见的对象。'}</p>
      <FieldGroup>
        <Field><FieldLabel htmlFor="feishu-object-target">绑定对象</FieldLabel><FeishuObjectPicker objects={data.objects} value={target} onChange={setTarget} disabled={!available} isCurrent={readable} /><FieldDescription>同名对象会分别保留，请确认对象后绑定。当前可见 {data.objects.length} 个对象。</FieldDescription></Field>
        <Field data-invalid={Array.from(alias.trim()).length > 50}><FieldLabel htmlFor="feishu-object-alias">别称</FieldLabel><Input id="feishu-object-alias" disabled={!available} value={alias} aria-invalid={Array.from(alias.trim()).length > 50} aria-describedby="feishu-object-alias-help" onChange={event => setAlias(event.target.value)} placeholder="例如项目群的常用简称" /><FieldDescription id="feishu-object-alias-help">最长50字；仅明确选择的对象会与此别称绑定。</FieldDescription></Field>
      </FieldGroup>
      <Button disabled={!available || !alias.trim() || Array.from(alias.trim()).length > 50 || !target} onClick={bind}>保存别称</Button>
      {!pending && !error && !data.objects.length && <p className="text-sm text-muted-foreground">当前没有可见对象，可更新后再试。</p>}
      <h3 className="text-sm font-medium">已保存别称</h3>
      {!data.aliases.length && !error && <p className="text-sm text-muted-foreground">尚未绑定别称。</p>}
      <ul aria-label="已保存别称" className="flex flex-col gap-3">{data.aliases.map(item => <li key={item.id} className="flex items-center justify-between gap-3"><span className="min-w-0 break-words text-sm">{item.alias} → {item.target_name} · {item.kind === 'group' ? '群' : '联系人'}</span><Button variant="ghost" disabled={!available} aria-label={`删除别称${item.alias}`} onClick={() => { if (readable()) void run('delete', () => deleteFeishuObjectAlias(item.id)) }}>删除</Button></li>)}</ul>
    </>}
  </section>;
}
