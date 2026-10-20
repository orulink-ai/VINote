import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Send } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { feishuStatus, disableDeviceAutomaticDelivery } from '@/lib/feishu'
import { createConnectorPluginStore, type ConnectorPluginState } from '@/lib/connectorPlugins'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Field, FieldLabel } from '@/components/ui/field'
import { ErrorState, LoadingState, EmptyState } from '@/components/Feedback/ResourceState'

const store = createConnectorPluginStore({ getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value) })
export function ConnectorPluginStore({ owner, returnTo }: { owner?: string; returnTo: string }) {
  const [accountVersion, setAccountVersion] = useState(0)
  const [tab, setTab] = useState('explore'), [search, setSearch] = useState('')
  const [saved, setSaved] = useState<ConnectorPluginState | null>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [authorization, setAuthorization] = useState<'loading' | 'connected' | 'none' | 'failed'>('loading')
  const authorizationEpoch = useRef(0)
  const failedSave = useRef<ConnectorPluginState | null>(null)
  const lifecycle = useRef({ active: false, epoch: 0, locked: false })
  const scope = lifecycle.current.epoch
  const current = () => lifecycle.current.active && lifecycle.current.epoch === scope && useAuthStore.getState().user?.id === owner
  async function read() {
    if (!owner || !current() || lifecycle.current.locked) return
    lifecycle.current.locked = true; setBusy(true); setError('')
    try { const value = await store.read(owner, current); if (current()) setSaved(value) }
    catch (cause) { if (current()) setError((cause as Error).message) }
    finally { if (current()) { lifecycle.current.locked = false; setBusy(false) } }
  }
  async function save(next: ConnectorPluginState) {
    if (!owner || !saved || !current() || lifecycle.current.locked) return
    lifecycle.current.locked = true; failedSave.current = next; setBusy(true); setError('')
    setMessage('')
    let stopped: { legacy: boolean } | undefined
    try {
      if (!next.installed || !next.enabled) {
        stopped = await disableDeviceAutomaticDelivery(owner)
        if (!current()) return
      }
      const value = await store.save(owner, next, current)
      if (current()) {
        setSaved(value); failedSave.current = null
        if (stopped) setMessage(stopped.legacy ? '插件状态已保存。当前服务未提供自动交付协议，未确认设备关闭接口。' : '新的设备自动交付已停止；服务已受理的原任务继续保留，飞书授权和已发布文档不变。')
      }
    }
    catch (cause) { if (current()) setError(!next.installed || !next.enabled
      ? `${stopped && !stopped.legacy ? '设备自动交付已停止，但插件状态未保存。' : '停用未完成，插件原状态保留。'}${cause instanceof Error ? cause.message : '请重试。'}`
      : '安装设置未能保存，原状态保留。请重试。') }
    finally { if (current()) { lifecycle.current.locked = false; setBusy(false) } }
  }
  async function readAuthorization() {
    const requestEpoch = ++authorizationEpoch.current
    setAuthorization('loading')
    try { const value = await feishuStatus(); if (current() && requestEpoch === authorizationEpoch.current) setAuthorization(value.connected ? 'connected' : 'none') }
    catch { if (current() && requestEpoch === authorizationEpoch.current) setAuthorization('failed') }
  }
  useEffect(() => {
    lifecycle.current.active = true
    lifecycle.current.locked = false; failedSave.current = null
    setSaved(null); setError(''); setMessage(''); setBusy(false)
    const unsubscribe = useAuthStore.subscribe((state, previous) => {
      if (state.user?.id !== previous.user?.id) { lifecycle.current.epoch++; setAccountVersion(value => value + 1) }
    })
    void read(); if (owner) void readAuthorization()
    return () => { lifecycle.current.active = false; unsubscribe() }
  }, [owner, accountVersion])
  const matches = '飞书 feishu 文档 发布 通知'.includes(search.trim().toLowerCase())
  const card = <article className="object-card grid gap-4">
    <div className="flex items-center gap-3"><span className="plugin-connection-icon"><Send aria-hidden="true" className="size-5" /></span><div className="flex-1"><h2 className="font-medium">飞书</h2><p className="text-sm text-muted-foreground">内置连接</p></div><Badge variant="secondary">{saved?.installed ? saved.enabled ? '已启用' : '已停用' : '未安装'}</Badge></div>
    <p className="text-sm leading-6 text-muted-foreground">将选定的会议纪要或笔记发布为飞书文档，管理阅读权限与消息通知。</p>
    <p className="text-sm text-muted-foreground">安装后可从详情发布文档，安装或启用本身不会开启自动交付。停用或卸载会先停止新的设备自动交付；服务已受理的原任务保留，不撤销飞书授权或删除文档。</p>
    <div className="flex flex-wrap gap-2">{saved?.installed ? <><Button variant="outline" disabled={busy} onClick={() => void save({ installed: true, enabled: !saved.enabled })}>{busy ? '正在保存…' : saved.enabled ? '停用' : '启用'}</Button><Button variant="outline" disabled={busy} onClick={() => void save({ installed: false, enabled: false })}>卸载</Button><Button variant="outline" asChild><Link to="/settings/feishu" state={{ returnTo }}>管理</Link></Button></> : <><Button disabled={!saved || busy} onClick={() => void save({ installed: true, enabled: true })}>{busy ? '正在保存…' : '安装'}</Button><Button variant="ghost" asChild><Link to="/settings/feishu" state={{ returnTo }}>管理授权</Link></Button></>}</div>
    {message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}
    {authorization === 'connected' && !saved?.installed && <p role="status" className="text-sm text-muted-foreground">已有飞书授权，可直接管理；商店模块尚未安装。</p>}
    {authorization === 'loading' && <p role="status" className="text-sm text-muted-foreground">正在核验已有授权…</p>}
    {authorization === 'failed' && <ErrorState error="已有授权暂时无法核验，可进入管理查看。" onRetry={() => void readAuthorization()} />}
  </article>
  return <section aria-label="插件商店" className="grid gap-4">
    <Tabs value={tab} onValueChange={setTab}><TabsList aria-label="插件商店分类"><TabsTrigger value="explore">探索</TabsTrigger><TabsTrigger value="installed">已安装</TabsTrigger></TabsList>
      <Field className="mt-4"><FieldLabel htmlFor="connector-search">搜索插件</FieldLabel><Input id="connector-search" type="search" placeholder="搜索名称或能力" value={search} onChange={event => setSearch(event.target.value)} /></Field>
      {error && <ErrorState error={error} busy={busy} onRetry={() => void (failedSave.current ? save(failedSave.current) : read())} />}
      {!owner ? <EmptyState title="请先登录" description="安装设置按此设备的账号保存。" /> : !saved ? !error && <LoadingState label="正在读取安装状态…" rows={1} /> : <>
        <TabsContent value="explore">{matches ? card : <EmptyState title="没有匹配的插件" description="试试飞书或清除搜索。"><Button variant="outline" onClick={() => setSearch('')}>清除搜索</Button></EmptyState>}</TabsContent>
        <TabsContent value="installed">{saved.installed && matches ? card : <EmptyState title={search ? '没有匹配的已安装插件' : '尚未安装插件'} description="到探索中安装飞书内置模块。"><Button variant="outline" onClick={() => { setSearch(''); setTab('explore') }}>返回探索</Button></EmptyState>}</TabsContent>
      </>}
    </Tabs>
  </section>
}
