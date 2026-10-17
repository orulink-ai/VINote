import { useEffect, useState } from 'react'
import { apiJson } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from '@/components/ui/alert-dialog'

type Application = { custom: boolean; app_id: string; redirect_uri: string; tenant_key: string; document_domain: string }
export function FeishuApplicationSetup({ onChanged }: { onChanged: () => void }) {
  const [app, setApp] = useState<Application | null>(null)
  const [advanced, setAdvanced] = useState(false)
  const [editing, setEditing] = useState(false), [busy, setBusy] = useState(false), [clear, setClear] = useState(false)
  const [secret, setSecret] = useState(''), [error, setError] = useState('')
  const load = async () => {
    setError(''); setBusy(true)
    try { setApp(await apiJson<Application>('/api/feishu/application')) }
    catch (cause) { setError((cause as Error).message) }
    finally { setBusy(false) }
  }
  useEffect(() => { void load() }, [])
  const save = async () => {
    if (!app) return
    setBusy(true); setError('')
    try {
      setApp(await apiJson<Application>('/api/feishu/application', { method: 'PUT', body: JSON.stringify({ app_id: app.app_id, app_secret: secret, tenant_key: app.tenant_key, document_domain: app.document_domain }) }))
      setSecret(''); setEditing(false); onChanged()
    } catch (cause) { setError((cause as Error).message) }
    finally { setBusy(false) }
  }
  if (!advanced) return <section aria-label="飞书应用管理" className="flex items-center justify-between gap-4 rounded-2xl border bg-card p-5"><div><h2 className="font-medium">应用管理</h2><p className="mt-1 text-sm text-muted-foreground">配置、更换或清理应用凭证；日常使用无需调整。</p></div><Button variant="ghost" aria-expanded={false} onClick={() => setAdvanced(true)}>管理</Button></section>
  return <section aria-label="飞书应用配置" className="rounded-2xl border bg-card p-5 space-y-4">
    <Button variant="ghost" aria-expanded={true} onClick={() => setAdvanced(false)}>收起应用管理</Button>
    <div><h2 className="font-medium">选择接入方式</h2><p className="mt-2 text-sm text-muted-foreground">公司已接入：直接在下方授权账号。使用自己的企业应用：配置一次，再授权。新应用需在飞书完成审核发布。</p></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}<Button variant="ghost" disabled={busy} onClick={() => void load()}>重新读取配置</Button></p>}
    <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy || !app} onClick={() => setEditing(!editing)}>{editing ? '收起应用配置' : app?.custom ? '更换应用凭证' : '选择已有企业应用'}</Button><a className="inline-flex items-center text-sm underline underline-offset-4" href="https://open.feishu.cn/app" target="_blank" rel="noreferrer">打开飞书应用后台</a>{app?.custom && <Button variant="ghost" disabled={busy} onClick={() => setClear(true)}>清理应用凭证</Button>}</div>
    {editing && app && <div className="grid gap-4 border-t pt-4">
      <p className="text-sm text-muted-foreground">在飞书后台设置回调地址：<span className="break-all select-all">{app.redirect_uri || '服务端尚未配置回调'}</span>。启用机器人，开通文档及消息权限，并发布给本公司成员。</p>
      {(['app_id', 'tenant_key', 'document_domain'] as const).map(key => <div key={key} className="grid gap-2"><Label htmlFor={`feishu-${key}`}>{({ app_id: 'App ID', tenant_key: '公司 Tenant Key', document_domain: '云文档域名' })[key]}</Label><Input id={`feishu-${key}`} disabled={busy} value={app[key]} onChange={event => setApp({ ...app, [key]: event.target.value.trim() })} /></div>)}
      <div className="grid gap-2"><Label htmlFor="feishu-secret">App Secret</Label><Input id="feishu-secret" type="password" autoComplete="off" disabled={busy} value={secret} onChange={event => setSecret(event.target.value)} /></div>
      <p className="text-xs text-muted-foreground">只通过 HTTPS 提交并在服务端加密保存，不写入笔记或浏览器存储。更换后需要重新授权，原飞书文档保留。</p>
      <Button disabled={busy || !secret || !app.app_id || !app.tenant_key || !app.document_domain} onClick={() => void save()}>{busy ? '正在验证应用…' : '验证并保存应用'}</Button>
    </div>}
    <AlertDialog open={clear} onOpenChange={setClear}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>清理应用凭证？</AlertDialogTitle><AlertDialogDescription>删除 VINote 保存的应用密钥和账号授权，停止后续交付；已创建文档保留。公司默认应用如已配置，仍可重新授权。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={async () => { setBusy(true); try { await apiJson('/api/feishu/application', { method: 'DELETE' }); setSecret(''); setEditing(false); await load(); onChanged() } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) } }}>清理凭证</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </section>
}
