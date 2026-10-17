import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { ArrowRight, Plug } from 'lucide-react'
import { ConnectorPluginStore } from '@/components/Plugins/ConnectorPluginStore'
import { PageHeading } from '@/components/Layout/PageHeading'
import { PageReturn } from '@/components/Layout/PageReturn'
import { useAuthStore } from '@/stores/authStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { pluginCatalog, pluginSetting, pluginRuns, pluginRun, previewPlugin, retryPlugin, savePlugin, pluginRunLabel, type ContentPlugin, type PluginRun } from '@/lib/contentPlugins'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Field, FieldLabel } from '@/components/ui/field'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { LoadingState, ErrorState, EmptyState } from '@/components/Feedback/ResourceState'
import { MarkdownContent } from '@/components/Markdown/MarkdownContent'
import { canRetryContentPluginRun, readContentPluginReceipts, rememberContentPluginRun, writeContentPluginReceipt, type ContentPluginReceipt, type ContentPluginRequest, type RecoverablePluginRun } from '@/lib/contentPluginRecovery'
import { resolvePageParent, pageParentLabel } from '@/lib/navigation'
import type { WorkspaceNote } from '@/lib/workspace'

const pluginNames: Record<string, string> = { translation: '全文翻译', diagram: '流程图整理', actions: '行动项整理', glossary: '术语校对' }
const languageNames: Record<string, string> = { en: '英语', zh: '简体中文', ja: '日语（历史处理）', de: '德语（历史处理）' }
const languageLabel = (value: string) => languageNames[value] || (value ? `历史语言（${value}）` : '目标语言待核验')
const pluginFallback = (id: string): ContentPlugin => ({ id, name: pluginNames[id] || '内容处理', description: '', option: id === 'translation' ? 'language' : id === 'glossary' ? 'glossary' : 'none', installed: false, enabled: false })

export function Connections() {
  const owner = useAuthStore(s => s.user?.id)
  const workspace = useWorkspaceStore()
  const [params] = useSearchParams()
  const location = useLocation()
  const returnTo = resolvePageParent(location.state?.returnTo, '/connections')
  const [catalog, setCatalog] = useState<ContentPlugin[]>([])
  const [runs, setRuns] = useState<PluginRun[]>([])
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [selected, setSelected] = useState<ContentPlugin | null>(null)
  const [noteKey, setNoteKey] = useState(''), [note, setNote] = useState<WorkspaceNote | null>(null), [versionId, setVersionId] = useState('')
  const [language, setLanguage] = useState('en'), [glossary, setGlossary] = useState('')
  const [run, setRun] = useState<RecoverablePluginRun | null>(null), [request, setRequest] = useState<ContentPluginRequest | null>(null), [taskError, setTaskError] = useState('')
  const [receipts, setReceipts] = useState<ContentPluginReceipt[]>([]), [recoveryError, setRecoveryError] = useState('')
  const [phase, setPhase] = useState<ContentPluginReceipt['phase']>('submitted')
  const [lookupOperation, setLookupOperation] = useState('')
  const [comparison, setComparison] = useState<'source' | 'result'>('result')
  const [viewOwner, setViewOwner] = useState(owner)
  const sourceEpoch = useRef(0)
  const viewEpoch = useRef(0), mounted = useRef(true)
  const accountScope = useRef({ owner, epoch: 0 })
  if (accountScope.current.owner !== owner) accountScope.current = { owner, epoch: accountScope.current.epoch + 1 }
  const epoch = accountScope.current.epoch
  const action = useRef({ active: false, id: 0 })
  const currentOwner = () => mounted.current && accountScope.current.epoch === epoch && useAuthStore.getState().user?.id === owner
  const operation = request?.operation_id || run?.id || lookupOperation
  const refreshReceipts = () => {
    if (!owner || !currentOwner()) return []
    const saved = readContentPluginReceipts(owner)
    setReceipts(saved); setRecoveryError('')
    return saved
  }
  const persist = (value: ContentPluginReceipt) => {
    if (!owner || !currentOwner()) throw new Error('账号已变化，请返回当前账号的处理记录。')
    writeContentPluginReceipt(owner, value)
    refreshReceipts()
    setPhase(value.phase)
  }
  const load = async () => {
    setLoading(true); setError('')
    const result = await Promise.allSettled([pluginCatalog(), pluginRuns()])
    if (!currentOwner()) return
    if (result[0].status === 'fulfilled') setCatalog(result[0].value.filter(item => item.id !== 'translation'))
    if (result[1].status === 'fulfilled') setRuns(result[1].value)
    if (result.some(item => item.status === 'rejected')) setError('无法读取插件或运行记录，请重新加载。已有内容继续保留。')
    setLoading(false)
  }
  const acceptRun = (result: RecoverablePluginRun, expectedId: string, visibleEpoch: number) => {
    if (!owner || !currentOwner()) return
    if (result.id !== expectedId) throw new Error('运行回执不属于本次处理，请保留原记录并查询。')
    const saved = rememberContentPluginRun(owner, result)
    refreshReceipts()
    if (viewEpoch.current !== visibleEpoch) return
    setRun(result); setRequest(saved.request); setPhase(saved.phase)
    setNoteKey(result.note_key); setVersionId(saved.request.version_id); setLanguage(saved.request.language)
  }
  const resume = async (id: string, saved?: ContentPluginReceipt, hint?: PluginRun) => {
    const visibleEpoch = ++viewEpoch.current
    setRun(null); setRequest(saved?.request || null); setLookupOperation(id); setNote(null); setVersionId(saved?.request.version_id || '')
    setPhase(saved?.phase || 'submitted'); setTaskError(''); setComparison('result')
    if (saved) { setSelected(catalog.find(item => item.id === saved.request.plugin_id) || pluginFallback(saved.request.plugin_id)); setNoteKey(saved.request.note_key); setLanguage(saved.request.language) }
    else if (hint) { setSelected(catalog.find(item => item.id === hint.plugin_id) || pluginFallback(hint.plugin_id)); setNoteKey(hint.note_key) }
    const result: RecoverablePluginRun = await pluginRun(id)
    if (!currentOwner() || viewEpoch.current !== visibleEpoch) return
    setSelected(catalog.find(item => item.id === result.plugin_id) || pluginFallback(result.plugin_id))
    acceptRun(result, id, visibleEpoch)
  }
  useEffect(() => {
    mounted.current = true
    const unsubscribe = useAuthStore.subscribe((state, previous) => {
      if (state.user?.id !== previous.user?.id) {
        accountScope.current.epoch++; sourceEpoch.current++; viewEpoch.current++
      }
    })
    return () => { mounted.current = false; unsubscribe() }
  }, [])
  useEffect(() => {
    action.current = { active: false, id: action.current.id + 1 }
    sourceEpoch.current++; viewEpoch.current++
    setViewOwner(owner); setCatalog([]); setRuns([]); setSelected(null); setRun(null); setRequest(null); setLookupOperation('')
    setNote(null); setNoteKey(''); setVersionId(''); setTaskError(''); setBusy(false); setReceipts([]); setRecoveryError('')
    void load()
    if (!owner) return
    try {
      const saved = refreshReceipts().find(item => item.phase !== 'saved' && (!params.get('note') || item.request.note_key === params.get('note')))
      if (saved) void act(() => resume(saved.request.operation_id, saved), true)
    } catch (cause) { setRecoveryError((cause as Error).message) }
  }, [owner])
  useEffect(() => {
    const epoch = ++sourceEpoch.current
    setNote(null)
    if (noteKey && selected && workspace.owner === owner) void workspace.loadDetail(noteKey, true).then(value => {
      if (epoch !== sourceEpoch.current || !currentOwner()) return
      setNote(value)
      if (!request) setVersionId(params.get('version') && value.versions.some(item => item.id === params.get('version')) ? params.get('version')! : String(value.metadata.default_version_id || value.versions[0]?.id || ''))
    }).catch(cause => { if (epoch === sourceEpoch.current && currentOwner()) setTaskError((cause as Error).message) })
  }, [noteKey, owner, workspace.owner, !!selected])
  const act = async (work: () => Promise<void>, task = false) => {
    if (!currentOwner() || action.current.active) return
    const id = ++action.current.id
    action.current.active = true
    setBusy(true); task ? setTaskError('') : setError('')
    try { await work() } catch (cause) { if (currentOwner()) (task ? setTaskError : setError)((cause as Error).message) }
    finally { if (currentOwner() && action.current.id === id) { action.current.active = false; setBusy(false) } }
  }
  const fresh = (plugin: ContentPlugin) => { viewEpoch.current++; sourceEpoch.current++; setSelected(plugin); setRun(null); setRequest(null); setLookupOperation(''); setPhase('submitted'); setTaskError(''); setNote(null); setVersionId(''); setNoteKey(params.get('note') || ''); setLanguage('en'); setGlossary(''); setComparison('result') }
  const open = (plugin: ContentPlugin) => {
    try {
      const saved = refreshReceipts().find(item => item.request.plugin_id === plugin.id && item.phase !== 'saved' && (!params.get('note') || item.request.note_key === params.get('note')))
      if (saved) void act(() => resume(saved.request.operation_id, saved), true)
      else fresh(plugin)
    } catch (cause) { setRecoveryError((cause as Error).message) }
  }
  const close = () => { viewEpoch.current++; sourceEpoch.current++; setSelected(null) }
  const sourceVersion = note?.versions.find(item => item.id === (run?.source_version_id || request?.version_id || versionId))
  const sourceContent = run?.source_content ?? sourceVersion?.content
  const sourceVerified = typeof run?.source_content === 'string' && !!run.source_content.trim() && !!run.source_version_id
  const pending = workspace.owner === owner && workspace.pending.some(item => item.key === noteKey)
  const activePlugin = catalog.find(item => item.id === selected?.id)
  const visibleRun = viewOwner === owner ? run : null
  const visibleSelected = viewOwner === owner ? selected : null
  const availableNotes = workspace.owner === owner ? workspace.items : []
  if (viewOwner !== owner) return <div className="workspace-page"><LoadingState label="正在读取当前账号的插件…" /></div>
  return <div className="workspace-page plugins-page max-w-4xl">
    {returnTo !== '/connections' && <PageReturn to={returnTo} label={pageParentLabel(returnTo)} />}
    <PageHeading title="插件" description="探索内置插件，管理已安装的能力与工具连接。" />
    <ConnectorPluginStore key={owner} owner={owner} returnTo={location.pathname + location.search} />
    <section aria-label="工具连接管理" className="grid gap-4 sm:grid-cols-2">
      {[
        { to: '/settings/mcp' + (params.get('note') ? '?mode=translation&note=' + encodeURIComponent(params.get('note')!) + (params.get('version') ? '&version=' + encodeURIComponent(params.get('version')!) : '') : ''), title: 'MCP 工具', icon: Plug, tag: '可选扩展', description: '管理翻译、任务创建和知识库检索等远程工具连接，逐项授权。外部写入先预览并确认。' },
      ].map(item => <Link key={item.to} to={item.to} state={{ returnTo }} className="object-card plugin-connection">
        <span className="plugin-connection-icon"><item.icon aria-hidden="true" className="size-[18px]" /></span>
        <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-x-3 gap-y-1"><h2 className="text-[15px] font-medium">{item.title}</h2><span className="text-[11px] text-muted-foreground">{item.tag}</span></div><p className="mt-2 text-[13px] leading-[22px] text-muted-foreground">{item.description}</p></div>
        <ArrowRight className="mt-1 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </Link>)}
    </section>
    <section aria-labelledby="content-plugin-heading" className="grid gap-4">
      <h2 id="content-plugin-heading" className="text-[15px] font-medium">内容处理插件</h2>
      <p className="text-[13px] leading-[22px] text-muted-foreground">使用你当前选择的文字模型，只读取本次选定版本。生成结果先预览，不自动改写原文。</p>
      {error && <ErrorState error={error} onRetry={() => void load()} busy={busy || loading} />}
      {recoveryError && <ErrorState error={recoveryError} onRetry={() => { try { refreshReceipts() } catch (cause) { setRecoveryError((cause as Error).message) } }} busy={busy} />}
      {loading && !catalog.length && <LoadingState label="正在读取插件…" />}
      <div className="grid gap-3 sm:grid-cols-2">{catalog.filter(plugin => plugin.id !== 'translation' && plugin.id !== 'diagram').map(plugin => <article key={plugin.id} className="plugin-content-card">
        <div className="flex items-center justify-between gap-3"><h3 className="text-sm font-medium">{pluginNames[plugin.id] || plugin.name}</h3><Badge variant="secondary">{plugin.installed ? plugin.enabled ? '已启用' : '已停用' : '内置扩展'}</Badge></div>
        <p className="flex-1 text-[13px] leading-[22px] text-muted-foreground">{plugin.description}</p>
        <div className="flex items-center justify-between gap-2">{plugin.installed ? <><Switch aria-label={`启用${pluginNames[plugin.id] || plugin.name}`} checked={plugin.enabled} disabled={busy} onCheckedChange={enabled => void act(async () => { const next = await pluginSetting(plugin.id, true, enabled); if (currentOwner()) setCatalog(next) })} /><Button variant="outline" disabled={busy || !plugin.enabled} onClick={() => open(plugin)}>选择内容</Button><Button variant="ghost" disabled={busy} onClick={() => void act(async () => { const next = await pluginSetting(plugin.id, false); if (currentOwner()) setCatalog(next) })}>移除</Button></> : <Button variant="outline" disabled={busy} onClick={() => void act(async () => { const next = await pluginSetting(plugin.id, true); if (currentOwner()) setCatalog(next) })}>添加插件</Button>}</div>
      </article>)}</div>
    </section>
    {viewOwner === owner && receipts.some(item => item.phase !== 'saved') && <section className="grid gap-3 border-t pt-5" aria-label="本机处理恢复"><h2 className="font-medium">继续本次处理</h2><p className="text-sm text-muted-foreground">原请求已保留。先查询处理结果，不会重新提交生成。</p>{receipts.filter(item => item.phase !== 'saved').map(item => <Button key={item.request.operation_id} variant="outline" className="h-auto min-h-11 justify-start whitespace-normal text-left" disabled={busy} onClick={() => void act(() => resume(item.request.operation_id, item), true)}>继续{pluginNames[item.request.plugin_id]} · {availableNotes.find(note => note.key === item.request.note_key)?.title || '已保存内容'}</Button>)}</section>}
    <section className="grid gap-3 border-t pt-5" aria-label="插件运行记录"><h2 className="font-medium">最近处理</h2>{!runs.length && !loading && <p className="text-sm text-muted-foreground">还没有处理记录。添加插件后选择一份已保存的纪要或笔记。</p>}{runs.map(item => <button type="button" key={item.id} disabled={busy} className="flex items-center justify-between gap-3 rounded-lg border p-3 text-left text-sm hover:bg-muted focus-visible:outline focus-visible:outline-ring" onClick={() => void act(() => resume(item.id, receipts.find(saved => saved.request.operation_id === item.id), item), true)}><span>{pluginNames[item.plugin_id] || '内容处理'} · {availableNotes.find(note => note.key === item.note_key)?.title || '已保存内容'}</span><Badge variant="secondary">{pluginRunLabel(item.status)}</Badge></button>)}</section>
    <section className="border-t pt-6 text-sm leading-7 text-muted-foreground"><h2 className="font-medium text-foreground">交付与恢复</h2><p>从内容详情选择已保存的版本再发布或调用工具。授权失效可重新连接；文档、权限与消息各自记录状态。结果不确定时先查询原任务。</p></section>
    <Dialog open={!!visibleSelected} onOpenChange={value => { if (!value) close() }}><DialogContent className="max-h-[85vh] overflow-auto sm:max-w-4xl"><DialogHeader><DialogTitle>{selected ? pluginNames[selected.id] || selected.name : '内容处理'}</DialogTitle><DialogDescription>选择完整已保存版本，生成预览后核对。关闭仅离开查看，原处理记录保留；原始音视频不会发送给插件。</DialogDescription></DialogHeader>
      {selected?.id === 'translation' && <p className="text-sm text-muted-foreground">这是历史内置翻译，只读核验。新的中英翻译请连接远程 MCP 工具。<Link className="ml-1 underline" to={'/settings/mcp?mode=translation&note=' + encodeURIComponent(noteKey) + '&version=' + encodeURIComponent(versionId)}>使用 MCP 翻译</Link></p>}
      {taskError && <ErrorState error={taskError} />}
      {selected?.id === 'diagram' && <p role="status" className="text-sm text-muted-foreground">流程图新生成已停止。历史记录与已有结果保留，可查询原运行。</p>}
      {!visibleRun && selected?.id !== 'diagram' && <div className="grid gap-4"><Field><FieldLabel htmlFor="plugin-note">处理哪份内容</FieldLabel><NativeSelect id="plugin-note" value={noteKey} disabled={busy || !!operation} onChange={event => { setNoteKey(event.target.value); setVersionId(''); setTaskError('') }}><NativeSelectOption value="">请选择</NativeSelectOption>{availableNotes.filter(item => !item.deleted).map(item => <NativeSelectOption key={item.key} value={item.key}>{item.title}</NativeSelectOption>)}</NativeSelect></Field>
        {note && <Field><FieldLabel htmlFor="plugin-version">源版本</FieldLabel><NativeSelect id="plugin-version" value={versionId} disabled={busy || !!operation} onChange={event => setVersionId(event.target.value)}>{note.versions.map((version, index) => <NativeSelectOption key={version.id} value={version.id}>{version.title} · {new Date(version.created_at).toLocaleString()} · {index + 1}</NativeSelectOption>)}</NativeSelect></Field>}
        {selected?.option === 'language' && <Field><FieldLabel htmlFor="plugin-language">目标语言</FieldLabel><NativeSelect id="plugin-language" value={language} disabled={busy || !!operation} onChange={event => setLanguage(event.target.value)}>{[['en', '英语'], ['zh', '简体中文']].map(([value, label]) => <NativeSelectOption key={value} value={value}>{label}</NativeSelectOption>)}{operation && !['en', 'zh'].includes(language) && <NativeSelectOption value={language}>{languageLabel(language)}</NativeSelectOption>}</NativeSelect></Field>}
        {selected?.option === 'glossary' && <Field><FieldLabel htmlFor="plugin-glossary">术语对照（每行：原词 → 正确词）</FieldLabel><Textarea id="plugin-glossary" value={request?.glossary ?? glossary} maxLength={4000} disabled={busy || !!operation} onChange={event => setGlossary(event.target.value)} /></Field>}
        {!availableNotes.some(item => !item.deleted) && <EmptyState title="没有可处理的内容" description="先保存一份纪要或笔记，再使用插件。" />}
        {pending && <p role="status" className="text-sm text-muted-foreground">这份内容的已保存版本尚不可读取。正文与输入保留，请重新读取内容后再选择版本。</p>}
        {sourceVersion && (sourceVersion.content.length > 60000 || !sourceVersion.content.trim()) && <p role="alert">请选择有文字且不超过 60000 字符的完整版本，不会截断处理。</p>}
        <p className="text-sm text-muted-foreground">处理完整已保存版本，最多 60000 字符。结果先预览，取消不修改正文。</p>
        <Button disabled={busy || !!recoveryError || !owner || workspace.owner !== owner || !note || note.deleted || !sourceVersion?.content.trim() || sourceVersion.content.length > 60000 || pending || !!operation || (selected?.id === 'translation' || selected?.id === 'diagram') || !activePlugin?.installed || !activePlugin.enabled || (selected?.option === 'glossary' && !glossary.trim())} onClick={() => void act(async () => {
          if (!owner || !note || !selected || (selected.id === 'translation' || selected.id === 'diagram') || !sourceVersion) return
          const body: ContentPluginRequest = { plugin_id: selected.id, note_key: note.key, version_id: sourceVersion.id, base_revision: note.revision, operation_id: crypto.randomUUID(), language, glossary }
          persist({ request: body, phase: 'submitted', created_at: new Date().toISOString() })
          setRequest(body)
          const visibleEpoch = viewEpoch.current
          const result = await previewPlugin(body)
          if (currentOwner()) { acceptRun(result, body.operation_id, visibleEpoch); await load() }
        }, true)}>{operation ? '原处理待核验' : busy ? '正在生成预览…' : '生成预览'}</Button>
      </div>}
      {operation && <Button variant="outline" disabled={busy} onClick={() => void act(async () => {
        const visibleEpoch = viewEpoch.current
        const result = await pluginRun(operation)
        if (currentOwner()) acceptRun(result, operation, visibleEpoch)
      }, true)}>查询本次处理结果</Button>}
      {operation && (!visibleRun || phase === 'saving' || phase === 'submitted') && <p role="status" className="text-sm text-muted-foreground">处理结果尚未确认，原请求与源版本已保留。请查询原运行，不会重新提交。</p>}
      {visibleRun && <div className="grid gap-4"><Badge className="w-fit" variant="secondary" role="status">{phase === 'saving' ? '保存待核验' : phase === 'submitted' ? '处理待核验' : pluginRunLabel(visibleRun.status)}</Badge><p className="text-sm text-muted-foreground">{visibleRun.source_title || note?.title || '已保存内容'} · {sourceVersion ? `${sourceVersion.title} · ${new Date(sourceVersion.created_at).toLocaleString()}` : '已固定的源版本'}{selected?.id === 'translation' && ` → ${languageLabel(visibleRun.language || request?.language || '')}`} · {visibleRun.model || '当前文字模型'}</p>{visibleRun.error && <p className="text-sm text-destructive" role="alert">{visibleRun.error}</p>}
        {visibleRun.output && <>
          <div className="flex gap-2 md:hidden" role="group" aria-label="核对原文与结果"><Button variant={comparison === 'source' ? 'secondary' : 'outline'} aria-pressed={comparison === 'source'} onClick={() => setComparison('source')}>原文</Button><Button variant={comparison === 'result' ? 'secondary' : 'outline'} aria-pressed={comparison === 'result'} onClick={() => setComparison('result')}>{selected?.id === 'translation' ? '译文' : '结果'}</Button></div>
          <div className="grid min-w-0 gap-4 md:grid-cols-2">
            <section aria-label="源版本原文" className={`min-w-0 rounded-xl border p-4 ${comparison === 'source' ? 'block' : 'hidden md:block'}`}><h3 className="mb-3 text-sm font-medium">原文（源版本）</h3><div className="max-h-96 overflow-auto">{sourceContent !== undefined ? <MarkdownContent content={sourceContent} /> : <p role="status" className="text-sm text-muted-foreground">源版本尚未读取，请查询原运行。不会使用当前正文代替。</p>}</div></section>
            <section aria-label={selected?.id === 'translation' ? '译文预览' : '处理结果预览'} className={`min-w-0 rounded-xl border p-4 ${comparison === 'result' ? 'block' : 'hidden md:block'}`}><h3 className="mb-3 text-sm font-medium">{selected?.id === 'translation' ? `译文（${languageLabel(visibleRun.language || language)}）` : '处理结果'}</h3><div className="max-h-96 overflow-auto"><MarkdownContent content={visibleRun.output} /></div></section>
          </div>
        </>}
        {visibleRun.plugin_id !== 'diagram' && ['failed', 'interrupted'].includes(visibleRun.status) && <><Button disabled={busy || !['failed', 'interrupted'].includes(phase) || (visibleRun.plugin_id === 'translation' || visibleRun.plugin_id === 'diagram' || !canRetryContentPluginRun(visibleRun))} onClick={() => void act(async () => {
          if (!owner || !request || !['failed', 'interrupted'].includes(phase) || !canRetryContentPluginRun(visibleRun)) return
          persist({ request, phase: 'submitted', created_at: receipts.find(item => item.request.operation_id === operation)?.created_at || new Date().toISOString() })
          const visibleEpoch = viewEpoch.current
          const result = await retryPlugin(visibleRun.id)
          if (currentOwner()) { acceptRun(result, visibleRun.id, visibleEpoch); await load() }
        }, true)}>重试生成预览</Button>{((visibleRun.plugin_id === 'translation' || visibleRun.plugin_id === 'diagram' || !canRetryContentPluginRun(visibleRun)) || !['failed', 'interrupted'].includes(phase)) && <p role="status" className="text-sm text-muted-foreground">处理待核验，当前尚不能安全重试。请查询原运行，原文保留。</p>}</>}
        {visibleRun.status === 'ready' && visibleRun.plugin_id !== 'translation' && <><p className="text-sm text-muted-foreground">保存后作为当前版本，原文保留在源版本中；不会发布到飞书或发送通知。</p><Button disabled={busy || phase === 'saving' || !sourceVerified || pending} onClick={() => void act(async () => {
          if (!owner || !request) return
          persist({ request, phase: 'saving', created_at: receipts.find(item => item.request.operation_id === operation)?.created_at || new Date().toISOString() })
          const visibleEpoch = viewEpoch.current
          const savedNote = await savePlugin(visibleRun.id)
          if (!currentOwner()) return
          if (!savedNote || savedNote.key !== visibleRun.note_key || savedNote.revision <= visibleRun.base_revision) throw new Error('保存回执尚未核验，请查询原运行。')
          const saved = { ...visibleRun, status: 'saved', retry_safe: false }
          acceptRun(saved, visibleRun.id, visibleEpoch)
          if (viewEpoch.current === visibleEpoch) setNote(savedNote)
          await load()
        }, true)}>{busy && phase === 'saving' ? '正在保存…' : '核对无误，保存为新版本'}</Button>{!sourceVerified && <p role="status" className="text-sm text-muted-foreground">源版本尚未核验，请查询本次处理再保存。</p>}</>}
        {visibleRun.status === 'saved' && <><p role="status">新版本已保存，原文版本保留。</p><Button asChild><Link to={'/workspace/' + encodeURIComponent(visibleRun.note_key)} state={{ returnTo: '/connections' }}>查看新版本</Link></Button></>}
        {visibleRun.plugin_id !== 'translation' && visibleRun.plugin_id !== 'diagram' && ['ready', 'saved'].includes(visibleRun.status) && phase !== 'saving' && <Button variant="outline" disabled={busy} onClick={() => { if (selected) { fresh(selected); if (noteKey) { setNoteKey(noteKey); setNote(note); setVersionId(String(note?.metadata.default_version_id || note?.versions[0]?.id || '')) } } }}>另选内容</Button>}
      </div>}
      <Button variant="ghost" onClick={close}>关闭预览</Button>
    </DialogContent></Dialog>
  </div>
}
