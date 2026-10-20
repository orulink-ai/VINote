import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { publishScope } from '@/lib/feishuPublishReceipt';
import { feishuContacts, type FeishuContact, type FeishuPreferenceContact } from '@/lib/feishu';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Field, FieldLabel, FieldDescription, FieldGroup } from '@/components/ui/field';
import { Alert, AlertDescription } from '@/components/ui/alert';

export function FeishuPresetContacts({ value, onChange, disabled, connectionKey, connectionCurrent }: {
  value: FeishuPreferenceContact[]; onChange: (contacts: FeishuPreferenceContact[]) => void; disabled: boolean; connectionKey: number; connectionCurrent: () => boolean;
}) {
  const owner = useAuthStore(state => state.user?.id);
  const [query, setQuery] = useState(''), [items, setItems] = useState<FeishuContact[]>([]);
  const [loading, setLoading] = useState(false), [error, setError] = useState(''), [loaded, setLoaded] = useState(false);
  const [cursor, setCursor] = useState('');
  const [selectionGuard, setSelectionGuard] = useState<(() => boolean) | null>(null);
  const sequence = useRef(0), pending = useRef(false);
  const state = useRef({ query, owner, disabled, connectionKey });
  state.current = { query, owner, disabled, connectionKey };
  const invalidate = () => { ++sequence.current; pending.current = false; setLoading(false); setItems([]); setCursor(''); setError(''); setLoaded(false) };
  useEffect(() => { invalidate(); setQuery(''); return () => { ++sequence.current; pending.current = false } }, [owner, disabled, connectionKey]);
  const search = async (append = false) => {
    if (disabled || !owner || !query.trim() || pending.current || !connectionCurrent()) return;
    const request = ++sequence.current, expected = { query, owner, connectionKey }, scope = publishScope(owner);
    const current = () => {
      try { scope(); return connectionCurrent() && sequence.current === request && !state.current.disabled && state.current.owner === expected.owner && state.current.query === expected.query && state.current.connectionKey === expected.connectionKey } catch { return false }
    };
    pending.current = true; setLoading(true); setError('');
    try {
      const page = await feishuContacts(query.trim(), append ? cursor : '');
      if (!current()) return;
      setSelectionGuard(() => current);
      setItems(previous => [...new Map((append ? [...previous, ...page.items] : page.items).map(item => [item.open_id, item])).values()]);
      setCursor(page.has_more ? page.page_token : ''); setLoaded(true);
    } catch (cause) { if (current()) setError(cause instanceof Error ? cause.message : '联系人读取失败，请重试') }
    finally { if (current()) { pending.current = false; setLoading(false) } }
  };
  return <FieldGroup>
    <Field>
      <FieldLabel htmlFor="feishu-contact-query">预设通知联系人</FieldLabel>
      <Input id="feishu-contact-query" value={query} disabled={disabled} placeholder="搜索飞书联系人姓名"
        onChange={event => { invalidate(); state.current.query = event.target.value; setQuery(event.target.value) }} />
      <FieldDescription>新选择需在15分钟内保存；已保存的联系人无需重复搜索。仅用于此处的自动交付设置。</FieldDescription>
    </Field>
    <div className="flex flex-wrap gap-2">{value.map(contact => <Button key={contact.open_id} variant="outline" disabled={disabled} onClick={() => onChange(value.filter(item => item.open_id !== contact.open_id))} aria-label={`移除联系人${contact.name}`}>{contact.name} · 移除</Button>)}</div>
    <Button variant="outline" disabled={disabled || loading || !query.trim()} onClick={() => void search()}>{loading ? '正在读取联系人…' : error ? '重试搜索联系人' : '搜索联系人'}</Button>
    {error && <Alert variant="destructive"><AlertDescription>{error}，已选联系人继续保留。</AlertDescription></Alert>}
    {loading && <p role="status" className="text-sm text-muted-foreground">正在读取联系人，已选联系人继续保留…</p>}
    {loaded && !loading && !items.length && !error && <FieldDescription>没有匹配的联系人，请调整姓名。</FieldDescription>}
    {items.map(contact => <Button key={contact.open_id} variant="outline" disabled={disabled} onClick={() => {
      if (!selectionGuard?.() || !owner || state.current.owner !== owner || state.current.disabled || !contact.expiresAt || contact.expiresAt <= Date.now()) { setError('联系人选择已过期，请重新搜索'); return }
      if (value.length >= 20 && !value.some(item => item.open_id === contact.open_id)) { setError('最多选择20位联系人'); return }
      // Replace the same ID to renew an expired new selection; names only come from the API.
      onChange([...value.filter(item => item.open_id !== contact.open_id), { ...contact, name: contact.name! }]);
    }}>选择联系人{contact.name}</Button>)}
    {cursor && <Button variant="outline" disabled={disabled || loading} onClick={() => void search(true)}>下一页联系人</Button>}
  </FieldGroup>;
}
