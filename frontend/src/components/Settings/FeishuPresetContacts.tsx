import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { publishScope } from '@/lib/feishuPublishReceipt';
import { feishuContacts, type FeishuContact, type FeishuPreferenceContact } from '@/lib/feishu';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Field, FieldLabel, FieldDescription, FieldGroup } from '@/components/ui/field';
import { Alert, AlertDescription } from '@/components/ui/alert';

export function FeishuPresetContacts({ value, onChange, disabled, connectionKey, connectionCurrent, hideHeading = false, browseRecent = false }: {
  value: FeishuPreferenceContact[]; onChange: (contacts: FeishuPreferenceContact[]) => void; disabled: boolean; connectionKey: number; connectionCurrent: () => boolean;
  hideHeading?: boolean; browseRecent?: boolean;
}) {
  const owner = useAuthStore(state => state.user?.id);
  const [query, setQuery] = useState(''), [items, setItems] = useState<FeishuContact[]>([]);
  const [loading, setLoading] = useState(false), [error, setError] = useState(''), [loaded, setLoaded] = useState(false);
  const [cursor, setCursor] = useState('');
  const [searchRequired, setSearchRequired] = useState(false);
  const [selectionGuard, setSelectionGuard] = useState<(() => boolean) | null>(null);
  const sequence = useRef(0), pending = useRef(false);
  const state = useRef({ query, owner, disabled, connectionKey });
  state.current = { query, owner, disabled, connectionKey };
  const invalidate = () => { ++sequence.current; pending.current = false; setLoading(false); setItems([]); setCursor(''); setError(''); setLoaded(false) };
  useEffect(() => { invalidate(); setQuery(''); state.current.query = ''; if (browseRecent && !disabled) void search(false, ''); return () => { ++sequence.current; pending.current = false } }, [owner, disabled, connectionKey, browseRecent]);
  const search = async (append = false, initialQuery?: string) => {
    const searched = initialQuery ?? query;
    if (disabled || !owner || (!searched.trim() && !browseRecent) || pending.current || !connectionCurrent()) return;
    const request = ++sequence.current, expected = { query: searched, owner, connectionKey }, scope = publishScope(owner);
    const current = () => {
      try { scope(); return connectionCurrent() && sequence.current === request && !state.current.disabled && state.current.owner === expected.owner && state.current.query === expected.query && state.current.connectionKey === expected.connectionKey } catch { return false }
    };
    pending.current = true; setLoading(true); setError('');
    try {
      const page = await feishuContacts(searched.trim(), append ? cursor : '');
      if (!current()) return;
      setSelectionGuard(() => current);
      setItems(previous => [...new Map((append ? [...previous, ...page.items] : page.items).map(item => [item.open_id, item])).values()]);
      setCursor(page.has_more ? page.page_token : ''); setSearchRequired(page.search_required === true); setLoaded(true);
    } catch (cause) { if (current()) setError(cause instanceof Error ? cause.message : '联系人读取失败，请重试') }
    finally { if (current()) { pending.current = false; setLoading(false) } }
  };
  return <FieldGroup>
    <Field>
      <FieldLabel htmlFor="feishu-contact-query" className={hideHeading ? 'sr-only' : undefined}>预设通知联系人</FieldLabel>
      <div className="flex items-center gap-2">
      <Input id="feishu-contact-query" value={query} disabled={disabled} placeholder="搜索飞书联系人姓名"
        onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); void search(); } }}
        onChange={event => { invalidate(); state.current.query = event.target.value; setQuery(event.target.value) }} />
      <Button className="shrink-0" variant="outline" disabled={disabled || loading || (!query.trim() && !browseRecent)} onClick={() => void search()}>{loading ? '正在读取联系人…' : error ? '重试搜索联系人' : '搜索联系人'}</Button>
      </div>
      <FieldDescription>{browseRecent ? '显示近期可见联系人；输入姓名后按回车，可查找其他人。' : '输入姓名后按回车，或点击搜索联系人。'}</FieldDescription>
    </Field>
    <div className="flex flex-wrap gap-2">{value.map(contact => <Button key={contact.open_id} variant="outline" disabled={disabled} onClick={() => onChange(value.filter(item => item.open_id !== contact.open_id))} aria-label={`移除联系人${contact.name}`}>{contact.name} · 移除</Button>)}</div>
    {error && <Alert variant="destructive"><AlertDescription>{error}，已选联系人继续保留。</AlertDescription></Alert>}
    {loading && <p role="status" className="text-sm text-muted-foreground">正在读取联系人，已选联系人继续保留…</p>}
    {loaded && !loading && !items.length && !error && <FieldDescription>{query.trim() ? '没有匹配的联系人，请尝试完整姓名或检查飞书可见范围。' : '暂无近期联系人，请输入姓名搜索。'}</FieldDescription>}
    {loaded && !loading && searchRequired && <FieldDescription>当前只显示部分联系人，可输入具体姓名继续查找。</FieldDescription>}
    <div className="grid max-h-72 gap-2 overflow-y-auto">
    {items.map(contact => <Button key={contact.open_id} variant="outline" disabled={disabled} onClick={() => {
      if (!selectionGuard?.() || !owner || state.current.owner !== owner || state.current.disabled || !contact.expiresAt || contact.expiresAt <= Date.now()) { setError('联系人选择已过期，请重新搜索'); return }
      if (value.length >= 20 && !value.some(item => item.open_id === contact.open_id)) { setError('最多选择20位联系人'); return }
      // Replace the same ID to renew an expired new selection; names only come from the API.
      onChange([...value.filter(item => item.open_id !== contact.open_id), { ...contact, name: contact.name! }]);
    }}>选择联系人{contact.name}</Button>)}
    </div>
    {cursor && <Button variant="outline" disabled={disabled || loading} onClick={() => void search(true)}>下一页联系人</Button>}
    <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">联系人选择说明</summary><p className="mt-2 leading-5">选择后请保存设置。新选择超过15分钟未保存需重新查找，已有预设不受影响。选择联系人本身不会发送消息。</p></details>
  </FieldGroup>;
}
