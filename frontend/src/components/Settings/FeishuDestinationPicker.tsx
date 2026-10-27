import { useEffect, useRef, useState } from 'react';
import { ChevronRight, Folder, Star } from 'lucide-react';
import { useAuthStore } from '@/stores/authStore';
import { publishScope } from '@/lib/feishuPublishReceipt';
import { apiJson } from '@/lib/api';
import type { DestinationCheck, FeishuDestination } from '@/lib/feishu';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Field, FieldGroup, FieldLabel, FieldDescription } from '@/components/ui/field';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { ErrorState, EmptyState } from '@/components/Feedback/ResourceState';

type Item = { kind: 'folder' | 'wiki'; folder_token?: string; space_id?: string; node_token?: string; name: string; has_child?: boolean };
type Place = { target: FeishuDestination; name: string };
type SavedPlaces = { recent: Place[]; favorites: Place[] };
type Directory = { scope: Record<string, string>; name: string };
const identity = (target: FeishuDestination) => target.kind === 'personal' ? 'personal' : target.kind === 'folder' ? `folder:${target.folder_token}` : `wiki:${target.space_id}:${target.node_token}`;
const complete = (target: FeishuDestination) => target.kind === 'personal' || (target.kind === 'folder' ? !!target.folder_token : !!target.space_id && !!target.node_token);
const label = (target: FeishuDestination) => target.kind === 'personal' ? '个人云文档' : complete(target) ? '已保留文档位置，请核验以读取名称。' : '尚未选择，请浏览可见位置。';
const blank = (kind: string): FeishuDestination => kind === 'folder' ? { kind, folder_token: '' } : kind === 'wiki' ? { kind, space_id: '', node_token: '' } : { kind: 'personal' };
const storageKey = (owner: string, connectionKey: string) => `vinote:feishu-destinations:${encodeURIComponent(owner)}:${encodeURIComponent(window.location.origin)}:${encodeURIComponent(connectionKey)}`;
function readPlaces(owner?: string, connectionKey?: string): SavedPlaces {
  const empty = { recent: [], favorites: [] };
  if (!owner || !connectionKey) return empty;
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey(owner, connectionKey)) || 'null');
    const valid = (value: unknown): value is Place => {
      if (!value || typeof value !== 'object') return false;
      const item = value as Place, target = item.target;
      const token = (text: unknown) => typeof text === 'string' && text.length > 0 && text.length <= 512;
      return typeof item.name === 'string' && item.name.length > 0 && item.name.length <= 300 && !!target
        && (target.kind === 'personal' || target.kind === 'folder' && token(target.folder_token) || target.kind === 'wiki' && token(target.space_id) && token(target.node_token));
    };
    return { recent: Array.isArray(parsed?.recent) ? parsed.recent.filter(valid).slice(0, 8) : [], favorites: Array.isArray(parsed?.favorites) ? parsed.favorites.filter(valid).slice(0, 12) : [] };
  } catch { return empty }
}

export function FeishuDestinationPicker({ value, onChange, capabilities, disabled, onChecked, autoCheck = false, connectionKey }: {
  value: FeishuDestination; onChange: (value: FeishuDestination) => void;
  capabilities?: Record<string, boolean>; disabled?: boolean;
  onChecked?: (value: DestinationCheck | null) => void; autoCheck?: boolean;
  connectionKey?: string;
}) {
  const owner = useAuthStore(state => state.user?.id);
  const [open, setOpen] = useState(false), [advanced, setAdvanced] = useState(false);
  const [draft, setDraft] = useState<FeishuDestination>(value), [draftName, setDraftName] = useState(label(value));
  const [check, setCheck] = useState<DestinationCheck | null>(null);
  const [items, setItems] = useState<Item[]>([]), [loaded, setLoaded] = useState(false);
  const [parent, setParent] = useState<Directory>({ scope: {}, name: '可见位置' }), [history, setHistory] = useState<Directory[]>([]);
  const [pageToken, setPageToken] = useState(''), [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(''), [error, setError] = useState(''), [dialogError, setDialogError] = useState('');
  const [places, setPlaces] = useState<SavedPlaces>(() => readPlaces(owner, connectionKey)), [visit, setVisit] = useState(0);
  const sequence = useRef(0), pending = useRef(false), dialogOpen = useRef(false);
  const confirmed = useRef<{ target: string; owner?: string; connectionKey?: string; check: DestinationCheck }>();
  const checkedCallback = useRef(onChecked); checkedCallback.current = onChecked;
  const target = identity(value);
  const live = useRef({ target, owner, disabled, connectionKey, capabilities }); live.current = { target, owner, disabled, connectionKey, capabilities };
  const renderScope = owner ? publishScope(owner) : null;
  const allowed = (next: FeishuDestination) => next.kind === 'personal' || live.current.capabilities?.[next.kind] !== false;
  const currentRender = () => {
    try { renderScope?.(); return !!renderScope && live.current.owner === owner && live.current.target === target && live.current.connectionKey === connectionKey && !live.current.disabled } catch { return false }
  };
  const invalidate = () => { ++sequence.current; pending.current = false; setBusy('') };
  const close = () => { invalidate(); dialogOpen.current = false; setOpen(false); setDialogError('') };
  useEffect(() => {
    if (typeof useAuthStore.subscribe !== 'function') return;
    let previousOwner = useAuthStore.getState().user?.id;
    return useAuthStore.subscribe(next => {
      if (next.user?.id !== previousOwner) {
        previousOwner = next.user?.id;
        ++sequence.current; pending.current = false; dialogOpen.current = false; confirmed.current = undefined; setOpen(false); setVisit(old => old + 1);
      }
    });
  }, []);
  const savePlaces = (next: SavedPlaces) => {
    if (!owner || !connectionKey || !currentRender()) return;
    setPlaces(next);
    try { localStorage.setItem(storageKey(owner, connectionKey), JSON.stringify(next)) }
    catch { setDialogError('快捷位置无法保存到此浏览器，仍可浏览并核验位置。') }
  };
  const verify = async (candidate: FeishuDestination, inDialog: boolean) => {
    if (pending.current || !currentRender() || !complete(candidate) || !allowed(candidate)) return;
    const request = ++sequence.current, scope = publishScope(owner!);
    const current = () => {
      try { scope(); return request === sequence.current && currentRender() && allowed(candidate) && (!inDialog || dialogOpen.current) } catch { return false }
    };
    pending.current = true; setBusy('check');
    if (inDialog) setDialogError(''); else { setError(''); setCheck(null); checkedCallback.current?.(null) }
    try {
      const next = await apiJson<DestinationCheck>('/api/feishu/destinations/check', { method: 'POST', body: JSON.stringify(candidate) });
      if (!current()) return;
      if (!next || !Array.isArray(next.path) || next.path.some(part => typeof part !== 'string') || typeof next.can_attempt_create !== 'boolean') throw new Error('位置核验响应不完整，请重新核验');
      if (identity(next) !== identity(candidate)) throw new Error('位置核验响应与所选位置不符，请重新核验');
      if (inDialog) {
        if (!next.can_attempt_create) throw new Error(typeof next.reason === 'string' && next.reason || '当前目标不能提交创建，请选择其他位置。');
        const entry = { target: candidate, name: next.path.join(' / ') || next.name || draftName };
        savePlaces({ ...places, recent: [entry, ...places.recent.filter(item => identity(item.target) !== identity(candidate))].slice(0, 8) });
        confirmed.current = { target: identity(candidate), owner, connectionKey, check: next };
        onChange(candidate); setCheck(next); checkedCallback.current?.(next); close();
      } else { setCheck(next); checkedCallback.current?.(next) }
    } catch (cause) {
      if (current()) (inDialog ? setDialogError : setError)(cause instanceof Error ? cause.message : '位置核验失败，请重试');
    } finally { if (request === sequence.current) { pending.current = false; setBusy('') } }
  };
  const browse = async (kind: 'folder' | 'wiki', directory: Directory = { scope: {}, name: '可见位置' }, append = false, back = false) => {
    if (pending.current || !currentRender() || !dialogOpen.current || capabilities?.[kind] === false) return false;
    const request = ++sequence.current, scope = publishScope(owner!);
    const current = () => {
      try { scope(); return request === sequence.current && currentRender() && dialogOpen.current } catch { return false }
    };
    pending.current = true; setBusy('browse'); setDialogError('');
    try {
      const params = new URLSearchParams({ kind, ...directory.scope, ...(append ? { page_token: pageToken } : {}) });
      const next = await apiJson<{ items: Item[]; has_more: boolean; page_token: string }>(`/api/feishu/destinations?${params}`);
      if (!current()) return false;
      if (!next || !Array.isArray(next.items) || typeof next.has_more !== 'boolean' || typeof next.page_token !== 'string' || next.has_more && !next.page_token || next.items.some(item => !item || item.kind !== kind || typeof item.name !== 'string' || !item.name.trim() || (item.kind === 'folder' ? !item.folder_token : !item.space_id))) throw new Error('目录响应不完整，请刷新当前目录');
      if (!append) {
        if (back) setHistory(old => old.slice(0, -1));
        else if (loaded && Object.keys(directory.scope).length > 0 && JSON.stringify(directory.scope) !== JSON.stringify(parent.scope)) setHistory(old => [...old, parent]);
      }
      setItems(old => append ? [...old, ...next.items] : next.items); setLoaded(true);
      setParent(directory); setPageToken(next.page_token); setHasMore(next.has_more);
      return true;
    } catch (cause) {
      if (current()) setDialogError(cause instanceof Error ? cause.message : '目录读取失败，请重试');
      return false;
    } finally { if (request === sequence.current) { pending.current = false; setBusy('') } }
  };
  const openPicker = (next: boolean) => {
    if (!next) { close(); return }
    if (!currentRender()) return;
    invalidate(); dialogOpen.current = true; setOpen(true); setAdvanced(false); setDialogError('');
    setDraft(value); setDraftName(check?.name || label(value)); setItems([]); setLoaded(false); setHistory([]); setParent({ scope: {}, name: '可见位置' }); setHasMore(false);
    if (value.kind !== 'personal') void browse(value.kind);
  };
  const editDraft = (next: FeishuDestination, name = label(next)) => {
    if (!currentRender() || !dialogOpen.current) return;
    invalidate(); setDraft(next); setDraftName(name); setDialogError('');
  };
  const chooseShortcut = (item: Place) => {
    if (!currentRender() || !dialogOpen.current) return;
    editDraft(item.target, item.name);
    setItems([]); setLoaded(false); setHistory([]); setParent({ scope: {}, name: '可见位置' }); setHasMore(false);
    if (item.target.kind !== 'personal') void browse(item.target.kind);
  };
  const changeKind = (kind: string) => {
    if (!currentRender() || !dialogOpen.current) return;
    const next = blank(kind); editDraft(next); setAdvanced(false); setItems([]); setLoaded(false); setHistory([]); setParent({ scope: {}, name: '可见位置' }); setHasMore(false);
    if (next.kind !== 'personal') void browse(next.kind);
  };
  const previousTarget = useRef<{ target: string; owner?: string; visit: number; connectionKey?: string }>();
  useEffect(() => {
    invalidate();
    const changed = previousTarget.current?.target !== target || previousTarget.current?.owner !== owner || previousTarget.current?.visit !== visit || previousTarget.current?.connectionKey !== connectionKey;
    previousTarget.current = { target, owner, visit, connectionKey };
    if (confirmed.current?.target === target && confirmed.current.owner === owner && confirmed.current.connectionKey === connectionKey) {
      setCheck(confirmed.current.check); checkedCallback.current?.(confirmed.current.check); confirmed.current = undefined;
    } else if (autoCheck || changed) {
      if (changed && dialogOpen.current) close();
      setCheck(null); setError(''); checkedCallback.current?.(null);
      if (autoCheck && !disabled && complete(value)) void verify(value, false);
    }
    return () => { ++sequence.current; pending.current = false };
  }, [target, owner, visit, autoCheck, disabled, connectionKey]);
  useEffect(() => { if (disabled) close() }, [disabled]);
  useEffect(() => { setPlaces(readPlaces(owner, connectionKey)); setCheck(null); setError('') }, [owner, visit, connectionKey]);
  const selectedName = check && identity(check) === target ? check.path.join(' / ') || check.name || label(value) : label(value);
  const favorite = places.favorites.some(item => identity(item.target) === identity(draft));
  const shortcuts = (heading: string, entries: Place[]) => !!entries.length && <section aria-label={heading} className="flex flex-col gap-2">
    <h3 className="text-sm font-medium">{heading}</h3><div className="flex flex-wrap gap-2">{entries.map(item => <Button key={identity(item.target)} variant="outline" size="sm" disabled={!!busy || !allowed(item.target)} className="max-w-full" onClick={() => chooseShortcut(item)}><span className="truncate">{item.name}</span></Button>)}</div>
  </section>;
  return <FieldGroup className="min-w-0">
    <Field><FieldLabel>文档位置</FieldLabel>
      <div role="region" aria-label="已选文档位置" className="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-lg border p-3">
        <div className="flex min-w-0 flex-1 items-center gap-2"><Folder aria-hidden="true" className="size-4 shrink-0" /><span className="min-w-0 break-words text-sm [overflow-wrap:anywhere]">{selectedName}</span></div>
        <Dialog open={open} onOpenChange={openPicker}>
          <DialogTrigger asChild><Button variant="outline" size="sm" disabled={disabled || !!busy}>选择文档位置</Button></DialogTrigger>
          <DialogContent closeLabel="取消选择位置" className="flex max-h-[85dvh] w-[calc(100vw-2rem)] max-w-2xl flex-col overflow-hidden">
            <DialogHeader><DialogTitle>选择文档位置</DialogTitle><DialogDescription>进入只浏览目录；选择后点击确认核验创建权限。取消保留原位置。</DialogDescription></DialogHeader>
            <div className="flex min-h-0 flex-col gap-4 overflow-y-auto overscroll-contain">
              <FieldGroup><Field><FieldLabel htmlFor="feishu-location-kind">位置类型</FieldLabel><NativeSelect id="feishu-location-kind" aria-label="文档位置类型" value={draft.kind} disabled={!!busy} onChange={event => changeKind(event.target.value)}>
                <NativeSelectOption value="personal">个人云文档</NativeSelectOption><NativeSelectOption value="folder" disabled={capabilities?.folder === false}>个人 / 组织共享文件夹</NativeSelectOption><NativeSelectOption value="wiki" disabled={capabilities?.wiki === false}>知识库节点</NativeSelectOption>
              </NativeSelect></Field></FieldGroup>
              {shortcuts('收藏位置', places.favorites)}{shortcuts('最近使用', places.recent)}
              <div role="region" aria-label="待确认位置" className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-muted/40 p-3"><p className="min-w-0 flex-1 break-words text-sm [overflow-wrap:anywhere]">待确认：{draftName}</p>
                <Button size="sm" variant="ghost" disabled={!!busy || !complete(draft) || !connectionKey} aria-pressed={favorite} onClick={() => savePlaces({ ...places, favorites: favorite ? places.favorites.filter(item => identity(item.target) !== identity(draft)) : [{ target: draft, name: draftName }, ...places.favorites].slice(0, 12) })}><Star aria-hidden="true" data-icon="inline-start" />{favorite ? '取消收藏' : '收藏位置'}</Button>
              </div>
              {!connectionKey && <p className="text-xs text-muted-foreground">连接身份尚未核验，暂不读取或保存最近与收藏位置。</p>}
              {draft.kind !== 'personal' && <section aria-label="可见目录" className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2"><span className="min-w-0 break-words text-sm">当前目录：{parent.name}</span><div className="flex gap-2">{!!history.length && <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => void browse(draft.kind as 'folder' | 'wiki', history[history.length - 1], false, true)}>返回上一级位置</Button>}<Button size="sm" variant="ghost" disabled={!!busy} onClick={() => void browse(draft.kind as 'folder' | 'wiki', parent)}>刷新当前目录</Button></div></div>
                {items.map(item => <div key={`${item.folder_token}:${item.space_id}:${item.node_token}`} className="flex min-w-0 items-center justify-between gap-2 border-b py-2"><span className="min-w-0 truncate text-sm" title={item.name}>{item.name}</span><div className="flex shrink-0 gap-1">
                  {(item.kind === 'folder' && item.folder_token || item.kind === 'wiki' && item.space_id && item.node_token) && <Button size="sm" variant="outline" disabled={!!busy} aria-label={`选择${item.name}`} onClick={() => editDraft(item.kind === 'folder' ? { kind: 'folder', folder_token: item.folder_token! } : { kind: 'wiki', space_id: item.space_id!, node_token: item.node_token! }, item.name)}>选择</Button>}
                  <Button size="sm" variant="ghost" disabled={!!busy || item.has_child === false} aria-label={`进入${item.name}`} onClick={() => void browse(item.kind, { name: item.name, scope: item.kind === 'folder' ? { folder_token: item.folder_token! } : { space_id: item.space_id!, ...(item.node_token ? { parent_node_token: item.node_token } : {}) } })}>进入<ChevronRight aria-hidden="true" data-icon="inline-end" /></Button>
                </div></div>)}
                {hasMore && <Button variant="outline" disabled={!!busy} onClick={() => void browse(draft.kind as 'folder' | 'wiki', parent, true)}>加载更多位置</Button>}
                {loaded && !items.length && !hasMore && !dialogError && !busy && <EmptyState title="此处没有可见位置" description="可返回上级浏览，或在高级设置填写已知位置标识。" />}
              </section>}
              {draft.kind !== 'personal' && <details open={advanced} onToggle={event => setAdvanced(event.currentTarget.open)} className="rounded-lg border p-3"><summary className="cursor-pointer text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">高级设置 · 手填位置标识</summary>
                {advanced && <FieldGroup className="mt-4"><FieldDescription>仅填写已知标识；确认时仍会重新核验位置与权限。</FieldDescription>
                  {draft.kind === 'folder' ? <Field><FieldLabel htmlFor="feishu-folder-token">文件夹标识</FieldLabel><Input id="feishu-folder-token" value={draft.folder_token} disabled={!!busy} onChange={event => editDraft({ kind: 'folder', folder_token: event.target.value.trim() })} /></Field> : <>
                    <Field><FieldLabel htmlFor="feishu-space-token">知识空间标识</FieldLabel><Input id="feishu-space-token" value={draft.space_id} disabled={!!busy} onChange={event => editDraft({ ...draft, space_id: event.target.value.trim() })} /></Field>
                    <Field><FieldLabel htmlFor="feishu-node-token">父节点标识</FieldLabel><Input id="feishu-node-token" value={draft.node_token} disabled={!!busy} onChange={event => editDraft({ ...draft, node_token: event.target.value.trim() })} /></Field>
                  </>}
                </FieldGroup>}
              </details>}
              {(capabilities?.folder === false || capabilities?.wiki === false) && <p className="text-sm text-muted-foreground">部分组织位置未开放访问，可先选个人云文档，或核对应用权限后重新授权。</p>}
              {busy && <p role="status" aria-live="polite" className="text-sm text-muted-foreground">{busy === 'check' ? '正在核验文档位置…' : '正在读取可见目录…'}</p>}
              {dialogError && <ErrorState error={dialogError} />}
            </div>
            <DialogFooter><Button variant="outline" onClick={close}>取消</Button><Button disabled={!!busy || !complete(draft) || !allowed(draft)} onClick={() => void verify(draft, true)}>{busy === 'check' ? '正在核验…' : '确认位置并核验'}</Button></DialogFooter>
          </DialogContent>
        </Dialog>
      </div><FieldDescription>组织位置沿用目标权限；浏览可见不代表可创建。</FieldDescription>
    </Field>
    {error && <ErrorState error={error} />}
    {(!autoCheck || !!error || !!check && !check.can_attempt_create) && <Button className="self-start" size="sm" variant="ghost" disabled={disabled || !!busy || !complete(value)} onClick={() => void verify(value, false)}>核验位置与权限</Button>}
    {busy === 'check' && !open && <p role="status" className="text-sm text-muted-foreground">正在核验文档位置…</p>}
    {check && (!autoCheck || !check.can_attempt_create) && <Alert variant={check.can_attempt_create ? 'default' : 'destructive'}><AlertDescription><p>{check.path_complete ? '完整路径：' : '已核验路径片段：'}{check.path.join(' / ') || check.name || '尚未确认'}</p><p>{check.can_create ? '已具备创建条件，提交时仍由飞书核验。' : check.can_attempt_create ? '目录可读，创建权限将在提交时核验。' : '当前目标不能提交创建。'}</p>{check.reason && <p>{typeof check.reason === 'string' ? check.reason : '目标权限未通过检查'}</p>}</AlertDescription></Alert>}
  </FieldGroup>;
}
